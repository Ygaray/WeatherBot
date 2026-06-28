"""Reusable process-lifecycle surface (SEAM-05).

The genuinely-reusable process-lifecycle layer: the systemd ``READY=1`` notifier,
the generic health-probe result DTO, the parameterized filesystem/process
identity + ``/proc`` staleness guard, and (added in Plan 25-02's wiring) the
:class:`ReadyGate` engine that drives an app-provided ``health_check`` through an
interruptible re-probe loop and emits ``READY=1`` once it passes.

Every symbol here is weather-noun-free: a bot supplies its own health predicate,
filesystem identity, and side-effect hooks. The module owns ZERO durable I/O —
the durable health row / heartbeat tick / online ping all ride injected
best-effort hooks, wired app-side at the composition root.
"""

from __future__ import annotations

from .health import HealthResult, Severity
from .identity import (
    LifecycleIdentity,
    is_running_process,
    read_pid,
    write_pid_atomic,
)
from .ready_gate import ReadyGate
from .sdnotify import SystemdNotifier

__all__ = [
    "ReadyGate",
    "SystemdNotifier",
    "HealthResult",
    "Severity",
    "LifecycleIdentity",
    "is_running_process",
    "write_pid_atomic",
    "read_pid",
]
