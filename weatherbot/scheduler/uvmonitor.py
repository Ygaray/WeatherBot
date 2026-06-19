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
references NONE of the briefing exactly-once namespace (``claim_slot`` / ``sent_log``
/ ``record_sent`` / ``release_claim``) — a UV dedup bug is structurally incapable of
gating a briefing.

All "today"/daylight time math uses the CONFIGURED ``Location.timezone`` (Pitfall 3),
never the API payload's offset field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog

from weatherbot.scheduler.catchup import fires_on
from weatherbot.weather.store import claimed_uv_kinds
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


def _local_date_iso(now_utc: datetime, tz: ZoneInfo) -> str:
    """The location-local ``YYYY-MM-DD`` for ``now`` in the configured tz.

    Mirrors ``store._local_date_iso`` (the configured tz is authoritative, D-03), but
    takes the already-resolved ``tz`` the tick computes once per location.
    """
    return now_utc.astimezone(tz).date().isoformat()


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
    if not _is_daylight(now_utc, sunrise, sunset, location.timezone):
        return True  # fetched, but outside daylight → take NO decision branch.

    threshold = snapshot.uv.threshold
    lead = snapshot.uv.pre_warn_lead_minutes
    margin = snapshot.uv.value_margin
    local_date = _local_date_iso(now_utc, tz)

    summary = compute_uv(onecall_imp, None, threshold, tz=tz, now=now_local)
    prior = claimed_uv_kinds(db_path, location.id, local_date)

    _decide(
        location=location,
        summary=summary,
        prior=prior,
        threshold=threshold,
        lead=lead,
        margin=margin,
        now_local=now_local,
        local_date=local_date,
        db_path=db_path,
        channel=channel,
    )
    return True


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
    db_path,
    channel: Channel | None,
) -> None:
    """The three once/day/location decision branches (Pattern 3).

    Task 2 fills this in. Task 1 leaves it a no-op stub so the gate/fetch/no-persist
    behavior is testable before the decision logic exists.
    """
    # --- DECISION BRANCHES (Task 2 fills this stub) ---
    return None


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

    Task 3 wraps the whole body so the tick can NEVER raise to its caller; Task 1
    already wraps each per-location iteration so one bad location isolates from the
    rest.
    """
    from datetime import datetime, timezone

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    snapshot = holder.current()  # snapshot-once (fire_slot idiom).

    if client is None:
        # Lazy build from settings (lookup.py precedent — break the import cycle).
        from weatherbot.cli import build_client

        client = build_client(settings)

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
