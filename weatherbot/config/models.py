"""Non-secret configuration models (validated at load time).

These models hold ONLY non-secret structure (locations, template choice, webhook
display identity). Secrets (API key, webhook URL) live exclusively on
``Settings`` (see ``settings.py``) and must never appear here (CONF-02).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from weatherbot.reliability.retry import RETRY_AFTER_CAP_S
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

    model_config = ConfigDict(extra="forbid", frozen=True)

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

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    # OPTIONAL stable sent-log identity (D-01). When omitted it defaults to the
    # RAW ``name`` verbatim (see ``_default_id_from_name``) so the exactly-once
    # ``(location, send_time, local_date)`` key stays BYTE-IDENTICAL to existing
    # rows for any config that never sets ``id`` (zero migration). An explicit
    # ``id`` wins, giving a rename-safe stable identity. Casefold is used ONLY in
    # the uniqueness check (loader), never for this stored value.
    id: str | None = None
    lat: float
    lon: float
    timezone: str
    units: str | None = None
    schedule: list[Schedule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_id_from_name(self) -> Location:
        # Default the optional ``id`` to the RAW ``name`` verbatim (NOT lowered,
        # NOT slugged) for the zero-migration sent-log key (D-01 / Pitfall 1 Option
        # A). frozen=True forbids normal assignment, so use ``object.__setattr__``
        # — the pydantic-blessed escape hatch inside an after-validator (mirrors
        # ``Reliability._budget_under_grace`` below).
        if self.id is None:
            object.__setattr__(self, "id", self.name)
        return self

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

    model_config = ConfigDict(extra="forbid", frozen=True)

    username: str = DEFAULT_USERNAME
    avatar_url: str | None = None


class Reliability(BaseModel):
    """Retry-budget config for the two-burst daemon retry engine (D-07/D-09).

    The retry engine (Plan 04-01) fires two bursts of ``attempts_per_burst`` attempts,
    each burst spread over ``burst_spread_seconds``, separated by a single
    ``mid_pause_seconds`` pause. These are the ONLY user-tunable timing knobs.

    Validated fail-loud at load (D-09), in the Phase-2 ``Schedule`` tradition:
    ``attempts_per_burst`` must be >= 2 (CR-01) and the seconds fields > 0, and the
    ACTUAL jittered worst-case budget must stay UNDER Phase 3's 90-min catch-up
    grace window (belt-and-suspenders, Pitfall 5) so a slow retry never outlives
    the window in which the missed slot is still re-fireable. That worst case is
    ``(2n-2) * max(within_max, RETRY_AFTER_CAP_S) + mid_pause_seconds`` where
    ``within_max = (burst_spread_seconds/(n-1)) * 1.5`` (the jitter ceiling) — NOT
    the naive ``2*burst_spread_seconds + mid_pause_seconds`` sum, which understates
    the within-burst jitter and ignores the capped Retry-After term (WR-01/WR-02).

    Defaults are the D-07 values (8 / 600 / 2700): worst case
    ``14 * max(128.6, 120) + 2700 ≈ 4500s ≈ 75 min``, comfortably under the 90-min
    grace. An existing config with no ``[reliability]`` section loads unchanged.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempts_per_burst: int = 8
    burst_spread_seconds: int = 600
    mid_pause_seconds: int = 2700

    @field_validator("attempts_per_burst", "burst_spread_seconds", "mid_pause_seconds")
    @classmethod
    def _must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"reliability timing values must be > 0, got {v!r}")
        return v

    @field_validator("attempts_per_burst")
    @classmethod
    def _attempts_at_least_two(cls, v: int) -> int:
        # The two-burst within-burst spread is step = burst_spread/(n-1); for n=1
        # that is a division by zero (CR-01). A single attempt per burst is also
        # not a "burst" — reject it loud at load instead of crashing at 9am.
        if v < 2:
            raise ValueError(
                f"attempts_per_burst must be >= 2 (the burst spread is undefined "
                f"for a single attempt), got {v!r}"
            )
        return v

    def worst_case_seconds(self) -> float:
        """The ACTUAL jittered worst-case wall-clock budget (WR-01/WR-02).

        Single source of truth for BOTH the load-time guard below AND the
        ``--check`` budget echo (so the operator-facing "approx total" can never
        drift from the value the validator actually enforces). With ``2n`` total
        attempts there are ``2n-1`` waits: one mid-pause and ``2n-2`` within-burst
        waits, each at most ``step*1.5`` (jitter ceiling) — but on a 429 the honored
        wait can be up to ``RETRY_AFTER_CAP_S``, so the worst per-retry contribution
        is ``max(within_max, cap)``. ``attempts_per_burst >= 2`` is guaranteed by
        the field validator, so ``n-1`` is never zero.
        """
        n = self.attempts_per_burst
        within_max = (self.burst_spread_seconds / (n - 1)) * 1.5
        per_retry = max(within_max, RETRY_AFTER_CAP_S)
        return (2 * n - 2) * per_retry + self.mid_pause_seconds

    @model_validator(mode="after")
    def _budget_under_grace(self) -> Reliability:
        worst = self.worst_case_seconds()
        if worst >= _CATCHUP_GRACE_SECONDS:
            n = self.attempts_per_burst
            per_retry = max((self.burst_spread_seconds / (n - 1)) * 1.5, RETRY_AFTER_CAP_S)
            raise ValueError(
                "retry budget too large: the worst-case two-burst schedule "
                f"(({2 * n - 2}) within-burst waits of up to {per_retry:.0f}s "
                f"+ {self.mid_pause_seconds}s mid-pause) = {worst:.0f}s must stay "
                f"under the {_CATCHUP_GRACE_SECONDS}s (90-min) catch-up grace window"
            )
        return self


class ReloadConfig(BaseModel):
    """File-watch auto-reload toggle (D-03).

    ``watch`` is ON by default: with no ``[reload]`` table an existing config
    loads unchanged and auto-reload is enabled. Set ``[reload] watch = false`` to
    disable the file watcher; the explicit reload triggers (SIGHUP /
    ``weatherbot reload``) always work regardless of this flag.

    Frozen and ``extra="forbid"`` like the other config models, so an unknown
    ``[reload]`` key fails loud at load (T-10-03) and the snapshot is immutable
    for lock-free shared reads via ``ConfigHolder``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    watch: bool = True


class BotConfig(BaseModel):
    """Inbound gateway bot config (CMD-02/D-06) — non-secret identity only.

    Carries the single Discord user ID authorized to issue commands to the bot
    (``operator_id``). This is a non-secret public identity (a Discord user ID),
    NOT a credential — the bot TOKEN is a secret and lives on ``Settings``
    (``discord_bot_token``), never here and never in ``config.toml`` (D-14).

    ``operator_id`` is a single ``int`` (NOT a list, RESEARCH Pattern 5 / A3):
    v1 is a one-operator bot. Frozen + ``extra="forbid"`` like the other config
    models, so an unknown ``[bot]`` key fails loud at load (T-11-03) and the
    snapshot is immutable for lock-free shared reads via ``ConfigHolder``.

    Optional on ``Config`` (``bot: BotConfig | None = None``): absence of the
    ``[bot]`` table MUST mean "no bot configured", so it is a plain optional with
    a ``None`` default — NOT a ``default_factory`` (which would conjure a bot
    section with no operator_id and fail confusingly).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operator_id: int


class Config(BaseModel):
    """Top-level non-secret config parsed from ``config.toml``.

    ``locations`` is a LIST even with one entry (D-06) so Phase 2 multi-location
    needs no refactor. This model carries NO secret field (CONF-02).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    locations: list[Location]
    template: str = DEFAULT_TEMPLATE
    webhook: WebhookIdentity = Field(default_factory=WebhookIdentity)
    reliability: Reliability = Field(default_factory=Reliability)
    reload: ReloadConfig = Field(default_factory=ReloadConfig)
    # Plain optional with None default (NOT default_factory): absence of the
    # [bot] table MUST mean "no bot configured" (PATTERNS.md / RESEARCH Pattern 5).
    bot: BotConfig | None = None
