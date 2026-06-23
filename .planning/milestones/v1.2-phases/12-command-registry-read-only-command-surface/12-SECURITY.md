---
phase: 12
slug: command-registry-read-only-command-surface
status: secured
threats_open: 0
threats_total: 15
threats_closed: 15
asvs_level: 1
block_on: high
created: 2026-06-23
---

# Security Audit — Phase 12: Command Registry & Read-Only Command Surface

**Phase:** 12 — command-registry-read-only-command-surface
**ASVS Level:** 1
**block_on:** high
**Threats Closed:** 15/15
**Threats Open:** 0
**Result:** SECURED

This audit VERIFIES each declared mitigation in the PLAN-time STRIDE register
against the implemented code (not documentation/intent). The register was authored
at plan time; no new-threat scan was performed per scope.

---

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-12-01 | Tampering | mitigate | CLOSED | `parse_command` (command.py:91-114) uses only `str.strip`/`str.casefold`/slicing; no `str.format`/`eval`/`exec`. Word-boundary guard at command.py:110 (`if rest and not rest[0].isspace(): continue`) — "sunny" ≠ "sun". |
| T-12-02 | DoS | mitigate | CLOSED | Longest-keyword-first via `COMMANDS_BY_KEYWORD_LEN_DESC` (registry.py:126-128, iterated at command.py:104) + the word-boundary guard (command.py:110) prevent prefix shadowing and bot-text re-trigger. |
| T-12-03 | Info Disclosure | accept | CLOSED (accepted) | `logging.getLogger("httpx").setLevel(logging.WARNING)` present at client.py:39 (unchanged). The `exclude` widening is `"minutely"` only (client.py:62) — adds data, no new logging. See Accepted Risks below. |
| T-12-04 | Tampering | mitigate | CLOSED | `read_heartbeat`/`read_health` (store.py:490-523) use `WHERE id=?` with `(1,)` tuple binding; SELECT-only + `executescript(_SCHEMA)`; no f-string into SQL. |
| T-12-05 | DoS | mitigate | CLOSED | Declared field `cloud_threshold: int = 60` (models.py:494) + `@field_validator("cloud_threshold")` `_cloud_threshold_in_range` raising `ValueError` unless `0 <= v <= 100` (models.py:504-509) — fails loud at load. |
| T-12-06 | Tampering | mitigate | CLOSED | weather_views.py imports nothing from `weatherbot.weather.store` (grep: no store import) and writes nothing — reads `result.forecast.raw_onecall_imp` only. Zero-store-writes spy extended in tests/test_command_views.py:221-241 (patches store fns to raise, asserts no call). |
| T-12-07 | EoP | mitigate | CLOSED | `DaemonState` is a `@dataclass(frozen=True)` (state.py:41); `next_fires` calls only `scheduler.get_jobs()` + `holder.current()` (reads); `uptime` reads `started_at`. Grep gate: no `add_job`/`remove_job`/`holder.replace`/`stamp_`/`persist` in state.py or status.py (only docstring mentions). |
| T-12-08 | Info Disclosure | mitigate | CLOSED | `status` (status.py:46-93) reports state only (next-send, uptime, liveness, last-success epoch) — no token/appid/webhook. `alerts` (weather_views.py:94-134) surfaces event/start/end/description (truncated to 200 chars) — no URL/key. |
| T-12-09 | DoS | mitigate | CLOSED | Defensive `or {}`/`or []`/`.get()` throughout weather_views.py (e.g. lines 102, 105, 115, 144, 173, 197-202, 215, 219); any escape is absorbed by the bot envelope (bot.py:332-337) and CLI envelope (cli.py:617-637). |
| T-12-10 | EoP | mitigate | CLOSED | Guard ladder step (2) `if message.author.id != operator_id: return` (bot.py:252) runs before any dispatch — silently drops non-operators for ALL commands. `operator_id` baked at construction. |
| T-12-11 | DoS/availability | mitigate | CLOSED | WHOLE registry dispatch (bot.py:270-337) sits inside ONE non-propagating `try/except Exception` that logs + sends `_ERROR_REPLY`, never re-raises. Handlers run via `loop.run_in_executor` (bot.py:302-308, 325). CLI mirror envelope at cli.py:617-637 (exit 3, no traceback). Isolation test: tests/test_bot.py:435-464 (raising handler does not propagate out of on_message). |
| T-12-12 | DoS | mitigate | CLOSED | Guard step (1) `if message.author.bot: return` (bot.py:249) + word-boundary/longest-first parse (T-12-01/02). |
| T-12-13 | Info Disclosure | mitigate | CLOSED | Outer except logs `_log.exception("inbound handler failed")` / `_ERROR_REPLY` generic string (bot.py:332-337) — no appid/webhook/token. CLI logs `command=spec.name` outcome-only (cli.py:635). status reports state only; UnknownLocationError reply carries valid names only (no secret). |
| T-12-14 | EoP | mitigate | CLOSED | `DaemonState` handed no write capability (frozen, read-only accessor, state.py:41-89); threaded into the bot as a read-only param. status reports, never mutates. Same grep gate as T-12-07. |
| T-12-SC | Tampering | mitigate | CLOSED | `uv.lock` / `pyproject.toml` NOT modified in any Phase-12 commit (7cf2fa9, 7e7065c, 730019d, 7d93e01, d324dda, 7d6e74e, e53f40b, 7df327c, dc5f7db). No new packages. |

---

## Accepted Risks Log

| Threat ID | Category | Rationale | Compensating Control |
|-----------|----------|-----------|----------------------|
| T-12-03 | Information Disclosure — request URL carries the `appid` secret | Single-user personal bot; the OpenWeather key in the request URL is a known, pre-existing exposure handled at Phase 6/7. Phase 12 only widened the One Call `exclude` (adds payload data, no new logging surface). | httpx's own logger pinned to WARNING (client.py:39) so the full URL is never emitted at INFO. Verified unchanged this phase. |

---

## Unregistered Flags

None. Neither 12-01/02/03-SUMMARY.md contains a `## Threat Flags` section; no new
attack surface was declared by the executor outside the PLAN-time register.

### Audit notes (informational, not threats)
- `registry.COMMANDS` now also contains `uv`, `weekday-forecast`, `weekend-forecast`
  specs (Phases 13/14). These post-date Phase 12 and are out of scope for THIS
  register. The Phase-12 invariants they ride on — parser purity, longest-first +
  word-boundary matching, the single non-propagating envelope, the operator-id guard
  — were verified intact, which is the point of auditing the foundational ladder here.

---

## Verdict

All 15 declared threats resolve to CLOSED (14 mitigations verified present in code +
1 accepted risk documented). No blockers. Phase 12 is cleared to ship under
ASVS L1 / block_on=high.
