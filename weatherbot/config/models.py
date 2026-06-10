"""Non-secret configuration models (validated at load time).

These models hold ONLY non-secret structure (locations, template choice, webhook
display identity). Secrets (API key, webhook URL) live exclusively on
``Settings`` (see ``settings.py``) and must never appear here (CONF-02).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Desired Discord webhook display identity (D-14).
DEFAULT_USERNAME = "WeatherBot ☀️"  # "WeatherBot ☀️"
DEFAULT_TEMPLATE = "briefing-sectioned.txt"

# Only imperial/metric are valid briefing units; "standard" (Kelvin) is
# intentionally excluded (A6 — a weather briefing is never in Kelvin).
_VALID_UNITS = {"imperial", "metric"}


class Location(BaseModel):
    """A single configured location (D-05: raw lat/lon + display name).

    Coordinates are provided directly (resolved once via ``--geocode``, LOC-03).
    ``timezone`` is the configured IANA zone, authoritative for "today"/`daily[0]`
    selection (D-03); ``from_payloads`` reads it to compute the local date. As of
    Plan 02-03 it is REQUIRED and validated against the IANA database via
    ``zoneinfo`` (a fake zone fails loud at load). ``units`` is an OPTIONAL
    per-location override (``imperial``/``metric`` only, D-03/A6).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    lat: float
    lon: float
    timezone: str
    units: str | None = None

    @field_validator("timezone")
    @classmethod
    def _tz_must_be_real(cls, v: str) -> str:
        # Let the stdlib own the IANA database (Don't Hand-Roll a zone list).
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"{v!r} is not a valid IANA timezone") from e
        return v

    @field_validator("units")
    @classmethod
    def _units_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_UNITS:
            raise ValueError(f"units must be one of {sorted(_VALID_UNITS)}, got {v!r}")
        return v


class WebhookIdentity(BaseModel):
    """Discord webhook display identity (D-14) — non-secret presentation only.

    The webhook URL itself is a secret and lives on ``Settings``, not here.
    """

    model_config = ConfigDict(extra="forbid")

    username: str = DEFAULT_USERNAME
    avatar_url: str | None = None


class Config(BaseModel):
    """Top-level non-secret config parsed from ``config.toml``.

    ``locations`` is a LIST even with one entry (D-06) so Phase 2 multi-location
    needs no refactor. This model carries NO secret field (CONF-02).
    """

    model_config = ConfigDict(extra="forbid")

    locations: list[Location]
    template: str = DEFAULT_TEMPLATE
    webhook: WebhookIdentity = Field(default_factory=WebhookIdentity)
