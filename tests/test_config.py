"""Config / secrets layer tests (CONF-02, D-05/D-06/D-07/D-14).

These assert the secrets boundary (secrets live only on Settings, never on the
Config model or in config.toml), the list-of-locations seam (D-06), fail-loud
validation of malformed config, and resolve_location semantics (D-07).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from weatherbot.config import (
    Config,
    Location,
    Settings,
    WebhookIdentity,
    assert_unique_names,
    load_config,
    load_settings,
    resolve_location,
)

# Repo-root config.example.toml (proves CONF-01: editable without code changes).
EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.example.toml"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# --- CONF-02: secrets live only on Settings -------------------------------


def test_settings_reads_both_secrets_from_env(monkeypatch):
    monkeypatch.setenv("OPENWEATHER_API_KEY", "ow-key-123")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord/webhook/abc")
    s = Settings()
    assert s.openweather_api_key == "ow-key-123"
    assert s.discord_webhook_url == "https://discord/webhook/abc"


def test_load_settings_reads_from_dotenv_file(tmp_path, monkeypatch):
    # No env vars set; secrets come from a .env file.
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    env = _write(
        tmp_path,
        ".env",
        """
        OPENWEATHER_API_KEY=dotenv-key
        DISCORD_WEBHOOK_URL=https://discord/webhook/dotenv
        """,
    )
    s = load_settings(env_file=env)
    assert s.openweather_api_key == "dotenv-key"
    assert s.discord_webhook_url == "https://discord/webhook/dotenv"


def test_config_model_has_no_secret_fields():
    # CONF-02: the Config model must NOT carry api key / webhook URL secrets.
    fields = set(Config.model_fields)
    forbidden = {"api_key", "openweather_api_key", "webhook_url", "discord_webhook_url"}
    assert fields.isdisjoint(forbidden), f"secrets leaked onto Config: {fields & forbidden}"
    # WebhookIdentity is non-secret display config only (username, avatar_url).
    assert set(WebhookIdentity.model_fields) == {"username", "avatar_url"}


# --- D-06: locations is a list; load_config parses TOML --------------------


def test_load_config_parses_locations_list(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        template = "briefing-sectioned.txt"

        [[locations]]
        name = "Home"
        lat = 40.7128
        lon = -74.0060
        timezone = "America/New_York"

        [webhook]
        username = "WeatherBot ☀️"
        avatar_url = "https://example/avatar.png"
        """,
    )
    config = load_config(cfg_path)
    assert isinstance(config, Config)
    assert isinstance(config.locations, list)
    assert len(config.locations) == 1
    loc = config.locations[0]
    assert isinstance(loc, Location)
    assert loc.name == "Home"
    assert loc.lat == pytest.approx(40.7128)
    assert loc.lon == pytest.approx(-74.0060)
    assert config.template == "briefing-sectioned.txt"
    assert config.webhook.username == "WeatherBot ☀️"


def test_config_template_and_username_defaults(tmp_path):
    # template defaults; webhook username defaults to the desired identity.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 1.0
        lon = 2.0
        timezone = "America/New_York"

        [webhook]
        """,
    )
    config = load_config(cfg_path)
    assert config.template == "briefing-sectioned.txt"
    assert config.webhook.username == "WeatherBot ☀️"
    assert config.webhook.avatar_url is None


def test_malformed_location_missing_lat_fails_loud(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Broken"
        lon = 2.0

        [webhook]
        """,
    )
    with pytest.raises(ValidationError):
        load_config(cfg_path)


# --- D-07: resolve_location --------------------------------------------------


def _two_location_config() -> Config:
    return Config(
        locations=[
            Location(name="Home", lat=40.0, lon=-74.0, timezone="America/New_York"),
            Location(
                name="Travel City",
                lat=34.0,
                lon=-118.0,
                timezone="America/Los_Angeles",
            ),
        ],
        webhook=WebhookIdentity(),
    )


def test_resolve_location_none_returns_first():
    config = _two_location_config()
    assert resolve_location(config, None) is config.locations[0]


def test_resolve_location_matches_case_insensitive():
    config = _two_location_config()
    got = resolve_location(config, "travel city")
    assert got.name == "Travel City"


def test_resolve_location_unknown_name_raises_value_error():
    config = _two_location_config()
    with pytest.raises(ValueError):
        resolve_location(config, "Nowhere")


# --- LOC-02 / CONF-03: timezone (required IANA) + units (optional) ----------


def test_location_fields_timezone_and_units_parse(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 40.7128
        lon = -74.0060
        timezone = "America/New_York"
        units = "imperial"

        [webhook]
        """,
    )
    config = load_config(cfg_path)
    loc = config.locations[0]
    assert loc.timezone == "America/New_York"
    assert loc.units == "imperial"


def test_location_units_optional_defaults_none(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 1.0
        lon = 2.0
        timezone = "Europe/London"

        [webhook]
        """,
    )
    config = load_config(cfg_path)
    assert config.locations[0].units is None


def test_location_missing_timezone_fails_loud(tmp_path):
    # timezone is REQUIRED (D-03): omitting it must fail loudly at load.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 1.0
        lon = 2.0

        [webhook]
        """,
    )
    with pytest.raises(ValidationError):
        load_config(cfg_path)


def test_bad_timezone_raises_validation_error():
    # A non-IANA zone string must raise (zoneinfo-backed validator, not a list).
    with pytest.raises(ValidationError):
        Location(name="Home", lat=1.0, lon=2.0, timezone="Not/AZone")


def test_invalid_units_value_fails_loud():
    # Only imperial/metric allowed (A6: standard/Kelvin intentionally excluded).
    with pytest.raises(ValidationError):
        Location(
            name="Home", lat=1.0, lon=2.0, timezone="America/New_York", units="kelvin"
        )
    with pytest.raises(ValidationError):
        Location(
            name="Home",
            lat=1.0,
            lon=2.0,
            timezone="America/New_York",
            units="standard",
        )


# --- LOC-01: ≥2 independent locations load + resolve ------------------------


def test_multi_location_config_loads_and_resolves(tmp_path):
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 40.7128
        lon = -74.0060
        timezone = "America/New_York"

        [[locations]]
        name = "Weekend"
        lat = 25.7617
        lon = -80.1918
        timezone = "America/New_York"
        units = "metric"

        [webhook]
        """,
    )
    config = load_config(cfg_path)
    assert len(config.locations) == 2
    assert resolve_location(config, "Home").name == "Home"
    assert resolve_location(config, "weekend").name == "Weekend"


# --- assert_unique_names: duplicate (casefold) names fail loud --------------


def test_assert_unique_names_passes_for_distinct():
    config = _two_location_config()
    assert_unique_names(config)  # does not raise


def test_assert_unique_names_rejects_casefold_duplicates():
    config = Config(
        locations=[
            Location(name="Home", lat=1.0, lon=2.0, timezone="America/New_York"),
            Location(name="home", lat=3.0, lon=4.0, timezone="America/New_York"),
        ],
        webhook=WebhookIdentity(),
    )
    with pytest.raises(ValueError):
        assert_unique_names(config)


# --- SCHD-01/02: per-location schedule entries load + fail loud -------------


def test_multiple_schedule_entries(tmp_path):
    # SCHD-01/02: a location can carry multiple [[locations.schedule]] entries,
    # one enabled and one enabled=false (toggle-without-delete); both load.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 40.7128
        lon = -74.0060
        timezone = "America/New_York"

        [[locations.schedule]]
        time = "07:00"
        days = "mon-fri"
        enabled = true

        [[locations.schedule]]
        time = "12:00"
        days = "weekends"
        enabled = false

        [webhook]
        """,
    )
    config = load_config(cfg_path)
    sched = config.locations[0].schedule
    assert len(sched) == 2
    assert sched[0].time == "07:00"
    assert sched[0].enabled is True
    assert sched[1].enabled is False  # retained, not deleted
    # accessors the trigger/planner share
    assert sched[0].parsed_time() == (7, 0)
    assert sched[1].day_of_week == "sat,sun"


def test_schedule_defaults_empty(tmp_path):
    # A location with no schedule loads with schedule == [] (default_factory).
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 1.0
        lon = 2.0
        timezone = "America/New_York"

        [webhook]
        """,
    )
    config = load_config(cfg_path)
    assert config.locations[0].schedule == []


def test_bad_days_fails_load(tmp_path):
    # SCHD-02: a bad days token fails loudly at config load.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 1.0
        lon = 2.0
        timezone = "America/New_York"

        [[locations.schedule]]
        time = "07:00"
        days = "funday"

        [webhook]
        """,
    )
    with pytest.raises(ValidationError):
        load_config(cfg_path)


def test_bad_time_fails_load(tmp_path):
    # SCHD-02: a malformed HH:MM time fails loudly at config load.
    cfg_path = _write(
        tmp_path,
        "config.toml",
        """
        [[locations]]
        name = "Home"
        lat = 1.0
        lon = 2.0
        timezone = "America/New_York"

        [[locations.schedule]]
        time = "24:00"
        days = "mon-fri"

        [webhook]
        """,
    )
    with pytest.raises(ValidationError):
        load_config(cfg_path)


def test_schedule_model_direct_validation():
    from weatherbot.config.models import Schedule

    assert Schedule(time="07:00", days="mon-fri", enabled=True).enabled is True
    for bad_time in ("7am", "24:00", "07:60", "7:00"):
        with pytest.raises(ValidationError):
            Schedule(time=bad_time, days="mon-fri")
    with pytest.raises(ValidationError):
        Schedule(time="07:00", days="funday")


# --- CONF-01: the shipped config.example.toml loads cleanly -----------------


def test_example_config_loads_cleanly():
    config = load_config(EXAMPLE_CONFIG)
    assert len(config.locations) >= 2
    for loc in config.locations:
        assert loc.timezone  # every example location carries an IANA timezone
    assert_unique_names(config)
