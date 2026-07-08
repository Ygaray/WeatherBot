# Human UAT — Pending (Gate-2, milestone-close obligations)

Deferred human-verification items batched to milestone close. Each entry's Gate-1 self-UAT log is
the record the human verifies against. `pending` blocks milestone close until the owner signs off;
it does NOT block the individual phase.

## Entries

### Phase 29 — startup-validation-honest-alerting (v2.1)

- **Status:** `pending`            <!-- pending | signed-off | signed-off-with-gap; owner adds date+name on sign-off -->
- **Milestone:** v2.1 (Hardening)
- **Gate 1 self-UAT log:** [`.planning/phases/29-startup-validation-honest-alerting/29-SELF-UAT.md`](phases/29-startup-validation-honest-alerting/29-SELF-UAT.md) — Verdict: **SC1 PASS, SC2 PASS, SC3 PARTIAL** (CLI subprocess, isolated tempdir + isolated health DB, git `e692a72`, 2026-07-08). Drove the real `weatherbot run`/`check-config` CLI: bad configs fatal-exit non-zero at boot with a CRITICAL config line + a `config_invalid` durable health row, while a good config passes `check-config`.
- **Items covered (3 ROADMAP success criteria + 1 deferred obligation):**
  - **HARD-STARTUP-01 — loud boot fail + F05 parity.** `run` on a bad config exits 1 with `run boot-validate failed` + `boot fatal: config/template invalid`; scheduler never starts; `check-config` rejects the same configs and accepts a good one. Verified on the real CLI.
  - **HARD-STARTUP-02 — permanent error is fatal.** Health row stamped `reason=config_invalid`, `detail=type(exc).__name__` (outcome-only); process exited (no warn-loop); fatal Discord alert attempted best-effort (WR-01). AUTH_FAILED stays non-fatal (mechanism + green tests). Verified via durable SQLite row + logs.
  - **HARD-STARTUP-03 — startup ordering/logging.** F90 (disabled forecast slot still announced with next_run_time), F07 (ping strictly after READY), F89 (streak prune) — mechanism+result via green behavioral tests + source. **PARTIAL** (live daemon drive intentionally skipped for side-effect safety).
- **Owner how-to-verify (run at milestone completion — the ONLY item that needs a human/device):**
  1. Read the Gate-1 log above for per-criterion evidence.
  2. **Live systemd restart-policy effect (D-05/D-06):** on host `yahir-mint`, redeploy `deploy/weatherbot.service`, `systemctl daemon-reload`, then start the daemon against a deliberately-bad config and confirm the fatal config-exit trips the start-limit so the unit parks `failed` (not an infinite restart loop). In-repo unit edit is already static-test-verified (`test_service_unit.py`, 3 passed).
- **Note:** No schema/migration in this phase. The Gate-1 run was fully isolated (temp cwd + temp health DB + dummy invalid webhook) — the live production daemon on `yahir-mint` was NOT touched. Only SC3's live drive and the systemd redeploy are deferred; SC1/SC2 were fully driven on the real CLI.
