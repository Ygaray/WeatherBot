"""The pure proactive-UV decision module (UV-04/UV-05/UV-06).

Modeled on :mod:`weatherbot.scheduler.catchup`: an APScheduler-free, side-effect-
minimal module that the Plan 15-03 daemon registers as an ``IntervalTrigger`` job.
``_uv_monitor_tick`` re-reads live config ONCE per run (the ``fire_slot``
snapshot-once idiom), monitors only active-today locations during daylight, fetches
the One Call payload READ-ONLY (it never writes the weather time series — Pattern 4,
no DB pollution), reuses Phase-14's :func:`compute_uv` verbatim for the crossing/window
math, and posts best-effort via ``channel.send`` — each alert gated by the durable
``claim_uv_alert`` dedup from Plan 15-01.

Three once/day/location alert kinds (Pattern 3): ``prewarn`` (whichever of time- or
value-proximity fires first), ``crossing`` (UV reaches the threshold — reused for a
first-poll already-high start with distinct wording), and ``allclear`` (UV drops
back below after a crossing). Each is claimed at most once per day per location and
is durable across a restart (a mid-day ``systemctl restart`` never re-spams —
Pitfall 2).

Failure isolation (UV-06) is two-layered: the whole tick body is wrapped so it can
NEVER raise to its (APScheduler) caller, and each per-location iteration is also
individually wrapped so one bad location never aborts the others. The module
references NONE of the briefing exactly-once namespace (the slot-claim / sent-log /
record-sent / release-claim helpers) — a UV dedup bug is structurally incapable of
gating a briefing.

All "today"/daylight time math uses the CONFIGURED ``Location.timezone`` (Pitfall 3),
never the API payload's offset field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog

from weatherbot.scheduler.catchup import fires_on
from weatherbot.weather.dates import local_date_iso
from weatherbot.weather.store import claim_uv_alert, claimed_uv_kinds
from weatherbot.weather.uv import compute_uv

if TYPE_CHECKING:
    from datetime import datetime

    from weatherbot.channels.base import Channel
    from weatherbot.config.holder import ConfigHolder
    from weatherbot.config.models import Location
    from weatherbot.config.settings import Settings

_log = structlog.get_logger(__name__)


def _active_today(location: Location, now_utc: datetime) -> bool:
    """Is ``location`` scheduled to send today (in its OWN tz)?

    Reuses the single source-of-truth :func:`catchup.fires_on` over the location's
    ENABLED slots — never a forked weekday parser (the catch-up planner and the live
    CronTrigger consume the same logic). A disabled-only or wrong-weekday location is
    skipped, so the monitor only polls a place the user will actually be (UV-04).
    """
    tz = ZoneInfo(location.timezone)
    now_local = now_utc.astimezone(tz)
    return any(s.enabled and fires_on(s, now_local) for s in location.schedule)


def _is_daylight(
    now_utc: datetime, sunrise_epoch: int, sunset_epoch: int, tz_name: str
) -> bool:
    """Is ``now`` within ``[sunrise, sunset]`` for the CONFIGURED tz (Pitfall 3)?

    ``sunrise_epoch``/``sunset_epoch`` are the absolute Unix-UTC instants from One
    Call ``daily[0]``; they are converted into ``tz_name`` (the configured IANA zone,
    NEVER the API payload offset) so the comparison is DST-correct. ``now_utc``
    must be tz-aware.
    """
    from datetime import datetime as _dt

    tz = ZoneInfo(tz_name)
    now_local = now_utc.astimezone(tz)
    sunrise = _dt.fromtimestamp(sunrise_epoch, tz=tz)
    sunset = _dt.fromtimestamp(sunset_epoch, tz=tz)
    return sunrise <= now_local <= sunset


def _daily0_matches_today(sunrise_epoch: int, tz: ZoneInfo, local_date: str) -> bool:
    """Does ``daily[0]``'s own local date equal today's ``local_date`` (WR-05)?

    The daylight gate trusts ``daily[0].sunrise``/``sunset``; ``compute_uv`` filters
    today's hourly buckets to ``now``'s local date. Both must reference the SAME day
    or the crossing-time math is judged against a stale day baseline near a tz/DST
    boundary. We derive ``daily[0]``'s date from its ``sunrise`` instant in the
    configured tz (sunrise unambiguously falls on the bucket's own calendar day) and
    require it to match ``local_date``. A non-numeric sunrise can't be dated → treat
    as a mismatch (skip safely), consistent with the fail-safe posture.
    """
    from datetime import datetime as _dt

    try:
        daily0_date = _dt.fromtimestamp(int(sunrise_epoch), tz=tz).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    return daily0_date == local_date


def _post(channel: Channel | None, text: str) -> None:
    """Best-effort alert post (mirrors ``_do_reload``'s reload-outcome idiom).

    A ``channel.send`` failure is logged outcome-only (never a secret) and SWALLOWED
    so a failed post never gates the monitor or a briefing (UV-06). ``channel`` is
    ``None`` in tests/headless runs — the guard tolerates it.
    """
    if channel is None:
        return
    try:
        channel.send(text)
    except Exception:  # noqa: BLE001 — best-effort; a failed post never gates the tick
        _log.warning("uv_alert_post_failed")


def _evaluate_location(
    location: Location,
    snapshot,
    now_utc: datetime,
    db_path,
    client,
    channel: Channel | None,
) -> bool:
    """Evaluate ONE active-today location: fetch read-only, gate daylight, decide.

    Returns ``True`` when a fetch was performed (for outcome counting), ``False`` when
    the location was gated out before any fetch. Raises nothing the caller cannot
    swallow — the per-location try/except in :func:`_uv_monitor_tick` is the isolation
    boundary, but this helper keeps its own body lean.
    """
    # Read-only fetch — UV is unitless so a single imperial payload suffices (A1).
    # The monitor never writes the weather time series (Pattern 4): no DB write,
    # no pollution (UV-04). It calls fetch_onecall directly, like lookup_weather.
    onecall_imp = client.fetch_onecall(location, "imperial")

    tz = ZoneInfo(location.timezone)
    now_local = now_utc.astimezone(tz)

    daily0 = (onecall_imp.get("daily") or [{}])[0] or {}
    sunrise = daily0.get("sunrise")
    sunset = daily0.get("sunset")
    if sunrise is None or sunset is None:
        return True  # no sun data → can't bound daylight; skip the decision safely.

    # D-08: the ONE shared local-date primitive (weatherbot.weather.dates) — the
    # monitor's local_date can never diverge from the render/store keying.
    local_date = local_date_iso(now_utc, tz)

    # WR-05: the daylight gate reads daily[0].sunrise/sunset while compute_uv's
    # _today_daytime_points independently filters hourly[] to ``now``'s local date.
    # Near a tz/DST/midnight boundary the payload's daily[0] can be the PRIOR day,
    # so the two reads would reference different day baselines (a crossing_time for
    # "today" judged against a daily[0] that is yesterday). Anchor both on one
    # source: require daily[0]'s own local date (derived from its sunrise in the
    # configured tz) to equal ``local_date`` before trusting its sun bounds. If they
    # disagree, skip the decision safely (fetched, no branch).
    if not _daily0_matches_today(sunrise, tz, local_date):
        return True

    prior = claimed_uv_kinds(db_path, location.id, local_date)
    in_daylight = _is_daylight(now_utc, sunrise, sunset, location.timezone)

    # WR-01: the all-clear ("protect window over") must be able to complete the
    # day's lifecycle even when UV only drops back below threshold AT/AFTER sunset
    # (the common case — UV peaks at solar noon and trails toward sunset). So we do
    # NOT early-return purely because daylight has ended IF a ``crossing`` was
    # already claimed today — we fall through to _decide, whose branches 1/2
    # (crossing/pre-warn) stay daylight-gated (via ``in_daylight``) so no spurious
    # post-sunset crossing can fire; only branch 3 (all-clear) runs post-sunset.
    if not in_daylight and "crossing" not in prior:
        return True  # outside daylight with nothing to close out → no decision.

    threshold = snapshot.uv.threshold
    lead = snapshot.uv.pre_warn_lead_minutes
    margin = snapshot.uv.value_margin

    summary = compute_uv(onecall_imp, None, threshold, tz=tz, now=now_local)

    _decide(
        location=location,
        summary=summary,
        prior=prior,
        threshold=threshold,
        lead=lead,
        margin=margin,
        now_local=now_local,
        local_date=local_date,
        in_daylight=in_daylight,
        db_path=db_path,
        channel=channel,
    )
    return True


def _fmt_threshold(threshold: float) -> str:
    """Render the threshold without a trailing ``.0`` (``6.0`` → ``6``)."""
    return str(int(threshold)) if float(threshold).is_integer() else str(threshold)


def _fmt_window(summary) -> str:
    """The ``HH:MM-HH:MM`` protect window (configured-tz wall-clock), or a fallback."""
    start = summary.window_start
    end = summary.window_end
    if start is None or end is None:
        return "today"
    return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"


def _decide(
    *,
    location: Location,
    summary,
    prior: set[str],
    threshold: float,
    lead: int,
    margin: float,
    now_local: datetime,
    local_date: str,
    in_daylight: bool,
    db_path,
    channel: Channel | None,
) -> None:
    """The three once/day/location decision branches (Pattern 3, in order).

    1. ALREADY-HIGH / CROSSING — ``current >= threshold`` (DAYLIGHT-gated): a
       first-poll already-high start (no prior rows) ALSO claims ``prewarn`` (marking
       the now-moot pre-warn claimed without posting) and posts the "already ≥T"
       wording; otherwise it posts the "now ≥T" crossing wording. Either way it
       claims ``crossing``.
    2. PRE-WARN — ``current < threshold`` and neither ``prewarn`` nor ``crossing``
       claimed (DAYLIGHT-gated): fires when within ``lead`` minutes of the predicted
       crossing OR within ``margin`` of the threshold (whichever first).
    3. ALL-CLEAR (independent, every tick) — ``current < threshold`` after a crossing
       was claimed and no all-clear yet. NOT daylight-gated (WR-01): it must be able
       to fire at/after sunset to close out the day's lifecycle.

    Each post is gated by :func:`claim_uv_alert` (``rowcount == 1`` ⇒ first claim ⇒
    post), so each kind posts at most once per day per location, durable across a
    restart. ``ordering``: branch 1 precedes branch 2 so a late already-high start
    never emits a pre-warn. ``in_daylight`` gates branches 1/2 so the post-sunset
    fall-through (WR-01) cannot emit a spurious crossing/pre-warn.
    """
    t = _fmt_threshold(threshold)
    name = location.name

    # --- (1) ALREADY-HIGH / CROSSING (daylight-gated, WR-01) ---
    if in_daylight and summary.current >= threshold and "crossing" not in prior:
        first_poll = not prior  # no rows yet today ⇒ a first/mid-day already-high.
        # WR-02: claim the POSTING gate (``crossing``) FIRST, before the moot-
        # ``prewarn`` suppression claim. The two claims are separate connections
        # (non-atomic), so a crash between them must never leave a suppressing
        # ``prewarn`` row whose ``crossing`` was never claimed/posted. Claiming
        # ``crossing`` first means the worst case of a crash after line A is a
        # claimed-but-unposted ``crossing`` (idempotent: never a re-spam, matching
        # the record_alert "claim-before-post, a failed post is not re-delivered"
        # idiom) — never an orphaned suppressing ``prewarn``.
        if claim_uv_alert(db_path, location.id, local_date, "crossing"):  # line A
            if first_poll and "prewarn" not in prior:
                # Suppress the now-moot pre-warn (claim WITHOUT posting), only AFTER
                # the crossing claim succeeded so the suppression can never outlive
                # its crossing.
                claim_uv_alert(db_path, location.id, local_date, "prewarn")
            window = _fmt_window(summary)
            if first_poll:
                _post(
                    channel,
                    f"☀️ UV already ≥{t} in {name} — sunscreen on. Protect ~{window}.",
                )
            else:
                _post(
                    channel,
                    f"☀️ UV now ≥{t} in {name} — sunscreen on. Protect ~{window}.",
                )

    # --- (2) PRE-WARN (whichever of time- | value-proximity fires first) ---
    elif (
        in_daylight
        and summary.current < threshold
        and "prewarn" not in prior
        and "crossing" not in prior
    ):
        delta_min = (
            (summary.crossing_time - now_local).total_seconds() / 60
            if summary.crossing_time is not None
            else None
        )
        time_close = delta_min is not None and 0 <= delta_min <= lead
        value_close = (threshold - summary.current) <= margin
        if (time_close or value_close) and claim_uv_alert(
            db_path, location.id, local_date, "prewarn"
        ):
            # WR-04: only render the "~N min" countdown when the crossing is a
            # FUTURE instant within ``lead`` (i.e. ``time_close`` actually holds).
            # A value_close-only trigger may have a crossing_time that is further
            # out than ``lead`` (a misleading "soon ... in ~90 min") or in the PAST
            # (a non-monotone profile → negative "~-12 min", since value_close has
            # no time guard). In those cases use value-proximity wording instead.
            if time_close:
                text = (
                    f"☀️ UV hits {t} in ~{int(delta_min)} min in {name} "
                    f"— sunscreen soon."
                )
            else:
                text = f"☀️ UV nearing {t} in {name} — sunscreen soon."
            _post(channel, text)

    # --- (3) ALL-CLEAR (independent: runs every tick once a crossing exists) ---
    # D-03 / F15: gate the all-clear on the day's PREDICTED end-of-window from the
    # SAME UvSummary compute_uv already returns — NOT a bare instantaneous
    # ``current < threshold`` dip. A passing-cloud dip at solar noon (current 5.8 vs
    # threshold 6.0) while UV is still peaking (now_local < peak_time) and the window
    # has not closed (now_local < window_end) must NOT declare "protect window over"
    # and must NOT burn the durable once-per-day allclear slot. Require
    # ``below AND past_peak AND window_over``.
    below = summary.current < threshold
    # D-03 empty-hourly degrade: when hourly[] is empty/missing, compute_uv returns
    # peak_time/window_end == None → past_peak/window_over are False → all-clear is
    # NOT posted (defer to a future tick with a real window or the next-day reset).
    # This keeps a premature latch AND a new persistence table both out of scope
    # (F36/F37 deferred) — the fail-safe "don't post yet" posture.
    past_peak = summary.peak_time is not None and now_local >= summary.peak_time
    window_over = summary.window_end is not None and now_local >= summary.window_end
    if (
        below
        and "crossing" in prior
        and "allclear" not in prior
        and window_over
        and past_peak
    ):
        if claim_uv_alert(db_path, location.id, local_date, "allclear"):
            _post(
                channel,
                f"✅ UV back below {t} in {name} — protect window over.",
            )


def _uv_monitor_tick(
    holder: ConfigHolder,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
    *,
    now_utc: datetime | None = None,
) -> None:
    """The APScheduler job callback: poll active+daylight locations, decide, post.

    Reads ``holder.current()`` EXACTLY ONCE at the top (the ``fire_slot`` snapshot-once
    idiom) and threads that snapshot through the per-location loop, so a mid-tick
    ``replace()`` can never tear a run. For each active-today location it fetches the
    One Call payload READ-ONLY (never persists), gates on daylight, reuses
    :func:`compute_uv`, and posts best-effort via ``channel.send`` — each alert gated
    by the durable :func:`claim_uv_alert`.

    ``now_utc`` is injected for tests (defaults to the current UTC instant). ``client``
    is lazily built from ``settings`` when ``None`` (the ``lookup_weather`` precedent).

    Failure isolation (UV-06) is two-layered: the WHOLE body is wrapped in an
    outermost ``try/except`` so the tick can NEVER raise to its (APScheduler) caller —
    even a ``holder.current()`` / client-build failure is logged and swallowed
    ("die alone", mirroring ``BotThread._run`` + ``fire_slot``). Each per-location
    iteration is ALSO individually wrapped, so one bad location never aborts the rest.
    """
    from datetime import datetime, timezone

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    try:
        snapshot = holder.current()  # snapshot-once (fire_slot idiom).

        # WR-03: honor ``monitor_enabled`` LIVE. The ``__uvmonitor__`` job stays
        # registered across a reload (DP-2: only ``interval_seconds`` is restart-
        # deferred), so a reload that flips ``monitor_enabled`` to false must stop
        # the work HERE — otherwise the job keeps polling the One Call API every
        # interval, wasting quota and contradicting the operator's intent.
        if not snapshot.uv.monitor_enabled:
            return None  # live disable: the job stays registered but does nothing.

        if client is None:
            # Lazy build from settings (lookup.py precedent — break import cycle).
            from weatherbot.cli import build_client  # pragma: no cover - production-only: tests always inject a client; this builds a real OpenWeather client (network/cli edge), deliberately bypassed offline

            client = build_client(settings)  # pragma: no cover - production-only (see above): builds a live network client

        fetched = 0
        skipped = 0
        for location in snapshot.locations:
            try:
                if not _active_today(location, now_utc):
                    skipped += 1
                    continue
                if _evaluate_location(
                    location, snapshot, now_utc, db_path, client, channel
                ):
                    fetched += 1
            except Exception:  # noqa: BLE001 — per-location isolation (UV-06)
                _log.warning("uv_monitor_location_failed", location=location.name)
                continue

        _log.info("uv_monitor_tick", fetched=fetched, skipped=skipped)
    except Exception:  # noqa: BLE001 — outermost envelope; the tick NEVER raises
        _log.critical("uv_monitor_tick_failed")
        return None
