"""Ops package: deployment / supervision helpers (Phase 5, OPS-01/02).

Re-exports the public ops surface the daemon gate (Plan 05-02) wires together: the
pure-stdlib systemd readiness notifier. Plan 05-01 Task 3 extends this with the
classified self-check engine (``run_self_check`` / ``CheckResult`` + reason
constants).
"""

from .sdnotify import SystemdNotifier

__all__ = [
    "SystemdNotifier",
]
