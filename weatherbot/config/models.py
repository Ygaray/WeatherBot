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

# A scheduled forecast slot is one of two base day-blocks (multiday.select_days
# resolves "weekday" -> mon-fri and "weekend" -> the fri-sat-sun window).
_VALID_FORECAST_KINDS = {"weekday", "weekend"}
# The two forecast render densities (Plan 13-02 templates).
_VALID_FORECAST_VARIANTS = {"detailed", "compact"}

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
            # F74: the raw ``time`` string is used verbatim as a job-id / sent-log
            # key, so it must be strictly canonical ``[0-9][0-9]:[0-9][0-9]``.
            # ``int()`` alone accepts non-canonical oddities that are still 2 chars
            # long (``"+9"``, ``" 9"``, ``"-1"``), which would pass a bare len==2
            # check and produce a non-canonical key. Require all-digit components
            # so only canonical two-digit strings survive to the range check.
            if not (hh.isdigit() and mm.isdigit()):
                raise ValueError
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


class ForecastSchedule(BaseModel):
    """One scheduled multi-day forecast slot for a location (FCAST-06).

    A SEPARATE model from :class:`Schedule` (NOT an extension): a forecast job's
    id is namespaced apart from a briefing job's id, so a forecast and a briefing
    at the same ``time``/``days`` never collide and a ``kind``/``variant`` never
    pollutes the briefing slot (RESEARCH Alternatives Considered, Plan 13-05).

    ``kind`` selects the base day-block (``weekday`` -> Mon-Fri, ``weekend`` ->
    the Fri-Sat-Sun window); ``variant`` selects the render density
    (``detailed``/``compact``, default detailed). ``time``/``days`` reuse the
    :class:`Schedule` HH:MM + ``parse_days`` validators VERBATIM (one source of
    truth), and ``parsed_time()``/``day_of_week`` behave identically so the
    forecast trigger and the briefing trigger share the same accessors.
    ``enabled`` defaults true and may be set false to pause a slot WITHOUT
    deleting it (toggle-without-delete, mirrors ``Schedule``).

    Frozen + ``extra="forbid"`` like every config model: a malformed
    ``kind``/``variant``/``time``/``days`` or an unknown key fails loud at load
    (T-13-08/T-13-09) and the immutable snapshot stays ``ConfigHolder``-compatible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    variant: str = "detailed"
    time: str
    days: str
    enabled: bool = True

    @field_validator("time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        # Reuse the Schedule HH:MM contract verbatim (one source of truth) —
        # including the F74 all-digit canonicalization, so a forecast job-id key
        # can never be a non-canonical int-parseable oddity either.
        try:
            hh, mm = v.split(":")
            if not (hh.isdigit() and mm.isdigit()):
                raise ValueError
            h, m = int(hh), int(mm)
            if not (len(hh) == 2 and len(mm) == 2 and 0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except Exception as e:
            raise ValueError(f"time must be 'HH:MM' 24-hour, got {v!r}") from e
        return v

    @field_validator("days")
    @classmethod
    def _days_valid(cls, v: str) -> str:
        # Reuse parse_days (presets + comma list); keep RAW, normalize at use.
        parse_days(v)
        return v

    @field_validator("kind")
    @classmethod
    def _kind_valid(cls, v: str) -> str:
        if v not in _VALID_FORECAST_KINDS:
            raise ValueError(
                f"kind must be one of {sorted(_VALID_FORECAST_KINDS)}, got {v!r}"
            )
        return v

    @field_validator("variant")
    @classmethod
    def _variant_valid(cls, v: str) -> str:
        if v not in _VALID_FORECAST_VARIANTS:
            raise ValueError(
                f"variant must be one of {sorted(_VALID_FORECAST_VARIANTS)}, got {v!r}"
            )
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
    # Scheduled multi-day forecast slots (FCAST-06). default_factory=list so an
    # absent [[locations.forecast]] table loads as [] (zero migration); kept
    # separate from ``schedule`` so forecast/briefing job ids never collide.
    forecast: list[ForecastSchedule] = Field(default_factory=list)

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

    @field_validator("name", "id")
    @classmethod
    def _no_pipe_in_identity(cls, v: str | None) -> str | None:
        # WR-04: ``name`` (and an explicit ``id``) are interpolated RAW into the
        # ``|``-delimited APScheduler job ids (briefing ``name|time|days`` and
        # forecast ``name|fc|kind|variant|time|days``). A ``|`` in the name could
        # craft a forecast id that collides with a briefing id (or another slot),
        # and ``replace_existing=True`` would then SILENTLY overwrite one job,
        # dropping a scheduled send. Forbid ``|`` fail-loud at load (matches the
        # existing fail-loud-at-load posture) so the delimiter stays collision-safe.
        if v is not None and "|" in v:
            raise ValueError(
                f"location name/id must not contain '|' (it is the job-id "
                f"delimiter), got {v!r}"
            )
        return v

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
            per_retry = max(
                (self.burst_spread_seconds / (n - 1)) * 1.5, RETRY_AFTER_CAP_S
            )
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
    section with no operator_id and fail confusingly). When the ``[bot]`` table
    IS present it now requires BOTH keys (``operator_id`` and ``panel_channel_id``).

    ``panel_channel_id`` (D-04) is the channel the persistent control panel is
    summoned/pinned into and re-found by scanning pins after a restart (PANEL-09).
    Like ``operator_id`` it is a non-secret Discord channel ID — it belongs in
    ``config.toml`` ``[bot]``, NOT ``.env``. Both ``[bot]`` keys are read ONCE at
    startup (the project's accepted restart-boundary tech debt): changing
    ``panel_channel_id`` requires a process restart, not a config hot-reload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operator_id: int
    panel_channel_id: int


class UvConfig(BaseModel):
    """Global UV threshold + pre-warn lead (D-01 / UV-03).

    A single GLOBAL UV threshold (no per-location override, D-01) that unifies
    three consumers: the existing "Wear sunscreen" hint (now reads this instead
    of the hardcoded literal ``6``), the new daily-briefing UV line, and the
    Phase-15 intraday monitor. ``threshold`` defaults to ``6.0`` — the exact
    value the hardcoded ``uvi_max >= 6`` hint used, so an existing config with no
    ``[uv]`` table behaves IDENTICALLY (A5, zero migration).

    ``pre_warn_lead_minutes`` is STORED + VALIDATED here in Phase 14 but has no
    behavior yet — Phase 15's monitor gives it meaning (Open Q1 / A4). Defaults
    to 30 minutes.

    Frozen + ``extra="forbid"`` like every config model: an out-of-range
    ``threshold``, a negative lead, or an unknown ``[uv]`` key fails loud at load
    (T-14-01) and the immutable snapshot stays ``ConfigHolder``-compatible. The
    field on ``Config`` uses ``default_factory=UvConfig`` (NOT ``| None``) so an
    absent ``[uv]`` table means "defaults", never "no UV" (D-01).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold: float = 6.0  # A5: 6.0 preserves the hardcoded sunscreen-hint behavior.
    pre_warn_lead_minutes: int = 30  # A4 / Open Q1 — Phase 14 stores+validates only.

    # --- Phase-15 monitor-only knobs (UV-04) -------------------------------
    # These extend the SAME [uv] table (one table, not two — DP-3); an absent or
    # partial [uv] table still loads with these defaults.
    # run_daemon registration gate, default on. LIVE via reload (WR-03): the
    # ``__uvmonitor__`` job stays registered across a reload, and the per-tick
    # holder read short-circuits the tick body when this flips to false — so
    # disabling the monitor via a reload stops the polling immediately (no
    # restart needed). Enabling from a startup-disabled state still requires a
    # restart, since no job is registered when it is false at startup.
    monitor_enabled: bool = True
    # 15-min default (UV-04). RESTART-DEFERRED (DP-2): the interval is baked into
    # the IntervalTrigger at job registration, NOT live-reloaded — changing it
    # requires a process restart, exactly like ``[reload] watch``. The other UV
    # knobs (threshold/lead/margin) ARE live via the per-tick holder read, and
    # ``monitor_enabled`` is honored live via the in-tick gate (WR-03).
    interval_seconds: int = 900
    value_margin: float = 1.0  # D-03 value-proximity ("within ~1 of threshold").

    @field_validator("threshold")
    @classmethod
    def _threshold_in_range(cls, v: float) -> float:
        # WHO UVI realistic range is 0..~12; allow up to 20 as a generous ceiling
        # and fail loud outside it (mirrors _cloud_threshold_in_range's style).
        if not 0 <= v <= 20:
            raise ValueError(f"uv.threshold must be between 0 and 20, got {v!r}")
        return v

    @field_validator("pre_warn_lead_minutes")
    @classmethod
    def _lead_in_range(cls, v: int) -> int:
        # WR-04: fail loud at BOTH ends (the file's posture — Reliability bounds an
        # upper budget, threshold is 0..20). A pre-warn lead beyond a daytime span
        # is meaningless for an intraday UV monitor (it would "warn at a time that
        # never comes" or "always warn"), so cap it at 720 min (12h) rather than
        # silently accept e.g. 100000 (~69 days).
        if not 0 <= v <= 720:
            raise ValueError(
                f"uv.pre_warn_lead_minutes must be between 0 and 720, got {v!r}"
            )
        return v

    @field_validator("interval_seconds")
    @classmethod
    def _interval_in_range(cls, v: int) -> int:
        # T-15-02 (DoS): floor at 60s so a config typo cannot drive a sub-minute
        # poll loop against the OpenWeather API; ceiling at 86400 (1 day) so the
        # monitor can still fire at least once per daylight span. Fail loud at
        # both ends, naming the field + got-value (mirrors _threshold_in_range).
        if not 60 <= v <= 86400:
            raise ValueError(
                f"uv.interval_seconds must be between 60 and 86400, got {v!r}"
            )
        return v

    @field_validator("value_margin")
    @classmethod
    def _value_margin_in_range(cls, v: float) -> float:
        # D-03 value-proximity margin: bound 0..20 like ``threshold`` (the UVI
        # scale), failing loud outside it. A negative or absurdly large margin is
        # meaningless for "within N of threshold".
        if not 0 <= v <= 20:
            raise ValueError(f"uv.value_margin must be between 0 and 20, got {v!r}")
        return v


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
    # Global cloud-cover threshold for `next-cloudy` (CMD-15, D-03): a single
    # top-level knob, default 60%, editable via the existing reload path (the
    # reload re-reads the whole Config, so no reload wiring change is needed). A
    # DECLARED field with a default keeps existing keyless configs loading under
    # extra="forbid" (Pitfall 6); the validator fails loud on out-of-range values.
    cloud_threshold: int = 60

    # Global UV config (UV-03, D-01): a frozen [uv] table with threshold +
    # pre_warn_lead_minutes. default_factory=UvConfig (NOT | None) so an absent
    # [uv] table means "defaults" (threshold 6.0), matching the
    # webhook/reliability/reload precedent and keeping existing keyless configs
    # loading under extra="forbid". The whole-Config reload picks up edits with
    # no reload-wiring change.
    uv: UvConfig = Field(default_factory=UvConfig)

    @field_validator("cloud_threshold")
    @classmethod
    def _cloud_threshold_in_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError(f"cloud_threshold must be between 0 and 100, got {v!r}")
        return v
