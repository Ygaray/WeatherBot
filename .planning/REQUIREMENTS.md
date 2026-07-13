# Requirements — Milestone v2.1 Hardening

**Type:** Audit-driven correctness/hardening milestone (no new user-facing features).
**Source of findings:** `.planning/WHOLE-PROJECT-REVIEW.md` (ranked) + `.planning/audit-raw.json` (raw).
**Scope:** 99 WeatherBot findings (88 WB + 11 shared). The 17 hub findings are out of scope here — handed off in `.planning/HUB-FINDINGS-HANDOFF.md` for a separate `YahirReusableBot` milestone.

Each requirement is a testable hardening *outcome*; the parenthetical `Fnn`/theme tags trace it to the
review. "Verify first" applies to the two `SWEEP-NEW` criticals before their fix lands.

---

## v2.1 Requirements

### Startup Validation & Honest Alerting (HARD-STARTUP)

The class with the highest real-world impact: a misconfigured daemon that boots green and silently drops every briefing.

- [x] **HARD-STARTUP-01**: The daemon `run` startup path runs the same `assert_unique_names` + template validation that `check-config`/reload enforce, so a duplicate location id or typo'd template placeholder fails loudly at boot instead of booting green and dropping briefings (F05, `cli.py:986`).
- [x] **HARD-STARTUP-02**: Permanent config/template errors are classified as fatal (not `NETWORK_NOT_READY`), so the daemon surfaces/alerts instead of warn-looping forever while sending nothing (F06, `selfcheck.py:116`).
- [x] **HARD-STARTUP-03**: Config→runtime startup ordering and logging divergences that can leave a feature silently disabled are corrected (config→runtime lifecycle/ordering findings).

### Send Atomicity & Exactly-Once (HARD-DELIV)

The exactly-once/failure-isolation spine is mostly sound; close the edge seams.

- [x] **HARD-DELIV-01**: Post-send bookkeeping (`resolve_alert`/`stamp_success`) cannot release an already-delivered claim — a DB error after delivery never makes the slot re-fireable, so no duplicate briefing (and no false `internal_error` alert) is produced (F01, `daemon.py:335`, verify first).
- [x] **HARD-DELIV-02**: Forecast-slot delivery failures are detected and alerted rather than silently swallowed (F08, forecast-slot fire path).
- [x] **HARD-DELIV-03**: A delivery-only failure does not trigger a fresh weather re-fetch on retry; retry re-uses the fetched payload (F13).
- [x] **HARD-DELIV-04**: Send paths check HTTP/response status and map send failures to the correct exception/alert reason (auth vs transient not conflated) (send-failure/HTTP-status findings).

### Secret Hygiene (HARD-SEC)

- [x] **HARD-SEC-01**: The OpenWeather `appid` never appears in an exception, traceback, or log line — `raise_for_status()` output is sanitized and the inbound Discord error path does not dump the key-bearing traceback to logs (F12, `client.py:67/84`).

### Timezone & Date-Boundary Correctness (HARD-TZ)

The residue of the One Call 3.0 migration: `daily[0]` and "which day is today" vs the configured IANA tz.

- [x] **HARD-TZ-01**: Missed-run catch-up composes the correct local date across a local-midnight boundary, so a late-evening slot missed just after midnight is still caught up, not silently lost (F14, `catchup.py:155`).
- [x] **HARD-TZ-02**: The intraday UV monitor's all-clear has hysteresis — it does not latch "protect window over" on a single momentary UV dip while UV is still at/above threshold (F15, `uvmonitor.py:318`), and the pre-warn↔crossing branches leave no never-fire gap.
- [x] **HARD-TZ-03**: `daily[0]` (and any positional daily/hourly indexing) is anchored to the configured location IANA timezone rather than positionally/UTC, so today's high/low and forecast day-windows are correct across DST and near midnight (F31, F35, F91, F109, and sibling tz findings).
- [x] **HARD-TZ-04**: The duplicated `_local_date_iso` helpers are unified into one tz-correct implementation so the two call sites cannot diverge (tz-helper duplication finding).

### Interactive / Panel Robustness (HARD-UI)

- [x] **HARD-UI-01**: Bare location-taking commands (e.g. `!weather` with no arg) resolve the default location instead of crashing on `result=None`; the Discord surface matches the CLI's default-location behavior (F02, `dispatch.py`/registry guard, verify first).
- [x] **HARD-UI-02**: Panel cache-invalidation and interaction races (stale reads, double-ack/expired-interaction, unbounded/mis-evicting cache) are closed (panel/cache/interaction-race findings). *(cache slice F13/bounding done in 33-02; F17/F22 done in 33-03; F23/F24 done in 33-04 — HARD-UI-02 CLOSED)*
- [x] **HARD-UI-03**: Rendering defects are fixed — no duplicated headers, empty-token trailing blanks, raw ISO timestamps, mispaired metric-on-missing-dt, ambiguous date labels, or unmarked default location (view-formatting/render findings). *(F107/F11 dt-pairing slice done in 33-05; F28/blanks/timestamps/labels landed in 33-06 — HARD-UI-03 CLOSED)*

### Persistence Robustness (HARD-STORE)

- [x] **HARD-STORE-01**: Weather-store writes are atomic (no truncate-then-write corruption; multi-step writes are transactional) and concurrent read/write races are guarded (store atomicity + race findings).
- [x] **HARD-STORE-02**: SQLite is opened with `WAL` + a `busy_timeout` so concurrent worker/heartbeat/UV-monitor access does not raise `database is locked` on the default rollback journal (SQLite concurrency findings; also de-risks HARD-DELIV-01).

### Test-Gap Backfill (HARD-TEST)

Backfill the coverage that let the above bugs hide — do this alongside/after the fixes so each fix ships with a real regression test.

- [x] **HARD-TEST-01**: The false-green tests are corrected — the "concurrent" test that runs sequentially actually exercises concurrency; weak/never-failing assertions (heartbeat, naming) are strengthened (false-green findings).
- [x] **HARD-TEST-02**: The highest-risk uncovered paths get tests: retry-then-alert exhaustion, catch-up across local midnight, rename-safe `id!=name`, dt-based metric pairing, weekend roll-forward, and the store atomicity/data-loss path (missing-coverage findings).

### Cleanup Sweep (HARD-CLEAN)

Remaining low/dead-code/latent findings, fixed behind the correctness work (same files, once already open) — not deferred to a backlog.

- [x] **HARD-CLEAN-01**: Dead/divergent code and inaccurate docs identified by the audit are removed or corrected (dead-code, doc-mismatch, dead-defensive-code findings).
- [ ] **HARD-CLEAN-02**: Remaining low-severity latent/quality findings (config defaults, boundary `>=`/`<=` nits, rounding disagreements, observability inconsistencies, resource/state-leak nits) are resolved or explicitly annotated as accepted with rationale, leaving no silent debt.

---

## Out of Scope (this milestone)

- **The 17 hub findings** (`yahir_reusable_bot/…`) — routed upstream via `.planning/HUB-FINDINGS-HANDOFF.md`; require a human-gated `YahirReusableBot` tag cut. WeatherBot repins after the hub ships `v0.1.2`.
- **New user-facing features** — deferred candidates (Telegram/SMS channels, arbitrary-location lookup, weather-pattern analysis) stay in PROJECT.md's Future Candidates.
- **One Call 3.0 → 2.5 migration or vice-versa** — the data source is settled; this milestone hardens the existing One Call 3.0 path.

---

## Traceability

Each requirement maps to exactly one phase (roadmap: Phases 29–35). Finding-level detail for every requirement lives in
`.planning/WHOLE-PROJECT-REVIEW.md` (by finding id + `file:line`) and `.planning/audit-raw.json`.

| Requirement | Phase | Status |
|-------------|-------|--------|
| HARD-STARTUP-01 | Phase 29 | Complete |
| HARD-STARTUP-02 | Phase 29 | Complete |
| HARD-STARTUP-03 | Phase 29 | Complete |
| HARD-SEC-01 | Phase 30 | Complete |
| HARD-DELIV-01 | Phase 31 | Complete |
| HARD-DELIV-02 | Phase 31 | Complete |
| HARD-DELIV-03 | Phase 31 | Complete |
| HARD-DELIV-04 | Phase 31 | Complete |
| HARD-STORE-01 | Phase 31 | Complete |
| HARD-STORE-02 | Phase 31 | Complete |
| HARD-TZ-01 | Phase 32 | Complete |
| HARD-TZ-02 | Phase 32 | Complete |
| HARD-TZ-03 | Phase 32 | Complete |
| HARD-TZ-04 | Phase 32 | Complete |
| HARD-UI-01 | Phase 33 | Complete |
| HARD-UI-02 | Phase 33 | Complete |
| HARD-UI-03 | Phase 33 | Complete |
| HARD-TEST-01 | Phase 34 | Complete |
| HARD-TEST-02 | Phase 34 | Complete |
| HARD-CLEAN-01 | Phase 35 | Complete |
| HARD-CLEAN-02 | Phase 35 | Pending |

**Coverage:** 21/21 v2.1 requirements mapped to exactly one phase. No orphans, no duplicates.
