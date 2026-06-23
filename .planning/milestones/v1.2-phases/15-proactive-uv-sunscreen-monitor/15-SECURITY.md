---
phase: 15
slug: proactive-uv-sunscreen-monitor
status: secured
threats_open: 0
asvs_level: 1
created: 2026-06-23
---

# SECURITY.md — Phase 15: proactive-uv-sunscreen-monitor

**Audit date:** 2026-06-23
**Disposition:** SECURED — 13/13 threats CLOSED
**ASVS Level:** 1
**block_on:** high (no high-severity threat left open)

This audit verifies that each declared threat mitigation in the Phase-15 threat
register is present in the shipped implementation. Evidence is a code location
(file:line) or grep result — documentation/intent alone was not accepted.

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-15-01 | Tampering (SQLi → uv_alerts) | mitigate | CLOSED | `weatherbot/weather/store.py:380` parameterized `INSERT OR IGNORE INTO uv_alerts (...) VALUES (?, ?, ?, ?)` and `:405` `SELECT ... WHERE location_id=? AND local_date=?`; zero f-string SQL (grep `f"INSERT`/`f"SELECT` → 0). |
| T-15-02 | DoS (interval_seconds) | mitigate | CLOSED | `weatherbot/config/models.py:448-459` `@field_validator("interval_seconds")` raises `ValueError` unless `60 <= v <= 86400` (floor >=60, ceiling <=86400). |
| T-15-03 | Interference (uv_alerts vs sent_log) | mitigate | CLOSED | Dedicated table `weatherbot/weather/store.py:129-136` `CREATE TABLE IF NOT EXISTS uv_alerts ... UNIQUE(location_id, local_date, alert_kind)`; separate from `alerts`/`sent_log`. Monitor never references the briefing namespace (T-15-07). |
| T-15-04 | Information disclosure (row contents) | accept | CLOSED | Accepted risk — see Accepted Risks Log below. Verified `uv_alerts` columns are id/location_id/local_date/alert_kind/created_at_utc only (`store.py:129-136`) — no key/URL/PII. |
| T-15-05 | DoS (tick raises → crash scheduler) | mitigate | CLOSED | Two layers in `weatherbot/scheduler/uvmonitor.py`: outermost `try/except Exception` at `:364-399` returns None on any failure incl. `holder.current()`; per-location `try/except` at `:384-394` isolates each iteration. |
| T-15-06 | Tampering (malformed One Call payload) | mitigate | CLOSED | `weatherbot/weather/uv.py:211-212,241,255` compute_uv degrades empty/malformed hourly to `stays_below=True` (never raises); `_coerce_uvi`/`_today_daytime_points` skip non-numeric (`uv.py:64-66,123-125`). Daylight read guards missing sunrise/sunset (`uvmonitor.py:154-155`) inside the per-location try/except. |
| T-15-07 | Repudiation/Interference (touch sent_log) | mitigate | CLOSED | grep `claim_slot\|sent_log\|record_sent\|release_claim` in `weatherbot/scheduler/uvmonitor.py` → 0. Module structurally cannot gate a briefing. |
| T-15-08 | Information disclosure (per-tick logging) | mitigate | CLOSED | `uvmonitor.py:125,393,396,398` outcome-only logs (`uv_alert_post_failed`, `uv_monitor_location_failed` with location name, `uv_monitor_tick` counts, `uv_monitor_tick_failed`). grep `appid\|exc.request.url\|webhook_url\|api_key` → 0. |
| T-15-09 | DoS (persist every fetch) | mitigate | CLOSED | grep `store.persist\|persist(` in `weatherbot/scheduler/uvmonitor.py` → 0; fetch at `:146` is read-only (`client.fetch_onecall`), no store write. |
| T-15-10 | DoS (__uvmonitor__ raising tick) | mitigate | CLOSED | `weatherbot/scheduler/daemon.py:764` `max_instances=1` (no stacked ticks) + APScheduler per-job catch + in-tick envelope (T-15-05). Proven by `tests/test_scheduler.py:1895` `test_raising_uvmonitor_tick_never_stops_scheduler` (asserts `scheduler.running is True`, EVENT_JOB_ERROR observed). |
| T-15-11 | Tampering/Interference (reconcile teardown) | mitigate | CLOSED | `weatherbot/scheduler/daemon.py:804-807` `live_ids = {... if j.id not in ("__heartbeat__", "__uvmonitor__")}` — excluded by id from reconcile diff, like the heartbeat. |
| T-15-12 | DoS (interval too small at registration) | mitigate | CLOSED | Registration `daemon.py:753` `IntervalTrigger(seconds=snapshot.uv.interval_seconds)` consumes the validator-bounded value (T-15-02 floor >=60). Config cannot construct an out-of-range interval. |
| T-15-SC | Tampering (supply chain) | mitigate | CLOSED | `git diff 37b4785~1 HEAD -- pyproject.toml uv.lock` → empty. No new packages added this phase. |

## Accepted Risks Log

| Threat ID | Category | Accepted Risk | Justification |
|-----------|----------|---------------|---------------|
| T-15-04 | Information disclosure | `uv_alerts` rows are persisted to the local SQLite DB and are not encrypted at rest. | Rows carry ONLY `location_id` (an operator-chosen identifier), `local_date`, `alert_kind` (`prewarn`/`crossing`/`allclear`), and `created_at_utc`. No API key, webhook URL, coordinates, or PII is stored (verified `store.py:129-136`). Mirrors the existing `alerts` table disposition (T-04-01). The DB is on the same trust boundary as the `.env` secrets; an attacker with DB read access already has the host. Accepted for a single-user personal bot. |

## Unregistered Flags

None. No `## Threat Flags` section appeared in any of 15-01/15-02/15-03 SUMMARY.md,
and no new attack surface was detected during implementation that lacks a threat
mapping. All implemented behavior maps to a registered threat ID above.

## Corroborating Tests

- `tests/test_uv_monitor.py` — 34 tests: gates, daylight, no-persist, snapshot-once, three decision branches, restart-dedup, ordering, stays-below, and isolation cases (per-location/whole-tick raise swallowed; briefing-namespace-untouched structural assert).
- `tests/test_store.py` — uv_alerts first-wins/repeat-loses, distinct kinds, per-location/date independence, fresh-connection durability, namespace isolation, no-secret rows.
- `tests/test_config_uv.py` — interval_seconds/value_margin range-fail + default/partial-load.
- `tests/test_scheduler.py:1895` — scheduler-level isolation (raising __uvmonitor__ leaves scheduler running).

## Audit Trail

### Security Audit 2026-06-23
| Metric | Count |
|--------|-------|
| Threats found | 13 |
| Closed | 13 |
| Open | 0 |

## Notes

- The live daylight-crossing UAT (Plan 15-03 Task 3) is an operator checkpoint, not a
  security control; it does not affect any threat disposition above.
- Implementation files were not modified during this audit (read-only).
- Register authored at plan-time (all three 15-0x PLAN.md files carried a `<threat_model>` block); auditor verified mitigations exist rather than scanning for new threats.
