"""Scheduler layer: the ``days`` vocabulary parser and (Plan 03) the daemon.

This package stays dependency-light at the leaf (``days.py`` imports nothing
from config or apscheduler) so the config model can import ``parse_days``
without an import cycle.

``run_daemon`` is exposed LAZILY (via :pep:`562` ``__getattr__``) rather than
eagerly imported here. ``weatherbot.config.models`` imports ``parse_days`` from
this package, which runs this ``__init__`` — and eagerly importing ``.daemon``
here would chain ``daemon -> weatherbot.ops -> weatherbot.config`` while
``weatherbot.config`` is still partially initialized, a circular import (Plan
05-02: the daemon now imports the ``ops`` self-check engine). Deferring the
``.daemon`` import to first attribute access breaks that chain while keeping
``from weatherbot.scheduler import run_daemon`` working.
"""

from .catchup import MissedSlot, plan_catchup
from .days import parse_days

__all__ = ["parse_days", "run_daemon", "plan_catchup", "MissedSlot"]


def __getattr__(name: str):  # noqa: ANN202 — PEP 562 module-level lazy attr
    if name == "run_daemon":
        from .daemon import run_daemon

        return run_daemon
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
