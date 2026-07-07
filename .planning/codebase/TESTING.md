# Testing Patterns

**Analysis Date:** 2026-07-07

## Test Framework

**Runner:**
- `pytest` (>=9.0.3), declared in `[dependency-groups] dev` of `pyproject.toml`.
- Config: `[tool.pytest.ini_options]` in `pyproject.toml`:
  - `testpaths = ["tests"]`
  - `pythonpath = ["."]` — makes both `weatherbot.*` and `tests.*` importable (tests import the shared harness via `from tests.conftest import ...`).
  - `addopts = "-ra"` — show a short summary of all non-passing outcomes.

**Assertion Library:**
- Plain `assert` (pytest rewriting). Snapshot/golden assertions use **syrupy** (`snapshot` fixture).

**Supporting dev deps:**
- `syrupy` (>=5.3.4) — snapshot / golden testing.
- `pytest-cov` (>=7.1.0) — branch coverage (invoked explicitly, not in `addopts`).
- `time-machine` (>=2.16) — deterministic clock freezing for golden tests.
- `grimp` (>=3.14) — import-hygiene graphing (used by `tests/test_import_hygiene.py`).

**Run Commands:**
```bash
uv run pytest                         # Run all tests
uv run pytest tests/test_client.py    # Run one file
uv run pytest -k golden               # Run golden suites
uv run pytest --snapshot-update       # Regenerate syrupy goldens (review the diff!)
uv run pytest \
  --cov --cov-branch --cov-report=term-missing   # Coverage audit (one-time, see below)
```

## ⚠️ Snapshot-Report Exit-0 Quirk (READ THIS)

The suite may print a line like **"N snapshots failed"** / "N snapshots unused" to the report footer **while pytest still exits 0 (all tests pass)**. This is pre-existing syrupy report noise, **not** a golden diff.

- **Trust the process exit code + the actual `.ambr` / `.raw` / `.json` file diff**, not the printed snapshot tally.
- A real golden failure shows up as a **failed test** (non-zero exit) with an inline diff, not merely in the footer summary.
- Before treating a snapshot line as a failure: check `echo $?` and `git diff tests/__snapshots__/`.

## Test File Organization

**Location:**
- All tests live in `tests/` (~20k LOC, 52 `test_*.py` files) — separate from `weatherbot/` source (not co-located).

**Naming:**
- `tests/test_<unit>.py` mirrors the module under test (`test_client.py`, `test_config.py`, `test_store.py`).
- Golden suites: `tests/test_golden_<subject>.py` (`test_golden_embeds.py`, `test_golden_cli.py`, `test_golden_db.py`, `test_golden_schedule.py`, `test_golden_custom_ids.py`, `test_golden_harness.py`).
- Meta / self-proof / gate tests: `test_oracle_selfproof.py`, `test_import_hygiene.py`, `test_module_provenance.py`, `test_exception_identity.py`.

**Structure:**
```
tests/
├── conftest.py                # shared fixtures + golden harness helpers
├── fixtures/                  # recorded OpenWeather JSON (onecall_*, geocode_*)
├── __snapshots__/             # committed syrupy goldens, one dir per golden suite
│   ├── test_golden_cli/       #   *.raw   (SingleFileSnapshotExtension — CLI stdout, custom_ids)
│   ├── test_golden_embeds/    #   *.json  (JSONSnapshotExtension — embed dicts)
│   ├── test_golden_db/        #   DB-row goldens
│   ├── test_golden_schedule/  #   APScheduler job-plan goldens
│   ├── test_golden_custom_ids/
│   ├── test_golden_harness/
│   └── test_oracle_selfproof/
└── test_*.py                  # 52 unit + golden + meta suites
```

## Test Structure

**Suite organization:**
- Function-style tests (`def test_...():`) with a descriptive name and a docstring that states what invariant / requirement (`SC#2`, `T-04-03`, `D-11`) it pins.
- Each test module opens with `from __future__ import annotations` and a module docstring describing the contract under test.

```python
def test_frozen_epoch_reaches_render() -> None:
    """Wave-0 smoke (A3): time_machine.travel(FROZEN) freezes the embed Updated stamp."""
    from weatherbot.interactive.bot import render_embed
    from weatherbot.interactive.commands import CommandReply
    expected_epoch = int(FROZEN.timestamp())
    with time_machine.travel(FROZEN, tick=False):
        embed = render_embed(CommandReply(title="Weather — home"), location="home")
    assert f"Updated <t:{expected_epoch}:t> (<t:{expected_epoch}:R>)" in embed.description
```

## Fixtures

Shared fixtures live in `tests/conftest.py`. Key ones:

- **`load_fixture`** — returns a loader; call with a fixture file name to read recorded OpenWeather JSON from `tests/fixtures/`.
- **`tmp_db`** — a fresh (not-yet-created) SQLite path under `tmp_path`; the store layer creates the schema on first connect, giving per-test DB isolation.
- **`seed_sent_row`** — seeds a real `sent_log` row through the shipped `claim_slot` path (byte-identical to a real fire) so exactly-once/reload tests exercise the real idempotency key, never a mock that always passes.
- **`holder_scheduler`** — builds a `(ConfigHolder, BackgroundScheduler, db_path)` harness with a **NOT-started** scheduler (reload tests assert on `get_jobs()` with no wall-clock waits / threads); defensive teardown shuts down any scheduler a test happened to start.
- **`_redirect_pid_file`** (`autouse=True`) — redirects the daemon's `PID_FILE` off the host `/run` onto a per-test tmp path so startup writes succeed in the sandbox.
- **Gateway-free discord.py builders** (pure `MagicMock`, no discord import, no network):
  - `fake_discord_message` — a `Message`-shaped mock feeding `on_message` (`author.bot`, `author.id`, `content`, `channel.send` as `AsyncMock`, `channel.typing()` as async-CM).
  - `fake_interaction` — an `Interaction`-shaped mock for panel callbacks (`user.id`, `data["custom_id"]`, `response.edit_message`/`send_message` as `AsyncMock`, `response.is_done` as `MagicMock`).
  - `fake_pins` / `fake_pinned_message` / `fake_permissions` — stand-ins for `channel.pins()` (an async iterator), pinned component rows, and `discord.Permissions`.

**Fixture data location:** `tests/fixtures/*.json` — recorded OpenWeather One Call responses (`onecall_imperial_*.json`, `onecall_metric_*.json`, `onecall_8day_*.json`) and geocode responses (`geocode_*.json`). No secrets in fixtures — ids are placeholders.

## Syrupy Snapshot / Golden Tests

Golden tests pin **byte-exact production output** as committed snapshots. Two extension shapes are wired in `conftest.py` (call shape confirmed against syrupy 5.3.4):

- **`json_snapshot`** = `snapshot.use_extension(JSONSnapshotExtension)` — for STRUCTURED payloads (embed dicts, schedule plans, DB rows). **Order-preserving** so a field REORDER surfaces as a real diff (the Amber default can normalize key order and defeat the contract). Snapshots land as `.json`.
- **`bytes_snapshot`** = `snapshot.use_extension(SingleFileSnapshotExtension)` — for `custom_id` strings and CLI stdout, where a single byte flip must fail. Snapshots land as `.raw`.

**Golden projection helpers (in `conftest.py`):**
- `embed_to_golden(embed)` — order-preserving `discord.Embed` → dict (title / description / color / ordered fields incl. `inline`); **excludes `embed.timestamp`** (outside the byte contract).
- `schedule_plan_golden(scheduler)` — projects `scheduler.get_jobs()` to `{job_id, trigger=str(job.trigger), next_run_time}`, sorted by `job_id`; reads `next_run_time` via `getattr` because a not-started job has no such attribute.
- `onecall_rows_golden(db_path)` — reads only the byte-contract columns with an explicit `ORDER BY units, location_name` (kill query-order nondeterminism at the SOURCE, never sort-scrub); `id` and clock columns are not selected → scrubbed; `raw_json` is parsed back to a dict so it diffs structurally.

**Determinism = freeze, don't scrub:** clock-derived values are frozen with `time_machine.travel(FROZEN, tick=False)` (shared `FROZEN = 2026-06-20 13:00 UTC`, epoch 1781960400) so the value becomes a stable literal while the `:t`/`:R` format string is KEPT in the golden. Avoid the over-scrubbing trap — prefer freezing the clock over masking output.

**Regenerating goldens:** `uv run pytest --snapshot-update`, then review the `git diff` of `tests/__snapshots__/` — a golden change is a contract change.

## Oracle Self-Proof Harness

`tests/test_oracle_selfproof.py` guarantees the golden suite actually **has teeth** — that the comparison would catch a real regression rather than passing vacuously.

- Drives **real production output** (a real `build_inbound_embed` render projected through the shipped `embed_to_golden`; a real panel `custom_id` off a real `PanelView`).
- Routes both halves through the **same configured syrupy extension** (not plain `==`) against the **same NAMED snapshot slot** (`json_snapshot(name=...)` / `bytes_snapshot(name=...)` — so the perturbed value doesn't get recorded as its own second snapshot):
  1. The **unperturbed** value MUST match its canonical snapshot (proves the snapshot is real, not a placeholder).
  2. The **perturbed** value (reversed `fields` list / one-byte-flipped `custom_id`) MUST NOT match — wrapped in `pytest.raises(AssertionError)`.
- Net effect: the suite goes RED if a golden extension is ever loosened to order-insensitive/fuzzy compare or removed, OR if the render/panel ids change.
- Deliberately **NOT** an `xfail` marker — these are ordinary green standing tests that are green *because* the perturbation raises.

**Related gate tests:**
- `tests/test_import_hygiene.py` — asserts the resolved `render_embed ↔ PanelView` cycle is never reintroduced; forbidden tokens are built from parts at runtime so the negative-grep gate doesn't self-invalidate. Its own self-proof runs the detector against synthetic source carrying a forbidden edge (proves the check bites).
- `tests/test_exception_identity.py` / `test_module_provenance.py` — pin that hub re-exports resolve to identical objects after the physical repo split.

## Mocking

**Framework:** `unittest.mock` (`MagicMock`, `AsyncMock`) — no third-party mock lib.

**Patterns:**
- **Gateway-free discord.py stand-ins** (see fixtures): pure `MagicMock`s shaped exactly like the discord.py objects the code reads — NO discord import, NO network, NO gateway. Awaited seams (`channel.send`, `response.edit_message`) are `AsyncMock`; called-not-awaited seams (`response.is_done()`) are plain `MagicMock`.
- **Fake clients over network calls:** `_FakeClient` in `test_oracle_selfproof.py` returns recorded imperial/metric fixtures from `fetch_onecall` — the real store/render path runs, only the HTTP boundary is faked.
- `monkeypatch` for module-level attribute swaps (`monkeypatch.setattr(_daemon_mod, "PID_FILE", ...)`).

**What to Mock:**
- The network / transport boundary (OpenWeather HTTP, Discord gateway/webhook).
- Host-runtime side effects (the `/run` PID file).

**What NOT to Mock:**
- The store / idempotency layer — seed real `sent_log` rows via the shipped `claim_slot` (`seed_sent_row`) so exactly-once assertions exercise the real key, never a mock that always passes ("no green-but-hollow scaffold", T-09-01).
- The render / projection path in golden tests — goldens must diff real output.

## Coverage

- **Branch coverage** is mandatory (`[tool.coverage.run] branch = true`, D-06).
- Coverage is a **one-time audit, NOT a standing gate** — there is deliberately no `--cov` in `addopts` and no enforced threshold (D-08). Invoke it explicitly when auditing.
- **Scope (`source`) is the reusable "move-path" packages only:** `weatherbot/{channels,scheduler,config,reliability,ops,interactive}`. `weatherbot/weather` (incl. `store.py`) is deliberately OUT of coverage scope (stays app-side, D-07) even though its DB rows are snapshotted by the DB-row golden. The hub core's coverage is measured in its own repo.
- `[tool.coverage.report] show_missing = true`; `exclude_also` skips `if TYPE_CHECKING:`, `raise NotImplementedError`, and bare `...` (Protocol stubs).

## Common Patterns

**Deterministic time (golden + scheduler tests):**
```python
with time_machine.travel(FROZEN, tick=False):
    embed = render_embed(...)          # clock-derived values become stable literals
```

**Async seam assertions:**
```python
message.channel.send = AsyncMock()
await handler(message)
message.channel.send.assert_awaited_once()   # AsyncMock for awaited seams
```

**Per-test DB isolation:**
```python
def test_claim(tmp_db, seed_sent_row):
    seed_sent_row(tmp_db, "home", "09:00", "2026-06-20")   # real claim_slot write
    assert claim_slot(tmp_db, "home", "09:00", "2026-06-20") is False  # exactly-once
```

**Error-path testing:** assert on the returned `DeliveryResult(ok=False, detail=...)` (expected failures return, not raise) and confirm the secret never appears in `detail`.

---

*Testing analysis: 2026-07-07*
