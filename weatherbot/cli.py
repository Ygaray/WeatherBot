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
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from weatherbot.channels import build_channel
from weatherbot.config import load_config, load_settings, resolve_location
from weatherbot.weather.client import fetch_onecall, geocode
from weatherbot.weather.models import Forecast
from weatherbot.weather.store import persist
from templates.renderer import load_template, render

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
) -> DeliveryResult:
    """Run the full pipeline for the resolved location (Pattern 2, DATA-03).

    Resolves the location (``None`` → first, D-07), fetches ONCE (One Call 3.0,
    both units — 2 calls), builds one :class:`Forecast`, then from that SAME
    forecast: persists it (no extra fetch), renders the briefing text, and
    delivers it via the Discord channel's ``send_briefing`` (embed attached
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
    onecall_imp = client.fetch_onecall(location, "imperial")
    onecall_met = client.fetch_onecall(location, "metric")

    forecast = Forecast.from_payloads(location, onecall_imp, onecall_met)

    # Same Forecast feeds BOTH consumers — no second network call (DATA-03).
    persist(db_path, location, forecast)
    text = render(load_template(config.template), forecast.placeholders())

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
        "--config",
        default="config.toml",
        help="Path to the non-secret TOML config (default: config.toml).",
    )
    args = parser.parse_args(argv)

    if not hasattr(args, "send_now"):
        parser.print_help()
        return 0

    config = load_config(args.config)
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
