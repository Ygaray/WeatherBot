# Phase 3: Always-On Scheduler - Pattern Map

**Mapped:** 2026-06-10
**Files analyzed:** 13 (5 new, 8 modified)
**Analogs found:** 13 / 13 (every new/modified file has a concrete in-repo analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/scheduler/__init__.py` (NEW) | package init | — | `weatherbot/config/__init__.py` (barrel exports) / `weatherbot/weather/__init__.py` (docstring-only) | exact |
| `weatherbot/scheduler/days.py` (NEW) | utility (pure parser/validator) | transform | `weatherbot/weather/models.py` `_hints`/`_alert_line` (pure module funcs) + `Location._tz_must_be_real` (whitelist validation) | role-match |
| `weatherbot/scheduler/catchup.py` (NEW) | service (pure planner) | batch / transform | `Forecast.from_payloads` (pure builder, injected `now_utc`) + `store._local_date_iso` (tz-local-date math) | role-match |
| `weatherbot/scheduler/context.py` (NEW) | model (dataclass) | request-response | `weather/models.py` `@dataclass Forecast` + `channels/base.py` `@dataclass DeliveryResult` | exact |
| `weatherbot/scheduler/daemon.py` (NEW) | service (daemon orchestrator) | event-driven | `cli.send_now` (composition caller) + `cli.do_check` (orchestration with outcome-only logging) | role-match |
| `weatherbot/config/models.py` (MOD: + `Schedule`, `Location.schedule`) | model | CRUD (config load) | existing `Location`/`Config` (extra="forbid" + `field_validator`) | exact |
| `weatherbot/weather/store.py` (MOD: + `sent_log` table + `was_sent`/`record_sent`) | store/data | CRUD (idempotency) | existing `weather_onecall` `_SCHEMA` + `persist` (parameterized `?`, inline schema) | exact |
| `weatherbot/weather/models.py` (MOD: `Forecast.placeholders()`) | model | transform | existing `placeholders()` map + `{hint}`/`{alert}` empty-collapse keys | exact |
| `templates/renderer.py` (MOD: `CANONICAL` += 3 keys) | utility/config | transform | existing `CANONICAL` frozenset + `validate_template` | exact |
| `weatherbot/cli.py` (MOD: `--run` branch, thread `schedule_ctx`) | controller (CLI entry) | request-response | existing `--send-now`/`--check`/`--geocode` arg branches + `send_now` signature | exact |
| `templates/*.txt` (MOD: footer line) | template | — | existing `briefing-sectioned.txt`/`-compact.txt` (`{hint}`/`{alert}` trailing lines) | exact |
| `pyproject.toml` (MOD: + apscheduler) | config | — | existing `[project].dependencies` list | exact |
| `config.toml` / `config.example.toml` (MOD: `[[locations.schedule]]`) | config | — | existing `config.example.toml` `[[locations]]` blocks | exact |
| `tests/test_scheduler.py` (NEW) + extend `test_config`/`test_renderer`/`test_send_now` | test | — | `tests/test_send_now.py` (`_FakeClient`/`_FakeChannel`), `tests/test_store.py` (`tmp_db`), `tests/test_config.py` (inline TOML + `pytest.raises(ValidationError)`) | exact |

---

## Pattern Assignments

### `weatherbot/scheduler/__init__.py` (NEW — package init)

**Analog:** `weatherbot/config/__init__.py` (barrel) — copy this exact export style for the package's public API. Minimal alternative: `weatherbot/weather/__init__.py` is a one-line module docstring with no exports (use this if the scheduler package keeps its API internal).

Barrel pattern (`config/__init__.py` lines 1-21):
```python
"""Config package: non-secret models, secrets settings, and loaders."""

from .loader import (...)
from .models import Config, Location, WebhookIdentity
from .settings import Settings

__all__ = [ ... ]
```

> Decide: export `run_daemon`, `parse_days`, `plan_catchup`, `ScheduleContext` from the barrel (matches `config`), or keep a docstring-only `__init__` (matches `weather`) and import from submodules. Either is established here.

---

### `weatherbot/scheduler/days.py` (NEW — utility, pure validator/transform)

**Analog (validation discipline):** `weatherbot/config/models.py` `Location._tz_must_be_real` (lines 42-50) — delegate-to-stdlib, raise `ValueError` on a bad token. The RESEARCH `parse_days` (RESEARCH lines 246-268) wires INTO this same `field_validator` shape.

`_tz_must_be_real` (models.py lines 42-50):
```python
@field_validator("timezone")
@classmethod
def _tz_must_be_real(cls, v: str) -> str:
    # Let the stdlib own the IANA database (Don't Hand-Roll a zone list).
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"{v!r} is not a valid IANA timezone") from e
    return v
```

**Analog (module-level pure helper + whitelist set):** `weatherbot/weather/models.py` module functions `_hints` (lines 52-78) and `_alert_line` (lines 81-95) — `days.py`'s `parse_days` is the same shape: a top-level pure function with module-level constant sets (mirror the `_DAYS = {...}` / `_PRESETS = {...}` style against models.py's `_VALID_UNITS` at line 20).

Whitelist-set + ValueError pattern (`models.py` lines 20, 52-57):
```python
_VALID_UNITS = {"imperial", "metric"}
# ...
@field_validator("units")
@classmethod
def _units_valid(cls, v: str | None) -> str | None:
    if v is not None and v not in _VALID_UNITS:
        raise ValueError(f"units must be one of {sorted(_VALID_UNITS)}, got {v!r}")
    return v
```

> `parse_days` mirrors `_units_valid`: whitelist the tokens, `raise ValueError` with a `sorted(...)`-listed allowed set. Wire it into `Schedule`'s `days` `field_validator` so a bad token fails loud at load (D-02 / Phase 2 fail-at-load tradition).

---

### `weatherbot/scheduler/catchup.py` (NEW — service, pure planner)

**Analog (pure builder with injectable `now_utc`):** `Forecast.from_payloads` (`weather/models.py` lines 142-219) — the project's established "pure function, inject the clock for deterministic tests" pattern. `plan_catchup` copies the `now_utc: datetime | None = None` → `if now_utc is None: now_utc = datetime.now(timezone.utc)` idiom.

`from_payloads` clock-injection (models.py lines 148, 164-165):
```python
now_utc: datetime | None = None,
# ...
if now_utc is None:
    now_utc = datetime.now(timezone.utc)
```

**Analog (tz-local-date math, D-03 authoritative config tz):** `weatherbot/weather/store.py` `_local_date_iso` (lines 122-136) — IDENTICAL helper also lives at `weather/models.py` lines 34-49. Copy this exact ZoneInfo-with-UTC-fallback `.astimezone(tz).date().isoformat()` for the planner's "today local / scheduled_dt" computation.

`_local_date_iso` (store.py lines 122-136):
```python
def _local_date_iso(location: Location, now_utc: datetime) -> str:
    tz_name = getattr(location, "timezone", None)
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
    else:
        tz = timezone.utc
    return now_utc.astimezone(tz).date().isoformat()
```

> Note: this helper is ALREADY DUPLICATED in `store.py` and `models.py` — the planner should reuse it (import or copy), not add a third divergent copy. The `local_date` it produces IS the date component of the D-06 dedup key. The `MissedSlot` dataclass and `plan_catchup` signature in RESEARCH (lines 280-309) are the target shape; inject `was_sent` reader + `now_utc` for testability.

---

### `weatherbot/scheduler/context.py` (NEW — model, dataclass)

**Analog:** `channels/base.py` `DeliveryResult` (lines 23-34) — a small `@dataclass` with a defaulted field, used as a value object across a seam. Also `weather/models.py` `@dataclass Forecast` (line 98).

`DeliveryResult` (base.py lines 23-34):
```python
@dataclass
class DeliveryResult:
    ok: bool
    detail: str = ""
```

> `ScheduleContext` (RESEARCH lines 355-359: `scheduled_dt: datetime | None`, `tz: ZoneInfo`, `late: bool = False`) follows this exact dataclass-value-object pattern. Keep `from __future__ import annotations` at the top (every module here uses it) so `datetime | None` / `ZoneInfo` annotations are lazy.

---

### `weatherbot/scheduler/daemon.py` (NEW — service, daemon orchestrator)

**Analog (composition / orchestration + outcome-only logging):** `cli.do_check` (`cli.py` lines 193-256) and `cli.send_now` (lines 77-142) — these are the established "orchestrate the pipeline, log the OUTCOME only, never the key/URL" patterns (T-04-01). `fire_slot` is a NEW CALLER of `send_now` (the seam stays unchanged; daemon just invokes it per slot).

`send_now` outcome-only logging (cli.py lines 137-142):
```python
_log.info(
    "send_now complete",
    location=location.name,
    delivered=result.ok,
)
return result
```

structlog logger acquisition (cli.py line 46): `_log = structlog.get_logger(__name__)` — reuse verbatim. The D-10 schedule-announce logs `location=`, `time=`, `days=`, `next_run_time=` through this same `_log.info(...)` kwargs style — never the appid/webhook.

**Analog (injectable collaborators for tests):** `send_now`'s `client=None`/`channel=None` keyword injection (cli.py lines 99-106) — `run_daemon`/`fire_slot` should take the same injectable `client`/`channel` so `tests/test_scheduler.py` can drive firing with the existing `_FakeClient`/`_FakeChannel` (RESEARCH testing strategy line 589: "invoke the fire_slot job callback directly").

> The foreground `BackgroundScheduler` + `signal`/`KeyboardInterrupt` + `scheduler.shutdown(wait=False)` lifecycle (RESEARCH lines 444-468) has NO in-repo analog — this is the genuinely new code. Use the RESEARCH Code Example as the template; everything it CALLS (`send_now`, `_log`, `was_sent`/`record_sent`) is an existing seam.

---

### `weatherbot/config/models.py` (MOD — add `Schedule` model + `Location.schedule` field)

**Analog:** the existing `Location` class in the SAME file (lines 23-57) — copy its structure exactly.

`extra="forbid"` strictness (models.py line 34): `model_config = ConfigDict(extra="forbid")` — `Schedule` MUST use this (D-02, same strictness as `Location`).

Field-validator imports already present (models.py line 12): `from pydantic import BaseModel, ConfigDict, Field, field_validator` — no new imports needed except the `parse_days` import from the new `scheduler.days`.

Optional/defaulted field with default-factory list (models.py lines 40, 81-83):
```python
units: str | None = None          # optional field default
# ...
locations: list[Location]         # required list
template: str = DEFAULT_TEMPLATE
webhook: WebhookIdentity = Field(default_factory=WebhookIdentity)
```

> Add `schedule: list[Schedule] = Field(default_factory=list)` to `Location` (mirrors the `webhook = Field(default_factory=...)` pattern — keeps schedule-less locations valid). The `Schedule` model with `time`/`days`/`enabled` field validators is in RESEARCH lines 478-500. Watch the import ordering: `Schedule` must be defined (and `parse_days` imported) before `Location` references `list[Schedule]`, OR use a forward ref — `from __future__ import annotations` (line 8) is already present, so a forward-referenced `list[Schedule]` works with `Schedule` defined later in the file.

---

### `weatherbot/weather/store.py` (MOD — add `sent_log` table + `was_sent`/`record_sent`)

**Analog:** `weather_onecall` table DDL in `_SCHEMA` (lines 84-106) + `persist` (lines 139-179) — the exact idempotency/secret-hygiene discipline to copy.

DDL appended to `_SCHEMA` (the `CREATE TABLE IF NOT EXISTS` idempotent style, lines 84-92):
```sql
CREATE TABLE IF NOT EXISTS weather_onecall (
    id                INTEGER PRIMARY KEY,
    location_name     TEXT    NOT NULL,
    ...
);
```

Inline-schema-on-connect + parameterized `?` insert (persist lines 155-179):
```python
with sqlite3.connect(db_path) as conn:
    conn.executescript(_SCHEMA)          # idempotent; same discipline reused by was_sent/record_sent
    # ...
    conn.execute(
        "INSERT INTO weather_onecall (...) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (location.name, location.lat, ...),   # NEVER f-string into SQL (T-02-03 / SQLi)
    )
    conn.commit()
```

UTC-timestamp-int pattern (persist lines 146-147): `now_utc = datetime.now(timezone.utc); fetched_at = int(now_utc.timestamp())` — reuse for `sent_at_utc`.

> Add the `sent_log` DDL (with `UNIQUE(location_name, send_time, local_date)`, RESEARCH lines 318-327) to the `_SCHEMA` string so `init_db`/the existing `executescript(_SCHEMA)` calls create it for free. `was_sent`/`record_sent` (RESEARCH lines 329-347) each open `sqlite3.connect(db_path)`, `executescript(_SCHEMA)`, and use parameterized `?` exactly like `persist`. Use `INSERT OR IGNORE` against the UNIQUE key (the race backstop, D-07). The module guards "no network in this layer" — `test_store.py` line 113 asserts `not hasattr(store_mod, "httpx")`; keep the sent-log helpers httpx-free too.

---

### `weatherbot/weather/models.py` (MOD — extend `Forecast.placeholders()`)

**Analog:** `placeholders()` (lines 261-276) in the SAME file — the flat `str -> str` map. The `{hint}`/`{alert}` keys (lines 274-275) are the empty-collapse precedent `{schedule_note}` follows (D-13).

`placeholders()` map (models.py lines 261-276):
```python
def placeholders(self) -> dict[str, str]:
    return {
        "temp": self.temp_display,
        # ...
        "hint": self.hint,       # collapses to "" when no hint fires
        "alert": self.alert,     # collapses to "" when no alert
    }
```

> Per RESEARCH Open Question 2 (lines 540-543), the RECOMMENDED seam is to MERGE the 3 scheduler keys at the `send_now` call site (`{**forecast.placeholders(), **schedule_placeholders(...)}`) so `Forecast` stays weather-only — `{checked_at}` maps to the fetch timestamp the model already retains. If instead added here as empty-default keys, follow the `{hint}`/`{alert}` collapse style. EITHER way, `CANONICAL` (renderer.py) MUST gain all three. Note: `test_renderer.py::test_canonical_matches_forecast_placeholder_keys` (lines 107-110) asserts `CANONICAL == set(placeholders().keys())` EXACTLY — if the 3 keys are added to `CANONICAL` but merged at the call site (not in `placeholders()`), that test will break and MUST be updated to reflect the new seam.

---

### `templates/renderer.py` (MOD — `CANONICAL` += `sent_at`/`checked_at`/`schedule_note`)

**Analog:** the existing `CANONICAL` set (lines 36-49) + `validate_template` (lines 52-66) in the SAME file — the renderer engine and `_TOKEN` grammar (line 31) are unchanged (D-15: "Renderer engine itself unchanged").

`CANONICAL` set (renderer.py lines 36-49):
```python
CANONICAL = {
    "temp", "feels_like", "high", "low", "rain", "wind",
    "humidity", "conditions", "location", "date", "hint", "alert",
}
```

> Add `"sent_at"`, `"checked_at"`, `"schedule_note"` to this set so templates referencing them pass `validate_template` (D-15). No change to `validate_template`/`render` logic — they read `CANONICAL` by reference.

---

### `weatherbot/cli.py` (MOD — add `--run` branch + thread `schedule_ctx`)

**Analog (CLI flag branch):** the `--send-now`/`--geocode`/`--check` argparse args (lines 288-319) and their dispatch branches in `main` (lines 322-355). Add `--run` as a `store_true` flag exactly like `--check` (lines 306-314 / 328-333).

`--check` flag + dispatch (cli.py lines 306-314, 328-333):
```python
parser.add_argument(
    "--check",
    action="store_true",
    default=argparse.SUPPRESS,
    help=(...),
)
# ...
if hasattr(args, "check"):
    config = _load_config_reporting(args.config)
    if config is None:
        return 1
    settings = load_settings()
    return do_check(config=config, settings=settings)
```

**Analog (config-load-then-settings composition):** the `--send-now` branch (lines 339-361) — `_load_config_reporting` (clean fail, lines 259-277) → `load_settings()` → build `db_path` → call the orchestrator. `--run` follows the SAME sequence into `run_daemon(config=..., settings=..., db_path=...)`.

**Analog (render-boundary seam to extend, D-15):** `send_now`'s keyword-only signature (lines 77-86) and its single `render(...)` call (line 130: `text = render(template_text, forecast.placeholders())`). D-15 threads `schedule_ctx: ScheduleContext | None = None` into `send_now` and merges schedule placeholders at line 130; default `None` keeps manual `--send-now` rendering `{sent_at}`/`{checked_at}` with empty `{schedule_note}` (Pitfall 4, RESEARCH lines 430-434).

> `db_path.parent.mkdir(parents=True, exist_ok=True)` (cli.py lines 344-345) — reuse for `--run` so the sent-log DB dir exists before the daemon starts.

---

### `templates/*.txt` (MOD — add footer line)

**Analog:** the trailing `{hint}` / `{alert}` lines in `briefing-sectioned.txt` (lines 9-10) and `briefing-compact.txt` (lines 2-3) — the new footer line drops in the same way.

`briefing-sectioned.txt` tail (lines 8-10):
```text
🌧️ Rain: {rain}   💨 Wind: {wind}   💧 Humidity: {humidity}
{hint}
{alert}
```

> Add a footer like `— sent {sent_at} · weather checked {checked_at}` then `{schedule_note}` on its own line (RESEARCH lines 505-512) to all three starter templates. Per `test_renderer.py::test_compact_template_has_no_emoji` (lines 75-77), the footer added to `briefing-compact.txt` MUST stay emoji-free (the `·` middot is fine; avoid the `—`/emoji range the test's `_EMOJI` regex catches — verify against `[\U0001F300-\U0001FAFF☀-➿]`).

---

### `pyproject.toml` (MOD — add apscheduler)

**Analog:** the `[project].dependencies` list (lines 5-11) and `[dependency-groups].dev` (lines 13-17).

```toml
dependencies = [
    "discord-webhook>=1.4.1",
    "httpx>=0.28.1",
    "pydantic>=2.13.4",
    "pydantic-settings>=2.14.1",
    "structlog>=26.1.0",
]
```

> Add `"apscheduler>=3.11.2,<4"` to `dependencies` and (if a DST test needs OS-tz mocking) `"time-machine>=2.16"` to the `dev` group. Prefer `uv add` so `uv.lock` resolves (RESEARCH flags exact patch as `[ASSUMED]` pending real-registry resolution).

---

### `config.toml` / `config.example.toml` (MOD — add `[[locations.schedule]]`)

**Analog:** the existing `[[locations]]` blocks in `config.example.toml` (the `Home`/`Weekend` two-tz example with inline `#` comments documenting each field). Add nested `[[locations.schedule]]` array-of-tables under each location (D-01 shape in CONTEXT lines 44-60).

> Match the existing comment style (explain `time`/`days`/`enabled` + the preset vocabulary inline). The example already models the weekday-home/weekend-travel split (CONTEXT specifics lines 220-222) — give `Home` a `"mon-fri"` slot and `Weekend` a `"sat,sun"` slot. Note `test_config.py::test_example_config_loads_cleanly` (lines 315-320) loads this file, so the added blocks MUST validate against the new `Schedule` model.

---

### `tests/test_scheduler.py` (NEW) + extensions to `test_config`/`test_renderer`/`test_send_now`

**Analog (fakes for firing tests):** `tests/test_send_now.py` `_FakeClient` (lines 21-31) and `_FakeChannel` (lines 33-47) — copy these verbatim to drive `fire_slot` without network (RESEARCH line 589). `_FakeChannel.send_briefing` captures `sent_text`/`briefing_forecasts` and returns `DeliveryResult(ok=True)`.

`_FakeChannel` (test_send_now.py lines 33-47):
```python
class _FakeChannel:
    def __init__(self):
        from weatherbot.channels import DeliveryResult
        self.sent_text: list[str] = []
        self.briefing_forecasts: list[object] = []
        self._result = DeliveryResult(ok=True)
    def send_briefing(self, text, forecast):
        self.sent_text.append(text)
        self.briefing_forecasts.append(forecast)
        return self._result
```

**Analog (tmp DB fixture):** `tests/conftest.py` `tmp_db` (lines 26-33) and `load_fixture` (lines 20-23) — already shared; the sent-log idempotency tests use `tmp_db` directly (RESEARCH line 601: "tests/conftest.py already supplies tmp_db").

**Analog (inline-TOML config + fail-loud assertion):** `tests/test_config.py` `_write` helper (lines 31-34) + `pytest.raises(ValidationError)` (e.g. lines 240-243) — reuse for `test_multiple_schedule_entries` (SCHD-01) and `test_bad_days_fails_load` (SCHD-02).

**Analog (store assertions via `sqlite3.Row`):** `tests/test_store.py` `_connect` (lines 34-37) + row-count assertions (lines 67-78) — mirror for `was_sent`/`record_sent` and the UNIQUE-constraint double-fire test (SCHD-07).

**Analog (renderer/validate extension):** `tests/test_renderer.py::test_validate_template_rejects_non_canonical_token` (lines 90-93) and `test_canonical_matches_forecast_placeholder_keys` (lines 107-110) — extend to assert the 3 new placeholders validate (and update the `CANONICAL == keys` assertion if the keys merge at the call site rather than in `placeholders()`).

> Full Wave-0 test → requirement map is in RESEARCH lines 574-602. No new fixtures needed (config + sent-log built inline; weather fakes reuse existing One Call fixtures). Run command: `uv run pytest tests/test_scheduler.py -x -q`.

---

## Shared Patterns

### Pure-function-with-injected-clock (deterministic tests)
**Source:** `weather/models.py` `Forecast.from_payloads` (lines 148, 164-165)
**Apply to:** `scheduler/catchup.py::plan_catchup` (inject `now_utc`), `scheduler/days.py::parse_days` (no clock, but pure + validated)
```python
now_utc: datetime | None = None,
# ...
if now_utc is None:
    now_utc = datetime.now(timezone.utc)
```
This is the project's testability backbone — every pure scheduler unit injects its inputs (`now`, `was_sent` reader) so tests need no wall-clock sleep or global clock patch.

### Config-local-date math (D-03 authoritative IANA tz)
**Source:** `weather/store.py::_local_date_iso` (lines 122-136) — identical copy at `weather/models.py` lines 34-49
**Apply to:** `scheduler/catchup.py` (computing "today local" + the `local_date` dedup-key component), `scheduler/daemon.py` (announce/next-fire in location tz)
```python
tz = ZoneInfo(tz_name)   # with try/except → timezone.utc fallback
return now_utc.astimezone(tz).date().isoformat()
```
The configured `Location.timezone` is authoritative (NOT the API offset). Reuse the existing helper rather than introducing a third copy.

### Fail-loud-at-load via pydantic `field_validator`
**Source:** `config/models.py` `_tz_must_be_real` (lines 42-50) + `_units_valid` (lines 52-57)
**Apply to:** `Schedule.time` (`"HH:MM"` check) and `Schedule.days` (`parse_days` whitelist) validators
```python
@field_validator("days")
@classmethod
def _days(cls, v: str) -> str:
    parse_days(v)   # raises ValueError on a bad token (fail-loud, D-02)
    return v
```
`extra="forbid"` (line 34) on every config model — `Schedule` inherits this strictness.

### Parameterized SQL + inline idempotent schema + secret hygiene
**Source:** `weather/store.py::persist` (lines 155-179) + `_SCHEMA` `CREATE TABLE IF NOT EXISTS` (lines 84-106)
**Apply to:** `was_sent`/`record_sent` (sent-log), the `sent_log` DDL appended to `_SCHEMA`
```python
with sqlite3.connect(db_path) as conn:
    conn.executescript(_SCHEMA)              # idempotent schema on connect
    conn.execute("... WHERE x=? AND y=?", (a, b))   # never f-string into SQL
    conn.commit()
```
Only response payloads / non-secret keys are stored; never the appid or webhook URL (T-02-03). `test_store.py` line 113 asserts the store module has no `httpx` — keep the sent-log helpers network-free.

### Outcome-only structured logging
**Source:** `cli.py` `_log = structlog.get_logger(__name__)` (line 46) + `send_now` log (lines 137-142) + `do_check`/`do_geocode` error logs (never echo key/URL/params)
**Apply to:** `scheduler/daemon.py` (schedule-announce, per-fire outcome, catch-up decisions)
```python
_log.info("send_now complete", location=location.name, delivered=result.ok)
```
Log `location`/`time`/`days`/`next_run_time`/`delivered` — NEVER the `appid` or webhook URL (T-04-01). This is the first long-running process, so disciplined outcome-only logging matters most here.

### Empty-placeholder collapse (D-13)
**Source:** `weather/models.py` `{hint}`/`{alert}` keys (lines 274-275) + `templates/*.txt` standalone `{hint}`/`{alert}` lines + `test_renderer.py::test_empty_hint_and_alert_collapse_cleanly` (lines 128-136)
**Apply to:** `{schedule_note}` — empty string on on-time/manual sends, populated only on late recovery
```python
"hint": self.hint,     # "" collapses the line cleanly
"alert": self.alert,
# {schedule_note} follows the exact same empty-collapse contract
```

### Injectable collaborators for the composition root
**Source:** `cli.send_now` `client=None`/`channel=None` keyword injection (lines 99-106)
**Apply to:** `scheduler/daemon.py::run_daemon`/`fire_slot` (accept injectable `client`/`channel` so tests drive firing with `_FakeClient`/`_FakeChannel`)
```python
if client is None:
    if settings is None:
        raise ValueError("send_now requires either a client or settings")
    client = build_client(settings)
```

---

## No Analog Found

| File / Concern | Role | Data Flow | Reason | Planner Action |
|----------------|------|-----------|--------|----------------|
| `scheduler/daemon.py` — the `BackgroundScheduler` + `CronTrigger` registration loop + `signal`/`KeyboardInterrupt` + `scheduler.shutdown(wait=False)` foreground lifecycle | service | event-driven | No long-running process or APScheduler usage exists in the repo yet (this is Phase 3's defining new capability) | Use RESEARCH Pattern 1 (lines 207-236) and the `--run` lifecycle Code Example (lines 444-468) as the template. NOTE: everything the daemon *calls* (`send_now`, `_log`, store helpers) IS an existing seam — only the APScheduler wiring is net-new. |
| `scheduler/catchup.py::_fires_on` day-of-week match | utility | transform | No day-of-week / weekday-matching logic exists yet | Drive it from the SAME normalized `day_of_week` string the `CronTrigger` uses (Pitfall 3, RESEARCH lines 424-428) so planner and trigger never disagree; Monday-first (`date.weekday()`, Mon=0). |

> Both gaps are pure logic delegated to APScheduler + zoneinfo; RESEARCH provides concrete code examples. No file lacks BOTH an analog and a research example.

## Metadata

**Analog search scope:** `weatherbot/` (all subpackages: `cli.py`, `config/`, `weather/`, `channels/`), `templates/`, `tests/`, repo-root config + `pyproject.toml`
**Files scanned:** 14 source/template files fully read (cli.py, config/models.py, config/__init__.py, weather/store.py, weather/models.py, weather/__init__.py, channels/base.py, renderer.py, briefing-sectioned.txt, briefing-compact.txt) + 5 test files (conftest.py, test_send_now.py, test_config.py, test_store.py, test_renderer.py) + config.example.toml + pyproject.toml
**Pattern extraction date:** 2026-06-10
```
