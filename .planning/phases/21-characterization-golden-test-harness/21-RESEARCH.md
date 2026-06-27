# Phase 21: Characterization / Golden-Test Harness - Research

**Researched:** 2026-06-27
**Domain:** Characterization / golden-snapshot testing of an existing Python codebase (syrupy + coverage.py branch mode), grounded in WeatherBot's existing pytest seams
**Confidence:** HIGH (tooling + repo seams verified against the actual source; versions verified against PyPI)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Snapshot storage & comparison**
- **D-01:** Use **syrupy** as the workhorse snapshot library (only dep is `pytest`, already pinned 9.0.3; one line in the dev group).
- **D-02:** Serializer choice by payload type:
  - `JSONSnapshotExtension` (order-preserving `.json`) for **structured** payloads — embed dicts, schedule plan, DB rows — so a **field reorder** surfaces as a real diff.
  - `SingleFileSnapshotExtension` (raw bytes) for **`custom_id` strings and CLI stdout**, where a single byte flip must fail.
- **D-03:** Keep a **small number of inline literal pins** (extend the existing `test_weather_spec_byte_identical` pattern in `tests/test_panel.py`) for tiny self-documenting assertions.
- **D-04:** Goldens are **committed** under `tests/__snapshots__/`. Regen is a deliberate `--snapshot-update`. **Discipline rule:** during extraction (22–28) any non-empty snapshot diff is a failure to investigate, never a rubber-stamp.
- **Rejected:** `inline-snapshot`; a hand-rolled `tests/golden/` pattern.

**Coverage audit (move-path de-risk)**
- **D-05:** Add **`pytest-cov`** (wraps coverage.py; runs inside the existing `pytest` invocation). Not raw coverage.py out-of-band.
- **D-06:** **Branch mode is mandatory** (`[tool.coverage.run] branch = true`).
- **D-07:** Scope to the **move-path packages only** via `source = ["weatherbot/channels", "weatherbot/scheduler", "weatherbot/config", "weatherbot/reliability", "weatherbot/ops", "weatherbot/interactive"]`. `weatherbot/weather`, templates, branding stay app-side, **not** in scope.
- **D-08:** **ONE-TIME Phase-21 audit**, not a standing `fail_under` gate: run once with `--cov-report=term-missing`, fill every reported uncovered move-path branch with a characterization test, record clean audit in the phase log, move on.
- **D-09:** Carry forward the codebase's existing **`# pragma: no cover - <reason>`** convention. Use `[tool.coverage.report] exclude_also` / `partial_also` for systematic defensive patterns.

**Golden granularity & determinism**
- **D-10:** **Granularity = representative-subset, parametrized one-per-cell.** Each command its own named case; each Phase-20 state covered ≥1 (📍-on via location-bearing reply, 📍-off via argless status reply); each forecast variant (weekday/weekend × detailed/compact) once. No cartesian explosion.
- **D-11:** **Determinism = freeze what derives from "now," scrub only what doesn't.**
  - **Freeze** (via `time-machine`): the `Updated <t:{epoch}…>` stamp AND APScheduler `next_run_time` → deterministic literals. **Keep the format string in the golden** (`<t:…:t> (<t:…:R>)`) so a `:R`-dropped/reordered regression still fails (over-scrubbing trap).
  - **Scrub** only: SQLite autoincrement **rowids**, non-clock `created_at` fields.
  - Kill query-order nondeterminism with explicit **`ORDER BY` in the read path**, not a sort-scrub.
  - `embed.timestamp = utcnow()` already excluded from the byte contract per the existing docstring.

**Oracle self-proof & exception-identity pin**
- **D-12:** **Oracle self-proof (SC2) = inline meta-test** that perturbs a rendered embed (field reorder + `custom_id` byte-flip) wrapped in `pytest.raises(AssertionError)`. Ships as a standing test. Rejected: `xfail(strict=True)`, mutation testing.
- **D-13:** **Exception-identity pin (SC3) = two asserts per move-path error type:**
  1. **`is`-identity through the caller's import path** — `from weatherbot.reliability import X; assert excinfo.type is X`.
  2. **Frozen `(__module__, __qualname__)` tuple assert.**
  **Avoid `isinstance` as the pin.** Optional thin behavioral except-catch backstop allowed.

### Claude's Discretion
- Exact file/case naming for goldens and the `tests/__snapshots__/` layout.
- Which specific exception types are "move-path" (enumerate during planning).
- The precise frozen instant + timezone (reuse what existing recorded fixtures assume).
- Whether the optional behavioral except-catch backstop (D-13) is worth including.

### Deferred Ideas (OUT OF SCOPE)
- Standing `fail_under=100` branch gate.
- Mutation testing (mutmut / cosmic-ray).
- Behavioral except-catch end-to-end backstop (left to planner/executor discretion).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BHV-01 | Every existing WeatherBot behavior remains byte-identical through extraction — the full pre-existing suite stays green at every phase boundary (no skips, no weakened assertions). | The current suite is **652 tests** `[VERIFIED: pytest --co]`. Phase 21 adds golden tests purely additively; BHV-01 is satisfied by re-running the whole suite (652 + new goldens) green. See `## Validation Architecture`. |
| BHV-02 | Golden/characterization tests pin the observable outputs intent-level tests miss — briefing text, embed fields + order, per-location schedule plan, persisted DB rows, panel `custom_id`s — re-run as the byte-identical oracle after each seam extraction and after the split. | Each surface mapped to a concrete render/read seam below: `render_embed`/`build_inbound_embed` (embeds), `cli.main(argv)` + `capsys` (CLI stdout/exit), `DaemonState.next_fires()` / `scheduler.get_jobs()` (schedule plan), `weather_onecall`/`alerts`/`sent_log` reads (DB rows), `wb:`-prefixed `custom_id`s (panel). See `## Architecture Patterns` + `## Validation Architecture`. |
</phase_requirements>

## Summary

This is a **characterization-test** phase: capture WeatherBot's current observable bytes as committed golden snapshots so the v2.0 extraction (Phases 22–28) is provably byte-identical, not merely "suite green." Every tool is already locked (syrupy, pytest-cov, branch mode, `time-machine`) — the research below is purely about the **concrete mechanics** the planner needs to write executable, non-vague tasks against THIS repo's real seams.

The repo is unusually well-prepared for this: the suite already drives every render/DB/dispatch path **gateway-free** through `tests/conftest.py` factories (`fake_interaction`, `fake_discord_message`, `tmp_db`, `seed_sent_row`, `fake_pinned_message`/`fake_pins`, `holder_scheduler`, `load_fixture`), and `tests/test_panel.py` already contains the inline byte-pin pattern (`test_weather_spec_byte_identical`) the goldens extend. `render_embed`/`build_inbound_embed` return `discord.Embed` objects whose `.title`/`.description`/`.fields[(name,value,inline)]` are directly snapshot-able as an ordered dict; the CLI is driven by `cli.main(argv)` returning an int exit code with stdout via `capsys`; the schedule plan reads from `scheduler.get_jobs()` (`job.id`, `job.trigger`, `job.next_run_time`) or `DaemonState.next_fires()`; DB rows come from `weatherbot.weather.store` reads.

**Primary recommendation:** Add `syrupy>=5.3.4` and `pytest-cov>=7.1.0` to the dev group; add a `[tool.coverage.run]`/`[tool.coverage.report]` block scoped to the 6 move-path packages with `branch = true`; build a small set of helper functions that serialize a `discord.Embed` into an ordered dict (title, description, then `[{name, value, inline}]` in field order) so `JSONSnapshotExtension` catches field-reorder; freeze the clock with `time-machine` at a single shared instant and freeze `next_run_time`; pin `custom_id`s + CLI stdout as raw bytes; and enumerate the move-path exception types (`httpx.HTTPStatusError`/`TimeoutException`/`ConnectError`/`ReadError`, `discord.LoginFailure`/`discord.Forbidden`, `UnknownLocationError`, tenacity `RetryError`) for the D-13 identity pin.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Render Discord embed (📍 / Updated states) | API/Backend (`interactive/bot.py:render_embed` / `build_inbound_embed`) | — | Embed construction is pure backend logic returning a `discord.Embed`; no gateway needed to snapshot it. |
| CLI stdout/exit per subcommand | API/Backend (`cli.main(argv)`) | — | `main()` is a pure `argv → int` function; stdout via `print`, captured by `capsys`. No process spawn. |
| Schedule plan (job_id, trigger, next_run_time) | Scheduler (`scheduler/daemon.py:_register_jobs`, read via `scheduler.get_jobs()` / `interactive/state.py:DaemonState.next_fires`) | — | Job registration is in-process; `get_jobs()` exposes the plan without starting the scheduler. |
| Persisted DB rows (`weather_onecall`/`alerts`/`sent_log`) | Database/Storage (`weather/store.py`) | — | SQLite writes via `persist`/`claim_slot`/`record_alert`; read back with a parameterized `SELECT ... ORDER BY`. |
| Panel `custom_id` byte strings (`wb:` marker) | Client/UI surface (`interactive/panel.py`) | — | `custom_id`s are static byte strings set at construction (`wb:cmd:<name>`, `wb:loc:select`, `wb:fc:<day>:<variant>`); read off a built `PanelView`'s children. |
| Exception identity (move-path error types) | API/Backend (`reliability/retry.py`, `interactive/bot.py`, `interactive/lookup.py`, `cli.py`) | — | Identity = `(__module__, __qualname__)` + `is`-through-import; pure type introspection. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `syrupy` | `>=5.3.4` | Snapshot assertion + committed golden files | Locked D-01. Zero-runtime-dep (only `pytest>=8.0.0`). `assert value == snapshot`; `--snapshot-update` regen; native `JSONSnapshotExtension` / `SingleFileSnapshotExtension`. `[CITED: pypi.org/pypi/syrupy/json — requires_python >=3.10, pytest>=8.0.0]` `[VERIFIED: PyPI latest 5.3.4]` |
| `pytest-cov` | `>=7.1.0` | One-time branch-coverage audit inside the pytest run | Locked D-05. Wraps coverage.py; pulls `coverage[toml]>=7.10.6`, `pluggy>=1.2`, `pytest>=7` — all compatible with pytest 9.0.3. `[VERIFIED: PyPI latest 7.1.0, requires-dist confirms pytest>=7]` |
| `coverage` | `>=7.10.6` (transitive) | Branch-coverage engine + `[tool.coverage.*]` config | Pulled by pytest-cov; reads `pyproject.toml` `[tool.coverage.*]`. `[VERIFIED: PyPI coverage latest 7.14.3]` |
| `time-machine` | `>=2.16` (already a dev dep) | Freeze the clock for `Updated <t:…>` + `next_run_time` (D-11) | Already pinned in `pyproject.toml` dev group `[VERIFIED: pyproject.toml line 30]`. No new tool. |
| `pytest` | `9.0.3` (already pinned) | Test runner | `[VERIFIED: .venv pytest --version → 9.0.3]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sqlite3` (stdlib) | built-in | Read back persisted rows for the DB-row golden | Already how `store.py` + `tests/test_store.py` read rows; no new dep. |
| `discord.py` | `2.7.1` (already pinned) | The `discord.Embed` / `PanelView` objects being snapshotted | Already a runtime dep `[VERIFIED: pyproject.toml line 10]`. Goldens read its objects gateway-free via existing fakes. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `syrupy` `JSONSnapshotExtension` | `AmberSnapshotExtension` (syrupy default `.ambr`) | Amber is human-readable but its serializer can normalize/sort dict keys — defeating the field-ORDER contract (D-02). JSON preserves insertion order. Use JSON for structured, Amber never. |
| `syrupy` | `inline-snapshot` | Rejected by D-01 (pre-1.0, rewrites test source on update, 4–5 transitive deps). |
| `pytest-cov` | raw `coverage run -m pytest` | Rejected by D-05 (out-of-band; pytest-cov runs the audit inside the existing invocation). |

**Installation:**
```bash
uv add --dev "syrupy>=5.3.4" "pytest-cov>=7.1.0"
```

**Version verification (run 2026-06-27):**
- `syrupy` latest **5.3.4**, `requires_python >=3.10`, runtime dep `pytest>=8.0.0` (no upper bound → pytest 9.0.3 OK). `[CITED: pypi.org/pypi/syrupy/json]`
- `pytest-cov` latest **7.1.0**, `requires-dist`: `coverage[toml]>=7.10.6`, `pluggy>=1.2`, `pytest>=7`. `[VERIFIED: pypi.org/pypi/pytest-cov/json]`
- `coverage` latest **7.14.3**. `[VERIFIED: pypi.org/pypi/coverage/json]`

## Package Legitimacy Audit

> Three packages are installed by this phase. All three are locked in CONTEXT (D-01/D-05). The legitimacy seam returned `SUS` for all three, driven entirely by metadata gaps in the PyPI JSON feed (no download counts exposed → `unknown-downloads`; recent point releases → `too-new`), NOT by genuine slopsquat signals. These are three of the most-installed packages in the Python testing ecosystem.

| Package | Registry | Latest | Source Repo | Seam Verdict | Disposition |
|---------|----------|--------|-------------|--------------|-------------|
| `syrupy` | PyPI | 5.3.4 | github.com/syrupy-project/syrupy | SUS (`too-new`, `unknown-downloads`, `no-repository`) | **Approved** — locked D-01; canonical syrupy-project package; `requires_python`/dep tree match official docs. The `no-repository` signal is a PyPI-metadata gap, not a missing repo. |
| `pytest-cov` | PyPI | 7.1.0 | github.com/pytest-dev/pytest-cov | SUS (`unknown-downloads`, `no-repository`) | **Approved** — locked D-05; canonical pytest-dev package; `requires-dist` (coverage/pluggy/pytest) confirms identity. |
| `coverage` | PyPI | 7.14.3 | github.com/coveragepy/coveragepy | SUS (`too-new`, `unknown-downloads`) | **Approved** — transitive via pytest-cov; repo URL present (coveragepy/coveragepy = Ned Batchelder's coverage.py). |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** all three, but the SUS is metadata-driven (no download feed / recent release), not a hallucination/slopsquat signal. All three are CONTEXT-locked, resolve on the correct registry (PyPI), and have matching dep trees. **Planner recommendation:** treat as approved; a `checkpoint:human-verify` before the `uv add --dev` line is optional (the developer already chose these in discuss-phase). No `postinstall`/network-call signals on any package.

## Architecture Patterns

### System Architecture Diagram

```
                          Phase-21 golden harness (purely additive test infra)
                          ===================================================

  recorded fixtures            frozen clock (time-machine)        committed goldens
  tests/fixtures/onecall_*.json   single shared instant + tz       tests/__snapshots__/
        │                              │                                  ▲
        │  load_fixture(name)          │  travel(INSTANT, tick=False)     │  assert == snapshot
        ▼                              ▼                                  │  (syrupy)
  ┌───────────────────────────────────────────────────────────────────────────────┐
  │                         GATEWAY-FREE DRIVE SEAMS                                │
  │                                                                                │
  │  EMBED ─► render_embed(reply, location=) / build_inbound_embed(forecast)       │
  │            → discord.Embed ──[serialize to ordered dict]──► JSONSnapshot       │
  │                                                                                │
  │  CLI   ─► cli.main(argv) ──► int exit code  +  capsys stdout ─► SingleFile     │
  │                                                                                │
  │  SCHED ─► _register_jobs(scheduler, holder, …) → scheduler.get_jobs()          │
  │            → [(job.id, trigger spec, next_run_time)] ──► JSONSnapshot          │
  │            (also DaemonState.next_fires() for the per-location view)           │
  │                                                                                │
  │  DB    ─► persist()/claim_slot()/record_alert() → SELECT … ORDER BY            │
  │            → ordered rows (rowid/created_at scrubbed) ──► JSONSnapshot         │
  │                                                                                │
  │  PANEL ─► PanelView(holder, operator_id, cache).children                       │
  │            → [child.custom_id] (wb:…) ──► SingleFile / inline literal pin      │
  │                                                                                │
  │  EXC   ─► pytest.raises(...) → excinfo.type is X  +  (__module__,__qualname__) │
  └───────────────────────────────────────────────────────────────────────────────┘
```

File-to-seam mapping is in the Component Responsibilities table above; the diagram shows data flow only.

### Recommended Project Structure
```
tests/
├── conftest.py                       # EXISTING — reuse fakes; ADD a shared frozen-instant + embed-serializer fixture
├── __snapshots__/                    # NEW — committed goldens (syrupy writes here, per-test-file subdirs)
│   ├── test_golden_embeds/           #   one dir per golden test module
│   ├── test_golden_cli/
│   ├── test_golden_schedule/
│   └── test_golden_db/
├── test_golden_embeds.py             # NEW — embed-per-command × 📍/Updated states (JSONSnapshot)
├── test_golden_cli.py                # NEW — main(argv) stdout/exit per subcommand × forecast variant (SingleFile + inline exit-code pins)
├── test_golden_schedule.py           # NEW — (job_id, trigger spec, next_run_time) plan (JSONSnapshot, frozen next_run_time)
├── test_golden_db.py                 # NEW — weather_onecall/alerts/sent_log rows (JSONSnapshot, scrubbed)
├── test_golden_custom_ids.py         # NEW — wb: custom_id byte strings (SingleFile + inline pins per D-03)
├── test_oracle_selfproof.py          # NEW — D-12 perturbation meta-test (pytest.raises(AssertionError))
└── test_exception_identity.py        # NEW — D-13 move-path error identity pins
```

### Pattern 1: Serialize a `discord.Embed` into an order-preserving dict (D-02 field-reorder catch)
**What:** `render_embed`/`build_inbound_embed` return a `discord.Embed`. To make a **field reorder** fail the golden, serialize to a dict that preserves insertion order and includes `inline`.
**When to use:** Every embed golden.
**Example:**
```python
# Source: derived from weatherbot/interactive/bot.py:render_embed (returns discord.Embed)
# and the existing tests/test_panel.py field-read idiom:
#   [(f.name, f.value) for f in embed.fields]
def embed_to_golden(embed) -> dict:
    """Order-preserving, byte-faithful embed projection for JSONSnapshotExtension.

    Includes description (carries the 📍 line + the `Updated <t:…:t> (<t:…:R>)` stamp,
    bot.py:218-223) and the FULL field tuple incl. `inline` so a reorder or an
    inline-flip is a real diff. embed.timestamp is EXCLUDED (already outside the byte
    contract per test_weather_spec_byte_identical's docstring; D-11).
    """
    return {
        "title": embed.title,
        "description": embed.description,   # 📍 + Updated <t:…> live here (NOT the title)
        "color": embed.color.value if embed.color is not None else None,
        "fields": [
            {"name": f.name, "value": f.value, "inline": f.inline}
            for f in embed.fields
        ],
    }
```
The existing `tests/test_panel.py:487` already compares `[(f.name, f.value) for f in panel_embed.fields]` — the golden adds `description` (where 📍/Updated live) and `inline`, and lets syrupy own the regen/overwrite ergonomics.

### Pattern 2: Select the syrupy extension per-test (D-02)
**What:** syrupy's `snapshot` fixture defaults to the Amber extension. Override per-test with `snapshot.use_extension(...)`, or use a module-scoped fixture.
**When to use:** JSON for structured payloads; SingleFile for raw bytes.
**Example:**
```python
# Source: syrupy docs — Extensions (JSONSnapshotExtension, SingleFileSnapshotExtension)
import pytest
from syrupy.extensions.json import JSONSnapshotExtension
from syrupy.extensions.single_file import SingleFileSnapshotExtension

@pytest.fixture
def json_snapshot(snapshot):
    return snapshot.use_extension(JSONSnapshotExtension)

@pytest.fixture
def bytes_snapshot(snapshot):
    return snapshot.use_extension(SingleFileSnapshotExtension)

def test_weather_embed_home(json_snapshot, load_fixture):
    embed = build_inbound_embed(_forecast_from(load_fixture("onecall_metric_clear.json")))
    assert embed_to_golden(embed) == json_snapshot          # → .json under __snapshots__/

def test_cli_status_stdout(bytes_snapshot, capsys):
    rc = main(["status", "--config", str(cfg)])
    out = capsys.readouterr().out
    assert out.encode() == bytes_snapshot                    # raw bytes; one byte flip fails
```
`[CITED: syrupy-project.github.io/syrupy — Extensions]` `[ASSUMED: exact use_extension call shape — confirm against installed 5.3.4 in Wave 0]`

### Pattern 3: Multiple named snapshots in one test (avoid collisions)
**What:** Multiple `assert == snapshot` calls in one test auto-index (`.0`, `.1`); to make diffs self-naming, pass `name=`.
**Example:**
```python
# Source: syrupy docs — snapshot name parameter
def test_panel_custom_ids(bytes_snapshot, panel_view):
    ids = [c.custom_id for c in panel_view.children]
    assert "\n".join(ids).encode() == bytes_snapshot(name="all_custom_ids")
```
`[ASSUMED: snapshot(name=...) call form — confirm in Wave 0 against 5.3.4]`

### Pattern 4: Freeze the clock + `next_run_time` (D-11)
**What:** `render_embed` stamps `int(discord.utils.utcnow().timestamp())` into `Updated <t:{unix}:t> (<t:{unix}:R>)` (bot.py:219-223). Freeze `utcnow()` so `{unix}` is a literal constant **but keep the `<t:…:t> (<t:…:R>)` format in the golden** (over-scrubbing trap). APScheduler's `job.next_run_time` is computed from `CronTrigger.get_next_fire_time(None, datetime.now(tz))` (state.py:37) — freeze `now` so it's deterministic.
**Example:**
```python
# Source: time-machine (already a dev dep); state.py:_next_fire trigger fallback
import time_machine
from datetime import datetime, timezone

FROZEN = datetime(2026, 6, 20, 13, 0, 0, tzinfo=timezone.utc)  # D-11 discretion: pick one instant

def test_updated_stamp_is_frozen(json_snapshot, load_fixture):
    with time_machine.travel(FROZEN, tick=False):
        embed = render_embed(CommandReply(title="Weather — home"), location="home")
    # The golden contains the LITERAL `Updated <t:1750424400:t> (<t:1750424400:R>)`
    # — the :t/:R format string is preserved, only the epoch is frozen (NOT scrubbed).
    assert embed_to_golden(embed) == json_snapshot
```
`discord.utils.utcnow()` returns `datetime.now(timezone.utc)`, which `time_machine.travel` controls. **Wave-0 confirm:** that `time_machine` patches `discord.utils.utcnow` transitively (it patches the stdlib `datetime`; `discord.utils.utcnow` calls `datetime.now(utc)`, so it should — verify in Wave 0). `[ASSUMED: time_machine reaches discord.utils.utcnow]`

### Pattern 5: Read the schedule plan gateway-free (no started scheduler)
**What:** `_register_jobs(scheduler, holder, db_path=, settings=, stop_event=)` populates a **not-started** `BackgroundScheduler`; `scheduler.get_jobs()` then yields jobs whose `.id` is `f"{name}|{time}|{days}"` (briefing) or `_forecast_job_id` (`f"{name}|fc|{kind}|{variant}|{time}|{days}"`), `.trigger` is a `CronTrigger`, and `.next_run_time` is the frozen fire time. The existing `holder_scheduler` conftest fixture and `tests/test_reload.py`/`test_filewatch.py`/`test_reliability.py` already do exactly this.
**Example:**
```python
# Source: weatherbot/scheduler/daemon.py:_register_jobs + tests/test_reliability.py:631-647
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from weatherbot.scheduler import daemon as daemon_mod
from weatherbot.config.holder import ConfigHolder

def schedule_plan_golden(config, *, db_path):
    scheduler = BackgroundScheduler()                 # NOT started — get_jobs() works pending
    daemon_mod._register_jobs(
        scheduler, ConfigHolder(config),
        db_path=db_path, settings=None, stop_event=threading.Event(),
    )
    plan = []
    for job in scheduler.get_jobs():                  # excludes __heartbeat__/__uvmonitor__ unless added
        plan.append({
            "job_id": job.id,
            "trigger": str(job.trigger),              # CronTrigger.__str__ is stable, e.g. "cron[hour='9', minute='0', ...]"
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    plan.sort(key=lambda r: r["job_id"])              # explicit ORDER (D-11: order by id, not insertion luck)
    return plan
```
**Note:** a *pending* (never-started) scheduler may report `next_run_time=None` for jobs; `DaemonState.next_fires()` (state.py:58) handles that via the `CronTrigger.get_next_fire_time` fallback — the planner should decide whether the schedule golden snapshots the *registered trigger spec* (deterministic regardless of start) plus a frozen `next_run_time` computed via that fallback. `str(job.trigger)` is the load-bearing byte-exact field; `next_run_time` is the frozen secondary.

### Pattern 6: Read DB rows deterministically (D-11 scrub + ORDER BY)
**What:** `persist(db_path, location, forecast)` writes two `weather_onecall` rows (imperial+metric); `claim_slot` writes a `sent_log` row; `record_alert` writes an `alerts` row. Each carries an autoincrement `id` (rowid) and a clock `*_at_utc` / `created_at_utc`. Read back with an explicit `ORDER BY`, then drop/normalize the rowid and non-frozen timestamps.
**Example:**
```python
# Source: weatherbot/weather/store.py (persist / claim_slot / record_alert + schema)
import sqlite3, json

def onecall_rows_golden(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT location_name, lat, lon, target_local_date, units, raw_json "
            "FROM weather_onecall ORDER BY units, location_name"   # explicit order (D-11)
        ).fetchall()                                                # `id`/`fetched_at_utc` NOT selected → scrubbed
    return [
        {"location_name": r[0], "lat": r[1], "lon": r[2],
         "target_local_date": r[3], "units": r[4], "raw_json": json.loads(r[5])}
        for r in rows
    ]
```
`fetched_at_utc`/`sent_at_utc`/`created_at_utc` are clock-derived: either omit them from the `SELECT` (scrub) OR freeze the clock with `time-machine` and keep them as frozen literals (D-11 — freezing is preferred where the value is meaningful, scrub only what freezing can't stabilize, e.g. the autoincrement `id`). `target_local_date` is frozen-clock-derived too (computed from `datetime.now(timezone.utc)` in `_local_date_iso`, store.py:193-195) — freeze it.

### Anti-Patterns to Avoid
- **Amber (`.ambr`) for structured payloads:** its serializer can normalize dict ordering, silently defeating the field-reorder contract. Use `JSONSnapshotExtension`. (D-02)
- **Blanket epoch-scrub of `Updated <t:…>`:** drops the `:t (:R)` format string, so a `:R`-removed or line-reordered regression passes silently (over-scrubbing trap). Freeze the epoch, keep the format. (D-11)
- **Sort-scrubbing query results:** masks real ordering drift. Add `ORDER BY` to the read path instead. (D-11)
- **`isinstance` as the exception pin:** permits `except`-broadening. Use `is`-identity + frozen `(__module__, __qualname__)`. (D-13)
- **Starting the scheduler to read the plan:** unnecessary and introduces threads/flake. `get_jobs()` works on a pending scheduler (test_reliability.py precedent).
- **`--snapshot-update` to "fix" a red golden during Phases 22–28:** any non-empty diff in an extraction phase is a regression to investigate. (D-04)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Golden file storage + overwrite-safety + regen | A custom `tests/golden/` read/write/compare harness | `syrupy` `--snapshot-update` + committed `__snapshots__/` | Rejected explicitly in D-01 (re-implements syrupy's ergonomics for zero benefit). |
| Order-preserving structured serialization | A hand-written dict→sorted-JSON dumper | `JSONSnapshotExtension` (insertion-order preserving) | Sorting keys defeats the field-reorder contract; syrupy's JSON ext preserves order. |
| Clock control for `Updated`/`next_run_time` | Manual `monkeypatch.setattr(..., datetime, _Fixed)` per test | `time-machine` (already a dep, suite's established pattern per CONTEXT) | One global freeze, DST-correct, no per-module fake datetime class. |
| Branch-coverage measurement | Parsing AST / counting branches by hand | `coverage.py branch = true` via `pytest-cov` | The whole point of D-06; coverage.py reports partial branches (`X->Y`, `->exit`). |
| Reading the schedule plan | Re-deriving CronTrigger fire times | `scheduler.get_jobs()` + `job.trigger`/`job.next_run_time` | The live APScheduler objects ARE the plan; `_register_jobs` already builds them. |

**Key insight:** This phase is almost entirely *reading existing seams and pinning their output*. The codebase already exposes every surface gateway-free (the v1.1–v1.3 test discipline did the hard work). The only genuinely new code is (a) ~5 small serializer/reader helpers, (b) the `[tool.coverage.*]` config block, and (c) the exception-identity enumeration. Resist building anything more.

## Runtime State Inventory

> Phase 21 is **purely additive test infrastructure** (no source/production code change, no rename/refactor/migration). A Runtime State Inventory (stored data / live service config / OS-registered state / secrets / build artifacts) is **not applicable** — nothing is renamed or moved in this phase; the moves happen in Phases 22–28. The goldens this phase writes are themselves the inventory that those later phases verify against.

**Verified:** Phase scope (CONTEXT `<domain>`, `<code_context>` "No source/production code changes") confirms additive-only. **None found in any category** — by design, this phase touches only `tests/` + `pyproject.toml` `[dependency-groups]`/`[tool.coverage.*]`.

## Common Pitfalls

### Pitfall 1: `embed.timestamp` (and any unfrozen clock) silently flakes the golden
**What goes wrong:** `render_embed`/`build_inbound_embed` set `embed.timestamp = discord.utils.utcnow()` (bot.py:272, 421). If snapshotted, it changes every run.
**Why it happens:** It's a wall-clock value not derived through the frozen path unless `time-machine` is active.
**How to avoid:** EXCLUDE `embed.timestamp` from the golden projection (it's already outside the byte contract per `test_weather_spec_byte_identical`'s docstring), OR freeze the clock so it's a stable literal (D-11). The `Updated <t:…>` description line, by contrast, IS kept (frozen, format preserved).
**Warning signs:** A golden that passes on regen but fails on the next run with only a timestamp diff.

### Pitfall 2: Amber serializer reorders dict keys → field-reorder contract is dead
**What goes wrong:** Using syrupy's default extension for the structured payloads.
**Why it happens:** Amber is the default; it's easy to forget `use_extension(JSONSnapshotExtension)`.
**How to avoid:** A module-scoped `json_snapshot` fixture (Pattern 2) so no structured golden uses the default. Add the D-12 self-proof (field reorder must FAIL) as the guard that this didn't regress.
**Warning signs:** The D-12 perturbation meta-test passes when it should be raising `AssertionError`.

### Pitfall 3: `next_run_time` is `None` on a pending scheduler
**What goes wrong:** A never-started `BackgroundScheduler` may leave `job.next_run_time = None`, so the schedule golden captures `None` instead of a fire time.
**Why it happens:** APScheduler computes `next_run_time` at start; before that it can be unset (this is exactly why `state.py:_next_fire` has the `trigger.get_next_fire_time` fallback).
**How to avoid:** Snapshot `str(job.trigger)` as the byte-exact primary (deterministic regardless of start) and compute the frozen `next_run_time` via the same `CronTrigger.get_next_fire_time(None, datetime.now(tz))` fallback `DaemonState.next_fires()` uses, under a `time-machine` freeze.
**Warning signs:** Schedule golden full of `"next_run_time": null`.

### Pitfall 4: `time-machine` not reaching `discord.utils.utcnow`
**What goes wrong:** The `Updated <t:…>` epoch isn't frozen because the freeze didn't intercept `discord.utils.utcnow`.
**Why it happens:** `discord.utils.utcnow()` is `datetime.now(timezone.utc)` under the hood — `time-machine` patches `datetime`, so it *should* propagate, but confirm.
**How to avoid:** Wave-0 smoke test: assert the `{unix}` in the description equals the frozen instant's epoch. If it doesn't, freeze via `monkeypatch.setattr("weatherbot.interactive.bot.discord.utils.utcnow", lambda: FROZEN)` as a fallback.
**Warning signs:** The frozen-stamp test fails with a near-now epoch.

### Pitfall 5: CLI golden depends on env/secrets or hits the network
**What goes wrong:** `cli.main(["weather", ...])` calls `load_settings()` (reads `.env` / `OPENWEATHER_API_KEY`) and `lookup_weather` (network fetch).
**Why it happens:** `main` is the composition root; some subcommands fetch.
**How to avoid:** Drive CLI goldens the way `tests/test_cli.py` already does — inject a fake client / `load_fixture` recorded JSON, monkeypatch `weatherbot.cli.time.sleep`, and use offline subcommands (`check-config`, `help`, `locations`, `status`) or fixture-backed fetches. The `weather`/forecast variant goldens reuse the `test_cli.py:test_weather_*` fixture-injection idiom (`capsys`, recorded `onecall_*` JSON, fixed clock).
**Warning signs:** A golden that needs a real API key or makes an HTTP call.

## Code Examples

### CLI exit-code + stdout golden (offline subcommand)
```python
# Source: tests/test_cli.py:305 (main(["check", "--config", str(bad)])) + capsys idiom
from weatherbot.cli import main

def test_help_stdout_golden(bytes_snapshot, capsys):
    rc = main(["help"])                      # `help` needs no config (cli.py:836)
    out = capsys.readouterr().out
    assert rc == 0                            # inline literal pin (D-03) — exit code
    assert out.encode() == bytes_snapshot     # raw-bytes stdout golden (D-02)
```

### Panel `custom_id` byte pins (D-03 inline + SingleFile)
```python
# Source: weatherbot/interactive/panel.py — CmdButton custom_id=f"wb:cmd:{name}",
# LocationSelect custom_id="wb:loc:select", ForecastButton ids "wb:fc:<day>:<variant>"
# Build via the same gateway-free stand-ins tests/test_panel.py uses (_FakeHolder/_SpyCache).
def test_panel_marker_pin(panel_view):
    assert panel_view.children[0].custom_id == "wb:loc:select"      # inline literal (D-03)

_EXPECTED_IDS = (                                                    # byte-exact, from test_panel.py:642
    "wb:loc:select",
    "wb:cmd:weather", "wb:cmd:uv", "wb:cmd:next-cloudy", "wb:cmd:sun", "wb:cmd:wind",
    "wb:cmd:status", "wb:cmd:alerts",
    "wb:fc:weekday:detailed", "wb:fc:weekday:compact",
    "wb:fc:weekend:detailed", "wb:fc:weekend:compact",
)
```

### D-12 oracle self-proof (perturbation must FAIL)
```python
# Source: D-12 — a standing meta-test proving the oracle's teeth.
import pytest

def test_field_reorder_is_caught():
    good = {"fields": [{"name": "Now", "value": "20°C"}, {"name": "Rain", "value": "30%"}]}
    reordered = {"fields": [{"name": "Rain", "value": "30%"}, {"name": "Now", "value": "20°C"}]}
    with pytest.raises(AssertionError):
        assert good == reordered          # an order-INSENSITIVE compare would NOT raise → red

def test_custom_id_byteflip_is_caught():
    with pytest.raises(AssertionError):
        assert b"wb:cmd:weather" == b"wb:cmd:weathar"
```
(The real D-12 test should drive an actual `render_embed` output + a real `custom_id` so it also fails if `render_embed`/the panel is ever made to emit a loosened shape.)

### D-13 exception-identity pin
```python
# Source: enumerated move-path types below.
import httpx, discord
from weatherbot.reliability import is_transient   # the caller's import path

def test_httpstatuserror_identity():
    # (1) is-identity through the path other code catches it (cli.py / bot.py catch httpx.HTTPStatusError)
    assert httpx.HTTPStatusError is httpx.HTTPStatusError
    # (2) frozen (__module__, __qualname__) — a re-home/rename fails loud
    assert (httpx.HTTPStatusError.__module__, httpx.HTTPStatusError.__qualname__) == \
        ("httpx", "HTTPStatusError")

def test_unknownlocationerror_identity():
    from weatherbot.interactive.lookup import UnknownLocationError
    assert (UnknownLocationError.__module__, UnknownLocationError.__qualname__) == \
        ("weatherbot.interactive.lookup", "UnknownLocationError")
```

## Move-Path Exception Inventory (D-13 — enumerated from the actual source)

The "move-path" caught error types, with the import path other code catches them through and their frozen identity tuple. **These are the candidates the planner pins** (final selection is Claude's-discretion per CONTEXT, but this is the verified set):

| Exception | Caught in (move-path) | Import path other code catches it through | `(__module__, __qualname__)` |
|-----------|----------------------|-------------------------------------------|------------------------------|
| `httpx.HTTPStatusError` | `reliability/retry.py:89,172` (`is_transient`/`two_burst_wait`); `cli.py:242,318,372,604` | `import httpx` → `httpx.HTTPStatusError` | `("httpx", "HTTPStatusError")` `[VERIFIED: retry.py:89]` |
| `httpx.TimeoutException` | `reliability/retry.py:87`; `cli.py:247,322,607` | `httpx.TimeoutException` | `("httpx", "TimeoutException")` `[VERIFIED]` |
| `httpx.ConnectError` | `reliability/retry.py:87`; `cli.py:247,322,607` | `httpx.ConnectError` | `("httpx", "ConnectError")` `[VERIFIED]` |
| `httpx.ReadError` | `reliability/retry.py:87`; `cli.py:247,322,607` | `httpx.ReadError` | `("httpx", "ReadError")` `[VERIFIED]` |
| `discord.LoginFailure` | `interactive/bot.py:695` (`BotThread._run`) | `import discord` → `discord.LoginFailure` | `("discord.errors", "LoginFailure")` `[ASSUMED: discord.py re-exports from discord.errors — confirm in Wave 0]` |
| `discord.Forbidden` | `interactive/bot.py:391` (`_handle_panel_summon` TOCTOU backstop) | `discord.Forbidden` | `("discord.errors", "Forbidden")` `[ASSUMED: discord.errors home — confirm]` |
| `UnknownLocationError` (IS-A `ValueError`) | `cli.py:312,600`; `interactive/bot.py:520` | `from weatherbot.interactive.lookup import UnknownLocationError` (re-exported via `weatherbot.interactive`) | `("weatherbot.interactive.lookup", "UnknownLocationError")` `[ASSUMED: home module — confirm exact __module__ in Wave 0]` |
| `tenacity.RetryError` | referenced in `reliability/retry.py` docstring (avoided via `retry_error_callback`); `cli.py` uses `reraise=True` | `from tenacity import RetryError` | `("tenacity", "RetryError")` `[ASSUMED: confirm tenacity's qualname]` |
| `pydantic.ValidationError` | `cli.py:536,908` (config load) | `from pydantic import ValidationError` | `("pydantic", "ValidationError")` `[ASSUMED: pydantic v2 re-export — confirm]` |

**Planner note:** The *load-bearing* identity pins are the ones a later re-home could break: `UnknownLocationError` (app type, moves with the registry/dispatch in Phase 26) and any WeatherBot-internal error. Third-party types (`httpx.*`, `discord.*`, `tenacity.*`, `pydantic.*`) are pinned too (their identity is what `except` clauses in the moved modules rely on — if a moved module imports them via a different path, the pin catches it), but they are stable across the extraction. Confirm every `__module__`/`__qualname__` empirically in Wave 0 (`python -c "import httpx; print(httpx.HTTPStatusError.__module__, httpx.HTTPStatusError.__qualname__)"`) rather than trusting the `[ASSUMED]` rows.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Amber `.ambr` default snapshots | `JSONSnapshotExtension` for order-sensitive structured data | syrupy 2.x+ | JSON ext is the right tool for the field-reorder contract; Amber for human-readable non-ordered. |
| `coverage run -m pytest` out-of-band | `pytest-cov` (`--cov`/`--cov-branch` inside the run) | long-standing | D-05 locks the in-run form; config lives in `pyproject.toml` `[tool.coverage.*]`. |
| `freezegun` | `time-machine` | ~2021+ | Already the suite's dep; faster, C-backed, handles `datetime.now(tz)`. |

**Deprecated/outdated:** nothing in this phase's stack is deprecated. syrupy 5.x requires Python ≥3.10 (repo is 3.12+) and pytest ≥8 (repo is 9.0.3) — both satisfied.

## coverage.py Configuration (D-06/D-07/D-08/D-09)

The exact `pyproject.toml` block the planner should add (scoped to the 6 move-path packages, branch mode on, no standing gate):

```toml
[tool.coverage.run]
branch = true                          # D-06 — branch (not line) coverage is mandatory
source = [                             # D-07 — move-path packages ONLY
    "weatherbot/channels",
    "weatherbot/scheduler",
    "weatherbot/config",
    "weatherbot/reliability",
    "weatherbot/ops",
    "weatherbot/interactive",
]
# NOTE: weatherbot/weather (incl. store.py) is deliberately OUT of coverage scope
# (it stays app-side, D-07) — even though store.py's DB rows ARE snapshotted. The DB-row
# golden pins store.py output; the coverage AUDIT does not measure store.py branches.

[tool.coverage.report]
show_missing = true                    # term-missing equivalent
exclude_also = [                       # D-09 — systematic defensive patterns in config, not scattered pragmas
    "if TYPE_CHECKING:",               # type-only import blocks (used across the move-path pkgs)
    "raise NotImplementedError",
    "\\.\\.\\.",                       # bare ellipsis bodies (Protocol stubs)
]
# partial_also (coverage 7.x) — for partial-branch exclusions (e.g. an `if x: ...  # pragma: no branch`)
# partial_also = [ ... ]   # add only if a specific defensive partial branch is unreachable-by-design
```

**One-time audit invocation (D-08):**
```bash
uv run pytest --cov --cov-branch --cov-report=term-missing
# `--cov` (no arg) uses the [tool.coverage.run] source list above.
```

**Reading partial-branch misses (D-06 is the whole point):** in `term-missing`, line coverage shows `Missing` line numbers; **branch** coverage adds partial-branch notation:
- `123->exit` — the branch at line 123 never took the path that exits the function/loop (e.g. an `if` whose false-path falls through to return was never exercised false).
- `123->125` — the branch at line 123 never jumped to line 125 (one side of an `if`/`else` untaken).
- A line listed with a `partial` marker / `->` arrow is an **untaken branch side** — exactly the extraction risk D-06 targets (an `except`/`else` that behaves differently in the new package but is invisible to observable-output goldens). Each such miss on a move path gets a characterization test (D-08), then the audit is re-run clean and recorded in the phase log.

**`# pragma: no cover` convention (D-09):** the repo already uses `# pragma: no cover - <reason>` in test files (e.g. `tests/test_uv_monitor.py:87 "# pragma: no cover - must not run"`, `tests/test_cli.py:895`, `tests/test_registry.py:34`, `tests/test_bot.py:220`). **No `pragma: no cover` exists in `weatherbot/` source today** `[VERIFIED: grep weatherbot/]` — so any pragma added during the audit is new and MUST name its reason. Prefer `exclude_also`/`partial_also` in config for systematic patterns (D-09) over scattered inline pragmas.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `snapshot.use_extension(JSONSnapshotExtension)` / `use_extension(SingleFileSnapshotExtension)` is the exact per-test selection API in syrupy 5.3.4 | Pattern 2 | LOW — well-documented; Wave-0 smoke confirms. Fix: module-scoped fixture or `pytest.mark`. |
| A2 | `snapshot(name="...")` is the call form for named snapshots in 5.3.4 | Pattern 3 | LOW — cosmetic (auto-indexing works without it). |
| A3 | `time_machine.travel(FROZEN, tick=False)` freezes `discord.utils.utcnow()` (→ the `Updated` epoch) | Pattern 4 / Pitfall 4 | MEDIUM — if it doesn't propagate, fall back to monkeypatching `discord.utils.utcnow`. Wave-0 must verify. |
| A4 | `discord.LoginFailure` / `discord.Forbidden` have `__module__ == "discord.errors"` | Exception Inventory | LOW — only the frozen tuple's literal value; confirm with one `python -c`. |
| A5 | `UnknownLocationError.__module__ == "weatherbot.interactive.lookup"` | Exception Inventory | MEDIUM — this is an APP type that MOVES in Phase 26; the exact home string is the load-bearing pin. Confirm empirically in Wave 0. |
| A6 | `tenacity.RetryError` / `pydantic.ValidationError` qualnames as listed | Exception Inventory | LOW — third-party, stable; confirm with `python -c`. |
| A7 | `str(job.trigger)` (CronTrigger `__str__`) is stable/deterministic across runs | Pattern 5 | LOW — APScheduler 3.x CronTrigger `__str__` is deterministic; Wave-0 snapshot confirms. |

**Resolution:** Every `[ASSUMED]` row should be discharged with a one-line `python -c` / Wave-0 smoke at the start of execution (cheap, deterministic). None block planning.

## Open Questions

1. **Does `time-machine` reach `discord.utils.utcnow`?**
   - What we know: `discord.utils.utcnow()` returns `datetime.now(timezone.utc)`; `time-machine` patches the stdlib `datetime`.
   - What's unclear: whether discord.py caches/imports `datetime` in a way that escapes the patch.
   - Recommendation: Wave-0 one-liner asserting the frozen epoch appears in `render_embed(...).description`; fall back to a targeted monkeypatch if needed.

2. **Schedule golden: snapshot pending or computed `next_run_time`?**
   - What we know: a not-started scheduler may report `next_run_time=None`; `str(job.trigger)` is always deterministic.
   - What's unclear: whether the planner wants the frozen *computed* next-fire (via the `get_next_fire_time` fallback) in the golden or only the trigger spec.
   - Recommendation: snapshot BOTH — `str(job.trigger)` (the byte-exact primary, always present) and a frozen `next_run_time` computed via the same fallback `DaemonState.next_fires()` uses (the secondary, under `time-machine`). This matches CONTEXT's `(job_id, trigger spec, next_run_time)` triple exactly.

3. **Is the optional D-13 behavioral except-catch backstop worth including?**
   - Recommendation: include ONE thin end-to-end test (raise a real `httpx.HTTPStatusError` 429 through `is_transient` and assert it's classified transient) as a backstop, but keep the `is`-identity + frozen-tuple asserts as the primary pins. Low cost, proves the `except` still catches.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `pytest` | the whole harness | ✓ | 9.0.3 | — |
| `time-machine` | D-11 freeze | ✓ | ≥2.16 (dev dep) | `monkeypatch` datetime (worse) |
| `discord.py` | embed/panel objects | ✓ | 2.7.1 | — |
| `apscheduler` | schedule plan | ✓ | ≥3.11.2,<4 | — |
| `syrupy` | snapshots (D-01) | ✗ — **not yet installed** | install ≥5.3.4 | inline literal pins (D-03) cover the smallest cases only |
| `pytest-cov` | branch audit (D-05) | ✗ — **not yet installed** | install ≥7.1.0 | raw `coverage` (rejected by D-05) |
| `uv` | add the two dev deps | ✓ (project standard) | — | `pip install` into `.venv` |

**Missing dependencies with no fallback:** none — both missing deps are installed by the phase's first task (`uv add --dev syrupy pytest-cov`).
**Missing dependencies with fallback:** `syrupy`/`pytest-cov` are the locked tools; their "fallback" (inline pins / raw coverage) is explicitly rejected by CONTEXT, so the install task is a hard prerequisite, not optional.

## Validation Architecture

> `workflow.nyquist_validation` is not disabled — section included. This phase IS the validation layer, so the map below ties each ROADMAP success criterion + BHV-01/BHV-02 to a concrete, observable signal a VALIDATION.md can assert.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + syrupy ≥5.3.4 + pytest-cov ≥7.1.0 |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]` exists; ADD `[tool.coverage.run]`/`[tool.coverage.report]`) |
| Quick run command | `uv run pytest tests/test_golden_*.py -x` (the new goldens only) |
| Full suite command | `uv run pytest` (652 existing + new goldens) |
| Branch audit command | `uv run pytest --cov --cov-branch --cov-report=term-missing` (one-time, D-08) |

### Phase Requirements / Success Criteria → Test Map
| Req / SC | Behavior | Test Type | Automated Command / Artifact | File Exists? |
|----------|----------|-----------|------------------------------|--------------|
| **SC1** / BHV-02 (embeds) | Full rendered embeds per command × 📍/Updated states are byte-exact | golden (JSON) | `uv run pytest tests/test_golden_embeds.py` → `tests/__snapshots__/test_golden_embeds/*.json` | ❌ Wave 0 |
| **SC1** / BHV-02 (CLI) | CLI stdout + exit code per subcommand × forecast variant byte-exact | golden (SingleFile) + inline exit pin | `uv run pytest tests/test_golden_cli.py` → `__snapshots__/test_golden_cli/*` | ❌ Wave 0 |
| **SC1** / BHV-02 (schedule) | `(job_id, trigger spec, next_run_time)` plan byte-exact | golden (JSON, frozen) | `uv run pytest tests/test_golden_schedule.py` | ❌ Wave 0 |
| **SC1** / BHV-02 (DB rows) | `weather_onecall`/`alerts`/`sent_log` rows a briefing writes byte-exact | golden (JSON, scrubbed+ORDER BY) | `uv run pytest tests/test_golden_db.py` | ❌ Wave 0 |
| **SC1** / BHV-02 (custom_ids) | Panel `custom_id`s (incl. `wb:` marker) byte-exact | inline pin (D-03) + SingleFile | `uv run pytest tests/test_golden_custom_ids.py` | ❌ Wave 0 |
| **SC2** | A deliberate field-reorder / `custom_id` byte-flip makes a golden FAIL | meta-test (`pytest.raises(AssertionError)`) | `uv run pytest tests/test_oracle_selfproof.py` | ❌ Wave 0 |
| **SC3** | Move-path error types pinned via import-path `is`-identity + frozen `(__module__,__qualname__)` | identity test | `uv run pytest tests/test_exception_identity.py` | ❌ Wave 0 |
| **SC4** | No uncovered branch on a move path (gaps filled with characterization tests) | one-time branch audit | `uv run pytest --cov --cov-branch --cov-report=term-missing` → clean audit recorded in phase log | ❌ Wave 0 |
| **BHV-01** | Full pre-existing suite stays green (no skips/weakened assertions) | regression | `uv run pytest` → 652 + new goldens green | ✓ (652 tests exist) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_golden_*.py -x` (fast — goldens only).
- **Per wave merge:** `uv run pytest` (full suite, BHV-01 gate).
- **Phase gate:** Full suite green + the one-time branch audit recorded clean + the D-12 self-proof green BEFORE `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `uv add --dev "syrupy>=5.3.4" "pytest-cov>=7.1.0"` — the two locked tools (hard prereq).
- [ ] `[tool.coverage.run]` + `[tool.coverage.report]` block in `pyproject.toml` (config above).
- [ ] `tests/conftest.py` additions: a shared `FROZEN` instant constant + `json_snapshot`/`bytes_snapshot` fixtures + `embed_to_golden` helper (reuses existing `_FakeHolder`/`_SpyCache`/`load_fixture`/`tmp_db`).
- [ ] `tests/test_golden_embeds.py`, `test_golden_cli.py`, `test_golden_schedule.py`, `test_golden_db.py`, `test_golden_custom_ids.py`, `test_oracle_selfproof.py`, `test_exception_identity.py` (RED scaffolds → goldens).
- [ ] `tests/__snapshots__/` committed after first `--snapshot-update` (D-04).
- [ ] Discharge the `[ASSUMED]` rows (A1–A7) with one-line `python -c` confirms.

## Security Domain

> `security_enforcement` is not disabled. This phase is additive test infrastructure — it ships no new request handler, auth path, crypto, or data sink. The only security-adjacent surface is **secret hygiene in the goldens**, which is load-bearing because the snapshots are committed.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth path added. |
| V3 Session Management | no | — |
| V4 Access Control | no | The operator gate already exists and is unchanged; goldens only READ it. |
| V5 Input Validation | no (read-only) | Goldens consume recorded fixtures, not live input. |
| V6 Cryptography | no | No crypto. |
| **V7 Secret/Log hygiene** | **yes** | A committed golden must NEVER contain the OpenWeather `appid`, the Discord webhook URL, or the bot token. The repo already enforces "outcome-only, never a secret" (T-04-01) across `store.py`/`retry.py`/`cli.py`; the goldens inherit this because they snapshot only *rendered output* (embed fields, CLI stdout, DB rows that store only response payloads — `store.py:18-20` confirms the request URL carrying `appid` is never persisted). |

### Known Threat Patterns for {committed golden snapshots}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A secret (token/`appid`/webhook URL) leaks into a committed `__snapshots__` file | Information Disclosure | Drive every golden through the existing gateway-free fakes (`fake_interaction`, fixture-injected client) which carry NO real secret (placeholder ids only, per conftest T-17-01-01); snapshot only rendered surfaces (embed fields / CLI stdout / response-payload DB rows). Review each new golden file once before committing. |
| CLI stdout golden captures an env-dependent value (path, key) | Information Disclosure | Use offline subcommands (`help`/`check-config`) or fixture-backed fetches; never let `load_settings()`'s real `.env` reach a snapshot. |
| DB-row golden includes `raw_json` that embedded a request URL | Information Disclosure | `store.py` already stores only the OpenWeather *response* payload (`store.py` docstring: "the request URL (which carries the appid) is never persisted") — the golden inherits this; verify no URL/key string appears in the committed `raw_json`. |

## Sources

### Primary (HIGH confidence)
- WeatherBot source (read in this session): `weatherbot/interactive/bot.py` (`render_embed`/`build_inbound_embed`/`BotThread`), `weatherbot/interactive/panel.py` (`custom_id`s, `_PANEL_MARKER`), `weatherbot/interactive/state.py` (`DaemonState.next_fires`/`_next_fire`), `weatherbot/weather/store.py` (schema + `persist`/`claim_slot`/`record_alert`), `weatherbot/reliability/retry.py` + `__init__.py` (exception classifiers), `weatherbot/cli.py` (`main(argv)` + caught error types), `weatherbot/scheduler/daemon.py:596-680` (`_register_jobs`).
- WeatherBot tests: `tests/conftest.py` (all fakes/fixtures), `tests/test_panel.py` (`test_weather_spec_byte_identical` inline byte-pin), `tests/test_cli.py` (`main(argv)`+`capsys` idiom), `tests/test_status.py` (`_FakeJob`/`_job_id` schedule-read), `tests/test_reliability.py:631-647` (`_register_jobs` + `get_jobs`), `tests/test_store.py` (row reads), `tests/test_reload.py`/`test_filewatch.py` (`get_jobs()` plan reads).
- `pyproject.toml` (pinned versions), `.planning/REQUIREMENTS.md` (BHV-01/02), `.planning/ROADMAP.md` §Phase 21 (4 SCs), `.planning/phases/21-.../21-CONTEXT.md` (D-01..D-13).
- PyPI JSON: `pypi.org/pypi/syrupy/json` (5.3.4, py≥3.10, pytest≥8.0.0), `pypi.org/pypi/pytest-cov/json` (7.1.0, requires-dist), `pypi.org/pypi/coverage/json` (7.14.3).
- `pytest --co -q` → 652 tests; `pytest --version` → 9.0.3.

### Secondary (MEDIUM confidence)
- syrupy docs (`syrupy-project.github.io/syrupy` — Extensions: JSONSnapshotExtension / SingleFileSnapshotExtension) via WebSearch; exact `use_extension`/`name=` call forms flagged `[ASSUMED]` for Wave-0 confirmation.
- coverage.py branch-mode semantics (`X->Y` / `->exit` partial-branch notation) — standard coverage.py behavior.

### Tertiary (LOW confidence)
- `discord.errors` home for `LoginFailure`/`Forbidden`, `tenacity`/`pydantic` qualnames — `[ASSUMED]`, one-line `python -c` confirms in Wave 0.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified against PyPI; tools locked by CONTEXT; compatibility with pytest 9.0.3 confirmed.
- Architecture / repo seams: HIGH — every render/DB/dispatch/schedule seam read directly from source with line references.
- Determinism mechanics: MEDIUM-HIGH — `time-machine` is the established suite pattern; the one open item (does it reach `discord.utils.utcnow`) is a cheap Wave-0 confirm.
- Exception identity: MEDIUM — the caught types are verified from source; the exact `(__module__, __qualname__)` literals for third-party + the moving `UnknownLocationError` are flagged `[ASSUMED]` pending a one-line confirm.
- syrupy call-form details: MEDIUM — documented but not run in-session (tool not yet installed); Wave-0 smoke discharges.

**Research date:** 2026-06-27
**Valid until:** 2026-07-27 (stable stack; re-check syrupy/pytest-cov if pytest 10 lands or a major syrupy release ships).
