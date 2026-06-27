"""The ``AlertSink`` port — the module's out-of-band alert contract (D-07).

The delivery-reliability lane (the two-burst retry engine in
:mod:`yahir_reusable_bot.reliability`) needs a way, on exhaustion, to record a
durable "this scheduled send did not go through" alert — and, on a later
success, to resolve it. That out-of-band sink is HOST policy: where the row is
written, what "resolved" means, and the persistence backend all belong to the
app. The module owns only the *contract*.

``AlertSink`` is that contract: a :class:`typing.Protocol` exposing exactly the
two operations the reliability orchestration consumes — ``record_alert`` (record
at most once per slot/day; returns whether THIS caller wrote the row) and
``resolve_alert`` (stamp it resolved when the slot later succeeds). It is a
STRUCTURAL protocol, so the app's existing
``weatherbot.weather.store.record_alert`` / ``resolve_alert`` functions satisfy
it without any subclassing or registration.

Weather-clean by construction (D-11): the host's store names its first key
parameter ``location_name``, but the PORT signature deliberately renames it to
the neutral ``target`` so no weather noun appears in the module's public name
surface (the AST litmus walks this file). Argument TYPES are likewise neutral —
``str | os.PathLike`` for the store handle, ``str`` for the slot/day/reason keys,
``bool`` for the result — never a weather model. There is NO ``briefing_missed``
method and NO heartbeat method on this port (D-08 — heartbeat is Phase 25).
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class AlertSink(Protocol):
    """Out-of-band sink for missed-delivery alerts (record-once / resolve).

    The reliability lane calls :meth:`record_alert` when a scheduled send is
    exhausted and :meth:`resolve_alert` when a later attempt for the same slot
    succeeds. The host (e.g. an SQLite store) supplies the implementation; the
    module depends only on this structural shape.
    """

    def record_alert(
        self,
        db_path: str | os.PathLike[str],
        target: str,
        slot_time: str,
        local_date: str,
        reason: str,
        severity: str = "critical",
    ) -> bool:
        """Durably record a missed-delivery alert, at most once per slot/day.

        Returns ``True`` iff THIS caller wrote the row (the first alert for this
        slot/day), so a caller can take a write-once side action exactly once.
        """
        ...

    def resolve_alert(
        self,
        db_path: str | os.PathLike[str],
        target: str,
        slot_time: str,
        local_date: str,
    ) -> None:
        """Stamp the matching unresolved alert resolved when the slot succeeds.

        A no-op when no matching unresolved alert exists.
        """
        ...
