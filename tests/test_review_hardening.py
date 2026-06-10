"""Regression tests for the two critical findings in 01-REVIEW.md.

CR-01 — the renderer must NOT expose attribute/index/positional access through
``str.format`` field parsing, and must never crash on a malformed template
(threat mitigations T-03-02 / T-03-03).

CR-02 — a present-but-``null`` field in an OpenWeather payload must not crash the
briefing pipeline. ``dict.get(key, default)`` returns ``None`` when the key is
present with a null value, so every consumer must coerce null, not rely on the
default. This protects the project's core reliability constraint (retry/alert,
never silently miss a briefing).
"""

from __future__ import annotations

from datetime import datetime, timezone

from weatherbot.config.models import Location
from weatherbot.weather.models import Forecast
from weatherbot.weather.store import persist

from templates.renderer import render

NOW = datetime(2024, 6, 14, 12, 0, tzinfo=timezone.utc)
DT = int(NOW.timestamp())
LOC = Location(name="X", lat=0.0, lon=0.0, timezone="America/New_York")


# --- CR-01: renderer hardening -------------------------------------------------


def test_attribute_access_is_not_evaluated():
    # str.format would resolve {conditions.__class__}; the guarded renderer must
    # leave it literal (no attribute traversal — T-03-02).
    out = render("{conditions.__class__}", {"conditions": "Rain"})
    assert out == "{conditions.__class__}"


def test_index_access_is_not_evaluated():
    out = render("{a[0]}", {"a": "hello"})
    assert out == "{a[0]}"


def test_positional_field_does_not_crash():
    # {0} would raise IndexError under vformat with no positional args.
    out = render("{0}", {"a": "1"})
    assert out == "{0}"


def test_unbalanced_brace_does_not_crash():
    # A lone '{' makes str.format raise ValueError; the renderer must not crash.
    out = render("now 100% {temp", {"temp": "72"})
    assert "{temp" in out


def test_known_placeholder_still_substitutes():
    assert render("hi {name}", {"name": "Bob"}) == "hi Bob"


# --- CR-02: present-but-null field tolerance (One Call path) -------------------
#
# The three CR-02 *bucket* null-tolerance tests were dropped in Plan 02-01: the
# 2.5 bucket high/low/rain logic was retired (D-01), so those tests no longer have
# a subject. The two ``from_payloads`` null-tolerance tests below were rewritten in
# Plan 02-02 for the One Call ``from_payloads(loc, onecall_imp, onecall_met)``
# signature + the now-required ``timezone`` on ``LOC`` (no longer xfail). They
# exercise the same CR-02 reliability guarantee against the One Call
# ``or {}``/``or []`` defenses — including the clear-day case where the ``current``,
# ``daily`` and ``alerts`` members are present-but-null (Pitfall 2).


def test_forecast_from_payloads_tolerates_null_current_fields():
    # Present-but-null current/daily/alerts must NOT raise (CR-02 / Pitfall 2).
    onecall = {"current": None, "daily": None, "alerts": None}
    fc = Forecast.from_payloads(LOC, onecall, onecall, now_utc=NOW)
    # Must not raise; display fields are safe to read.
    assert fc.temp_display
    assert fc.conditions == ""
    # A null ``alerts`` member collapses {alert} cleanly (Pitfall 2).
    assert fc.alert == ""
    # Derived content never crashes on a null payload (it may degrade to default
    # zeros; the contract here is "does not raise", not a specific hint string).
    assert isinstance(fc.hint, str)


def test_persist_tolerates_minimal_onecall_payload(tmp_db):
    # A minimal One Call payload missing the optional generated-column source
    # fields must persist without raising (the weather_onecall write tolerates
    # absent json_extract sources).
    onecall = {"current": {"temp": 1.0}, "daily": [{"temp": {}}]}
    fc = Forecast.from_payloads(LOC, onecall, onecall, now_utc=NOW)
    persist(tmp_db, LOC, fc)
