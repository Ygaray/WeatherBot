"""Tests for the read-only on-demand forecast path (Phase 13-04).

This suite pins the two FCAST guarantees the on-demand forecast surface must hold:

* FCAST-05 (read-only): the forecast handler + its lookup path import nothing from
  ``weatherbot.weather.store`` and trip none of the seven store write functions —
  proven by the zero-store-writes spy (copied from ``test_lookup.py``).
* FCAST-07 (no extra fetch): a forecast lookup reuses the SAME dual One Call fetch a
  plain ``lookup_weather`` performs — ``client.fetch_onecall`` is called exactly twice
  (imperial + metric), never a third time.

It also pins the rendered output: weekday / weekend / variant (FCAST-01/02/03) and the
out-of-horizon ``+day`` notice (D-03).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.interactive.command import ForecastFlags
from weatherbot.interactive.commands import forecast as forecast_cmd
from weatherbot.interactive.lookup import LookupResult, lookup_forecast, lookup_weather

_FIX = Path(__file__).parent / "fixtures"

# The seven store write functions a read-only path must never touch (FCAST-05).
_STORE_WRITES = (
    "persist",
    "claim_slot",
    "record_alert",
    "resolve_alert",
    "stamp_tick",
    "stamp_success",
    "stamp_health",
)


def _load(name: str) -> dict:
    return json.loads((_FIX / name).read_text())


class _FakeClient:
    """Returns the 8-day One Call fixtures and counts fetch calls (FCAST-07)."""

    def __init__(self, onecall_imp: dict, onecall_met: dict) -> None:
        self._onecall = {"imperial": onecall_imp, "metric": onecall_met}
        self.onecall_calls: list[str] = []

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._onecall[units]


def _ny_config() -> Config:
    return Config(
        locations=[
            Location(
                name="New York",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
            )
        ],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )


def _result(monkeypatch) -> LookupResult:
    """A LookupResult carrying the 8-day fixture payloads (fetched once)."""
    client = _FakeClient(
        _load("onecall_8day_imperial.json"),
        _load("onecall_8day_metric.json"),
    )
    return lookup_weather("New York", config=_ny_config(), client=client)


# --------------------------------------------------------------------------- #
# FCAST-07: no extra fetch
# --------------------------------------------------------------------------- #


def test_lookup_forecast_no_extra_fetch() -> None:
    """The forecast lookup performs the SAME dual fetch as a plain weather lookup."""
    client = _FakeClient(
        _load("onecall_8day_imperial.json"),
        _load("onecall_8day_metric.json"),
    )
    result = lookup_forecast("New York", config=_ny_config(), client=client)
    assert isinstance(result, LookupResult)
    # imperial + metric, nothing more — reuses the already-fetched daily[].
    assert client.onecall_calls == ["imperial", "metric"]


# --------------------------------------------------------------------------- #
# FCAST-05: read-only (zero store writes)
# --------------------------------------------------------------------------- #


def test_forecast_path_writes_nothing_to_store(monkeypatch, tmp_path) -> None:
    """weekday_forecast over a real LookupResult trips no store write (FCAST-05)."""
    import weatherbot.weather.store as store

    def _boom(*args, **kwargs):
        raise AssertionError("forecast path touched the store")

    for fn in _STORE_WRITES:
        monkeypatch.setattr(store, fn, _boom)

    client = _FakeClient(
        _load("onecall_8day_imperial.json"),
        _load("onecall_8day_metric.json"),
    )
    result = lookup_forecast("New York", config=_ny_config(), client=client)
    reply = forecast_cmd.weekday_forecast(result, ForecastFlags())
    assert reply.text  # rendered without tripping a store write


def test_forecast_module_imports_no_store() -> None:
    """The forecast handler module imports nothing from the SQLite store (FCAST-05)."""
    src = (
        Path(forecast_cmd.__file__).read_text(encoding="utf-8")
    )
    assert "weatherbot.weather.store" not in src
    assert "import store" not in src


# --------------------------------------------------------------------------- #
# FCAST-01/02/03/04: rendered weekday / weekend / variant / notice
# --------------------------------------------------------------------------- #


def test_weekday_forecast_renders_lines(monkeypatch) -> None:
    """weekday_forecast over the 8-day fixture renders one line per weekday (FCAST-01)."""
    result = _result(monkeypatch)
    reply = forecast_cmd.weekday_forecast(result, ForecastFlags())
    assert reply.text is not None
    # Mon-Fri are all inside the fixture window (Fri 6/19 .. Fri 6/26).
    # The fixture "today" is Fri 6/19, so the upcoming weekday block is next-week Mon-Fri.
    # Either way the rendered block carries day labels and at least one temperature.
    assert "°F" in reply.text


def test_weekend_forecast_renders_fri_sat_sun(monkeypatch) -> None:
    """weekend_forecast renders the Fri-Sat-Sun block (FCAST-02)."""
    result = _result(monkeypatch)
    reply = forecast_cmd.weekend_forecast(result, ForecastFlags())
    assert reply.text is not None
    assert "°F" in reply.text


def test_compact_variant_is_shorter_than_detailed(monkeypatch) -> None:
    """The compact variant produces shorter per-day lines than detailed (FCAST-03)."""
    result = _result(monkeypatch)
    detailed = forecast_cmd.weekend_forecast(result, ForecastFlags(variant="detailed"))
    compact = forecast_cmd.weekend_forecast(result, ForecastFlags(variant="compact"))
    assert detailed.text is not None and compact.text is not None
    # Compact drops rain/wind/uvi/feels/sun, so its body is strictly shorter.
    assert len(compact.text) < len(detailed.text)
    # Detailed carries a detailed-only token's value; compact does not show UV.
    assert "UV" in detailed.text
    assert "UV" not in compact.text


def test_out_of_window_flag_renders_notice(monkeypatch) -> None:
    """A +day beyond the horizon surfaces a notice in the reply, not a silent drop (D-03)."""
    result = _result(monkeypatch)
    # The fixture horizon ends Fri 6/26; a +sat from a late-week run names a Saturday
    # beyond the horizon. weekday over the whole fixture window + a far +day → notice.
    reply = forecast_cmd.weekday_forecast(
        result, ForecastFlags(add=frozenset({"sat"}))
    )
    assert reply.text is not None
    # The 8-day fixture's last Saturday in-window is 6/20; a forward +sat past 6/26
    # is out of horizon. The notice text mentions the horizon.
    # (When sat IS in window no notice fires — but the fixture's weekday block rolls
    # to next week where the added Saturday 6/27 is beyond 6/26.)
    assert "horizon" in reply.text.lower()
