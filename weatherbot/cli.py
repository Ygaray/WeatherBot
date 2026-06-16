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
import os
import signal
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

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
)
from weatherbot.config.loader import validate_config_and_templates
from weatherbot.interactive import UnknownLocationError, lookup_weather
from weatherbot.ops import AUTH_FAILED, run_self_check
from weatherbot.ops.pidfile import PID_FILE, is_weatherbot_pid, read_pid
from weatherbot.reliability import is_transient
from weatherbot.scheduler.context import schedule_placeholders
from weatherbot.weather.client import fetch_onecall, geocode
from weatherbot.weather.store import persist

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
    if client is None:
        if settings is None:
            raise ValueError("send_now requires either a client or settings")
        client = build_client(settings)
    if channel is None:
        if settings is None:
            raise ValueError("send_now requires either a channel or settings")
        channel = build_channel(config, settings)

    # The read-only HEAD (resolve -> dual fetch -> Forecast -> validate/render) is
    # delegated to the shared ``lookup_weather`` core (D-08) so there is ONE source
    # of truth for fetch->render across the v1.0 scheduled path, the P7 CLI, and the
    # P11 Discord bot. Only this HEAD changed; the deliver+persist TAIL below is
    # byte-identical (criterion #4; tests/test_send_now.py is the contractual gate).
    #
    # The scheduler timing placeholders are layered ON TOP via ``extra_placeholders``
    # (Pattern 1 Option A): ``lookup_weather`` merges weather + on-demand timing, then
    # values.update(extra_placeholders) overrides the timing keys with the SCHEDULED
    # {sent_at}/{checked_at}/{schedule_note} — preserving send_now's exact merge order
    # and precedence (Pitfall 1). sent_dt is the delivery instant; checked_dt is the
    # freshness proxy — within seconds of the single fetch (DATA-03). When schedule_ctx
    # is None (manual --send-now) the times are computed in the location's own timezone
    # (D-14), matching lookup_weather's own on-demand default.
    tz = schedule_ctx.tz if schedule_ctx is not None else None
    sent_dt = datetime.now(tz) if tz is not None else None
    checked_dt = datetime.now(tz) if tz is not None else None
    if tz is not None:
        extra_placeholders = schedule_placeholders(schedule_ctx, sent_dt, checked_dt)
    else:
        extra_placeholders = None

    result_lr = lookup_weather(
        location_name,
        config=config,
        settings=settings,
        client=client,
        templates_dir=templates_dir,
        extra_placeholders=extra_placeholders,
    )

    # Explicit dispatch (WR-05): every channel exposes ``send_briefing``. The
    # base default delegates to the text-only ``send``; Discord overrides it to
    # attach its embed internally. The canonical body is always ``result_lr.text``.
    result = channel.send_briefing(result_lr.text, result_lr.forecast)

    # Persist the SAME Forecast (no second network call, DATA-03) ONLY after a
    # successful delivery (WR-04). The fetch above stays inside the retried
    # callable so a fetch-429 ``httpx.HTTPStatusError`` (carrying Retry-After)
    # still propagates to the daemon wait callable (RELY-02) — but a FAILED attempt
    # no longer writes a duplicate ``weather_onecall`` row. The result is exactly
    # one persisted round per DELIVERED briefing, which is what the v2
    # forecast-vs-actual accuracy join wants.
    if result.ok:
        persist(db_path, result_lr.location, result_lr.forecast)

    _log.info(
        "send_now complete",
        location=result_lr.location.name,
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


def run_weather(
    location_name: str | None,
    *,
    config: Config,
    settings: Settings | None = None,
    client=None,
    templates_dir: str | Path | None = None,
    verbose: bool = False,
) -> int:
    """Standalone ``weather [location]`` path: read-only lookup, print, exit (D-08).

    The daemon-free one-shot deliverable (CMD-01/03/04/05). Wraps the shared
    read-only :func:`~weatherbot.interactive.lookup_weather` core in a SHORT
    bounded retry (``stop_after_attempt(3)``) so an attended transient blip
    (fetch 429/5xx/timeout) recovers in seconds. Unlike :func:`run_send_now`,
    there is NO :class:`DeliveryResult` on a read-only lookup, so the retry has
    ONLY the ``retry_if_exception(is_transient)`` arm — there is no
    ``retry_if_result`` arm and no ``retry_error_callback`` (D-08).

    Exit-code contract (D-05):

    * 0 — printed ``LookupResult.text`` (the exact v1 template, CMD-05) to stdout.
    * 1 — unknown location: prints :class:`UnknownLocationError`'s verbatim
      message (lists valid names) to stderr (CMD-04). ``resolve_location`` fails
      BEFORE any fetch, so the client's ``fetch_onecall`` is never called.
    * 3 — a fetch failure: an exhausted transient error OR a permanent auth
      (401/403) reraised on attempt 1. Logging is OUTCOME-ONLY (status code or
      exception type) — never the ``appid``/URL (T-07-02).

    The ``UnknownLocationError`` arm MUST precede any broad ``ValueError`` arm
    because ``UnknownLocationError`` IS-A ``ValueError`` and ``is_transient``
    returns False for it (reraised on attempt 1, never retried).
    """
    retrying = Retrying(
        stop=stop_after_attempt(_MANUAL_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=1, max=10),
        # Read-only path: ONLY the transient-exception arm. A permanent error
        # (auth 401/403, other 4xx) is not transient → reraised on attempt 1.
        # There is no DeliveryResult here, so no retry_if_result arm and no
        # retry_error_callback (D-08).
        retry=retry_if_exception(is_transient),
        reraise=True,
        sleep=time.sleep,  # patchable seam so tests run the bound in milliseconds
    )

    try:
        result = retrying(
            lookup_weather,
            location_name,
            config=config,
            settings=settings,
            client=client,
            templates_dir=templates_dir,
        )
    except UnknownLocationError as exc:
        # Reuse the error's verbatim message (lists valid names) to stderr (CMD-04,
        # D-06). MUST precede any broad ValueError arm — UnknownLocationError IS-A
        # ValueError and is reraised on attempt 1 (is_transient is False for it).
        print(str(exc), file=sys.stderr)
        return 1
    except httpx.HTTPStatusError as exc:
        # Outcome-only (T-07-02): never the appid/URL/exc.request.url.
        _log.error("weather lookup failed", status=exc.response.status_code)
        return 3
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
        _log.error("weather lookup failed", error=type(exc).__name__)
        return 3

    # Print the exact v1 template render (CMD-05) — result.text, unmodified.
    print(result.text)
    return 0


def _cmd_weather(args) -> int:
    """``weather`` subcommand dispatcher: load config (exit 2 if bad), then lookup.

    A bad/missing ``--config`` returns 2 here (D-05) — NOT the 1 the migrated
    flags use — so a configuration problem is distinguishable from an
    unknown-location (1) and a fetch failure (3).
    """
    config = _load_config_reporting(args.config)
    if config is None:
        return 2
    settings = load_settings()
    return run_weather(
        args.location,
        config=config,
        settings=settings,
        verbose=args.verbose,
    )


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


def do_reload(
    pid_file: str | Path = PID_FILE,
    *,
    _cmdline_reader=None,
) -> int:
    """Send ``SIGHUP`` to the running daemon — the ``weatherbot reload`` sender (CFG-02/D-03).

    The cross-process control path: a short-lived ``weatherbot reload`` process
    discovers the daemon PID and signals it to swap config live. Mirrors
    ``do_check``'s return-int + outcome-only-log contract (never a secret).

    Steps, all returning 1 (without signaling) on the safe-fail branches:
    (1) read the PID via :func:`~weatherbot.ops.pidfile.read_pid`; a missing or
    garbage PID file → "reload: no valid PID file" → 1. (2) pass the
    ``/proc/<pid>/cmdline`` staleness guard via
    :func:`~weatherbot.ops.pidfile.is_weatherbot_pid` — a missing/recycled PID
    that is NOT a weatherbot process → "reload: PID not running / not a weatherbot
    process" → 1 (T-09-06 PID-recycling defense, the signal is NEVER sent).
    (3) ``os.kill(pid, signal.SIGHUP)`` and return 0.

    ``_cmdline_reader`` injects the ``/proc`` reader so tests can stub the guard;
    production passes ``None`` and reads ``/proc`` directly.
    """
    try:
        pid = read_pid(pid_file)
    except (FileNotFoundError, ValueError):
        _log.error("reload: no valid PID file", path=str(pid_file))
        return 1

    if not is_weatherbot_pid(pid, cmdline_reader=_cmdline_reader):
        _log.error(
            "reload: PID not running / not a weatherbot process (stale or recycled)",
            pid=pid,
        )
        return 1

    os.kill(pid, signal.SIGHUP)
    _log.info("reload signal sent", pid=pid)
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


def _configure_logging(level: int) -> None:
    """Configure structlog to honor ``level`` and write logs to STDERR (D-09).

    structlog's DEFAULT configuration ignores the stdlib root level and renders to
    STDOUT — which both defeats D-09's quiet mode (the INFO "lookup complete" line
    survives a WARNING root level) AND pollutes the ``weather`` command's pipeable
    STDOUT with a log line above the briefing (breaking CMD-01's "stdout is just the
    briefing" contract). Configure structlog explicitly so (a) the effective level is
    enforced via ``make_filtering_bound_logger`` (so ``weather`` without ``-v`` at
    WARNING drops the INFO line) and (b) rendered logs go to STDERR via a
    ``PrintLoggerFactory(file=sys.stderr)`` — leaving STDOUT for the briefing only.
    """
    from weatherbot import _LiveStderr

    logging.basicConfig(level=level)  # keep the stdlib root coherent for any std logger
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=_LiveStderr()),
        cache_logger_on_first_use=False,
    )


def main(argv: list[str] | None = None) -> int:
    """Dispatch a subcommand and run the matching path (D-01/D-02).

    The CLI surface is ``add_subparsers``-based (clean break, no flag aliases):

    * ``weather [location] [-v]`` — standalone read-only one-shot: resolve the
      configured location, print the v1 briefing, exit. No daemon, no send, no DB
      write (CMD-01/03/04/05). Exit 0 ok / 1 unknown-location / 2 bad-config /
      3 fetch-failure (D-05). Quiet by default; ``-v`` restores INFO (D-09).
    * ``run`` — foreground always-on scheduler (blocks until SIGTERM/Ctrl-C).
    * ``check`` — validate config + template + one reachability probe; send nothing.
    * ``send-now [location]`` — send a briefing now (first/default when omitted).
    * ``geocode QUERY`` — setup-time lat/lon lookup; prints a config snippet.

    The four migrated subcommands keep their ORIGINAL exit codes (0/1); only
    ``weather`` uses the richer 0/1/2/3 scheme.
    """
    # Shared parent parser carrying the non-secret config path. Attached to every
    # subcommand that loads config; ``geocode`` deliberately omits it (it loads
    # only secrets, never the config).
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument(
        "--config",
        default="config.toml",
        help="Path to the non-secret TOML config (default: config.toml).",
    )

    parser = argparse.ArgumentParser(
        prog="weatherbot",
        description="Weather briefing CLI (one-shot lookup, scheduler, config tools).",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_weather = subparsers.add_parser(
        "weather",
        parents=[config_parent],
        help="Print the briefing for a configured location now (read-only one-shot).",
    )
    p_weather.add_argument(
        "location",
        nargs="?",
        default=None,
        help="Configured location name (omit for the first/default location).",
    )
    p_weather.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show INFO logging (quiet by default for the weather command, D-09).",
    )

    subparsers.add_parser(
        "run",
        parents=[config_parent],
        help="Run the always-on scheduler in the foreground (Ctrl-C / SIGTERM to stop).",
    )

    subparsers.add_parser(
        "check",
        parents=[config_parent],
        help="Validate config + template + one reachability probe without sending.",
    )

    subparsers.add_parser(
        "check-config",
        parents=[config_parent],
        help="Validate config + templates OFFLINE (no network); apply/send nothing (CFG-08).",
    )

    p_reload = subparsers.add_parser(
        "reload",
        help=(
            "Signal the running daemon to hot-reload its config (SIGHUP via the "
            "PID file; no config loaded by the sender — CFG-02)."
        ),
    )
    p_reload.add_argument(
        "--pid-file",
        default=str(PID_FILE),
        help=f"Path to the daemon PID file (default: {PID_FILE}).",
    )

    p_send_now = subparsers.add_parser(
        "send-now",
        parents=[config_parent],
        help="Send a briefing now (omit LOCATION for the first/default location).",
    )
    p_send_now.add_argument(
        "location",
        nargs="?",
        default=None,
        metavar="LOCATION",
        help="Location to send now (omit for the first/default location).",
    )

    p_geocode = subparsers.add_parser(
        "geocode",
        help=(
            'Resolve "City, ST" to lat/lon (setup-time only) and print a '
            "paste-ready config snippet. Never writes config; never runs on the "
            "send path."
        ),
    )
    p_geocode.add_argument(
        "query", metavar="QUERY", help='Place to resolve, e.g. "Austin, TX".'
    )

    args = parser.parse_args(argv)

    # D-09 quiet logging: basicConfig MUST run AFTER parse_args (a second
    # basicConfig call is a no-op, so the old unconditional INFO call defeated
    # this). The ``weather`` command without ``-v`` drops the root level to
    # WARNING so structlog's default config (which defers to the stdlib root)
    # suppresses lookup.py's "lookup complete" INFO line.
    level = logging.INFO
    if args.command == "weather" and not getattr(args, "verbose", False):
        level = logging.WARNING
    _configure_logging(level)

    # D-07 exit-2 overlap (intentional): argparse raises ``SystemExit(2)`` for bad
    # usage INSIDE parse_args, while a bad config returns ``2`` from
    # ``_cmd_weather``. Both mean "bad input"; tests distinguish them via
    # ``pytest.raises(SystemExit)`` vs ``main([...]) == 2``.
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "weather":
        return _cmd_weather(args)

    # geocode: setup-time lookup ONLY — load secrets, NOT the config/channel.
    if args.command == "geocode":
        settings = load_settings()
        return do_geocode(args.query, settings=settings)

    # check: validate everything, deliver nothing.
    if args.command == "check":
        config = _load_config_reporting(args.config)
        if config is None:
            return 1
        settings = load_settings()
        return do_check(config=config, settings=settings)

    # check-config: the OFFLINE subset of `check` (CFG-08, Pitfall 8) — parse +
    # schema + unique name/id + template-token validation via the SHARED validator,
    # ZERO network. It does NOT load Settings/secrets and NEVER calls
    # do_check/run_self_check (those probe the network).
    if args.command == "check-config":
        try:
            validate_config_and_templates(args.config)
        except (
            FileNotFoundError,
            tomllib.TOMLDecodeError,
            ValidationError,
            ValueError,
        ) as exc:
            _log.error("check-config failed", path=str(args.config), error=str(exc))
            return 1
        _log.info("check-config passed", path=str(args.config))
        return 0

    # reload: signal the running daemon to hot-reload (CFG-02). Loads NO config —
    # only the PID file + /proc guard + os.kill (do_reload).
    if args.command == "reload":
        return do_reload(args.pid_file)

    # run: foreground always-on scheduler (blocks until SIGTERM/Ctrl-C, D-09).
    if args.command == "run":
        config = _load_config_reporting(args.config)
        if config is None:
            return 1
        settings = load_settings()
        # Reuse the send-now db-dir prep so the sent-log DB dir exists before
        # the daemon starts. Import the daemon module HERE (not at module top) —
        # daemon imports send_now from this module, so a top-level import would
        # create a cycle.
        db_path = DEFAULT_DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        from weatherbot.scheduler import daemon

        return daemon.run_daemon(
            config=config, settings=settings, db_path=db_path, config_path=args.config
        )

    # send-now: single construction site (WR-04) — pass only ``settings`` and let
    # ``send_now`` build both the client and the channel. The manual path wraps
    # the single-attempt ``send_now`` in a SHORT bounded retry (D-10) so an
    # attended transient blip recovers; a final failure reports to the terminal
    # and writes NO alerts/heartbeat rows (those are daemon-liveness concerns).
    config = _load_config_reporting(args.config)
    if config is None:
        return 1
    settings = load_settings()

    db_path = DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return run_send_now(
        args.location,
        config=config,
        db_path=db_path,
        settings=settings,
    )
