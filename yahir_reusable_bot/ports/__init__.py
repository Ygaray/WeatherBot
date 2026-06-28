"""Host-supplied adapter seams — the Protocols the host implements (D-07).

Exports the module's port contracts. ``AlertSink`` is the out-of-band
missed-delivery alert sink the reliability lane consumes; ``OccurrenceStore`` is
the generic exactly-once gate; ``JobStore`` is the serialization contract (with
the trivial in-memory ``MemoryJobStore`` impl). The host supplies the concrete
implementations (structurally — no subclassing required).
"""

from __future__ import annotations

from .alerts import AlertSink
from .jobstore import JobStore, MemoryJobStore
from .occurrence import OccurrenceStore

__all__ = ["AlertSink", "OccurrenceStore", "JobStore", "MemoryJobStore"]
