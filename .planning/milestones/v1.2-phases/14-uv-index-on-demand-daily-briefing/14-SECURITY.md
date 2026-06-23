---
phase: 14
slug: uv-index-on-demand-daily-briefing
status: secured
threats_open: 0
threats_total: 12
threats_closed: 12
asvs_level: 1
block_on: high
created: 2026-06-23
---

# 14-SECURITY.md — Phase 14 (uv-index-on-demand-daily-briefing)

**Status:** SECURED
**Threats Closed:** 12/12
**ASVS Level:** 1
**block_on:** high — no open high-severity threats; phase may ship.
**Register provenance:** authored at PLAN time (`register_authored_at_plan_time: true`); this audit VERIFIES each declared mitigation against the implemented code (no new-threat scan).

## Scope note

`weatherbot/scheduler/uvmonitor.py` and `tests/test_uv_monitor.py` belong to the LATER Phase-15 UV monitor and were NOT audited. `UvConfig` carries Phase-15-only knobs (`monitor_enabled`, `interval_seconds`, `value_margin`) which are stored/validated here but behavior-less in Phase 14; their validators are present (models.py:448-469) and do no harm to the Phase-14 surface.

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-14-01 | Tampering | mitigate | CLOSED | `UvConfig` frozen + `extra="forbid"` (config/models.py:402); `_threshold_in_range` 0..20 (models.py:425-432); `_lead_in_range` 0..720 non-negative (models.py:434-446); malformed `[uv]` raises `ValidationError`/`ValueError` from `validate_config_and_templates` (config/loader.py:99-119), caught + re-raised by reload leaving holder/jobs untouched = keep-old (scheduler/daemon.py:903-928). Tests: test_config_uv.py:118/132/146/160 + unknown-key. |
| T-14-02 | DoS | mitigate | CLOSED | Validation is load/reload-only (loader.py:131-166); reload-keeps-old proven at daemon.py:905-928. `Config.uv = Field(default_factory=UvConfig)` (models.py:502) → an absent/blank `[uv]` defaults to threshold 6.0 and can never gate a send. Tests: test_config_uv.py:39 (absent defaults), :51 (partial defaults). |
| T-14-03 | Info Disclosure | accept | CLOSED (accepted) | Accepted risk — unchanged from Phase 2. `client.py` is VERIFY-ONLY this phase; the `httpx` WARNING-level logger and the `appid` query param handling are not touched by any Phase-14 file. No fixture/test/config change alters logging. See Accepted Risks below. |
| T-14-04 | DoS | mitigate | CLOSED | `compute_uv` defensive reads: `raw.get("daily") or [{}]` / `raw.get("hourly") or []` (weather/uv.py:109,116), skip-None-bucket + coerce guards (uv.py:120-130, `_coerce_uvi` 61-71); no usable points → `crossing_time is None` → `stays_below=True`, never raises (uv.py:238-241). Tests: test_uv.py empty/malformed/missing-hourly no-raise + test_uvbelow_stays_below (test_uv.py:110). |
| T-14-05 | Tampering | mitigate | CLOSED | "today" + daytime bounding use the passed-in CONFIGURED `tz` arg: `now.astimezone(tz).date()` (uv.py:114), `_epoch_local(int(ts), tz)` (uv.py:56-58,127). The API `timezone` field is never read (grep `timezone` in uv.py → 0 payload reads). Test: test_uv.py pins explicit `ZoneInfo` `NY` + anchored `now`. |
| T-14-06 | Tampering | mitigate | CLOSED | Six UV tokens added to the `CANONICAL` allow-list (templates/renderer.py:54-59). Substitution is the guarded regex `_TOKEN = \{(\w+)\}` (renderer.py:31) via `_sub` (renderer.py:164-168) — no `str.format`/`Formatter`/`eval`. `validate_template` rejects only tokens NOT in the set (renderer.py:139-153), so adding tokens is backward-compatible. Tests: test_renderer.py:128 (tokens in CANONICAL), :133 (lockstep). |
| T-14-07 | DoS | mitigate | CLOSED | `from_payloads` wraps `compute_uv` + `_format_uv` in `try/except Exception` degrading the six UV fields to `""` (weather/models.py:326-342) — belt-and-suspenders over compute_uv's own non-raising guarantee (T-14-04); the rest of the briefing still renders. Test: test_models.py:497 `test_uv_missing_hourly_degrades_without_raising`. |
| T-14-08 | Tampering | mitigate | CLOSED | Single source of truth: `_hints` fires at `uvi_max >= uv_threshold` (models.py:103, literal 6 removed), and `from_payloads` threads the SAME `uv_threshold` into both `compute_uv` (models.py:328) and `_hints` (models.py:364-365); live call passes `config.uv.threshold` (interactive/lookup.py:128). Tests: test_models.py:399/404/409 (hint fires/suppressed at configured value). |
| T-14-09 | EoP | mitigate | CLOSED | The `uv` dispatch (interactive/bot.py:317-318) sits INSIDE the existing Phase-12 guard ladder: `author.bot` drop (bot.py:249), `author.id != operator_id` silent ignore (bot.py:252), `!`-prefix required (bot.py:256), registry parse (bot.py:260). No new envelope, no new entry path. Test: test_bot.py:492/545. |
| T-14-10 | DoS | mitigate | CLOSED | Discord: the `uv` branch is inside the non-propagating `try/except Exception` envelope (bot.py:270-337) → generic `_ERROR_REPLY`, logged, never re-raised, never touches the scheduler thread. CLI: `uv` branch inside the failure-isolation envelope (cli.py:617-637) → clean message + exit 3; unknown-loc → exit 1, fetch-fail → exit 3 (cli.py:601-608). Both surfaces are off the scheduled briefing spine. Tests: test_bot.py:584 `test_raising_uv_handler_is_isolated`; test_cli.py:956/972. |
| T-14-11 | Tampering | mitigate | CLOSED | Handler `uv` reads ONLY `result.forecast.raw_onecall_imp`/`raw_onecall_met` (weather_views.py:284,290) — no second fetch. Zero store import in weather_views.py (only a docstring prose reference, no import/`store.` call). Location resolves via `resolve_location`/`UnknownLocationError` in the shared cache/lookup path (cache.py:104, lookup.py:44). Test: test_command_views.py:206 (reads-only-retained), zero-store-writes spy. |
| T-14-12 | Info Disclosure | accept | CLOSED (accepted) | Accepted risk — the `uv` reply is built only from config-sourced location name (weather_views.py:286) + UV numbers/category + fixed labels (weather_views.py:297-322); no `appid`/webhook/token is constructed or logged on this path (mirrors `next-cloudy`). See Accepted Risks below. |

## Accepted Risks Log

- **T-14-03 (Information Disclosure — client request URL carrying `appid`):** Accepted. Carried forward unchanged from Phase 2. `weatherbot/weather/client.py` is VERIFY-ONLY in Phase 14 — no Phase-14 file edits the HTTP client, its `appid` query param, or its WARNING-level `httpx` logger. The fixture/test work in Plan 14-01 alters no logging surface. Residual risk is identical to the pre-Phase-14 baseline.
- **T-14-12 (Information Disclosure — secret leak in the `uv` reply):** Accepted. The on-demand `uv` reply payload is assembled exclusively from non-secret config-sourced data (location display name, computed UV numbers, WHO category words, fixed labels). No secret (`appid`, Discord webhook URL, bot token) is read, constructed, or logged on the `uv` command path. Mirrors the existing `next-cloudy` reply posture.

## Unregistered Flags

None. The only SUMMARY with a `## Threat Flags` section (14-03) states "None"; no new network endpoint, auth path, or trust boundary was introduced beyond the already-registered user-edited-template→renderer (T-14-06) and compute_uv→render (T-14-07) boundaries. 14-02 and 14-04 SUMMARYs carry no `## Threat Flags` section and introduce no unmapped attack surface (pure helper; command rides the existing Phase-12 registry/guard ladder).

## Audit Trail

### Security Audit 2026-06-23
| Metric | Count |
|--------|-------|
| Threats found | 12 |
| Closed | 12 |
| Open | 0 |

Re-verification: register is authored at PLAN time and `threats_open: 0`, so the short-circuit applies — all plan-time threats remain verified CLOSED (12 mitigated/accepted with code-level evidence above). No new threats scanned; no implementation files modified.

## Implementation files: unmodified by this audit (read-only verification only).
