---
phase: 21-characterization-golden-test-harness
reviewed: 2026-06-27T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - tests/conftest.py
  - tests/test_golden_embeds.py
  - tests/test_golden_custom_ids.py
  - tests/test_oracle_selfproof.py
  - tests/test_golden_cli.py
  - tests/test_golden_schedule.py
  - tests/test_golden_db.py
  - tests/test_exception_identity.py
  - tests/test_golden_coverage_fill.py
  - tests/test_golden_harness.py
  - pyproject.toml
  - weatherbot/interactive/lookup.py
  - weatherbot/ops/selfcheck.py
  - weatherbot/reliability/retry.py
  - weatherbot/scheduler/uvmonitor.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 21: Code Review Report

**Reviewed:** 2026-06-27
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 21 is a purely-additive characterization/golden-test harness. The review confirmed
the phase met its hard structural constraints, and the bugs that remain are quality issues
in the oracle suite rather than correctness/security defects.

Verified clean (no findings):

- **Production-source constraint (D-09):** all four `weatherbot/` edits
  (`lookup.py`, `selfcheck.py`, `retry.py`, `uvmonitor.py`) are pure trailing
  `# pragma: no cover - <reason>` comment additions — confirmed by diffing
  `84095033100778632d1b461986bd1e4603bcc44d^..HEAD`. No production behavior changed.
  Not a single executable line was modified.
- **Secret / PII leakage:** grepped every committed snapshot under `tests/__snapshots__/`
  for `appid`, api-key, webhook, `discord.com/api`, bearer tokens, `/home/`, `/run/`,
  `yahir-mint`, and private-IP patterns — zero matches. Fixtures and snapshots use
  placeholder coordinates/names only.
- **Determinism / host-state leakage:** every clock-derived golden carries the frozen
  epoch `1781960400` (verified `== int(datetime(2026,6,20,13,0,0,UTC).timestamp())`). The
  previously-flagged `status` CLI golden correctly redirects `DEFAULT_DB_PATH` to a tmp db
  AND freezes the clock so `started_at=datetime.now()` yields a stable `up 0m`. DB-row
  readers use explicit `ORDER BY`; the schedule golden computes `next_run_time` per-job in
  its own explicit `ZoneInfo` (not host-local tz). `_register_jobs` never opens the
  hardcoded `/tmp/golden-schedule.db` (registration only), so no real DB/daemon read
  reaches a snapshot.
- **Exception-identity (D-13):** `test_exception_identity.py` uses `is`-identity plus
  frozen `(__module__, __qualname__)` tuples (never `isinstance`), and correctly pins
  `pydantic.ValidationError` to `pydantic_core._pydantic_core`.
- **Coverage config:** `branch = true`, source scoped to the six move-path packages
  (`weatherbot/weather` correctly excluded), no `fail_under` gate, no `--cov` in
  `addopts`.

The three warnings below all concern the *trustworthiness* of the oracle (a softer oracle
poisons the whole milestone), which is why they are warnings rather than info.

## Warnings

### WR-01: Oracle self-proof tests Python `==`, not the syrupy serializer it claims to guard

**File:** `tests/test_oracle_selfproof.py:90-91, 112-113`
**Issue:** The module docstring asserts these meta-tests "stand guard" over the
*order-preserving comparison* used by the real goldens (the syrupy `JSONSnapshotExtension`
/ `SingleFileSnapshotExtension` path). But both proofs ultimately assert on a plain Python
expression:

```python
with pytest.raises(AssertionError):
    assert good == reordered          # dict/list ==, not syrupy
...
with pytest.raises(AssertionError):
    assert real_bytes == flipped      # bytes ==, not the snapshot extension
```

Python `list`/`dict`/`bytes` `==` is *always* order-sensitive — so these tests would keep
passing even if `JSONSnapshotExtension` were swapped for the order-normalizing Amber
default (exactly the loosening SC2 is meant to catch). The proof exercises a property of
CPython, not a property of the configured oracle. SC2's stated intent ("the JSON serializer
must be order-PRESERVING for lists so a field reorder is caught") is therefore not actually
verified by this guard.
**Fix:** Route the perturbation through the *real* fixture so the test fails if the
extension is loosened. e.g. assert the perturbed payload does NOT match the committed
snapshot via the `json_snapshot` / `bytes_snapshot` fixture:

```python
def test_field_reorder_is_caught(json_snapshot):
    good = _real_embed_golden()
    reordered = {**good, "fields": list(reversed(good["fields"]))}
    # good must match its golden; the reorder must NOT — through the actual extension
    assert good == json_snapshot
    assert reordered != json_snapshot
```

(or keep the literal `==` proof but ADD an extension-level assertion so the serializer's
order-preservation is the thing under test).

### WR-02: Self-proof renders the embed from a unit-mismatched fixture pair

**File:** `tests/test_oracle_selfproof.py:67-71`
**Issue:** `_real_embed_golden()` feeds the **metric** fixture into the **imperial** slot:

```python
client=_FakeClient(
    imperial=_load("onecall_metric_clear.json"),   # <-- metric file in the imperial slot
    metric=_load("onecall_metric_clear.json"),
),
```

`onecall_imperial_clear.json` exists (every other golden file uses it for the imperial
slot), so this is a copy-paste error, not an intentional choice. The self-proof still
"works" (it only needs ≥2 fields to reverse), but it renders a non-representative embed
(imperial temperatures sourced from a metric payload), which undercuts the docstring's
claim that the proof drives "ACTUAL production output." A maintainer copying this idiom
into a real golden would silently pin wrong-unit data.
**Fix:** Use the imperial fixture for the imperial slot, matching every other test:

```python
imperial=_load("onecall_imperial_clear.json"),
metric=_load("onecall_metric_clear.json"),
```

### WR-03: `_redirect_pid_file` is autouse and imports the daemon module for every test

**File:** `tests/conftest.py:32-49`
**Issue:** The `_redirect_pid_file` fixture is `autouse=True`, so it runs `import
weatherbot.scheduler.daemon` before *every* test in the suite — including the
pure-introspection ones (`test_exception_identity.py`, `test_golden_custom_ids.py`) that
never touch the daemon. This couples otherwise-independent oracle tests to the daemon
module's import-time health: if a future extraction (Phases 23/25) makes
`weatherbot.scheduler.daemon` raise at import (a circular import, a missing optional dep),
every test in the suite errors at collection/setup — masking which tests are genuinely
affected and making the oracle harder to trust during exactly the extraction phases it
exists to protect. For a characterization harness whose job is to localize regressions,
broad autouse coupling works against the goal.
**Fix:** Scope the PID-file redirect to the tests that actually run the daemon — either
gate it on a marker/fixture-request, or move it to a daemon-specific conftest under the
daemon test module's directory, so introspection-only goldens don't import the daemon:

```python
@pytest.fixture          # drop autouse; request explicitly in daemon tests
def redirect_pid_file(tmp_path, monkeypatch):
    ...
```

## Info

### IN-01: `monkeypatch` mutates a frozen `Forecast` via `object.__setattr__` without restoring

**File:** `tests/test_golden_coverage_fill.py:392, 691, 712` (and the `sun`/`wind`/`next_cloudy` helpers)
**Issue:** Several fill tests reach past the model's immutability with
`object.__setattr__(result.forecast, "raw_onecall_imp", raw)` to force an untaken branch.
Each test builds its own fresh `result` via `_result_from`, so there is no cross-test
leak today — but the pattern bypasses the frozen-model contract and would silently share
state if a future refactor module-cached the fixture/result. It is also a latent footgun
for anyone copying the idiom.
**Fix:** Prefer constructing a purpose-built `Forecast`/payload for the branch under test,
or wrap the mutation so the original is restored. At minimum, add a comment that the
result is per-test-local and must not be hoisted to module scope.

### IN-02: Hardcoded `/tmp/golden-schedule.db` instead of `tmp_path`

**File:** `tests/test_golden_schedule.py:94`
**Issue:** `_build_pending_scheduler` passes `db_path="/tmp/golden-schedule.db"`. It is
never opened (registration only, verified against `_register_jobs`), so this is harmless
in practice — but a hardcoded world-writable `/tmp` path is an inconsistent convention
versus the rest of the suite (which uses the `tmp_db`/`tmp_path` fixtures) and would
become a real cross-run collision if `_register_jobs` ever started touching the db.
**Fix:** Use the existing `tmp_path`/`tmp_db` fixture for the path even though it is
currently unopened, to keep the convention uniform and future-proof.

### IN-03: Self-proof imports private test internals across modules

**File:** `tests/test_oracle_selfproof.py:30`, `tests/test_golden_custom_ids.py:24`
**Issue:** Both files import underscore-prefixed internals from a sibling test module
(`from tests.test_panel import _FakeHolder, _SpyCache, _make_panel`). This creates an
implicit cross-test-module dependency on private names: a rename in `test_panel.py`
breaks these goldens with a confusing `ImportError` far from the change. For oracle
files that must stay maximally robust across the milestone, depending on another test
module's private surface is fragile.
**Fix:** Promote the shared panel stand-ins (`_make_panel`/`_FakeHolder`/`_SpyCache`) to
`conftest.py` fixtures (the same place the other gateway-free builders already live), and
have both the panel tests and the goldens consume them from there.

---

_Reviewed: 2026-06-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
