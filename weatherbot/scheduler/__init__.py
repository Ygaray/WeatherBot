"""Scheduler layer: the ``days`` vocabulary parser and (Plan 03) the daemon.

This package stays dependency-light at the leaf (``days.py`` imports nothing
from config or apscheduler) so the config model can import ``parse_days``
without an import cycle.
"""

from .catchup import MissedSlot, plan_catchup
from .daemon import run_daemon
from .days import parse_days

__all__ = ["parse_days", "run_daemon", "plan_catchup", "MissedSlot"]
