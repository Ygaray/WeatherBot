"""Tests for the classified self-check engine (OPS-02, D-03/D-06).

``run_self_check`` reuses ``do_check``'s validate+probe steps but returns a
classified :class:`CheckResult` (``online`` / ``network_not_ready`` / ``auth_failed``)
instead of a print-budget + exit code, so the daemon's re-probe loop (Plan 05-02)
and the durable health row can branch on the outcome. Classification reuses the
Phase-4 ``is_transient`` / ``is_auth_failure`` classifiers; ``detail`` is
outcome-only (status code / exception class name), never a secret (T-04-01).
"""

from __future__ import annotations

import httpx
import pytest

from yahir_reusable_bot.lifecycle import Severity

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.ops import (
    AUTH_FAILED,
    NETWORK_NOT_READY,
    PASS,
    CheckResult,
    run_self_check,
    to_health_result,
)

# CONFIG_INVALID is added to weatherbot.ops in plan 29-03. Guard the import so this
# file still COLLECTS pre-29-03 — the dependent cases are xfail until the symbol and
# the pre-probe config classification split land. A sentinel string keeps the
# parametrize tables buildable at collection time.
try:  # pragma: no cover - import shim; the real symbol lands in 29-03
    from weatherbot.ops import CONFIG_INVALID

    _CONFIG_INVALID_PRESENT = True
except ImportError:  # pragma: no cover - pre-29-03 collection path
    CONFIG_INVALID = "config_invalid"
    _CONFIG_INVALID_PRESENT = False

_needs_config_invalid = pytest.mark.xfail(
    not _CONFIG_INVALID_PRESENT,
    strict=False,
    reason="CONFIG_INVALID classifier + CRITICAL map land in 29-03",
)


def _config(template="briefing-sectioned.txt"):
    return Config(
        locations=[
            Location(
                name="New York",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
            )
        ],
        template=template,
        webhook=WebhookIdentity(),
    )


class _OkClient:
    """A probe that succeeds (returns a payload)."""

    def __init__(self, load_fixture):
        self._imp = load_fixture("onecall_imperial_clear.json")
        self.onecall_calls: list[str] = []

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._imp


class _RaisingClient:
    """A probe that raises a supplied exception."""

    def __init__(self, exc):
        self._exc = exc
        self.onecall_calls: list[str] = []

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        raise self._exc


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/onecall")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


def test_pass_returns_online(load_fixture):
    """A clean probe -> CheckResult(ok=True, reason='online')."""
    client = _OkClient(load_fixture)
    result = run_self_check(config=_config(), client=client)
    assert isinstance(result, CheckResult)
    assert result.ok is True
    assert result.reason == PASS == "online"
    # EXACTLY one reachability probe (imperial) — not the 2-call send round.
    assert client.onecall_calls == ["imperial"]


def test_transient_connect_error_is_network_not_ready():
    """A ConnectError -> network_not_ready, detail is the exception class name."""
    client = _RaisingClient(httpx.ConnectError("boom"))
    result = run_self_check(config=_config(), client=client)
    assert result.ok is False
    assert result.reason == NETWORK_NOT_READY == "network_not_ready"
    assert result.detail == "ConnectError"


def test_transient_timeout_is_network_not_ready():
    """A TimeoutException -> network_not_ready."""
    client = _RaisingClient(httpx.TimeoutException("slow"))
    result = run_self_check(config=_config(), client=client)
    assert result.ok is False
    assert result.reason == NETWORK_NOT_READY


def test_auth_401_is_auth_failed():
    """A 401 HTTPStatusError -> auth_failed, detail='401'."""
    client = _RaisingClient(_http_status_error(401))
    result = run_self_check(config=_config(), client=client)
    assert result.ok is False
    assert result.reason == AUTH_FAILED == "auth_failed"
    assert result.detail == "401"


def test_auth_403_is_auth_failed():
    """A 403 HTTPStatusError -> auth_failed, detail='403'."""
    client = _RaisingClient(_http_status_error(403))
    result = run_self_check(config=_config(), client=client)
    assert result.ok is False
    assert result.reason == AUTH_FAILED
    assert result.detail == "403"


def test_5xx_is_network_not_ready_not_auth():
    """A 503 HTTPStatusError is transient -> network_not_ready, NOT auth_failed."""
    client = _RaisingClient(_http_status_error(503))
    result = run_self_check(config=_config(), client=client)
    assert result.ok is False
    assert result.reason == NETWORK_NOT_READY


def test_429_is_network_not_ready():
    """A 429 HTTPStatusError is transient -> network_not_ready."""
    client = _RaisingClient(_http_status_error(429))
    result = run_self_check(config=_config(), client=client)
    assert result.ok is False
    assert result.reason == NETWORK_NOT_READY


def test_detail_never_carries_a_secret():
    """T-04-01: the CheckResult.detail is outcome-only, never a key/URL."""
    client = _RaisingClient(_http_status_error(401))
    result = run_self_check(config=_config(), client=client)
    assert "appid" not in result.detail
    assert "api.openweathermap.org" not in result.detail


# --- HARD-STARTUP-02: CONFIG_INVALID classification + severity map (Wave 0) ---
# Defense-in-depth for F05/F06: a config/template/empty-locations error caught at the
# self-check boundary must classify as CONFIG_INVALID (a distinct FATAL outcome), not
# be swept into NETWORK_NOT_READY where the daemon would re-probe forever on an error
# that can never fix itself. The CONFIG_INVALID reason + the pre-probe classification
# split + the CRITICAL severity map land in plan 29-03, so these cases are xfail until
# then. The two D-03 guards (transient->NETWORK_NOT_READY, 401->AUTH_FAILED) must
# stay GREEN today — they pin that the new split does NOT regress the existing
# network/auth classification.


def _empty_config():
    """A schema-valid Config with ZERO locations — an offline CONFIG_INVALID trip."""
    return Config(
        locations=[],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )


@_needs_config_invalid
def test_config_invalid_on_bad_template():
    """HARD-STARTUP-02: a missing template token -> reason == CONFIG_INVALID, with
    detail == the exception CLASS name (never str(exc), which can carry a path —
    T-04-01/T-29-01). The bad template trips BEFORE the network probe, so an OkClient
    is never reached."""
    client = _OkClient.__new__(_OkClient)  # never probed; config error trips first
    client.onecall_calls = []
    result = run_self_check(
        config=_config(template="__does_not_exist__.txt"), client=client
    )
    assert result.ok is False
    assert result.reason == CONFIG_INVALID
    # detail is the exception CLASS name only — a bare identifier, never str(exc)
    # (which would embed the "__does_not_exist__.txt" path) — T-29-01 / T-04-01.
    assert result.detail.isidentifier()  # a class name, not a str(exc) sentence
    assert "/" not in result.detail  # never leaks a filesystem path
    assert "__does_not_exist__" not in result.detail  # never echoes the bad token
    assert client.onecall_calls == []  # the network probe was never reached


@_needs_config_invalid
def test_config_invalid_on_empty_locations():
    """HARD-STARTUP-02: an empty-locations config -> reason == CONFIG_INVALID
    (config error, not a transient network state)."""
    client = _OkClient.__new__(_OkClient)
    client.onecall_calls = []
    result = run_self_check(config=_empty_config(), client=client)
    assert result.ok is False
    assert result.reason == CONFIG_INVALID
    assert result.detail.isidentifier()  # class name only, outcome-only (T-29-01)
    assert client.onecall_calls == []


def test_connect_error_still_network_not_ready():
    """D-03 guard (HARD-STARTUP-02): a transient ConnectError STAYS
    network_not_ready after the CONFIG_INVALID split — a network blip must never be
    reclassified as a fatal config error."""
    client = _RaisingClient(httpx.ConnectError("boom"))
    result = run_self_check(config=_config(), client=client)
    assert result.ok is False
    assert result.reason == NETWORK_NOT_READY
    assert result.detail == "ConnectError"


def test_401_still_auth_failed():
    """D-03 guard (HARD-STARTUP-02): a 401 STAYS auth_failed after the CONFIG_INVALID
    split — the pre-probe config classification must not shadow the auth branch."""
    client = _RaisingClient(_http_status_error(401))
    result = run_self_check(config=_config(), client=client)
    assert result.ok is False
    assert result.reason == AUTH_FAILED
    assert result.detail == "401"


@_needs_config_invalid
@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (CONFIG_INVALID, Severity.CRITICAL),
        (AUTH_FAILED, Severity.CRITICAL),
        (NETWORK_NOT_READY, Severity.WARNING),
    ],
    ids=["config_invalid_critical", "auth_failed_critical", "network_warning"],
)
def test_severity_map(reason, expected):
    """HARD-STARTUP-02: to_health_result maps CONFIG_INVALID and AUTH_FAILED to
    CRITICAL (fatal-worthy) and NETWORK_NOT_READY to WARNING (re-probe)."""
    health = to_health_result(CheckResult(ok=False, reason=reason))
    assert health.severity == expected
