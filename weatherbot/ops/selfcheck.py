"""Classified startup self-check engine (OPS-02, D-03/D-04/D-06).

``do_check`` (``cli.py``) validates config + template, resolves locations, and makes
ONE OpenWeather reachability probe whose 401/403 distinguishes "subscription not
active / not yet propagated" from a generic error — but it returns a print-budget +
exit code (0/1). The daemon's startup gate (Plan 05-02) needs the SAME validate+probe
with a *classified* outcome so its re-probe loop and the durable health row can
branch. ``run_self_check`` is that shared engine: it reuses do_check's exact steps and
returns a :class:`CheckResult` (``online`` / ``network_not_ready`` / ``auth_failed``).

Classification reuses the Phase-4 ``is_transient`` / ``is_auth_failure`` classifiers
(``weatherbot.reliability``) rather than re-deriving status logic. Per D-06 a single
401/403 cannot distinguish a permanently-bad key from a new key still propagating, so
both are classified ``auth_failed`` (with the existing key-not-active wording at the
``do_check`` layer) and the daemon re-probe loop recovers a genuinely-propagating key
on a later attempt. ``CheckResult.detail`` is outcome-only — a status code or
exception class name — NEVER a secret (T-04-01).

This module lives in ``weatherbot.ops`` and imports NEITHER ``weatherbot.cli`` nor
``weatherbot.scheduler.daemon`` at import time, so both ``cli`` and ``daemon`` import
it cleanly without re-introducing the cli<->daemon cycle (``cli.main`` already imports
the daemon lazily for exactly that reason). The weather-client builder lives only in
``cli`` today, so it is imported LAZILY inside ``run_self_check`` (only when no client
is injected) to keep this module's import graph cycle-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from weatherbot.config import assert_unique_names, resolve_location
from weatherbot.reliability import is_auth_failure, is_transient
from templates.renderer import load_template, validate_template

if TYPE_CHECKING:
    from weatherbot.config.models import Config
    from weatherbot.config.settings import Settings

# Health/self-check reason vocabulary (D-08). Mirrors retry.py's REASON_* constants.
PASS = "online"
NETWORK_NOT_READY = "network_not_ready"
AUTH_FAILED = "auth_failed"


@dataclass
class CheckResult:
    """The classified outcome of a startup self-check.

    ``ok`` is the pass/fail flag; ``reason`` is one of :data:`PASS` /
    :data:`NETWORK_NOT_READY` / :data:`AUTH_FAILED`; ``detail`` is outcome-only (a
    status code or exception class name) and NEVER a secret (T-04-01).
    """

    ok: bool
    reason: str
    detail: str = ""


def run_self_check(
    *,
    config: Config,
    settings: Settings | None = None,
    client=None,
) -> CheckResult:
    """Validate config+template, resolve locations, make ONE probe, classify it.

    Reuses ``do_check``'s exact validate+probe steps; differs only in returning a
    classified :class:`CheckResult` instead of printing + an exit code. The probe is
    never retried here (the daemon's re-probe loop owns retrying, D-04). Failures are
    classified (D-06): a 401/403 -> :data:`AUTH_FAILED`; a transient
    connect/timeout/read or 429/5xx -> :data:`NETWORK_NOT_READY`; any other failure
    (config/template error included) -> :data:`NETWORK_NOT_READY` (still
    stay-alive-able, D-04). A clean probe -> ``ok=True, reason=online``.
    """
    try:
        if not config.locations:
            raise ValueError("No locations configured in config.toml")

        # (2) Template placeholders are all canonical (D-10).
        validate_template(load_template(config.template))

        # (4a) Names are unique so --send-now "<name>" is unambiguous (CONF-05).
        assert_unique_names(config)

        # (4b) Every configured location resolves by name.
        for loc in config.locations:
            resolve_location(config, loc.name)

        # (3) ONE live reachability probe — never retried here.
        if client is None:
            if settings is None:
                raise ValueError("run_self_check requires either a client or settings")
            # Lazy import: build_client lives in cli today; importing it at module
            # level would couple ops -> cli. Only needed when no client is injected.
            from weatherbot.cli import build_client

            client = build_client(settings)

        client.fetch_onecall(config.locations[0], "imperial")
    except httpx.HTTPStatusError as exc:
        if is_auth_failure(exc):  # 401/403
            return CheckResult(
                ok=False,
                reason=AUTH_FAILED,
                detail=str(exc.response.status_code),
            )
        # A non-auth HTTPStatusError (429/5xx via is_transient, or any other) is
        # treated as not-ready so the daemon keeps re-probing rather than dying.
        return CheckResult(
            ok=False, reason=NETWORK_NOT_READY, detail=type(exc).__name__
        )
    except Exception as exc:  # noqa: BLE001 — surface any failure as a classified result
        # is_transient is consulted for clarity/parity with the daemon path; either
        # branch is network_not_ready (D-04 keeps re-probing on every non-pass).
        is_transient(exc)
        return CheckResult(
            ok=False, reason=NETWORK_NOT_READY, detail=type(exc).__name__
        )

    return CheckResult(ok=True, reason=PASS)
