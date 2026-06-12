"""Ops package: deployment / supervision helpers (Phase 5, OPS-01/02).

Re-exports the public ops surface the daemon gate (Plan 05-02) wires together: the
pure-stdlib systemd readiness notifier and the classified self-check engine
(``run_self_check`` / ``CheckResult`` + the reason constants).
"""

from .sdnotify import SystemdNotifier
from .selfcheck import (
    AUTH_FAILED,
    NETWORK_NOT_READY,
    PASS,
    CheckResult,
    run_self_check,
)

__all__ = [
    "AUTH_FAILED",
    "NETWORK_NOT_READY",
    "PASS",
    "CheckResult",
    "SystemdNotifier",
    "run_self_check",
]
