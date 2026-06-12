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

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.ops import (
    AUTH_FAILED,
    NETWORK_NOT_READY,
    PASS,
    CheckResult,
    run_self_check,
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
