---
phase: 35-cleanup-sweep
plan: gap-closure
subsystem: audit-remediation
tags: [HARD-CLEAN-02, disposition-ledger, low-severity, gap-closure]
status: complete
provides:
  - "F38/F49/F50/F64/F81 dispositioned per HARD-CLEAN-02 (no DEFERRED remains)"
requires:
  - "35-VERIFICATION.md gap report (SC-2 partial)"
affects:
  - weatherbot/interactive/panel.py
  - weatherbot/interactive/cache.py
  - weatherbot/weather/store.py
  - weatherbot/scheduler/daemon.py
  - .planning/WHOLE-PROJECT-REVIEW.md
key-files:
  modified:
    - weatherbot/interactive/panel.py
    - weatherbot/interactive/cache.py
    - weatherbot/weather/store.py
    - weatherbot/scheduler/daemon.py
    - tests/test_panel.py
    - .planning/WHOLE-PROJECT-REVIEW.md
metrics:
  completed: 2026-07-13
---

# Phase 35 Gap Closure: HARD-CLEAN-02 Low-Severity Disposition Reconciliation

Reconciled the 5 LOW-severity WeatherBot findings (F38, F49, F50, F64, F81) that the
Phase-35 verifier (`35-VERIFICATION.md`) flagged as wrongly `DEFERRED(v2.2-hardening)` —
a backlog deferral HARD-CLEAN-02 disallows for low-severity findings ("resolved OR
explicitly annotated as accepted — NOT deferred to a backlog"). Applied the project's
durable hardening-milestone preference (fold low-impact findings in, don't defer) via the
D-01 rule: fix by default, accept-with-rationale only where a fix carries behavior-change
risk on a load-bearing path or is a documented intentional tradeoff.

## Dispositions

| Finding | Site | Disposition | Rationale |
|---------|------|-------------|-----------|
| **F81** | `interactive/panel.py` `LocationSelect.callback` | **FIXED@35** | Trivial, safe defensive guard: `if not self.values: return` short-circuits an empty/deselect payload to a no-op instead of an IndexError surfaced as a generic error. Happy path (one value) unchanged. Regression test added. |
| **F49** | `interactive/cache.py` miss-fetch path | **ACCEPTED** | Per-suffix redundant One Call fetch is, per the audit itself, "a documented, bounded tradeoff" — trivially bounded against the 60/min & 1M/month free tier at single-user scale. In-code `# ACCEPTED (F49, v2.1)`. |
| **F50** | `interactive/cache.py` `maxsize=16` default | **ACCEPTED** | Shared cap is latent at the 2-location deployment (~10 keys < 16 → no eviction); the plain-weather entry is already pinned by `_PinnedTTLCache.popitem`. Retuning/partitioning has subtle eviction/warmth effects for no live benefit. In-code `# ACCEPTED (F50, v2.1)`. |
| **F64** | `weather/store.py` `init_db` | **ACCEPTED** | The per-op `_SCHEMA` re-exec the finding described is already structurally closed by the F10 store-connect discipline: `init_db` is the sole DDL owner and every per-write connect runs no DDL. Annotated to document the already-resolved state rather than re-touch the load-bearing connect path. In-code `# ACCEPTED (F64, v2.1)`. |
| **F38** | `scheduler/daemon.py` briefing job-id register | **ACCEPTED** | Raw-`slot.days` job-id footgun is genuinely latent and harmless: the losing duplicate job does ZERO API calls (claim/INSERT runs before any fetch → no-op INSERT + "slot skipped" log, no double-send/double-fetch). Normalizing the id key would touch the reconcile-diff identity for a self-neutralizing duplicate. In-code `# ACCEPTED (F38, v2.1)`. |

## Ledger Reconciliation

`WHOLE-PROJECT-REVIEW.md` Disposition Ledger (v2.1) updated non-destructively:
- 5 rows flipped from `DEFERRED(v2.2-hardening)` → `FIXED@35` (F81) / `ACCEPTED` (F38/F49/F50/F64).
- Tally line: **64 FIXED + 15 ACCEPTED + 20 DEFERRED → 65 FIXED + 19 ACCEPTED + 15 DEFERRED** (still 99 WB+BOTH).
- ACCEPTED-annotation legend count updated 15 → 19.
- Verified: `grep -ohE "# ACCEPTED \(F[0-9]+, v2.1\)" weatherbot/ -r | wc -l` = **19**, matching the 19 ACCEPTED ledger rows exactly (no silent debt). No DEFERRED row remains for any of the 5.

## Verification

- `uv run pytest -q` → **877 passed, exit 0** (baseline 876 + new `test_empty_values_callback_is_noop`). The "2 snapshots failed" line is the known syrupy quirk — exit code trusted per project memory.
- No `yahir_reusable_bot/` or `../Reusable/` source touched (`git diff --name-only db7bb90~1 HEAD | grep -i "yahir_reusable_bot\|Reusable/"` → 0 hits).
- The 3 pre-existing daemon.py ruff nits (lines 67, 68, 1384) are unrelated to these edits and remain as the ledger-Appendix-documented trivial follow-ups (out of gap-closure scope).

## Deviations from Plan

None — each finding resolved via fix-or-accept per D-01. F64 was found already resolved in code (per-op DDL re-exec absent at HEAD); annotated to document the resolution rather than deferring.

## Commits

- `db7bb90` — fix(35-gap): guard empty LocationSelect values (F81)
- `93b3b41` — docs(35-gap): accept-annotate F38/F49/F50/F64 low-severity findings
- `5428b85` — docs(35-gap): reconcile ledger — F38/F49/F50/F64→ACCEPTED, F81→FIXED@35

## Self-Check: PASSED

- `weatherbot/interactive/panel.py` empty-values guard present; `test_empty_values_callback_is_noop` green.
- 4 in-code `# ACCEPTED (F38|F49|F50|F64, v2.1)` annotations present (grep-confirmed).
- All 5 ledger rows updated; 0 DEFERRED remain for the 5; tally reconciles to 65/19/15.
- Full suite exit 0; no hub-path files touched.
