"""Scaffolds for the CLI subcommands landing in Plans 02-03 / 02-04.

This file exists NOW (Wave 0, Plan 02-01) so the test surface is named before
any production code reads One Call. Every test name matches a research ``-k``
selector so later slices can fill the body in and flip the marker off — the
same strict-xfail-then-remove discipline ``test_send_now.py`` followed through
Phase 1 (see that file's module docstring).

Until the feature lands, each test is ``@pytest.mark.xfail(strict=False)``:
the suite stays GREEN now and the test starts PASSING (xpass) the moment the
behavior ships, signalling "remove this marker".

The ``_FakeClient`` / ``_FakeChannel`` mirror ``test_send_now.py`` so the
``--check`` reachability and ``--send-now`` composition paths can be exercised
offline (no network, no real webhook) once they exist.
"""

from __future__ import annotations

import pytest


class _FakeClient:
    """Returns recorded fixtures and records fetch calls (mirrors test_send_now)."""

    def __init__(self, current_imp, current_met, forecast_imp, forecast_met):
        self._current = {"imperial": current_imp, "metric": current_met}
        self._forecast = {"imperial": forecast_imp, "metric": forecast_met}
        self.current_calls: list[str] = []
        self.forecast_calls: list[str] = []

    def fetch_current(self, location, units):
        self.current_calls.append(units)
        return self._current[units]

    def fetch_forecast(self, location, units):
        self.forecast_calls.append(units)
        return self._forecast[units]


class _FakeChannel:
    """Captures the rendered body and the Forecast (mirrors test_send_now)."""

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self.briefing_forecasts: list[object] = []
        self._result = DeliveryResult(ok=True)

    def send_briefing(self, text, forecast):
        self.sent_text.append(text)
        self.briefing_forecasts.append(forecast)
        return self._result


# --- --geocode subcommand (Plan 02-03) -----------------------------------------


@pytest.mark.xfail(reason="--geocode implemented in 02-03", strict=False)
def test_geocode_prints_coords(load_fixture, capsys):
    """`--geocode "Austin"` resolves to lat/lon via /geo/1.0/direct and prints them."""
    raise NotImplementedError("--geocode lands in Plan 02-03")


@pytest.mark.xfail(reason="geocode-on-send guard implemented in 02-03", strict=False)
def test_send_now_never_geocodes(load_fixture, tmp_db):
    """--send-now must use configured lat/lon and never hit the geocoding API."""
    raise NotImplementedError("send-now/geocode separation verified in Plan 02-03")


# --- --check subcommand (Plan 02-04) -------------------------------------------


@pytest.mark.xfail(reason="--check implemented in 02-04", strict=False)
def test_check_validates_config(tmp_path):
    """`--check` validates the config file (locations, schedules, template) offline."""
    raise NotImplementedError("--check config validation lands in Plan 02-04")


@pytest.mark.xfail(reason="--check reachability implemented in 02-04", strict=False)
def test_check_reachability_one_call(load_fixture, monkeypatch):
    """`--check` probes One Call 3.0 reachability via a mocked transport."""
    raise NotImplementedError("--check reachability probe lands in Plan 02-04")


@pytest.mark.xfail(reason="bad-template abort implemented in 02-04", strict=False)
def test_send_now_bad_template_aborts(tmp_path):
    """A malformed/missing template aborts --send-now before any network call."""
    raise NotImplementedError("template pre-flight abort lands in Plan 02-04")


@pytest.mark.xfail(reason="unique-name validation implemented in 02-04", strict=False)
def test_check_unique_names():
    """`--check` rejects a config with duplicate location names."""
    raise NotImplementedError("unique-name validation lands in Plan 02-04")
