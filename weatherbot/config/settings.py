"""Secrets settings — the ONLY place secrets enter the process (CONF-02).

Reads ``OPENWEATHER_API_KEY`` and ``DISCORD_WEBHOOK_URL`` from the environment /
a ``.env`` file via pydantic-settings. These values must never be written to
``config.toml``, committed to git, or logged (the webhook URL is itself a
bearer-style credential).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bearer-style secrets loaded from env / ``.env``.

    ``extra="ignore"`` so unrelated env vars on the host do not break startup.
    Field names map case-insensitively to ``OPENWEATHER_API_KEY`` and
    ``DISCORD_WEBHOOK_URL``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openweather_api_key: str
    discord_webhook_url: str
