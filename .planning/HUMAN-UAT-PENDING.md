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

### Phase 30 — secret-hygiene (v2.1)

- **Status:** `pending`            <!-- pending | signed-off | signed-off-with-gap; owner adds date+name on sign-off -->
- **Milestone:** v2.1 (Hardening)
- **Gate 1 self-UAT log:** [`.planning/phases/30-secret-hygiene/30-01-SELF-UAT.md`](phases/30-secret-hygiene/30-01-SELF-UAT.md) — Verdict: **SC1 PASS (live), SC2 PARTIAL (mechanism+result verified; live-daemon Discord drive deferred), SC3 PASS** (CLI/pytest, source md5 `1dc8f9371b6f7b3aab8a052763a0a848` @ `d89eb0c`, 2026-07-09). Drove a real fetch-failure with `OPENWEATHER_API_KEY=SENTINEL_LEAKCHECK_9f3x`: the sentinel is absent from stdout AND stderr on both onecall and geocode paths, the rendered traceback shows `appid=***`, and `.response.status_code` (401) is preserved.
- **Items covered (3 ROADMAP success criteria + 1 deferred obligation):**
  - **HARD-SEC-01 / SC1 — 401/403 never leaks appid.** Live one-shot drive of the real `client.fetch_onecall`/`geocode` under a sentinel key: no leak in stdout or stderr, redaction (`appid=***`) actually fired in the full rendered traceback, type contract (`.response.status_code`) intact. Verified end-to-end (`client.py` redacted re-raise + `_LiveStderr` backstop).
  - **HARD-SEC-01 / SC2 — Discord `!weather` logs an outcome, no key-bearing traceback.** Real `on_message` non-propagating envelope drove a key-bearing `HTTPStatusError` dispatch failure to `_log.exception`; sentinel absent from rendered stderr; envelope swallowed (CMD-08). **PARTIAL** — only the live Discord gateway drive on `yahir-mint` is deferred (mechanism + result already proven).
  - **HARD-SEC-01 / SC3 — regression suite + type-contract canary.** `tests/test_redact_hygiene.py` 4/4 pass (sentinel absent from `str(exc)`, full traceback, and stderr across all three leak paths); `.response.status_code == 401` canary green; full suite 810 passed, exit 0.
- **Owner how-to-verify (run at milestone completion — the items that need a live host/gateway):**
  1. Read the Gate-1 log above for per-criterion evidence.
  2. **Live daemon + journald no-appid check (SC1/SC2 physical step):** on host `yahir-mint`, redeploy the editable install and `sudo systemctl restart weatherbot`, then trigger a failing `!weather <loc>` over the real Discord gateway (e.g. against a bad/expired key) and confirm `journalctl -u weatherbot` shows the failure outcome with NO `appid` value anywhere (grep the unique key prefix returns nothing).
  3. **Optional key rotation (T-30-03 residual):** if the OpenWeather key previously leaked to on-disk/journald logs before this fix landed, rotate the key (human-gated ops decision) and update `.env` on the host.
- **Note:** No schema/migration in this phase. The Gate-1 run was fully isolated (offline `httpx.MockTransport` 401; no real OpenWeather call, no live Discord gateway, and the live production daemon on `yahir-mint` was NOT touched — no `systemctl`/signals). SC1 and SC3 were fully driven; only SC2's live-gateway drive and the optional key rotation are deferred.
