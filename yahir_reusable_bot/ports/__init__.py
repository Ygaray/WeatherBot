"""Host-supplied adapter seams — the Protocols the host implements (D-07).

Exports the module's port contracts. ``AlertSink`` is the out-of-band
missed-delivery alert sink the reliability lane consumes; the host supplies the
concrete implementation (structurally — no subclassing required).
"""

from __future__ import annotations

from .alerts import AlertSink

__all__ = ["AlertSink"]
