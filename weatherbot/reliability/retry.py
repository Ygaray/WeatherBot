"""App-side re-export shim for the two-burst retry engine (RELY-01/02, D-06).

The retry engine now lives, weather-clean, in
:mod:`yahir_reusable_bot.reliability.retry` — the reusable bot core (D-06). This
shim re-exports the FULL retry surface (the two-burst constants, the status-code
frozensets, the ``REASON_*`` taxonomy, and every classifier / parser / builder
function) so that every existing
``from weatherbot.reliability.retry import ...`` importer — including the
direct-by-name consumers (``weatherbot.config.models`` for ``RETRY_AFTER_CAP_S``,
``tests/test_reliability.py`` for the constants + ``two_burst_wait``, and the
Phase-21 exception-identity pin for ``is_transient``) — resolves to the IDENTICAL
objects with zero call-site churn (byte-identical contract).
"""

from __future__ import annotations

from yahir_reusable_bot.reliability.retry import (
    BURST_SIZE,
    BURST_SPREAD_S,
    MID_PAUSE_S,
    PERMANENT,
    REASON_AUTH_FAILED,
    REASON_INTERNAL_ERROR,
    REASON_TRANSIENT_EXHAUSTED,
    RETRY_AFTER_CAP_S,
    TRANSIENT,
    build_retrying,
    is_auth_failure,
    is_transient,
    parse_retry_after,
    two_burst_wait,
)

__all__ = [
    "BURST_SIZE",
    "BURST_SPREAD_S",
    "MID_PAUSE_S",
    "PERMANENT",
    "REASON_AUTH_FAILED",
    "REASON_INTERNAL_ERROR",
    "REASON_TRANSIENT_EXHAUSTED",
    "RETRY_AFTER_CAP_S",
    "TRANSIENT",
    "build_retrying",
    "is_auth_failure",
    "is_transient",
    "parse_retry_after",
    "two_burst_wait",
]
