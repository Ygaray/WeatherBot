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

import logging
import signal
import threading
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
import structlog
from pydantic import ValidationError
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
from yahir_reusable_bot.config import ConfigHolder, ReloadEngine
from weatherbot.config.loader import validate_config_and_templates
from weatherbot.ops.pidfile import PID_FILE, write_pid_atomic
from weatherbot.scheduler.catchup import plan_catchup
# Module-side import lives INSIDE daemon.py (NOT at weatherbot/scheduler/__init__.py
# top level): that barrel runs during weatherbot.config.models' parse_days import via
# the PEP-562 lazy run_daemon export, and an eager engine import there could
# re-introduce the import cycle the lazy export dodges (Pitfall 4).
from yahir_reusable_bot.scheduler import SchedulerEngine
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

# The project's structlog default renders to STDERR via a PrintLoggerFactory and does
# NOT route through stdlib ``logging`` (so STDOUT stays a clean pipe for the ``weather``
# one-shot — weatherbot/__init__.py). The reload OUTCOME lines (CFG-06/D-07) must also be
# capturable by the operator's standard logging pipeline (and by pytest ``caplog``, which
# hooks stdlib logging) so "what took effect" / "why it was rejected" is greppable in the
# host's journal — so they are mirrored through this stdlib logger. Outcome-only: counts +
# the validation reason, never a secret (T-04-01 / T-09-08).
_stdlog = logging.getLogger(__name__)

# Heartbeat cadence (D-06, Claude's discretion): a liveness tick every ~10 min,
# independent of any send, so a future monitor can distinguish a CRASHED process
# (stale last_tick) from one that is alive but FAILING to send (fresh last_tick,
# stale last_success). 600s is well below any reasonable staleness alarm and runs
# on the same APScheduler threadpool (default max_workers=10) — at a personal-bot
# slot count it never starves slot jobs (Pitfall 3).
HEARTBEAT_INTERVAL_S = 600

# File-watch quiet-window / debounce / teardown constants (Phase 10, D-05). These are
# MODULE constants, NOT config surface (D-05 rejected exposing the debounce window).
# Mapped onto watchfiles' watch() params (RESEARCH Pattern 2):
#   - WATCH_QUIET_MS (step): wait this long for new changes; if none arrive AND >=1
#     change was seen, YIELD. This is the D-05 ~400ms quiet window that coalesces a
#     truncate-write / temp-then-rename / multi-event editor save into ONE reload
#     (SC#2 / Pitfall #2). watchfiles' default step=50 is too tight — a slow editor
#     save can have a >50ms inter-event gap and yield twice.
#   - WATCH_DEBOUNCE_MS (debounce): the upper bound on grouping a never-quiescing
#     storm before forcing a yield (watchfiles default).
#   - WATCH_RUST_TIMEOUT_MS (rust_timeout): bounds how often the blocking Rust loop
#     returns to Python to re-check stop_event / the re-derived watch dirs. Set to 500
#     (NOT the 5000 default) so a SIGTERM-driven stop.set() tears the observer down
#     sub-second instead of hanging up to ~5s (Pitfall #2 / SC#3 teardown).
WATCH_QUIET_MS = 400
WATCH_DEBOUNCE_MS = 1600
WATCH_RUST_TIMEOUT_MS = 500

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
    holder: ConfigHolder | None = None,
    config: Config | None = None,
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
        # Single-read-per-fire (SC#2 / D-01 / Pitfall #9): resolve the config
        # snapshot EXACTLY ONCE at the top and thread that same object through the
        # whole fetch→render→persist→send lifecycle (the reliability budget read AND
        # send_now(config=snapshot)). An explicit ``config=`` override WINS over the
        # holder (existing config=-only callers keep working); otherwise read
        # ``holder.current()`` once — a mid-fire ``replace()`` can never tear this
        # delivery because the running job never re-reads.
        if config is not None:
            snapshot = config
        elif holder is not None:
            snapshot = holder.current()
        else:
            raise ValueError("fire_slot requires holder= or config=")

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
        if not claim_slot(db_path, location.id, slot.time, local_date):
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
            attempts_per_burst=snapshot.reliability.attempts_per_burst,
            burst_spread_s=snapshot.reliability.burst_spread_seconds,
            mid_pause_s=snapshot.reliability.mid_pause_seconds,
        )

        def _attempt() -> DeliveryResult:
            # Let the fetch ``httpx.HTTPStatusError`` (carrying ``.response`` with
            # the ``Retry-After`` header) PROPAGATE so Plan 01's wait callable can
            # honor the capped Retry-After (RELY-02). Do NOT translate/strip it.
            return send_now(
                location.name,
                config=snapshot,
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
            release_claim(db_path, location.id, slot.time, local_date)
            claimed = False
            reason = (
                REASON_AUTH_FAILED
                if is_auth_failure(exc)
                else REASON_TRANSIENT_EXHAUSTED
            )
            self_first = record_alert(
                db_path, location.id, slot.time, local_date, reason
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
            release_claim(db_path, location.id, slot.time, local_date)
            claimed = False
            self_first = record_alert(
                db_path,
                location.id,
                slot.time,
                local_date,
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
            release_claim(db_path, location.id, slot.time, local_date)
            claimed = False
            self_first = record_alert(
                db_path,
                location.id,
                slot.time,
                local_date,
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
        resolve_alert(db_path, location.id, slot.time, local_date)
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
            release_claim(db_path, location.id, slot.time, local_date)
        if local_date is not None:
            self_first = record_alert(
                db_path,
                location.id,
                slot.time,
                local_date,
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


# WR-05: a SCHEDULED forecast is off the exactly-once SQLite path (read-only, no
# claim/catch-up) — correct — but ``fire_forecast_slot`` swallowing EVERY failure
# with only an ERROR log means a chronically-dead slot (persistent channel auth
# failure, a renamed location, etc.) never delivers and emits NO operator-visible
# signal, weaker than the project's "retry then alert rather than silently miss"
# constraint. We keep isolation intact (the failure is STILL swallowed and never
# touches a briefing) but DISTINGUISH a one-off transient from a persistent failure:
# a per-slot in-memory consecutive-failure streak that, once it crosses
# ``_FORECAST_DEAD_AFTER``, escalates to a CRITICAL log + a THROTTLED best-effort
# operator channel notice. This is purely in-process state (zero store writes — the
# forecast path's read-only discipline is preserved). A successful fire resets the
# streak. State is keyed by the same ``_forecast_job_id`` so editing/removing a slot
# naturally starts a fresh streak.
_FORECAST_DEAD_AFTER = 3  # consecutive failures before a slot is "chronically dead"
_forecast_failure_streaks: dict[str, int] = {}


def _note_forecast_failure(
    location: Location,
    fc,  # noqa: ANN001 — ForecastSchedule
    *,
    channel: Channel | None,
) -> None:
    """Bump the slot's failure streak and, when chronic, alert operator-visibly (WR-05).

    In-process only (no store write — read-only discipline preserved). On the fire
    that first crosses ``_FORECAST_DEAD_AFTER`` consecutive failures, emit a CRITICAL
    ``forecast_slot_dead`` log (machine-detectable, mirroring the briefing's
    ``briefing_missed``) and a single best-effort operator channel notice. The notice
    is throttled to fire ONCE per dead-streak (only on the crossing fire), so a
    forecast that fails every day does not spam the channel. The channel post is
    wrapped in its own try/except so a post failure is swallowed — it must NEVER
    re-raise out of the isolation envelope.
    """
    job_id = _forecast_job_id(location, fc)
    streak = _forecast_failure_streaks.get(job_id, 0) + 1
    _forecast_failure_streaks[job_id] = streak
    if streak == _FORECAST_DEAD_AFTER:
        # Crossing fire: escalate ONCE (== not >=) so the CRITICAL log + channel
        # notice fire exactly once per dead-streak, not on every subsequent failure.
        _log.critical(
            "forecast_slot_dead",
            location=location.name,
            kind=fc.kind,
            variant=fc.variant,
            time=fc.time,
            consecutive_failures=streak,
            severity="critical",
        )
        if channel is not None:
            try:
                channel.send(
                    f"⚠️ scheduled {fc.kind} forecast for {location.name} "
                    f"({fc.time}) has failed {streak} times in a row — it is "
                    f"not being delivered. Check the bot logs."
                )
            except Exception:  # noqa: BLE001 — best-effort alert; never re-raise
                _log.warning("forecast dead-slot alert post failed")


def _note_forecast_success(location: Location, fc) -> None:  # noqa: ANN001 — ForecastSchedule
    """Reset the slot's failure streak after a successful fire (WR-05)."""
    _forecast_failure_streaks.pop(_forecast_job_id(location, fc), None)


def fire_forecast_slot(
    location: Location,
    fc,  # noqa: ANN001 — ForecastSchedule (avoid an import cycle at module top)
    *,
    holder: ConfigHolder | None = None,
    config: Config | None = None,
    db_path=None,
    settings: Settings | None = None,
    client=None,
    channel: Channel | None = None,
    stop_event=None,
) -> None:
    """Deliver one SCHEDULED multi-day forecast — read-only, failure-isolated (FCAST-05/06).

    Mirrors :func:`fire_slot`'s structure MINUS the store/claim writes:

    1. resolves the config snapshot EXACTLY ONCE (an explicit ``config=`` override
       wins; otherwise ``holder.current()``) — a mid-fire ``replace()`` never tears
       this delivery;
    2. routes the request through the SAME on-demand render path the ``!weekday-forecast``
       / ``!weekend-forecast`` commands use (``lookup_forecast`` + the ``forecast``
       handler) so scheduled and on-demand output are IDENTICAL — the variant comes from
       ``fc.variant`` and the kind from ``fc.kind`` with NO additive day flags (a
       scheduled slot has a fixed variant, D-05);
    3. POSTs the rendered text to the ``channel`` via ``send`` (a forecast is plain text,
       not a briefing embed).

    It calls NEITHER ``claim_slot``/``release_claim`` NOR any store write (A1
    no-claim/no-catchup, FCAST-05) — a scheduled forecast is read-only and is NOT on the
    exactly-once SQLite path. Reuses the already-fetched dual One Call payload via
    ``lookup_forecast`` (FCAST-07 — no ``client.py`` change, no extra endpoint).

    The WHOLE body is wrapped in a ``try/except`` that LOGS and returns ``None`` so one
    bad forecast can NEVER crash the scheduler thread or gate/delay a briefing fire
    (UV-06-style isolation, T-13-15). Returns ``None`` always (no DeliveryResult — the
    forecast path records nothing).
    """
    try:
        # Single-read-per-fire (mirror fire_slot): an explicit ``config=`` override
        # WINS; otherwise read ``holder.current()`` ONCE so a mid-fire reload can never
        # tear this delivery.
        if config is not None:
            snapshot = config
        elif holder is not None:
            snapshot = holder.current()
        else:
            raise ValueError("fire_forecast_slot requires holder= or config=")

        # Lazy imports: the interactive package is dragged in while ``weatherbot.cli``
        # is still initializing (same cycle fire_slot's send_now import dodges), so keep
        # these in-function.
        from weatherbot.interactive.command import ForecastFlags
        from weatherbot.interactive.commands.forecast import (
            weekday_forecast,
            weekend_forecast,
        )
        from weatherbot.interactive.lookup import lookup_forecast

        # Reuse the already-fetched dual One Call payload (FCAST-07): lookup_forecast
        # delegates to lookup_weather, which performs the dual imperial+metric fetch and
        # retains both raw payloads the handler reads. No extra OpenWeather call.
        result = lookup_forecast(
            location.name,
            config=snapshot,
            settings=settings,
            client=client,
        )

        # A scheduled slot has a FIXED variant and no on-demand +day/-day overrides
        # (D-05): empty add/drop, the configured variant.
        flags = ForecastFlags(variant=fc.variant)
        handler = weekday_forecast if fc.kind == "weekday" else weekend_forecast
        reply = handler(result, flags)

        if channel is not None:
            channel.send(reply.text)
        # WR-05: a clean delivery resets the slot's failure streak so a future
        # transient blip starts counting from zero (only a CONSECUTIVE run of
        # failures is "chronically dead").
        _note_forecast_success(location, fc)
        _log.info(
            "forecast slot fired",
            location=location.name,
            kind=fc.kind,
            variant=fc.variant,
            time=fc.time,
        )
        return None
    except Exception:  # noqa: BLE001 — one bad forecast must not kill the thread
        # Outcome-only log (T-13-19): location/kind/variant/time + the traceback — never
        # the appid/webhook (those stay inside the injected client/channel). Swallow so
        # the APScheduler worker SURVIVES and every briefing job keeps firing (T-13-15).
        _log.exception(
            "forecast slot fire failed",
            location=location.name,
            kind=fc.kind,
            variant=fc.variant,
            time=fc.time,
        )
        # WR-05: bump the per-slot failure streak; once it crosses the dead-slot
        # threshold this emits a throttled CRITICAL log + best-effort operator
        # channel alert so a chronically-dead forecast slot is discoverable without
        # tailing logs. In-process only (no store write — read-only discipline
        # preserved) and STILL swallowed — isolation from the briefing spine is
        # untouched. The bookkeeping itself is guarded so a bug in it can never
        # break the isolation envelope.
        try:
            _note_forecast_failure(location, fc, channel=channel)
        except Exception:  # noqa: BLE001 — dead-slot bookkeeping must never re-raise
            _log.warning("forecast dead-slot bookkeeping failed")
        return None


def _forecast_job_id(location: Location, fc) -> str:  # noqa: ANN001 — ForecastSchedule (avoid import cycle)
    """The stable, namespaced APScheduler id for one scheduled forecast slot (FCAST-06).

    ``f"{location.name}|fc|{fc.kind}|{fc.variant}|{fc.time}|{fc.days}"`` — the ``|fc|``
    segment is the anti-collision namespace (Pitfall 4): a briefing's id is
    ``name|time|days``, so a forecast and a briefing at the SAME ``time``/``days`` can
    NEVER produce the same id. ``kind``/``variant`` are part of the id so editing
    either (e.g. detailed->compact) yields a DIFFERENT id, which the reconcile diffs as
    one ADD (new id) + one REMOVE (old id) — the same edit-as-new-slot semantics the
    briefing's ``time``/``days`` id already has (D-06).

    This is the SINGLE source of the forecast id: BOTH :func:`_register_jobs` (the
    enumeration that creates the job) and :func:`_desired_job_ids` (the reconcile's
    desired set) call it, so the registered id and the desired id can never drift apart.
    """
    return f"{location.name}|fc|{fc.kind}|{fc.variant}|{fc.time}|{fc.days}"


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
    holder: ConfigHolder,
    *,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
    stop_event=None,
    replace_existing: bool = False,
) -> None:
    """Register one CronTrigger job per ENABLED slot at the location's own tz (Pattern 1).

    Disabled slots produce NO job (SCHD-02 toggle). Each trigger is pinned to the
    LOCATION's IANA ``timezone`` so it fires at that place's local wall-clock time
    (SCHD-04). ``misfire_grace_time=None`` because cross-restart recovery is owned
    by the sent-log + catch-up scan, not APScheduler (Anti-Pattern); ``coalesce``
    is a harmless backstop. The job ``id`` keys on ``name|time|days`` (D-06: editing
    a time = a new slot).

    The slot ENUMERATION reads ``holder.current()`` once (the structure at
    registration time); each job's per-fire ``kwargs`` carry the ``holder`` itself
    (NOT a baked-in ``config``), so an UNCHANGED job re-reads ``holder.current()`` at
    every fire — a later ``replace()`` changes what it renders (D-03/D-04).

    ``replace_existing`` is ``False`` at first startup (a fresh scheduler has no
    jobs); the reload reconcile (:func:`_reconcile_jobs`) calls it with ``True`` so
    re-registering an already-live id is an idempotent swap, not a ConflictingIdError.
    """
    config = holder.current()
    # Thin non-owning registrar over the host-built scheduler (D-15): the enumeration
    # loop below STAYS app-side (the Phase-24 desired_jobs seed); only the per-job
    # add_job call routes through engine.register, which bakes the three invariant
    # job-options (misfire_grace_time=None / coalesce=True / max_instances=1) in once.
    engine = SchedulerEngine(scheduler)
    for location in config.locations:
        for slot in location.schedule:
            if not slot.enabled:
                continue
            hh, mm = slot.parsed_time()
            engine.register(
                f"{location.name}|{slot.time}|{slot.days}",
                CronTrigger(
                    hour=hh,
                    minute=mm,
                    day_of_week=slot.day_of_week,
                    timezone=location.timezone,
                ),
                fire_slot,
                args=[location, slot],
                kwargs={
                    "holder": holder,
                    "db_path": db_path,
                    "settings": settings,
                    "client": client,
                    "channel": channel,
                    # The SAME daemon stop Event whose ``.wait`` is the retry's
                    # ``sleep=`` — so a SIGTERM during the 45-min mid-pause aborts
                    # the in-progress retry cleanly (D-07 / Pitfall 1).
                    "stop_event": stop_event,
                },
                replace_existing=replace_existing,
            )

        # SCHEDULED FORECAST SLOTS (FCAST-06): a SECOND enumeration loop, mirroring
        # the briefing loop above but targeting ``fire_forecast_slot`` and the
        # namespaced ``_forecast_job_id``. Disabled slots produce NO job (toggle).
        # Each trigger is pinned to the LOCATION's own tz (per-place wall-clock) and
        # registered with the SAME ``misfire_grace_time=None``/``coalesce=True`` as a
        # briefing — forecasts are read-only so there is no claim/catch-up to recover,
        # a missed forecast is simply skipped. The job carries the ``holder`` (not a
        # baked config) so a later ``replace()`` swaps what it renders, and the SAME
        # ``_forecast_job_id`` is used here AND in ``_desired_job_ids`` (no drift).
        for fc in location.forecast:
            if not fc.enabled:
                continue
            fhh, fmm = fc.parsed_time()
            engine.register(
                _forecast_job_id(location, fc),
                CronTrigger(
                    hour=fhh,
                    minute=fmm,
                    day_of_week=fc.day_of_week,
                    timezone=location.timezone,
                ),
                fire_forecast_slot,
                args=[location, fc],
                kwargs={
                    "holder": holder,
                    "db_path": db_path,
                    "settings": settings,
                    "client": client,
                    "channel": channel,
                    "stop_event": stop_event,
                },
                replace_existing=replace_existing,
            )


def _desired_job_ids(holder: ConfigHolder) -> set[str]:
    """The stable job-id set the CURRENT config wants live (enabled slots only).

    Mirrors :func:`_register_jobs` enumeration EXACTLY — same
    ``name|time|days`` id, same enabled-slot filter — so the reconcile diff keys on
    the identical identity. ``__heartbeat__`` is the daemon's internal job and is
    NEVER in this set (it is excluded from the reconcile on the live side too).
    """
    config = holder.current()
    briefing_ids = {
        f"{location.name}|{slot.time}|{slot.days}"
        for location in config.locations
        for slot in location.schedule
        if slot.enabled
    }
    # The forecast desired set uses the SAME ``_forecast_job_id`` + enabled filter as
    # ``_register_jobs`` (byte-for-byte), so an enabled forecast slot reconciles
    # churn-free and a disabled/edited slot diffs correctly (Pitfall 4 — no drift).
    forecast_ids = {
        _forecast_job_id(location, fc)
        for location in config.locations
        for fc in location.forecast
        if fc.enabled
    }
    return briefing_ids | forecast_ids


def _register_uvmonitor_job(
    scheduler: BackgroundScheduler,
    holder: ConfigHolder,
    *,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
) -> None:
    """Register the proactive UV monitor on its own IntervalTrigger job (UV-04, Plan 15-03).

    Gated on ``snapshot.uv.monitor_enabled`` (default on) AT STARTUP: when false at
    startup NO ``__uvmonitor__`` job is registered (the briefing spine + heartbeat
    are untouched). When true, Plan 15-02's :func:`_uv_monitor_tick` is registered on
    an ``IntervalTrigger`` at ``snapshot.uv.interval_seconds``, threading the SAME
    ``holder``/``db_path``/``settings``/``client``/``channel`` instances the briefing
    jobs use (one channel/client per process). The tick re-reads ``holder.current()``
    every fire, so threshold/lead/margin edits are LIVE via a config reload; only
    ``interval_seconds`` is restart-deferred (DP-2) — it is baked into the trigger at
    registration here and a reload does NOT re-register this job (see
    :func:`_reconcile_jobs`, which excludes ``__uvmonitor__`` by id like
    ``__heartbeat__``).

    ``monitor_enabled`` is ALSO honored LIVE (WR-03): the registered job stays
    registered across a reload, but :func:`_uv_monitor_tick` short-circuits when the
    live snapshot's ``monitor_enabled`` is false, so disabling via reload stops the
    polling without a restart. (Enabling from a startup-disabled state still needs a
    restart, since no job exists to re-read the flag.)

    ``misfire_grace_time=None`` / ``coalesce=True`` mirror the slot + heartbeat jobs
    (a missed tick is skipped, not stacked). ``max_instances=1`` (Pitfall 4 / T-15-10)
    guarantees a slow tick can never stack a second concurrent run.
    """
    snapshot = holder.current()
    if not snapshot.uv.monitor_enabled:
        return
    # Lazy in-function import (cycle-safe, mirrors the build_channel / send_now import
    # discipline): keeps uvmonitor's transitive imports off the daemon module's
    # import-time graph and avoids a daemon<->uvmonitor import cycle.
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    # Route through the engine like every other job (D-04): the three invariant
    # options (incl. max_instances=1, formerly passed explicitly here) now live in
    # engine.register — its baked default-of-1 is byte-identical (Plan 01 read-back).
    engine = SchedulerEngine(scheduler)
    engine.register(
        "__uvmonitor__",
        IntervalTrigger(seconds=snapshot.uv.interval_seconds),
        _uv_monitor_tick,
        kwargs={
            "holder": holder,
            "db_path": db_path,
            "settings": settings,
            "client": client,
            "channel": channel,
        },
    )


def _reconcile_jobs(
    scheduler: BackgroundScheduler,
    holder: ConfigHolder,
    *,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
    stop_event=None,
) -> tuple[int, int, int, int]:
    """Diff-reconcile APScheduler jobs to ``holder.current()`` on the stable id (Pattern 4).

    Returns ``(added, removed, changed, unchanged)``. The DESIRED set is the current
    config's enabled-slot ids (:func:`_desired_job_ids`); the LIVE set is
    ``scheduler.get_jobs()`` EXCLUDING ``__heartbeat__``. For every desired id we
    ``add_job(..., replace_existing=True)`` — a brand-new id counts as ADDED, an
    already-live id counts as UNCHANGED (it rides the holder swap: the job's kwargs
    carry the holder, not a baked config, so its content auto-updates). Every live id
    not desired is ``remove_job``'d (REMOVED) — never a wholesale clear-and-rebuild.

    A ``send_time``/``days`` edit yields a DIFFERENT id, so it surfaces as one ADD
    (new id) + one REMOVE (old id) — the new-time job is created and fires today if
    ahead (amended D-02 / RESEARCH A3); it is NOT suppressed. ``changed`` is reserved
    for a same-id trigger/kwargs delta — content edits ride the holder swap in this
    codebase, so it is 0 here (kept in the tuple for the diff-summary contract).

    The ADD/replace phase delegates to :func:`_register_jobs` (with
    ``replace_existing=True``) so registration uses the ONE canonical job-builder; the
    REMOVE phase deletes every live id the desired set dropped. A wholesale
    clear-and-rebuild of the job table is NEVER used.
    """
    # Exclude BOTH daemon-internal IntervalTrigger jobs from the reconcile diff: the
    # ``__heartbeat__`` liveness ping AND the ``__uvmonitor__`` UV poll (Plan 15-03 /
    # T-15-11). Neither is a briefing slot, so leaving them out of ``live_ids`` means a
    # reload never removes or duplicates them — the monitor's restart-deferred interval
    # (DP-2) is preserved across a SIGHUP reload.
    # Read live ids through the engine; the __heartbeat__/__uvmonitor__ exclusion
    # stays an APP-side convention the engine never learns (D-04).
    engine = SchedulerEngine(scheduler)
    live_ids = {
        jid
        for jid in engine.list_live_ids()
        if jid not in ("__heartbeat__", "__uvmonitor__")
    }
    desired_ids = _desired_job_ids(holder)

    added = len(desired_ids - live_ids)
    unchanged = len(desired_ids & live_ids)
    changed = 0

    # ADD/replace every desired (enabled) slot via the canonical builder. An
    # already-live id is an idempotent swap (rides the holder); a new id is created.
    _register_jobs(
        scheduler,
        holder,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
        stop_event=stop_event,
        replace_existing=True,
    )

    # REMOVE every live id the new config no longer wants (deleted or disabled). A
    # send_time/days change drops the OLD id here (its NEW id was added above).
    removed = 0
    for job_id in live_ids - desired_ids:
        engine.remove(job_id)
        removed += 1

    return added, removed, changed, unchanged


def _restore_jobs(
    scheduler: BackgroundScheduler,
    old_cfg: Config,
    *,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
    stop_event=None,
) -> None:
    """Deterministically rebuild the OLD job set from ``old_cfg`` (rollback, Pitfall 7).

    Wraps ``old_cfg`` in a transient :class:`ConfigHolder` and reuses
    :func:`_reconcile_jobs` against it, so the live job set is reconciled back to
    exactly what ``old_cfg`` wants — re-adding the old jobs via
    ``add_job(replace_existing=True)`` and removing any half-applied new id. The
    daemon-internal ``__heartbeat__`` and ``__uvmonitor__`` jobs are excluded by id in
    the reconcile and are left alone (a rollback never tears them down either).
    """
    transient = ConfigHolder(old_cfg)
    _reconcile_jobs(
        scheduler,
        transient,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
        stop_event=stop_event,
    )


def _do_reload(
    config: Config | None = None,
    *,
    config_path: str | Path | None = None,
    holder: ConfigHolder,
    scheduler: BackgroundScheduler,
    db_path,
    settings: Settings | None = None,
    client=None,
    channel: Channel | None = None,
    stop_event=None,
    watch_dirs_ref=None,
    cache=None,
) -> None:
    """Two-phase build-then-commit reload: validate-or-keep-old, swap, reconcile, rollback.

    PHASE 1 (validate-or-keep-old, CFG-04/CFG-06): when ``config_path`` is given,
    re-read + validate it via the ONE shared offline validator
    :func:`~weatherbot.config.loader.validate_config_and_templates`. On ANY validator
    raise (``FileNotFoundError``/``tomllib.TOMLDecodeError``/``ValidationError``/
    ``ValueError``) log the reason and RE-RAISE with the live holder + job set
    UNTOUCHED — the rejected config never swaps (keep-old). A pre-validated ``config``
    object (the in-process callers/tests) skips PHASE 1.

    PHASE 2 (atomic swap + diff-reconcile, Pitfall 6/7): snapshot ``old_cfg``,
    ``holder.replace(new_cfg)``, then :func:`_reconcile_jobs` on the stable id. On ANY
    reconcile throw, ROLL BACK all-or-nothing — ``holder.replace(old_cfg)`` and
    :func:`_restore_jobs` rebuild the old job set from ``old_cfg`` — then re-raise so
    the caller sees the failure with the OLD schedule fully intact.

    On success log the ``+a -r ~c =u`` diff summary (CFG-06/D-07). This engine
    constructs NO :class:`Settings` and NEVER touches the systemd READY gate / .env
    (D-04 / Pitfall 12) — the restart boundary is untouched on a reload.
    """
    # PHASE 1 — validate-or-keep-old. A config PATH is re-read + validated; the
    # established catch set is logged + re-raised, leaving holder/jobs untouched.
    if config_path is not None:
        try:
            new_cfg = validate_config_and_templates(config_path)
        except (
            FileNotFoundError,
            tomllib.TOMLDecodeError,
            ValidationError,
            ValueError,
        ) as exc:
            _log.error("reload rejected", reason=str(exc))
            _stdlog.error("reload rejected: %s", exc)
            # CFG-07 (D-13): post the validation reason in-channel so the operator
            # learns WHY the edit was refused without tailing logs. Best-effort,
            # mirroring emit_online's guard: wrapped in its own try/except so a
            # channel.send failure is logged and swallowed — the ORIGINAL validation
            # error below is the one re-raised, keeping the keep-old contract intact.
            if channel is not None:
                try:
                    channel.send(f"⛔ config reload rejected: {exc}")
                except Exception:  # noqa: BLE001 — best-effort post; never mask the validation error
                    _log.warning(
                        "reload-rejected post failed; original error re-raised"
                    )
            raise
    elif config is not None:
        new_cfg = config
    else:
        raise ValueError("_do_reload requires config= or config_path=")

    # PHASE 2 — atomic swap + diff-reconcile, all-or-nothing rollback on any throw.
    old_cfg = holder.current()
    holder.replace(new_cfg)
    try:
        added, removed, changed, unchanged = _reconcile_jobs(
            scheduler,
            holder,
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            stop_event=stop_event,
        )
    except Exception:
        # Roll back to the previous config AND rebuild the old job set from it, then
        # re-raise so the OLD schedule fires fully intact (Pitfall 6/7). Because the
        # reconcile ADDs (replace_existing) BEFORE it REMOVEs, a throw in the add
        # phase leaves the old jobs untouched; the restore is a best-effort rebuild
        # that must never mask the ORIGINAL reconcile error.
        holder.replace(old_cfg)
        try:
            _restore_jobs(
                scheduler,
                old_cfg,
                db_path=db_path,
                settings=settings,
                client=client,
                channel=channel,
                stop_event=stop_event,
            )
        except Exception:  # noqa: BLE001 — restore is best-effort; surface the real cause
            _log.exception("reload rollback restore raised; original error re-raised")
        _log.error("reload reconcile failed; rolled back to previous config")
        _stdlog.error("reload reconcile failed; rolled back to previous config")
        raise

    summary = f"+{added} -{removed} ~{changed} ={unchanged}"
    _log.info(
        "reload applied",
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        summary=summary,
    )
    _stdlog.info("reload applied %s", summary)

    # CFG-07 (D-13): post the structured outcome in-channel so the operator sees
    # exactly what took effect (the same ``+a -r ~c =u`` token the log reports),
    # as PLAIN text distinct from the rich briefing embed. Capture the ``summary``
    # tuple directly — never scrape the log line. Best-effort, mirroring
    # emit_online's guard: a channel.send failure is logged and swallowed and MUST
    # NOT abort the already-succeeded reload (the swap is already committed above).
    if channel is not None:
        try:
            channel.send(f"✅ config reloaded: {summary}")
        except Exception:  # noqa: BLE001 — best-effort post; reload already succeeded
            _log.warning("reload-applied post failed; reload unaffected")

    # CR-01 (Pattern 4): invalidate the bot's ForecastCache in the COMMITTED-SUCCESS
    # branch ONLY — after ``holder.replace`` + ``_reconcile_jobs`` have committed above
    # — so the next ``!weather <loc>`` refetches against the freshly reloaded config and
    # never serves a pre-reload forecast for up to the TTL (D-12, ~10 min). Best-effort,
    # mirroring the emit_online / CFG-07 post idiom: an ``invalidate()`` error is logged
    # (outcome-only, no secret) and SWALLOWED so it can NEVER abort an already-committed
    # reload. ``cache`` is None for the validation-reject and rollback paths' callers and
    # whenever the daemon ran without ``settings`` — the guard tolerates both.
    if cache is not None:
        try:
            cache.invalidate()
        except Exception:  # noqa: BLE001 — best-effort; reload already committed
            _log.warning("forecast cache invalidate failed; reload unaffected")

    # D-04: re-derive the watch set AFTER a SUCCESSFUL swap so a template that moved to
    # a NEW directory becomes watched without a restart. This ONLY mutates the shared
    # watch_dirs_ref[0] cell — it MUST NOT construct a second observer thread or call
    # watch() directly (A4 / Pitfall #3): the single _run_watch_observer thread picks
    # up the new dirs by detecting the changed cell on its next empty timeout tick,
    # breaking out of its current watch() generator, and re-entering watch() with the
    # new dirs (releasing the old inotify fds on exhaustion — no fd leak across re-derive).
    # No-ops for SIGHUP/CLI and Phase-9 callers, where watch_dirs_ref defaults to None.
    if watch_dirs_ref is not None and config_path is not None:
        watch_dirs_ref[0] = _derive_watch_dirs(new_cfg, Path(config_path))


def _announce_schedule(scheduler: BackgroundScheduler, holder: ConfigHolder) -> None:
    """Log every registered slot + its computed next_run_time (D-10).

    Outcome-only logging: ``location``/``time``/``days``/``next_run_time`` — never
    a secret. Announce runs BEFORE ``scheduler.start()`` (so the log reads cleanly),
    and a not-yet-started APScheduler job has no ``next_run_time`` attribute yet —
    so the next fire is computed straight from the job's CronTrigger, which is
    tz-aware in the location's own zone (the proof the per-location wall-clock
    firing works).
    """
    from datetime import datetime

    config = holder.current()
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
    holder: ConfigHolder,
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

    Reads ``holder.current()`` ONCE to drive the PURE-INPUT ``plan_catchup`` planner
    (catchup.py stays config-in/missed-out — Assumption A3), then fires each missed
    slot via ``fire_slot(holder=holder, ...)`` so each recovered send resolves the
    live snapshot at its own fire time.
    """
    config = holder.current()
    missed = plan_catchup(
        config,
        lambda name, time, date: was_sent(db_path, name, time, date),
    )
    for ms in missed:
        fire_slot(
            ms.location,
            ms.slot,
            holder=holder,
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


def _referenced_template_names(config: Config) -> set[str]:
    """Every template filename the config references: the briefing + all forecast slots.

    The briefing template (``config.template``) PLUS, for every ``location.forecast``
    slot, the whole-message + sibling per-day line template of its ``(kind, variant)``
    (resolved via the renderer's single source of truth). Both watch helpers
    (:func:`_derive_watch_dirs` / :func:`_make_watch_filter`) build their watched set
    from THIS function so editing ANY referenced template — briefing or forecast —
    triggers a reload, while the validated set (loader) and the watched set never drift
    (Pitfall 5 / Plan 13-05).
    """
    from templates.renderer import FORECAST_TEMPLATE_NAMES

    names: set[str] = {config.template}
    for location in config.locations:
        for fc in location.forecast:
            whole_name, line_name = FORECAST_TEMPLATE_NAMES[(fc.kind, fc.variant)]
            names.add(whole_name)
            names.add(line_name)
    return names


def _derive_watch_dirs(config: Config, config_path: str | Path) -> set[Path]:
    """Derive the set of DIRECTORIES to watch: ``config.toml``'s dir + ``TEMPLATES_DIR``.

    Watch DIRECTORIES, never the files themselves (Pitfall #11c): an atomic
    temp-then-rename save SWAPS the file inode, so a watch pinned to the file goes
    deaf — only a directory watch survives the rename. The referenced-template set is
    built over the SAME ``{config.template}`` contract that
    :func:`~weatherbot.config.loader.validate_config_and_templates` uses (loader.py),
    so the watched set and the validated set never drift; building over a SET means a
    future per-location-template model extends this for free (Assumption A3).

    Called once at startup and RE-CALLED on each successful reload (D-04) so a template
    moved to a new directory becomes watched without a restart.
    """
    # Lazy in-function import (mirrors the loader idiom + build_channel): keeps the
    # renderer's transitive import graph off the daemon module's import-time path.
    from templates.renderer import TEMPLATES_DIR

    dirs: set[Path] = {Path(config_path).resolve().parent}
    # Every referenced template (briefing AND forecast, Plan 13-05) lives under the
    # SAME TEMPLATES_DIR today, so watching that one directory covers them all. The
    # iteration is kept so a future per-location-template model that moves a template
    # to a new directory extends this for free (Assumption A3).
    for _template_name in _referenced_template_names(config):
        dirs.add(Path(TEMPLATES_DIR).resolve())
    return dirs


def _make_watch_filter(config: Config, config_path: str | Path):
    """Build the ``watch_filter`` callable: match ONLY config.toml + referenced templates.

    The filter is the HARD secrets boundary (Pitfall #12 / T-10-02): a ``.env`` (or any
    other file) saved in the watched directory must produce ZERO reloads — secrets are a
    restart boundary, never hot-reloaded. watchfiles calls the filter as
    ``filter(change, path) -> bool``; we accept a change ONLY when the changed path's
    BASENAME is the config filename (``Path(config_path).name``) or one of the referenced
    template filenames (the ``{config.template}`` set). Everything else — ``.env``,
    dotfiles, editor temp/backup files — is rejected.
    """
    allowed = {Path(config_path).name}
    for _template_name in _referenced_template_names(config):
        allowed.add(Path(_template_name).name)

    def _watch_filter(_change, path) -> bool:  # noqa: ANN001 — watchfiles filter signature
        # Match on basename only: directory-watch yields absolute paths, but the
        # allow-list is filenames (config.toml + referenced templates). A `.env` edit
        # never matches → ZERO reloads (Pitfall #12).
        return Path(path).name in allowed

    return _watch_filter


def _run_watch_observer(watch_dirs_ref, request_reload, stop, *, watch_filter) -> None:
    """The file-watch observer loop: run the blocking ``watch()`` and flag-set ONLY.

    Runs in its own daemon thread (started in :func:`run_daemon`). On each settled,
    NON-EMPTY change-set it calls the zero-arg ``request_reload`` seam, which ONLY
    ``.set()``s the existing ``reload_requested`` Event (D-02) — the file-watch analog
    of :func:`_install_reload_signal`'s ``_handle_hup``. The actual reload work
    (validate/swap/reconcile) NEVER runs here; it runs on the MAIN poll-loop thread via
    :func:`_do_reload` (Pitfall #6/#9 — no re-entrant reload on the observer thread).

    ``watch_dirs_ref`` is a one-element box holding the current watch-dir set. Each outer
    iteration snapshots it and opens one ``watch()`` generator on that snapshot; on an
    empty timeout-tick yield the loop compares the live ``watch_dirs_ref[0]`` against the
    snapshot and, when a reload re-derived the set (D-04), BREAKS out of the generator so
    the outer loop re-enters ``watch()`` with the new dirs (``watch(..., yield_on_timeout=
    True)`` never returns on its own while ``stop`` is clear, so this break is what makes
    a live re-watch possible). The single long-lived ``watch()`` generator (one observer
    for the process, Pitfall #11a) is given ``stop_event=stop`` + ``rust_timeout=500`` +
    ``yield_on_timeout=True`` so a SIGTERM-driven ``stop.set()`` is honored sub-second and
    an empty timeout-tick yield lets the loop re-check ``stop`` and the watch set. The
    watch is ``recursive=False`` (the design watches the specific config + TEMPLATES_DIR
    directories, not their subtrees, so a basename-colliding file in a subdirectory cannot
    trigger a spurious reload, WR-01).
    """
    # Lazy in-function import (mirrors build_channel): keeps watchfiles' Rust-binary
    # transitive imports off the daemon module's import-time graph.
    from watchfiles import watch

    while not stop.is_set():
        # A4: re-enter the single watch() generator with the re-derived dirs (no second
        # observer). The re-entry is driven by the inner-loop break below: on a timeout
        # tick we compare the live watch_dirs_ref[0] against the snapshot this generator
        # was opened on, and break out of the (otherwise non-returning) watch() generator
        # when they differ — so the generator is exhausted, its inotify fds released, and
        # this outer loop re-enters watch() with the new dirs (fd count stays flat across
        # a watch-set re-derive). watch(..., yield_on_timeout=True) never returns on its
        # own while stop is clear, so without this break the re-derived dirs would never
        # be picked up live (the D-04 contract).
        dirs_snapshot = frozenset(watch_dirs_ref[0])
        for _changes in watch(
            *tuple(dirs_snapshot),
            step=WATCH_QUIET_MS,
            debounce=WATCH_DEBOUNCE_MS,
            rust_timeout=WATCH_RUST_TIMEOUT_MS,
            yield_on_timeout=True,
            watch_filter=watch_filter,
            stop_event=stop,
            recursive=False,
        ):
            if stop.is_set():
                return
            if _changes:
                request_reload()
            # An empty set is a timeout tick (yield_on_timeout). On a timeout tick, check
            # whether the watch set was re-derived on a reload (D-04); if so, drop this
            # generator so the outer loop re-enters watch() with the new dirs.
            elif frozenset(watch_dirs_ref[0]) != dirs_snapshot:
                break
        # watch() returned (stop fired) or we broke out (watch-set re-derived): re-check
        # stop, then the outer loop re-reads watch_dirs_ref and re-enters watch().
        if stop.is_set():
            return


def _install_reload_signal() -> threading.Event:
    """Install the ``SIGHUP`` handler and return the ``reload_requested`` flag (CFG-02).

    The handler is FLAG-SET ONLY (Pitfall 6 / T-09-14): it ``.set()``s the returned
    :class:`threading.Event` and does NOTHING else — no lock, no config read, no job
    mutation — so a delivered ``SIGHUP`` never runs reload work re-entrantly inside an
    async-signal context. The MAIN poll loop in :func:`run_daemon` observes the flag,
    clears it, and runs :func:`_do_reload` on the main thread. Mirrors the SIGTERM
    handler's install posture; like it, the handler must be installed BEFORE
    ``scheduler.start()`` so a reload requested during startup is not lost.

    Returned as a standalone helper so the SIGHUP install + flag semantics are unit-
    testable (``test_sighup_triggers_reload``) without standing up the whole daemon.
    """
    reload_requested = threading.Event()

    def _handle_hup(signum, frame):  # noqa: ANN001 — signal handler signature
        # FLAG-SET ONLY: never do reload work here (Pitfall 6 / signal-docs blessed).
        reload_requested.set()

    signal.signal(signal.SIGHUP, _handle_hup)
    return reload_requested


def run_daemon(
    config: Config,
    settings: Settings | None,
    db_path,
    *,
    config_path: str | Path | None = None,
    client=None,
    channel: Channel | None = None,
) -> int:
    """Run the always-on scheduler in the FOREGROUND until SIGTERM / Ctrl-C (D-09).

    Order (so the log reads cleanly): register jobs → announce the schedule →
    run the catch-up scan → ``scheduler.start()``. Then block on a
    ``threading.Event`` with a SIGTERM handler + a ``KeyboardInterrupt`` catch,
    and ``scheduler.shutdown(wait=False)`` on exit. Returns 0 on a clean shutdown.
    Does NOT self-daemonize (systemd owns process liveness, Phase 5).

    When ``channel is None`` and ``settings`` is present, the daemon builds the
    channel from config+settings (mirroring ``send_now``) and shares that single
    instance across the one-time online ping and every briefing job; an
    explicitly-injected ``channel`` wins and skips the build.
    """
    # Channel-from-settings fallback (mirrors send_now / cli.py:119-122): the
    # ``--run`` CLI path calls run_daemon WITHOUT channel=, so without this the
    # online ping's `if channel is not None` guard silently drops it (the UAT gap).
    # Build ONCE here so the SAME instance threads into both _register_jobs and
    # emit_online (single construction point, one channel per process, WR-04). An
    # injected channel wins (tests stay deterministic); channel=None + settings=None
    # stays None (channel-less path is tolerated by the guard + send_now fallback).
    # The build is intentionally UN-GUARDED: a build_channel ValueError (unknown
    # type / missing webhook) propagates here, BEFORE the self-check gate and
    # scheduler.start(), so a misconfigured channel fails loud at startup rather
    # than coming "online" with no delivery path (fail-loud-at-load posture).
    if channel is None and settings is not None:
        # Lazy in-function import, consistent with the in-function send_now import
        # above (keeps build_channel's transitive imports off the daemon module's
        # import-time graph).
        from weatherbot.channels import build_channel

        channel = build_channel(config, settings)

    # Process start time (UTC) for the `status` uptime read (A5). Captured up front so
    # the read-only DaemonState reports a stable origin; ``datetime`` is imported
    # locally to match this module's in-function import discipline.
    from datetime import datetime, timezone

    started_at = datetime.now(timezone.utc)

    scheduler = BackgroundScheduler()
    # Create the shutdown Event UP FRONT so the SAME instance can be threaded into
    # every fire_slot job (live + catch-up) as the retry's interruptible sleep
    # source (D-07 / Pitfall 1) — a SIGTERM during a 45-min mid-pause aborts it.
    stop = threading.Event()
    # The single live-config cell (Discretion #4): construct ONE ConfigHolder here
    # alongside ``stop``/``channel`` and thread it into the three readers
    # (_register_jobs / _announce_schedule / _run_catchup) so every live job resolves
    # ``holder.current()`` at fire time. ``replace()`` is Phase 9's reload seam.
    holder = ConfigHolder(config)
    # INBOUND BOT seam (Plan 11-04): construct the per-location TTL ForecastCache the
    # bot reads on a ``!weather`` command, alongside ``holder``/``stop``/``channel``.
    # Only when ``settings`` is present (the bot needs it to build the One Call client
    # on a cache miss). Lazy in-function import of the interactive package (consistent
    # with the in-function build_channel import below) so discord.py stays OFF the
    # daemon module's import-time graph. A successful reload now INVALIDATES this cache
    # via the ReloadEngine's ``on_applied`` hook (committed-success only) so the next
    # ``!weather`` refetches against the reloaded config (CR-01); the scheduler-READ seam
    # stays UNWIRED (Q2/D-12) — this cache is for the bot only for now. ``bot`` is
    # initialised to None up front so the finally can reference it unconditionally.
    bot = None
    cache = None
    if settings is not None:
        from weatherbot.interactive import ForecastCache

        cache = ForecastCache(settings=settings)

    _register_jobs(
        scheduler,
        holder,
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
    # Route through the engine like every other job (D-04): omitting max_instances
    # here today already defaults to 1, so baking it into engine.register is
    # byte-identical (Plan 01 read-back).
    SchedulerEngine(scheduler).register(
        "__heartbeat__",
        IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S),
        _heartbeat_tick,
        kwargs={"db_path": db_path},
    )
    # Register the proactive UV monitor on its own IntervalTrigger job (UV-04, Plan
    # 15-03), immediately after the heartbeat and gated on ``uv.monitor_enabled``. It
    # reuses the SAME holder/channel/client threaded into _register_jobs (one channel
    # /client per process). interval_seconds is restart-deferred (DP-2): baked into the
    # trigger here; threshold/lead/margin stay LIVE via the per-tick holder re-read, and
    # _reconcile_jobs excludes __uvmonitor__ by id so a reload never disturbs it.
    _register_uvmonitor_job(
        scheduler,
        holder,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
    )
    _announce_schedule(scheduler, holder)
    _run_catchup(
        holder,
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
    # RELOAD ENGINE (Phase 24, SEAM-04 / D-05/D-08/D-09): construct the reusable
    # ReloadEngine and DRIVE every reload through it. The engine owns the genuinely-
    # reusable orchestration (validate→swap→reconcile→rollback control flow, the
    # request_reload()/service_pending() flag pair, the engine-owned watch thread, the
    # best-effort applied/rejected hooks); EVERY WeatherBot specific is injected here:
    #   - validate      → the ONE shared offline validator (concrete Config out, D-03)
    #   - desired_jobs   → _desired_job_ids over a transient ConfigHolder(cfg) (A2)
    #   - register_jobs  → _register_jobs(replace_existing=True) — the FULL desired set (D-01a)
    #   - restore        → _restore_jobs(old_cfg) — deterministic rollback rebuild (D-08)
    #   - excluded_ids   → the app supplies {__heartbeat__, __uvmonitor__}; the module
    #                      never NAMES these ids — it subtracts the frozenset before
    #                      diffing so a reload never tears down liveness/monitor (Pitfall 2)
    #   - on_rejected    → CFG-07 "⛔ rejected" in-channel post, fired BEFORE the re-raise
    #   - on_applied     → CFG-07 "✅ reloaded" post + CR-01 ForecastCache invalidation +
    #                      the D-04 watch-set re-derive — all in the COMMITTED-SUCCESS branch
    # The transient-holder closures (ConfigHolder(cfg)) adapt the engine's bare-cfg
    # callable shape to the existing helpers that take a holder — the thinnest adapter
    # that preserves byte-identical behavior (a helper-signature refactor is Phase-25).
    def _on_applied(summary: str) -> None:
        # COMMITTED-SUCCESS side effects, in the SAME order + with the EXACT strings the
        # in-place _do_reload posted (daemon L999 post, L1013 cache, L1026 re-derive):
        # post the structured outcome, invalidate the bot's ForecastCache, then re-derive
        # the watch set so a moved template becomes watched without a restart (D-04). Each
        # is wrapped best-effort so a side-effect hiccup never aborts the committed reload;
        # the engine's own _best_effort_hook also guards the whole closure.
        if channel is not None:
            try:
                channel.send(f"✅ config reloaded: {summary}")
            except Exception:  # noqa: BLE001 — best-effort post; reload already succeeded
                _log.warning("reload-applied post failed; reload unaffected")
        if cache is not None:
            try:
                cache.invalidate()
            except Exception:  # noqa: BLE001 — best-effort; reload already committed
                _log.warning("forecast cache invalidate failed; reload unaffected")
        # D-04 / Pitfall 4: re-derive the watch dirs from the freshly-swapped config and
        # hand them to the engine's shared box (engine owns the box + the observer; the
        # app owns the derivation since it knows config.template + TEMPLATES_DIR). A no-op
        # when watching is off (config_path None or the box was never armed).
        if config_path is not None:
            reload_engine.update_watch_dirs(
                _derive_watch_dirs(holder.current(), Path(config_path))
            )

    reload_engine: ReloadEngine[Config] = ReloadEngine(
        holder,
        SchedulerEngine(scheduler),
        validate=lambda p: validate_config_and_templates(p),
        desired_jobs=lambda cfg: _desired_job_ids(ConfigHolder(cfg)),
        register_jobs=lambda cfg: _register_jobs(
            scheduler,
            ConfigHolder(cfg),
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            stop_event=stop,
            replace_existing=True,
        ),
        restore=lambda old: _restore_jobs(
            scheduler,
            old,
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            stop_event=stop,
        ),
        excluded_ids=frozenset({"__heartbeat__", "__uvmonitor__"}),
        on_rejected=(
            (lambda exc: channel.send(f"⛔ config reload rejected: {exc}"))
            if channel is not None
            else None
        ),
        on_applied=_on_applied,
    )

    # Install the SIGHUP reload handler in the SAME before-start() position and for
    # the SAME load-bearing reason (a reload requested during the self-check gate must
    # not be lost). The handler is FLAG-SET ONLY — the poll loop below services it on
    # the MAIN thread (Pitfall 6 / CFG-02). It now flag-sets the ENGINE's reload flag
    # (reload_engine.request_reload()) instead of a daemon-owned Event; the engine owns
    # the reload_requested flag the main loop services via service_pending().
    signal.signal(signal.SIGHUP, lambda signum, frame: reload_engine.request_reload())

    # Write the PID file atomically at startup so the short-lived `weatherbot reload`
    # sender can discover + signal this process (CFG-02 / D-03, Plan 03 helper). The
    # writer re-raises on failure (a startup PID-write failure must be loud); the
    # finally unlinks it on clean shutdown. ``PID_FILE``/``write_pid_atomic`` are
    # module-level so tests can redirect the path off the host's ``/run``.
    write_pid_atomic(PID_FILE)

    # FILE-WATCH OBSERVER (Phase 10, CFG-03/D-02/D-03): start a SINGLE long-lived daemon
    # thread running the blocking watchfiles watch() loop, gated on the [reload] watch
    # toggle AND a real config PATH (we can only re-read a config from disk, never from a
    # bare in-process Config). The observer is FLAG-SET ONLY: its request_reload closure
    # ONLY .set()s the SAME reload_requested Event the SIGHUP path uses (D-02) — the main
    # poll loop services the flag and runs _do_reload on THIS (main) thread. The explicit
    # triggers (SIGHUP / `weatherbot reload`) always work regardless of this toggle.
    #
    # The toggle is read ONCE here at startup (Open Question Q2): flipping `[reload]
    # watch` in config.toml itself applies on the NEXT restart, not live — acceptable,
    # and the explicit trigger always works. A single observer is started here and joined
    # in the existing finally (Pitfall #11a — never per-event).
    # FILE-WATCH OBSERVER ownership now lives in the ReloadEngine (Phase 24): the engine
    # owns the single long-lived observer thread + the shared watch-dir box, so a new bot
    # does NOT re-hand-write the pitfall-dense watch plumbing. run_daemon supplies the
    # WeatherBot-specific watch FILTER (_make_watch_filter — the hard .env secrets
    # boundary) + the initial dir box; the engine's observer flag-sets the engine's own
    # reload flag on each settled change (the main poll loop services it on the MAIN
    # thread). ``watching`` records whether we armed the observer so the finally joins it
    # only when started (mirrors the old ``watch_thread is not None`` guard).
    watching = False
    if config.reload.watch and config_path is not None:
        watch_dirs_ref = [_derive_watch_dirs(config, Path(config_path))]
        reload_engine.start_watching(
            watch_dirs_ref,
            watch_filter=_make_watch_filter(config, Path(config_path)),
            stop=stop,
        )
        watching = True
        _log.info(
            "file-watch observer started",
            dirs=[str(d) for d in watch_dirs_ref[0]],
        )

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

        # INBOUND BOT START (Plan 11-04, CMD-08 / T-11-11/T-11-12, Pitfall 4): start
        # the gateway BotThread STRICTLY AFTER scheduler.start() + emit_online() — a
        # bot failure can NEVER delay or gate the systemd READY signal, and a dead bot
        # thread never touches the readiness gate. Guarded on a real ``[bot]`` section
        # AND ``settings`` (we need the token + the cache). The construct + start is
        # wrapped in a try/except that LOGS and PROCEEDS (D-11): a startup bot failure
        # must let the always-on daemon keep serving briefings. The thread name
        # ``weatherbot-discord`` is set inside BotThread. emit_online / notifier.ready()
        # is NOT called from this path.
        if config.bot is not None and settings is not None:
            try:
                from weatherbot.interactive import BotThread, DaemonState

                # READ-ONLY live-state accessor for the `status` command (CMD-12 / D-02):
                # the live scheduler (next-send), the holder (location list, read via
                # current()), the db_path (last-briefing heartbeat), the captured
                # started_at (uptime), and a bot-liveness callable. ``bot_alive`` is a
                # late-binding lambda over the local ``bot`` (assigned just below) so the
                # accessor reports the CURRENT liveness at status-call time, not at
                # construction. DaemonState is frozen + holds NO write capability (D-02):
                # it never adds/removes a job, replaces config, or writes the store.
                daemon_state = DaemonState(
                    scheduler=scheduler,
                    holder=holder,
                    db_path=db_path,
                    started_at=started_at,
                    bot_alive=lambda: bot is not None and bot.is_alive(),
                    # ``monitor_alive`` is "running" when the ``__uvmonitor__`` job is
                    # registered (gated on ``monitor_enabled`` at startup) AND the LIVE
                    # snapshot still has it enabled (WR-03 live-disable short-circuits the
                    # tick without removing the job). Both reads are read-only — DaemonState
                    # holds no write capability (D-02).
                    monitor_alive=lambda: (
                        scheduler.get_job("__uvmonitor__") is not None
                        and holder.current().uv.monitor_enabled
                    ),
                )

                bot = BotThread(
                    settings.discord_bot_token,
                    holder=holder,
                    operator_id=config.bot.operator_id,
                    cache=cache,
                    daemon_state=daemon_state,
                )
                bot.start()
                _log.info("inbound bot thread started")
            except Exception:  # noqa: BLE001 — bot failure must NOT stop the briefing path
                _log.exception("inbound bot failed to start; briefings unaffected")
                bot = None

        # MAIN PARK → POLL LOOP (Pitfall 6 / CFG-02): the single `stop.wait()` park is
        # replaced by a loop that parks on `stop.wait(timeout=1.0)` — cheap, no
        # busy-spin, and SIGTERM still WINS (a set `stop` returns True and exits the
        # loop at once). Each ~1s tick ALSO services the SIGHUP-set `reload_requested`
        # flag on the MAIN thread: `stop` is re-checked first so a stop delivered
        # alongside a reload shuts down without reloading, then the reload runs
        # `_do_reload` on THIS thread (never re-entrantly in the signal handler).
        while not stop.wait(timeout=1.0):
            if reload_engine._reload_requested.is_set():
                if stop.is_set():
                    # SIGTERM wins a stop+reload race: clear the flag and shut down
                    # WITHOUT reloading (the engine clears it inside service_pending, but
                    # here we short-circuit before calling it, so clear explicitly).
                    reload_engine._reload_requested.clear()
                    break
                if config_path is None:
                    # A daemon started without a config PATH cannot re-read from disk
                    # (the real `run` dispatch always supplies it; only bare-config
                    # callers omit it). Skip with a one-line warning, never crash.
                    reload_engine._reload_requested.clear()
                    _log.warning("reload ignored: daemon has no config_path to re-read")
                    continue
                try:
                    # service_pending clears the flag and runs reload() on THIS (main)
                    # thread — never re-entrantly in the signal handler or on the observer
                    # thread (D-05). The engine drives the SAME validate→swap→reconcile→
                    # rollback control flow with the injected WeatherBot specifics.
                    reload_engine.service_pending(config_path)
                except Exception:  # noqa: BLE001 — a bad reload must NOT crash the daemon
                    # The engine already kept-old (validation reject) or rolled back
                    # (reconcile throw) and logged the reason; the live schedule is
                    # intact. Swallow here so an operator's bad edit + SIGHUP never
                    # takes the always-on process down (CFG-04 keep-old is end-to-end).
                    _log.exception("reload failed; live config left intact")
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
        # Stop + join the engine-owned file-watch observer ALONGSIDE the scheduler
        # shutdown (SC#3 clean teardown). stop.set() is idempotent — a SIGTERM already
        # set it; we set it again so the gate-stop / KeyboardInterrupt paths also
        # terminate the blocking watch() generator (rust_timeout=500 → join returns
        # within ~0.5s, NOT the 5s the default would cost — Pitfall #2). reload_engine.stop()
        # owns the join + the join-timeout warning; we only set ``stop`` and call it when
        # the observer was actually armed (``watching``). Never spawn a second observer here.
        if watching:
            stop.set()
            reload_engine.stop()
        # Stop + join the inbound BotThread in the SAME finally (Plan 11-04, clean
        # teardown). bot.stop() cross-thread schedules client.close() onto the bot loop
        # and joins the bot thread (warning on timeout, all inside BotThread). Guarded
        # so a never-started / failed-to-start bot (bot is None) is a no-op. Wrapped so
        # a teardown hiccup never masks the clean shutdown / PID-unlink below.
        if bot is not None:
            try:
                bot.stop()
            except Exception:  # noqa: BLE001 — best-effort teardown; never mask shutdown
                _log.exception("inbound bot stop raised during shutdown")
        # Remove the PID file on clean shutdown so a later `weatherbot reload` does not
        # signal a dead/recycled PID (the /proc guard is the backstop; this is the
        # primary cleanup). missing_ok tolerates a never-written / already-removed file.
        PID_FILE.unlink(missing_ok=True)
        _log.info("daemon stopped")
    return 0
