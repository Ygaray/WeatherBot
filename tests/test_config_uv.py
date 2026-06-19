"""UV config table tests (UV-03, D-01).

Assert the new `[uv]` table loads/validates/hot-reloads via the existing
whole-Config loader: an absent table defaults to threshold 6.0 (zero migration
under extra="forbid"); an out-of-range threshold, a negative lead, and an
unknown `[uv]` key all fail loud at load; and editing the threshold + re-reading
the whole Config (the reload path) picks up the new value with no extra wiring.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from weatherbot.config import Config, UvConfig, load_config


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


_BASE_LOCATION = """
[[locations]]
name = "Home"
lat = 40.7128
lon = -74.0060
timezone = "America/New_York"
"""


# --- Defaults: absent [uv] table loads as defaults (zero migration) --------


def test_absent_uv_table_defaults(tmp_path):
    # An existing config with no [uv] table loads unchanged under extra="forbid".
    cfg_path = _write(tmp_path, "config.toml", _BASE_LOCATION)
    config = load_config(cfg_path)
    assert config.uv.threshold == pytest.approx(6.0)
    assert config.uv.pre_warn_lead_minutes == 30
    # Phase-15 monitor knobs default sensibly when the [uv] table is absent.
    assert config.uv.monitor_enabled is True
    assert config.uv.interval_seconds == 900
    assert config.uv.value_margin == pytest.approx(1.0)


def test_partial_uv_table_defaults_monitor_knobs(tmp_path):
    # A [uv] table that sets ONLY threshold still loads; the monitor knobs default.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        threshold = 5.0
        """,
    )
    config = load_config(cfg_path)
    assert config.uv.threshold == pytest.approx(5.0)
    assert config.uv.monitor_enabled is True
    assert config.uv.interval_seconds == 900
    assert config.uv.value_margin == pytest.approx(1.0)


def test_uv_field_is_frozen_uvconfig():
    # The field default factory yields a UvConfig with the D-01 defaults.
    config = Config(locations=[])
    assert isinstance(config.uv, UvConfig)
    assert config.uv.threshold == pytest.approx(6.0)
    assert config.uv.pre_warn_lead_minutes == 30
    # Frozen snapshot — assignment is rejected (ConfigHolder-compatible).
    with pytest.raises(ValidationError):
        config.uv.threshold = 7.0


# --- Explicit values load -----------------------------------------------------


def test_uv_threshold_loads(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        threshold = 4.0
        """,
    )
    config = load_config(cfg_path)
    assert config.uv.threshold == pytest.approx(4.0)
    # Lead defaults when only threshold is set.
    assert config.uv.pre_warn_lead_minutes == 30


def test_uv_lead_loads(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        threshold = 7.5
        pre_warn_lead_minutes = 45
        """,
    )
    config = load_config(cfg_path)
    assert config.uv.threshold == pytest.approx(7.5)
    assert config.uv.pre_warn_lead_minutes == 45


# --- Fail-loud validation (T-14-01) ------------------------------------------


def test_threshold_out_of_range_fails_loud(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        threshold = 25
        """,
    )
    with pytest.raises(ValueError, match="threshold"):
        load_config(cfg_path)


def test_threshold_negative_fails_loud(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        threshold = -1.0
        """,
    )
    with pytest.raises(ValueError, match="threshold"):
        load_config(cfg_path)


def test_negative_lead_fails_loud(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        pre_warn_lead_minutes = -5
        """,
    )
    with pytest.raises(ValueError):
        load_config(cfg_path)


def test_lead_over_upper_bound_fails_loud(tmp_path):
    # WR-04: a nonsensical lead (e.g. 100000 min ~ 69 days) must fail loud at load,
    # consistent with the file's fail-loud-at-both-ends posture, rather than
    # silently mis-configure the Phase-15 monitor.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        pre_warn_lead_minutes = 100000
        """,
    )
    with pytest.raises(ValueError, match="pre_warn_lead_minutes"):
        load_config(cfg_path)


def test_lead_at_upper_bound_loads(tmp_path):
    # The ceiling (720) itself is accepted — only values ABOVE it fail.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        pre_warn_lead_minutes = 720
        """,
    )
    config = load_config(cfg_path)
    assert config.uv.pre_warn_lead_minutes == 720


# --- Phase-15 monitor knobs: explicit load + fail-loud validation -----------


def test_monitor_knobs_load(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        monitor_enabled = false
        interval_seconds = 600
        value_margin = 2.5
        """,
    )
    config = load_config(cfg_path)
    assert config.uv.monitor_enabled is False
    assert config.uv.interval_seconds == 600
    assert config.uv.value_margin == pytest.approx(2.5)


def test_interval_seconds_below_floor_fails_loud(tmp_path):
    # A sub-minute interval would hammer the API on a config typo — fail loud.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        interval_seconds = 30
        """,
    )
    with pytest.raises(ValueError, match="interval_seconds"):
        load_config(cfg_path)


def test_interval_seconds_at_floor_loads(tmp_path):
    # The floor (60) itself is accepted — only values BELOW it fail.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        interval_seconds = 60
        """,
    )
    config = load_config(cfg_path)
    assert config.uv.interval_seconds == 60


def test_interval_seconds_above_ceiling_fails_loud(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        interval_seconds = 100000
        """,
    )
    with pytest.raises(ValueError, match="interval_seconds"):
        load_config(cfg_path)


def test_value_margin_negative_fails_loud(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        value_margin = -1.0
        """,
    )
    with pytest.raises(ValueError, match="value_margin"):
        load_config(cfg_path)


def test_value_margin_above_ceiling_fails_loud(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        value_margin = 25
        """,
    )
    with pytest.raises(ValueError, match="value_margin"):
        load_config(cfg_path)


def test_unknown_uv_key_fails_loud(tmp_path):
    # extra="forbid": an unknown [uv] key aborts the load.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        foo = 1
        """,
    )
    with pytest.raises(ValidationError):
        load_config(cfg_path)


# --- Hot-reload: re-reading the whole Config picks up the edit ---------------


def test_reload_picks_up_threshold_edit(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        threshold = 3.0
        """,
    )
    first = load_config(cfg_path)
    assert first.uv.threshold == pytest.approx(3.0)

    # Edit the threshold and re-read the whole Config (the existing reload path).
    cfg_path.write_text(
        textwrap.dedent(
            _BASE_LOCATION
            + """
            [uv]
            threshold = 9.0
            """
        ),
        encoding="utf-8",
    )
    second = load_config(cfg_path)
    assert second.uv.threshold == pytest.approx(9.0)


def test_reload_picks_up_monitor_knob_edits(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        _BASE_LOCATION
        + """
        [uv]
        interval_seconds = 900
        value_margin = 1.0
        monitor_enabled = true
        """,
    )
    first = load_config(cfg_path)
    assert first.uv.interval_seconds == 900
    assert first.uv.value_margin == pytest.approx(1.0)
    assert first.uv.monitor_enabled is True

    # Edit the monitor knobs and re-read the whole Config (the existing reload path).
    cfg_path.write_text(
        textwrap.dedent(
            _BASE_LOCATION
            + """
            [uv]
            interval_seconds = 1800
            value_margin = 3.0
            monitor_enabled = false
            """
        ),
        encoding="utf-8",
    )
    second = load_config(cfg_path)
    assert second.uv.interval_seconds == 1800
    assert second.uv.value_margin == pytest.approx(3.0)
    assert second.uv.monitor_enabled is False
