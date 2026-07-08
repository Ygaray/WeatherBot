# Phase 21: Characterization / Golden-Test Harness - Pattern Map

**Mapped:** 2026-06-27
**Files analyzed:** 9 new test files + 2 modified (conftest.py, pyproject.toml)
**Analogs found:** 9 / 9 (every new file maps to a shipped test seam — the suite already drives every surface gateway-free)

> This phase is **purely additive test infrastructure**. No source/production file is
> touched. Every "new file" is a test that *reads an existing seam and pins its output*.
> The planner can write each new test file by **direct analogy** to the analog below —
> the seams, fixtures, and read idioms already exist and are battle-tested across 652
> green tests. The genuinely-new code is ~5 small serializer/reader helpers, a
> `[tool.coverage.*]` block, and an exception enumeration.

---

## File Classification

| New/Modified File | Role | Data Flow (seam driven) | Closest Analog | Match Quality |
|-------------------|------|-------------------------|----------------|---------------|
| `tests/conftest.py` (MODIFY — add helpers/fixtures) | test fixtures | shared-harness | `tests/conftest.py` (itself) | self / exact |
| `tests/test_golden_embeds.py` | golden snapshot test | embed render → ordered dict | `tests/test_panel.py::test_weather_spec_byte_identical` | exact |
| `tests/test_golden_cli.py` | golden snapshot test | `cli.main(argv)` → exit-int + `capsys` stdout | `tests/test_cli.py` (`_FakeClient` + `capsys` idiom) | exact |
| `tests/test_golden_schedule.py` | golden snapshot test | `_register_jobs` → `scheduler.get_jobs()` plan | `tests/test_reliability.py::test_heartbeat_job_registered_with_slots` + `tests/test_status.py` | exact |
| `tests/test_golden_db.py` | golden snapshot test | `persist`/`claim_slot`/`record_alert` → `SELECT … ORDER BY` | `tests/test_store.py` (`_connect` + `conn.execute`) | exact |
| `tests/test_golden_custom_ids.py` | exception/byte-identity pin (inline + SingleFile) | `PanelView.children` → `custom_id` byte strings | `tests/test_panel.py` (`_FC_SUBGRID_IDS`, `_make_panel`) | exact |
| `tests/test_oracle_selfproof.py` | oracle self-proof meta-test | `pytest.raises(AssertionError)` over a perturbed render | `tests/test_panel.py::test_callback_raise_isolated` (raises-discipline) | role-match |
| `tests/test_exception_identity.py` | exception-identity pin | `is`-identity + `(__module__,__qualname__)` introspection | (no test analog — pure introspection; see "No Analog" + verified table) | new (verified) |
| `tests/__snapshots__/` (NEW dir) | committed golden artifacts | syrupy write target | — (syrupy-managed) | n/a |
| `pyproject.toml` (MODIFY — `[tool.coverage.*]` + 2 dev deps) | config | coverage-audit | existing `[tool.pytest.ini_options]` / `[dependency-groups]` | role-match |

---

## Shared Patterns

These cross-cutting patterns apply to **every** golden file. Put the helpers in
`tests/conftest.py` (the Wave-0 modification) so no per-module copy drifts.

### Gateway-free drive seams (reuse verbatim — DO NOT rebuild)
**Source:** `tests/conftest.py`
**Apply to:** all golden files
Already-shipped fixtures the goldens consume directly — no new fakes needed:
- `load_fixture` (line 21-24) — recorded OpenWeather JSON loader; the frozen-forecast input.
- `tmp_db` (line 47-54) — fresh isolated SQLite path; store creates schema on first connect.
- `seed_sent_row` (line 95-98) — writes a real `sent_log` row via shipped `claim_slot`.
- `fake_interaction` (line 226-229) — gateway-free `discord.Interaction` (`custom_id`, operator gate).
- `holder_scheduler` (line 337-364) — `(ConfigHolder, NOT-started BackgroundScheduler, db_path)`.
- `_FakeHolder` / `_SpyCache` / `_FakeForecast` / `_make_panel` from `tests/test_panel.py:87-140`
  (module-local, not conftest — copy or import for the panel/embed goldens).

### Frozen clock (D-11 — freeze, don't scrub)
**Source:** `time-machine` (already a dev dep); freeze idiom is the suite's established pattern.
**Apply to:** every golden that captures a clock-derived value (`Updated <t:…>`, `next_run_time`, `*_at_utc`, `target_local_date`).
```python
import time_machine
from datetime import datetime, timezone

FROZEN = datetime(2026, 6, 20, 13, 0, 0, tzinfo=timezone.utc)  # shared constant in conftest (D-11 discretion: pick one)

with time_machine.travel(FROZEN, tick=False):
    embed = render_embed(reply, location="home")
# The golden then contains the LITERAL `Updated <t:1750424400:t> (<t:1750424400:R>)`
# — epoch frozen, the :t/:R FORMAT string preserved (over-scrubbing trap, D-11).
```
**Wave-0 confirm (Open Q1 / A3):** verify `time_machine.travel` reaches `discord.utils.utcnow()`
(it calls `datetime.now(timezone.utc)`, so it should). Fallback:
`monkeypatch.setattr("weatherbot.interactive.bot.discord.utils.utcnow", lambda: FROZEN)`.

### syrupy extension selection (D-02)
**Source:** syrupy docs; new Wave-0 fixtures in `tests/conftest.py`.
**Apply to:** JSON for structured (embeds/plan/rows), SingleFile for raw bytes (custom_id/stdout).
```python
import pytest
from syrupy.extensions.json import JSONSnapshotExtension
from syrupy.extensions.single_file import SingleFileSnapshotExtension

@pytest.fixture
def json_snapshot(snapshot):
    return snapshot.use_extension(JSONSnapshotExtension)   # order-preserving — catches field reorder

@pytest.fixture
def bytes_snapshot(snapshot):
    return snapshot.use_extension(SingleFileSnapshotExtension)  # raw bytes — one flip fails
```
`[A1: confirm use_extension call shape against installed syrupy 5.3.4 in Wave 0]`

### `# pragma: no cover - <reason>` discipline (D-09)
**Source:** existing convention in `tests/test_uv_monitor.py:87`, `tests/test_cli.py:895`,
`tests/test_registry.py:34`, `tests/test_bot.py:220` (`# pragma: no cover - <reason>`).
**Apply to:** any branch the coverage audit can't reach. **No pragma exists in `weatherbot/`
source today** — any added must NAME its reason. Prefer `exclude_also`/`partial_also` in
`pyproject.toml` for systematic patterns over scattered inline pragmas.

---

## Pattern Assignments

### `tests/test_golden_embeds.py` (golden, embed render → ordered dict)

**Analog:** `tests/test_panel.py::test_weather_spec_byte_identical` (lines 470-492)

**Existing field-read idiom to extend** (test_panel.py:487-488):
```python
panel_fields = [(f.name, f.value) for f in panel_embed.fields]
reference_fields = [(f.name, f.value) for f in reference_embed.fields]
```
The golden **extends** this: add `description` (where 📍 + Updated live — NOT the title)
and `inline` (so an inline-flip is a real diff), and let syrupy own regen.

**Render seam** (`weatherbot/interactive/bot.py:194`):
```python
def render_embed(reply: CommandReply, *, location: str | None = None) -> discord.Embed:
```
- `location="home"` → 📍 line emitted (bot.py:221-222); `location=None` → 📍 suppressed
  (the 📍-on/off cell of D-10, driven via a location-bearing reply vs an argless status reply).
- `build_inbound_embed(forecast)` (bot.py:402) is the briefing-side render (no `location`).
- `Updated <t:{unix}:t> (<t:{unix}:R>)` is built at bot.py:219-223 from `discord.utils.utcnow()` — freeze it.
- `embed.timestamp = discord.utils.utcnow()` (bot.py:272, 421) is EXCLUDED from the golden
  projection (already outside the byte contract per test_weather_spec_byte_identical's docstring).

**NEW helper to add (`embed_to_golden`, in conftest.py):**
```python
def embed_to_golden(embed) -> dict:
    """Order-preserving, byte-faithful embed projection for JSONSnapshotExtension.
    Includes description (📍 + Updated stamp) and the FULL field tuple incl. `inline`.
    Excludes embed.timestamp (outside the byte contract, D-11)."""
    return {
        "title": embed.title,
        "description": embed.description,
        "color": embed.color.value if embed.color is not None else None,
        "fields": [{"name": f.name, "value": f.value, "inline": f.inline} for f in embed.fields],
    }
```

**Test shape:**
```python
def test_weather_embed_home(json_snapshot, load_fixture):
    with time_machine.travel(FROZEN, tick=False):
        embed = build_inbound_embed(_forecast_from(load_fixture("onecall_metric_clear.json")))
    assert embed_to_golden(embed) == json_snapshot      # → .json under __snapshots__/
```
**Granularity (D-10):** one named case per command (weather/uv/next-cloudy/sun/wind/status/
alerts/forecast variants); 📍-on once (location reply), 📍-off once (argless status). No cartesian.

---

### `tests/test_golden_cli.py` (golden, `cli.main(argv)` → exit-int + capsys stdout)

**Analog:** `tests/test_cli.py` — `_FakeClient` (lines 35-50) + `capsys` idiom (lines 85-100)

**Fixture-injection idiom (test_cli.py:35-50, 87-92):**
```python
class _FakeClient:                       # returns recorded fixtures, records calls — NO network
    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._onecall[units]
# ...
client = _FakeClient(onecall_imp=load_fixture("onecall_imperial_clear.json"),
                     onecall_met=load_fixture("onecall_metric_clear.json"))
rc = do_geocode("Austin, TX", client=client)   # or main([...]) for the full surface
out = capsys.readouterr().out
assert rc == 0                                  # inline exit-code pin (D-03)
```

**CLI surface** (`weatherbot/cli.py:698` `def main(argv)`, subparsers at 729-837):
subcommands `weather`, `check`, `reload`, `send-now`, `geocode`, `status`, plus registry-driven
specs (cli.py:837). Each handler returns an int (`return 0`/`return 1` at 246-953).

**Golden shape (offline subcommand — no secret, no network, Pitfall 5):**
```python
def test_help_stdout_golden(bytes_snapshot, capsys):
    rc = main(["help"])
    out = capsys.readouterr().out
    assert rc == 0                          # inline literal pin (D-03)
    assert out.encode() == bytes_snapshot   # raw-bytes stdout golden (D-02 — one byte flip fails)
```
For `weather`/forecast variants reuse the `test_cli.py` `_FakeClient` + recorded `onecall_*`
JSON + frozen clock; monkeypatch `weatherbot.cli.time.sleep` (the test_cli.py precedent) so a
retry pause is instant. **Never** let `load_settings()`'s real `.env` reach a snapshot (V7 hygiene).

---

### `tests/test_golden_schedule.py` (golden, `_register_jobs` → `get_jobs()` plan)

**Analog:** `tests/test_reliability.py::test_heartbeat_job_registered_with_slots` (lines 621-651)
+ `tests/test_status.py` (`_FakeJob`/`DaemonState.next_fires`, lines 34-114)

**Register-then-read idiom (test_reliability.py:627-647) — scheduler NEVER started:**
```python
from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()                 # NOT started — get_jobs() works pending
daemon_mod._register_jobs(scheduler, ConfigHolder(config),
                          db_path=tmp_db, settings=None, stop_event=threading.Event())
job_ids = {job.id for job in scheduler.get_jobs()}
```

**NEW plan-serializer helper:**
```python
def schedule_plan_golden(scheduler):
    plan = [{
        "job_id": job.id,                                          # "{name}|{time}|{days}" / forecast variant
        "trigger": str(job.trigger),                               # CronTrigger.__str__ — byte-exact PRIMARY (deterministic)
        "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
    } for job in scheduler.get_jobs()]
    plan.sort(key=lambda r: r["job_id"])                           # explicit ORDER (D-11), not insertion luck
    return plan
```
**Pitfall 3 (Open Q2):** a pending scheduler may report `next_run_time=None`. Snapshot
`str(job.trigger)` as the byte-exact primary; compute a frozen `next_run_time` via the same
`CronTrigger.get_next_fire_time(None, datetime.now(tz))` fallback `DaemonState.next_fires()`
uses (`weatherbot/interactive/state.py`), under `time_machine.travel`. Use `holder_scheduler`
fixture (conftest.py:337) to avoid thread teardown.

---

### `tests/test_golden_db.py` (golden, `persist`/`claim_slot`/`record_alert` → `SELECT … ORDER BY`)

**Analog:** `tests/test_store.py` — `_connect` (lines 48-50) + `conn.execute(SELECT …)` (84-150)

**Read idiom (test_store.py:48-50, 79-84):**
```python
import sqlite3
def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
# ...
persist(tmp_db, LOC, forecast)            # writes TWO weather_onecall rows (imperial + metric)
with _connect(tmp_db) as conn:
    rows = list(conn.execute("SELECT * FROM weather_onecall"))
```

**Schema (store.py:84-94) — columns to SELECT vs scrub:**
- `weather_onecall`: `location_name, lat, lon, target_local_date, units, raw_json` are the
  byte-contract columns. **Scrub** the autoincrement `id` and `fetched_at_utc` (omit from
  SELECT), OR freeze the clock and keep `fetched_at_utc`/`target_local_date` as frozen
  literals (D-11 preference: freeze what's meaningful, scrub only the rowid).
- `target_local_date` is frozen-clock-derived (`_local_date_iso`, store.py ~193) — freeze it.
- Add an explicit **`ORDER BY units, location_name`** to the read path (D-11 — never sort-scrub).

**NEW reader helper:**
```python
def onecall_rows_golden(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT location_name, lat, lon, target_local_date, units, raw_json "
            "FROM weather_onecall ORDER BY units, location_name"   # id/fetched_at_utc NOT selected → scrubbed
        ).fetchall()
    return [{"location_name": r[0], "lat": r[1], "lon": r[2],
             "target_local_date": r[3], "units": r[4], "raw_json": json.loads(r[5])} for r in rows]
```
**V7 hygiene:** `store.py` persists only the OpenWeather *response* payload (the request URL
carrying `appid` is never stored) — verify no key/URL string appears in committed `raw_json`.
Also cover `sent_log` (via `claim_slot`/`seed_sent_row`) and `alerts` (via `record_alert`).

---

### `tests/test_golden_custom_ids.py` (byte-identity pin: inline + SingleFile)

**Analog:** `tests/test_panel.py` — `_FC_SUBGRID_IDS` (lines 642-647), `_make_panel` (134-140),
`test_view_persistent_and_layout_bounded` child-walk (438-445)

**Construction seam (`weatherbot/interactive/panel.py`):**
- `_PANEL_MARKER == "wb:"` (panel.py:141).
- `CmdButton custom_id=f"wb:cmd:{name}"` (panel.py:194).
- `LocationSelect custom_id="wb:loc:select"` (panel.py:263).
- Forecast buttons: `wb:fc:<day>:<variant>` (the `_FC_SUBGRID_IDS` tuple, test_panel.py:642).

**Child-walk read idiom (test_panel.py:438-445):**
```python
view = _make_panel(panel, holder=_FakeHolder(["home", "travel"]), cache=_SpyCache())
ids = [c.custom_id for c in view.children]
```

**Pin shape (inline D-03 + SingleFile byte golden):**
```python
def test_panel_marker_pin(panel_view):
    assert panel_view.children[0].custom_id == "wb:loc:select"   # inline literal (D-03)

def test_all_custom_ids(bytes_snapshot, panel_view):
    ids = [c.custom_id for c in panel_view.children]
    assert "\n".join(ids).encode() == bytes_snapshot(name="all_custom_ids")  # byte-exact
```
The byte-exact expected set (from test_panel.py / UI-SPEC Copywriting Contract):
`wb:loc:select`, `wb:cmd:{weather,uv,next-cloudy,sun,wind,status,alerts}`,
`wb:fc:weekday:detailed`, `wb:fc:weekday:compact`, `wb:fc:weekend:detailed`, `wb:fc:weekend:compact`.

---

### `tests/test_oracle_selfproof.py` (oracle self-proof meta-test, D-12 / SC2)

**Analog:** `tests/test_panel.py::test_callback_raise_isolated` (lines 500-522) — the
`pytest.raises`/raises-discipline idiom (here inverted: the comparison MUST raise).

**Shape — perturbation MUST FAIL (proves the oracle's teeth):**
```python
import pytest

def test_field_reorder_is_caught(json_snapshot, load_fixture):
    """A field REORDER of a real render must fail the comparison — an order-insensitive
    compare would NOT raise → this test goes red, exposing a loosened oracle."""
    with time_machine.travel(FROZEN, tick=False):
        good = embed_to_golden(build_inbound_embed(_forecast_from(load_fixture("onecall_metric_clear.json"))))
    reordered = {**good, "fields": list(reversed(good["fields"]))}
    with pytest.raises(AssertionError):
        assert good == reordered

def test_custom_id_byteflip_is_caught():
    with pytest.raises(AssertionError):
        assert b"wb:cmd:weather" == b"wb:cmd:weathar"
```
Drive an ACTUAL `render_embed`/`build_inbound_embed` output + a real `custom_id` (not a hand
literal) so the test also fails if the render/panel is ever loosened. Ships as a STANDING test
(rejected: `xfail(strict=True)` — reads inverted; mutation testing — out-of-band).

---

### `tests/test_exception_identity.py` (exception-identity pin, D-13 / SC3)

**Analog:** none in `tests/` (pure type introspection). Pattern is fully specified in RESEARCH;
the identity tuples are **VERIFIED empirically this session** (see correction below).

**Two asserts per move-path error type (D-13):**
```python
import httpx
def test_httpstatuserror_identity():
    # (1) is-identity through the caller's import path (cli.py/bot.py catch httpx.HTTPStatusError)
    from httpx import HTTPStatusError
    assert HTTPStatusError is httpx.HTTPStatusError
    # (2) frozen (__module__, __qualname__) — a re-home/rename fails loud
    assert (HTTPStatusError.__module__, HTTPStatusError.__qualname__) == ("httpx", "HTTPStatusError")
```
**Avoid `isinstance`** as the pin (permits `except`-broadening — D-13).

**VERIFIED identity tuples (run this session — supersedes the RESEARCH `[ASSUMED]` rows):**

| Exception | Import path other code catches it through | `(__module__, __qualname__)` — VERIFIED |
|-----------|-------------------------------------------|------------------------------------------|
| `httpx.HTTPStatusError` | `import httpx` | `("httpx", "HTTPStatusError")` |
| `httpx.TimeoutException` | `import httpx` | `("httpx", "TimeoutException")` |
| `httpx.ConnectError` | `import httpx` | `("httpx", "ConnectError")` |
| `httpx.ReadError` | `import httpx` | `("httpx", "ReadError")` |
| `discord.LoginFailure` | `import discord` | `("discord.errors", "LoginFailure")` |
| `discord.Forbidden` | `import discord` | `("discord.errors", "Forbidden")` |
| `tenacity.RetryError` | `from tenacity import RetryError` | `("tenacity", "RetryError")` |
| `pydantic.ValidationError` | `from pydantic import ValidationError` | **`("pydantic_core._pydantic_core", "ValidationError")`** ⚠ NOT `"pydantic"` |
| `UnknownLocationError` (app type — MOVES in Phase 26) | `from weatherbot.interactive.lookup import UnknownLocationError` | `("weatherbot.interactive.lookup", "UnknownLocationError")` |

⚠ **Correction:** RESEARCH listed `pydantic.ValidationError` as `("pydantic", "ValidationError")`.
The actual `__module__` is `pydantic_core._pydantic_core` (pydantic v2 re-exports it). The frozen
tuple must use the real value. The **load-bearing** pin is `UnknownLocationError` (app type that
re-homes in Phase 26); third-party tuples are pinned but stable across the extraction.
**Optional D-13 backstop** (planner discretion): one thin behavioral test raising a real
`httpx.HTTPStatusError(429)` through `reliability.is_transient` and asserting it's classified transient.

---

## `pyproject.toml` config block (D-06/D-07/D-08/D-09)

**Analog:** existing `[tool.pytest.ini_options]` / `[dependency-groups]` in `pyproject.toml`.
Add two dev deps (`syrupy>=5.3.4`, `pytest-cov>=7.1.0`) and:
```toml
[tool.coverage.run]
branch = true                          # D-06 — branch (not line) coverage is mandatory
source = [                             # D-07 — move-path packages ONLY
    "weatherbot/channels", "weatherbot/scheduler", "weatherbot/config",
    "weatherbot/reliability", "weatherbot/ops", "weatherbot/interactive",
]
# weatherbot/weather (incl. store.py) is deliberately OUT of scope (stays app-side, D-07)
# — even though store.py's DB rows ARE snapshotted by test_golden_db.py.

[tool.coverage.report]
show_missing = true
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError", "\\.\\.\\."]
```
**One-time audit (D-08, NOT a standing gate):**
`uv run pytest --cov --cov-branch --cov-report=term-missing` → fill each uncovered move-path
branch with a characterization test → record clean audit in the phase log → done.

---

## No Analog Found

| File | Role | Reason |
|------|------|--------|
| `tests/test_exception_identity.py` | exception-identity pin | No existing test does type-identity introspection. Pattern is fully specified by D-13 + the VERIFIED tuple table above — the planner writes it from that table directly, no codebase analog needed. |
| `tests/__snapshots__/` | golden artifacts | syrupy-managed directory, created on first `--snapshot-update`. Not authored by hand. |

---

## Metadata

**Analog search scope:** `tests/` (conftest, test_panel, test_cli, test_reliability, test_store,
test_status), `weatherbot/interactive/{bot,panel}.py`, `weatherbot/weather/store.py`,
`weatherbot/cli.py`, `tests/fixtures/`.
**Files scanned:** ~12 (6 test analogs read in depth; 4 source seams confirmed; 1 empirical
`python -c` identity check).
**Wave-0 assumptions discharged this session:** A4/A5/A6 (exception tuples — VERIFIED, with the
pydantic correction). Still open for Wave 0: A1/A2 (syrupy `use_extension`/`name=` call shape),
A3 (`time_machine` reaching `discord.utils.utcnow`), A7 (`str(job.trigger)` stability).
**Pattern extraction date:** 2026-06-27
