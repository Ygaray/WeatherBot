# Phase 13: Multi-Day Forecast Templates - Pattern Map

**Mapped:** 2026-06-19
**Files analyzed:** 11 (4 new code modules, 4 new template files, 3 extended modules)
**Analogs found:** 11 / 11 (every file has an in-repo analog — pure brownfield extension)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/weather/models.py` — add `ForecastDay` | model | transform | `Forecast` (same file) | exact (same module, same dataclass/`_temp_str` discipline) |
| `weatherbot/weather/multiday.py` (NEW) | utility | transform | `weatherbot/scheduler/days.py` (pure, dep-free logic) | role-match (pure testable logic helper) |
| `templates/renderer.py` — add forecast token sets + per-day render helper | utility | transform | `validate_template`/`render`/`CANONICAL` (same file) | exact (already parameterized on `allowed`) |
| `templates/forecast-weekday-detailed.txt` (NEW) | config | request-response | `templates/briefing-sectioned.txt` | exact (editable `.txt` precedent) |
| `templates/forecast-weekday-compact.txt` (NEW) | config | request-response | `templates/briefing-compact.txt` | exact |
| `templates/forecast-weekend-detailed.txt` (NEW) | config | request-response | `templates/briefing-sectioned.txt` | exact |
| `templates/forecast-weekend-compact.txt` (NEW) | config | request-response | `templates/briefing-compact.txt` | exact |
| `weatherbot/interactive/commands/forecast.py` (NEW handler) | controller | request-response | `weatherbot/interactive/commands/weather_views.py` | exact (read-only `LookupResult`→`CommandReply` handler) |
| `weatherbot/interactive/lookup.py` — add forecast lookup path | service | request-response | `lookup_weather` (same file) | exact |
| `weatherbot/interactive/registry.py` — register forecast commands | config | event-driven | `COMMANDS`/`_wire_handlers` (same file) | exact |
| `weatherbot/interactive/command.py` — `+day`/`-day`/`+compact` flag grammar | utility | transform | `parse_command`/`parse_weather_command` (same file) | exact |
| `weatherbot/config/models.py` — add `ForecastSchedule` + `Location.forecast` | model | CRUD (config) | `Schedule` / `Location` (same file) | exact |
| `weatherbot/scheduler/daemon.py` — forecast jobs in register/reconcile/watch | service | event-driven | `_register_jobs`/`_desired_job_ids`/`fire_slot` (same file) | exact |
| `weatherbot/interactive/cache.py` — widen `ForecastCache` key (if shared) | service | request-response | `ForecastCache.lookup` (same file) | exact |

## Pattern Assignments

### `ForecastDay` in `weatherbot/weather/models.py` (model, transform)

**Analog:** `Forecast` dataclass + `from_payloads` + `_temp_str`, same file.

**Defensive `daily[i]` read pattern** (mirror `from_payloads` lines 167-219): use `.get() or {}` / `or []` everywhere; a present-but-null field returns `None`, so coalesce. `daily[i]` shape (RESEARCH-verified): `dt`, `sunrise`, `sunset`, `temp{min,max,day,night,eve,morn}`, `feels_like{day,night,eve,morn}` (NO `min`/`max` — Pitfall 3), `humidity`, `pop`, `uvi`, `weather[]`, `wind_speed`, `wind_deg`, `clouds`.

**Imperial-primary display — COPY VERBATIM** (lines 228-259):
```python
def _temp_str(self, imp: float, met: float) -> str:
    """Temperature display: primary value + label leads, secondary in parens."""
    if self.primary == "metric":
        return f"{round(met)}°C ({round(imp)}°F)"
    return f"{round(imp)}°F ({round(met)}°C)"
```
Reuse this exact body for per-day high/low/feels-high/feels-low so multi-day temps are byte-identical to the briefing. `high_display`/`low_display` (lines 248-259) show the `None`-guard fallback idiom.

**rain_chance / uvi extraction** (lines 180-181): `rain_chance = round((day_i.get("pop") or 0.0) * 100)`; `uvi_max = day_i.get("uvi") or 0.0`.

**feels-like high/low derivation (Pitfall 3 — NEW logic):** `feels_like` has only `day`/`night`/`eve`/`morn`. Derive `feels_high = max(feels_like.values())`, `feels_low = min(feels_like.values())`. Do NOT look for `feels_like.max` (KeyError).

**`placeholders()`-style flat map** (lines 261-276): `ForecastDay` should expose a per-day `dict[str,str]` keyed to `FORECAST_DAY_TOKENS_*` (the per-day-line token map), the same flat-`str→str` seam the renderer consumes.

---

### `weatherbot/weather/multiday.py` (NEW utility, transform — the genuinely new logic)

**Analog:** `weatherbot/scheduler/days.py` — a deliberately dependency-free pure module (no config/apscheduler import) so it can be imported without cycles and unit-tested in isolation.

**Pattern to copy:** module-level constants + a single pure function that fails loud on bad input. Reuse `days._DAYS` as the `+day`/`-day` token vocabulary (Don't Hand-Roll — one source of truth).

**Signature (RESEARCH Code Example):**
```python
def select_days(
    kind: str,               # "weekday" (mon-fri) | "weekend" (fri-sat-sun)
    today_local: date,       # via ZoneInfo(location.timezone)
    daily: list[dict],       # raw daily[] (today + up to 7)
    add: set[str],           # {"sat"} from +sat (reuse days._DAYS tokens)
    drop: set[str],          # {"mon"} from -mon
) -> tuple[list[int], list[str]]:  # (in-window indices in calendar order, out-of-window notices)
```

**Critical (Pitfall 1):** never index `daily[]` positionally by day-of-week math. Resolve each desired calendar date → index by matching the LOCAL date of each `daily[i].dt` (convert `dt` UTC → `ZoneInfo(location.timezone)` date), mirroring the `_local_date_iso` discipline in `models.py` lines 34-49. Desired dates with no matching in-window entry become `{notice}` strings (Pitfall 2), never silent drops.

**tz "today" (Pitfall 6):** compute `today_local` via `ZoneInfo(location.timezone)`, NOT `date.today()` or the API `timezone` field — same authority rule as `_local_date_iso`.

---

### `templates/renderer.py` — forecast token sets + per-day render helper (utility, transform)

**Analog:** `validate_template`/`render`/`CANONICAL`, same file.

**Existing parameterized signature — extend, do not rewrite** (lines 58, 75):
```python
def validate_template(template_text: str, allowed: set[str] = CANONICAL) -> None: ...
def render(template_text: str, values: dict) -> str: ...  # guarded {name} substitution only
```

**Add two token scopes** (RESEARCH Pattern 1) — keep them DISTINCT from `CANONICAL`:
```python
FORECAST_TOKENS = {"location", "title", "range_label", "days", "footer_note", "notice"}
FORECAST_DAY_TOKENS_DETAILED = {
    "label", "high", "low", "sky", "rain", "wind", "uvi",
    "feels_high", "feels_low", "sunrise", "sunset",
}
FORECAST_DAY_TOKENS_COMPACT = {"label", "high", "low", "sky"}
```

**Code-rendered per-day block (RESEARCH Pattern 2 — NO template logic):**
```python
def render_forecast(template_text, line_fmt, days, header_values, day_allowed):
    validate_template(line_fmt, allowed=day_allowed)            # fail-loud per-day tokens
    block = "\n".join(render(line_fmt, d) for d in days)        # code iteration, no template logic
    values = {**header_values, "days": block}
    validate_template(template_text, allowed=FORECAST_TOKENS)   # fail-loud header/footer tokens
    return render(template_text, values)
```
The `{days}` token is the code-built block merged in at the call site — the SAME merge-in idiom as `schedule_placeholders` (lookup.py line 140). Anti-pattern: never add `str.format`/Jinja2/loops to a template — `render`'s docstring (renderer.py lines 1-18) forbids it; `_TOKEN` (line 31) deliberately won't match `{x.attr}`/`{x[0]}`/`{0}`.

---

### `templates/forecast-*.txt` (NEW config files, request-response)

**Analog:** `templates/briefing-sectioned.txt` (detailed) and `templates/briefing-compact.txt` (compact).

**briefing-sectioned.txt** structure to mirror (header with `{location}`/`{date}`, body lines, footer with `— sent {sent_at}`):
```
☀️ WEATHER — {location}
{date}
...
{hint}
{alert}
— sent {sent_at} · weather checked {checked_at}
{schedule_note}
```

Forecast templates own the header/footer + a single per-day line-format string (tokens from `FORECAST_TOKENS` / `FORECAST_DAY_TOKENS_*`). RESEARCH A3 recommends a sibling `*.line.txt` file carrying the per-day line-format (reuses `load_template` unchanged) — planner's discretion (CONTEXT D-06).

---

### `weatherbot/interactive/commands/forecast.py` (NEW controller, request-response)

**Analog:** `weatherbot/interactive/commands/weather_views.py` — the read-only handler module.

**Module contract to copy** (weather_views.py lines 1-25): handler takes a `LookupResult` (carrying `.forecast` with `raw_onecall_imp` + resolved `.location`), reads off the ALREADY-FETCHED payload (never a second fetch), imports NOTHING from `weatherbot.weather.store`, returns a surface-agnostic `CommandReply`.

**`_tz_for` helper** (line 88): `ZoneInfo(result.location.timezone)` — reuse for day-label/sun formatting.

**Handler signature pattern** (line 92 `alerts`, line 181 `next_cloudy` for the extra-arg case):
```python
def weekday_forecast(result: LookupResult, ...) -> CommandReply:
    raw = result.forecast.raw_onecall_imp or {}   # already-fetched daily[]
    tz = _tz_for(result)
    # call multiday.select_days(...) + build ForecastDay per index + render_forecast(...)
    return CommandReply(title=..., text=rendered)  # or lines=(...)
```
`CommandReply` shape: `title` + optional `lines: tuple[(name,value),...]` + optional free-form `text` (commands/__init__.py lines 21-35). For a rendered multi-line forecast, use `text=` (like `help`).

**Day labels (D-04, Pitfall 6 — NEW):** "Today"/"Tomorrow" for the first two days from the local-date diff, then explicit f-string `f"{abbr} {dt.month}/{dt.day}"` (NOT `strftime("%-m/%-d")` — glibc-specific; RESEARCH State of the Art).

---

### `weatherbot/interactive/lookup.py` — forecast lookup path (service, request-response)

**Analog:** `lookup_weather` (same file).

**Read-only constraint (lines 12-21):** the forecast path takes NO `db_path`, imports nothing from the store, writes none of the seven store functions. HARD constraint FCAST-05.

**Dual-fetch + reuse already-fetched `daily[]`** (lines 115-123): the existing call already fetches the full payload (FCAST-07 = free). A forecast lookup either reuses an existing `LookupResult.forecast.raw_onecall_imp` or runs the same `client.fetch_onecall(location, "imperial"/"metric")` pair — no new endpoint, no `client.py` change.

**Template validate-at-load boundary** (lines 125-131): `load_template(...)` then `validate_template(...)` BEFORE render — for forecasts pass the forecast token set (Pitfall 5: a typo aborts loudly at load, not at send).

**Lazy `build_client` import inside `client is None`** (lines 104-113): copy this cli↔interactive cycle-break.

---

### `weatherbot/interactive/registry.py` — register forecast commands (config, event-driven)

**Analog:** `_SPECS`/`_wire_handlers`/`COMMANDS`, same file.

**Add specs to the `_SPECS` tuple** (lines 50-63) with a "Forecast" `group`; `takes_location=True`:
```python
CommandSpec("weekday-forecast", "Forecast", "Multi-day weekday (Mon-Fri) forecast.", True),
CommandSpec("weekend-forecast", "Forecast", "Multi-day weekend (Fri-Sat-Sun) forecast.", True),
```
**Wire handlers LAZILY in `_wire_handlers`** (lines 66-89) — add `import ... forecast` inside the function and a `handlers[...]` entry. Keeps registry import acyclic. Longest-keyword-first ordering (`COMMANDS_BY_KEYWORD_LEN_DESC`, lines 100-102) handles `weekday-forecast` vs any prefix automatically. The new commands appear on BOTH CLI and Discord with no other edit (derive-from-one-list).

**Heterogeneous handler args:** `next-cloudy` already shows the extra-arg precedent — both CLI (`cli.py` lines 602-605) and Discord (`bot.py` lines 227-230) special-case `spec.name == "next-cloudy"` to pass `config.cloud_threshold`. Forecast handlers need flags (variant/add/drop) threaded the same way — the dispatch sites special-case by `spec.name`.

---

### `weatherbot/interactive/command.py` — `+day`/`-day`/`+compact` grammar (utility, transform)

**Analog:** `parse_command` / `parse_weather_command`, same file.

**Security contract — COPY** (lines 8-15, 96-100): parse-don't-validate; ONLY `str.strip`/`str.casefold`/slicing; NEVER `str.format`/`eval`/`exec`/shell. Word-boundary guard requires whitespace after the keyword.

**Frozen result dataclass pattern** (lines 76-87 `ParsedCommand`): return a frozen dataclass carrying the parsed flags (e.g. `variant: str`, `add: frozenset[str]`, `drop: frozenset[str]`, `location: str | None`). Token vocabulary for `+day`/`-day` = `weatherbot.scheduler.days._DAYS` (A4 — abbreviations only; presets like `weekends` are NOT valid flag tokens).

---

### `weatherbot/config/models.py` — `ForecastSchedule` + `Location.forecast` (model, CRUD)

**Analog:** `Schedule` model (lines 31-79) and `Location` (lines 82-135).

**`Schedule` patterns to copy VERBATIM:**
- `model_config = ConfigDict(extra="forbid", frozen=True)` (line 45) — REQUIRED for `ConfigHolder` snapshot compatibility.
- `_hhmm` time validator (lines 51-61), `_days_valid` via `parse_days` (lines 63-69), `parsed_time()` (lines 71-74), `day_of_week` property (lines 76-79) — reuse identically.

**New `ForecastSchedule` (RESEARCH — separate model, NOT extending `Schedule`):**
```python
class ForecastSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str            # "weekday" | "weekend"   (field_validator: one of {...})
    variant: str = "detailed"   # "detailed" | "compact"  (field_validator like _units_valid)
    time: str            # reuse Schedule._hhmm validator
    days: str            # reuse parse_days
    enabled: bool = True
    # parsed_time() / day_of_week identical to Schedule
```
Use the `_units_valid` enum-validator idiom (lines 130-135) for `kind`/`variant`.

**On `Location`** (line 107 shows `schedule: list[Schedule] = Field(default_factory=list)`):
```python
forecast: list[ForecastSchedule] = Field(default_factory=list)
```
`default_factory=list` → an absent `[[locations.forecast]]` table loads as empty (zero migration). Keep `frozen=True` so `ConfigHolder` stays snapshot-compatible.

---

### `weatherbot/scheduler/daemon.py` — forecast jobs (service, event-driven)

**Analog:** `_register_jobs` (lines 389-448), `_desired_job_ids` (lines 451-465), `fire_slot` (lines 131+), `_derive_watch_dirs`/`_make_watch_filter` (lines 872-917).

**Briefing job id (lines 444, 461):** `f"{location.name}|{slot.time}|{slot.days}"`.

**Forecast job id — NAMESPACE it (RESEARCH Pattern 3, Pitfall 4):** factor a single shared helper called by BOTH enumeration sites so they can never drift:
```python
def _forecast_job_id(location, fc) -> str:
    return f"{location.name}|fc|{fc.kind}|{fc.variant}|{fc.time}|{fc.days}"
```
The `|fc|` namespace prevents collision with a briefing at the same time/days (anti-pattern — would silently replace the briefing job).

**Add a second loop in BOTH `_register_jobs` (after line 448) and `_desired_job_ids` (after line 464):**
```python
for fc in location.forecast:
    if not fc.enabled:
        continue
    # _register_jobs: scheduler.add_job(fire_forecast_slot, trigger=CronTrigger(
    #     hour=hh, minute=mm, day_of_week=fc.day_of_week, timezone=location.timezone),
    #     id=_forecast_job_id(location, fc), replace_existing=replace_existing,
    #     misfire_grace_time=None, coalesce=True, kwargs={holder, db_path, settings, ...})
    # _desired_job_ids: ids.add(_forecast_job_id(location, fc))
```
`_reconcile_jobs` (lines 468-518) needs NO body change — it excludes only `__heartbeat__` and reconciles any id in `_desired_job_ids` (add/remove/unchanged automatically). A variant edit → different id → one ADD + one REMOVE.

**`fire_forecast_slot` callback (RESEARCH Pattern 4 — mirror `fire_slot` MINUS store writes):** copy `fire_slot`'s try/except failure-isolation envelope (lines 163-173) and single-snapshot read (lines 181-186), but NO `claim_slot`/`release_claim`/store write (FCAST-05; A1 recommends no-claim, no-catchup for v1). Wrap the whole body so one bad forecast can't kill the scheduler thread.

**Watch sets (Pitfall 5, lines 872-917):** `_derive_watch_dirs` and `_make_watch_filter` both iterate `{config.template}` today — ADD the forecast template filenames to those sets so editing a forecast template triggers a reload and is watched. Also add forecast templates to `validate_config_and_templates` (loader.py) so a bad one is rejected at load/reload.

---

### `weatherbot/interactive/cache.py` — widen `ForecastCache` key (service, request-response; if shared per A5)

**Analog:** `ForecastCache.lookup` (lines 82-108), same file.

**Current key (line 93):** `key = resolve_location(config, name).id` — location-only. A `!weather` and a `!weekday-forecast --compact +sat` would COLLIDE (A5, Open Question 2). Extend the key to a composite suffix `(location.id, command, variant, flags)` so repeated identical forecast commands still hit cache but distinct commands never collide.

**Lock discipline to preserve (lines 95-108):** Lock held ONLY around the dict get/store; `lookup_weather` network fetch runs OUTSIDE the lock. `invalidate()` (lines 110-114) is the config-reload hook.

---

## Shared Patterns

### Read-only discipline (FCAST-05 — HARD constraint)
**Source:** `weatherbot/interactive/lookup.py` lines 12-21; `weatherbot/interactive/commands/weather_views.py` lines 4-7.
**Apply to:** `forecast.py` handler, the forecast lookup path, `fire_forecast_slot`.
No `db_path` for writing, no import from `weatherbot.weather.store`, write none of the store functions. Proven by the Phase-6 zero-store-writes spy harness (reuse for `tests/test_forecast_lookup.py`).

### Guarded template rendering (injection-safe, fail-loud)
**Source:** `templates/renderer.py` lines 31, 58-87.
**Apply to:** all four forecast templates + the per-day line-format.
`_TOKEN` whitelist substitution only — no `str.format`/`Formatter`/`eval`. `validate_template(text, allowed=...)` at the load boundary aborts on a typo'd token before any send (Pitfall 5).

### Frozen, fail-loud config models
**Source:** `weatherbot/config/models.py` — every model is `ConfigDict(extra="forbid", frozen=True)` with `field_validator`s that raise at load.
**Apply to:** `ForecastSchedule`. Keeps `ConfigHolder` snapshot compatibility and rejects bad `kind`/`variant`/`time`/`days` at load/reload (keep-old).

### IANA-tz "today" authority
**Source:** `weatherbot/weather/models.py` `_local_date_iso` lines 34-49; reused in `weather_views._epoch_local` (line 59).
**Apply to:** `multiday.select_days` window math + day labels.
`ZoneInfo(location.timezone)` is authoritative — never `date.today()` or the API `timezone` field (Pitfall 6).

### Day-of-week vocabulary (one source of truth)
**Source:** `weatherbot/scheduler/days.py` `_DAYS` (line 25), `parse_days` (lines 28-48).
**Apply to:** `ForecastSchedule.days` validation AND the `+day`/`-day` flag grammar. Don't hand-roll a second mon..sun set.

### Derive-from-one-list registry (CLI + Discord parity)
**Source:** `weatherbot/interactive/registry.py` `_SPECS`/`COMMANDS`; consumed by `cli.py` lines 794-805 (subparser gen) and `bot.py` lines 199-239 (dispatch).
**Apply to:** forecast commands — add to `_SPECS` once; both surfaces pick them up. The `next-cloudy` extra-arg special-casing (cli.py 602-605, bot.py 227-230) is the precedent for threading forecast flags through dispatch.

### Failure isolation envelope
**Source:** `fire_slot` try/except (daemon.py lines 163-173); CLI `_run_registry_command` envelope (cli.py lines 593-615); Discord `on_message` envelope (bot.py).
**Apply to:** `fire_forecast_slot` and the forecast handler — a bad forecast must never crash the scheduler thread or leak a raw traceback / secret.

## No Analog Found

None. Every file in this phase extends or mirrors an existing in-repo seam — this is a fully brownfield phase (RESEARCH: "~80% wiring existing seams, ~20% new pure logic"). The only genuinely-new module, `weatherbot/weather/multiday.py`, has a structural analog in `scheduler/days.py` (a pure, dependency-free, fail-loud logic helper).

## Metadata

**Analog search scope:** `weatherbot/weather/`, `weatherbot/interactive/`, `weatherbot/interactive/commands/`, `weatherbot/config/`, `weatherbot/scheduler/`, `templates/`.
**Files scanned:** 13 read (models.py, renderer.py, lookup.py, registry.py, status.py, weather_views.py, days.py, config/models.py, command.py, cache.py, daemon.py [targeted], cli.py [targeted], briefing-sectioned.txt, commands/__init__.py).
**Pattern extraction date:** 2026-06-19
