# Phase 6: Shared Lookup Core & Command Parser - Research

**Researched:** 2026-06-15
**Domain:** Internal Python refactor — extracting a read-only fetch→render core and a pure command parser from a shipped v1.0 codebase (no third-party integration)
**Confidence:** HIGH (every seam verified against the live code in this session; no external API surface to verify)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01: Parse, don't validate.** `parse_weather_command()` decides only "is this a `weather` command?" and extracts the raw location string. It does NOT check the name against configured locations — that is `lookup_weather`'s job. Keeps the parser config-free and trivially unit-testable; preserves a distinct downstream "unknown location" signal (CMD-04).
- **D-02: Three-state result.** `NotACommand` (input isn't a weather command → Discord bot ignores it) | bare-command "use default location" (e.g. `Command(location=None)`) | `Command(location="<raw name>")`. The three states are the contract; exact type name/shape is the planner's call.
- **D-03: Input is the full command text** including the `weather` keyword (inputs are `weather`, `weather <loc>`, garbage). Both surfaces feed raw text → identical semantics.
- **D-04: Location extraction = everything after the `weather` keyword, trimmed; matched case-insensitively.** `weather   New York ` → `"New York"`. Multi-word configured names work without quoting. No first-token-only truncation.
- **D-05: `lookup_weather` returns a small `LookupResult`** bundling `.text` (rendered v1 briefing string), `.forecast` (structured `Forecast`), `.location` (resolved `Location`). P7 uses `.text`; P11 builds a richer embed from `.forecast` without re-fetching. Mirrors the existing `channel.send_briefing(text, forecast)` pairing.
- **D-06: Read-only is absolute.** `lookup_weather` writes NONE of: `weather_onecall` (`persist`), `sent_log` (`claim_slot`), `alerts` (`record_alert`/`resolve_alert`), `heartbeat` (`stamp_tick`/`stamp_success`), `health` (`stamp_health`). Enforced by test (criterion #2). Otherwise reuses v1 behavior exactly: dual imperial+metric fetch, `units` override leads display, exact v1 template (FCST-04 / CR-01 / CMD-05).
- **D-07: `lookup_weather` raises a typed `UnknownLocationError(ValueError)`** carrying the requested name + the list of valid configured location names. P7 (stderr + non-zero exit) and P11 (channel message) each format CMD-04 their own way; the valid-names list travels with the error. Subclassing `ValueError` keeps existing `resolve_location`/`send_now` behavior + tests green.
- **D-08: `send_now` delegates to `lookup_weather()`.** `send_now` calls the read-only core for fetch→render, then runs its EXISTING send + persist tail on the returned `LookupResult` (`.forecast`, `.text`). One read-only core, zero duplicated fetch/render logic. Only the read-only HEAD of `send_now` changes; the delivery + `persist` ordering that underpins exactly-once is NOT touched. Byte-identical output is the acceptance bar (criterion #4 + existing `tests/test_send_now.py`).

### Claude's Discretion
- Exact module/type names and where `LookupResult` + `UnknownLocationError` live within `weatherbot/interactive/`.
- `lookup_weather`'s injectable seams for tests — mirror `send_now`'s injectable `client`/`settings`/`templates_dir`.
- Whether `resolve_location` itself is upgraded to raise `UnknownLocationError` (backward-compatible via the `ValueError` subclass) or `lookup_weather` wraps it.
- Precise signature/keyword args of `lookup_weather` and `parse_weather_command`.

### Deferred Ideas (OUT OF SCOPE)
- **Short-TTL fetch cache (CMD-06)** — Phase 11 wraps `lookup_weather` with caching. No caching seam baked into the Phase 6 core.
- **Discord embed formatting** — Phase 11 consumes `LookupResult.forecast`; Phase 6 only guarantees the structured forecast is available on the return.
- **Geocoded / arbitrary-city lookup (CMD-V2-02)** — out of v1.1; the parser stays configured-locations-only.
</user_constraints>

<phase_requirements>
## Phase Requirements

Phase 6 is a **foundation phase — it closes no requirement** (per REQUIREMENTS.md traceability). It builds the two seams that downstream phases consume to close their requirements. The mapping below is therefore "which downstream requirement each Phase 6 deliverable enables," not "which requirement this phase completes."

| ID | Description | Research Support (Phase 6 deliverable that enables it) |
|----|-------------|--------------------------------------------------------|
| CMD-01 (P7) | `weather [location]` CLI prints a briefing, no daemon | `lookup_weather().text` is the printable body; `parse_weather_command` parses argv |
| CMD-02 (P11) | `weather [location]` in Discord returns an in-channel reply | `lookup_weather` (text + forecast) + `parse_weather_command` (raw message text) |
| CMD-03 (P7) | bare `weather` → default/primary location | `parse_weather_command("weather")` → `Command(location=None)`; `resolve_location(config, None)` → `config.locations[0]` |
| CMD-04 (P7) | unknown location → clear error listing valid names, no geocoding | `UnknownLocationError(ValueError)` carries requested name + valid-names list (D-07) |
| CMD-05 (P7) | on-demand reply reuses the exact v1 template/format | `lookup_weather` reuses `load_template` + `validate_template` + `render` + `Forecast.placeholders()` unchanged |
| CMD-06 (P11) | short-TTL cache | Phase 6 leaves `lookup_weather` cache-free; P11 wraps it (deferred) |
| CMD-07 (P11) | bot ignores non-commands / its own posts | `parse_weather_command` returns `NotACommand` for garbage — the parser half of the feedback-loop guard |

**No requirement is CLOSED by Phase 6.** Verification is against the ROADMAP's 4 success criteria, not a requirement ID.
</phase_requirements>

## Summary

Phase 6 is a **pure-Python internal refactor plus two new leaf modules** in a brand-new `weatherbot/interactive/` package. There is **no third-party integration, no network surface, no new dependency, and no external environment requirement.** Everything the phase needs already exists and is shipped in v1.0: `resolve_location`, `fetch_onecall` (via the injectable `_WeatherClient`), `Forecast.from_payloads`, `load_template`/`validate_template`/`render`, and a complete recorded-fixture test harness.

The phase has exactly three moving parts: (1) extract the **read-only head** of `send_now` (resolve → dual fetch → build Forecast → validate template → render) into `lookup_weather`, returning a `LookupResult(text, forecast, location)`; (2) write a **pure parser** `parse_weather_command` with a three-state result; (3) prove `send_now` stays **byte-identical** by delegating to `lookup_weather` and keeping the existing send + persist tail untouched, with the existing `tests/test_send_now.py` as the regression gate.

The single genuine design subtlety — flagged correctly in CONTEXT — is **where the `schedule_placeholders` / `schedule_ctx` merge lives.** In the current code (cli.py L153–162) that merge happens at the `render(...)` call site inside `send_now`. The recommendation below keeps that timing/scheduler concern **inside `send_now`'s tail, NOT inside `lookup_weather`**, because (a) `lookup_weather` is for on-demand reads that have no scheduler context, and (b) folding `schedule_ctx` into the read-only core would couple the shared interactive seam to the scheduler — the exact coupling `scheduler/context.py` was written to avoid.

**Primary recommendation:** `lookup_weather` does resolve → fetch → build `Forecast` → `load_template` → `validate_template` → `render(template_text, forecast.placeholders())` and returns `LookupResult(text, forecast, location)`. `send_now` calls `lookup_weather` for the resolve/fetch/build/validate, then **re-renders** with the schedule placeholders merged for the scheduled path — OR (preferred, byte-identical-safe) `lookup_weather` accepts an optional `extra_placeholders: Mapping[str,str] | None = None` that is merged at its single render site, and `send_now` passes the `schedule_placeholders(...)` dict through. See Pattern 1 for the exact mechanic and why the second option is the safer one for criterion #4.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Parse raw command text → intent | New `interactive/command.py` (pure logic) | — | Config-free, surface-agnostic; both CLI argv and Discord message feed it (D-01/D-03) |
| Resolve a config location name → `Location` | `config/loader.py::resolve_location` (existing) | `interactive/lookup.py` (caller) | Already does case-insensitive match + default; reuse verbatim, optionally upgrade its raise type (D-07) |
| Fetch One Call (dual unit) | `weather/client.py` via injectable `_WeatherClient` (existing) | `interactive/lookup.py` (caller) | The read-only core is just the existing fetch chain; no new client |
| Build normalized `Forecast` | `weather/models.py::Forecast.from_payloads` (existing) | `interactive/lookup.py` (caller) | Unchanged; `lookup_weather` calls it exactly as `send_now` does today |
| Render briefing text | `templates/renderer.py::render` (existing) | `interactive/lookup.py` (caller) | Exact v1 template + placeholders (CMD-05); read-only core owns the call |
| Merge scheduler timing placeholders | `send_now` tail (existing call site) | — | Scheduler concern; MUST stay out of the read-only core to avoid coupling |
| Deliver + persist | `send_now` tail + `weather/store.py` (existing) | — | Untouched by Phase 6; the read-only core never touches the store (D-06) |
| Signal "unknown location" to surfaces | `UnknownLocationError(ValueError)` in `interactive/` | both P7 & P11 | Typed error carries valid-names list so neither surface re-derives it (D-07) |

## Standard Stack

**No new packages.** This phase adds zero dependencies. Everything is stdlib + the already-installed dev tools.

### Core (already installed — verified in pyproject.toml)
| Library | Version (pyproject) | Purpose in this phase | Why standard |
|---------|---------------------|------------------------|--------------|
| Python stdlib `dataclasses` | 3.12 builtin | `LookupResult` value object; the existing `Forecast` and `ScheduleContext` are both `@dataclass` | House style — every value object in this codebase is a `@dataclass` (`Forecast`, `ScheduleContext`, `DeliveryResult`) |
| Python stdlib `enum` / `dataclasses` | 3.12 builtin | Parser three-state result | Pure-stdlib; no library needed for a 3-state tagged value |
| pytest | 9.0.3 (dev) | Unit tests for both new modules + regression guard | Existing test framework; `tests/` already uses it |
| ruff | 0.15.16 (dev) | Lint + format the two new modules | Project's single lint/format tool (`uv run ruff`) |

### Supporting (existing modules the new code imports — verified)
| Module | Symbol | Purpose |
|--------|--------|---------|
| `weatherbot.config` | `resolve_location`, `Config`, `Location` | Resolve a name to a `Location` (loader.py L40) |
| `weatherbot.cli` | `build_client`, `_WeatherClient` | Build the injectable fetch client from `Settings` (cli.py L85) |
| `weatherbot.weather.models` | `Forecast` | `Forecast.from_payloads(loc, imp, met, primary=...)` (models.py L142) |
| `templates.renderer` | `load_template`, `validate_template`, `render` | The exact v1 fetch→render chain (renderer.py L58/75/90) |
| `weatherbot.config.settings` | `Settings` | Injectable secret source (mirrors `send_now`) |

### Alternatives Considered (for the parser result type)
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single dataclass with a state enum | Three distinct classes / `typing.Union` | More types to import at both surfaces; the codebase favors one small dataclass (see `DeliveryResult`, `ScheduleContext`) |
| `enum.Enum` for the three states | bare string literals | Strings are stringly-typed; enum gives exhaustiveness + IDE help. Recommend a small `enum` |
| `NamedTuple` | `@dataclass` | Both work; `@dataclass` matches every other value object here. Recommend `@dataclass` for consistency |

**Installation:** None. `uv sync` already provides everything. No `uv add`.

## Package Legitimacy Audit

**Not applicable — this phase installs no external packages.** Zero `uv add` calls. All imports are Python stdlib or already-vendored first-party modules verified present in `pyproject.toml` (`apscheduler`, `discord-webhook`, `httpx`, `pydantic`, `pydantic-settings`, `structlog`, `tenacity`) and the dev group (`pytest`, `ruff`, `time-machine`). No registry lookup, slopcheck, or postinstall audit is required.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
   raw command text  ──▶ │  parse_weather_command(text)            │  (interactive/command.py)
   ("weather NYC",       │   - case-insensitive "weather" prefix?  │   PURE: no config, no I/O
    "weather",           │   - extract trailing text, trim         │
    "hello")             └───────────────┬─────────────────────────┘
                                          │
                         NotACommand ─────┼───── Command(location=None)
                          (ignore)        │       Command(location="NYC")
                                          ▼
        (P7 CLI / P11 bot map Command.location ──▶ name | None)
                                          │
                                          ▼  name | None
   ┌──────────────────────────────────────────────────────────────────────┐
   │  lookup_weather(name, *, config, settings|client, templates_dir)      │ (interactive/lookup.py)
   │     resolve_location(config, name) ──[no match]──▶ UnknownLocationError│  READ-ONLY
   │            │                                        (ValueError,       │  NEVER touches store
   │            ▼                                         valid_names=[...]) │
   │     client.fetch_onecall(loc,"imperial")                              │
   │     client.fetch_onecall(loc,"metric")   ◀── 2 calls (FCST-04)        │
   │            ▼                                                           │
   │     Forecast.from_payloads(loc, imp, met, primary=loc.units|imperial) │
   │            ▼                                                           │
   │     load_template → validate_template → render(text, placeholders)    │
   │            ▼                                                           │
   │     return LookupResult(text, forecast, location)                     │
   └────────────────────────┬─────────────────────────────────────────────┘
                             │
          ┌──────────────────┴───────────────────┐
          ▼                                       ▼
   P7 CLI: print(result.text)            send_now tail (cli.py, UNCHANGED ordering):
   P11 bot: embed from result.forecast     merge schedule_placeholders → channel.send_briefing
                                            ──[result.ok]──▶ persist(weather_onecall)
```

The **read-only core writes nothing**; the only path that touches the store is `send_now`'s existing tail after a successful delivery (D-06 / criterion #2).

### Recommended Project Structure
```
weatherbot/
├── interactive/              # NEW package (does not exist yet)
│   ├── __init__.py           # re-export lookup_weather, LookupResult,
│   │                         #   UnknownLocationError, parse_weather_command,
│   │                         #   Command (+ state enum) — mirror config/__init__.py style
│   ├── lookup.py             # lookup_weather() + LookupResult + UnknownLocationError
│   └── command.py            # parse_weather_command() + Command (+ CommandKind enum)
tests/
├── test_lookup.py            # NEW — read-only core (criterion #1, #2)
├── test_command.py           # NEW — parser matrix (criterion #3)
└── test_send_now.py          # EXISTING — byte-identical regression gate (criterion #4)
```

**Package `__init__.py` convention (verified against `config/__init__.py`, `ops/__init__.py`):** every package here re-exports its public surface in `__init__.py` with an explicit `__all__`. Follow it: `from weatherbot.interactive import lookup_weather, parse_weather_command, LookupResult, UnknownLocationError`.

> **Import-cycle caution (verified real in this codebase):** `weatherbot/scheduler/__init__.py` documents and uses PEP-562 lazy `__getattr__` specifically to avoid a `daemon → ops → config` cycle, and `cli.py` imports `daemon` *inside* a function for the same reason (cli.py L478). If `lookup.py` imports `build_client`/`_WeatherClient` from `weatherbot.cli`, and `weatherbot.cli` later imports `lookup_weather` from `weatherbot.interactive` (D-08 makes it a consumer), that is a **direct import cycle**. See Pitfall 3 for the mitigation (the client-builder lives in `cli.py`; `lookup.py` should take an injected `client`/`settings` and import `build_client` lazily, or `build_client` should move to a neutral module).

### Pattern 1: Extract the read-only head, keep the scheduler merge in `send_now` (criterion #4 mechanic)

**What:** `lookup_weather` owns resolve → fetch → build → validate → render. `send_now` keeps delivery + persist + the scheduler-timing merge.

**The subtle part (verified at cli.py L153–162):** the current `send_now` render call merges TWO dicts:
```python
text = render(template_text, {**forecast.placeholders(), **schedule_placeholders(schedule_ctx, sent_dt, checked_dt)})
```
`schedule_placeholders` supplies `{sent_at}`, `{checked_at}`, `{schedule_note}`. The on-demand `lookup_weather` path has **no `ScheduleContext`** — it is a manual read. There are two viable ways to keep `send_now` byte-identical:

**Option A (RECOMMENDED — `extra_placeholders` seam):** `lookup_weather` renders at one site and accepts an optional merge dict:
```python
def lookup_weather(name, *, config, settings=None, client=None, templates_dir=None,
                   extra_placeholders: Mapping[str, str] | None = None) -> LookupResult:
    location = resolve_location(config, name)   # may raise UnknownLocationError (D-07)
    if client is None:
        if settings is None:
            raise ValueError("lookup_weather requires either a client or settings")
        client = build_client(settings)         # lazy import — see Pitfall 3
    onecall_imp = client.fetch_onecall(location, "imperial")
    onecall_met = client.fetch_onecall(location, "metric")
    primary = location.units or "imperial"
    forecast = Forecast.from_payloads(location, onecall_imp, onecall_met, primary=primary)
    template_text = (load_template(config.template, templates_dir)
                     if templates_dir is not None else load_template(config.template))
    validate_template(template_text)
    values = dict(forecast.placeholders())
    if extra_placeholders:
        values.update(extra_placeholders)       # schedule keys layer ON TOP, exactly as today
    text = render(template_text, values)
    return LookupResult(text=text, forecast=forecast, location=location)
```
`send_now` then becomes:
```python
result_lr = lookup_weather(location_name, config=config, settings=settings, client=client,
                           templates_dir=templates_dir,
                           extra_placeholders=schedule_placeholders(schedule_ctx, sent_dt, checked_dt))
# ... build channel, then the UNCHANGED tail:
result = channel.send_briefing(result_lr.text, result_lr.forecast)
if result.ok:
    persist(db_path, result_lr.location, result_lr.forecast)
```
Because the merge order (`{**placeholders, **schedule}`) is preserved exactly via `values.update(extra_placeholders)`, and `validate_template` runs on the same `config.template`, the rendered bytes are identical. The **canonical placeholder set in `renderer.py` already includes** `sent_at`/`checked_at`/`schedule_note`, so `validate_template` does not reject a template using them whether or not they were merged — no validation drift. On-demand callers pass nothing → those three keys are simply absent from `values` → the renderer leaves any `{sent_at}` token visible (its documented behavior), exactly as it would have rendered an on-demand briefing with no scheduler.

> **Decision needed (Open Question 1):** whether an on-demand briefing template containing `{sent_at}` should render the token literally (renderer leaves unknown-but-canonical tokens visible) or whether `lookup_weather` should always supply `sent_at`/`checked_at` for a manual read (the way `send_now` does for manual `--send-now` via `schedule_placeholders(None, ...)`). Recommendation: have `lookup_weather` itself compute the location-local `sent_at`/`checked_at` the same way the manual `--send-now` path does today (cli.py L153–155: `tz = ZoneInfo(location.timezone)`, `datetime.now(tz)`), so an on-demand briefing matches a manual `--send-now` briefing. Then `send_now` for the SCHEDULED path overrides via `extra_placeholders`. This keeps both surfaces' default output consistent and is the cleaner seam.

**Option B (re-render in `send_now`):** `lookup_weather` returns text rendered with weather-only placeholders; `send_now` discards `.text` and re-renders with the merge. Rejected — it duplicates the render call and the load/validate, defeating "one source of truth" (D-08), and risks the two render sites drifting.

**When to use:** Option A for this phase.

### Pattern 2: Pure three-state command parser

**What:** `parse_weather_command(text: str) -> Command` with three outcomes (D-02). House style favors one small `@dataclass` + an `enum` tag (matching `DeliveryResult`/`ScheduleContext`).

**Example (recommended shape):**
```python
# interactive/command.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

_KEYWORD = "weather"

class CommandKind(Enum):
    NOT_A_COMMAND = "not_a_command"
    DEFAULT = "default"          # bare `weather` → default/primary location
    LOCATED = "located"          # `weather <loc>` → named location

@dataclass(frozen=True)
class Command:
    kind: CommandKind
    location: str | None = None  # None for NOT_A_COMMAND and DEFAULT; raw name for LOCATED

def parse_weather_command(text: str) -> Command:
    """Parse-don't-validate (D-01): classify text, extract the raw location string.

    Does NOT check the name against configured locations (that is lookup_weather's
    job, D-01) — keeps this surface-agnostic and config-free (D-03).
    """
    stripped = (text or "").strip()
    lowered = stripped.casefold()
    if not lowered.startswith(_KEYWORD):
        return Command(CommandKind.NOT_A_COMMAND)
    rest = stripped[len(_KEYWORD):]
    # Require a word boundary after the keyword so "weathervane" is NOT a command.
    if rest and not rest[0].isspace():
        return Command(CommandKind.NOT_A_COMMAND)
    location = rest.strip()
    if not location:
        return Command(CommandKind.DEFAULT)
    return Command(CommandKind.LOCATED, location=location)
```
**Decision needed (Open Question 2 — word boundary):** D-04 says "everything after the `weather` keyword, trimmed." The matrix in CONTEXT does not include `weathervane`/`weatherman`. The snippet above adds a word-boundary guard so `weatherman` is `NOT_A_COMMAND` (the conservative, feedback-loop-safe reading — see Pitfall 2 in PITFALLS.md about loose substring matching). Confirm with the planner whether the guard is wanted; if D-04 is read literally as "any string starting with `weather`," drop the boundary check. **Recommend keeping the boundary guard** — it is strictly safer for the P11 Discord surface and costs one line + one test.

### Anti-Patterns to Avoid
- **Folding `schedule_ctx`/`schedule_placeholders` into `lookup_weather`.** That couples the shared read-only core to the scheduler — the exact coupling `scheduler/context.py` documents itself as avoiding (it merges at the call site precisely so `Forecast` stays weather-only). Keep scheduler timing in `send_now`'s tail / passed via `extra_placeholders`.
- **Validating the location name inside the parser.** Violates D-01 and erases the distinct "unknown location" signal CMD-04 needs.
- **`lookup_weather` returning a bare `str`.** Violates D-05; P11 would have to re-fetch to build an embed.
- **Re-rendering in `send_now` (Option B).** Duplicates load/validate/render → drift risk → defeats single-source-of-truth (D-08).
- **First-token truncation in the parser.** Multi-word configured names (`New York`) must survive (D-04).
- **Catching the `UnknownLocationError` inside `lookup_weather`.** It must propagate so each surface formats CMD-04 its own way (D-07).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Name → `Location` resolution | A second case-insensitive matcher | `resolve_location` (loader.py L40) | Already does casefold match + `None`→default + a clear raise; reuse verbatim |
| Template placeholder substitution | `str.format` / f-string interpolation | `render()` (renderer.py L75) | The guarded regex renderer is a deliberate security choice (T-03-02 no format-string injection); on-demand must reuse it (CMD-05) |
| Template validation | Re-deriving the allowed token set | `validate_template()` + `CANONICAL` | Single source of the canonical set; already includes the schedule keys |
| Dual-unit forecast normalization | Re-parsing One Call JSON | `Forecast.from_payloads(..., primary=...)` | Handles partial payloads, alerts-absent, tz-local date, display rounding (FCST-04/CR-01) |
| Injectable fetch client | A new HTTP client | `build_client(settings)` / `_WeatherClient` (cli.py L85) | Bundles the secret `appid`, never logs it; tests already swap it (FakeClient) |
| "Did this write to the store?" detection | A custom audit log | `monkeypatch` the store functions / count rows in a `tmp_db` | The store module exposes named functions and a fresh-db fixture exists; see Validation Architecture |

**Key insight:** This phase is almost entirely *moving and re-wiring existing, tested code*, not writing new logic. The only genuinely-new logic is the ~15-line pure parser. Treat anything that looks like "re-implement X" as a red flag — X already exists and has tests.

## Runtime State Inventory

> This is a refactor (extracting `send_now`'s head into a new module), so the inventory applies. It is a **code-only** refactor — no stored data, no live external config, no OS registration changes.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None.** The refactor changes *where* code lives, not any DB key, collection, or schema. `weather_onecall`/`sent_log`/`alerts`/`heartbeat`/`health` table names and keys are unchanged; `lookup_weather` writes to none of them (D-06). | None |
| Live service config | **None.** No external service config references these module paths. The Discord webhook URL / OpenWeather key live in `.env` and are read by `Settings` — untouched. | None |
| OS-registered state | **None.** systemd unit invokes `weatherbot` (entry point `main()` in cli.py), which is unchanged; no module path is baked into a unit file or task. | None |
| Secrets/env vars | **None.** `OPENWEATHER_API_KEY` / `DISCORD_WEBHOOK_URL` env var names and the `Settings` model are not touched. `lookup_weather` receives secrets via the same injected `settings`/`client` seam as `send_now`. | None |
| Build artifacts / installed packages | **New package dir** `weatherbot/interactive/` with `__init__.py` — picked up automatically (the project uses `pythonpath=["."]`, verified in pyproject `[tool.pytest.ini_options]`; no `[tool.setuptools.packages]` enumeration to update). No egg-info/wheel rebuild needed for `uv run`. | None — verify `uv run python -c "import weatherbot.interactive"` after creating the package |

**The canonical question — after every file is updated, what runtime state still carries the old shape?** Nothing. No string is being renamed; code is being *extracted*. `send_now`'s public signature and behavior are preserved (criterion #4). The only observable change is the existence of a new importable package.

## Common Pitfalls

### Pitfall 1: The `schedule_placeholders` merge silently changes `send_now`'s output
**What goes wrong:** Moving the render call into `lookup_weather` but dropping or reordering the `{**forecast.placeholders(), **schedule_placeholders(...)}` merge changes which dict "wins" on a key collision, or drops the three timing tokens → `send_now` output diverges → criterion #4 fails.
**Why it happens:** The merge is a one-liner at cli.py L156–162 and easy to overlook; the schedule keys (`sent_at`/`checked_at`/`schedule_note`) are NOT in `Forecast.placeholders()` — they only exist via the merge.
**How to avoid:** Use the `extra_placeholders` seam (Pattern 1, Option A) and merge with `values.update(extra_placeholders)` so schedule keys layer on top in the same order. Keep `tz`/`sent_dt`/`checked_dt` computation where `send_now` needs scheduler context. The existing `tests/test_send_now.py::test_manual_send_schedule_placeholders` and `test_send_now_late_context_populates_note` are the byte-level guard — they MUST stay green unchanged.
**Warning signs:** `test_send_now_late_context_populates_note` fails ("intended for 7:00 AM" missing); a literal `{sent_at}` appears in a scheduled briefing.

### Pitfall 2: Loose `weather` matching trips the future Discord feedback loop
**What goes wrong:** If the parser treats any string *containing* (or even *starting with*) `weather` as a command, the daily briefing text — which contains the word "weather" and location names — could later be parsed as a command by the P11 bot, firing an OpenWeather call on every briefing (PITFALLS.md Pitfall 2).
**Why it happens:** "everything after the keyword" (D-04) is easy to implement as `startswith("weather")` with no word boundary, so `weatherman`/`weathervane` and a briefing line beginning "weather:" both match.
**How to avoid:** Require a word boundary after the keyword (Pattern 2 snippet) and match only when `weather` is the leading token. Phase 6's parser is the first line of defense; P11 adds the `author.bot` guard. Add explicit `weatherman`/`weathervane`/`"weather:"` cases to `test_command.py`.
**Warning signs:** `parse_weather_command("weatherman")` returns `LOCATED`; a briefing-shaped string parses as a command.

### Pitfall 3: Import cycle between `weatherbot.cli` and `weatherbot.interactive`
**What goes wrong:** D-08 makes `cli.send_now` import `lookup_weather` from `weatherbot.interactive`. If `interactive/lookup.py` does a top-level `from weatherbot.cli import build_client, _WeatherClient`, you get a circular import at module load (`cli → interactive → cli`), which surfaces as `ImportError: cannot import name ... (most likely due to a circular import)` or a partially-initialized module.
**Why it happens:** `build_client`/`_WeatherClient` currently live in `cli.py`. This codebase already hit and documented this exact class of cycle twice (`scheduler/__init__.py` PEP-562 lazy attr; `cli.py` L478 deferring the `daemon` import).
**How to avoid (pick one, planner's discretion):**
- **(a) Lazy import** inside `lookup_weather`: `from weatherbot.cli import build_client` only inside the `if client is None:` branch (matches the cli.py L478 daemon-deferral precedent). Tests inject `client`, so the import never even runs in unit tests. Lowest-churn option.
- **(b) Move `build_client` + `_WeatherClient`** to a neutral module (e.g. `weatherbot/weather/client.py` already holds `fetch_onecall`/`geocode`, or a new `weatherbot/weather/_client_factory.py`), and have both `cli.py` and `lookup.py` import from there. Cleaner long-term; more churn now.
**Recommendation:** (a) for this phase — it mirrors the established lazy-import precedent and keeps the diff small. Note the choice in the plan so the plan-checker expects a function-level import.
**Warning signs:** `ImportError ... circular import` when running `uv run python -c "import weatherbot.cli"` or any test that imports `send_now`.

### Pitfall 4: `lookup_weather` accidentally touches the store
**What goes wrong:** Copy-pasting `send_now`'s body into `lookup_weather` drags the `persist(db_path, ...)` tail along, so an on-demand read writes a `weather_onecall` row → pollutes the scheduled time series (the explicit out-of-scope item in REQUIREMENTS.md, and criterion #2).
**Why it happens:** `persist` sits at the end of `send_now`; an over-eager extraction includes it. `lookup_weather` also has no `db_path` parameter — which is the point.
**How to avoid:** `lookup_weather` takes NO `db_path` and imports nothing from `weatherbot.weather.store`. Enforce with a test that runs `lookup_weather` against a fresh `tmp_db` and asserts every table has zero rows (and/or `monkeypatch` all seven store write functions to raise). See Validation Architecture criterion #2.
**Warning signs:** `SELECT COUNT(*) FROM weather_onecall` > 0 after a lookup; `lookup.py` imports `store`.

### Pitfall 5: `UnknownLocationError` breaks the existing `ValueError` contract
**What goes wrong:** If `UnknownLocationError` does NOT subclass `ValueError`, or `resolve_location` is changed to raise it but a caller (e.g. `do_check`, `run_send_now`) was catching plain `ValueError`, existing behavior/tests break — violating "keep v1.0 path green" (D-07).
**Why it happens:** `resolve_location` currently raises `ValueError` (loader.py L48/L56) and `assert_unique_names` raises `ValueError`; callers and tests rely on that type.
**How to avoid:** Define `class UnknownLocationError(ValueError)`. If you upgrade `resolve_location` to raise it (the backward-compatible discretion option in D-07), every existing `except ValueError` still catches it. Carry `requested: str` and `valid_names: list[str]` (or `tuple[str, ...]`) as attributes; build the `valid_names` from `config.locations` (the message string already does this at loader.py L55). Add a test that `UnknownLocationError` IS-A `ValueError` and that an existing `except ValueError` path still works.
**Warning signs:** `test_config.py`/`test_cli.py` location-resolution tests fail; `isinstance(err, ValueError)` is False.

## Code Examples

Verified patterns lifted from the live codebase (these are the seams the new code reuses).

### The exact read-only chain to extract (from `weatherbot/cli.py` send_now, L113–162)
```python
# Source: weatherbot/cli.py L113-162 (verified this session)
location = resolve_location(config, location_name)            # L113
onecall_imp = client.fetch_onecall(location, "imperial")      # L129
onecall_met = client.fetch_onecall(location, "metric")        # L130
primary = location.units or "imperial"                        # L132
forecast = Forecast.from_payloads(location, onecall_imp, onecall_met, primary=primary)  # L133
template_text = (load_template(config.template, templates_dir) # L139-142
                 if templates_dir is not None else load_template(config.template))
validate_template(template_text)                              # L143
text = render(template_text, {**forecast.placeholders(),      # L156-162  <-- schedule merge here
                              **schedule_placeholders(schedule_ctx, sent_dt, checked_dt)})
```
Everything ABOVE the `render` merge is pure read-only and moves into `lookup_weather`. The `schedule_placeholders(...)` half stays a `send_now` concern (passed via `extra_placeholders`).

### House dataclass value-object style (from `weatherbot/scheduler/context.py` L29-43)
```python
# Source: weatherbot/scheduler/context.py L29-43 (verified) — mirror this for LookupResult
@dataclass
class ScheduleContext:
    scheduled_dt: datetime | None
    tz: ZoneInfo
    late: bool = False
```
`LookupResult` follows the same pattern:
```python
# interactive/lookup.py — recommended
@dataclass
class LookupResult:
    text: str
    forecast: Forecast
    location: Location
```

### Existing test harness to reuse verbatim (from `tests/test_send_now.py` + `tests/conftest.py`)
```python
# Source: tests/test_send_now.py L24-49 + conftest.py L20-33 (verified)
# - FakeClient(onecall_imp, onecall_met): records fetch units, returns fixtures
# - FakeChannel(): captures sent_text + briefing_forecasts, returns DeliveryResult(ok=True)
# - load_fixture("onecall_imperial_clear.json") / "onecall_metric_clear.json"
# - tmp_db fixture: a fresh, not-yet-created SQLite path
```
`test_lookup.py` reuses `FakeClient` + `load_fixture` (no `FakeChannel` needed — `lookup_weather` never delivers).

## State of the Art

| Old (v1.0) | New (post-Phase-6) | When Changed | Impact |
|------------|--------------------|--------------|--------|
| `send_now` owns resolve→fetch→render→deliver→persist as one monolith (cli.py) | `lookup_weather` owns read-only resolve→fetch→render; `send_now` delegates the head and keeps deliver→persist | Phase 6 | One read-only core, two future surfaces (P7/P11), zero duplicated fetch/render |
| Location-not-found raises bare `ValueError` (loader.py) | `UnknownLocationError(ValueError)` carrying `requested` + `valid_names` (D-07 — optional upgrade of `resolve_location`) | Phase 6 | Surfaces can format CMD-04 without re-deriving the valid-names list; old `except ValueError` still works |
| No command-text parsing exists | `parse_weather_command` three-state parser | Phase 6 | Both CLI argv and Discord message text get identical semantics |

**Deprecated/outdated:** Nothing is removed. The v1.0 2.5-era `weather_current`/`weather_forecast` store tables remain (already historical). No code is deleted in this phase — only extracted and re-wired.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The word-boundary guard (`weatherman` → NOT_A_COMMAND) is desired. CONTEXT's D-04 ("everything after the keyword") is literally satisfiable without it; the matrix omits `weatherman`. | Pattern 2 / Pitfall 2 | If undesired, `weatherman` would (wrongly) parse as `LOCATED("man")`. Low risk — strictly safer to keep; confirm with planner. |
| A2 | On-demand `lookup_weather` should compute its own location-local `sent_at`/`checked_at` (matching the manual `--send-now` path) rather than leaving those tokens literal. | Pattern 1 / Open Question 1 | If wrong, an on-demand briefing using a template with `{sent_at}` renders the literal token. Confirm desired on-demand timing behavior with planner. |
| A3 | Lazy-importing `build_client` inside `lookup_weather` (vs. relocating it) is the preferred cycle-break. | Pitfall 3 | Either works; the choice only affects diff size + where the symbol lives. Planner picks. |
| A4 | `weatherbot/interactive/` is auto-discovered (no packaging manifest enumerates packages). Verified: pyproject uses `pythonpath=["."]` and has no `[tool.setuptools.packages]` / hatch include list. | Runtime State Inventory | If a packaging build step (wheel) later enumerates packages explicitly, the new package must be added there. Not relevant for `uv run`. |

## Open Questions (RESOLVED)

> All three resolved per the recommendations below and locked into executable plan tasks during /gsd-plan-phase (verified by gsd-plan-checker 2026-06-15).

1. **On-demand timing placeholders.** Should `lookup_weather` populate `{sent_at}`/`{checked_at}` for a manual/on-demand read (matching `--send-now`'s manual path), or leave them to the caller / unrendered?
   - What we know: `send_now`'s manual path (schedule_ctx=None) DOES render them via `schedule_placeholders(None, sent_dt, checked_dt)` using `ZoneInfo(location.timezone)` (cli.py L153–155).
   - What's unclear: whether the P7/P11 on-demand surfaces want those tokens populated.
   - Recommendation: have `lookup_weather` compute them the same way (A2) so on-demand output matches a manual `--send-now`; `send_now` overrides via `extra_placeholders` for the scheduled path. Surface to the planner.
   - **RESOLVED:** Adopted. `lookup_weather` computes its own location-local `{sent_at}`/`{checked_at}`; `send_now` overrides via `extra_placeholders` (preserving byte-identity). Implemented by 06-02 Task 2 + 06-03 Task 2.

2. **Parser word boundary** (see A1). Recommendation: keep the boundary guard; add `weatherman`/`weathervane`/`"weather:"` to the test matrix.
   - **RESOLVED:** Adopted. Word-boundary guard kept (`weatherman`/`weather:` → NotACommand) with explicit test-matrix rows. Implemented by 06-01 Tasks 1–2.

3. **Where `UnknownLocationError` is raised** — upgrade `resolve_location` (touches `config/loader.py`, shared with the v1.0 path) vs. wrap inside `lookup_weather` (keeps loader untouched). Both are D-07-compliant. Recommendation: upgrade `resolve_location` to raise `UnknownLocationError(ValueError)` — it is backward-compatible, single-source, and means the daemon/`--check`/`--send-now` paths all get the richer error for free. Add a regression test that the existing `except ValueError` callers are unaffected.
   - **RESOLVED:** Adopted. `resolve_location` itself upgraded to raise `UnknownLocationError(ValueError)` (backward-compatible), with a documented ValueError-wrap fallback if an import cycle surfaces. Implemented by 06-02 Task 3.

## Environment Availability

> **SKIPPED (no external dependencies).** This phase is pure code: stdlib + already-installed first-party modules. No CLI tool, service, runtime upgrade, or network dependency is introduced. The only "environment" facts (verified this session): Python 3.12.3, uv 0.11.19, ruff 0.15.16, pytest 9.0.3 — all present. No OpenWeather network access is needed (tests use recorded fixtures).

## Validation Architecture

Nyquist validation is enabled (no `workflow.nyquist_validation: false` found). The phase's 4 success criteria map cleanly onto the existing pytest + recorded-fixture harness — no new framework, no new fixtures beyond two new test files.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (verified `uv run pytest --version`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"` |
| Quick run command | `uv run pytest tests/test_lookup.py tests/test_command.py -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------|----------|-----------|-------------------|--------------|
| #1 | `lookup_weather` resolves + fetches (fixtures) + renders v1 template → correct `.text`, `.forecast`, `.location` | unit | `uv run pytest tests/test_lookup.py -x` | ❌ Wave 0 |
| #2 | `lookup_weather` writes NO store rows (onecall/sent_log/alerts/heartbeat/health) | unit | `uv run pytest tests/test_lookup.py::test_lookup_writes_nothing -x` | ❌ Wave 0 |
| #3 | `parse_weather_command` full input matrix → stable 3-state result | unit | `uv run pytest tests/test_command.py -x` | ❌ Wave 0 |
| #4 | `send_now` byte-identical after delegation; existing tests green | regression | `uv run pytest tests/test_send_now.py -x` | ✅ existing (must stay green) |
| D-07 | `UnknownLocationError` IS-A `ValueError`; carries `requested` + `valid_names`; old `except ValueError` unaffected | unit | `uv run pytest tests/test_lookup.py::test_unknown_location_error -x` | ❌ Wave 0 |

**Concrete test techniques (fit the existing style):**

- **Criterion #1 (lookup happy path):** Reuse `FakeClient` + `load_fixture` from `test_send_now.py`/`conftest.py`. Assert `result.text` contains `"New York"` and `"°F"` (clear fixture, imperial-primary); assert `result.forecast.location == "New York"`; assert `result.location.name == "New York"`; assert `client.onecall_calls == ["imperial", "metric"]` (the dual-fetch contract). For metric-primary, reuse the `Berlin units="metric"` config from `test_send_now_metric_location_renders_metric_primary` and assert `result.forecast.temp_display == "20°C (68°F)"`.
- **Criterion #2 (zero store writes) — two complementary assertions:**
  1. **Row-count:** run `lookup_weather` against the `tmp_db` fixture, then open the db and assert `SELECT COUNT(*)` is 0 for `weather_onecall`, `sent_log`, `alerts` — and that the seeded singleton rows `heartbeat`/`health` are still `last_tick_utc IS NULL`/`reason IS NULL` (untouched). Note: `lookup_weather` takes no `db_path`, so the cleanest form is to assert it never opens the db at all. The row-count test is belt-and-suspenders if a `db_path` ever leaks in.
  2. **Spy/monkeypatch (preferred, directly proves intent):** `monkeypatch.setattr` each of the seven store write functions (`weatherbot.weather.store.persist`, `claim_slot`, `record_alert`, `resolve_alert`, `stamp_tick`, `stamp_success`, `stamp_health`) to a function that raises `AssertionError("lookup_weather touched the store")`; run `lookup_weather`; assert it completes without raising. This catches an accidental store import even if no `db_path` is passed.
- **Criterion #3 (parser matrix):** parametrize `test_command.py` over the full matrix:
  | Input | Expected |
  |-------|----------|
  | `"weather"` | `DEFAULT`, location=None |
  | `"weather home"` | `LOCATED`, location=`"home"` |
  | `"weather New York"` | `LOCATED`, location=`"New York"` |
  | `"weather   home  "` | `LOCATED`, location=`"home"` (trimmed) |
  | `"Weather HOME"` | `LOCATED`, location=`"HOME"` (raw case preserved; keyword matched case-insensitively) |
  | `"WEATHER"` | `DEFAULT` |
  | `"hello"` | `NOT_A_COMMAND` |
  | `""` | `NOT_A_COMMAND` |
  | `"  "` | `NOT_A_COMMAND` |
  | `"weatherman"` | `NOT_A_COMMAND` (A1/Pitfall 2 — if boundary guard kept) |
  | `"weather: 72°F today"` (briefing-shaped) | `NOT_A_COMMAND` (boundary guard) |
  Note D-04: the location RAW case is preserved (`HOME`, `New York`), only the *keyword* is matched case-insensitively, and `resolve_location` later casefolds for matching — so `parse_weather_command` must NOT lowercase the extracted location.
- **Criterion #4 (byte-identical regression):** Do NOT modify `test_send_now.py`'s assertions. Run it unchanged; it already asserts the rendered body content, the dual-fetch order, the metric-primary `temp_display`, the schedule-note rendering, and the persist row count. If it stays green after the refactor, byte-identity holds. For extra rigor, the planner may add a test that captures the rendered `send_now` body for the `onecall_imperial_clear` fixture before and after, but the existing suite is the contractual gate.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_lookup.py tests/test_command.py -x -q` (the two new files) plus `uv run pytest tests/test_send_now.py -q` once the delegation lands.
- **Per wave merge:** `uv run pytest -q` (full suite — the byte-identical guard lives across `test_send_now.py`, `test_renderer.py`, `test_store.py`, `test_cli.py`).
- **Phase gate:** Full suite green + `uv run ruff check` + `uv run ruff format --check` before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_lookup.py` — covers criterion #1, #2, D-07 (reuses `FakeClient`/`load_fixture`/`tmp_db`)
- [ ] `tests/test_command.py` — covers criterion #3 (pure, no fixtures needed)
- [ ] No new conftest fixtures required — `load_fixture` and `tmp_db` already exist and suffice.
- [ ] No framework install — pytest is already in the dev group.

## Security Domain

`security_enforcement` is not set to `false` in config (treated as enabled). This phase introduces **no new attack surface** — no new input boundary beyond a pure in-process string parser, no new network call, no new secret, no new persistence. The relevant controls are all *inherited from v1.0 and must not regress*.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control (inherited, must not regress) |
|---------------|---------|-----------------------------------------------|
| V2 Authentication | no | No auth surface in this phase |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | Single-user tool; no access control added here (P11 adds the operator-ID allowlist) |
| V5 Input Validation | **yes** | The command text is untrusted input (esp. for P11 later). The parser is parse-don't-validate but MUST NOT route text through `eval`/`str.format`/shell. It only does `str.strip`/`casefold`/slice — no interpolation. The renderer (`render`) is the guarded regex substitutor (T-03-02: no format-string injection) — reused unchanged (CMD-05). |
| V6 Cryptography | no | No crypto |
| V7/V8 Logging & secrets | **yes** | T-04-01: never log the `appid`/webhook URL. `lookup_weather` must keep the "outcome-only" logging discipline — never echo the fetched URL or key. It reuses `_WeatherClient`, which already holds the key internally and never logs it. |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation (already in place / preserved) |
|---------|--------|----------------------------------------------------|
| Format-string / template injection via a user-editable template | Tampering / EoP | Guarded regex `render` — no `str.format`, no `eval`, unknown tokens left visible (renderer.py T-03-02/03). Reused unchanged. |
| SQL injection via location name | Tampering | N/A in Phase 6 — `lookup_weather` never touches SQL (D-06). v1's store uses parameterized `?` throughout (store.py). |
| Secret leakage in logs/errors | Info Disclosure | `UnknownLocationError` carries only the requested name + configured display names — never a key/URL. `lookup_weather` logging stays outcome-only (T-04-01). |
| Command-trigger abuse / quota burn | DoS | Out of scope here (CMD-06 cache + cooldown are P11). The parser's word-boundary guard (A1) is the first line against the briefing-feedback loop (PITFALLS.md Pitfall 2). |

**Net:** Phase 6's security obligation is *non-regression* — reuse the guarded renderer, keep `lookup_weather` store-free and log-clean, and make the parser a pure string classifier with no interpolation/eval.

## Sources

### Primary (HIGH confidence — read directly this session)
- `weatherbot/cli.py` L1–505 — `send_now` body (the refactor target), `build_client`/`_WeatherClient`, the schedule-merge render site (L153–162), the lazy `daemon` import precedent (L478)
- `weatherbot/config/loader.py` L40–75 — `resolve_location` (raises `ValueError`), `assert_unique_names`
- `weatherbot/config/models.py` — `Location`, `Config`, first-location-is-default
- `weatherbot/weather/store.py` — the seven write functions `lookup_weather` must NOT call; table/key shapes
- `weatherbot/weather/models.py` — `Forecast.from_payloads`, `.placeholders()`, display properties
- `templates/renderer.py` — `load_template`/`validate_template`/`render`, `CANONICAL` set (incl. schedule keys)
- `weatherbot/scheduler/context.py` — `ScheduleContext` + `schedule_placeholders` (the merge-at-call-site seam), dataclass value-object house style
- `weatherbot/scheduler/__init__.py`, `weatherbot/config/__init__.py`, `weatherbot/ops/__init__.py` — package `__init__` re-export + PEP-562 lazy-import precedent (import-cycle evidence)
- `tests/test_send_now.py`, `tests/conftest.py` — `FakeClient`/`FakeChannel`/`load_fixture`/`tmp_db`, the byte-identical regression assertions
- `pyproject.toml` — deps (no new package needed), pytest config (`pythonpath=["."]`, no package enumeration), tool versions
- `.planning/phases/06-.../06-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/research/PITFALLS.md` — locked decisions + requirement + feedback-loop pitfall

### Secondary / Tertiary
- None required — the phase has no external/third-party surface to verify; all claims are grounded in the live codebase (HIGH) or flagged `[ASSUMED]` in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every reused symbol read directly this session.
- Architecture / refactor mechanic: HIGH — the exact `send_now` body, the merge site, and the import-cycle precedent were all read in-session; the only judgment calls (timing placeholders, word boundary, where to raise) are flagged as Open Questions.
- Pitfalls: HIGH — import cycle and store-write are concrete and grounded in this codebase's documented prior cycles and the explicit out-of-scope note; feedback-loop pitfall is from the project's own PITFALLS.md.
- Validation: HIGH — maps onto the existing pytest harness with no new infrastructure.

**Research date:** 2026-06-15
**Valid until:** ~2026-07-15 (stable — internal refactor of a shipped codebase; no fast-moving external dependency. Re-verify only if `send_now`/`resolve_location`/the renderer change before Phase 6 is planned.)
