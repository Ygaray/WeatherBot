"""The ``SchedulerEngine`` — a thin registrar over a host-owned scheduler (D-15).

The host constructs, ``start()``s, and ``shutdown()``s its own background
scheduler; this engine is a NON-owning facade that holds a reference to it and
exposes exactly three operations the host's registration loop needs:
``register`` (add a job), ``remove`` (drop one by id), and ``list_live_ids``
(read the currently-scheduled ids). It deliberately owns NO lifecycle — there is
no ``start``/``shutdown`` on this class (D-15 / A4).

Its one job is to bake the three job-options that every host call site repeated
by hand into a SINGLE place so they can no longer drift apart (D-03):
``misfire_grace_time=None`` (cross-restart recovery is owned by a durable
sent-log + catch-up scan, NOT the scheduler), ``coalesce=True`` (collapse a
backlog of missed fires into one), and ``max_instances=1`` (never overlap two
runs of the same job). ``max_instances=1`` happens to be APScheduler's own
``add_job`` default, so baking it in is behavior-preserving for the call sites
that omit it — a fact pinned by a job-options read-back test, not a string golden.

The native trigger object passes THROUGH untouched (D-01): the engine never
constructs or inspects a trigger, so the host keeps full control of cron/interval
semantics and the schedule golden stays byte-identical. The callback and its
``args``/``kwargs`` are likewise opaque — the engine never names or reads them,
so any host (a different bot) binds its own callable through the identical hole
(D-05). No ``cron()``/``interval()``/``date()`` trigger-sugar methods (D-02).
"""

from __future__ import annotations

from typing import Any, Callable


class SchedulerEngine:
    """Thin, non-owning registrar over a host-supplied background scheduler.

    Construct with the host's already-built scheduler instance; the host retains
    ownership of its lifecycle (``start``/``shutdown``). The engine forwards
    registrations with the three invariant job-options baked in once so they
    cannot drift across call sites.
    """

    def __init__(self, scheduler: Any) -> None:
        self._scheduler = scheduler

    def register(
        self,
        job_id: str,
        trigger: Any,
        callback: Callable[..., Any],
        *,
        args: Any = None,
        kwargs: Any = None,
        replace_existing: bool = False,
    ) -> None:
        """Register a job, baking the three invariant options in once (D-03).

        The ``trigger`` and ``callback`` (plus its opaque ``args``/``kwargs``)
        pass through untouched; ``misfire_grace_time=None``, ``coalesce=True``,
        and ``max_instances=1`` are forced here so no call site can drift.
        """
        self._scheduler.add_job(
            callback,
            trigger=trigger,
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=replace_existing,
            misfire_grace_time=None,
            coalesce=True,
            max_instances=1,
        )

    def remove(self, job_id: str) -> None:
        """Drop the job with this id from the host scheduler."""
        self._scheduler.remove_job(job_id)

    def list_live_ids(self) -> set[str]:
        """The set of ids currently scheduled on the host scheduler."""
        return {job.id for job in self._scheduler.get_jobs()}
