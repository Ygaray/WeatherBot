---
phase: 29-startup-validation-honest-alerting
verified: 2026-07-08T00:00:00Z
status: passed
score: 19/19 must-haves verified
behavior_unverified: 0
overrides_applied: 0
deferred:
  - truth: "Live effect of the deploy/weatherbot.service change (redeploy + systemctl daemon-reload on host yahir-mint)"
    addressed_in: "Milestone-close Gate-2 (deferred obligation, D-06)"
    evidence: "CONTEXT.md D-06 + deferred-items.md: unit edit is in-repo; live redeploy is an intentional deferred Gate-2 milestone-close obligation, not phase-incomplete"
---

# Phase 29: Startup Validation & Honest Alerting Verification Report

**Phase Goal:** A misconfigured daemon can no longer boot green and silently drop every briefing — the `run` startup path enforces the same validation `check-config`/reload already run, and permanent config/template errors are surfaced as fatal (alerted) instead of being misclassified as transient network faults the daemon warn-loops on forever.
**Verified:** 2026-07-08T00:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Merged from ROADMAP Success Criteria (SC1–SC3, the contract) + PLAN frontmatter must_haves across all 6 plans.

| #   | Truth (source) | Status | Evidence |
| --- | -------------- | ------ | -------- |
| 1   | **SC1/HARD-STARTUP-01:** `run` calls full `validate_config_and_templates(args.config)` before `run_daemon` (same validator check-config/reload use) | ✓ VERIFIED | `cli.py:1031` calls `validate_config_and_templates(args.config)` in the `run` branch; success path reaches `daemon.run_daemon(...)` at `cli.py:1063`. Behavioral: `test_check_run_parity` + `test_run_boot_validate_*` pass. |
| 2   | **SC1:** duplicate id/name, typo'd template token, or missing template file makes `run` exit non-zero at boot (no green boot) | ✓ VERIFIED | `run` catch tuple `cli.py:1032-1037` = `(FileNotFoundError, tomllib.TOMLDecodeError, ValidationError, ValueError)` → `_fatal_config_exit(...)` returns 1. Behavioral: `test_run_boot_validate_rejects_duplicate_id`, `test_run_boot_template_rejects_missing_template`, `test_run_bad_config_exit_code` (subprocess, real process exit) pass. |
| 3   | **SC1 (F05 parity):** anything check-config rejects, run rejects; anything it accepts, run accepts | ✓ VERIFIED | Catch tuple `cli.py:1032-1037` is byte-identical to check-config's `cli.py:1007-1011`; both call the SAME `validate_config_and_templates`. Behavioral: `test_check_run_parity` (parametrized valid/dup-id/bad-template) passes. |
| 4   | **SC2/HARD-STARTUP-02:** `run_self_check` classifies config/template/empty-locations errors as CONFIG_INVALID, not NETWORK_NOT_READY | ✓ VERIFIED | `selfcheck.py:88-113` — pre-probe block wraps `config.locations`/`validate_template`/`assert_unique_names`/`resolve_location` in `except (ValueError, OSError)` → `CheckResult(reason=CONFIG_INVALID, detail=type(exc).__name__)`, placed BEFORE the network probe (`selfcheck.py:115`). Behavioral: `test_config_invalid_*` pass. |
| 5   | **SC2 (D-03 guard):** transient ConnectError still NETWORK_NOT_READY, 401/403 still AUTH_FAILED (unchanged) | ✓ VERIFIED | Network branch `selfcheck.py:127-144` unchanged: 401/403→AUTH_FAILED, else→NETWORK_NOT_READY, trailing `except Exception`→NETWORK_NOT_READY. Behavioral: `test_*network_not_ready`, `test_*auth_failed` pass. |
| 6   | **SC2:** `to_health_result` maps CONFIG_INVALID→CRITICAL, AUTH_FAILED→CRITICAL, NETWORK_NOT_READY→WARNING | ✓ VERIFIED | `selfcheck.py:162-165`: `Severity.CRITICAL if result.reason in (AUTH_FAILED, CONFIG_INVALID) else Severity.WARNING`. Behavioral: `test_severity_map` (parametrized) passes. |
| 7   | **SC2:** CONFIG_INVALID importable from `weatherbot.ops` and resolvable as `daemon.CONFIG_INVALID` | ✓ VERIFIED | `ops/__init__.py:18,28` re-exports + `__all__`; `daemon.py:55` imports it. Runtime probe: `from weatherbot.ops import CONFIG_INVALID; daemon.CONFIG_INVALID=='config_invalid'` → OK. |
| 8   | **SC2:** CONFIG_INVALID detail is outcome-only (`type(exc).__name__`), never `str(exc)` | ✓ VERIFIED | `selfcheck.py:112` uses `detail=type(exc).__name__`. `_fatal_config_exit` alert/stamp use caller-passed `type(exc).__name__` (`cli.py:1046`). |
| 9   | **SC2 (D-10):** dedicated `fatal: threading.Event` threaded through RuntimeParts (separate from `stop`) | ✓ VERIFIED (behavior-dependent) | `wiring.py:102` `fatal: threading.Event` field; constructed `wiring.py:168`; returned `wiring.py:375`. State-transition test `test_fatal_exit_code` + `test_clean_shutdown_returns_zero` pass (fatal set vs unset distinguished). |
| 10  | **SC2:** `_on_fail` on CONFIG_INVALID/CRITICAL sets fatal + best-effort alert + stop; AUTH_FAILED does NOT set fatal (re-probes) | ✓ VERIFIED (behavior-dependent) | `wiring.py:313-331` fatal branch guarded on `reason == daemon.CONFIG_INVALID and severity >= CRITICAL` → `fatal.set()` + `channel.send(...)` + `stop.set()`; AUTH_FAILED falls to `elif` at `wiring.py:332` (log only). Behavioral: `test_auth_not_fatal` passes (fatal NOT set on AUTH). |
| 11  | **SC2:** `run_daemon` returns non-zero on fatal, 0 on clean SIGTERM | ✓ VERIFIED (behavior-dependent) | `daemon.py:1486` `return 1 if parts.fatal.is_set() else 0` at the gate-stop branch. Behavioral: `test_fatal_exit_code` (→1), `test_clean_shutdown_returns_zero` (→0) pass. |
| 12  | **SC2 (WR-01 fix):** primary boot-validate fatal path actually FIRES the Discord alert (`build_channel(None, settings)` no longer raises) | ✓ VERIFIED | `factory.py:28-30` `_build_discord` tolerates `config is None` (fallback username `"WeatherBot"`, avatar `None`); `_fatal_config_exit` calls `build_channel(None, settings)` at `cli.py:611`. Behavioral: `test_fatal_config_exit_sends_via_real_build_channel` (drives REAL build_channel) + `test_build_channel_none_config_uses_settings_and_default_identity` pass. |
| 13  | **SC2 (WR-03 fix):** pre-probe catch widened to OSError so IsADirectory/Permission classify CONFIG_INVALID (don't crash ReadyGate) | ✓ VERIFIED | `selfcheck.py:101` `except (ValueError, OSError)`. Behavioral: `test_config_invalid_on_template_oserror` (parametrized PermissionError/IsADirectoryError) passes. |
| 14  | **SC3/HARD-STARTUP-03 (F90):** `_announce_schedule` logs every briefing AND forecast slot incl. disabled, with next_run_time | ✓ VERIFIED | `daemon.py:1087-1097` briefing loop (no continue-skip, `enabled=slot.enabled`); `daemon.py:1100-1110` forecast loop keyed by `_forecast_job_id`, disabled→`by_id.get`miss→`next_run_time=None`. Behavioral: `test_announce_forecast` passes. |
| 15  | **SC3 (F07):** online ping fires strictly AFTER `notifier.ready()` (moved out of `_on_online`) | ✓ VERIFIED (behavior-dependent) | Ping removed from `_on_online` (`wiring.py:352-356`, comment :357-360); relocated to `daemon.py:1496-1507` AFTER `ready_gate.run(stop)` returns True (`daemon.py:1478`). Ordering test `test_ping_after_ready` passes (ping index > ready index). |
| 16  | **SC3 (F89):** reload prunes `_forecast_failure_streaks` keyed by `_forecast_job_id`; live entries retained | ✓ VERIFIED (behavior-dependent) | `daemon.py:447-461` `_prune_forecast_streaks` pops `set(_forecast_failure_streaks) - _desired_job_ids(holder)`; called best-effort from `wiring.py:243` `_on_applied`. Cleanup test `test_streak_prune` passes (dead removed, live kept). |
| 17  | **Scope:** dead `gate_until_healthy`/`wait_ready_gate` removed; `emit_online`/`_do_reload` left for Phase 35 | ✓ VERIFIED | No `def gate_until_healthy`/`def wait_ready_gate` remain (grep empty; only NB removal-comment at `daemon.py:1156`). `emit_online` (`daemon.py:1165`) + `_do_reload` (`daemon.py:900`) still present. |
| 18  | **Scope:** NO hub source under `../Reusable/YahirReusableBot/` modified; ReadyGate enhancement recorded in HUB-FINDINGS-HANDOFF | ✓ VERIFIED | Hub is a separate repo (`/home/yahir/Projects/Reusable/YahirReusableBot`); no hub paths in WeatherBot commits/tree. `ready_gate.py` finding present in `.planning/HUB-FINDINGS-HANDOFF.md`. |
| 19  | **HARD-STARTUP-02/03:** systemd unit has Restart=on-failure + StartLimit* in [Unit] + TimeoutStartSec=infinity kept | ✓ VERIFIED | `deploy/weatherbot.service`: `StartLimitIntervalSec=300` (:22) + `StartLimitBurst=5` (:23) in `[Unit]` (before `[Service]` :25); `Restart=on-failure` (:54), no `Restart=always`; `TimeoutStartSec=infinity` (:32). Behavioral: 3 `test_service_unit.py` static tests pass. |

**Score:** 19/19 truths verified (0 present, behavior-unverified)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Live effect of `deploy/weatherbot.service` change (redeploy + `systemctl daemon-reload` on yahir-mint) | Milestone-close Gate-2 | D-06 + deferred-items.md: unit edit is in-repo (static test green); live redeploy is an intentional deferred Gate-2 obligation, NOT a phase gap. |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `weatherbot/cli.py` | run boot-validate gate + `_fatal_config_exit` | ✓ VERIFIED | Gate at :1030-1047, helper at :590-626, imports `validate_config_and_templates`/`CONFIG_INVALID`/`build_channel`. |
| `weatherbot/ops/selfcheck.py` | CONFIG_INVALID classification split + severity map | ✓ VERIFIED | Pre-probe OSError branch :101, severity map :162-165. |
| `weatherbot/ops/__init__.py` | CONFIG_INVALID re-export | ✓ VERIFIED | :18 import, :28 `__all__`. |
| `weatherbot/scheduler/daemon.py` | fatal exit code + F90 announce + F89 prune + dead-code removal + relocated ping | ✓ VERIFIED | :1486 exit, :1100-1110 forecast announce, :447-461 prune, dead code removed, :1496-1507 ping. |
| `weatherbot/scheduler/wiring.py` | fatal plumbing + _on_fail fatal branch + ping removal + prune call | ✓ VERIFIED | :102/:168/:375 fatal, :313-331 fatal branch, :352-356 ping removed, :243 prune call. |
| `weatherbot/channels/factory.py` | config-optional _build_discord (WR-01) | ✓ VERIFIED | :22 `Config | None`, :28-30 None fallback. |
| `deploy/weatherbot.service` | Restart=on-failure + StartLimit* [Unit] + Timeout kept | ✓ VERIFIED | :22-23, :32, :54. |
| `.planning/HUB-FINDINGS-HANDOFF.md` | deferred ReadyGate fatal-outcome entry | ✓ VERIFIED | ready_gate.py entry present. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `cli.py:run` | `validate_config_and_templates` | direct call before run_daemon | ✓ WIRED | `cli.py:1031` |
| `cli.py:_fatal_config_exit` | `build_channel(None, settings)` | best-effort alert send | ✓ WIRED | `cli.py:611` → `factory.py:28-30` (config-optional) |
| `cli.py:_fatal_config_exit` | `stamp_health` | durable CONFIG_INVALID row (D-02) | ✓ WIRED | `cli.py:622` |
| `wiring.py:_on_fail` | `daemon.CONFIG_INVALID` | reason comparison | ✓ WIRED | `wiring.py:313`; symbol resolves via daemon re-export |
| `daemon.py gate-return` | `parts.fatal.is_set()` | exit-code branch | ✓ WIRED | `daemon.py:1486` |
| `wiring.py:_on_applied` | `daemon._prune_forecast_streaks` | best-effort reload hook | ✓ WIRED | `wiring.py:243` |
| `daemon.py run_daemon` | online ping | post-`ready_gate.run` best-effort | ✓ WIRED | `daemon.py:1496-1507`, after :1478 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Full suite | `uv run pytest -q` | 806 passed, exit 0 (2 syrupy snapshot lines = known pre-existing noise) | ✓ PASS |
| daemon.CONFIG_INVALID resolves | `python -c "...assert d.CONFIG_INVALID=='config_invalid'"` | OK | ✓ PASS |
| fatal/clean/auth/announce/ping | `pytest test_scheduler.py -k ...` | 5 passed | ✓ PASS |
| F89 streak prune | `pytest test_reload.py -k streak_prune` | 1 passed | ✓ PASS |
| boot-validate/parity/subprocess/fatal-exit | `pytest test_cli.py -k ...` | 11 passed | ✓ PASS |
| classification/severity/WR-03 oserror | `pytest test_ops_selfcheck.py -k ...` | 15 passed | ✓ PASS |
| systemd directives | `pytest test_service_unit.py` | 3 passed | ✓ PASS |
| WR-01 none-config factory | `pytest test_channel.py -k none_config` | 1 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| HARD-STARTUP-01 | 29-01, 29-04 | run path runs same validation as check-config; loud boot fail (F05) | ✓ SATISFIED | Truths 1–3; `cli.py:1030-1047` parity gate |
| HARD-STARTUP-02 | 29-01/02/03/04/05/06 | permanent config/template errors fatal + alerted, not NETWORK_NOT_READY warn-loop (F06) | ✓ SATISFIED | Truths 4–13, 19; selfcheck split + fatal plumbing + WR-01/WR-03 fixes + systemd |
| HARD-STARTUP-03 | 29-02/05/06 | startup ordering/logging divergences corrected (F90/F07/F89) | ✓ SATISFIED | Truths 14–16, 17; announce + ping-order + streak-prune + dead-code removal |

No orphaned requirements: all 3 IDs in REQUIREMENTS.md map to Phase 29 and are claimed by shipped code.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `weatherbot/cli.py` | 1038 | `error=str(exc)` on boot-validate log line | ℹ️ Info (WR-02 WON'T FIX) | Deliberate parity with check-config's own `error=str(exc)` (:1013); LOCAL operator log; the OpenWeather key + Discord webhook live in `.env`/settings, NOT in the config-validation exception — config-content disclosure at most, not a credential leak. Dispositioned in 29-REVIEW.md as accept-by-design; the fatal ALERT detail path correctly uses `type(exc).__name__`. |

No `TBD`/`FIXME`/`XXX` debt markers in phase-modified files. No stub returns, no hollow props, no orphaned artifacts. `str(exc)` in `_fatal_config_exit` alert/detail path: confirmed ABSENT (uses caller-supplied `type(exc).__name__`).

### Human Verification Required

None. All behavior-dependent truths (fatal exit-code state transition, clean-SIGTERM distinction, AUTH-non-fatal guard, ping-after-READY ordering, streak-prune cleanup) are exercised by passing named behavioral tests, so none route to human verification.

The live systemd redeploy on yahir-mint (D-06) is a deferred Gate-2 milestone-close obligation per project policy — not a Phase 29 gap and not a per-phase human checkpoint.

### Gaps Summary

No gaps. All 19 must-haves (3 ROADMAP SCs + all 6 plans' frontmatter truths, deduplicated) verified against actual source with passing behavioral evidence. Both code-review resolutions confirmed landed in code: WR-01 (`factory.py:28-30` config-optional + real-`build_channel` test) and WR-03 (`selfcheck.py:101` OSError widening + parametrized regression test). WR-02 is an accepted-by-design open Info (documented disposition, not a gap). The one deferred item (live redeploy) is an intentional Gate-2 obligation.

---

_Verified: 2026-07-08T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
