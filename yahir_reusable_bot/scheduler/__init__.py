"""In-process scheduling surface.

Exports the :class:`SchedulerEngine` thin registrar — the non-owning facade over
a host-built background scheduler that bakes the invariant job-options in once
(D-01/D-03/D-15). The host keeps constructing and starting/stopping its own
scheduler; this subpackage owns only the registration contract.
"""

from __future__ import annotations

from .engine import SchedulerEngine

__all__ = ["SchedulerEngine"]
