---
phase: 21-characterization-golden-test-harness
verified: 2026-06-27T20:12:42Z
status: passed
score: 4/4 success criteria verified (+ purely-additive invariant + requirement accounting)
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: none
  note: initial verification
gaps: []
deferred: []
human_verification: []
notes:
  - "WR-03 (autouse _redirect_pid_file imports daemon before every test) remains open — a non-blocking oracle-robustness nit, not a correctness/SC defect. Recommended for a follow-up cleanup, does not gate Phase 21."
---

# Phase 21: Characterization / Golden-Test Harness — Verification Report

**Phase Goal:** Pin every observable byte of WeatherBot's current behavior as golden/characterization snapshots BEFORE any v2.0-extraction code moves (Phases 22–28), so "byte-identical" is provable. Stand up the trustworthy oracle re-run after every later seam extraction.

**Verified:** 2026-06-27T20:12:42Z
**Status:** PASSED
**Re-verification:** No — initial verification

All evidence below was produced by running the actual tests/greps in the repo (`main`, working tree clean of source changes). SUMMARY claims were treated as unverified narrative and independently re-derived.

## Goal Achievement — The 4 LOCKED Success Criteria

| #   | Success Criterion | Status | Evidence (command + result) |
| --- | ----------------- | ------ | --------------------------- |
| SC1 | Full suite green on `main`; goldens pin embeds, CLI stdout/exit, schedule plan, briefing DB rows, panel custom_ids as byte-exact artifacts | ✓ VERIFIED | `uv run pytest -q` → **732 passed**, 1 warning, 0 skips. 27 committed snapshots exist under `tests/__snapshots__/` covering embeds (11 json), CLI (8 raw stdout/exit), schedule plan (1 json), DB rows (weather_onecall/sent_log/alerts json), custom_ids (raw), harness + self-proof slots. |
| SC2 | A deliberate perturbation makes a golden FAIL — through the ACTUAL syrupy extension, not plain `==` (WR-01 fix `b8d8e6c` must hold) | ✓ VERIFIED | `tests/test_oracle_selfproof.py` Half-2 now routes the reversed-fields / byte-flipped value through `json_snapshot(name="real_embed")` / `bytes_snapshot(name="real_custom_id")` fixtures (the configured `JSONSnapshotExtension` / `SingleFileSnapshotExtension`) against the SAME committed named slot (lines 124/130-132, 163/172-173). Canonical snapshots exist: `test_field_reorder_is_caught[real_embed].json`, `test_custom_id_byteflip_is_caught[real_custom_id].raw`. `uv run pytest tests/test_oracle_selfproof.py -v` → 2 passed; reporter shows "2 snapshots failed" = the intentional perturbation mismatch caught by `pytest.raises(AssertionError)`. The proof goes RED if the extension were loosened/removed — NOT a CPython `==` order-sensitivity proof. WR-01 fix `b8d8e6c` post-dates review commit `08113d2` and is present in source. |
| SC3 | Exception-identity test asserts via import path + `is`-identity + frozen `(__module__,__qualname__)` tuples, NOT isinstance; pydantic tuple is `pydantic_core._pydantic_core` | ✓ VERIFIED | `grep -c isinstance tests/test_exception_identity.py` → **0**. `pydantic_core._pydantic_core` pinned at line 139. 9 identity pins (httpx ×4, discord ×2, tenacity, pydantic, app-defined `UnknownLocationError`) each use `X is module.X` + frozen `(__module__,__qualname__)` tuple. Plus a real-429 behavioral backstop. `uv run pytest -q` includes these — all green. |
| SC4 | Coverage audit over the 6 move-path packages shows no unaccounted uncovered move-path branch; pyproject has branch=true + 6-package source + no fail_under; weatherbot/weather excluded | ✓ VERIFIED | Reproduced `uv run pytest --cov --cov-branch --cov-report=term-missing -q` → **TOTAL 2031 stmts, 104 missed, 540 branches, 48 partial, 93%** — byte-identical to the 21-COVERAGE-AUDIT.md AFTER table. `[tool.coverage.run] branch = true` + exactly the 6 packages (`channels,scheduler,config,reliability,ops,interactive`); `weatherbot/weather` explicitly excluded (D-07). No `fail_under` (grep → none). No `--cov` in addopts (only `-ra`). Every uncovered move-path branch is filled (39 fills in `test_golden_coverage_fill.py`) or excused with a named reason in the audit. |

**Score: 4/4 success criteria verified.**

## Purely-Additive Invariant (D-09)

**Claim:** The ONLY `weatherbot/` source changes across the phase are comment-only `# pragma: no cover - <reason>` annotations — NO executable production change.

**Status:** ✓ VERIFIED

**Evidence:** `git diff 26bcf87^..HEAD -- weatherbot/` touches exactly four files — `interactive/lookup.py`, `ops/selfcheck.py`, `reliability/retry.py`, `scheduler/uvmonitor.py` (precisely the four named in the brief). Every hunk is an otherwise-identical statement with a trailing `# pragma: no cover - <reason>` comment appended; not one executable line changed. `git grep 'pragma: no cover' -- weatherbot/ | grep -v 'no cover -'` → empty (every pragma names a reason).

## Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `tests/conftest.py` | FROZEN + json/bytes_snapshot fixtures + embed/schedule/onecall serializers | ✓ VERIFIED | `FROZEN` (line 394), `embed_to_golden` (420), `schedule_plan_golden` (439), `onecall_rows_golden` (473) all defined and importable. |
| `pyproject.toml` | syrupy+pytest-cov deps; `[tool.coverage.*]` branch-mode, 6 pkgs, no gate | ✓ VERIFIED | Config block present; branch=true; 6-package source; weatherbot/weather excluded; no fail_under; no --cov in addopts. |
| `tests/test_golden_embeds.py` + 11 json snapshots | Per-command embeds × states | ✓ VERIFIED | 11 committed embed snapshots present. |
| `tests/test_golden_cli.py` + 8 raw snapshots | CLI stdout/exit per subcommand+forecast variant | ✓ VERIFIED | 8 raw stdout/exit snapshots present. |
| `tests/test_golden_schedule.py` + 1 json | (job_id, trigger, next_run_time) plan | ✓ VERIFIED | schedule-plan snapshot present, frozen next_run_time. |
| `tests/test_golden_db.py` + 3 json | weather_onecall / sent_log / alerts rows | ✓ VERIFIED | 3 DB-row snapshots present. |
| `tests/test_golden_custom_ids.py` + raw | panel custom_id bytes incl. wb: marker | ✓ VERIFIED | Raw all-custom-ids snapshot present; inline `wb:loc:select` pin + ordered set; drives real PanelView. |
| `tests/test_oracle_selfproof.py` | SC2 self-proof via syrupy extension | ✓ VERIFIED | See SC2; 2 canonical slots committed. |
| `tests/test_exception_identity.py` | SC3 identity pins | ✓ VERIFIED | See SC3. |
| `tests/test_golden_coverage_fill.py` | 39 fills for SC4 | ✓ VERIFIED | Present; coverage reproduces to 93%. |
| `21-COVERAGE-AUDIT.md` | SC4 audit record | ✓ VERIFIED | AFTER table reproduces byte-identical. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Full suite green (SC1/BHV-01) | `uv run pytest -q` | 732 passed, 0 skips | ✓ PASS |
| Self-proof oracle bites (SC2) | `uv run pytest tests/test_oracle_selfproof.py -v` | 2 passed; intentional 2-snapshot perturbation caught by `pytest.raises` | ✓ PASS |
| Coverage audit reproduces (SC4) | `uv run pytest --cov --cov-branch --cov-report=term-missing -q` | TOTAL 93%, 2031/104/540/48 — matches audit doc | ✓ PASS |
| No isinstance in identity test (SC3) | `grep -c isinstance tests/test_exception_identity.py` | 0 | ✓ PASS |

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| BHV-01 | 21-01, 21-05 | Suite stays green / byte-identical at every boundary | ✓ SATISFIED (Complete) | 732 passed; `--snapshot-update` is an empty diff (goldens canonical). REQUIREMENTS.md marks BHV-01 Complete at Phase 21, re-run 22–28. |
| BHV-02 | 21-02, 21-03, 21-04 | Golden pins of observable outputs, re-run as the oracle after each extraction | ✓ SATISFIED (In Progress — correctly NOT closed) | All five observable surfaces pinned (embeds, CLI, schedule, DB rows, custom_ids). REQUIREMENTS.md line 90 correctly marks BHV-02 "In Progress" — it is a cross-cutting acceptance re-exercised through Phase 28, so closure at Phase 21 would be premature. Not prematurely closed. ✓ |

All requirement IDs declared in PLAN frontmatter (BHV-01, BHV-02) are accounted for in REQUIREMENTS.md. No orphaned requirements.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | TBD/FIXME/XXX scan of all phase-21 test files | — | Clean — zero debt markers. |

## Code-Review Follow-Through (21-REVIEW.md)

| Finding | Severity | Status at verify |
| ------- | -------- | ---------------- |
| WR-01 — self-proof tested Python `==`, not the syrupy serializer (load-bearing SC2) | Warning | ✓ RESOLVED in `b8d8e6c` — both halves now route through `json_snapshot`/`bytes_snapshot` fixtures against a committed named slot. Verified in source. |
| WR-02 — self-proof fed metric fixture into imperial slot | Warning | ✓ RESOLVED — imperial slot now uses `onecall_imperial_clear.json` (line 87). |
| WR-03 — `_redirect_pid_file` autouse imports daemon before every test | Warning | ⚠ OPEN — still `autouse=True` (conftest line 32). Non-blocking oracle-robustness nit; no test fails, no SC affected. Recommended follow-up cleanup. |
| IN-01/02/03 | Info | Not blocking; quality nits. |

## Human Verification Required

None. All four success criteria, the purely-additive invariant, and requirement accounting are verifiable programmatically and were verified by running the actual suite/greps. (Per the project two-gate UAT policy, BHV-02's ongoing oracle re-run is a deferred milestone-close obligation, not a Phase-21 gate.)

## Gaps Summary

No gaps. Phase 21 achieves its goal: the byte-identical oracle is stood up, trustworthy, and green on `main`. Every observable surface (rendered embeds, CLI stdout/exit, schedule plan, briefing DB rows, panel custom_ids, exception identity) is pinned as a committed byte-exact artifact; the SC2 self-proof genuinely routes drift through the configured syrupy extension (the load-bearing WR-01 fix holds); the SC4 coverage audit is clean and reproduces exactly; and the only production-source touch across the phase is reason-bearing comment-only pragmas. The single remaining open item (WR-03, autouse daemon import) is a non-blocking robustness nit recommended for follow-up.

---

_Verified: 2026-06-27T20:12:42Z_
_Verifier: Claude (gsd-verifier)_
