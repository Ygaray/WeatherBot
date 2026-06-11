"""Non-secret configuration models (validated at load time).

These models hold ONLY non-secret structure (locations, template choice, webhook
display identity). Secrets (API key, webhook URL) live exclusively on
``Settings`` (see ``settings.py``) and must never appear here (CONF-02).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from weatherbot.scheduler.days import parse_days

# Desired Discord webhook display identity (D-14).
DEFAULT_USERNAME = "WeatherBot ☀️"  # "WeatherBot ☀️"
DEFAULT_TEMPLATE = "briefing-sectioned.txt"

# Only imperial/metric are valid briefing units; "standard" (Kelvin) is
# intentionally excluded (A6 — a weather briefing is never in Kelvin).
_VALID_UNITS = {"imperial", "metric"}

# Phase 3's startup catch-up grace window (90 min). The two-burst retry budget
# (D-07) must finish well inside it, else a slow retry could outlast the window in
# which a missed slot is still re-fireable. Belt-and-suspenders guard (Pitfall 5).
_CATCHUP_GRACE_SECONDS = 90 * 60  # 5400s


class Schedule(BaseModel):
    """One send slot for a location (D-01/D-02/D-03).

    ``time`` is a 24-hour ``HH:MM`` string in the location's IANA timezone;
    ``days`` is a friendly preset or comma list (validated/normalized via
    ``parse_days``); ``enabled`` defaults true and may be set false to pause a
    slot WITHOUT deleting it (toggle-without-delete, SCHD-02).

    ``days`` is stored RAW (so logs/announce stay human-friendly, e.g.
    ``"weekends"``) and normalized at use via :attr:`day_of_week`; the trigger
    and the catch-up planner (Plan 03) consume :meth:`parsed_time` /
    :attr:`day_of_week` so they share one source of truth.
    """

    model_config = ConfigDict(extra="forbid")

    time: str
    days: str
    enabled: bool = True

    @field_validator("time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        try:
            hh, mm = v.split(":")
            h, m = int(hh), int(mm)
            if not (len(hh) == 2 and len(mm) == 2 and 0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except Exception as e:
            raise ValueError(f"time must be 'HH:MM' 24-hour, got {v!r}") from e
        return v

    @field_validator("days")
    @classmethod
    def _days_valid(cls, v: str) -> str:
        # Raises on a bad token (fail-loud-at-load, D-02). Keep the RAW value;
        # normalize at use via ``day_of_week``.
        parse_days(v)
        return v

    def parsed_time(self) -> tuple[int, int]:
        """Return the ``(hour, minute)`` of this slot's ``HH:MM`` time."""
        hh, mm = self.time.split(":")
        return int(hh), int(mm)

    @property
    def day_of_week(self) -> str:
        """The normalized APScheduler ``day_of_week`` string for ``days``."""
        return parse_days(self.days)


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
    schedule: list[Schedule] = Field(default_factory=list)

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


class Reliability(BaseModel):
    """Retry-budget config for the two-burst daemon retry engine (D-07/D-09).

    The retry engine (Plan 04-01) fires two bursts of ``attempts_per_burst`` attempts,
    each burst spread over ``burst_spread_seconds``, separated by a single
    ``mid_pause_seconds`` pause. These are the ONLY user-tunable timing knobs.

    Validated fail-loud at load (D-09), in the Phase-2 ``Schedule`` tradition: every
    field must be positive, and the total worst-case budget
    ``2*burst_spread_seconds + mid_pause_seconds`` must stay UNDER Phase 3's 90-min
    catch-up grace window (belt-and-suspenders, Pitfall 5) so a slow retry never
    outlives the window in which the missed slot is still re-fireable.

    Defaults are the D-07 values (8 / 600 / 2700 ≈ 65 min total), so an existing
    config with no ``[reliability]`` section loads unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    attempts_per_burst: int = 8
    burst_spread_seconds: int = 600
    mid_pause_seconds: int = 2700

    @field_validator("attempts_per_burst", "burst_spread_seconds", "mid_pause_seconds")
    @classmethod
    def _must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"reliability timing values must be > 0, got {v!r}")
        return v

    @model_validator(mode="after")
    def _budget_under_grace(self) -> Reliability:
        total = 2 * self.burst_spread_seconds + self.mid_pause_seconds
        if total >= _CATCHUP_GRACE_SECONDS:
            raise ValueError(
                "retry budget too large: "
                f"2*burst_spread_seconds + mid_pause_seconds = {total}s must stay "
                f"under the {_CATCHUP_GRACE_SECONDS}s (90-min) catch-up grace window"
            )
        return self


class Config(BaseModel):
    """Top-level non-secret config parsed from ``config.toml``.

    ``locations`` is a LIST even with one entry (D-06) so Phase 2 multi-location
    needs no refactor. This model carries NO secret field (CONF-02).
    """

    model_config = ConfigDict(extra="forbid")

    locations: list[Location]
    template: str = DEFAULT_TEMPLATE
    webhook: WebhookIdentity = Field(default_factory=WebhookIdentity)
    reliability: Reliability = Field(default_factory=Reliability)
