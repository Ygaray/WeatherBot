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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
    """The forecast handler module imports nothing from the SQLite store (FCAST-05).

    Scans the parsed AST import statements only (NOT docstring prose, which legitimately
    references the store package to explain the read-only contract).
    """
    import ast

    src = Path(forecast_cmd.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imported.append(mod)
            imported.extend(f"{mod}.{alias.name}" for alias in node.names)
    assert not any("store" in name for name in imported), imported


# --------------------------------------------------------------------------- #
# FCAST-01/02/03/04: rendered weekday / weekend / variant / notice
# --------------------------------------------------------------------------- #


def _monday() -> datetime:
    return datetime(2026, 6, 22, 9, 0, tzinfo=ZoneInfo("America/New_York"))


def _friday() -> datetime:
    return datetime(2026, 6, 19, 9, 0, tzinfo=ZoneInfo("America/New_York"))


def test_weekday_forecast_renders_lines(monkeypatch) -> None:
    """weekday_forecast over the 8-day fixture renders one line per weekday (FCAST-01)."""
    result = _result(monkeypatch)
    # Run on Mon 6/22 → the full Mon-Fri block (6/22..6/26) is in window.
    reply = forecast_cmd.weekday_forecast(result, ForecastFlags(), now=_monday())
    assert reply.text is not None
    assert "°F" in reply.text
    # Five weekday lines: Today/Tomorrow + three abbreviated dates.
    assert "Today" in reply.text
    assert "Tomorrow" in reply.text


def test_weekend_forecast_renders_fri_sat_sun(monkeypatch) -> None:
    """weekend_forecast renders the Fri-Sat-Sun block (FCAST-02)."""
    result = _result(monkeypatch)
    # Run on Fri 6/19 → Fri 6/19, Sat 6/20, Sun 6/21 in window.
    reply = forecast_cmd.weekend_forecast(result, ForecastFlags(), now=_friday())
    assert reply.text is not None
    assert "°F" in reply.text
    assert "Today" in reply.text  # Fri 6/19


def test_compact_variant_is_shorter_than_detailed(monkeypatch) -> None:
    """The compact variant produces shorter per-day lines than detailed (FCAST-03)."""
    result = _result(monkeypatch)
    detailed = forecast_cmd.weekend_forecast(
        result, ForecastFlags(variant="detailed"), now=_friday()
    )
    compact = forecast_cmd.weekend_forecast(
        result, ForecastFlags(variant="compact"), now=_friday()
    )
    assert detailed.text is not None and compact.text is not None
    # Compact drops rain/wind/uvi/feels/sun, so its body is strictly shorter.
    assert len(compact.text) < len(detailed.text)
    # Detailed carries a detailed-only token's value; compact does not show UV.
    assert "UV" in detailed.text
    assert "UV" not in compact.text


def test_imperial_metric_paired_by_dt_not_position(monkeypatch) -> None:
    """WR-01: imperial/metric daily[] are paired by dt, not by shared index.

    The imperial and metric payloads come from two SEPARATE fetches. Simulate a
    length/ordering skew by DROPPING the first metric daily entry, then assert the
    "Today" line's parenthetical metric value matches THAT day's own dt (the correct
    metric), never the wrong-day metric a positional pairing would have produced.
    """
    result = _result(monkeypatch)
    raw_imp = result.forecast.raw_onecall_imp["daily"]
    raw_met = result.forecast.raw_onecall_met["daily"]

    # On Mon 6/22 the first selected ("Today") day is imperial index 3 (6/22). Its
    # CORRECT metric max is the metric entry with the SAME dt; a +1 positional skew
    # (after we drop the first metric day) would instead pick index 4's metric.
    today_dt = raw_imp[3]["dt"]
    today_met = next(d for d in raw_met if d["dt"] == today_dt)
    correct_met_max = round(today_met["temp"]["max"])  # Today's TRUE metric max (21)
    skewed_met = raw_met[4]  # what positional index 3 points at after dropping met[0]
    wrong_met_max = round(skewed_met["temp"]["max"])  # the wrong-day metric (28)
    assert correct_met_max != wrong_met_max

    # Skew: drop the first metric day so positional index i now points one day late.
    result.forecast.raw_onecall_met["daily"] = raw_met[1:]

    reply = forecast_cmd.weekday_forecast(result, ForecastFlags(), now=_monday())
    assert reply.text is not None
    today_line = next(
        ln for ln in reply.text.splitlines() if "📆" in ln and "Today" in ln
    )
    # The Today line must show ITS OWN metric value, paired by dt...
    assert f"({correct_met_max}°C)" in today_line
    # ...NOT the wrong-day metric a position-based pairing would have shown.
    assert f"({wrong_met_max}°C)" not in today_line


def test_out_of_window_flag_renders_notice(monkeypatch) -> None:
    """A +day beyond the horizon surfaces a notice in the reply, not a silent drop (D-03)."""
    result = _result(monkeypatch)
    # The fixture horizon ends Fri 6/26. Run on Thu 6/25 with +sat → next Saturday is
    # 6/27, beyond the horizon → a notice (never a silent drop). Inject a fixed clock
    # so the assertion is deterministic regardless of the real system date.
    now = datetime(2026, 6, 25, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    reply = forecast_cmd.weekday_forecast(
        result, ForecastFlags(add=frozenset({"sat"})), now=now
    )
    assert reply.text is not None
    assert "horizon" in reply.text.lower()
