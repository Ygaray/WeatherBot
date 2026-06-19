# Phase 14: UV Index — On-Demand & Daily Briefing - Research

**Researched:** 2026-06-18
**Domain:** Brownfield Python — derived-field computation over One Call 3.0 `hourly[]`/`daily[0]`, renderer token extension, config model extension
**Confidence:** HIGH

## Summary

This is an almost entirely **brownfield** phase: every seam it touches already exists and is well-documented in-code. The work is (1) a new pure UV-computation helper that reads the two already-fetched One Call payloads and emits current/max/peak-time/interpolated-crossing/protect-window/category, (2) wiring those values into the renderer's `CANONICAL` token set + the editable templates, (3) a global `[uv]` config table (frozen) carrying `threshold` (default 6) and `pre_warn_lead`, (4) replacing the hardcoded `uvi_max >= 6` sunscreen hint with the configured threshold, and (5) registering a `uv <loc>` command on the Phase 12 registry that reuses the read-only `lookup_weather` core.

**There is exactly one hard blocker that the planner MUST address as task #1:** the One Call client at `weatherbot/weather/client.py:58` currently sends `"exclude": "minutely,hourly"`, so **the `hourly[]` array — the only source of intra-day UV points needed for crossing-time/protect-window/peak-time interpolation — is NOT fetched today, and none of the test fixtures contain it.** Every UV summary field beyond `current.uvi` and `daily[0].uvi` depends on this data. Stop excluding `hourly` (change to `"exclude": "minutely"`), and add `hourly[]` to the test fixtures, before any interpolation logic can be written or tested.

**Primary recommendation:** Build one pure helper `compute_uv(onecall_imp, onecall_met, threshold, *, now=None) -> UvSummary` (a frozen dataclass) in a new module (e.g. `weatherbot/weather/uv.py`). It takes raw payloads + the configured threshold and returns every UV field. The `Forecast` model calls it to populate UV placeholder fields; the `uv` command calls it for the summary + builds the extra hourly line from `hourly[]`; **Phase 15's monitor calls the exact same helper** with the same threshold. Get this one interface right and the phase + Phase 15 fall out cleanly.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fetch One Call payload incl. `hourly[]` | API client (`weather/client.py`) | — | Single fetch point; `hourly` must stop being excluded |
| UV computation (current/max/peak/cross/window/category) | Pure helper (`weather/uv.py`) | — | Stateless, payload-in → values-out; reused by briefing, `uv` cmd, Phase 15 monitor |
| UV summary → placeholder strings | `weather/models.py` (`Forecast`) | — | Mirrors existing `placeholders()` "code computes, template displays" seam |
| UV token validation | `templates/renderer.py` (`CANONICAL`) | config loader | Fail-loud unknown-token gate already wired into load + reload |
| Threshold/lead config | `config/models.py` (`UvConfig`) | `config/loader.py` | Frozen validated field on `Config`, hot-reloaded via `ConfigHolder` |
| `uv <loc>` command | Phase 12 registry + `interactive/lookup.py` | `cli.py` / `interactive/bot.py` | Read-only core, guard ladder, off-loop fetch all reused |
| Daytime window bounding | `weather/uv.py` (from `daily[0].sunrise`/`sunset`) | — | Shared concept with Phase 12 `next-cloudy`; keep derivation reusable |

## Standard Stack

No new third-party dependencies. Everything needed is already in the project or the stdlib.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| (stdlib) `datetime` + `zoneinfo` | built-in 3.11+ | epoch→location-local time for crossing/peak/window | Already the project's tz idiom (`models.py`, `scheduler/context.py`) `[VERIFIED: codebase]` |
| pydantic | 2.13.x | `UvConfig` model, frozen + `extra="forbid"` | Every other config table uses this exact pattern `[VERIFIED: codebase config/models.py]` |
| (project) `templates/renderer.py` | n/a | token validation + substitution | Extend `CANONICAL`, no logic change `[VERIFIED: codebase]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (project) `interactive/lookup.py` | n/a | read-only resolve+fetch+render | `uv` command rides `lookup_weather`/`ForecastCache` |
| (stdlib) `tomllib` | built-in 3.11+ | read `[uv]` table | Loader already uses it `[VERIFIED: codebase]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Linear interpolation between hourly `uvi` | Spline / cubic fit | Overkill; hourly UV is smooth and "~minute" precision (D-03) does not justify it. Linear is the locked decision. |
| New `weather/uv.py` module | Methods on `Forecast` | A standalone pure helper is reusable by Phase 15's monitor without instantiating a full `Forecast`; keeps `models.py` lean. **Recommended: standalone module.** |

**Installation:** None — zero new packages. (No Package Legitimacy Audit needed; no external installs.)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UV-01 | `uv <loc>` current + max UV (CLI + Discord) | Phase 12 registry + `lookup_weather`; `compute_uv` supplies current/max; command adds compact hourly line from `hourly[]` (D-04) |
| UV-02 | Briefing: current UV + today's max + threshold-crossing time (or "stays below") | New placeholder tokens fed by `compute_uv`; rendered into `briefing-*.txt`; summary fields only (D-04) |
| UV-03 | Configurable threshold + pre-warn lead in config, no code change | `UvConfig` frozen table on `Config`, hot-reloaded; threshold unifies hint + briefing + Phase 15 monitor (D-01) |

## Architecture Patterns

### System Architecture Diagram

```
config.toml [uv] table ──load/validate──> UvConfig(threshold, pre_warn_lead)
        │ (hot-reloaded via ConfigHolder)
        ▼
  One Call client.fetch_onecall  ── MUST now include hourly[] ──┐
   (imperial + metric payloads)                                 │
        │                                                       │
        ▼                                                       ▼
  compute_uv(imp, met, threshold, now) ───────────────> UvSummary (frozen)
        │   reads: current.uvi, daily[0].uvi,              · current, max, category
        │          hourly[].{dt,uvi}, daily[0].sunrise/    · peak_time, peak_uvi
        │          sunset                                  · crossing_time | None
        │   linear-interpolates crossings, bounds          · window_start/end | None
        │   protect window by daytime                      · stays_below: bool
        │                                                       │
        ├───────────────┬───────────────────────────────┬──────┘
        ▼               ▼                                ▼
  Forecast        uv <loc> command                Phase 15 monitor
  .placeholders() (summary + hourly line,         (SAME helper, SAME
  → {uv_now} ...  D-04)  via lookup_weather        threshold; this phase
        │         + Phase 12 registry              writes no loop)
        ▼
  renderer.render (CANONICAL gate)
        ▼
  briefing-*.txt  +  inbound Discord embed
```

File-to-implementation mapping is in the Component Responsibilities below, NOT the diagram.

### Recommended Project Structure
```
weatherbot/weather/
├── uv.py            # NEW: compute_uv() + UvSummary dataclass (pure, reusable)
├── models.py        # Forecast gains UV placeholder fields; _hints reads config threshold
└── client.py        # STOP excluding hourly[]
weatherbot/config/
└── models.py        # NEW UvConfig table on Config
templates/
├── renderer.py      # CANONICAL += UV tokens
└── briefing-*.txt   # add UV line(s)
weatherbot/interactive/
└── lookup.py / (Phase 12 registry)  # uv command handler
```

### Pattern 1: Pure payload→value helper (the reuse seam)
**What:** A stateless function taking raw dicts + threshold, returning a frozen value object. No I/O, no config import beyond the passed-in threshold/lead.
**When to use:** Anything Phase 15 must also call. The monitor cannot depend on `Forecast`/render machinery, so the computation must live below it.
**Example:**
```python
# weatherbot/weather/uv.py  [ASSUMED — illustrative shape, not copied from an existing file]
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class UvSummary:
    current: float
    max: float
    category: str            # WHO band word for `max`
    peak_uvi: float
    peak_time: datetime | None
    crossing_time: datetime | None   # first up-cross of threshold (interpolated)
    window_start: datetime | None    # = crossing_time, daytime-bounded
    window_end: datetime | None      # down-cross back below threshold
    stays_below: bool
    hourly_points: list[tuple[datetime, float]]  # daytime (dt, uvi) for the cmd line

def compute_uv(onecall_imp, onecall_met, threshold, *, tz: ZoneInfo,
               now: datetime | None = None) -> UvSummary:
    ...
```
Both payloads are passed in (matching `Forecast.from_payloads`) so the helper can stay unit-agnostic — but note: **UV index is unitless and identical in both payloads**, so `compute_uv` really only needs one payload for the numbers. Pass both for signature symmetry/future-proofing, or document that only `imp` is read. **Recommend: read from `onecall_imp` only and document why; accept `onecall_met` for signature parity but ignore it** (avoids a "which one?" bug). This is a planner decision (D — Claude's discretion area).

### Pattern 2: Linear interpolation of the threshold crossing
**What:** Walk consecutive `hourly[]` points `(t0, u0) → (t1, u1)`. A crossing exists between them when `u0 < threshold <= u1` (up-cross) or `u0 >= threshold > u1` (down-cross). The crossing instant is `t0 + (t1 - t0) * (threshold - u0) / (u1 - u0)`.
**When to use:** crossing_time (first up-cross), window_end (first down-cross after the up-cross).
**Edge cases the planner MUST enumerate as tests:**
- UV already ≥ threshold at the first daytime point → crossing_time = window_start = daytime start (sunrise), no interpolation.
- UV never reaches threshold across today's daytime points → `stays_below=True`, crossing/window/peak-window fields `None`, render the "stays below threshold today" line (D-02).
- UV crosses up but the down-cross is beyond the 48h `hourly[]` horizon (rare for UV; sun sets first) → bound `window_end` by sunset.
- Two daily peaks / multiple crossings → spec is "FIRST crosses above" (UV-02 / D-02); take the first up-cross, first subsequent down-cross.

### Pattern 3: Daytime-window bounding
**What:** Restrict the hourly scan to `[sunrise, sunset]` from `daily[0]` (epoch seconds → location-local via the configured tz, the `_local_date_iso` idiom). UV is ~0 overnight; bounding avoids spurious "crossing at 02:00" artifacts and matches the `next-cloudy` "daytime only" decision (Phase 12 D-03).
**Important:** "today" must be the **location-local** day from the CONFIGURED IANA tz (`Location.timezone`), NOT the API `timezone` field — this is the project's load-bearing Pitfall 3 (`models.py:34`). Select the hourly points whose local date == location-local today, AND within `[sunrise, sunset]`.

### Pattern 4: WHO category word from the numeric UV
**What:** Map a UV value to the standard WHO band. Locked bands (CONTEXT + EPA/WHO): **0–2 Low, 3–5 Moderate, 6–7 High, 8–10 Very High, 11+ Extreme.** `[VERIFIED: epa.gov UV Index Scale + who.int]`
**Boundaries (the gotcha):** WHO bands are on **rounded-to-integer** UV index values. UV `5.6` displays as `6` and is "High". Decide explicitly whether to round before banding (recommended — matches how people read UV) and apply consistently to `max` for the category word. Document the chosen rule.
**Implementation:** a small ordered threshold table, not a chain of ifs hardcoded inline. `category(uvi: float) -> str`.

### Pattern 5: Extend `CANONICAL` with new tokens (fail-loud preserved)
**What:** Add the UV token names to `templates/renderer.CANONICAL` AND emit them from `Forecast.placeholders()`. The two must stay in lockstep — `CANONICAL` is "exactly the keys `placeholders()` emits" (renderer.py:33). Suggested tokens (D — discretion): `{uv_now}`, `{uv_max}`, `{uv_cross}`, `{uv_window}`, `{uv_peak}`, `{uv_category}`.
**Why it's safe for existing templates:** adding tokens to the allow-list is backward-compatible — existing templates that don't reference them still validate. `validate_template` only rejects tokens NOT in the set. **But** every placeholder you add to `CANONICAL` MUST be present in `placeholders()` or a template using it will substitute… nothing is wrong actually — `render` leaves a token whose key is absent from `values` VISIBLE. So a token in `CANONICAL` but missing from `values` passes validation yet renders as a literal `{uv_now}`. **Therefore: add tokens to BOTH `CANONICAL` and `placeholders()` together** (verified by a test asserting `set(placeholders().keys()) ⊇ uv_tokens`).
**Empty-collapse precedent:** like `{hint}`/`{alert}`/`{schedule_note}`, a UV field that doesn't apply (e.g. crossing when `stays_below`) should render as a clear single line or empty string, never a stray `None`.

### Anti-Patterns to Avoid
- **Refetching for UV:** all UV data is in the already-fetched payloads (UV-04 success criterion: no extra API call). The ONLY change is to stop *excluding* `hourly` — same single fetch.
- **Logic in templates:** UV display strings (category word, window range, "stays below" line) are computed in code → placeholder tokens. The project's "no logic in templates" rule (CONTEXT code_context). Don't push banding/formatting into `.txt`.
- **Per-location threshold:** explicitly deferred (D-01); single GLOBAL threshold. Don't add a `Location.uv_threshold`.
- **Banding the unrounded value inconsistently:** pick round-then-band once.
- **Computing "today" from `daily[0].sunrise` epoch in UTC:** convert to the configured location tz first (Pitfall 3).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| epoch → local wall-clock | manual offset math from `timezone_offset` | `datetime.fromtimestamp(dt, tz=timezone.utc).astimezone(ZoneInfo(loc.timezone))` | DST-correct, matches existing `_local_date_iso` idiom; the API `timezone_offset` is a Pitfall-3 trap |
| token validation | a second regex/checker | existing `validate_template` + `CANONICAL` | Already wired into load + reload + `--check-config` |
| config hot-reload | bespoke reload of the threshold | `ConfigHolder` + frozen `UvConfig` | The threshold is "just another validated field" (CONTEXT) — reload is free |
| time formatting | new format string | `scheduler/context._TIME_FMT` (`"%-I:%M %p"`) idiom | Consistent "7:30 AM" rendering already used for `sent_at` |

**Key insight:** This phase adds **zero** new infrastructure. Every cross-cutting concern (config validation, hot-reload, token validation, read-only lookup, guard ladder, off-loop fetch, embed reply) already exists and is reused verbatim. The only genuinely new code is the pure `compute_uv` math and its tests.

## Common Pitfalls

### Pitfall 1: `hourly[]` is excluded from the fetch (THE blocker)
**What goes wrong:** Every interpolation-based field (crossing_time, window, peak_time) silently has no data — `onecall["hourly"]` is absent. Tests pass against fixtures that also lack `hourly`, so the gap hides until live UAT.
**Why it happens:** `client.py:58` sets `"exclude": "minutely,hourly"` — a deliberate v1 bandwidth trim (the docstring says "trims the unused minutely/hourly blocks"). UV makes `hourly` no longer unused.
**How to avoid:** Change to `"exclude": "minutely"`. Add a `hourly[]` array (48 points, each `{dt, uvi, ...}`) to the test fixtures used for UV tests (`onecall_imperial_highuv.json`, a new "uv crossing" fixture, a "stays below" fixture). Update the client docstring.
**Warning signs:** A UV computation that returns `None`/`stays_below` for every fixture; a `KeyError`/empty-list guard that never fires in tests.

### Pitfall 2: Computing "today" from the API tz instead of the configured tz
**What goes wrong:** Off-by-one-day hourly selection near midnight; wrong daytime window. `[VERIFIED: codebase models.py:34 Pitfall 3]`
**How to avoid:** Reuse the `_local_date_iso(loc, now_utc)` pattern; pass `ZoneInfo(loc.timezone)` into `compute_uv`.

### Pitfall 3: `CANONICAL` token added but not emitted (or vice versa)
**What goes wrong:** Token in `CANONICAL` but not in `placeholders()` → validates fine, renders literal `{uv_now}` (silent). Token emitted but not in `CANONICAL` → `validate_template` raises at load for any template using it.
**How to avoid:** Add every UV token to BOTH simultaneously; add a test `assert UV_TOKENS <= set(Forecast(...).placeholders())` and `assert UV_TOKENS <= renderer.CANONICAL`.

### Pitfall 4: The hardcoded `>= 6` hint now diverges from the configured threshold
**What goes wrong:** Two sources of truth — the sunscreen hint fires at the literal 6 (`models.py:76`) while the briefing UV line uses `config.uv.threshold`. With threshold=4 the briefing says "cross at 09:40" but no "Wear sunscreen" hint appears.
**Why it happens:** `_hints()` currently takes raw values, not config; the literal `6` is baked in.
**How to avoid:** Thread the configured threshold into `_hints` (or compute the sunscreen line from the same `compute_uv`/threshold). `from_payloads` will need access to the threshold — pass it in (e.g. `Forecast.from_payloads(loc, imp, met, *, uv_threshold=...)`). This is the explicit D-01 "unify three consumers" requirement. Default the param to `6.0` so existing call sites/tests that don't pass it keep current behavior, then update the live call sites (`lookup_weather`, `send_now`/daemon) to pass `config.uv.threshold`.
**Warning signs:** A test that asserts the sunscreen hint at uvi 9.6 still passes while a threshold-config test is missing.

### Pitfall 5: `daily[0].sunrise`/`sunset` absent (polar) or `hourly` short
**What goes wrong:** WHO/One Call docs note sunrise/sunset "not returned for polar areas in midnight sun / polar night." `[CITED: openweathermap.org/api/one-call-3]` A `None` sunrise breaks daytime bounding.
**How to avoid:** Defensive `.get()` (the project's house style — `or {}`/`or []`). Fall back to scanning all of today's hourly points (or current.sunrise/sunset) when daily sunrise/sunset is missing. Low practical risk for this user's cities, but the helper must not crash. Document the fallback.

### Pitfall 6: `current.uvi` "now" vs. interpolating "now"
**What goes wrong:** `current.uvi` is OpenWeather's current value; if you ALSO interpolate UV at `now` from hourly you can get a slightly different number, confusing the user.
**How to avoid:** Use `current.uvi` verbatim for `{uv_now}`. Use `daily[0].uvi` for the day's max (`{uv_max}`) — it is documented as "the maximum value of UV index for the day" `[CITED: openweathermap.org/api/one-call-3]`. Use `hourly[]` ONLY for crossing/window/peak-time. Do not re-derive "now" or "max" from hourly. (Peak-time clock derives from hourly; peak-value should agree with `daily[0].uvi` — if they disagree, prefer `daily[0].uvi` for the displayed number and the hourly argmax for the clock time.)

## Runtime State Inventory

> Rename/refactor categories — this is a feature phase, but it touches the live service, so checked explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — UV is computed on read; nothing persisted. The read-only `uv` command writes nothing (D-06 hard constraint). | none |
| Live service config | `config.toml` on host `yahir-mint` gains a `[uv]` table; the live daemon picks it up via existing file-watch/SIGHUP reload. No manual restart needed for config. | operator adds `[uv]` table (or it defaults) |
| OS-registered state | None — no systemd unit / scheduler change. | none |
| Secrets/env vars | None — threshold/lead are non-secret config, not `.env`. | none |
| Build artifacts | Editable install on host (per MEMORY): new `weatherbot/weather/uv.py` + edits ship via the existing editable install; **a daemon restart IS needed for the new Python code** (config reload alone won't load a new module). | restart daemon after deploy |

**Note for planner:** config (`[uv]` threshold/lead) is hot-reloadable; the new *code* (uv.py, models changes, client `exclude` change) requires a daemon restart on the host — same as any prior code-shipping phase.

## Code Examples

### Selecting today's daytime hourly UV points
```python
# [ASSUMED — illustrative; follows the codebase _local_date_iso idiom]
from datetime import datetime, timezone

def _today_daytime_points(onecall, tz, now):
    daily0 = (onecall.get("daily") or [{}])[0] or {}
    sunrise = daily0.get("sunrise")
    sunset = daily0.get("sunset")
    today = now.astimezone(tz).date()
    pts = []
    for h in (onecall.get("hourly") or []):
        ts = h.get("dt")
        uvi = h.get("uvi")
        if ts is None or uvi is None:
            continue
        local = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz)
        if local.date() != today:
            continue
        if sunrise and sunset and not (sunrise <= ts <= sunset):
            continue
        pts.append((local, float(uvi)))
    return pts
```

### Interpolated up-crossing time
```python
# [ASSUMED — illustrative]
def _first_up_cross(points, threshold):
    for (t0, u0), (t1, u1) in zip(points, points[1:]):
        if u0 < threshold <= u1:
            frac = (threshold - u0) / (u1 - u0)
            return t0 + (t1 - t0) * frac
    if points and points[0][1] >= threshold:
        return points[0][0]   # already above at first daytime point
    return None
```

### WHO category mapping
```python
# Bands [VERIFIED: epa.gov / who.int]: 0-2 Low, 3-5 Moderate, 6-7 High, 8-10 Very High, 11+ Extreme
def uv_category(uvi: float) -> str:
    u = round(uvi)
    if u <= 2: return "Low"
    if u <= 5: return "Moderate"
    if u <= 7: return "High"
    if u <= 10: return "Very High"
    return "Extreme"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `exclude=minutely,hourly` (bandwidth trim, v1.0) | `exclude=minutely` (keep hourly for UV) | This phase | Enables all interpolation; payload slightly larger, still 1 call/unit |
| Hardcoded `uvi_max >= 6` sunscreen hint | config-driven `uv.threshold` | This phase (D-01) | Unifies hint + briefing + Phase-15 monitor |

**Deprecated/outdated:** none relevant. One Call 3.0 hourly schema is current and stable. `[CITED: openweathermap.org/api/one-call-3]`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `compute_uv` reads UV from `onecall_imp` only (UV index is unitless, identical across unit systems); `onecall_met` accepted for parity but ignored | Pattern 1 | Low — if metric payload ever differed, would need both; UV is genuinely unitless |
| A2 | Round-then-band for the WHO category word (UV 5.6 → "High") | Pattern 4 | Low — purely a display convention; planner/user can pick floor-then-band |
| A3 | Suggested token names `{uv_now}/{uv_max}/{uv_cross}/{uv_window}/{uv_peak}/{uv_category}` | Pattern 5 | None — explicitly Claude's discretion (D); names are cosmetic |
| A4 | `[uv]` table with `threshold` (float, default 6) + `pre_warn_lead` (e.g. minutes int) | UV-03 / config | Low — exact field names/shape are Claude's discretion (D); `pre_warn_lead` is consumed by Phase 15 but configured here per UV-03 |
| A5 | Threshold default `6.0` preserves the current hardcoded hint behavior exactly | Pitfall 4 | None — matches the literal being replaced (D-01) |
| A6 | "First crosses above" = first up-cross within today's daytime points; protect window = that up-cross → first subsequent down-cross, sunset-bounded | Pattern 2/3 | Low — direct from D-02/D-03 locked decisions |

## Open Questions

1. **`pre_warn_lead` units and semantics in `[uv]`**
   - What we know: UV-03 requires a "pre-warning lead" configured here; Phase 15 consumes it.
   - What's unclear: minutes vs. a duration string; whether it's a time-before-crossing or a UV-delta-before-threshold. CONTEXT D-01 only locks the threshold.
   - Recommendation: model it as integer minutes (`pre_warn_lead_minutes`, default e.g. 30) for simplicity; Phase 14 only stores/validates it (no behavior), Phase 15 gives it meaning. Flag for the planner to confirm shape; it's discretion-area config.

2. **Does the `uv` command's compact hourly line need both up- and down-cross annotated, or just raw daytime values?**
   - What we know: D-04 says "compact today-hourly UV line (daytime hours with their UV values)."
   - Recommendation: render raw `HH UV` pairs for daytime hours (e.g. `08:2 10:5 12:7 14:8 16:6`); the summary fields already carry the crossing/window. Planner decides exact format.

## Environment Availability

> No new external tools/services. One Call 3.0 is already integrated and authenticated; the only change is dropping `hourly` from `exclude`.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| OpenWeather One Call 3.0 `hourly[]` | crossing/window/peak | ✓ (already entitled; just stop excluding) | 3.0 | none needed |
| Python stdlib `zoneinfo`/`datetime` | time math | ✓ | 3.12+ | — |
| pydantic | `UvConfig` | ✓ | 2.13.x | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

## Validation Architecture

> nyquist_validation: config.json not found to set it false; treating as enabled.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing; `tests/` with fixtures) `[VERIFIED: codebase tests/]` |
| Config file | (project uses pytest convention; see `pyproject.toml`/`tests/`) |
| Quick run command | `uv run pytest tests/test_uv.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UV-03 | `[uv]` threshold/lead loads, validates, hot-reloads; unknown key fails loud | unit | `uv run pytest tests/test_config_uv.py -x` | ❌ Wave 0 |
| UV-02 | compute_uv: crossing interpolation, stays-below, window, peak, category | unit | `uv run pytest tests/test_uv.py -x` | ❌ Wave 0 |
| UV-02 | UV tokens render in briefing; CANONICAL ↔ placeholders lockstep | unit | `uv run pytest tests/test_models.py tests/test_renderer.py -x` | ✅ (extend) |
| UV-01/02 | sunscreen hint reads configured threshold (not literal 6) | unit | `uv run pytest tests/test_models.py -k hint -x` | ✅ (extend) |
| UV-01 | `uv <loc>` command (CLI + Discord) returns summary + hourly line via read-only core | unit/integration | `uv run pytest tests/test_interactive*.py -x` | ✅ (extend, Phase-12 registry) |
| UV-04 (criterion) | no extra API call; hourly kept via exclude change | unit | `uv run pytest tests/test_client.py -x` | ✅ (extend) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_uv.py -x`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_uv.py` — covers UV-02 (compute_uv math: up-cross, down-cross, already-above-at-sunrise, never-crosses, multi-peak, missing-sunrise fallback, category boundaries)
- [ ] `tests/test_config_uv.py` — covers UV-03 (`[uv]` load/validate/reload/unknown-key)
- [ ] **Fixtures with `hourly[]`** — at least: a "UV crosses 6 mid-morning" fixture, a "stays below threshold all day" fixture, and add `hourly[]` to `onecall_imperial_highuv.json`. **This is the critical Wave-0 deliverable** — no UV interpolation test can exist without it.
- [ ] Extend `tests/test_models.py` (UV placeholders + threshold-driven hint), `tests/test_renderer.py` (UV tokens in CANONICAL), `tests/test_client.py` (exclude no longer drops hourly).

## Security Domain

> security_enforcement: no config.json found disabling it; included for completeness.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | OpenWeather `appid` already handled; unchanged |
| V3 Session Management | no | n/a |
| V4 Access Control | yes (reused) | `uv` command rides the existing operator-id guard ladder (Phase 12 D-05); no new surface |
| V5 Input Validation | yes | `[uv]` config validated fail-loud (pydantic `extra="forbid"`); location arg goes through existing `parse`/`resolve_location`; template tokens allow-listed |
| V6 Cryptography | no | no new secrets; threshold/lead are non-secret |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Template-token injection via user-edited `.txt` | Tampering | Existing regex substitution (no `str.format`/`eval`) + `CANONICAL` allow-list — unchanged, just extended `[VERIFIED: codebase renderer.py]` |
| Secret leak via logged request URL (`appid`) | Info Disclosure | Already mitigated: `httpx` logger raised to WARNING (`client.py:39`); the exclude change doesn't alter logging |
| Malformed `[uv]` config crashing the 9am send | DoS | Fail-loud at load + reload-keeps-old-on-bad-config (existing `validate_config_and_templates`) |

## Sources

### Primary (HIGH confidence)
- Codebase: `weatherbot/weather/models.py`, `weatherbot/weather/client.py`, `templates/renderer.py`, `weatherbot/config/models.py`, `weatherbot/config/loader.py`, `weatherbot/interactive/lookup.py`, `weatherbot/interactive/command.py`, `weatherbot/scheduler/context.py`, `tests/fixtures/*.json`, `tests/test_models.py` — read directly this session.
- https://openweathermap.org/api/one-call-3 — `hourly[].{dt,uvi}` (48h), `daily[0].{sunrise,sunset,uvi}` ("uvi" = max UV for the day; sunrise/sunset absent in polar), `exclude` options. HIGH
- https://www.epa.gov/sunsafety/uv-index-scale-0 + https://www.who.int/news-room/questions-and-answers/item/radiation-the-ultraviolet-(uv)-index — WHO UV bands 0–2/3–5/6–7/8–10/11+. HIGH

### Secondary (MEDIUM confidence)
- 14-CONTEXT.md / 12-CONTEXT.md / ROADMAP.md / REQUIREMENTS.md / STATE.md — locked decisions and reuse anchors.

### Tertiary (LOW confidence)
- None — all claims verified against code or official docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all seams read directly.
- Architecture: HIGH — pure-helper + placeholder + config patterns all already exist in-repo.
- Pitfalls: HIGH — the `hourly`-excluded blocker and the hardcoded-`6` divergence are both confirmed by reading the exact lines.

**Research date:** 2026-06-18
**Valid until:** 2026-07-18 (stable; One Call 3.0 schema and the local codebase are the only inputs)
