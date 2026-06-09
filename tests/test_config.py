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
    load_config,
    load_settings,
    resolve_location,
)


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
            Location(name="Home", lat=40.0, lon=-74.0),
            Location(name="Travel City", lat=34.0, lon=-118.0),
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
