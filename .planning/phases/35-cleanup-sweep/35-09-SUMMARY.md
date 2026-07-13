---
phase: 35-cleanup-sweep
plan: 09
subsystem: planning-docs
tags: [reconciliation, disposition-ledger, audit, hub-handoff, no-silent-debt]
status: complete
requires:
  - "35-02..35-08 final FIX/ACCEPT dispositions"
  - "Phases 29-34 correctness-phase fixes (verify-then-mark bucket)"
provides: "v2.1 Disposition Ledger reconciling every in-scope WB/BOTH finding + 17-vs-18 hub reconciliation note (SC-3 evidence for the milestone audit)"
affects:
  - .planning/WHOLE-PROJECT-REVIEW.md
  - .planning/HUB-FINDINGS-HANDOFF.md
tech-stack:
  added: []
  patterns:
    - "Append-only ledger table (option 2 from RESEARCH Ledger Write-Back) — does not rewrite severity sections"
    - "Disposition provenance: FIXED@ via git/summary, ACCEPTED mirrored to in-code annotation, DEFERRED names a target"
key-files:
  created:
    - .planning/phases/35-cleanup-sweep/35-09-SUMMARY.md
  modified:
    - .planning/WHOLE-PROJECT-REVIEW.md
    - .planning/HUB-FINDINGS-HANDOFF.md
decisions:
  - "20 audit-surfaced WB/BOTH findings NOT remediated by v2.1 correctness phases (29-34) and out of HARD-CLEAN scope are DEFERRED(v2.2-hardening) — documented debt, not silent drop"
  - "F06 marked FIXED@29 despite no F-tag in its summary — verified fixed-by-rewrite (CONFIG_INVALID split, git 24b446e); F87 FIXED@33 via dt-match pairing verified in source"
  - "3 pre-existing ruff nits in daemon.py recorded as DEFERRED/trivial-follow-up appendix (pre-date 6b45e55, not audit findings, ruff non-blocking)"
metrics:
  duration_min: 22
  completed: 2026-07-13
  tasks: 2
  files_changed: 2
---

# Phase 35 Plan 09: Wave-3 Reconciliation (Disposition Ledger) Summary

Appended the v2.1 Disposition Ledger to `WHOLE-PROJECT-REVIEW.md` mapping every in-scope WeatherBot/BOTH finding (99) to exactly one disposition — 64 `FIXED@<phase>`, 15 `ACCEPTED`, 20 `DEFERRED(v2.2-hardening)` — plus a `HUB (routed-out)` row for each of the 17 hub findings, and annotated the 17-vs-18 hub-count discrepancy in `HUB-FINDINGS-HANDOFF.md`. Docs-only, non-destructive, no code and no hub source touched.

## What Was Built

**Task 1 — v2.1 Disposition Ledger (commit `382d193`).** Appended a `## Disposition Ledger (v2.1)` section (184 lines, append-only, 0 deletions) at the end of `.planning/WHOLE-PROJECT-REVIEW.md`. It reconciles the §Severity Summary's completeness contract (88 WB + 11 BOTH + 17 HUB = 116):
- **99 WB/BOTH findings**, each exactly one disposition (verified: 99 unique rows, no duplicates, no missing).
- **64 `FIXED@<phase>`** — the verify-then-mark bucket (F28/F84/F86@33, F33/F35/F65/F69/F91@32, F89/F90@29, F104@33, F106–F116@34) each grep-verified clean against source at HEAD (D-04, no code re-touched); the correctness-phase fixes (F01–F48 across phases 29–33) attributed to their owning phase's summary/git provenance; and the Plans 02–08 sweep fixes (F16/F46/F60/F61/F66/F68/F70/F74/F75/F76/F78/F79/F80/F82/F85/F88/F92/F105@35).
- **15 `ACCEPTED`** — F51/F52/F53/F56/F57/F58/F59/F62/F67/F71/F72/F73/F77/F83/F103; the ledger ACCEPTED set equals the in-code `# ACCEPTED (F##, v2.1)` annotation set **exactly** (SC-2 / no silent debt — ledger and code agree).
- **20 `DEFERRED(v2.2-hardening)`** — audit findings not remediated by v2.1 and out of HARD-CLEAN scope (F03/F04/F09/F18/F19/F20/F21/F25/F26/F29/F30/F34/F38/F47/F49/F50/F54/F55/F64/F81). Several positively confirmed still-open in source (e.g. F30 raw-`ts` daytime compare at `uv.py:153`; F29 nocturnal `_is_daytime` drop; F26 `--sat`-routes-to-drop). Each names its target — documented forward debt, not a silent drop.
- **17 HUB rows** — F39/F40/F41/F42/F43/F44/F45/F93–F102 mapped H01–H17, marked routed-out.
- **Appendix** — the 3 pre-existing `ruff` nits in `daemon.py` (F401 `ReloadEngine`, F401 `PID_FILE`, F841 `notifier`) recorded DEFERRED/trivial-follow-up.

**Task 2 — 17-vs-18 hub reconciliation (commit `d4e33ee`).** Added a reconciliation note under the severity line of `.planning/HUB-FINDINGS-HANDOFF.md` (9 lines, append-only) stating: 17 audit findings (H01–H17) + 1 Phase-29-appended deferred enhancement (H18 = `ready_gate.run` no first-class fatal outcome) = 18 rows; the milestone's out-of-scope count is the 17 defects; repin after hub ships v0.1.2. H01/H17/H18 all confirmed present.

## Acceptance Criteria — Evidence

| Criterion | Evidence |
|-----------|----------|
| `## Disposition Ledger (v2.1)` exists | `grep -q` → PASS |
| Every WB/BOTH id exactly once | scripted count → 99 rows, 0 missing, 0 duplicate |
| Ledger ACCEPTED == in-code annotations | both sets = `F51 F52 F53 F56 F57 F58 F59 F62 F67 F71 F72 F73 F77 F83 F103` → MATCH |
| Severity sections unchanged (append-only) | `git diff --numstat` → 184 insertions, **0 deletions** |
| H01/H17/H18 present + "17 audit findings" note | all four `grep -q` → PASS |
| No `yahir_reusable_bot/`/`../Reusable/` source in phase diff | phase-range `git log --name-only` → only `.planning/HUB-FINDINGS-HANDOFF.md` (a DOC), no hub source path |
| `uv run pytest -q` exits 0 | 876 passed, exit 0 (the "2 snapshots failed" line is the known syrupy quirk — exit code trusted) |

## Deviations from Plan

None — plan executed exactly as written (docs-only, two tasks, append-only). The plan's disposition buckets were treated as recommendations and reconciled against **ground truth**: the actual Plans 02–08 SUMMARY dispositions, the in-code `# ACCEPTED` annotations, and per-finding source verification at HEAD. Two findings (F06, F87) were confirmed FIXED-by-rewrite despite no F-tag in their owning summary, and the residual un-remediated set was classified `DEFERRED(v2.2-hardening)` per the ROADMAP SC-3 wording ("fixed, accepted-with-rationale, or explicitly deferred").

## Known Stubs

None — this plan writes only planning-doc reconciliation tables; no runtime stubs introduced.

## Self-Check: PASSED

- FOUND: `.planning/WHOLE-PROJECT-REVIEW.md` (Disposition Ledger appended)
- FOUND: `.planning/HUB-FINDINGS-HANDOFF.md` (17-vs-18 note appended)
- FOUND commit `382d193` (Task 1 ledger)
- FOUND commit `d4e33ee` (Task 2 hub reconciliation)
