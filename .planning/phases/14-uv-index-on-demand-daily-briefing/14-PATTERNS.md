# Phase 14: UV Index — On-Demand & Daily Briefing - Pattern Map

**Mapped:** 2026-06-19
**Files analyzed:** 9 (1 new module, 1 new test, 6 modified, 1+ templates)
**Analogs found:** 9 / 9 (every seam already exists in-repo — pure brownfield)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/weather/uv.py` (NEW) | utility (pure helper) | transform | `weatherbot/interactive/commands/weather_views.py` (`next_cloudy` + `_is_daytime`/`_epoch_local`) | role-match (closest hourly-scan/epoch-local/daytime-bound precedent); also `models.ForecastDay._local_hhmm` |
| `weatherbot/weather/models.py` (MOD) | model | transform | itself (`Forecast.placeholders` / `_hints` / `from_payloads`) | exact (extend existing seam) |
| `weatherbot/config/models.py` (MOD) | config | request-response | `ForecastSchedule` (frozen separate table) + `cloud_threshold` field + `_cloud_threshold_in_range` validator | exact |
| `templates/renderer.py` (MOD) | config (token allow-list) | transform | itself (`CANONICAL` set) | exact |
| `templates/briefing-*.txt` (MOD) | template | transform | `briefing-sectioned.txt` (`{hint}`/`{alert}` empty-collapse lines) | exact |
| `weatherbot/weather/client.py` (verify only) | service | request-response | itself (`fetch_onecall` — `exclude` already widened in Phase 12) | exact (NO edit; Wave-0 verify) |
| `weatherbot/interactive/registry.py` (MOD) | registry | event-driven | `_SPECS` entries + `_wire_handlers` (`next-cloudy` row) | exact |
| `weatherbot/cli.py` + `interactive/bot.py` (MOD) | controller/route | request-response | the `next-cloudy` dispatch special-case (passes `config.cloud_threshold`) | exact |
| `tests/test_uv.py` + fixtures (NEW) | test | — | `tests/test_command_views.py` / existing `onecall_*.json` fixtures | role-match |

## Pattern Assignments

### `weatherbot/weather/uv.py` (NEW — pure transform helper)

**Analog:** `weatherbot/interactive/commands/weather_views.py` (hourly-scan + epoch→local + daytime bounding), plus `ForecastDay._local_hhmm` for tz fallback.

**Imports pattern** (mirror `weather_views.py` lines 16-25 + `models.py` lines 23-28):
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
```
Keep this module dependency-free of the interactive layer (Phase 15's monitor reuses it) — do NOT import `CommandReply`/`LookupResult` here. It reads raw dicts + a threshold and returns a frozen dataclass.

**Frozen value-object pattern** (copy the `CommandReply`/`ScheduleContext` house style — `commands/__init__.py:21`, `context.py:29`):
```python
@dataclass(frozen=True)
class UvSummary:
    current: float
    max: float
    category: str
    peak_uvi: float
    peak_time: datetime | None
    crossing_time: datetime | None
    window_start: datetime | None
    window_end: datetime | None
    stays_below: bool
    hourly_points: tuple[tuple[datetime, float], ...]  # daytime (dt, uvi) for the cmd line
```

**epoch→local helper — copy VERBATIM from `weather_views.py` lines 59-61:**
```python
def _epoch_local(unix_ts: int, tz: ZoneInfo) -> datetime:
    """Convert a Unix-UTC timestamp to location-local wall-clock (DST-correct)."""
    return datetime.fromtimestamp(unix_ts, tz)
```

**Daytime/hourly-scan pattern — copy the `next_cloudy` hourly loop guard structure (`weather_views.py` lines 195-203) and `_is_daytime` sunrise/sunset bounding (lines 64-85).** Critical reuse points:
- Defensive `raw.get("hourly") or []`, skip any bucket where `dt`/`uvi` is `None` (mirror the `clouds is None or dt_ts is None` guard at line 200 — WR-01 "never subscript a key only assumed present").
- Sunrise/sunset from `daily[]` matched by local date, with the fixed-window fallback (`6 <= dt.hour < 20`) when sun data is absent — `weather_views.py` lines 75-85. (Pitfall 5: `None` sunrise must not crash.)
- "today" = location-local date from the CONFIGURED `Location.timezone` (NOT the API `timezone` field) — Pitfall 3, established by `models._local_date_iso` (lines 47-62).

**Interpolation (NEW math, no analog — from RESEARCH Code Examples lines 250-272):**
```python
def _first_up_cross(points, threshold):
    for (t0, u0), (t1, u1) in zip(points, points[1:]):
        if u0 < threshold <= u1:
            frac = (threshold - u0) / (u1 - u0)
            return t0 + (t1 - t0) * frac
    if points and points[0][1] >= threshold:
        return points[0][0]
    return None
```

**WHO category — small ordered table (RESEARCH lines 265-272), NOT inline if-chain. Round-then-band (A2).**

> **Read UV from `onecall_imp` only** (A1 — UV index is unitless); accept `onecall_met` for signature parity and ignore it. Use `current.uvi` for `{uv_now}`, `daily[0].uvi` for `{uv_max}`, `hourly[]` ONLY for crossing/window/peak (Pitfall 6).

---

### `weatherbot/weather/models.py` (MOD — extend the placeholder seam)

**Analog:** itself. Three concrete edits.

**1. Replace the hardcoded `>= 6` (lines 65-91, `_hints`).** Currently:
```python
def _hints(rain_chance, feels_imp, wind_imp, uvi_max) -> str:
    ...
    if uvi_max >= 6:
        lines.append("Wear sunscreen \U0001F9F4")
```
Thread the configured threshold in (Pitfall 4 / D-01 "unify three consumers"). Add a `uv_threshold: float = 6.0` param defaulted to `6.0` so existing test call sites stay green, change the literal to `uvi_max >= uv_threshold`, and update `from_payloads` (lines 155-232) to accept + forward `uv_threshold` (e.g. `from_payloads(loc, imp, met, *, uv_threshold=...)`). Then update the live call site `lookup_weather` (`interactive/lookup.py:121`) to pass `config.uv.threshold`.

**2. Add UV placeholder fields + emit them in `placeholders()`** (lines 274-289). The existing map is the template. New tokens MUST be added here AND to `renderer.CANONICAL` in lockstep (Pitfall 3). Follow the empty-collapse precedent of `{hint}`/`{alert}` — a non-applicable UV field renders `""`, never `None`:
```python
def placeholders(self) -> dict[str, str]:
    return {
        ...
        "hint": self.hint,
        "alert": self.alert,
        # NEW UV tokens (must mirror renderer.CANONICAL exactly):
        "uv_now": ...,
        "uv_max": ...,
        "uv_cross": ...,    # "" when stays_below
        "uv_window": ...,
        "uv_peak": ...,
        "uv_category": ...,
    }
```
Display-string formatting (category word, "~9:40", window range, "stays below threshold today") is computed in CODE here — never in the template (anti-pattern: logic in templates). Call `compute_uv` from `from_payloads` (it has `raw_onecall_imp` + the location tz + the threshold) and stash the formatted strings as fields, mirroring how `hint`/`alert` are computed once in `from_payloads` and stored.

**3. Time formatting** — reuse the `_local_hhmm` idiom (`ForecastDay._local_hhmm`, lines 426-437) for crossing/peak/window clock strings, or the `scheduler/context._TIME_FMT = "%-I:%M %p"` "7:30 AM" idiom (Don't-Hand-Roll table). Pick one and stay consistent.

---

### `weatherbot/config/models.py` (MOD — new frozen `[uv]` table)

**Analog:** `ForecastSchedule` (separate frozen model, lines 88-110) + the `cloud_threshold` field & validator on `Config` (lines 398-410).

**New model** (mirror `WebhookIdentity`/`Reliability` shape — frozen, `extra="forbid"`, defaulted fields, range validator):
```python
class UvConfig(BaseModel):
    """Global UV threshold + pre-warn lead (D-01/UV-03)."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold: float = 6.0           # A5: 6.0 preserves the hardcoded hint behavior
    pre_warn_lead_minutes: int = 30  # A4 / Open Q1 — Phase 14 stores+validates only

    @field_validator("threshold")
    @classmethod
    def _threshold_in_range(cls, v: float) -> float:
        if not 0 <= v <= 20:   # WHO UVI realistic range; pick bound, fail loud
            raise ValueError(f"uv.threshold must be 0..20, got {v!r}")
        return v
```

**Field on `Config`** — copy the `cloud_threshold` precedent EXACTLY (lines 398-403): a DECLARED field with a `default_factory` keeps keyless existing configs loading under `extra="forbid"`, and the whole-`Config` reload picks up edits with no reload-wiring change:
```python
class Config(BaseModel):
    ...
    cloud_threshold: int = 60
    uv: UvConfig = Field(default_factory=UvConfig)
```
Use `default_factory=UvConfig` (like `webhook`/`reliability`/`reload`), NOT `| None = None` — the `[uv]` table absence MUST mean "defaults", not "no UV".

---

### `templates/renderer.py` (MOD — extend `CANONICAL`)

**Analog:** the `CANONICAL` set itself (lines 36-55).

**Pattern** — add the SAME UV token names emitted by `placeholders()` (Pitfall 3 lockstep). `validate_template` (lines 128-142) and `render` (lines 145-157) need ZERO logic change — adding to the allow-list is backward-compatible (existing templates that don't reference the tokens still validate):
```python
CANONICAL = {
    "temp", "feels_like", "high", "low", "rain", "wind", "humidity",
    "conditions", "location", "date", "hint", "alert",
    "sent_at", "checked_at", "schedule_note",
    # NEW (mirror Forecast.placeholders()):
    "uv_now", "uv_max", "uv_cross", "uv_window", "uv_peak", "uv_category",
}
```
Do NOT touch `FORECAST_TOKENS`/`FORECAST_DAY_TOKENS_*` — UV briefing tokens are daily-briefing scope only (the `uv` command builds its hourly line in CODE, not via a template).

---

### `templates/briefing-*.txt` (MOD — add the UV line(s))

**Analog:** `briefing-sectioned.txt` `{hint}`/`{alert}` lines (lines 9-10) — a bare token on its own line that collapses to empty when the value is `""`.

**Pattern** — add a UV line of bare tokens (D-04: summary fields only, no hourly line in the briefing), e.g.:
```
☀️ UV: {uv_now} now, max {uv_max} ({uv_category})
{uv_window}
```
Apply to all three briefing variants (`briefing-sectioned.txt`, `briefing-compact.txt`, `briefing-multiline.txt`). The collapse-to-empty behavior is already handled by code emitting `""` (renderer leaves no stray `None`).

---

### `weatherbot/weather/client.py` (VERIFY ONLY — no edit)

**Analog:** itself. `fetch_onecall` (lines 42-68) ALREADY sets `"exclude": "minutely"` (Phase 12 D-06 widened it; docstring lines 44-50 explicitly name Phases 14/15). Phase 14 does NOT re-edit this.

**Wave-0 verification task (CONTEXT D-05):** add/keep a test asserting `client.fetch_onecall` returns a non-empty `hourly[]` carrying `uvi` (the regression canary the docstring references at line 50). Fail loud here rather than shipping a UV helper that silently returns "stays below" for everything.

---

### `weatherbot/interactive/registry.py` (MOD — register `uv`)

**Analog:** the `next-cloudy` row in `_SPECS` (lines 54-59) + its `_wire_handlers` entry (line 101).

**Two edits, mirror `next-cloudy` exactly:**
```python
# in _SPECS:
CommandSpec("uv", "Weather", "Current + max UV and sunscreen window for a location.", True),
# in _wire_handlers() handlers dict (lazy import of the handler module):
"uv": weather_views.uv,   # or a new commands/uv_view.py — planner decides
```
`takes_location=True` is the only flag that matters — the CLI subparser loop (`cli.py:815`) auto-derives the `uv <loc>` subparser, and `render_help` auto-lists it (the derive-from-one-list invariant). No parser edit needed.

---

### `weatherbot/cli.py` + `weatherbot/interactive/bot.py` (MOD — dispatch special-case)

**Analog:** the `next-cloudy` dispatch branch that threads the global config knob into the handler — `cli.py:621-622` and `bot.py:315-316`:
```python
elif spec.name == "next-cloudy":
    reply = spec.handler(result, config.cloud_threshold)
```
**Pattern** — add a sibling branch passing `config.uv.threshold` to the `uv` handler in BOTH dispatch sites (CLI one-shot + Discord on_message). The `uv` handler signature should match: `def uv(result: LookupResult, threshold: float) -> CommandReply`. It reads `result.forecast.raw_onecall_imp`, calls `compute_uv`, and builds the summary lines + the compact daytime hourly line (D-04) as a `CommandReply` (mirror `next_cloudy`'s `CommandReply(title=..., lines=tuple(...))` shape, `weather_views.py:204-210`).

---

### `tests/test_uv.py` + fixtures (NEW)

**Analog:** `tests/test_command_views.py` (handler tests against `onecall_*.json` fixtures); existing `tests/fixtures/onecall_*.json`.

**Fixtures (the critical Wave-0 deliverable):** add `hourly[]` (each `{dt, uvi, ...}`) to a "UV crosses 6 mid-morning" fixture, a "stays below all day" fixture, and to `onecall_imperial_highuv.json` — the existing 8 fixtures lack `hourly`.

**Test cases (RESEARCH Wave-0 + Pattern 2 edge cases):** up-cross, down-cross/window-end, already-above-at-sunrise, never-crosses → `stays_below`, multi-peak (first up-cross wins), missing-sunrise fallback, category boundaries (5.6→"High"), and the lockstep assertions `UV_TOKENS <= set(Forecast(...).placeholders())` and `UV_TOKENS <= renderer.CANONICAL` (Pitfall 3).

## Shared Patterns

### Defensive payload access (`.get(...) or {}` / `or []`)
**Source:** `weatherbot/weather/models.py` lines 180-194; `weather_views.py` lines 100-103, 195-203.
**Apply to:** `uv.py` (all `raw.get("hourly")`/`daily[0]`/`current` reads), the `uv` handler.
```python
cur = raw.get("current") or {}
day0 = (raw.get("daily") or [{}])[0] or {}
for h in raw.get("hourly") or []:
    if h.get("dt") is None or h.get("uvi") is None:
        continue
```

### Location-local date/time from the CONFIGURED tz (Pitfall 3)
**Source:** `weatherbot/weather/models.py` `_local_date_iso` lines 47-62; `weather_views._epoch_local`/`_is_daytime` lines 59-85.
**Apply to:** all UV time math — `compute_uv` takes `tz: ZoneInfo` from `ZoneInfo(location.timezone)`, NOT the API `timezone` field.

### Frozen `extra="forbid"` config table, declared-with-default field on `Config`
**Source:** `config/models.py` — `ForecastSchedule` (88-110), `cloud_threshold` field+validator (398-410), `Field(default_factory=...)` usage (392-394).
**Apply to:** the new `UvConfig` + its `Config.uv` field. Free hot-reload (whole-`Config` re-read).

### Empty-collapse placeholder line
**Source:** `briefing-sectioned.txt` lines 9-12 (`{hint}`/`{alert}`/`{schedule_note}`); precedent documented `models.py` lines 14, 140.
**Apply to:** the new UV briefing tokens — emit `""` for non-applicable fields in `placeholders()`.

### `CANONICAL` ↔ `placeholders()` lockstep (fail-loud token gate)
**Source:** `renderer.py` lines 33-55, 128-142; `models.placeholders()` lines 274-289.
**Apply to:** every UV token added to BOTH sets simultaneously, asserted by a test.

### Registry-derived command surface (one list → CLI + Discord + help)
**Source:** `registry.py` `_SPECS`/`_wire_handlers` (50-112); dispatch special-case `cli.py:621`, `bot.py:315`.
**Apply to:** the `uv` command registration + the `config.uv.threshold` dispatch branch in both surfaces.

## No Analog Found

| File / Concern | Role | Data Flow | Reason |
|----------------|------|-----------|--------|
| Linear interpolation of the threshold crossing (`_first_up_cross`/window-end math) | utility | transform | No existing interpolation in-repo — `next_cloudy` does whole-bucket scans, not sub-hour interpolation. Use RESEARCH Code Examples (lines 250-260) as the template. This is the ONLY genuinely new logic. |

The interpolation math has no codebase analog; everything else extends an existing seam verbatim.

## Metadata

**Analog search scope:** `weatherbot/weather/`, `weatherbot/config/`, `weatherbot/interactive/` (+ `commands/`), `templates/`, `tests/`
**Files scanned:** models.py, client.py, renderer.py, weather_views.py, registry.py, config/models.py, lookup.py, forecast.py, scheduler/context.py, commands/__init__.py, cli.py (dispatch + subparser regions), bot.py (dispatch region), briefing-sectioned.txt
**Pattern extraction date:** 2026-06-19
**Project skills:** none found (no `.claude/skills/` or `.agents/skills/`)
