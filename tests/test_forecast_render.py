"""Tests for the forecast token vocabulary + code-rendered per-day block (Plan 13-02).

The renderer gains a forecast-specific token scope (``FORECAST_TOKENS``) and two
per-day scopes (``FORECAST_DAY_TOKENS_DETAILED`` / ``_COMPACT``) DISTINCT from the
daily-briefing ``CANONICAL`` set, plus a ``render_forecast`` helper that:

* validates the per-day ``line_fmt`` against the variant's day-token set (fail loud),
* code-iterates the days and joins them into the ``{days}`` block (no template loop),
* validates the whole-message ``template_text`` against ``FORECAST_TOKENS`` (fail loud).

This keeps the "no logic in templates" invariant (T-13-04) and the typo-fails-loud
guarantee (T-13-05): the per-day loop lives ONLY in code, and a typo'd ``{token}`` in
either the header or the line-format aborts at validate time, never shipping a literal.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.interactive.command import ForecastFlags
from weatherbot.interactive.commands import forecast as forecast_cmd
from weatherbot.interactive.lookup import LookupResult, lookup_weather
from templates.renderer import (
    CANONICAL,
    FORECAST_DAY_TOKENS_COMPACT,
    FORECAST_DAY_TOKENS_DETAILED,
    FORECAST_TOKENS,
    load_template,
    render,
    render_forecast,
    validate_template,
)

# ---------------------------------------------------------------------------
# Token-set shape (Pattern 1 — distinct from CANONICAL)
# ---------------------------------------------------------------------------


def test_token_sets_have_expected_keys():
    assert FORECAST_TOKENS == {
        "location",
        "title",
        "range_label",
        "days",
        "footer_note",
        "notice",
    }
    assert FORECAST_DAY_TOKENS_COMPACT == {"label", "high", "low", "sky"}
    assert FORECAST_DAY_TOKENS_DETAILED == {
        "label",
        "high",
        "low",
        "sky",
        "rain",
        "wind",
        "uvi",
        "feels_high",
        "feels_low",
        "sunrise",
        "sunset",
    }


def test_token_sets_distinct_from_canonical():
    # Forecast scopes are NOT an extension of the daily-briefing CANONICAL set.
    assert FORECAST_TOKENS != CANONICAL
    # CANONICAL daily-briefing keys (temp/feels_like/conditions/...) are NOT in
    # the forecast header scope.
    assert "temp" not in FORECAST_TOKENS
    assert "conditions" not in FORECAST_TOKENS
    # compact is a strict subset of detailed.
    assert FORECAST_DAY_TOKENS_COMPACT < FORECAST_DAY_TOKENS_DETAILED


# ---------------------------------------------------------------------------
# Per-day line-format validation (variant token scopes)
# ---------------------------------------------------------------------------


def test_detailed_line_format_with_all_tokens_validates_clean():
    line = (
        "{label}: {high}/{low} {sky} rain {rain} wind {wind} uv {uvi} "
        "feels {feels_high}/{feels_low} sun {sunrise}-{sunset}"
    )
    # All 11 detailed tokens — must validate without raising.
    validate_template(line, allowed=FORECAST_DAY_TOKENS_DETAILED)


def test_compact_line_format_with_detailed_token_fails_loud():
    # A compact line-format referencing a detailed-only token (uvi) must raise.
    line = "{label}: {high}/{low} {sky} uv {uvi}"
    with pytest.raises(ValueError):
        validate_template(line, allowed=FORECAST_DAY_TOKENS_COMPACT)


# ---------------------------------------------------------------------------
# render_forecast — code-iterated block + fail-loud header/line
# ---------------------------------------------------------------------------

_HEADER = "{title} — {location} ({range_label})\n{days}\n{notice}\n{footer_note}"
_DETAILED_LINE = "{label}: {high}/{low} {sky} rain {rain} wind {wind} uv {uvi}"
_COMPACT_LINE = "{label}: {high}/{low} {sky}"

_DAYS_DETAILED = [
    {
        "label": "Today",
        "high": "76°F (24°C)",
        "low": "60°F (16°C)",
        "sky": "Clear",
        "rain": "10%",
        "wind": "8 mph N (3.6 m/s)",
        "uvi": "7",
        "feels_high": "78°F (26°C)",
        "feels_low": "59°F (15°C)",
        "sunrise": "05:24",
        "sunset": "20:31",
    },
    {
        "label": "Tomorrow",
        "high": "80°F (27°C)",
        "low": "62°F (17°C)",
        "sky": "Clouds",
        "rain": "40%",
        "wind": "12 mph SW (5.4 m/s)",
        "uvi": "6",
        "feels_high": "83°F (28°C)",
        "feels_low": "61°F (16°C)",
        "sunrise": "05:24",
        "sunset": "20:32",
    },
]


def test_render_forecast_joins_n_days_into_n_lines():
    out = render_forecast(
        _HEADER,
        _DETAILED_LINE,
        _DAYS_DETAILED,
        {
            "title": "Weekday Forecast",
            "location": "New York",
            "range_label": "Mon-Fri",
            "notice": "",
            "footer_note": "— forecast",
        },
        day_allowed=FORECAST_DAY_TOKENS_DETAILED,
    )
    # The {days} slot carries exactly one line per day dict.
    assert "Today: 76°F (24°C)/60°F (16°C) Clear" in out
    assert "Tomorrow: 80°F (27°C)/62°F (17°C) Clouds" in out
    # Header tokens substituted.
    assert "Weekday Forecast — New York (Mon-Fri)" in out
    # No literal placeholder leaked.
    assert "{days}" not in out
    assert "{label}" not in out
    assert "{title}" not in out


def test_render_forecast_compact_variant():
    days = [
        {"label": d["label"], "high": d["high"], "low": d["low"], "sky": d["sky"]}
        for d in _DAYS_DETAILED
    ]
    out = render_forecast(
        "{title}\n{days}",
        _COMPACT_LINE,
        days,
        {
            "title": "Wknd",
            "location": "",
            "range_label": "",
            "notice": "",
            "footer_note": "",
        },
        day_allowed=FORECAST_DAY_TOKENS_COMPACT,
    )
    assert out.count("\n") >= len(days)  # one line per day inside the block
    assert "Today: 76°F (24°C)/60°F (16°C) Clear" in out


def test_render_forecast_typod_header_token_fails_loud():
    # A typo'd header token (not in FORECAST_TOKENS) must raise at validate time.
    bad_header = "{title}\n{days}\n{footr_note}"  # typo: footr_note
    with pytest.raises(ValueError):
        render_forecast(
            bad_header,
            _DETAILED_LINE,
            _DAYS_DETAILED,
            {
                "title": "x",
                "location": "",
                "range_label": "",
                "notice": "",
                "footer_note": "",
            },
            day_allowed=FORECAST_DAY_TOKENS_DETAILED,
        )


def test_render_forecast_typod_line_token_fails_loud():
    # A typo'd per-day line token must raise BEFORE any render.
    bad_line = "{label}: {hihg}/{low}"  # typo: hihg
    with pytest.raises(ValueError):
        render_forecast(
            _HEADER,
            bad_line,
            _DAYS_DETAILED,
            {
                "title": "x",
                "location": "",
                "range_label": "",
                "notice": "",
                "footer_note": "",
            },
            day_allowed=FORECAST_DAY_TOKENS_DETAILED,
        )


def test_render_forecast_no_str_format_in_renderer_source():
    # The forecast path must not introduce str.format/Formatter/eval (T-13-04).
    import templates.renderer as r

    src = "".join(
        line
        for line in open(r.__file__, encoding="utf-8").read().splitlines(keepends=True)
        if not line.lstrip().startswith("#")
    )
    # Strip the module docstring (which legitimately MENTIONS the forbidden idioms).
    body = re.sub(r'""".*?"""', "", src, count=0, flags=re.DOTALL)
    assert ".format(" not in body
    assert "Formatter" not in body
    assert "eval(" not in body


# ---------------------------------------------------------------------------
# Task 2 — the four templates + sibling line-format files validate clean
# ---------------------------------------------------------------------------

_DETAILED_TEMPLATES = (
    "forecast-weekday-detailed.txt",
    "forecast-weekend-detailed.txt",
)
_COMPACT_TEMPLATES = (
    "forecast-weekday-compact.txt",
    "forecast-weekend-compact.txt",
)
_ALL_TEMPLATES = _DETAILED_TEMPLATES + _COMPACT_TEMPLATES

_DETAILED_LINES = (
    "forecast-weekday-detailed.line.txt",
    "forecast-weekend-detailed.line.txt",
)
_COMPACT_LINES = (
    "forecast-weekday-compact.line.txt",
    "forecast-weekend-compact.line.txt",
)

_DETAILED_ONLY_TOKENS = {
    "rain",
    "wind",
    "uvi",
    "feels_high",
    "feels_low",
    "sunrise",
    "sunset",
}


def test_four_files_each_reference_days_slot():
    for name in _ALL_TEMPLATES:
        raw = load_template(name)
        assert "{days}" in raw, f"{name} must reference the code-built {{days}} block"


def test_each_template_validates_against_forecast_tokens():
    for name in _ALL_TEMPLATES:
        raw = load_template(name)
        # No typo'd header token — must validate clean against FORECAST_TOKENS.
        validate_template(raw, allowed=FORECAST_TOKENS)


def test_detailed_line_files_validate_against_detailed_tokens():
    for name in _DETAILED_LINES:
        line = load_template(name)
        validate_template(line, allowed=FORECAST_DAY_TOKENS_DETAILED)
        assert "\n" not in line.rstrip("\n"), f"{name} must be a single line"


def test_compact_line_files_validate_against_compact_tokens():
    for name in _COMPACT_LINES:
        line = load_template(name)
        validate_template(line, allowed=FORECAST_DAY_TOKENS_COMPACT)
        assert "\n" not in line.rstrip("\n"), f"{name} must be a single line"


def test_compact_line_files_reference_no_detailed_only_token():
    token = re.compile(r"\{(\w+)\}")
    for name in _COMPACT_LINES:
        used = {m.group(1) for m in token.finditer(load_template(name))}
        leaked = used & _DETAILED_ONLY_TOKENS
        assert not leaked, f"{name} references detailed-only tokens: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# Plan 33-06 — HARD-UI-03 render-formatting slice (F28 dedup / empty-token
# blanks / D-06 out-of-today date label). Handler-driven regressions.
# ---------------------------------------------------------------------------

_FIX = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIX / name).read_text())


class _FakeClient:
    """Returns the 8-day One Call fixtures (mirrors test_forecast_lookup)."""

    def __init__(self, onecall_imp: dict, onecall_met: dict) -> None:
        self._onecall = {"imperial": onecall_imp, "metric": onecall_met}

    def fetch_onecall(self, location, units):
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


def _forecast_result() -> LookupResult:
    client = _FakeClient(
        _load_fixture("onecall_8day_imperial.json"),
        _load_fixture("onecall_8day_metric.json"),
    )
    return lookup_weather("New York", config=_ny_config(), client=client)


def _monday() -> datetime:
    # Mon 6/22 → weekday block 6/22..6/26; 6/24+ are out-of-today buckets.
    return datetime(2026, 6, 22, 9, 0, tzinfo=ZoneInfo("America/New_York"))


def test_forecast_header_appears_once():
    """F28: no rendered body line equals the CommandReply.title.

    The embed keeps its title; the body must NOT repeat "{title} — {location}"
    as its first line, so the header shows exactly once across both surfaces.
    """
    reply = forecast_cmd.weekday_forecast(
        _forecast_result(), ForecastFlags(), now=_monday()
    )
    assert reply.title == "Weekday forecast — New York"
    body_lines = (reply.text or "").splitlines()
    # No body line may equal the title (with or without a leading emoji/marker).
    for line in body_lines:
        stripped = line.lstrip("📅 ").strip()
        assert stripped != reply.title, (
            f"body line duplicates the embed title (F28): {line!r}"
        )


def test_empty_token_no_trailing_blank():
    """D-08: a token substituting to "" leaves no trailing/interior blank line."""
    # A template whose LAST two tokens ({notice}, {footer_note}) render empty.
    template = "{title}\n{days}\n{notice}\n{footer_note}"
    out = render_forecast(
        template,
        _COMPACT_LINE,
        [{"label": "Today", "high": "70°F", "low": "60°F", "sky": "Clear"}],
        {
            "title": "Wknd",
            "location": "",
            "range_label": "",
            "notice": "",
            "footer_note": "",
        },
        day_allowed=FORECAST_DAY_TOKENS_COMPACT,
    )
    # No trailing blank line, and no interior run of blank lines from empty tokens.
    assert not out.endswith("\n"), f"trailing blank left by empty token: {out!r}"
    assert "\n\n" not in out, f"interior blank left by empty token: {out!r}"


def test_empty_token_interior_blank_collapsed():
    """An empty token BETWEEN content lines collapses, not just the trailing run."""
    template = "{title}\n{notice}\n{days}"
    out = render(template, {"title": "Head", "notice": "", "days": "Body"})
    assert out == "Head\nBody", f"empty interior token not collapsed: {out!r}"


def test_out_of_today_date_label():
    """D-06: out-of-today buckets render weekday + abbrev month + day (Thu Jul 17).

    Today/Tomorrow labels are unchanged; the ambiguous "Wed 6/24" numeric form
    is replaced by "Wed Jun 24".
    """
    reply = forecast_cmd.weekday_forecast(
        _forecast_result(), ForecastFlags(), now=_monday()
    )
    text = reply.text or ""
    assert "Today" in text
    assert "Tomorrow" in text
    # 6/24 is Wed → "Wed Jun 24"; the old ambiguous "Wed 6/24" must be gone.
    assert "Wed Jun 24" in text, f"missing weekday+abbrev-month+day label: {text!r}"
    assert "6/24" not in text, f"ambiguous numeric date label still present: {text!r}"
