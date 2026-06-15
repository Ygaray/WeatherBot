# Phase 6: Shared Lookup Core & Command Parser - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 7 (5 new, 2 modified)
**Analogs found:** 7 / 7 (every new/modified file has a strong in-repo analog)

This phase is a **pure-Python internal refactor + two new leaf modules** — every
seam already exists and is tested. The dominant instruction is *copy, don't
invent*: the read-only core is the head of `send_now` lifted verbatim; the value
objects copy the established `@dataclass` house style; the tests reuse the
existing `FakeClient`/`load_fixture`/`tmp_db` harness unchanged.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/interactive/__init__.py` | package barrel | n/a | `weatherbot/config/__init__.py` | exact |
| `weatherbot/interactive/lookup.py` (`lookup_weather` + `LookupResult` + `UnknownLocationError`) | service (read-only core) | request-response / transform | `weatherbot/cli.py::send_now` (head) + `scheduler/context.py::ScheduleContext` (dataclass) | exact (lifted head) |
| `weatherbot/interactive/command.py` (`parse_weather_command` + `Command` + `CommandKind`) | utility (pure parser) | transform | `scheduler/context.py` (dataclass + enum-less module) + `channels/base.py::DeliveryResult` (frozen value object) | role-match (no parser exists yet) |
| `weatherbot/cli.py` (`send_now` delegates; `resolve_location` raise upgrade is in `config/loader.py`) | service (composition root) | request-response | itself (current `send_now`) — preserve byte-identical | exact (in-place refactor) |
| `weatherbot/config/loader.py` (`resolve_location` raises `UnknownLocationError`) | service (resolver) | transform | current `resolve_location` (L40-56) | exact (in-place, backward-compatible) |
| `tests/test_lookup.py` | test | request-response | `tests/test_send_now.py` | exact |
| `tests/test_command.py` | test | transform | `tests/test_renderer.py` (pure-logic unit test idiom) | role-match |

## Pattern Assignments

### `weatherbot/interactive/lookup.py` — `lookup_weather` (service, read-only core)

**Primary analog:** `weatherbot/cli.py::send_now` (L113-162). The read-only HEAD
(resolve → dual fetch → build Forecast → load/validate template → render) is
lifted into `lookup_weather`; the deliver+persist TAIL stays in `send_now`.

**The exact chain to extract** (`weatherbot/cli.py` L113-162):
```python
location = resolve_location(config, location_name)            # L113

if client is None:                                            # L115-118 — keep this injectable guard
    if settings is None:
        raise ValueError("send_now requires either a client or settings")
    client = build_client(settings)

onecall_imp = client.fetch_onecall(location, "imperial")      # L129  <-- dual fetch (FCST-04/DATA-03)
onecall_met = client.fetch_onecall(location, "metric")        # L130

primary = location.units or "imperial"                        # L132  <-- CR-01 display primary
forecast = Forecast.from_payloads(                            # L133-135
    location, onecall_imp, onecall_met, primary=primary
)

if templates_dir is not None:                                 # L139-142 — keep this injectable guard
    template_text = load_template(config.template, templates_dir)
else:
    template_text = load_template(config.template)
validate_template(template_text)                              # L143

text = render(                                                # L156-162  <-- single render site
    template_text,
    {
        **forecast.placeholders(),
        **schedule_placeholders(schedule_ctx, sent_dt, checked_dt),  # <-- schedule half STAYS in send_now
    },
)
```

**Imports to copy** (from `cli.py` L39-51 — note the import style):
```python
from weatherbot.config import resolve_location           # already exported by config/__init__
from weatherbot.weather.models import Forecast
from templates.renderer import load_template, render, validate_template
# build_client / _WeatherClient: import LAZILY inside lookup_weather to avoid the
# cli <-> interactive cycle (Pitfall 3) — see "Import-cycle" under Shared Patterns.
```

**`Forecast.from_payloads` signature** (`weather/models.py` L143-150) — call it exactly as `send_now` does:
```python
Forecast.from_payloads(loc, onecall_imp, onecall_met, primary=primary)  # primary kw, both payloads always read
```

**Injectable-seam pattern to mirror** (the `client is None` / `settings is None`
guard at `cli.py` L115-118) — `lookup_weather` reproduces this so offline tests
inject a `FakeClient` and never need real secrets:
```python
if client is None:
    if settings is None:
        raise ValueError("lookup_weather requires either a client or settings")
    from weatherbot.cli import build_client   # LAZY import (cycle break, Pitfall 3 / matches cli.py L478)
    client = build_client(settings)
```

**`extra_placeholders` merge seam** (RESEARCH Pattern 1, Option A — the
byte-identical mechanic): `lookup_weather` renders at one site; `send_now` passes
its `schedule_placeholders(...)` dict through so the merge ORDER
(`{**forecast.placeholders(), **extra}`) is preserved exactly:
```python
values = dict(forecast.placeholders())
if extra_placeholders:
    values.update(extra_placeholders)   # schedule keys layer ON TOP — same order as cli.py L158-161
text = render(template_text, values)
return LookupResult(text=text, forecast=forecast, location=location)
```

**Read-only guard (D-06):** `lookup_weather` takes NO `db_path` and imports
NOTHING from `weatherbot.weather.store`. The `persist(db_path, location, forecast)`
call at `cli.py` L176-177 is the line that MUST NOT be carried along.

---

### `weatherbot/interactive/lookup.py` — `LookupResult` (value object)

**Analog:** `weatherbot/scheduler/context.py::ScheduleContext` (L29-43) — the house
`@dataclass` value-object style. Also mirrors the `channel.send_briefing(text,
forecast)` pairing (`channels/base.py` L52) by bundling `.text` + `.forecast`.

```python
# scheduler/context.py L29-43 — copy this dataclass style
@dataclass
class ScheduleContext:
    scheduled_dt: datetime | None
    tz: ZoneInfo
    late: bool = False
```

`LookupResult` (recommended shape — D-05):
```python
@dataclass
class LookupResult:
    text: str          # rendered v1 briefing — P7 prints this
    forecast: Forecast  # structured — P11 builds an embed from this WITHOUT re-fetching
    location: Location  # the resolved Location
```

---

### `weatherbot/interactive/lookup.py` — `UnknownLocationError` (typed exception)

**Analog:** the `ValueError` raise in `config/loader.py::resolve_location` (L55-56),
whose message already builds the valid-names list:
```python
known = ", ".join(loc.name for loc in config.locations)   # loader.py L55
raise ValueError(f"No location named {name!r}; configured locations: {known}")  # L56
```

**Pattern (D-07 — subclass `ValueError`, carry the list as an attribute so neither
surface re-derives it):**
```python
class UnknownLocationError(ValueError):
    def __init__(self, requested: str, valid_names: list[str]) -> None:
        self.requested = requested
        self.valid_names = valid_names
        known = ", ".join(valid_names)
        super().__init__(f"No location named {requested!r}; configured locations: {known}")
```
Subclassing `ValueError` keeps every existing `except ValueError` (in `do_check`,
`run_send_now`, `assert_unique_names` callers) green — non-regression (Pitfall 5).

---

### `weatherbot/interactive/command.py` — `parse_weather_command` (pure parser)

**Analog:** `scheduler/context.py` (a small pure-logic module with a `@dataclass` +
module-level helpers and no I/O) and `channels/base.py::DeliveryResult` (frozen
value object). No parser exists yet — this is the only genuinely-new logic.

**House style to copy:** one small `@dataclass(frozen=True)` + a tiny `enum.Enum`
tag (matches `DeliveryResult`/`ScheduleContext` preference for one value object
over a `Union` of three classes — RESEARCH "Alternatives Considered").

**Recommended shape (RESEARCH Pattern 2 — D-01/02/03/04):**
```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

_KEYWORD = "weather"

class CommandKind(Enum):
    NOT_A_COMMAND = "not_a_command"
    DEFAULT = "default"            # bare `weather` → default location
    LOCATED = "located"           # `weather <loc>` → named location

@dataclass(frozen=True)
class Command:
    kind: CommandKind
    location: str | None = None   # raw name for LOCATED; None otherwise

def parse_weather_command(text: str) -> Command:
    stripped = (text or "").strip()
    if not stripped.casefold().startswith(_KEYWORD):     # keyword matched case-insensitively (D-04)
        return Command(CommandKind.NOT_A_COMMAND)
    rest = stripped[len(_KEYWORD):]
    if rest and not rest[0].isspace():                   # word-boundary guard (Pitfall 2): "weatherman" → NOT_A_COMMAND
        return Command(CommandKind.NOT_A_COMMAND)
    location = rest.strip()                              # everything after keyword, trimmed; RAW case preserved (D-04)
    if not location:
        return Command(CommandKind.DEFAULT)
    return Command(CommandKind.LOCATED, location=location)
```

**Critical conventions (from CONTEXT/RESEARCH, enforce in code + tests):**
- Do NOT lowercase the extracted location — only the keyword is case-insensitive; `resolve_location` casefolds later (D-04, RESEARCH Validation note).
- Do NOT validate the name against config (parse-don't-validate, D-01) — no `Config` import in this module.
- Keep the word-boundary guard so `weatherman` / `weathervane` / `"weather: 72°F"` → `NOT_A_COMMAND` (Pitfall 2, the briefing-feedback-loop guard).
- No `str.format` / `eval` / shell — pure `strip`/`casefold`/slice only (Security V5 non-regression).

---

### `weatherbot/cli.py` — `send_now` refactor (modify in place, byte-identical)

**Analog:** the current `send_now` itself (L90-184). Only the read-only HEAD
changes — it becomes a `lookup_weather(...)` call; the deliver+persist TAIL is
NOT touched (D-08, criterion #4).

**Preserve EXACTLY (the untouched tail, `cli.py` L164-184):**
```python
result = channel.send_briefing(text, forecast)           # L167  <-- now (result_lr.text, result_lr.forecast)
if result.ok:
    persist(db_path, location, forecast)                 # L176-177  <-- (db_path, result_lr.location, result_lr.forecast)
_log.info("send_now complete", location=location.name, delivered=result.ok)  # L179-183
return result
```

**Schedule-timing computation STAYS in `send_now`** (`cli.py` L153-155) and is
passed via `extra_placeholders` (RESEARCH Pattern 1):
```python
tz = schedule_ctx.tz if schedule_ctx is not None else ZoneInfo(location.timezone)  # L153
sent_dt = datetime.now(tz); checked_dt = datetime.now(tz)                          # L154-155
# pass schedule_placeholders(schedule_ctx, sent_dt, checked_dt) as extra_placeholders=
```
Open Question 1 (RESEARCH L401, A2): recommendation is `lookup_weather` computes
its own location-local `sent_at`/`checked_at` for on-demand reads so a bare lookup
matches a manual `--send-now`; `send_now` overrides them via `extra_placeholders`
for the scheduled path. Planner confirms.

**New import for `send_now` (the D-08 cycle edge — `cli` becomes a consumer of `interactive`):**
```python
from weatherbot.interactive import lookup_weather   # top-level here is fine; the lazy import is on the lookup side
```

---

### `weatherbot/config/loader.py` — `resolve_location` raise upgrade (modify in place)

**Analog:** current `resolve_location` (L40-56). RESEARCH recommendation (Open
Question 3, A-option in D-07): upgrade the raise to `UnknownLocationError` so the
daemon/`--check`/`--send-now` paths all get the richer error for free. Backward-
compatible because `UnknownLocationError` IS-A `ValueError`.

Change only the final raise (L55-56):
```python
known = [loc.name for loc in config.locations]
raise UnknownLocationError(name, known)   # was: raise ValueError(f"No location named ...")
```
(`UnknownLocationError` lives in `interactive/lookup.py`; importing it into
`config/loader.py` is a `config → interactive` edge — verify no cycle since
`interactive/command.py`/`lookup.py` import `config`, not the reverse-at-module-load.
If a cycle appears, keep the raise in `loader.py` as `ValueError` and have
`lookup_weather` wrap it — the alternative D-07 option.)

---

### `tests/test_lookup.py` (test — reuse the existing harness)

**Analog:** `tests/test_send_now.py` (L24-49 fakes + L52-99 happy path) and
`tests/conftest.py` (`load_fixture`, `tmp_db`). Copy `_FakeClient` verbatim;
`_FakeChannel` is NOT needed (`lookup_weather` never delivers).

**`_FakeClient` to copy** (`test_send_now.py` L24-33):
```python
class _FakeClient:
    def __init__(self, onecall_imp, onecall_met):
        self._onecall = {"imperial": onecall_imp, "metric": onecall_met}
        self.onecall_calls: list[str] = []
    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._onecall[units]
```

**Config construction to copy** (`test_send_now.py` L59-70) — `Config`/`Location`/
`WebhookIdentity` from `weatherbot.config`, template `"briefing-sectioned.txt"`,
fixtures `onecall_imperial_clear.json` / `onecall_metric_clear.json`.

**Tests to write (RESEARCH Validation → Test Map):**
- **Criterion #1 (happy path):** assert `result.text` contains `"New York"` + `"°F"`; `result.forecast.location == "New York"`; `result.location.name == "New York"`; `client.onecall_calls == ["imperial", "metric"]` (dual-fetch).
- **Criterion #1 (metric-primary):** reuse the Berlin `units="metric"` config from `test_send_now.py` L189-201; assert `result.forecast.temp_display == "20°C (68°F)"`.
- **Criterion #2 (zero store writes):** `monkeypatch.setattr` each of the seven `weatherbot.weather.store` write functions (`persist`, `claim_slot`, `record_alert`, `resolve_alert`, `stamp_tick`, `stamp_success`, `stamp_health`) to raise `AssertionError`; run `lookup_weather`; assert it completes. Belt-and-suspenders: run against `tmp_db` and assert row counts are 0.
- **D-07 (`test_unknown_location_error`):** `lookup_weather("Nowhere", ...)` raises `UnknownLocationError`; `isinstance(err, ValueError)` is True; `err.valid_names` lists configured names; an `except ValueError` still catches it.

---

### `tests/test_command.py` (test — pure, no fixtures)

**Analog:** `tests/test_renderer.py` (L1-45) for the pure-logic unit-test idiom
(`from __future__ import annotations`, direct import, plain `assert`). No
`load_fixture`/`tmp_db` needed — the parser is config-free and I/O-free.

> Note: the repo has NO existing `pytest.mark.parametrize` usage. Parametrizing
> the matrix is fine and idiomatic, but a simple loop or one test per case also
> matches the existing plain-`assert` style — planner's call.

**Full matrix to cover** (RESEARCH Validation, criterion #3):

| Input | Expected `kind` | Expected `location` |
|-------|-----------------|---------------------|
| `"weather"` | DEFAULT | None |
| `"weather home"` | LOCATED | `"home"` |
| `"weather New York"` | LOCATED | `"New York"` |
| `"weather   home  "` | LOCATED | `"home"` (trimmed) |
| `"Weather HOME"` | LOCATED | `"HOME"` (raw case preserved) |
| `"WEATHER"` | DEFAULT | None |
| `"hello"` | NOT_A_COMMAND | None |
| `""` | NOT_A_COMMAND | None |
| `"  "` | NOT_A_COMMAND | None |
| `"weatherman"` | NOT_A_COMMAND | (word-boundary guard) |
| `"weather: 72°F today"` | NOT_A_COMMAND | (briefing-shaped, boundary guard) |

---

### `weatherbot/interactive/__init__.py` (package barrel)

**Analog:** `weatherbot/config/__init__.py` (L1-22) — every package re-exports its
public surface with an explicit `__all__`.

```python
# config/__init__.py L1-21 — copy this barrel style
from .loader import (assert_unique_names, load_config, load_settings, resolve_location)
from .models import Config, Location, WebhookIdentity
from .settings import Settings
__all__ = ["Config", "Location", ...]
```

`interactive/__init__.py` re-exports:
```python
from .command import Command, CommandKind, parse_weather_command
from .lookup import LookupResult, UnknownLocationError, lookup_weather
__all__ = ["Command", "CommandKind", "LookupResult", "UnknownLocationError",
           "lookup_weather", "parse_weather_command"]
```

## Shared Patterns

### Injectable test seam (client / settings)
**Source:** `weatherbot/cli.py` L115-118 (`send_now`).
**Apply to:** `lookup_weather`.
```python
if client is None:
    if settings is None:
        raise ValueError("<fn> requires either a client or settings")
    client = build_client(settings)   # lazy import in lookup.py
```
Tests inject a `FakeClient` so the import never runs and no real secret is needed.

### Import-cycle break (lazy / function-level import)
**Source:** `weatherbot/cli.py` L478 (`from weatherbot.scheduler import daemon`
INSIDE `main`, because `daemon` imports `send_now`) and `scheduler/__init__.py`
(PEP-562 lazy `__getattr__`).
**Apply to:** `interactive/lookup.py` — `from weatherbot.cli import build_client`
must be INSIDE the `if client is None:` branch (Pitfall 3, RESEARCH A3). `cli.py`
top-level `from weatherbot.interactive import lookup_weather` is then safe because
the only `cli → interactive` resolution at runtime is the function-level one.

### Dataclass value-object house style
**Source:** `scheduler/context.py` L29-43 (`ScheduleContext`), `channels/base.py`
L23-34 (`DeliveryResult`).
**Apply to:** `LookupResult` (plain `@dataclass`), `Command` (`@dataclass(frozen=True)`).

### Guarded renderer reuse (CMD-05 / Security V5 non-regression)
**Source:** `templates/renderer.py` L58 `validate_template`, L75 `render`, L90
`load_template`; `CANONICAL` set L36-55 (already includes `sent_at`/`checked_at`/
`schedule_note`, so no validation drift whether or not those keys are merged).
**Apply to:** `lookup_weather` — call `load_template → validate_template → render`
exactly as `send_now` does. Never `str.format`/`eval`. `render` leaves
unknown-but-canonical tokens visible (its documented behavior).

### Outcome-only logging (T-04-01)
**Source:** `cli.py` L179-183, L253, L289-291 — log location/outcome, never the
`appid` or webhook URL.
**Apply to:** any logging in `lookup_weather` (keep outcome-only); the `_WeatherClient`
already holds the key internally and never logs it.

### Byte-identical regression gate (criterion #4)
**Source:** `tests/test_send_now.py` (all four tests) — they assert the rendered
body content, dual-fetch order, metric-primary `temp_display`, schedule-note
rendering, and persist row count. Do NOT modify them; they must stay green
unchanged after the delegation.

## No Analog Found

None. Every new/modified file has a strong in-repo analog. The only genuinely-new
logic is the ~15-line pure `parse_weather_command`, whose value-object + module
shape still copies the established `@dataclass`/`enum` house style.

## Metadata

**Analog search scope:** `weatherbot/` (cli, config, scheduler, channels, weather),
`templates/`, `tests/`.
**Files scanned:** ~14 source modules + 14 test files (full source/test inventory listed).
**Pattern extraction date:** 2026-06-15
**Read directly this session:** `cli.py`, `config/loader.py`, `config/__init__.py`,
`scheduler/context.py`, `channels/base.py`, `templates/renderer.py` (L36-94),
`weather/models.py` (L143-177), `tests/conftest.py`, `tests/test_send_now.py`,
`tests/test_renderer.py` (L1-45).
</content>
</invoke>
