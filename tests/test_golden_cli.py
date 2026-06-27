"""Byte-exact CLI stdout goldens + inline exit-code pins (Plan 21-03, D-02/D-03/D-10).

These pin the ``weatherbot`` CLI's *observable bytes* — the stdout a real invocation
prints, per offline subcommand and per forecast variant — as the byte-identical oracle the
later registry/dispatch (Phase 26) and config-reload (Phase 24) extractions re-run. An
intent-test asserts "a briefing was printed"; THIS asserts the exact bytes, so a copy-edit,
a reordered field, or a single flipped character anywhere in stdout surfaces as a real diff.

Serializer split (D-02): stdout is pinned via the raw-bytes ``bytes_snapshot``
(``SingleFileSnapshotExtension``) so one byte flip fails; the exit code is pinned as an
INLINE literal (``assert rc == 0``, D-03) so the expected value is visible in the source.

Offline / gateway-free / secret-free (Pitfall 5 / V7): every case drives ``cli.main(argv)``
against a temp ``config.toml`` (never the host ``.env``) — the offline subcommands
(``help``/``check-config``/``locations``/``status``) make ZERO network calls, and the
forecast variants inject a fixture-built ``LookupResult`` by monkeypatching
``cli.lookup_weather`` (the ``test_cli.py`` precedent) so no ``appid``/webhook/URL is ever
reached. ``cli.load_settings`` is stubbed to ``None`` so the real ``.env`` never loads.
``weatherbot.cli.time.sleep`` is patched to a no-op so any bounded retry pause is instant.

Frozen clock (D-11 — freeze, don't scrub): every case runs inside
``time_machine.travel(FROZEN, tick=False)`` so any clock-derived stdout (the forecast
window selection, time tokens) is a deterministic literal — and the forecast handlers are
additionally pinned with ``now=FROZEN`` (their documented test seam) so the rendered day set
is stable across runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import time_machine

from tests.conftest import FROZEN
from weatherbot.cli import main
from weatherbot.config import Location

_FIXTURE_DIR = Path(__file__).parent / "fixtures"

# A stable IANA tz so every clock-derived token is deterministic under FROZEN.
_LOCATION = Location(
    name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York"
)


def _load(name: str) -> dict:
    """Read a recorded OpenWeather fixture by file name (offline, no network)."""
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _good_config_file(tmp_path: Path) -> Path:
    """Write a minimal VALID config.toml and return its path (the test_cli.py idiom)."""
    p = tmp_path / "config.toml"
    p.write_text(
        'template = "briefing-sectioned.txt"\n'
        "[[locations]]\n"
        'name = "New York"\n'
        "lat = 40.7128\n"
        "lon = -74.006\n"
        'timezone = "America/New_York"\n\n'
        "[[locations.schedule]]\n"
        'time = "07:00"\n'
        'days = "mon-fri"\n',
        encoding="utf-8",
    )
    return p


def _forecast_result(load_fixture):
    """A LookupResult carrying the 8-day One Call payloads (forecast rendering, no net)."""
    from weatherbot.interactive.lookup import LookupResult
    from weatherbot.weather.models import Forecast

    forecast = Forecast.from_payloads(
        _LOCATION,
        load_fixture("onecall_8day_imperial.json"),
        load_fixture("onecall_8day_metric.json"),
        now_utc=FROZEN,
    )
    return LookupResult(text="", forecast=forecast, location=_LOCATION)


# --------------------------------------------------------------------------- #
# Offline subcommands — ZERO network, no config needed for `help`. Each pins the
# exact stdout bytes + an inline exit-code literal (D-02/D-03).
# --------------------------------------------------------------------------- #


def test_help_stdout_golden(bytes_snapshot, capsys):
    """``weatherbot help`` prints every registry command, fetch-free, exit 0."""
    with time_machine.travel(FROZEN, tick=False):
        rc = main(["help"])
    out = capsys.readouterr().out
    assert rc == 0  # inline exit-code pin (D-03)
    assert out.encode() == bytes_snapshot  # raw-bytes stdout golden (D-02)


def test_check_config_stdout_golden(tmp_path, bytes_snapshot, capsys):
    """``check-config`` on a GOOD config validates OFFLINE (zero network), exit 0."""
    good = _good_config_file(tmp_path)
    with time_machine.travel(FROZEN, tick=False):
        rc = main(["check-config", "--config", str(good)])
    out = capsys.readouterr().out
    assert rc == 0  # inline exit-code pin (D-03)
    assert out.encode() == bytes_snapshot


def test_locations_stdout_golden(tmp_path, bytes_snapshot, capsys):
    """``locations`` prints the configured location names (no fetch), exit 0."""
    good = _good_config_file(tmp_path)
    with time_machine.travel(FROZEN, tick=False):
        rc = main(["locations", "--config", str(good)])
    out = capsys.readouterr().out
    assert rc == 0  # inline exit-code pin (D-03)
    assert out.encode() == bytes_snapshot


def test_status_stdout_golden(tmp_path, monkeypatch, bytes_snapshot, capsys):
    """``status`` runs the read-only status handler (no live scheduler/bot), exit 0.

    The CLI ``status`` reads the *last-briefing heartbeat* from ``cli.DEFAULT_DB_PATH``
    (the daemon's SQLite db). On a real host that points at the LIVE daemon's db, whose
    ``last_success_utc`` is a moving wall-clock value — a determinism + host leak that
    would make the golden flake (and embed a real send time). Redirect ``DEFAULT_DB_PATH``
    at a fresh tmp db so the read is the deterministic "never run yet" branch (D-11:
    isolate the clock-derived value, never snapshot the host's live state).
    """
    good = _good_config_file(tmp_path)
    monkeypatch.setattr(
        "weatherbot.cli.DEFAULT_DB_PATH", tmp_path / "weatherbot.db", raising=False
    )
    with time_machine.travel(FROZEN, tick=False):
        rc = main(["status", "--config", str(good)])
    out = capsys.readouterr().out
    assert rc == 0  # inline exit-code pin (D-03)
    assert out.encode() == bytes_snapshot


# --------------------------------------------------------------------------- #
# Forecast variants — weekday/weekend × detailed/compact (D-10, one case per cell).
# A fixture-built LookupResult is injected via monkeypatched ``cli.lookup_weather``
# (the test_cli.py precedent) so NO network / NO secret is reached; ``+detailed`` /
# ``+compact`` flags route through the shared grammar. ``now=FROZEN`` + the frozen
# clock pin the rendered day set so the stdout bytes are stable.
# --------------------------------------------------------------------------- #


def _forecast_stdout_case(
    tmp_path, monkeypatch, load_fixture, *, command: str, variant_flag: str
):
    """Drive a forecast subcommand through ``main`` with an injected fixture lookup."""
    good = _good_config_file(tmp_path)
    monkeypatch.setattr(
        "weatherbot.cli.lookup_weather",
        lambda name, *, config, settings: _forecast_result(load_fixture),
    )
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)
    monkeypatch.setattr("weatherbot.cli.time.sleep", lambda _d: None, raising=False)
    with time_machine.travel(FROZEN, tick=False):
        rc = main([command, "New York", variant_flag, "--config", str(good)])
    return rc


def test_weekday_forecast_detailed_stdout_golden(
    tmp_path, monkeypatch, load_fixture, bytes_snapshot, capsys
):
    """Weekday × detailed forecast stdout, byte-exact, frozen window, exit 0."""
    rc = _forecast_stdout_case(
        tmp_path,
        monkeypatch,
        load_fixture,
        command="weekday-forecast",
        variant_flag="+detailed",
    )
    out = capsys.readouterr().out
    assert rc == 0  # inline exit-code pin (D-03)
    assert out.encode() == bytes_snapshot


def test_weekday_forecast_compact_stdout_golden(
    tmp_path, monkeypatch, load_fixture, bytes_snapshot, capsys
):
    """Weekday × compact forecast stdout, byte-exact, frozen window, exit 0."""
    rc = _forecast_stdout_case(
        tmp_path,
        monkeypatch,
        load_fixture,
        command="weekday-forecast",
        variant_flag="+compact",
    )
    out = capsys.readouterr().out
    assert rc == 0  # inline exit-code pin (D-03)
    assert out.encode() == bytes_snapshot


def test_weekend_forecast_detailed_stdout_golden(
    tmp_path, monkeypatch, load_fixture, bytes_snapshot, capsys
):
    """Weekend × detailed forecast stdout, byte-exact, frozen window, exit 0."""
    rc = _forecast_stdout_case(
        tmp_path,
        monkeypatch,
        load_fixture,
        command="weekend-forecast",
        variant_flag="+detailed",
    )
    out = capsys.readouterr().out
    assert rc == 0  # inline exit-code pin (D-03)
    assert out.encode() == bytes_snapshot


def test_weekend_forecast_compact_stdout_golden(
    tmp_path, monkeypatch, load_fixture, bytes_snapshot, capsys
):
    """Weekend × compact forecast stdout, byte-exact, frozen window, exit 0."""
    rc = _forecast_stdout_case(
        tmp_path,
        monkeypatch,
        load_fixture,
        command="weekend-forecast",
        variant_flag="+compact",
    )
    out = capsys.readouterr().out
    assert rc == 0  # inline exit-code pin (D-03)
    assert out.encode() == bytes_snapshot
