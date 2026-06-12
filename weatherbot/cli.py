"""The composition root: ``--send-now`` wires the whole pipeline (CONF-04).

``send_now`` is the ONE place fetch, persist, render, and deliver meet. It
performs a SINGLE OpenWeather fetch round (One Call 3.0 in BOTH imperial and
metric — 2 calls, the FCST-04 dual-unit display), builds ONE :class:`Forecast`,
and hands that same object to BOTH the SQLite store (``persist`` — no second
fetch, DATA-03) and the renderer. The rendered plain-text body is the canonical message; it is
delivered via the Discord channel's ``send_briefing`` so the embed enrichment is
attached without crossing the channel-agnostic ``send(text)`` seam (DELV-03).

``main`` parses ``--send-now [location]`` (bare flag → first location, D-07),
loads non-secret config + env secrets, builds the channel via the factory, and
runs ``send_now``. Logging records the *outcome* only — never the webhook URL or
the ``appid`` (T-04-01).
"""

from __future__ import annotations

import argparse
import logging
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
import structlog
from pydantic import ValidationError
from tenacity import (
    Retrying,
    retry_if_exception,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
)

from weatherbot.channels import build_channel
from weatherbot.config import (
    load_config,
    load_settings,
    resolve_location,
)
from weatherbot.ops import AUTH_FAILED, run_self_check
from weatherbot.reliability import is_transient
from weatherbot.scheduler.context import schedule_placeholders
from weatherbot.weather.client import fetch_onecall, geocode
from weatherbot.weather.models import Forecast
from weatherbot.weather.store import persist
from templates.renderer import load_template, render, validate_template

if TYPE_CHECKING:
    from weatherbot.channels.base import Channel, DeliveryResult
    from weatherbot.config.models import Config
    from weatherbot.config.settings import Settings
    from weatherbot.scheduler.context import ScheduleContext

_log = structlog.get_logger(__name__)

# Default on-disk SQLite store (gitignored via data/).
DEFAULT_DB_PATH = Path("data") / "weatherbot.db"


class _WeatherClient:
    """Thin client seam bundling the API key so the composition root stays clean.

    Holds the secret ``appid`` internally and exposes ``fetch_onecall`` (the One
    Call 3.0 fetch) taking only (location, units), plus a setup-time ``geocode``
    helper (used by ``--geocode`` in 02-03, never the send path). Existing only to
    give ``send_now`` a single injectable collaborator (tests swap it via
    ``build_client``); it never logs the key.
    """

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    def fetch_onecall(self, location, units: str) -> dict:
        return fetch_onecall(location, self._key, units)

    def geocode(self, query: str, limit: int = 5) -> list[dict]:
        return geocode(query, self._key, limit)


def build_client(settings: Settings) -> _WeatherClient:
    """Construct the weather client from the env-loaded secret (CONF-02)."""
    return _WeatherClient(settings.openweather_api_key)


def send_now(
    location_name: str | None,
    *,
    config: Config,
    db_path: str | Path,
    settings: Settings | None = None,
    client=None,
    channel: Channel | None = None,
    templates_dir: str | Path | None = None,
    schedule_ctx: ScheduleContext | None = None,
) -> DeliveryResult:
    """Run the full pipeline for the resolved location (Pattern 2, DATA-03).

    Resolves the location (``None`` → first, D-07), fetches ONCE (One Call 3.0,
    both units — 2 calls), builds one :class:`Forecast` whose display primary is
    the location's ``units`` override (``imperial`` when unset, CR-01), renders the
    briefing text, and delivers it via the Discord channel's ``send_briefing``
    (embed attached internally). On a SUCCESSFUL delivery the SAME forecast is then
    persisted (no extra fetch, DATA-03); a FAILED delivery persists nothing, so the
    retry path re-fetches (RELY-02) but writes exactly one ``weather_onecall`` round
    per DELIVERED briefing (WR-04). ``client``/``channel`` are injectable for
    testing; otherwise they are built from ``settings``.
    """
    location = resolve_location(config, location_name)

    if client is None:
        if settings is None:
            raise ValueError("send_now requires either a client or settings")
        client = build_client(settings)
    if channel is None:
        if settings is None:
            raise ValueError("send_now requires either a channel or settings")
        channel = build_channel(config, settings)

    # --- the SINGLE fetch round (2 One Call calls: imperial + metric) ---
    # Both payloads are always fetched for the parenthetical secondary value
    # (FCST-04 dual-unit, DATA-03 single round). The per-location ``units``
    # override only selects which unit LEADS the display (CR-01); imperial is the
    # default when ``units`` is unset.
    onecall_imp = client.fetch_onecall(location, "imperial")
    onecall_met = client.fetch_onecall(location, "metric")

    primary = location.units or "imperial"
    forecast = Forecast.from_payloads(
        location, onecall_imp, onecall_met, primary=primary
    )

    # Validate the template at the load boundary (D-10/11): a typo'd {token}
    # aborts the send loudly here rather than shipping a literal placeholder.
    if templates_dir is not None:
        template_text = load_template(config.template, templates_dir)
    else:
        template_text = load_template(config.template)
    validate_template(template_text)

    # Merge the scheduler timing placeholders at the SINGLE render call site (the
    # recommended seam, Open Question 2): Forecast.placeholders() stays
    # weather-only, and {sent_at}/{checked_at}/{schedule_note} are layered on here.
    # sent_dt is the delivery instant; checked_dt is the freshness proxy — within
    # seconds of the single fetch (DATA-03), since Forecast does not expose its
    # fetch instant (a fetched_at field would be needed for exact fidelity; out of
    # scope, D-12). When schedule_ctx is None (manual --send-now) we still render
    # location-local times by computing them in the location's own timezone (D-14).
    tz = schedule_ctx.tz if schedule_ctx is not None else ZoneInfo(location.timezone)
    sent_dt = datetime.now(tz)
    checked_dt = datetime.now(tz)
    text = render(
        template_text,
        {
            **forecast.placeholders(),
            **schedule_placeholders(schedule_ctx, sent_dt, checked_dt),
        },
    )

    # Explicit dispatch (WR-05): every channel exposes ``send_briefing``. The
    # base default delegates to the text-only ``send``; Discord overrides it to
    # attach its embed internally. The canonical body is always ``text``.
    result = channel.send_briefing(text, forecast)

    # Persist the SAME Forecast (no second network call, DATA-03) ONLY after a
    # successful delivery (WR-04). The fetch above stays inside the retried
    # callable so a fetch-429 ``httpx.HTTPStatusError`` (carrying Retry-After)
    # still propagates to the daemon wait callable (RELY-02) — but a FAILED attempt
    # no longer writes a duplicate ``weather_onecall`` row. The result is exactly
    # one persisted round per DELIVERED briefing, which is what the v2
    # forecast-vs-actual accuracy join wants.
    if result.ok:
        persist(db_path, location, forecast)

    _log.info(
        "send_now complete",
        location=location.name,
        delivered=result.ok,
    )
    return result


# Manual (attended) tight-retry bound (D-10). Deliberately SHORT — at most 3
# attempts with a brief exponential backoff (cap 10s) — NOT the daemon's patient
# ~65-min two-burst schedule. The manual path is terminal-bound: an attended user
# is watching the terminal, so a transient blip recovers in seconds or the failure
# is reported immediately. The daemon owns the long patient schedule + alerts.
_MANUAL_MAX_ATTEMPTS = 3


def run_send_now(
    location_name: str | None,
    *,
    config: Config,
    db_path: str | Path,
    settings: Settings | None = None,
    client=None,
    channel: Channel | None = None,
    templates_dir: str | Path | None = None,
) -> int:
    """Manual ``--send-now`` path: a SHORT bounded retry around ``send_now`` (D-10).

    This is the ATTENDED half of the daemon-vs-manual split. It wraps the
    single-attempt ``send_now`` composition root in a tight :class:`Retrying`
    (``stop_after_attempt(3)``) so a transient blip (a fetch 429/5xx/timeout or a
    one-off non-ok Discord ``DeliveryResult``) recovers without involving the
    daemon's patient ~65-min two-burst schedule. On final failure it reports the
    ``detail`` to the terminal and returns exit 1 (the existing report path).

    CRITICALLY (D-10 / Pitfall 4): the manual path writes NO ``alerts`` and NO
    ``heartbeat`` rows — those liveness concerns belong exclusively to the
    unattended daemon. ``send_now`` already only ``persist``s weather data, and
    this wrapper adds no liveness write. ``send_now`` stays single-attempt; the
    retry locus is here, not inside it (Open Question 1).

    Returns 0 on (eventual) delivery, 1 on a final failure or an exhausted
    transient error.
    """
    retrying = Retrying(
        stop=stop_after_attempt(_MANUAL_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, max=10),
        # Retry a non-ok DeliveryResult OR a transient fetch/network error. A
        # permanent error (auth 401/403, 4xx) is NOT transient → reraised at once.
        retry=(retry_if_result(lambda r: not r.ok) | retry_if_exception(is_transient)),
        # reraise=True → an exhausted/permanent EXCEPTION (transient_exhausted or a
        # permanent auth/4xx) is reraised so the except blocks below report it.
        reraise=True,
        # An exhausted non-ok DeliveryResult never raised an exception, so without
        # this callback tenacity would wrap it in a RetryError. Return the last
        # result instead so the terminal report path below logs its `detail` (D-10).
        retry_error_callback=lambda rs: rs.outcome.result(),
        sleep=time.sleep,  # patchable seam so tests run the bound in milliseconds
    )

    try:
        result = retrying(
            send_now,
            location_name,
            config=config,
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            templates_dir=templates_dir,
        )
    except httpx.HTTPStatusError as exc:
        # An exhausted/permanent transport failure on the manual path: report the
        # outcome to the terminal (never the key/URL — outcome only, T-04-01).
        _log.error("briefing delivery failed", status=exc.response.status_code)
        return 1
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
        _log.error("briefing delivery failed", error=type(exc).__name__)
        return 1

    if result.ok:
        _log.info("briefing delivered")
        return 0
    _log.error("briefing delivery failed", detail=result.detail)
    return 1


def do_geocode(
    query: str,
    *,
    settings: Settings | None = None,
    client=None,
) -> int:
    """Resolve ``query`` to coordinates and PRINT a paste-ready snippet (LOC-03).

    Calls the setup-time ``/geo/1.0/direct`` geocoder ONCE and prints each match
    plus a commented ``[[locations]]`` block the user can paste into
    ``config.toml``. It NEVER writes the config file and NEVER runs on the send
    path (D-04). ``client`` is injectable for tests; otherwise it is built from
    ``settings``. Returns 0 on success, non-zero on failure. The ``appid`` never
    appears in output or logs (T-04-01).
    """
    if client is None:
        if settings is None:
            raise ValueError("do_geocode requires either a client or settings")
        client = build_client(settings)

    try:
        matches = client.geocode(query)
    except httpx.HTTPStatusError as exc:
        # Never echo the URL/params (which carry the key) — outcome only.
        _log.error("geocode failed", status=exc.response.status_code)
        return 1

    if not matches:
        print(f"# No matches for {query!r}.")
        return 1

    for match in matches:
        name = match.get("name", "")
        state = match.get("state", "")
        country = match.get("country", "")
        lat = match.get("lat")
        lon = match.get("lon")
        label = ", ".join(part for part in (name, state, country) if part)
        print(f"{label} -> lat={lat}  lon={lon}")
        print("# paste into config.toml:")
        print("#   [[locations]]")
        print(f'#   name = "{name}"')
        print(f"#   lat = {lat}")
        print(f"#   lon = {lon}")
        print('#   timezone = "America/Chicago"  # set the IANA zone for this place')
    return 0


def do_check(
    *,
    config: Config,
    settings: Settings | None = None,
    client=None,
    channel: Channel | None = None,
) -> int:
    """Validate the whole config WITHOUT delivering a briefing (CONF-05, D-12).

    Runs the four D-12 steps in order and delivers nothing: (1) the config was
    already schema/IANA-tz/units validated by ``load_config``; (2)
    ``validate_template`` on the configured template; (3) ONE
    ``client.fetch_onecall(first_location, "imperial")`` reachability probe whose
    401/403 message distinguishes "subscription not active / not yet propagated"
    from a generic error (Pitfall 1); (4) ``assert_unique_names`` then
    ``resolve_location`` for each location. ``channel`` is accepted only to prove
    nothing is sent. Returns 0 on success, 1 on any failure. Logging is
    outcome-only — never the key/URL/params (T-04-01).
    """
    # The validate+probe is delegated to the SHARED self-check engine (D-03) so
    # `--check` and the daemon's startup gate (Plan 05-02) use ONE implementation.
    # do_check keeps its own surface: the 401/403 subscription-not-active message,
    # the "delivered nothing" guard, and the retry-budget echo on success (D-09).
    result = run_self_check(config=config, settings=settings, client=client)
    if not result.ok:
        if result.reason == AUTH_FAILED:
            # Distinguish subscription-not-active from a generic error WITHOUT
            # leaking the key (Pitfall 1 / T-04-02) — the SAME wording as before.
            _log.error(
                "config check failed",
                error=(
                    "One Call reachability probe returned "
                    f"{result.detail}: the OpenWeather key or its 'One Call by Call' "
                    "subscription may not be active or not yet propagated — "
                    "wait a few hours and retry."
                ),
            )
        else:
            _log.error("config check failed", error=result.reason, detail=result.detail)
        return 1

    # Nothing should ever have been delivered.
    if channel is not None and getattr(channel, "sent_text", None):
        _log.error("config check unexpectedly delivered a briefing")
        return 1

    # (5) Surface the RESOLVED retry budget so a mis-tuned [reliability] section is
    # visible at check time WITHOUT sending (D-09). The values were already
    # fail-loud validated by Plan 02's `Reliability` model at load; --check only
    # echoes them. Only numeric budget fields are printed — never a secret
    # (T-04-01). The approx total is the SAME jittered worst case the validator
    # enforces (`worst_case_seconds`), shown in minutes — so the echo can never
    # drift from the guard (previously it used the optimistic 2*spread+mid_pause).
    rel = config.reliability
    approx_total_min = rel.worst_case_seconds() / 60
    print(
        "retry budget: "
        f"attempts_per_burst={rel.attempts_per_burst} "
        f"burst_spread_seconds={rel.burst_spread_seconds} "
        f"mid_pause_seconds={rel.mid_pause_seconds} "
        f"(approx total ~{approx_total_min:.0f} min)"
    )

    _log.info("config check passed", locations=len(config.locations))
    return 0


def _load_config_reporting(path: str | Path) -> Config | None:
    """Load + validate config, reporting load failures cleanly (no traceback).

    A realistic config typo (missing ``[[locations]]`` header, a missing required
    field like ``timezone``, or a wrong ``--config`` path) must fail LOUDLY but
    CLEANLY — exit 1 with an actionable message, never a raw Python traceback
    (CONF-05 / SC-05: "report malformed input loudly"). Returns the validated
    :class:`Config`, or ``None`` when loading failed (the caller returns exit 1).
    Logging is outcome-only and never echoes secrets.
    """
    try:
        return load_config(path)
    except FileNotFoundError:
        _log.error("config file not found", path=str(path))
    except tomllib.TOMLDecodeError as exc:
        _log.error("config TOML syntax error", path=str(path), error=str(exc))
    except ValidationError as exc:
        _log.error("config validation failed", path=str(path), error=str(exc))
    return None


def main(argv: list[str] | None = None) -> int:
    """Parse ``--send-now [location]`` and run the composition root."""
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        prog="weatherbot",
        description="On-demand weather briefing (fetch -> persist -> render -> deliver).",
    )
    parser.add_argument(
        "--send-now",
        nargs="?",
        const=None,
        default=argparse.SUPPRESS,
        metavar="LOCATION",
        help="Send a briefing now for LOCATION (omit LOCATION for the first/default location).",
    )
    parser.add_argument(
        "--geocode",
        default=argparse.SUPPRESS,
        metavar="QUERY",
        help=(
            'Resolve "City, ST" to lat/lon (setup-time only) and print a '
            "paste-ready config snippet. Never writes config; never runs on the "
            "send path."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Validate config + template + one live reachability probe without "
            "sending a briefing."
        ),
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Run the always-on scheduler in the foreground (blocks; "
            "Ctrl-C / SIGTERM to stop)."
        ),
    )
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to the non-secret TOML config (default: config.toml).",
    )
    args = parser.parse_args(argv)

    # --geocode: setup-time lookup ONLY — load secrets, NOT the config/channel.
    if hasattr(args, "geocode"):
        settings = load_settings()
        return do_geocode(args.geocode, settings=settings)

    # --check: validate everything, deliver nothing.
    if hasattr(args, "check"):
        config = _load_config_reporting(args.config)
        if config is None:
            return 1
        settings = load_settings()
        return do_check(config=config, settings=settings)

    # --run: foreground always-on scheduler (blocks until SIGTERM/Ctrl-C, D-09).
    if hasattr(args, "run"):
        config = _load_config_reporting(args.config)
        if config is None:
            return 1
        settings = load_settings()
        # Reuse the --send-now db-dir prep so the sent-log DB dir exists before
        # the daemon starts. Import the daemon module HERE (not at module top) —
        # daemon imports send_now from this module, so a top-level import would
        # create a cycle.
        db_path = DEFAULT_DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        from weatherbot.scheduler import daemon

        return daemon.run_daemon(config=config, settings=settings, db_path=db_path)

    if not hasattr(args, "send_now"):
        parser.print_help()
        return 0

    config = _load_config_reporting(args.config)
    if config is None:
        return 1
    settings = load_settings()

    db_path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Single construction site (WR-04): pass only ``settings`` and let
    # ``send_now`` build both the client and the channel. The manual path wraps
    # the single-attempt ``send_now`` in a SHORT bounded retry (D-10) so an
    # attended transient blip recovers; a final failure reports to the terminal
    # and writes NO alerts/heartbeat rows (those are daemon-liveness concerns).
    return run_send_now(
        args.send_now,
        config=config,
        db_path=db_path,
        settings=settings,
    )
