"""The daemon spine: the always-on foreground lifecycle + the per-fire callback.

This is Phase 3's defining new capability — the first long-running process. It
turns the validated building blocks (the ``Schedule`` model + ``sent_log`` from
Plan 01, the ``ScheduleContext`` from Plan 02, the ``plan_catchup`` planner from
this plan) into a working scheduler:

- ``run_daemon`` registers one APScheduler ``CronTrigger`` job per ENABLED
  ``(location, schedule entry)`` at the LOCATION's own IANA timezone (so a Home
  weekday slot and a Weekend slot in another zone each fire at their own local
  wall-clock time, SCHD-04/SCHD-05), announces the schedule (D-10), runs the
  90-minute startup catch-up scan (Pattern 3 / SCHD-06), starts the scheduler,
  then blocks in the foreground until SIGTERM / Ctrl-C and shuts down cleanly
  (D-09). It does NOT self-daemonize — systemd keeps the process alive (Phase 5).

- ``fire_slot`` is the SAME callback used by both the live cron job and the
  catch-up scan: it ATOMICALLY claims the slot via ``claim_slot`` BEFORE delivering
  (delivery-level exactly-once, SCHD-07 — the claim's ``INSERT OR IGNORE`` +
  ``rowcount==1`` arbitrates two overlapping fires so only the winner POSTs),
  threads a ``ScheduleContext`` through ``send_now`` (so a recovered late send
  renders its intended-vs-actual note), and on a failed / non-ok send RELEASES the
  claim via ``release_claim`` so the slot stays re-fireable (mark-after-success for
  the failure case — retry-then-alert is Phase 4). Its whole body is wrapped in a
  try/except so one bad slot cannot crash the scheduler thread (minimal isolation
  now; Phase 4 hardens it, Anti-Pattern: per-job isolation).

Recovery across a restart is OWNED by the sent-log + catch-up scan, NOT by
APScheduler misfire/coalesce (the memory jobstore loses all state on exit), so
every job is registered with ``misfire_grace_time=None``.

Logging is OUTCOME-ONLY (T-04-01): ``location``/``time``/``days``/
``next_run_time``/``delivered`` — never the API key or the webhook URL, which
stay inside the injected client/channel.
"""

from __future__ import annotations

import signal
import threading
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from weatherbot.ops import (
    AUTH_FAILED,
    SystemdNotifier,
    run_self_check,
)
from weatherbot.reliability import (
    REASON_AUTH_FAILED,
    REASON_INTERNAL_ERROR,
    REASON_TRANSIENT_EXHAUSTED,
    build_retrying,
    is_auth_failure,
)
from weatherbot.scheduler.catchup import plan_catchup
from weatherbot.scheduler.context import ScheduleContext
from weatherbot.weather.store import (
    claim_slot,
    record_alert,
    release_claim,
    resolve_alert,
    stamp_health,
    stamp_success,
    stamp_tick,
    was_sent,
)

if TYPE_CHECKING:
    from weatherbot.channels.base import Channel, DeliveryResult
    from weatherbot.config.models import Config, Location, Schedule
    from weatherbot.config.settings import Settings

_log = structlog.get_logger(__name__)

# Heartbeat cadence (D-06, Claude's discretion): a liveness tick every ~10 min,
# independent of any send, so a future monitor can distinguish a CRASHED process
# (stale last_tick) from one that is alive but FAILING to send (fresh last_tick,
# stale last_success). 600s is well below any reasonable staleness alarm and runs
# on the same APScheduler threadpool (default max_workers=10) — at a personal-bot
# slot count it never starves slot jobs (Pitfall 3).
HEARTBEAT_INTERVAL_S = 600

# Startup self-check re-probe cadence (OPS-02, D-04 — Claude's discretion, 60–300s
# band). 120s: frequent enough that a propagating key / restored network recovers
# within ~2 min of becoming good, gentle enough it never approaches the OpenWeather
# 60/min limit. A module constant for now — promotable to config later (D-04), but
# NOT promoted in this phase.
RE_PROBE_INTERVAL_S = 120


def fire_slot(
    location: Location,
    slot: Schedule,
    *,
    config: Config,
    db_path,
    settings: Settings | None = None,
    client=None,
    channel: Channel | None = None,
    scheduled_dt=None,
    late: bool = False,
    stop_event=None,
) -> DeliveryResult | None:
    """Deliver one briefing for ``(location, slot)`` — claim-before-fire, release-on-failure.

    The single callback for BOTH the live cron job and the catch-up scan. It:

    1. computes the ``local_date`` dedup-key component (from ``scheduled_dt`` when
       present, else "now" in the location's tz);
    2. ATOMICALLY claims the slot via ``claim_slot`` BEFORE delivering — returns
       ``None`` early if the claim is LOST (already sent, or a concurrent/overlapping
       fire won first), so two overlapping fires deliver EXACTLY ONCE (SCHD-07,
       delivery-level exactly-once; subsumes the old restart-replay / DST fall-back
       guard, D-06);
    3. builds a :class:`ScheduleContext` and calls ``send_now`` (which fetches live
       weather, so a recovered late send carries CURRENT data, D-05);
    4. on a NON-ok result (or a raised delivery) RELEASES the claim via
       ``release_claim`` so the slot stays re-fireable (mark-after-success for the
       failure case, D-07 — retry-then-alert is Phase 4). A successful send leaves
       the claim row in place (the slot is already recorded by the claim).

    The whole body is wrapped in ``try/except`` that logs and returns ``None`` so
    one bad slot cannot crash the scheduler thread (minimal isolation, T-03-07).
    Returns the :class:`DeliveryResult` on a fire, or ``None`` on skip/failure.
    """
    # Track whether THIS caller won the claim, so the except-block release only
    # ever undoes a claim this caller actually took — never a row it never owned,
    # and never before local_date is even computed (avoids an unbound-name /
    # wrong-row delete that would itself break per-job isolation).
    local_date = None
    claimed = False
    try:
        tz = ZoneInfo(location.timezone)
        if scheduled_dt is not None:
            local_date = scheduled_dt.astimezone(tz).date().isoformat()
        else:
            from datetime import datetime

            local_date = datetime.now(tz).date().isoformat()

        # Claim-before-fire: atomically claim the slot BEFORE the side-effecting
        # send so two overlapping fires deliver EXACTLY ONCE (SCHD-07). A LOST
        # claim means the slot is already sent OR a concurrent fire won first —
        # either way this caller must not deliver. This single atomic claim
        # subsumes the old was_sent read (restart-replay / DST fall-back, D-06).
        if not claim_slot(db_path, location.name, slot.time, local_date):
            _log.info(
                "slot skipped (already sent)",
                location=location.name,
                time=slot.time,
                local_date=local_date,
            )
            return None
        claimed = True

        # Import send_now lazily: this module is dragged in (via the scheduler
        # package barrel) while ``weatherbot.cli`` is still initializing, so a
        # top-level ``from weatherbot.cli import send_now`` would be a cycle.
        from weatherbot.cli import send_now

        ctx = ScheduleContext(scheduled_dt=scheduled_dt, tz=tz, late=late)

        # The DAEMON patient path (D-10, Open Question 1 resolution): wrap the
        # SINGLE-attempt ``send_now`` in Plan 01's two-burst retry. ``send_now``
        # itself stays the retry-agnostic shared composition root — the retry
        # locus lives HERE so a transient fetch exception (httpx) OR a non-ok
        # ``DeliveryResult`` (delivery failure) is retried on the two-burst
        # schedule, while a 401/403 short-circuits (classifier doesn't retry it).
        #
        # ``stop_event`` is threaded from ``run_daemon`` so the long mid-pause is
        # SIGTERM-interruptible (D-07 / Pitfall 1). A standalone fire (catch-up
        # before run_daemon, or a test) may pass None — fall back to a fresh,
        # never-set Event so the schedule still runs (just not externally
        # interruptible). The budget is config-driven (D-09).
        stop = stop_event if stop_event is not None else threading.Event()
        retrying = build_retrying(
            stop,
            attempts_per_burst=config.reliability.attempts_per_burst,
            burst_spread_s=config.reliability.burst_spread_seconds,
            mid_pause_s=config.reliability.mid_pause_seconds,
        )

        def _attempt() -> DeliveryResult:
            # Let the fetch ``httpx.HTTPStatusError`` (carrying ``.response`` with
            # the ``Retry-After`` header) PROPAGATE so Plan 01's wait callable can
            # honor the capped Retry-After (RELY-02). Do NOT translate/strip it.
            return send_now(
                location.name,
                config=config,
                db_path=db_path,
                settings=settings,
                client=client,
                channel=channel,
                schedule_ctx=ctx,
            )

        try:
            result = retrying(_attempt)
        except httpx.HTTPStatusError as exc:
            # Reraised from tenacity (reraise=True): a short-circuited 401/403
            # (auth) or an EXHAUSTED transient (429/5xx) HTTP error.
            release_claim(db_path, location.name, slot.time, local_date)
            claimed = False
            reason = (
                REASON_AUTH_FAILED if is_auth_failure(exc)
                else REASON_TRANSIENT_EXHAUSTED
            )
            self_first = record_alert(
                db_path, location.name, slot.time, local_date, reason
            )
            if self_first:
                _log.critical(
                    "briefing_missed",
                    location=location.name,
                    slot=slot.time,
                    local_date=local_date,
                    reason=reason,
                    severity="critical",
                )
            return None
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError):
            # An EXHAUSTED transient NETWORK error (no HTTP response): same
            # transient_exhausted outcome as an exhausted 5xx (RELY-03).
            release_claim(db_path, location.name, slot.time, local_date)
            claimed = False
            self_first = record_alert(
                db_path, location.name, slot.time, local_date,
                REASON_TRANSIENT_EXHAUSTED,
            )
            if self_first:
                _log.critical(
                    "briefing_missed",
                    location=location.name,
                    slot=slot.time,
                    local_date=local_date,
                    reason=REASON_TRANSIENT_EXHAUSTED,
                    severity="critical",
                )
            return None

        # Retry exhausted on a NON-OK DeliveryResult (a delivery failure that
        # never raised — e.g. a persistent Discord non-2xx). The channel owns its
        # own within-attempt 429 wait, so a Discord ok=False is ONE transient unit
        # (no double-retry, D-02 / Pitfall 2). Treat the exhausted non-ok as a
        # transient exhaustion alert.
        if not result.ok:
            release_claim(db_path, location.name, slot.time, local_date)
            claimed = False
            self_first = record_alert(
                db_path, location.name, slot.time, local_date,
                REASON_TRANSIENT_EXHAUSTED,
            )
            if self_first:
                _log.critical(
                    "briefing_missed",
                    location=location.name,
                    slot=slot.time,
                    local_date=local_date,
                    reason=REASON_TRANSIENT_EXHAUSTED,
                    severity="critical",
                )
            return None

        # Eventual SUCCESS: keep the claim, resolve any prior alert for this
        # slot/day (D-13, e.g. a restart-within-grace recovery), and stamp the
        # heartbeat last_success (D-04/D-05 — distinguishes alive+failing from
        # alive+delivering).
        resolve_alert(db_path, location.name, slot.time, local_date)
        stamp_success(db_path)
        _log.info(
            "slot fired",
            location=location.name,
            time=slot.time,
            late=late,
            delivered=result.ok,
        )
        return result
    except Exception:  # noqa: BLE001 — one bad slot must not kill the thread
        # An UNEXPECTED exception (not a classified transient/auth HTTP error):
        # a real bug somewhere in the send path. The claim was taken BEFORE the
        # send, so release it (D-07) and ALERT with reason=internal_error +
        # the FULL traceback (D-12 / RELY-06), then return None so the APScheduler
        # worker thread SURVIVES and other slots keep firing (T-03-07).
        if claimed and local_date is not None:
            release_claim(db_path, location.name, slot.time, local_date)
        if local_date is not None:
            self_first = record_alert(
                db_path, location.name, slot.time, local_date,
                REASON_INTERNAL_ERROR,
            )
            if self_first:
                _log.critical(
                    "briefing_missed",
                    location=location.name,
                    slot=slot.time,
                    local_date=local_date,
                    reason=REASON_INTERNAL_ERROR,
                    severity="critical",
                )
        _log.exception(
            "slot fire failed",
            location=location.name,
            time=slot.time,
        )
        return None


def _heartbeat_tick(db_path) -> None:
    """Stamp the liveness tick + emit the periodic ``heartbeat`` event (RELY-05, D-05).

    Runs on its own ``IntervalTrigger`` job (registered in :func:`run_daemon`),
    independent of any send, so a future monitor reading the single ``heartbeat``
    row can tell a CRASHED process (stale ``last_tick``) apart from one that is
    alive but failing to send (fresh ``last_tick``, stale ``last_success``).
    Outcome-only logging (T-04-01): a stable event key + the flat ``last_tick``
    field — never a secret.
    """
    from datetime import datetime, timezone

    stamp_tick(db_path)
    _log.info("heartbeat", last_tick=int(datetime.now(timezone.utc).timestamp()))


def _register_jobs(
    scheduler: BackgroundScheduler,
    config: Config,
    *,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
    stop_event=None,
) -> None:
    """Register one CronTrigger job per ENABLED slot at the location's own tz (Pattern 1).

    Disabled slots produce NO job (SCHD-02 toggle). Each trigger is pinned to the
    LOCATION's IANA ``timezone`` so it fires at that place's local wall-clock time
    (SCHD-04). ``misfire_grace_time=None`` because cross-restart recovery is owned
    by the sent-log + catch-up scan, not APScheduler (Anti-Pattern); ``coalesce``
    is a harmless backstop. The job ``id`` keys on ``name|time|days`` (D-06: editing
    a time = a new slot).
    """
    for location in config.locations:
        for slot in location.schedule:
            if not slot.enabled:
                continue
            hh, mm = slot.parsed_time()
            scheduler.add_job(
                fire_slot,
                trigger=CronTrigger(
                    hour=hh,
                    minute=mm,
                    day_of_week=slot.day_of_week,
                    timezone=location.timezone,
                ),
                kwargs={
                    "config": config,
                    "db_path": db_path,
                    "settings": settings,
                    "client": client,
                    "channel": channel,
                    # The SAME daemon stop Event whose ``.wait`` is the retry's
                    # ``sleep=`` — so a SIGTERM during the 45-min mid-pause aborts
                    # the in-progress retry cleanly (D-07 / Pitfall 1).
                    "stop_event": stop_event,
                },
                args=[location, slot],
                id=f"{location.name}|{slot.time}|{slot.days}",
                misfire_grace_time=None,
                coalesce=True,
            )


def _announce_schedule(scheduler: BackgroundScheduler, config: Config) -> None:
    """Log every registered slot + its computed next_run_time (D-10).

    Outcome-only logging: ``location``/``time``/``days``/``next_run_time`` — never
    a secret. Announce runs BEFORE ``scheduler.start()`` (so the log reads cleanly),
    and a not-yet-started APScheduler job has no ``next_run_time`` attribute yet —
    so the next fire is computed straight from the job's CronTrigger, which is
    tz-aware in the location's own zone (the proof the per-location wall-clock
    firing works).
    """
    from datetime import datetime

    jobs = scheduler.get_jobs()
    by_id = {job.id: job for job in jobs}
    for location in config.locations:
        tz = ZoneInfo(location.timezone)
        for slot in location.schedule:
            if not slot.enabled:
                continue
            job = by_id.get(f"{location.name}|{slot.time}|{slot.days}")
            next_run = None
            if job is not None:
                # Prefer a running scheduler's computed value; else derive it from
                # the trigger (pending jobs have no next_run_time attribute yet).
                next_run = getattr(job, "next_run_time", None)
                if next_run is None:
                    next_run = job.trigger.get_next_fire_time(None, datetime.now(tz))
            _log.info(
                "scheduled slot",
                location=location.name,
                time=slot.time,
                days=slot.days,
                next_run_time=str(next_run),
            )


def _run_catchup(
    config: Config,
    *,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
    stop_event=None,
) -> None:
    """Run the 90-minute startup catch-up scan, firing each missed slot once (Pattern 3).

    Re-derives what should have fired TODAY within the grace window and isn't in
    the sent-log (SCHD-06), then fires each via the SAME ``fire_slot`` callback
    with ``late=True`` so the recovered send renders its intended-vs-actual note.
    Catch-up fires are also a daemon-path delivery, so the SAME ``stop_event`` is
    threaded through so an in-progress retry pause is SIGTERM-interruptible (D-07).
    """
    missed = plan_catchup(
        config,
        lambda name, time, date: was_sent(db_path, name, time, date),
    )
    for ms in missed:
        fire_slot(
            ms.location,
            ms.slot,
            config=config,
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            scheduled_dt=ms.scheduled_dt,
            late=True,
            stop_event=stop_event,
        )


def gate_until_healthy(
    stop: threading.Event,
    *,
    config: Config,
    settings: Settings | None,
    db_path,
    client=None,
) -> bool:
    """Run the startup self-check; stay alive and re-probe until pass or stop (D-03/D-04).

    The classified self-check gate that runs BEFORE ``scheduler.start()`` (D-03). On
    EVERY outcome it stamps the durable single-row health table (D-08) so the future
    inbound-``status`` reader always reflects the latest probe. On a non-ok result it
    NEVER ``sys.exit``/raises (a dead process can't answer a future status query,
    D-04) — it logs (CRITICAL for a confirmed 401/403 ``auth_failed``, WARNING for a
    transient ``network_not_ready``) and re-probes on an interruptible
    ``stop.wait(RE_PROBE_INTERVAL_S)`` (NEVER ``time.sleep`` — a ``systemctl stop``
    during the loop must shut down promptly, Pitfall 2). A 401/403 stays alive too:
    one probe cannot tell a permanently-bad key from a still-propagating one (D-06),
    so a genuinely-propagating key recovers on a later re-probe.

    Returns ``True`` once the self-check passes; ``False`` if ``stop`` was set first
    (clean shutdown during the gate — the caller falls straight through to
    ``scheduler.shutdown`` without starting the scheduler or emitting the online
    signal).
    """
    while not stop.is_set():
        result = run_self_check(config=config, settings=settings)
        # D-08: stamp the durable health row on EVERY outcome (online included below).
        stamp_health(db_path, reason=result.reason, detail=result.detail)
        if result.ok:
            return True
        if result.reason == AUTH_FAILED:
            _log.critical(
                "startup self-check auth failure",
                reason=result.reason,
                detail=result.detail,
            )
        else:
            _log.warning(
                "startup self-check not ready",
                reason=result.reason,
                detail=result.detail,
            )
        # Interruptible re-probe wait: returns True if stop was set during the wait
        # -> clean shutdown (NEVER a blocking time.sleep, anti-pattern/Pitfall 2).
        if stop.wait(RE_PROBE_INTERVAL_S):
            break
    return False


def emit_online(
    notifier: SystemdNotifier,
    *,
    db_path,
    channel: Channel | None,
    jobs: int,
) -> None:
    """Fire the one-time online signal once the self-check first passes (D-05/D-07).

    Five parts, exactly once per process start: (1) stamp the health row
    ``reason="online"`` (D-08); (2) stamp the liveness heartbeat tick (reuses the
    existing startup tick so a freshly-online daemon never shows last_tick=NULL);
    (3) a structured ``weatherbot online`` log (machine-detectable); (4) sd_notify
    ``READY=1`` (a no-op when ``NOTIFY_SOCKET`` is unset, so identical behavior
    interactively and in tests); (5) a one-time human-facing Discord ping. The ping
    is a FIXED literal with NO user/template interpolation and no ``@everyone`` /
    mention (markdown-injection-safe, T-05-T). It is best-effort: a non-ok
    ``DeliveryResult`` is logged but does NOT block startup or re-fire (D-07 — the
    daemon is online regardless of whether the human notice landed).
    """
    stamp_health(db_path, reason="online")
    stamp_tick(db_path)
    _log.info("weatherbot online", jobs=jobs)
    notifier.ready()
    if channel is not None:
        result = channel.send("WeatherBot online — startup self-check passed.")
        if result is not None and not getattr(result, "ok", True):
            _log.warning(
                "online ping not delivered",
                detail=getattr(result, "detail", ""),
            )


def run_daemon(
    config: Config,
    settings: Settings | None,
    db_path,
    *,
    client=None,
    channel: Channel | None = None,
) -> int:
    """Run the always-on scheduler in the FOREGROUND until SIGTERM / Ctrl-C (D-09).

    Order (so the log reads cleanly): register jobs → announce the schedule →
    run the catch-up scan → ``scheduler.start()``. Then block on a
    ``threading.Event`` with a SIGTERM handler + a ``KeyboardInterrupt`` catch,
    and ``scheduler.shutdown(wait=False)`` on exit. Returns 0 on a clean shutdown.
    Does NOT self-daemonize (systemd owns process liveness, Phase 5).
    """
    scheduler = BackgroundScheduler()
    # Create the shutdown Event UP FRONT so the SAME instance can be threaded into
    # every fire_slot job (live + catch-up) as the retry's interruptible sleep
    # source (D-07 / Pitfall 1) — a SIGTERM during a 45-min mid-pause aborts it.
    stop = threading.Event()

    _register_jobs(
        scheduler,
        config,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
        stop_event=stop,
    )
    # Register the periodic heartbeat tick on its own IntervalTrigger job (RELY-05,
    # D-06): a liveness ping independent of any send. Runs on the same default
    # threadpool (max_workers=10) — never starves slot jobs at a personal-bot
    # slot count (Pitfall 3). misfire_grace_time=None / coalesce=True mirror the
    # slot jobs (a missed tick is simply skipped, not stacked).
    scheduler.add_job(
        _heartbeat_tick,
        trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S),
        kwargs={"db_path": db_path},
        id="__heartbeat__",
        misfire_grace_time=None,
        coalesce=True,
    )
    _announce_schedule(scheduler, config)
    _run_catchup(
        config,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
        stop_event=stop,
    )

    def _handle(signum, frame):  # noqa: ANN001 — signal handler signature
        stop.set()

    # LOAD-BEARING ORDERING (Pitfall 2 / D-04): register the SIGTERM handler BEFORE
    # the self-check gate. The gate (`gate_until_healthy`) runs before
    # `scheduler.start()`, so a `systemctl stop`/`restart` DURING the re-probe loop
    # must already have a handler installed to set `stop` and break the loop's
    # `stop.wait(...)` — otherwise the stop is ignored until systemd escalates to
    # SIGKILL after TimeoutStopSec.
    signal.signal(signal.SIGTERM, _handle)
    notifier = SystemdNotifier()

    try:
        # STARTUP SELF-CHECK GATE (D-03): run the classified self-check and stay
        # alive re-probing on any failure (D-04) BEFORE starting the scheduler. If
        # `stop` was set during the gate (clean shutdown), fall straight through to
        # the finally without starting the scheduler or emitting the online signal.
        if not gate_until_healthy(
            stop,
            config=config,
            settings=settings,
            db_path=db_path,
            client=client,
        ):
            return 0

        scheduler.start()
        # The three-part online signal fires EXACTLY ONCE here, only after the gate
        # first passes (D-05/D-07): health=online + heartbeat tick + structured log +
        # sd_notify READY=1 + one-time Discord ping. The startup tick (IN-02) is
        # subsumed by emit_online's stamp_tick so a freshly-online daemon never shows
        # last_tick=NULL while last_success is fresh.
        emit_online(
            notifier,
            db_path=db_path,
            channel=channel,
            jobs=len(scheduler.get_jobs()),
        )
        _log.info("daemon started", jobs=len(scheduler.get_jobs()))

        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        # Only shut down a RUNNING scheduler: on the gate-stop path (clean shutdown
        # during the self-check re-probe loop) `scheduler.start()` is never reached,
        # and APScheduler's `shutdown()` raises SchedulerNotRunningError on an
        # unstarted scheduler — which would mask the clean return. `running` is False
        # until start() (default False on a fresh BackgroundScheduler).
        if getattr(scheduler, "running", True):
            scheduler.shutdown(wait=False)
        _log.info("daemon stopped")
    return 0
