"""Reliability package: the Phase-4 two-burst retry contract (RELY-01/02).

Re-exports the public retry surface that Plans 03 (daemon patient path) and 04
(manual tight path) consume — the builder, the transient/auth classifiers, the
capped ``Retry-After`` parser, and the alert-reason taxonomy constants.
"""

from .retry import (
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
