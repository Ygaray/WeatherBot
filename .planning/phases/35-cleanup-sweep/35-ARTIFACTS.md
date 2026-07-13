# Phase 35 — Artifacts This Phase Produces

> Consumed by execute-phase drift verification. Lists every symbol this phase CREATES and every
> symbol it REMOVES. Removals are tagged `[removed]` so drift verification does not flag them as
> missing. Cleanup phase: behavior-preserving by default; the anchor invariant "the morning
> briefing always goes out, exactly once" is untouched (full suite green, 878 baseline).

## Created

| Symbol / Artifact | File | Plan | Notes |
|-------------------|------|------|-------|
| `tests/test_dead_code_removed.py` (module + its negative-grep test) | tests/ | 01 | Wave-0 gate: asserts removed dead symbols stay gone (F16/F46/F76/F92); token-from-parts, no self-trip |
| F74 regression test (`# HARD-CLEAN-02 / F74`) | tests/test_config.py | 04 | non-canonical HH:MM rejected |
| F75 regression test (`# HARD-CLEAN-02 / F75`) | tests/test_config.py | 04 | resolve_location id-then-name |
| F60 regression test (`# HARD-CLEAN-02 / F60`) | tests/test_uv_monitor.py | 05 | round() prewarn minutes |
| F68 regression test (`# HARD-CLEAN-02 / F68`) | tests/test_client.py | 05 | 2xx-non-JSON classified error |
| F105 snapshot/assertion (`# HARD-CLEAN-02 / F105`) | tests/test_command_views.py | 06 | default-location marker |
| F85 snapshot/assertion (`# HARD-CLEAN-02 / F85`) | tests/test_command_views.py | 06 | dated hourly When label |
| F79 assertion (if F79 fixed) | tests/test_bot.py | 06 | `!panel <text>` not dropped |
| F70 regression test (`# HARD-CLEAN-02 / F70`) | tests/test_multiday.py | 07 | drop beats contradictory same-day add |
| `errored` tick counter | weatherbot/scheduler/uvmonitor.py | 05 | F61 counter reconcile (fetched+skipped+errored==len) |
| `send-now` dispatch guard | weatherbot/cli.py | 03 | F78 fallthrough guard |
| `## Disposition Ledger (v2.1)` table | .planning/WHOLE-PROJECT-REVIEW.md | 09 | D-03 reconciliation record (appended) |
| In-code `# ACCEPTED (F##, v2.1): ...` annotations | (per site below) | 03/05/06/07/08 | D-02 accepted-finding markers |

### Accepted-annotation markers created (D-02)
F51, F56, F57, F58?, F59, F62, F67?, F71, F72, F73, F77, F79?, F80?, F82?, F83, F88, F103
(`?` = fix-or-accept; lands as an annotation only if the finding is accepted rather than fixed — the exact set is recorded in the Plan 09 Disposition Ledger and must match `grep -ohE "# ACCEPTED \(F[0-9]+, v2.1\)" -r weatherbot/`).

## Removed

| Symbol | File | Plan | Notes |
|--------|------|------|-------|
| `emit_online` (function) | weatherbot/scheduler/daemon.py | 08 | [removed] dead twin — live online-ping is inlined in `_run_daemon` (F16, D-05) |
| `_do_reload` (function) | weatherbot/scheduler/daemon.py | 08 | [removed] dead twin — live reload is `reload_engine.service_pending()` (F16, D-05) |
| `_argv_is_weatherbot` (function) | weatherbot/ops/pidfile.py | 02 | [removed] dead copy — live guard is hub's `_argv_matches_marker` (F46, D-05) |
| `test_argv_is_weatherbot_empty_and_forms` (test) | tests/test_golden_coverage_fill.py | 02 | [removed] exercised only the dead F46 function (D-05) |
| `is_transient(exc)` discarded call | weatherbot/ops/selfcheck.py | 02 | [removed] result-discarding call; both branches return NETWORK_NOT_READY (F92, D-05) |
| `verbose` param on `run_weather` + `verbose=args.verbose` call-site arg | weatherbot/cli.py | 03 | [removed] inert param; live `-v` plumbing is `main()`/`_configure_logging` (F76, D-05) |
| `_do_reload`-exclusive tests | tests/test_reload.py, tests/test_filewatch.py | 08 | [removed] exercised only the dead twin; live reload covered by test_reload_engine.py (D-05) |
| `emit_online`-exclusive tests | tests/test_scheduler.py | 08 | [removed] exercised only the dead twin (D-05) |
| `logging.getLogger("httpx").setLevel(...)` (F67, if superseded) | weatherbot/weather/client.py | 05 | [removed-or-accepted] superseded by Phase-30 redaction; removed only if URL-log coverage proven, else accepted (A4) |

> Note: symbols already removed by Phases 29–34 (e.g. `gate_until_healthy`@29, `_local_date_iso`
> copies@32) are NOT re-removed here — they are verify-then-mark FIXED@<phase> in the ledger (D-04),
> already absent from the tree.
