"""App-side re-export shim for the Phase-4 two-burst retry contract (RELY-01/02).

The retry engine now lives in :mod:`yahir_reusable_bot.reliability` (D-06). This
shim re-exports the public retry surface from there so every existing
``from weatherbot.reliability import ...`` importer (``scheduler.daemon``,
``ops.selfcheck``, ``cli``) — and the Phase-21 exception-identity pins that
depend on it — stays byte-identical, resolving to the IDENTICAL objects.
"""

from yahir_reusable_bot.reliability import (
    REASON_AUTH_FAILED,
    REASON_INTERNAL_ERROR,
    REASON_TRANSIENT_EXHAUSTED,
    build_retrying,
    is_auth_failure,
    is_transient,
    parse_retry_after,
)

__all__ = [
    "REASON_AUTH_FAILED",
    "REASON_INTERNAL_ERROR",
    "REASON_TRANSIENT_EXHAUSTED",
    "build_retrying",
    "is_auth_failure",
    "is_transient",
    "parse_retry_after",
]
