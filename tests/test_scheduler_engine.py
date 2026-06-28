"""Wave-0 safety net for the SchedulerEngine job-options contract (Phase 23).

The schedule-plan golden projects ``str(trigger)`` only — it does NOT cover
``misfire_grace_time`` / ``coalesce`` / ``max_instances`` (Pitfall 1/2). So the
ONLY proof that centralizing the 4 copy-pasted ``add_job`` invariant kwargs into
``SchedulerEngine.register`` is behavior-preserving is a job-options READ-BACK:
register a job through the engine on a NON-started scheduler, then read the job
back via ``scheduler.get_jobs()`` and assert the three options landed.

A separate test pins APScheduler's bare ``add_job`` default ``max_instances == 1``
(A1) — the assumption the ``max_instances`` baking rests on for the briefing call
sites that omit the kwarg. ``list_live_ids`` / ``remove`` are covered too.

No ``scheduler.start()`` anywhere: registration + read-back only, so the suite
stays fast and deterministic.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from yahir_reusable_bot.scheduler import SchedulerEngine


def _briefing_callback(*args, **kwargs):
    """A plain module-level callback shaped like a real briefing fire (no-op here)."""
    return None


def test_register_bakes_three_invariant_job_options():
    """A briefing-shaped job (no max_instances at the call site) reads back with all 3 options.

    Proves the centralization (Pitfall 1) AND the max_instances default-of-1
    baking (Pitfall 2) are byte-identical to the inline call sites.
    """
    scheduler = BackgroundScheduler()
    engine = SchedulerEngine(scheduler)

    engine.register(
        "Home|09:00|weekdays",
        CronTrigger(hour=9, minute=0, day_of_week="mon-fri"),
        _briefing_callback,
        args=["home", "morning"],
        kwargs={"db_path": ":memory:"},
    )

    (job,) = scheduler.get_jobs()
    assert job.misfire_grace_time is None
    assert job.coalesce is True
    assert job.max_instances == 1


def test_bare_add_job_default_max_instances_is_one():
    """APScheduler's own add_job default max_instances == 1 (A1 / Pitfall 2).

    This is the assumption the engine's baked max_instances=1 relies on for the
    call sites that omitted the kwarg — pin it so a library upgrade can't silently
    change the default out from under the centralization.

    APScheduler defers applying ``add_job`` defaults until the scheduler processes
    its pending queue, so a job on a NON-started scheduler has no ``max_instances``
    attribute yet. ``start(paused=True)`` materializes the defaults WITHOUT firing
    any job (the trigger is far in the future and the scheduler is paused), keeping
    the test fast and deterministic. The same processing reveals that bare
    ``misfire_grace_time`` defaults to ``1`` (NOT ``None``) — which is exactly why
    the engine must bake ``misfire_grace_time=None`` in explicitly (D-03).
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _briefing_callback,
        trigger=CronTrigger(hour=9, minute=0),
        id="bare",
    )
    scheduler.start(paused=True)
    try:
        (job,) = scheduler.get_jobs()
        assert job.max_instances == 1
        # The non-None default the engine deliberately overrides.
        assert job.misfire_grace_time == 1
    finally:
        scheduler.shutdown(wait=False)


def test_list_live_ids_matches_get_jobs():
    """engine.list_live_ids() equals the scheduler's own job-id set after >=2 registers."""
    scheduler = BackgroundScheduler()
    engine = SchedulerEngine(scheduler)

    engine.register("a", CronTrigger(hour=8), _briefing_callback)
    engine.register("b", CronTrigger(hour=9), _briefing_callback)

    assert engine.list_live_ids() == {job.id for job in scheduler.get_jobs()}
    assert engine.list_live_ids() == {"a", "b"}


def test_remove_drops_the_job():
    """engine.remove(id) drops that id from list_live_ids()."""
    scheduler = BackgroundScheduler()
    engine = SchedulerEngine(scheduler)

    engine.register("a", CronTrigger(hour=8), _briefing_callback)
    engine.register("b", CronTrigger(hour=9), _briefing_callback)

    engine.remove("a")

    assert engine.list_live_ids() == {"b"}
