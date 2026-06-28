"""The ``JobStore`` port + ``MemoryJobStore`` impl — the serialization contract (D-11/D-12/D-13).

Where the host's scheduled jobs live is HOST policy. The module owns only the
*contract* that says what a durable job store WOULD require — and the trivial
in-memory implementation that ships today. The PAYLOAD of this file is the
docstring contract, not the method surface: the Protocol body is intentionally
minimal because the deliverable is the documented set of constraints, plus the
named-but-unbuilt durable-store boundary (D-13).

A durable job store serializes (pickles) each job. The constraints below are
ALREADY true of today's jobs, so a durable backend could be slotted in without
changing the host's registration — EXCEPT for the live runtime handles, which the
boundary paragraph addresses.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class JobStore(Protocol):
    """The store a host's scheduler keeps its registered jobs in (contract-only).

    The deliverable here is the SERIALIZATION CONTRACT a durable backend would
    impose — three constraints that hold for today's jobs, plus the boundary a
    durable impl must cross. The shipped :class:`MemoryJobStore` satisfies this
    trivially (it never serializes), so the Protocol body stays minimal.

    Serialization constraints (true of today's jobs):

    1. **Importable callback.** Every job's callable is a module-level function
       referenceable by import path, never a closure or a bound method on a
       transient object — so a serializer can re-resolve it by reference.

    2. **Picklable identity-style positional args.** Positional ``args`` are
       plain data (a plain-string id plus plain-data records), never a live
       client, socket, channel, or threading primitive closed over the args — so
       the args round-trip through a pickle unchanged.

    3. **Per-fire keyword data re-resolved at fire time.** Per-fire keyword data
       carries a holder/registry that the job re-reads when it fires, never a
       baked-in snapshot of mutable state — so a later reconfigure changes what an
       unchanged job does.

    Durable-store boundary (named here, built nowhere — D-13):

        Today's jobs additionally thread NON-picklable runtime handles through
        their per-fire keyword data: a live API client, an open delivery channel,
        a process stop signal, and a config holder. These cannot survive a pickle.
        A durable implementation that serializes jobs would have to RELOCATE these
        handles out of the job payload into a process-level registry resolved BY
        ID at fire time, leaving only the picklable id in the stored job. This
        boundary is documented, not implemented — v2.0 ships only the in-memory
        store below, which sidesteps it entirely.
    """

    ...


class MemoryJobStore:
    """In-memory job store: holds jobs directly, never serializes (D-12).

    The shipped v2.0 implementation. Because it keeps each registered job as a
    live object, the non-picklable runtime handles (client, channel, stop signal,
    holder) are carried as-is — none of the serialization constraints above bite.
    The job set is re-derived from config on each restart rather than persisted,
    so there is nothing to deserialize and no durable-store boundary to cross.
    """

    def __init__(self) -> None:
        ...
