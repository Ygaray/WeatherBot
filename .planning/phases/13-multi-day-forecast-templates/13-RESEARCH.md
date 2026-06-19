# Phase 13: Multi-Day Forecast Templates - Research

**Researched:** 2026-06-18
**Domain:** Multi-day forecast rendering + per-location forecast scheduling over already-fetched One Call 3.0 `daily[]` (brownfield extension of WeatherBot)
**Confidence:** HIGH

## Summary

This is a **brownfield, zero-new-dependency** phase. Every primitive the phase needs already
exists in the codebase: the One Call 3.0 client already fetches the full 8-element `daily[]`
array (it only excludes `minutely`/`hourly`), so FCAST-07 ("reuse already-fetched `daily`, no
new call") is satisfied **for free** — nothing changes in `weather/client.py`. The renderer
already has a parameterized `validate_template(text, allowed=...)` signature, so a forecast
token set is a one-argument extension, not a rewrite. The scheduler reconcile-by-stable-id
machinery (`_register_jobs` / `_desired_job_ids` / `_reconcile_jobs`) is already a clean loop
over `(location, slot)` keyed on a string id — forecast jobs slot in by **widening the id to
encode a job kind + variant** and adding a second enumeration source. The day-of-week grammar
(`mon`..`sun`, presets) already lives in a dependency-free `scheduler/days.py`, which the new
`+day`/`-day` flag parser should reuse for its token vocabulary.

The genuinely **new** code is: (1) a per-day extraction model reading `daily[1..7]` (analogous
to how `Forecast` reads `daily[0]`); (2) a forecast token set + a code-rendered per-day line
with a template-controlled format string and header/footer; (3) a config representation for
per-location forecast schedule slots that stays `frozen=True` and reconcilable; (4) a shared
CLI+Discord `+day`/`-day`/`+compact` flag grammar; (5) the window/roll-forward day-selection
logic bounded by One Call's today+7 horizon.

The single highest-risk area is the **windowing logic** (D-01: "remaining days now, roll
forward when empty") interacting with One Call's 8-day horizon — a weekend forecast that rolls
to "next week" can request days that fall outside `daily[0..7]`, and out-of-window `+day` flags
(D-03) must surface a clear notice rather than silently drop. This is pure date arithmetic over
a bounded array and is fully testable with synthetic `daily[]` fixtures.

**Primary recommendation:** Add a `ForecastDay` extraction model (reads `daily[i]`, mirrors
`Forecast`'s imperial-primary `_temp_str` display discipline) + a `multiday.py` selector that
maps (forecast-kind, today's local date, flags) → an ordered list of in-window `ForecastDay`s;
render via the existing `render`/`validate_template` with a **forecast-specific allowed token
set** and a **code-built per-day block**; represent forecast schedule slots as a new
`ForecastSchedule` model on `Location` (kind+variant+time+days+enabled), enumerated alongside
`location.schedule` in a widened stable job id `{location.name}|fc|{kind}|{variant}|{time}|{days}`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reuse already-fetched `daily[]` (FCAST-07) | Weather model (`ForecastDay` extraction) | One Call client (already fetches it) | Pure extraction/formatting; the client already returns full `daily[]`, so no fetch-tier change |
| Window/roll-forward day selection (D-01) | Forecast selector logic (new `multiday.py`) | — | Date arithmetic over a bounded array; belongs in pure, testable logic, not in the model or renderer |
| Detailed vs compact + per-day line (D-02/D-06) | Renderer (forecast token set + code-rendered per-day block) | Template files (header/footer + line format string) | "No logic in templates" is a project invariant — per-day iteration is code; the template owns presentation strings |
| `+day`/`-day`/`+compact` flag parsing (D-03) | Command/flag parser (shared CLI+Discord) | `scheduler/days.py` (token vocabulary) | One grammar feeds both surfaces (Phase 6 shared-core principle); reuse the existing day vocabulary |
| On-demand dispatch, read-only, no store writes (FCAST-05) | `interactive/lookup.py` + `ForecastCache` + Phase 12 registry | Discord bot / CLI subparsers | Reuses the proven read-only fetch→render core and guard ladder; zero store imports |
| Per-location forecast schedule slots (FCAST-06) | Config models (`Location` + new `ForecastSchedule`) | Scheduler (`_register_jobs`/reconcile) | Config owns the editable, validated, frozen structure; scheduler reconciles it by stable id |
| Scheduled forecast firing (FCAST-06) | Scheduler (`fire_forecast_slot` callback + cron job) | `_do_reload` reconcile path | Must obey the same exactly-once/DST discipline as the briefing spine |

## Standard Stack

This phase introduces **no new packages**. Every dependency is already in `uv.lock` and in
production use. Versions below are verified from the project's `uv.lock` (2026-06-18).

### Core (already installed — reused, not added)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `datetime` / `zoneinfo` | 3.12+ | Window date arithmetic, weekday labels, local-date selection | Already the project's tz-correctness foundation (`_local_date_iso`, `ZoneInfo(location.timezone)`); the configured IANA tz is authoritative for "today" [VERIFIED: codebase weather/models.py] |
| pydantic | 2.13.4 | Forecast schedule slot model (`frozen=True`, `extra="forbid"`, fail-loud validators) | Every config model already uses this exact pattern (`Schedule`, `Location`) [VERIFIED: uv.lock] |
| apscheduler | 3.11.2 | Forecast cron jobs via `CronTrigger(day_of_week=..., timezone=...)` | The briefing spine already uses this; forecast jobs reuse `_register_jobs` verbatim [VERIFIED: uv.lock] |
| httpx | 0.28.1 | (unchanged) One Call fetch — already returns full `daily[]` | No change; FCAST-07 reuses the existing fetch [VERIFIED: uv.lock] |
| cachetools (via `ForecastCache`) | 7.1.4 | Off-loop TTL reuse for on-demand forecasts | Discretion in CONTEXT.md: "share `ForecastCache` — likely yes" [VERIFIED: uv.lock] |

### Supporting (existing project modules — extend, don't replace)
| Module | Purpose | When to Use |
|---------|---------|-------------|
| `templates/renderer.py` | `validate_template(text, allowed=SET)` + `render(text, values)` | Already parameterized on `allowed`; pass a forecast token set |
| `weatherbot/scheduler/days.py` | `parse_days` + `_DAYS`/`_PRESETS` vocabulary | Reuse `_DAYS` as the canonical `+day`/`-day` token set |
| `weatherbot/interactive/lookup.py` | read-only fetch→render core | Add a forecast lookup path that reuses the same dual-unit fetch |
| `weatherbot/weather/models.py` | `Forecast` + `_temp_str` imperial-primary display | Mirror `_temp_str` in a new `ForecastDay` so per-day temps match briefing display |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New `ForecastSchedule` model on `Location` | Extend `Schedule` with `kind`/`variant` fields | Extending `Schedule` muddies the briefing slot (every briefing slot would carry null forecast fields) and risks the `name|time|days` job-id collision between a briefing and a forecast at the same time/days. A separate list (`location.forecast`) keeps the two job kinds cleanly partitioned and the id encoding unambiguous. **Recommend the separate model.** |
| Code-rendered per-day block | Jinja2 per-day loop in templates | Project forbids logic in templates (CLAUDE.md "logic should live in the template file, not code" refers to *editable presentation*; the renderer deliberately runs NO `str.format`/`eval`/loops — see `renderer.py` docstring). A Jinja2 loop reintroduces template logic and a second rendering engine. **Code-render the per-day block; template owns header/footer + one line-format string.** |
| `strftime("%a %-m/%-d")` for labels | Manual weekday/month formatting | `%-m`/`%-d` (no zero-pad) is glibc-specific and non-portable to some platforms; the host is Linux (yahir-mint), so it works, but a small explicit `f"{abbr} {dt.month}/{dt.day}"` is portable and matches the D-04 "Wed 6/25" example exactly. **Use explicit f-string, not `%-m`.** [VERIFIED: Bash strftime test on host] |

**Installation:** None. `uv sync` already provides everything.

**Version verification:** Confirmed from `uv.lock` (2026-06-18): apscheduler 3.11.2, httpx 0.28.1,
pydantic 2.13.4, cachetools 7.1.4. CLAUDE.md's recommended bands (apscheduler 3.11.x, httpx
0.28.x, pydantic 2.13.x) all match. No package install occurs in this phase.

## Package Legitimacy Audit

**Not applicable — this phase installs zero external packages.** All code reuses modules and
libraries already present in `uv.lock` and in production. No `uv add` step appears in any plan
for this phase. (If a planner later proposes a new package, the Package Legitimacy Gate must run
before it is added — but the research finds no such need.)

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────────────────────────────┐
ON-DEMAND  (FCAST-05)     │  Phase 12 command registry                  │
  CLI  weekday-forecast ──┤  (CLI subparser + Discord !dispatch)        │
  Discord !weekday-forecast│  parses: location, +compact, +day/-day     │
                          └───────────────┬─────────────────────────────┘
                                          │ (name, kind, variant, flags)
                                          ▼
SCHEDULED (FCAST-06)              ┌────────────────────┐
  CronTrigger(day_of_week,        │  forecast lookup    │  read-only, off-loop,
  timezone) → fire_forecast_slot ─┤  (extends lookup_*) │  ForecastCache-backed
                                  └─────────┬──────────┘
                                            │ reuses dual-unit One Call payloads
                                            ▼
                          ┌──────────────────────────────────────┐
                          │ raw_onecall_imp/met  (ALREADY FETCHED)│ ← FCAST-07: no new call
                          │   .daily[0..7]                        │
                          └─────────────────┬────────────────────┘
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │ multiday selector (NEW, pure logic)           │
                    │  (kind, today_local_date, flags) →            │
                    │   ordered in-window day indices               │  ← D-01 window/roll-forward
                    │   + out-of-window notice for bad +flags       │  ← D-03 horizon guard
                    └─────────────────┬─────────────────────────────┘
                                      ▼
                    ┌───────────────────────────────────────────────┐
                    │ ForecastDay (NEW model, reads daily[i])       │  ← mirrors Forecast._temp_str
                    │   label + hi/lo + sky + rain (+ wind/uvi/     │     imperial-primary display
                    │   feels-hi/lo/sun if detailed)                │
                    └─────────────────┬─────────────────────────────┘
                                      ▼ per-day token maps
                    ┌───────────────────────────────────────────────┐
                    │ renderer (EXISTING render + validate_template)│
                    │  code builds per-day block from a template-   │  ← D-06 line format string
                    │  supplied line-format; template owns          │     header/footer
                    │  {header}/{footer} + {days} insertion         │
                    └─────────────────┬─────────────────────────────┘
                                      ▼
                          rendered text → CLI stdout / Discord embed or message
                          (NEVER writes the SQLite time series — FCAST-05)
```

### Recommended Project Structure
```
weatherbot/weather/
├── models.py              # EXISTING Forecast; ADD ForecastDay (reads daily[i])
└── multiday.py            # NEW: window/roll-forward selector (pure, testable)
templates/
├── renderer.py            # EXISTING; ADD FORECAST_TOKENS set + per-day render helper
├── forecast-weekday-detailed.txt   # NEW editable template (header/footer + line fmt)
├── forecast-weekday-compact.txt     # NEW
├── forecast-weekend-detailed.txt    # NEW
└── forecast-weekend-compact.txt     # NEW
weatherbot/config/
└── models.py              # ADD ForecastSchedule model + Location.forecast list
weatherbot/interactive/
├── lookup.py              # ADD forecast lookup path (reuse dual-unit fetch)
└── flags.py (or extend command.py)  # NEW shared +day/-day/+compact grammar
weatherbot/scheduler/
└── daemon.py              # EXTEND _register_jobs/_desired_job_ids/_reconcile_jobs
                           # + fire_forecast_slot callback
```

### Pattern 1: Forecast token set as a second `allowed` set (renderer parameterization)
**What:** `validate_template` already takes `allowed: set[str] = CANONICAL`. Define a distinct
`FORECAST_TOKENS` set for the header/footer + line-format tokens and pass it explicitly.
**When to use:** Every forecast template load+validate (mirror `lookup_weather`'s
`validate_template(template_text)` call site, but with the forecast set).
**Example:**
```python
# Source: templates/renderer.py (existing signature) — extend, do not rewrite
# renderer.py ALREADY supports this:
def validate_template(template_text: str, allowed: set[str] = CANONICAL) -> None: ...

# ADD a forecast token set. Two scopes:
#  - HEADER/FOOTER tokens (whole-message, validated against the template body):
FORECAST_TOKENS = {"location", "title", "range_label", "days", "footer_note", "notice"}
#  - PER-DAY LINE tokens (validated against the template's line-format string):
FORECAST_DAY_TOKENS_DETAILED = {
    "label", "high", "low", "sky", "rain", "wind", "uvi", "feels_high",
    "feels_low", "sunrise", "sunset",
}
FORECAST_DAY_TOKENS_COMPACT = {"label", "high", "low", "sky"}

# The {days} token is the code-built per-day block injected at render time
# (NOT a placeholder the user fills) — same merge-in idiom as schedule_placeholders.
```

### Pattern 2: Code-rendered per-day block with a template-supplied line format (D-06)
**What:** The template body contains a header, a footer, and a single line-format string for one
day; code iterates the selected `ForecastDay`s, renders each via `render(line_fmt, day_tokens)`,
joins them, and injects the joined block as `{days}` into the outer template.
**When to use:** All four forecast templates.
**Example:**
```python
# Source: derived from templates/renderer.py render() contract (guarded substitution)
from templates.renderer import render, validate_template

def render_forecast(template_text: str, line_fmt: str, days: list[dict],
                    header_values: dict, day_allowed: set[str]) -> str:
    validate_template(line_fmt, allowed=day_allowed)          # fail-loud per-day tokens
    block = "\n".join(render(line_fmt, d) for d in days)      # code iteration, no template logic
    values = {**header_values, "days": block}
    validate_template(template_text, allowed=FORECAST_TOKENS) # fail-loud header/footer tokens
    return render(template_text, values)
```
**Design note:** How the template *carries* the line-format is Claude's discretion (CONTEXT.md
D-06). Two viable shapes — both keep "no logic in template": (a) a separate `*.line.txt`
sibling file per template; (b) a sentinel block inside one file (e.g. a `{{day}} ... {{/day}}`
fenced region the loader splits out before `render`). Recommend (a) the sibling line-file: it
needs no new parsing grammar and reuses `load_template` unchanged.

### Pattern 3: Widened stable job id for forecast slots (reconcile churn-free)
**What:** `_register_jobs`/`_desired_job_ids` build the id `f"{location.name}|{slot.time}|{slot.days}"`.
Forecast jobs need a DISTINCT, collision-free id that also encodes kind+variant so a no-op reload
diffs to zero churn.
**When to use:** Both enumeration sites (they MUST stay byte-identical — `_desired_job_ids`
"mirrors `_register_jobs` EXACTLY", per the docstring).
**Example:**
```python
# Source: weatherbot/scheduler/daemon.py (existing id scheme) — extend the loop
# Briefing id (unchanged):     f"{location.name}|{slot.time}|{slot.days}"
# Forecast id (NEW, namespaced so it can never collide with a briefing id):
def _forecast_job_id(location, fc) -> str:
    return f"{location.name}|fc|{fc.kind}|{fc.variant}|{fc.time}|{fc.days}"

# In BOTH _register_jobs and _desired_job_ids, add a second loop AFTER the
# existing `for slot in location.schedule` loop:
for fc in location.forecast:           # new ForecastSchedule list
    if not fc.enabled:
        continue
    # _register_jobs: scheduler.add_job(fire_forecast_slot, trigger=CronTrigger(
    #     hour, minute, day_of_week=fc.day_of_week, timezone=location.timezone),
    #     id=_forecast_job_id(location, fc), replace_existing=replace_existing,
    #     misfire_grace_time=None, coalesce=True, kwargs={holder, db_path, ...})
    # _desired_job_ids: ids.add(_forecast_job_id(location, fc))
```
**Critical:** `_reconcile_jobs` excludes only `__heartbeat__` from the live set; once forecast
ids are in `_desired_job_ids`, reconcile handles add/remove/unchanged for them automatically —
**no reconcile-body change needed**, only the two enumeration loops. A variant edit
(detailed→compact) yields a different id → surfaces as one ADD + one REMOVE (same semantics as a
briefing time edit, per the existing `_reconcile_jobs` docstring).

### Pattern 4: `fire_forecast_slot` mirrors `fire_slot` discipline minus the store writes
**What:** A forecast cron callback that fetches (reusing One Call), renders the forecast, and
posts to the channel — but does NOT `claim_slot`/`record_alert`/write the time series (forecasts
are read-only per FCAST-05; the exactly-once-briefing machinery does not apply because a missed
scheduled forecast is not a "briefing missed" event).
**When to use:** The scheduled-forecast path (FCAST-06).
**Design decision for the planner:** Scheduled briefings use `claim_slot` for delivery-level
exactly-once across overlapping fires/restarts. Forecasts are lower-stakes and read-only. Two
options: (a) **no claim** — accept that a restart-within-catch-up could re-post a scheduled
forecast (simplest, and the catch-up scan currently only enumerates `location.schedule`, so
forecasts are NOT caught up unless explicitly added); (b) **reuse `claim_slot`** with a
forecast-namespaced slot key for the same exactly-once guarantee. **Recommend (a) no-claim,
no-catchup for v1** — it keeps forecasts entirely off the briefing's exactly-once SQLite path
(cleaner FCAST-05 "never writes the time series"), and a missed scheduled forecast on restart is
not user-visible harm. Confirm with the user during planning (see Assumptions Log A1).

### Anti-Patterns to Avoid
- **Adding a Jinja2 loop or `str.format` to templates.** The renderer deliberately runs neither
  (`renderer.py` docstring: no `str.format`/`Formatter`, no `eval`, guarded `{name}` substitution
  only). Reintroducing logic in templates breaks the project's fail-loud, injection-safe contract.
- **Reusing the briefing job id namespace for forecasts.** A forecast at the same `time`/`days`
  as a briefing would collide on `{name}|{time}|{days}` and silently replace the briefing job.
  Namespace forecast ids (`|fc|...`).
- **Touching `weather/client.py`.** It already fetches the full `daily[]`. FCAST-07 is satisfied
  by extraction alone; a new endpoint or a changed `exclude` would be a regression.
- **Writing the SQLite store from any forecast path.** FCAST-05 is a HARD constraint mirroring
  Phase 6's read-only discipline — no store imports in the forecast lookup/fire path.
- **Mutating `Schedule` to carry forecast fields.** Keep forecast slots in a separate frozen
  model so the briefing slot stays clean and ids never collide.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Day-of-week token vocabulary for `+day`/`-day` | A new mon..sun set | `scheduler/days._DAYS` (reuse/import) | One source of truth; `parse_days` already validates these tokens fail-loud |
| Cron scheduling for forecast slots | A custom timer/thread | APScheduler `CronTrigger(day_of_week=, timezone=)` via `_register_jobs` | Already the proven, DST-correct, per-location-tz spine |
| Stable-id job reconcile on reload | A clear-and-rebuild of the job table | Existing `_reconcile_jobs` (just add forecast ids to `_desired_job_ids`) | Churn-free no-op reloads, rollback, all already handled |
| Template token validation | A custom `{token}` parser | `validate_template(text, allowed=FORECAST_TOKENS)` | Already parameterized on `allowed`; shares the exact `_TOKEN` grammar with `render` |
| Guarded `{token}` substitution | `str.format`/f-string interpolation of user templates | Existing `render()` | Injection-safe (no attr/index/positional/format-string access), leaves typos visible |
| Off-loop TTL caching for on-demand | A new cache | `ForecastCache` (CONTEXT.md says "likely yes") | Same read-only off-loop path; repeated commands stay off the API quota |
| Imperial-primary-with-metric temp display | New formatting code | `Forecast._temp_str` pattern (copy into `ForecastDay`) | Keeps per-day temps byte-consistent with the briefing's display |
| IANA tz "today" selection | API `timezone` field or naive `date.today()` | `ZoneInfo(location.timezone)` + `_local_date_iso` pattern | Configured tz is authoritative (D-03, existing Pitfall 3) |

**Key insight:** This phase is ~80% wiring existing seams and ~20% genuinely new pure logic
(window selection + per-day extraction). The temptation to "just add a Jinja2 loop" or "write a
quick scheduler" would each re-solve a problem the codebase already solved correctly and safely.

## Runtime State Inventory

This is a **greenfield-feature phase** (adds new output + new config slots), not a
rename/refactor/migration. No existing stored data, service config, OS-registered state, or
secrets are renamed or migrated. The one operational note:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — forecasts are read-only (FCAST-05); no SQLite rows written or renamed | None |
| Live service config | New `[[locations.forecast]]` slots are added to the live, file-watched `config.toml`; the running daemon on host `yahir-mint` picks them up via the existing reload/reconcile path (no manual export) | None beyond editing config.toml (per CLAUDE.md "no code changes" requirement) |
| OS-registered state | None — no new systemd units, no Task Scheduler, no PID changes | None |
| Secrets/env vars | None — no new secrets; OpenWeather key + webhook/token unchanged | None |
| Build artifacts | The bot runs as an **editable install** on `yahir-mint` (per MEMORY.md); new modules are picked up on a daemon **restart** for scheduled forecasts to register. On-demand forecast commands need the same restart to be dispatchable. | Daemon restart after deploy (config-only edits hot-reload; **new code** does not) |

**Nothing found requiring data migration.** The only operational action is the standard
post-deploy daemon restart (new Python modules require it; this is the established
editable-install + systemd `Restart=always` pattern, MEMORY.md).

## Common Pitfalls

### Pitfall 1: Window roll-forward requesting days outside One Call's today+7 horizon
**What goes wrong:** D-01 says a weekday forecast run on Saturday rolls to "next week's full
block" (next Mon–Fri). But One Call 3.0 `daily[]` is **today + 7 days = 8 entries** [CITED:
openweathermap.org/api/one-call-3]. Next week's Friday can be 6 days out (in window) — but the
combination of roll-forward + `+day` flags can name a day beyond `daily[7]`.
**Why it happens:** The block's calendar dates are computed independently of the fetched array's
bounded length; naive indexing past `daily[7]` raises `IndexError` or silently wraps.
**How to avoid:** The `multiday` selector maps each desired calendar date to a `daily[]` index
by matching the local date of each `daily[i]` (`dt` → location-local date), and **drops + flags**
any desired date with no matching in-window entry. Never index `daily[]` positionally by
day-of-week math; always resolve date→index against the actual array.
**Warning signs:** `IndexError` in tests with short `daily[]` fixtures; a "next week" weekday
forecast showing fewer than 5 days near the horizon edge (expected — emit the notice, not a crash).

### Pitfall 2: Out-of-window `+day` flags silently dropped
**What goes wrong:** D-03 explicitly requires "Out-of-window days (beyond the +7 horizon) → a
clear notice rather than a silent drop." A naive set-intersection with the in-window dates drops
them invisibly.
**Why it happens:** Dedup/sort/intersect logic discards unmatched flag days without recording
them.
**How to avoid:** Partition flag days into in-window (rendered) and out-of-window (collected into
a `{notice}` token, e.g. "Sat 7/4 is beyond the 7-day forecast horizon"). The forecast template's
header/footer set includes a `notice`/`{notice}` token for this.
**Warning signs:** A `+sat` flag near the horizon producing identical output to no flag.

### Pitfall 3: `feels_like` per-day has no `min`/`max` (only day/night/eve/morn)
**What goes wrong:** The detailed variant wants "feels-like high/low" (D-02), but `daily[i].feels_like`
is an object with keys `day`/`night`/`eve`/`morn` — there is **no `min`/`max`** [VERIFIED: One Call
3.0 docs + fixture introspection: `feels_like keys: ['day','eve','morn','night']`]. By contrast
`daily[i].temp` DOES have `min`/`max`.
**Why it happens:** Assuming `feels_like` mirrors `temp`'s shape.
**How to avoid:** Derive feels-like "high/low" as `max(feels_like.values())` / `min(feels_like.values())`
across the four dayparts (the sensible interpretation), and document it. Do NOT look for
`feels_like.max`. Confirm the high/low derivation with the user (Assumptions Log A2).
**Warning signs:** `KeyError: 'max'` on `daily[i].feels_like`.

### Pitfall 4: Stable-id enumeration drift between `_register_jobs` and `_desired_job_ids`
**What goes wrong:** If the two functions build the forecast id even slightly differently, every
reload diffs the same slot as one ADD + one REMOVE (constant churn), defeating the no-op-reload
guarantee.
**Why it happens:** Copy-paste divergence; the existing code warns "Mirrors `_register_jobs`
EXACTLY".
**How to avoid:** Extract `_forecast_job_id(location, fc)` as a single helper called by BOTH
enumeration loops (the briefing id is currently inlined in both — for forecasts, factor it out so
it can't drift).
**Warning signs:** A reload with no config change logging a non-zero `+a -r` summary.

### Pitfall 5: Forecast template typo crashing a scheduled send vs. failing loud at load
**What goes wrong:** A typo'd `{token}` in a forecast template either ships a literal token or
crashes the scheduled forecast fire.
**Why it happens:** Skipping the load-boundary `validate_template` for the new templates.
**How to avoid:** Validate every forecast template (and its line-format) at the same boundary the
briefing template is validated — and add them to `validate_config_and_templates` so a bad
forecast template is rejected at config load / reload (keep-old), exactly like the briefing
template. The file-watch `_derive_watch_dirs`/`_make_watch_filter` build over the
`{config.template}` set today; forecast template filenames must be added to those sets so editing
a forecast template also triggers a reload (and is watched). [VERIFIED: codebase
daemon.py `_derive_watch_dirs`/`_make_watch_filter`]
**Warning signs:** Editing a forecast template does not trigger a reload; a literal `{hgih}`
appears in a posted forecast.

### Pitfall 6: `daily[0]` "today" vs. relative labels "Today"/"Tomorrow" off-by-one across tz/DST
**What goes wrong:** D-04 labels the first two days "Today"/"Tomorrow", then weekday+date. If
"today" is computed in UTC or the API tz instead of the configured IANA tz, the label and the
date can disagree near midnight or a DST boundary.
**Why it happens:** Mixing `daily[i].dt` (UTC) interpretation with the configured-tz "today".
**How to avoid:** Compute today's local date via `ZoneInfo(location.timezone)` (the existing
`_local_date_iso` discipline), convert each `daily[i].dt` to that same tz for its date, and derive
the relative label from the difference in local dates. One tz, used consistently.
**Warning signs:** "Tomorrow" showing today's date in a test pinned near local midnight.

## Code Examples

### Extract a single forecast day (mirrors Forecast.from_payloads daily[0] read)
```python
# Source: derived from weatherbot/weather/models.py Forecast.from_payloads (existing)
# daily[i] shape VERIFIED against One Call 3.0 docs + tests/fixtures introspection:
#   keys: dt, sunrise, sunset, temp{min,max,day,night,eve,morn},
#         feels_like{day,night,eve,morn}, humidity, pop, uvi, weather[], wind_speed,
#         wind_deg, clouds  (NO feels_like.min/max — see Pitfall 3)
@dataclass
class ForecastDay:
    label: str                  # "Today" / "Tomorrow" / "Wed 6/25" (D-04)
    high_imp: float | None; high_met: float | None
    low_imp: float | None;  low_met: float | None
    sky: str                    # weather[0].main
    rain_chance: int            # round(pop*100)
    wind_imp: float; wind_met: float          # detailed only
    uvi: float                                # detailed only (daily[i].uvi)
    feels_high_imp: float | None; feels_high_met: float | None   # max(feels_like dayparts)
    feels_low_imp: float | None;  feels_low_met: float | None    # min(feels_like dayparts)
    sunrise: int; sunset: int                 # Unix UTC → format in location tz
    primary: str = "imperial"
    # reuse Forecast._temp_str logic for *_display props (imperial-primary)
```

### Window selector signature (pure, testable)
```python
# Source: NEW weatherbot/weather/multiday.py — implements D-01 + D-03
def select_days(
    kind: str,                  # "weekday" (mon-fri) | "weekend" (fri-sat-sun)
    today_local: date,          # computed via ZoneInfo(location.timezone)
    daily: list[dict],          # raw daily[] (today + up to 7); resolved date→index
    add: set[str],              # {"sat"} from +sat   (mon..sun tokens, reuse days._DAYS)
    drop: set[str],             # {"mon"} from -mon
) -> tuple[list[int], list[str]]:
    """Return (in-window daily[] indices in calendar order, out-of-window notices).

    1. base day set = kind's weekdays; apply drop then add; dedup; sort calendar order.
    2. if every base day is in the PAST (block exhausted) → roll to next week's block.
    3. map each desired calendar date → daily[] index by matching local date of daily[i].
    4. dates with no in-window match → collected as notices (Pitfall 2), not indexed.
    """
```

### Forecast schedule config model (frozen, fail-loud)
```python
# Source: derived from weatherbot/config/models.py Schedule (existing pattern)
class ForecastSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str            # "weekday" | "weekend"   (field_validator: one of {...})
    variant: str = "detailed"   # "detailed" | "compact"  (validator)
    time: str            # "HH:MM"  (reuse the exact Schedule._hhmm validator)
    days: str            # preset/comma list (reuse parse_days)
    enabled: bool = True
    # parsed_time() / day_of_week property identical to Schedule
# On Location:  forecast: list[ForecastSchedule] = Field(default_factory=list)
# Stays frozen=True → ConfigHolder snapshot-compatible; absent table → empty list.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 2.5 `/forecast` 3-hour bucket aggregation for high/low | One Call 3.0 `daily[]` ready-made per-day aggregates | Retired in Plan 02-01 (D-01), codebase comment | Multi-day is pure extraction from `daily[1..7]`; no bucket math to re-derive |
| APScheduler 4.x | APScheduler 3.11.x (`CronTrigger`) | Project decision (CLAUDE.md: "do NOT use 4.x") | Forecast jobs use the same stable 3.x `CronTrigger`/`day_of_week` API |

**Deprecated/outdated:** Nothing new deprecated for this phase. The `%-m`/`%-d` strftime
specifiers, while working on the Linux host, are glibc-specific — prefer explicit f-string
date formatting for the "Wed 6/25" label (portable, matches D-04 verbatim).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Scheduled forecasts use a **no-claim, no-catchup** path (not the briefing `claim_slot` exactly-once machinery), since they are read-only and a missed scheduled forecast on restart is low-harm. | Pattern 4 | If the user expects a missed scheduled forecast to be caught up on restart like a briefing, this path omits it. Low risk (forecasts are informational), but confirm. |
| A2 | "Feels-like high/low" (D-02 detailed) is derived as `max`/`min` over the four `feels_like` dayparts (`day`/`night`/`eve`/`morn`), since One Call provides no `feels_like.min/max`. | Pitfall 3 | A different intended definition (e.g. feels-like at the temp-max hour) would change the displayed values. Reasonable default; confirm. |
| A3 | The per-day line-format lives in a **sibling `*.line.txt` file** per template (vs. an in-file fenced block). | Pattern 2 | Pure presentation choice; CONTEXT.md leaves it to Claude's discretion, so low risk — planner may pick either. |
| A4 | The `+day`/`-day` token vocabulary is the **weekday abbreviations only** (`mon`..`sun`, reusing `days._DAYS`); presets like `weekends` are NOT valid flag tokens (D-03 says "Day tokens are the weekday abbreviations"). | Don't Hand-Roll | If the user wants `+weekends`, the grammar would need presets too. D-03 text supports abbrevs-only; low risk. |
| A5 | On-demand forecasts **share `ForecastCache`** (CONTEXT.md: "likely yes"). The cache key must distinguish a briefing lookup from a forecast lookup (and variant/flags) for the same location, or extend the cache to key on (location.id, command, variant, flags). | Standard Stack | If forecasts reuse the briefing cache key (location.id only), a `!weather` and a `!weekday-forecast` could collide. Planner must widen the cache key. Medium risk — flag explicitly. |

## Open Questions

1. **Scheduled-forecast exactly-once vs. fire-and-forget (A1).**
   - What we know: Briefings use `claim_slot` for exactly-once across restarts/overlaps; forecasts
     are read-only and the catch-up scan only enumerates `location.schedule` today.
   - What's unclear: Whether a missed scheduled forecast should be caught up / deduped at all.
   - Recommendation: v1 = fire-and-forget (no claim, no catch-up) for the cleanest FCAST-05
     "never writes the time series"; revisit only if the user reports duplicate/missed scheduled
     forecasts. Confirm in `/gsd-discuss-phase` or planning.

2. **`ForecastCache` key collision between weather/forecast/variant (A5).**
   - What we know: `ForecastCache` keys on `resolve_location(config, name).id` only.
   - What's unclear: Whether to extend the same cache (new composite key) or add a parallel cache.
   - Recommendation: Extend `ForecastCache.lookup` to accept a key suffix (command+variant+flags)
     so a `!weather` result and a `!weekday-forecast --compact +sat` result never collide, while
     repeated identical forecast commands within TTL still serve from memory.

3. **Compact-variant rain in the per-day line.** D-02 compact = "day label + high/low + a single
   sky condition word/icon" — rain% is NOT in compact. FCAST-01/02 require "per-day high/low, sky
   condition, and rain chance." These coexist because FCAST-01/02 describe the **detailed**
   default; compact intentionally drops rain.
   - Recommendation: Confirm the compact line excludes rain (per D-02) and that the detailed
     default carries the full FCAST-01/02 field set — no conflict, just make it explicit in the plan.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ stdlib (`datetime`/`zoneinfo`) | Window logic, labels, tz "today" | ✓ | 3.12+ | — |
| apscheduler | Forecast cron jobs | ✓ | 3.11.2 | — |
| httpx (existing One Call client) | Reused fetch (no new call) | ✓ | 0.28.1 | — |
| pydantic | ForecastSchedule model | ✓ | 2.13.4 | — |
| cachetools (ForecastCache) | On-demand TTL reuse | ✓ | 7.1.4 | — |
| OpenWeather One Call 3.0 `daily[]` | All per-day data (FCAST-07) | ✓ (already fetched) | 3.0 | — |
| pytest | Window/extraction/render/reconcile tests | ✓ | (dev) | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None. This phase adds no external dependency.

## Validation Architecture

Project config does not disable `nyquist_validation`, so this section applies.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing — `tests/` with `test_models.py`, `test_renderer.py`, `test_scheduler.py`) |
| Config file | pyproject.toml (project uses `uv`); no separate pytest.ini observed |
| Quick run command | `uv run pytest tests/test_multiday.py -x -q` (per new test file) |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FCAST-01 | Weekday (Mon–Fri) per-day hi/lo/sky/rain from editable template | unit | `uv run pytest tests/test_multiday.py -k weekday -x` | ❌ Wave 0 |
| FCAST-02 | Weekend (Fri–Sat–Sun) per-day from its own template | unit | `uv run pytest tests/test_multiday.py -k weekend -x` | ❌ Wave 0 |
| FCAST-03 | Detailed (default) vs compact variant selection | unit | `uv run pytest tests/test_forecast_render.py -k variant -x` | ❌ Wave 0 |
| FCAST-04 | `+day`/`-day` flags: append/drop, dedup, calendar-sort, out-of-window notice | unit | `uv run pytest tests/test_flags.py tests/test_multiday.py -k flag -x` | ❌ Wave 0 |
| FCAST-05 | On-demand both surfaces; zero store writes | unit + spy | `uv run pytest tests/test_forecast_lookup.py -k "no_store or readonly" -x` | ❌ Wave 0 (reuse Phase-6 store-spy pattern) |
| FCAST-06 | Per-location schedule slots register + reconcile churn-free | unit | `uv run pytest tests/test_scheduler.py -k forecast -x` | ⚠️ extend existing |
| FCAST-07 | Reuse `daily[]`, no extra fetch (assert client.fetch_onecall call count unchanged) | unit | `uv run pytest tests/test_forecast_lookup.py -k no_extra_fetch -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_multiday.py tests/test_forecast_render.py -x -q`
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_multiday.py` — window/roll-forward/horizon selection (FCAST-01/02/04); needs a
  **multi-day `daily[]` fixture** (current fixtures have `len(daily)==1` — VERIFIED). Build a
  synthetic 8-element `daily[]` fixture with known dates for deterministic window tests.
- [ ] `tests/test_forecast_render.py` — forecast token-set validation + detailed/compact render
  (FCAST-03); covers Pitfall 3 (feels-like hi/lo derivation) and Pitfall 5 (typo fails loud).
- [ ] `tests/test_flags.py` — shared `+day`/`-day`/`+compact` grammar (FCAST-04).
- [ ] `tests/test_forecast_lookup.py` — read-only no-store-write spy + no-extra-fetch assertion
  (FCAST-05/07); reuse the Phase-6 zero-store-writes spy harness.
- [ ] Extend `tests/test_scheduler.py` — forecast job register + reconcile no-op-churn + variant-edit
  ADD/REMOVE (FCAST-06).
- [ ] **8-element synthetic `daily[]` fixture** — the single most important Wave 0 asset; the
  existing fixtures only carry `daily[0]`.

## Security Domain

`security_enforcement` is not disabled; this section applies. This is a read-only,
no-new-secret, no-new-endpoint phase, so the surface is narrow.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth; on-demand commands ride the existing operator-id guard ladder (Phase 11/12) |
| V3 Session Management | no | No sessions |
| V4 Access Control | yes | Forecast commands MUST route through the Phase 12 registry behind the same operator-id / `!`-prefix / `author.bot` guard ladder (CMD-16 discipline) — no new bypass path |
| V5 Input Validation | yes | `+day`/`-day`/`+compact`/location flag parsing uses only `str` ops (mirror `parse_weather_command`'s no-`format`/`eval`/shell rule); fail-loud config validators for `ForecastSchedule` (kind/variant/time/days) |
| V6 Cryptography | no | None |
| V7 Error Handling/Logging | yes | Outcome-only logging (location/kind/variant/time) — never the appid/webhook/token (existing T-04-01 discipline); forecast template render errors fail loud at load, not at send |

### Known Threat Patterns for {Python forecast rendering + Discord + APScheduler}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Template injection via user-editable `.txt` | Tampering/EoP | Existing guarded `render()` — no `str.format`/`Formatter`/`eval`; only `{name}` whitelist substitution. Forecast line-format goes through the SAME `render`. |
| Markdown/mention injection in a forecast posted to Discord | Tampering | Forecast content is weather data + fixed labels; mirror `emit_online`'s no-`@everyone`/no-mention discipline. Location names come from validated config, not free user input. |
| Secret leakage (appid/webhook/token) in forecast logs/messages | Info Disclosure | Outcome-only logging (existing); the One Call URL is never logged (`httpx` logger pinned to WARNING in `client.py`). No forecast path constructs or logs the URL. |
| Forecast command failure stopping a scheduled briefing | DoS | Same failure isolation as CMD-16/D-11: on-demand handler in the non-propagating try/except; scheduled `fire_forecast_slot` body wrapped like `fire_slot` so one bad forecast can't kill the scheduler thread. |
| Config-driven forecast slot with malformed time/days/kind/variant | Tampering/DoS | Fail-loud pydantic validators at load + reload keep-old (rejected config never swaps) — same as `Schedule`. |

## Sources

### Primary (HIGH confidence)
- Codebase (read this session): `weatherbot/weather/models.py`, `templates/renderer.py`,
  `weatherbot/scheduler/daemon.py`, `weatherbot/config/models.py`, `weatherbot/interactive/lookup.py`,
  `weatherbot/interactive/bot.py`, `weatherbot/interactive/cache.py`, `weatherbot/interactive/command.py`,
  `weatherbot/scheduler/days.py`, `weatherbot/weather/client.py`, `weatherbot/cli.py`,
  `templates/briefing-*.txt` — the authoritative seam definitions.
- `tests/fixtures/onecall_imperial_clear.json` introspection — VERIFIED `daily[]` element shape
  and that current fixtures carry only `daily[0]` (`len(daily)==1`).
- `uv.lock` — VERIFIED versions: apscheduler 3.11.2, httpx 0.28.1, pydantic 2.13.4, cachetools 7.1.4.
- `.planning/phases/13-multi-day-forecast-templates/13-CONTEXT.md` — locked decisions (authoritative).
- `.planning/phases/12-command-registry-read-only-command-surface/12-CONTEXT.md` — registry seam.
- `.planning/REQUIREMENTS.md` (FCAST-01..07), `.planning/ROADMAP.md` (Phase 13), `.planning/STATE.md`.
- openweathermap.org/api/one-call-3 — One Call 3.0 `daily[]` field list + "8 days (today + 7)"
  horizon. [CITED]

### Secondary (MEDIUM confidence)
- CLAUDE.md technology stack section — version bands + "do NOT use APScheduler 4.x" + One Call 3.0
  decision (cross-confirmed against uv.lock).

### Tertiary (LOW confidence)
- None — all claims grounded in codebase reads, the One Call docs, or uv.lock.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; all versions verified from uv.lock and in production.
- Architecture: HIGH — every seam read directly; the renderer is already parameterized, the
  reconcile loop already keys on a stable id, the client already fetches full `daily[]`.
- Pitfalls: HIGH — window/horizon and feels-like-shape pitfalls verified against the One Call
  docs + fixture introspection; tz/exactly-once pitfalls grounded in existing codebase discipline.

**Research date:** 2026-06-18
**Valid until:** 2026-07-18 (stable — brownfield, no fast-moving external deps; the only external
surface is One Call 3.0's `daily[]` schema, which is stable)
