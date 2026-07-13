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
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from weatherbot.ops import (
    AUTH_FAILED,  # noqa: F401 — re-exported so daemon.AUTH_FAILED resolves for wiring.py:_on_fail (29-05, after gate_until_healthy removal)
    CONFIG_INVALID,  # noqa: F401 — re-exported so daemon.CONFIG_INVALID resolves for wiring.py:_on_fail (29-05)
    SystemdNotifier,  # noqa: F401 — re-exported so daemon.SystemdNotifier resolves for wiring.py:build_runtime (35-08, after emit-online twin removal)
    run_self_check,  # noqa: F401 — re-exported so daemon.run_self_check resolves for wiring.py:_health_check (29-05, after gate_until_healthy removal)
)
from yahir_reusable_bot.lifecycle import (
    Severity,  # noqa: F401 — re-exported so daemon.Severity resolves for wiring.py:_on_fail fatal branch (29-05)
)
from weatherbot.reliability import (
    REASON_AUTH_FAILED,
    REASON_INTERNAL_ERROR,
    REASON_TRANSIENT_EXHAUSTED,
    build_retrying,
    is_auth_failure,
)
from yahir_reusable_bot.config import ConfigHolder, ReloadEngine
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
    stamp_health,  # noqa: F401 — re-exported so daemon.stamp_health resolves for wiring.py on_online/on_fail hooks (35-08, after emit-online twin removal)
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

        # DELIV-03 (HARD-DELIV-03, D-03): a single-slot fetch cache shared across
        # every retry attempt of THIS fire. The FIRST successful fetch stashes its
        # payload here; a DELIVERY-only retry reuses it (no re-fetch — the fetch
        # runs exactly once per fire). A FETCH-429 raises before the cache is
        # populated, so it still reaches the two-burst wait callable (RELY-02).
        fetch_cache: list = []

        def _attempt() -> DeliveryResult:
            # Let the fetch ``httpx.HTTPStatusError`` (carrying ``.response`` with
            # the ``Retry-After`` header) PROPAGATE so Plan 01's wait callable can
            # honor the capped Retry-After (RELY-02). Do NOT translate/strip it.
            # The delivery retries against the ONE cached payload (D-03), so only a
            # fetch failure re-runs ``lookup_weather``.
            return send_now(
                location.name,
                config=snapshot,
                db_path=db_path,
                settings=settings,
                client=client,
                channel=channel,
                schedule_ctx=ctx,
                fetch_cache=fetch_cache,
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
        #
        # F01 (HARD-DELIV-01, D-01): once ``result.ok``, the exactly-once claim is
        # the source of truth for "delivered" — the briefing is already POSTed and
        # can never be un-sent. The post-send bookkeeping (resolve_alert +
        # stamp_success) is therefore BEST-EFFORT: a raise here (e.g. a
        # ``database is locked`` OperationalError) must NOT fall to the broad
        # except below, which — because ``claimed=True`` — would release_claim
        # (deleting the sent_log row ⇒ a duplicate on catch-up/restart) and record
        # a false internal-error alert. Swallow-on-committed, mirroring the
        # daemon.py cache-invalidate idiom below: log the outcome (no secret) and
        # KEEP the claim. No code path after ``result.ok`` may reach release_claim.
        #
        # CR-01: the success ``_log.info("slot fired")`` MUST live INSIDE this
        # swallow too. The custom ``PrintLoggerFactory(file=_LiveStderr())`` sink
        # (``weatherbot/__init__.py``) forwards to ``sys.stderr.write``, which can
        # raise ``BrokenPipeError`` / ``ValueError: I/O operation on closed file`` /
        # ``OSError`` (journald restart, closed console). If that raise fell to the
        # broad ``except`` below with ``claimed=True``, it would ``release_claim`` a
        # DELIVERED slot ⇒ a duplicate briefing on catch-up/restart — the exact F01
        # defect. So the whole post-commit tail (bookkeeping + success log) is
        # best-effort; the claim is inviolable once ``result.ok``.
        try:
            resolve_alert(db_path, location.id, slot.time, local_date)
            stamp_success(db_path)
            _log.info(
                "slot fired",
                location=location.name,
                time=slot.time,
                late=late,
                delivered=result.ok,
            )
        except Exception:  # noqa: BLE001 — best-effort; briefing already delivered
            # Belt-and-suspenders: the warning log itself routes through the same
            # stderr sink and could re-raise, so guard it — nothing after
            # ``result.ok`` may escape to the broad except and touch the claim.
            try:
                _log.warning(
                    "post-send bookkeeping/log failed; "
                    "briefing already delivered, claim kept",
                    location=location.name,
                    time=slot.time,
                )
            except Exception:  # noqa: BLE001 — the claim must be inviolable
                pass
        return result
    except Exception:  # noqa: BLE001 — one bad slot must not kill the thread
        # An UNEXPECTED exception (not a classified transient/auth HTTP error):
        # a real bug somewhere in the send path. The claim was taken BEFORE the
        # send, so release it (D-07) and ALERT with reason=internal_error +
        # the FULL traceback (D-12 / RELY-06), then return None so the APScheduler
        # worker thread SURVIVES and other slots keep firing (T-03-07).
        #
        # WR-02: the recovery side effects themselves touch the store
        # (release_claim / record_alert), so under the very contention this phase
        # hardens against they can raise ``database is locked``. On the live cron
        # path APScheduler absorbs an escape, but ``_run_catchup`` fires slots in a
        # loop — an escape there would abort every remaining catch-up slot, silently
        # dropping recoverable briefings. Guard the recovery bookkeeping so the
        # isolation handler can NEVER itself re-raise past the envelope.
        try:
            if claimed and local_date is not None:
                release_claim(db_path, location.id, slot.time, local_date)
            # ACCEPTED (F56, v2.1): a raise BEFORE local_date is computed (e.g. an invalid
            # IANA tz -> ZoneInfo ValueError) skips the record_alert below (local_date is
            # None), so that narrow pre-local_date failure is logged but not alerted. The
            # tz is config-validated at load/reload (validate_config_and_templates), so this
            # arm is unreachable from a real caller; kept guarded to avoid an unbound-name
            # delete rather than to alert on it.
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
        except Exception:  # noqa: BLE001 — recovery must never re-raise past isolation
            try:
                _log.warning(
                    "fire_slot recovery bookkeeping failed",
                    location=location.name,
                    time=slot.time,
                )
            except Exception:  # noqa: BLE001 — isolation envelope is inviolable
                pass
        try:
            _log.exception(
                "slot fire failed",
                location=location.name,
                time=slot.time,
            )
        except Exception:  # noqa: BLE001 — a logging raise must not escape isolation
            pass
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


def _prune_forecast_streaks(holder: ConfigHolder) -> None:
    """Drop ``_forecast_failure_streaks`` entries for removed/renamed slots (F89 / D-13).

    The streak dict is in-process state keyed by :func:`_forecast_job_id`. A reload
    that removes or renames a forecast slot must prune its stale entry so a
    subsequently-added slot re-using the same id never inherits a phantom streak. We
    compute the authoritative live id set via :func:`_desired_job_ids` (the SAME
    single-source ids the reconcile uses) and pop the set-difference. The set-diff is
    safe: the streak dict only ever holds forecast ids, and ``_desired_job_ids``
    includes every live forecast id, so live slots are always retained. Best-effort by
    contract — the caller wraps it so a prune hiccup never aborts an applied reload.
    """
    live_ids = _desired_job_ids(holder)
    for dead_id in set(_forecast_failure_streaks) - live_ids:
        _forecast_failure_streaks.pop(dead_id, None)


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

        # F08 (HARD-DELIV-02, D-02): INSPECT the DeliveryResult — a Discord non-2xx
        # returns ``ok=False`` (the channel's never-raise contract), it does NOT
        # raise. Mirroring fire_slot's sibling ``if not result.ok:`` arm, an
        # ok=False forecast delivery is a FAILURE: route it to the WR-05 dead-slot
        # escalation (reuse ``_note_forecast_failure`` verbatim — do NOT duplicate
        # the escalation) and return None. Only a CLEAN delivery (ok, or no channel
        # wired) reaches ``_note_forecast_success`` — so only a clean delivery
        # resets the streak. This still never re-raises out of the slot (Pitfall 4
        # isolation): a chronically-dead slot becomes operator-visible without ever
        # touching a briefing.
        if channel is not None:
            # WR-03: a REVOKED forecast webhook makes ``channel.send`` RAISE the
            # DELIV-04 auth carrier (``httpx.HTTPStatusError`` with a REDACTED URL)
            # rather than returning ok=False. Pre-fix that raise skipped the
            # ``if not fc_result.ok`` arm and folded into the generic broad-except
            # transient streak, so a PERMANENT auth misconfiguration only surfaced
            # after ``_FORECAST_DEAD_AFTER`` fires (three missed forecasts) instead
            # of immediately. Mirror fire_slot's auth/transient split: on an auth
            # failure emit the CRITICAL dead-slot escalation NOW (bypassing the
            # streak) and return; re-raise a non-auth HTTPStatusError so the existing
            # broad-except transient handling is unchanged.
            try:
                fc_result = channel.send(reply.text)
            except httpx.HTTPStatusError as exc:
                if is_auth_failure(exc):
                    _log.critical(
                        "forecast_slot_dead",
                        location=location.name,
                        kind=fc.kind,
                        variant=fc.variant,
                        time=fc.time,
                        reason="auth_failed",
                        severity="critical",
                    )
                    return None
                raise
            if fc_result is not None and not fc_result.ok:
                _log.warning(
                    "forecast slot delivery failed",
                    location=location.name,
                    kind=fc.kind,
                    variant=fc.variant,
                    time=fc.time,
                )
                _note_forecast_failure(location, fc, channel=channel)
                return None
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
    # ACCEPTED (F57, v2.1): a long tenacity retry-pause inside a fire_slot job could in
    # theory starve the shared APScheduler worker pool and delay this heartbeat tick.
    # Not reachable at the deployed 2-slot scale (the pool is never saturated), and
    # misfire_grace_time=None means a contended tick is DELAYED then coalesced, never
    # SKIPPED — so last_tick freshness (the liveness signal) is preserved.
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


def _announce_schedule(scheduler: BackgroundScheduler, holder: ConfigHolder) -> None:
    """Log EVERY slot (briefing + forecast, incl. disabled) + its next_run_time (D-10/D-11).

    Outcome-only logging: ``location``/``kind``/``time``/``days``/``enabled``/
    ``next_run_time`` — never a secret. Announce runs BEFORE ``scheduler.start()``
    (so the log reads cleanly), and a not-yet-started APScheduler job has no
    ``next_run_time`` attribute yet — so the next fire is computed straight from the
    job's CronTrigger, which is tz-aware in the location's own zone (the proof the
    per-location wall-clock firing works).

    F90 (D-11): a DISABLED slot registers NO job, so its ``by_id.get(...)`` is None
    and it logs with ``next_run_time=None`` — the visible "this slot is off" signal.
    We STOP skipping disabled slots (both briefing and forecast) so a silently-paused
    slot is auditable in the startup log instead of vanishing. The forecast loop keys
    on the SINGLE-SOURCE :func:`_forecast_job_id` so the announced id byte-matches the
    registered id.
    """
    from datetime import datetime

    def _next_run(job, tz) -> str:  # noqa: ANN001 — internal helper
        # A disabled slot has no registered job -> None (the F90 "off" signal). Else
        # prefer a running scheduler's computed value, falling back to the trigger
        # (pending jobs have no next_run_time attribute yet).
        if job is None:
            return str(None)
        next_run = getattr(job, "next_run_time", None)
        if next_run is None:
            next_run = job.trigger.get_next_fire_time(None, datetime.now(tz))
        return str(next_run)

    config = holder.current()
    jobs = scheduler.get_jobs()
    by_id = {job.id: job for job in jobs}
    for location in config.locations:
        tz = ZoneInfo(location.timezone)
        # Briefing slots — announced incl. disabled ones (kind="briefing" to
        # distinguish them from the forecast lines below).
        for slot in location.schedule:
            job = by_id.get(f"{location.name}|{slot.time}|{slot.days}")
            _log.info(
                "scheduled slot",
                location=location.name,
                kind="briefing",
                time=slot.time,
                days=slot.days,
                enabled=slot.enabled,
                next_run_time=_next_run(job, tz),
            )
        # Forecast slots (F90) — a parallel loop keyed by the shared _forecast_job_id,
        # announced incl. disabled ones (disabled -> no job -> next_run_time=None).
        for fc in location.forecast:
            job = by_id.get(_forecast_job_id(location, fc))
            _log.info(
                "scheduled slot",
                location=location.name,
                kind=f"forecast:{fc.kind}",
                variant=fc.variant,
                time=fc.time,
                days=fc.days,
                enabled=fc.enabled,
                next_run_time=_next_run(job, tz),
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
        # WR-02: fire_slot already isolates its own body, but defensively wrap the
        # call here too so an escape from ANY one recovered slot (e.g. an unguarded
        # raise from deep in the send path) can NEVER abort the remaining catch-up
        # scan — every missed slot gets its own recovery attempt.
        try:
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
        except Exception:  # noqa: BLE001 — one bad catch-up slot must not abort the scan
            _log.exception(
                "catch-up slot fire escaped isolation",
                location=ms.location.name,
                time=ms.slot.time,
            )


# NB (29-05 dead-code cleanup): the hand-rolled ``gate_until_healthy`` self-check gate
# was REMOVED here. It was the dead twin of the reusable hub ``ReadyGate.run(stop)`` —
# the live startup gate is now driven exclusively through the ReadyGate wired in
# ``build_runtime`` (its ``_health_check`` + ``on_fail`` + ``on_online`` hooks reproduce
# this function's classified-log + durable-stamp + re-probe behavior byte-for-byte).
#
# NB (35-08 dead-code cleanup, F16): the two dead online-signal / config-reload twin
# defs were also REMOVED here (Open-Q1 traced-and-confirmed-dead). The LIVE online signal
# is inlined in :func:`run_daemon` (stamp + log + notifier.ready() + best-effort ping,
# STRICTLY AFTER the ReadyGate returns True). The LIVE reload path routes through the
# hub reload engine's ``service_pending(config_path)`` wired in ``build_runtime`` (its
# ``validate``/``desired_jobs``/``register_jobs``/``restore`` seams reproduce the removed
# engine's validate→swap→reconcile→rollback + CFG-07 posts byte-for-byte). Both twins had
# ZERO runtime callers; do NOT reintroduce them.


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
    the hub reload engine's ``service_pending`` (Pitfall #6/#9 — no re-entrant reload on
    the observer thread).

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
    clears it, and runs the hub reload engine's ``service_pending`` on the main thread.
    Mirrors the SIGTERM
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
    # COMPOSITION ROOT (Phase 25, APP-01 / D-04): all constructor/wiring now lives in
    # the single app-side build_runtime(...) — it builds the channel-once, the
    # scheduler + stop + holder + cache, registers jobs + heartbeat + uv-monitor,
    # announces the schedule, runs the catch-up scan, constructs the ReloadEngine, and
    # constructs the new ReadyGate wiring the four injected leak points (health-check /
    # config id-deriver / selected-location / render_embed) + the byte-identical
    # default LifecycleIdentity + the on_fail/on_online best-effort hooks (D-02a).
    # This is a MOVE, not a redesign: run_daemon KEEPS the load-bearing lifecycle
    # ORDERING below (SIGTERM-before-gate, PID write before the gate, observer armed,
    # gate -> scheduler.start() -> READY, finally teardown). build_runtime NEVER emits
    # READY — only the post-gate online path does.
    # Resolve build_runtime THROUGH the daemon module object (the daemon-namespace
    # resolution convention) so a daemon-suite ``daemon.build_runtime`` monkeypatch
    # (e.g. the fatal-marker spy) bites; fall back to the lazy import otherwise. The
    # lazy import still dodges the wiring<->daemon cycle (run_daemon imports
    # build_runtime, build_runtime lazily imports daemon).
    build_runtime = globals().get("build_runtime")
    if build_runtime is None:
        from weatherbot.scheduler.wiring import build_runtime

    parts = build_runtime(
        config,
        settings,
        db_path,
        config_path=config_path,
        client=client,
        channel=channel,
    )
    scheduler = parts.scheduler
    stop = parts.stop
    holder = parts.holder
    cache = parts.cache
    channel = parts.channel
    bot = parts.bot
    reload_engine = parts.reload_engine
    ready_gate = parts.ready_gate
    notifier = parts.notifier
    identity = parts.identity
    started_at = parts.started_at

    def _handle(signum, frame):  # noqa: ANN001 — signal handler signature
        stop.set()

    # LOAD-BEARING ORDERING (Pitfall 2 / D-04): register the SIGTERM handler BEFORE
    # the self-check gate. The gate (the ReadyGate's re-probe loop) runs before
    # `scheduler.start()`, so a `systemctl stop`/`restart` DURING the re-probe loop
    # must already have a handler installed to set `stop` and break the loop's
    # `stop.wait(...)` — otherwise the stop is ignored until systemd escalates to
    # SIGKILL after TimeoutStopSec.
    signal.signal(signal.SIGTERM, _handle)

    # Install the SIGHUP reload handler in the SAME before-start() position and for
    # the SAME load-bearing reason (a reload requested during the self-check gate must
    # not be lost). FLAG-SET ONLY — the poll loop below services it on the MAIN thread
    # (Pitfall 6 / CFG-02) via reload_engine.request_reload().
    signal.signal(signal.SIGHUP, lambda signum, frame: reload_engine.request_reload())

    # Write the PID file atomically at startup so the short-lived `weatherbot reload`
    # sender can discover + signal this process (CFG-02 / D-03). The writer re-raises
    # on failure (a startup PID-write failure must be loud); the finally unlinks it on
    # clean shutdown. The path now threads the default LifecycleIdentity's pid_file
    # (byte-identical to the prior PID_FILE default: /run/weatherbot/weatherbot.pid).
    write_pid_atomic(identity.pid_file)

    # FILE-WATCH OBSERVER (Phase 10/24, CFG-03): arm the engine-owned single long-lived
    # observer thread, gated on the [reload] watch toggle AND a real config PATH (we can
    # only re-read a config from disk). The engine owns the observer + shared watch-dir
    # box; run_daemon supplies the WeatherBot watch FILTER (_make_watch_filter — the
    # hard .env secrets boundary) + the initial dir box. ``watching`` records whether we
    # armed it so the finally joins it only when started. The watch toggle is read once
    # at startup (Q2); the explicit triggers (SIGHUP / `weatherbot reload`) always work.
    watching = False
    if parts.watch and config_path is not None:
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

    try:
        # STARTUP SELF-CHECK GATE (D-03): drive the reusable ReadyGate — it re-probes
        # the injected health-check, stays alive on any failure (D-04, stamping the
        # durable health row + logging the app's classified CRITICAL/WARNING line via
        # the on_fail hook), and on the FIRST passing probe fires on_online (which
        # starts the scheduler, stamps health=online + the heartbeat tick, logs the
        # structured online event, and posts the one-time Discord ping) and THEN emits
        # sd_notify READY=1 — so READY reaches systemd STRICTLY AFTER scheduler.start()
        # (the most golden-sensitive invariant). If `stop` was set during the gate
        # (clean shutdown), run() returns False and we fall straight through to the
        # finally without starting the scheduler or emitting the online signal.
        if not ready_gate.run(stop):
            # The gate stopped WITHOUT ever passing. Two shapes, distinguished by the
            # DEDICATED fatal marker (D-10 / HARD-STARTUP-02): a CONFIG_INVALID/CRITICAL
            # self-check set ``parts.fatal`` (+ ``stop``) → return NON-ZERO so systemd
            # treats the death as a failure (restart → start-limit); a clean SIGTERM set
            # only ``stop`` (``fatal`` unset) → return 0 (systemd sees a clean exit). We
            # read ``parts.fatal`` directly (like ``stop = parts.stop``) — NEVER ``stop``
            # itself, which a clean SIGTERM also sets.
            return 1 if parts.fatal.is_set() else 0

        _log.info("daemon started", jobs=len(scheduler.get_jobs()))

        # ONLINE PING (F07 / D-12): fire the one-time Discord online ping STRICTLY
        # AFTER the gate returns True — i.e. after the hub emitted READY=1. It was
        # relocated OUT of the on_online hook (which the hub fires BEFORE ready()) so a
        # slow/hung webhook can no longer delay systemd readiness past TimeoutStartSec.
        # Best-effort: a hang/failure here NEVER re-raises and never gates READY (which
        # was already emitted). The not-delivered warning semantics are preserved.
        if channel is not None:
            try:
                send_result = channel.send(
                    "WeatherBot online — startup self-check passed."
                )
                # ACCEPTED (F103, v2.1): getattr(send_result, "ok", True) over-guards — a
                # channel returning a truthy-but-.ok-less object (or None handled above)
                # defaults to "delivered", masking a channel that failed without an ok=False
                # DeliveryResult. Cost is a single missed WARNING on a best-effort startup
                # ping (the daemon is already online / READY emitted); no send-spine impact.
                if send_result is not None and not getattr(send_result, "ok", True):
                    _log.warning(
                        "online ping not delivered",
                        detail=getattr(send_result, "detail", ""),
                    )
            except Exception:  # noqa: BLE001 — best-effort post-READY ping; never re-raise
                _log.warning("online ping post failed (best-effort)")

        # INBOUND BOT START (Plan 11-04, CMD-08 / T-11-11/T-11-12, Pitfall 4): start
        # the gateway BotThread STRICTLY AFTER scheduler.start() + the inlined online
        # signal above — a bot failure can NEVER delay or gate the systemd READY signal,
        # and a dead bot thread never touches the readiness gate. Guarded on a real
        # ``[bot]`` section AND ``settings`` (we need the token + the cache). The construct
        # + start is wrapped in a try/except that LOGS and PROCEEDS (D-11): a startup bot
        # failure must let the always-on daemon keep serving briefings. The thread name
        # ``weatherbot-discord`` is set inside BotThread. The online signal / notifier.ready()
        # is NOT called from this path.
        if config.bot is not None and settings is not None:
            try:
                from weatherbot.interactive import DaemonState
                from weatherbot.scheduler.wiring import build_inbound_bot

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

                # COMPOSITION ROOT (Phase-27, APP-01/APP-02): build_inbound_bot constructs
                # the MODULE BotThread + PanelKit at the single greppable injection site,
                # threading render=_render_bridge / the cosmetic contributors / marker="wb:" /
                # operator_id (baked, v1) / the per-tap dispatch closure. The bot is started
                # HERE strictly after the READY signal (D-11) — build_inbound_bot does NOT
                # start it.
                bot = build_inbound_bot(
                    settings.discord_bot_token,
                    holder=holder,
                    operator_id=config.bot.operator_id,
                    cache=cache,
                    daemon_state=daemon_state,
                    # F22: the SAME SelectedContext the reload-reconcile seam holds
                    # (built at build_runtime's composition root) so the panel dropdown
                    # and the hot-reload reconcile share ONE cell — a renamed/removed
                    # selected location can't leave the panel pointing at a gone name.
                    selection=parts.selection,
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
        # alongside a reload shuts down without reloading, then the reload runs via the
        # hub reload engine's `service_pending` on THIS thread (never re-entrantly in the
        # signal handler).
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
        # Threads the default LifecycleIdentity's pid_file (byte-identical default).
        identity.pid_file.unlink(missing_ok=True)
        _log.info("daemon stopped")
    return 0
