---
phase: 03
slug: always-on-scheduler
status: secured
threats_open: 0
threats_closed: 18
asvs_level: 1
created: 2026-06-10
---

# SECURITY — Phase 03: Always-On Scheduler

**Audit date:** 2026-06-10
**ASVS Level:** L1
**Block-on:** high
**Verdict:** SECURED — all `mitigate`-disposition controls verified present in implemented code; all `accept` risks documented below.

WeatherBot Phase 03 is a local, single-user, foreground daemon: no inbound network
listener, no auth surface, no multi-user access control. Severity is calibrated
accordingly — no HIGH threat is expected or found. The realistic risk surface is
(a) secret-leakage in long-run logs, (b) SQL handling of config/tz-derived strings,
(c) template-injection on the user-editable briefing template, and (d) exactly-once
delivery across restarts / DST. Each is verified below against the implementation.

## Threat Verification (mitigate)

| Threat ID | Category | Evidence (file:line) |
|-----------|----------|----------------------|
| T-03-01 | Tampering (sent_log SQL) | `weatherbot/weather/store.py:205-209` (SELECT `?`-bound), `:229-234` (INSERT OR IGNORE `?`-bound); UNIQUE backstop `:114`; grep: zero f-string INSERT/SELECT/DELETE in module |
| T-03-02 | Tampering (Schedule.days/time) | `weatherbot/config/models.py:45-55` `_hhmm` HH:MM validator (fail-loud), `:57-63` `_days_valid` → `parse_days`; whitelist in `weatherbot/scheduler/days.py:17-48` (raises on unknown token) |
| T-03-SC | Tampering (apscheduler/time-machine install) | `pyproject.toml:7` `apscheduler>=3.11.2,<4`, `:19` `time-machine>=2.16`; `uv.lock:34-36` apscheduler 3.11.2 pinned with sha256 hash; time-machine 3.2.0 hashed `uv.lock:403+` |
| T-03-04 | Tampering (template injection, new placeholders) | `templates/renderer.py:31` `_TOKEN = \{(\w+)\}` (no `.attr`/`[idx]`/`{0}`), `:36-55` CANONICAL whitelist incl. the 3 new keys, `:83-87` plain regex sub — no `str.format`/`eval`; grep: zero `.format(`/`eval(` |
| T-03-06 | Tampering (manual-send note leak / None crash) | `weatherbot/scheduler/context.py:74-78` note only when `ctx.late and ctx.scheduled_dt is not None`, else `""`; `:67-69` tz-None path for manual send; test `test_schedule_placeholders_manual_no_context`, `test_schedule_placeholders_on_time_not_late_empty_note` |
| T-04-01 | Info disclosure (daemon structlog over multi-day run) | `weatherbot/scheduler/daemon.py:114-119,146-152,161-166` log only `location`/`time`/`days`/`late`/`delivered`/`next_run_time`/`error`; grep gate: no `appid`/`webhook_url`/`api_key` logged (only the word "secret" in a docstring `:219`); secrets stay inside injected client/channel |
| T-03-07 | DoS (one fire_slot exception kills scheduler thread) | `weatherbot/scheduler/daemon.py:99-167` whole body in `try/except Exception` → logs + returns None; test `test_fire_slot_isolates_exception` |
| T-03-08 | Tampering (DST fall-back / restart replay double-send) | `weatherbot/scheduler/daemon.py:113` `claim_slot(...)` before send keyed on `(name, time, local_date)`; UNIQUE backstop `store.py:114`; tests `test_dst_exactly_once`, `test_dst_transition_band_exactly_once`, `test_fire_slot_idempotent_double_fire` |
| T-03-10 | Tampering (config schedule reaching trigger unvalidated) | pydantic validators (`models.py:45-63`) fail loud at load; `daemon.py:188-212` `_register_jobs` consumes only `slot.parsed_time()`/`slot.day_of_week` (validated/normalized form) |
| T-03-04-01 | Tampering (plan_catchup instant construction) | `weatherbot/scheduler/catchup.py:150-172` all math on in-process validated `datetime`/`ZoneInfo`; `.replace(tzinfo=tz)` + UTC round-trip; no SQL, no string interpolation in module |
| T-03-04-SC | Tampering (installs) | No new deps — `catchup.py:25,27` stdlib `datetime`/`zoneinfo` only |
| T-03-05-01 | Tampering (claim_slot/release_claim SQL) | `weatherbot/weather/store.py:268-273` INSERT OR IGNORE `?`-bound; `:297-299` DELETE binds all THREE key columns (no delete-arbitrary-row primitive); grep: zero f-string INSERT/DELETE |
| T-03-05-02 | Repudiation/Integrity (duplicate delivery) | `store.py:268-275` atomic `INSERT OR IGNORE` + `return cur.rowcount == 1`; claim taken BEFORE send at `daemon.py:113`; test `test_concurrent_double_fire_delivers_once` asserts `len(channel.sent_text) == 1` |
| T-03-05-SC | Tampering (installs) | No new deps — `store.py:24-25` stdlib `json`/`sqlite3`/`datetime` only |

## Accepted Risks (accept — no control required)

| Threat ID | Category | Rationale |
|-----------|----------|-----------|
| T-03-03 | DoS (absurd schedule) | Single-user tool; OpenWeather 60/min, 1M/month headroom; 90-min/today catch-up bound (`catchup.py:34` GRACE) caps bursts. No control for v1. |
| T-03-05 | Info disclosure (timing strings in briefing) | `{sent_at}`/`{checked_at}`/`{schedule_note}` are non-secret local wall-clock times; no API key / webhook URL crosses the render boundary (T-04-01). |
| T-03-09 | DoS (catch-up burst after outage) | Bounded to TODAY's slots < 90 min late (`catchup.py:165-167`) — a handful of fires, rounding error vs quota. Backoff is Phase 4. |
| T-03-04-02 | DoS (catch-up burst) | DST fix only REDUCES phantom fires (spring-forward gap skipped, `catchup.py:162-163`); never widens the TODAY/90-min bound. |
| T-03-05-03 | DoS (release-on-failure loop) | A failing delivery releases the claim (`daemon.py:143,160`); re-fire bounded by 90-min GRACE + sent-log. Unbounded retry/alert is Phase 4 (RELY-*). |

## Unregistered Flags

None. The 03-0x SUMMARY files carry "Threat Surface" / "Threat Surface Scan"
sections (not a `## Threat Flags` section); each explicitly reports no new
security-relevant surface beyond the plan's `<threat_model>`. `--run` is a local
foreground daemon with no inbound surface (03-03-SUMMARY). No new attack surface
appeared during implementation that lacks a threat mapping.

## Verification Notes

- All 65 tests across `test_scheduler.py`, `test_store.py`, `test_renderer.py`,
  `test_config.py` pass — confirming the mitigations are live, not merely present
  in source (`uv run pytest`, 2026-06-10).
- Implementation files were NOT modified by this audit (read-only).
- Two `feat(03-05)` commits with no standalone RED `test(...)` gate were flagged by
  the executor (03-05-SUMMARY) for process transparency; the exactly-once behavior
  is nonetheless test-asserted (`test_concurrent_double_fire_delivers_once`). This
  is a process note, not a security gap.
