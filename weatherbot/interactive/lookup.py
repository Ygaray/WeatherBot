"""The read-only fetch->render core: ``lookup_weather`` (Phase 06-02).

``lookup_weather`` resolves a configured location, fetches imperial+metric via
the existing One Call client, builds one :class:`~weatherbot.weather.models.Forecast`,
renders the exact v1 template, and returns a :class:`LookupResult`. It is the
seam two future surfaces share: P7's CLI prints ``LookupResult.text`` and P11's
Discord bot builds an embed from ``LookupResult.forecast`` — both without
re-fetching. Plan 06-03's ``send_now`` will delegate to it.

HARD CONSTRAINT (D-06): this core is READ-ONLY. It takes no database path, imports
nothing from the SQLite store package, and writes none of the seven store
functions — proven by the zero-store-writes spy test. An unknown location name
raises :class:`UnknownLocationError`, a backward-compatible ``ValueError``
subclass carrying ``.requested`` + ``.valid_names`` (D-07).

Import-cycle note (Pitfall 3): ``build_client`` lives in ``weatherbot.cli``,
which imports interactive modules transitively. To avoid a cli<->interactive
cycle, ``build_client`` is LAZILY imported INSIDE the ``client is None`` branch
(matching the cli.py lazy-daemon-import precedent); tests inject a client so the
import never runs offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog

from weatherbot.config import resolve_location
from weatherbot.scheduler.context import schedule_placeholders
from weatherbot.weather.models import Forecast
from templates.renderer import load_template, render, validate_template

if TYPE_CHECKING:
    from weatherbot.config.models import Config, Location
    from weatherbot.config.settings import Settings

_log = structlog.get_logger(__name__)


class UnknownLocationError(ValueError):
    """Raised when a requested location name matches no configured location (D-07).

    Subclasses ``ValueError`` so every existing ``except ValueError`` caller
    (``resolve_location``'s historical contract, ``run_send_now``, ``do_check``)
    stays green (Pitfall 5). Carries the offending ``requested`` name and the
    ``valid_names`` list so a caller (CLI, Discord) can offer a corrective hint
    without re-reading config. Never carries the ``appid``/webhook URL (T-06-05).
    """

    def __init__(self, requested: str, valid_names: list[str]) -> None:
        self.requested = requested
        self.valid_names = valid_names
        super().__init__(
            f"No location named {requested!r}; "
            f"configured locations: {', '.join(valid_names)}"
        )


@dataclass
class LookupResult:
    """The read-only lookup's return value (D-05).

    Bundles the three things both future surfaces need: ``text`` (the rendered v1
    briefing the CLI prints), ``forecast`` (the structured data the Discord embed
    builds from), and ``location`` (the resolved target). Mirrors the
    ``ScheduleContext``/``DeliveryResult`` plain-dataclass house style.
    """

    text: str
    forecast: Forecast
    location: Location


def lookup_weather(
    name: str | None,
    *,
    config: Config,
    settings: Settings | None = None,
    client=None,
    templates_dir: str | None = None,
    extra_placeholders: dict[str, str] | None = None,
) -> LookupResult:
    """Resolve, fetch, render — the read-only core (D-05/D-06/D-07).

    ``name`` resolves via :func:`~weatherbot.config.resolve_location` (``None`` ->
    first/default; case-insensitive match), which now raises
    :class:`UnknownLocationError` on no-match. The One Call ``client`` is
    injectable for tests; otherwise it is built from ``settings`` (requiring a
    ``settings`` when no client is given). Both units are fetched (imperial first,
    FCST-04/DATA-03 order); the per-location ``units`` override only flips which
    unit LEADS the display (CR-01). On-demand timing matches the manual
    ``--send-now`` path: ``{sent_at}``/``{checked_at}`` are computed in the
    location's own timezone with no :class:`ScheduleContext` (Open Question 1).
    ``extra_placeholders`` is merged LAST so a caller (e.g. a future scheduled
    delegation) can override the timing keys — preserving send_now's merge order.

    Writes NOTHING to the store (D-06): no database-path parameter, no store import.
    """
    location = resolve_location(config, name)

    if client is None:
        if settings is None:
            raise ValueError("lookup_weather requires either a client or settings")
        # Lazy import INSIDE this branch to break the cli<->interactive import
        # cycle (Pitfall 3; matches cli.py's lazy-daemon-import precedent). Tests
        # inject a client so this never runs offline.
        from weatherbot.cli import build_client  # pragma: no cover - production-only: tests always inject a client; this lazy build_client makes a real OpenWeather client (network/cli edge), deliberately bypassed offline

        client = build_client(settings)  # pragma: no cover - production-only (see above): builds a live network client

    # Dual fetch: imperial first (FCST-04/DATA-03 order), then metric for the
    # parenthetical secondary value.
    onecall_imp = client.fetch_onecall(location, "imperial")
    onecall_met = client.fetch_onecall(location, "metric")

    primary = location.units or "imperial"
    # Thread the configured global UV threshold (D-01 single source of truth) into
    # BOTH the sunscreen hint and the new UV briefing line.
    forecast = Forecast.from_payloads(
        location,
        onecall_imp,
        onecall_met,
        primary=primary,
        uv_threshold=config.uv.threshold,
    )

    # Validate the template at the load boundary (D-10/11): a typo'd {token}
    # aborts loudly here rather than shipping a literal placeholder.
    if templates_dir is not None:
        template_text = load_template(config.template, templates_dir)
    else:
        template_text = load_template(config.template)
    validate_template(template_text)

    # On-demand timing (Open Question 1): a bare lookup renders the same
    # location-local {sent_at}/{checked_at} a manual --send-now would, via the
    # schedule_ctx=None form. extra_placeholders merges LAST so a caller can
    # override the timing keys (send_now's exact merge order/precedence).
    tz = ZoneInfo(location.timezone)
    now = datetime.now(tz)
    values = dict(forecast.placeholders())
    values.update(schedule_placeholders(None, now, now))
    if extra_placeholders:
        values.update(extra_placeholders)

    text = render(template_text, values)

    _log.info("lookup complete", location=location.name)
    return LookupResult(text=text, forecast=forecast, location=location)


def lookup_forecast(
    name: str | None,
    *,
    config: Config,
    settings: Settings | None = None,
    client=None,
) -> LookupResult:
    """The read-only multi-day forecast lookup path (FCAST-05/07).

    A multi-day forecast needs nothing the daily lookup did not already fetch:
    ``lookup_weather`` performs the dual imperial+metric ``fetch_onecall`` and
    retains BOTH raw One Call payloads on the returned ``Forecast``
    (``raw_onecall_imp``/``raw_onecall_met``), which carry the ready-made
    ``daily[]`` aggregates the forecast handler reads. So this path simply
    DELEGATES to ``lookup_weather`` — there is NO extra OpenWeather call beyond
    the existing dual fetch (FCAST-07) and NO new endpoint (``client.py`` is
    untouched).

    Like ``lookup_weather`` this is READ-ONLY (FCAST-05): it takes no database
    path, imports nothing from the SQLite store, and writes none of the store
    functions. It exists as a NAMED seam so the on-demand forecast dispatch (CLI
    + Discord) and the cache can route forecast requests through one place
    distinct from a plain ``weather`` lookup, without re-deriving the dual-fetch
    contract. The daily-briefing template render performed by ``lookup_weather``
    is harmless overhead the forecast handler ignores (it reads ``.forecast``,
    not ``.text``).
    """
    return lookup_weather(name, config=config, settings=settings, client=client)
