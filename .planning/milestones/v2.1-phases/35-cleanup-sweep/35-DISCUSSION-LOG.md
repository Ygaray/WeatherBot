# Phase 35: Cleanup Sweep - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 35-cleanup-sweep
**Mode:** `--auto` (all gray areas auto-selected; every decision auto-set to recommended default)
**Areas discussed:** Fix-vs-accept rule, Accepted annotation format, Ledger reconciliation, Scope reconciliation, Dead-code + orphaned tests, Behavior-preservation guard

---

## Fix-vs-Accept rule

| Option | Description | Selected |
|--------|-------------|----------|
| Fix by default; accept only on behavior-risk/cosmetic | Fix in already-open files; accept-with-rationale only when the fix carries behavior-change risk or is purely cosmetic with a real reason | ✓ |
| Accept-by-default, fix only the cheapest | Annotate most low findings as accepted, fix a minimal subset | |

**User's choice:** Fix by default (recommended) → **D-01**
**Notes:** Files are already open from Phases 29–34, so marginal fix cost is low. No finding silently skipped.

---

## Accepted-finding annotation format

| Option | Description | Selected |
|--------|-------------|----------|
| Inline `# ACCEPTED (F##, v2.1): rationale` + ledger | Durable in-code marker at the site, mirrored in ledger | ✓ |
| Ledger-only | Record acceptance only in WHOLE-PROJECT-REVIEW.md | |

**User's choice:** Inline annotation + ledger (recommended) → **D-02**
**Notes:** Satisfies Success Criterion 2's "explicit in-code annotation."

---

## Ledger reconciliation

| Option | Description | Selected |
|--------|-------------|----------|
| Per-WB-finding disposition in WHOLE-PROJECT-REVIEW.md | Tag each WB finding FIXED@phase / ACCEPTED / DEFERRED; confirm 17 hub findings routed | ✓ |
| Separate reconciliation doc | New file tracking dispositions | |

**User's choice:** Disposition markers in the existing ledger (recommended) → **D-03**
**Notes:** Review currently tracks no per-finding status — this reconciliation record is created by the phase. Flagged the 17-vs-18 hub count discrepancy for the planner.

---

## Scope reconciliation (findings possibly fixed in 29–34)

| Option | Description | Selected |
|--------|-------------|----------|
| Verify-then-mark-fixed, don't re-touch | Confirm current code state; mark FIXED@phase without editing clean code | ✓ |
| Re-fix everything from the ledger | Ignore prior phases, re-apply every listed fix | |

**User's choice:** Verify-then-mark-fixed (recommended) → **D-04**

---

## Dead-code + orphaned tests

| Option | Description | Selected |
|--------|-------------|----------|
| Remove dead code + exercise-only tests | Delete dead production code and the tests that only exist to run it | ✓ |
| Remove code, keep tests | Delete dead code but leave the tests | |

**User's choice:** Remove both (recommended) → **D-05**
**Notes:** F16's dead gate/reload copies are "exercised only by tests" — those tests assert nothing about the live path.

---

## Behavior-preservation guard

| Option | Description | Selected |
|--------|-------------|----------|
| Behavior-preserving; behavior-changing fixes get a regression test | Cleanup must not change runtime behavior; any boundary/rounding/default change lands with a test | ✓ |
| Trust review, no new tests | Apply fixes without added regression coverage | |

**User's choice:** Behavior-preserving + regression test on behavior changes (recommended) → **D-06**
**Notes:** Protects the "briefing always goes out, exactly once" invariant. Reuse Phase-34 test patterns.

---

## Claude's Discretion

- Grouping of findings into plans (recommended: by file/subsystem so each plan rides one already-open file).
- The per-finding fix-or-accept verdict for each of the ~48 WB LOW/CLEANUP findings — apply the D-01 rule.

## Deferred Ideas

- 17 hub findings (H01–H17) — belong to YahirReusableBot, human-gated; confirm routed only.
- Any deliberately DEFERRED WB finding must be recorded in the D-03 ledger with a target — no silent drop.
