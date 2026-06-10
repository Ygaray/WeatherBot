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
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog
from pydantic import ValidationError

from weatherbot.channels import build_channel
from weatherbot.config import (
    assert_unique_names,
    load_config,
    load_settings,
    resolve_location,
)
from weatherbot.weather.client import fetch_onecall, geocode
from weatherbot.weather.models import Forecast
from weatherbot.weather.store import persist
from templates.renderer import load_template, render, validate_template

if TYPE_CHECKING:
    from weatherbot.channels.base import Channel, DeliveryResult
    from weatherbot.config.models import Config
    from weatherbot.config.settings import Settings

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
) -> DeliveryResult:
    """Run the full pipeline for the resolved location (Pattern 2, DATA-03).

    Resolves the location (``None`` → first, D-07), fetches ONCE (One Call 3.0,
    both units — 2 calls), builds one :class:`Forecast` whose display primary is
    the location's ``units`` override (``imperial`` when unset, CR-01), then from
    that SAME forecast: persists it (no extra fetch), renders the briefing text,
    and delivers it via the Discord channel's ``send_briefing`` (embed attached
    internally). ``client``/``channel`` are injectable for testing; otherwise
    they are built from ``settings``.
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

    # Same Forecast feeds BOTH consumers — no second network call (DATA-03).
    persist(db_path, location, forecast)
    # Validate the template at the load boundary (D-10/11): a typo'd {token}
    # aborts the send loudly here rather than shipping a literal placeholder.
    if templates_dir is not None:
        template_text = load_template(config.template, templates_dir)
    else:
        template_text = load_template(config.template)
    validate_template(template_text)
    text = render(template_text, forecast.placeholders())

    # Explicit dispatch (WR-05): every channel exposes ``send_briefing``. The
    # base default delegates to the text-only ``send``; Discord overrides it to
    # attach its embed internally. The canonical body is always ``text``.
    result = channel.send_briefing(text, forecast)

    _log.info(
        "send_now complete",
        location=location.name,
        delivered=result.ok,
    )
    return result


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
    try:
        # (1) Config is already loaded/validated (IANA tz + units fired at load).
        if not config.locations:
            raise ValueError("No locations configured in config.toml")

        # (2) Template placeholders are all canonical (D-10).
        validate_template(load_template(config.template))

        # (4a) Names are unique so --send-now "<name>" is unambiguous (CONF-05).
        assert_unique_names(config)

        # (4b) Every configured location resolves by name.
        for loc in config.locations:
            resolve_location(config, loc.name)

        # (3) ONE live reachability probe — no delivery, never retried here.
        if client is None:
            if settings is None:
                raise ValueError("do_check requires either a client or settings")
            client = build_client(settings)
        try:
            client.fetch_onecall(config.locations[0], "imperial")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                # Distinguish subscription-not-active from a generic error WITHOUT
                # leaking the key (Pitfall 1 / T-04-02).
                raise ValueError(
                    "One Call reachability probe returned "
                    f"{status}: the OpenWeather key or its 'One Call by Call' "
                    "subscription may not be active or not yet propagated — "
                    "wait a few hours and retry."
                ) from exc
            raise
    except Exception as exc:  # noqa: BLE001 — surface any check failure as outcome
        _log.error("config check failed", error=str(exc))
        return 1

    # Nothing should ever have been delivered.
    if channel is not None and getattr(channel, "sent_text", None):
        _log.error("config check unexpectedly delivered a briefing")
        return 1

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
    # ``send_now`` build both the client and the channel. Tests inject
    # pre-built ``client``/``channel`` directly.
    result = send_now(
        args.send_now,
        config=config,
        db_path=db_path,
        settings=settings,
    )

    if result.ok:
        _log.info("briefing delivered")
        return 0
    _log.error("briefing delivery failed", detail=result.detail)
    return 1
