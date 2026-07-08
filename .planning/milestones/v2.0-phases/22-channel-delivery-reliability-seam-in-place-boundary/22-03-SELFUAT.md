# 22-03 Self-UAT — Reliability seam (retry engine + AlertSink port) byte-identical extraction

**Gate:** Gate-1 agent self-UAT (autonomous; gates the phase/PR). No per-phase human pause.
**Date:** 2026-06-27
**Plan:** 22-03 — move the retry engine into `yahir_reusable_bot.reliability` (D-06) + define the
`AlertSink` port (D-07), re-export via the `weatherbot.reliability` shim, `fire_slot` byte-identical.
**Oracle:** the full pytest suite + the Phase-21 syrupy goldens (embed bytes, CLI stdout/exit,
schedule plan, DB rows, custom_ids, exception identity).

## Per-criterion evidence

| # | Criterion (SEAM-01 / PKG-01 / BHV-01 / BHV-02) | Command | Observed | Verdict |
|---|---|---|---|---|
| 1 | **BHV-01** Full suite green, byte-identical | `uv run pytest -q` | `738 passed` (exit 0); cosmetic syrupy line `2 snapshots failed. 27 snapshots passed.` (unused-snapshot accounting — same line on the 738 baseline, documented in 22-01/22-02; NOT a test failure) | PASS |
| 2 | **BHV-02** Zero golden snapshot diff | `git status --porcelain tests/__snapshots__/` then `wc -c` | output = **0 bytes** (empty); `od -c` shows no bytes | PASS |
| 3 | **PKG-01** grimp gate — zero module→app edges over the FULL module | `grimp.build_graph('yahir_reusable_bot')` leak scan | graph now includes `reliability`, `reliability.retry`, `ports`, `ports.alerts` (+ channels); `app leaks: []` | PASS |
| 4 | **PKG-01** isolated-import smoke (app namespace blocked) | `tests/test_import_hygiene.py::test_module_imports_with_app_blocked` (+ self-proof) | passes — every `yahir_reusable_bot.*` module imports with `weatherbot` blocked | PASS |
| 5 | **PKG-01** AST litmus clean over the full module (incl. `ports/alerts.py`) | `tests/test_import_hygiene.py::test_litmus_clean` (+ self-proof) + the port one-liner | no weather noun in any `def`/`class`/param/annotation name; the port's `location_name` is renamed to `target` | PASS |
| 6 | **SEAM-01** retry engine weather-clean in the module | `inspect.getsource(yahir_reusable_bot.reliability.retry)` contains no `weatherbot` | true; pragma `# pragma: no cover` carried verbatim | PASS |
| 7 | **SEAM-01** app shim re-exports the SAME objects (no copy) | `weatherbot.reliability.build_retrying is yahir_reusable_bot.reliability.build_retrying`; `RETRY_AFTER_CAP_S`/`is_transient` identity across `config.models`, `reliability.retry`, module | all `is` checks pass (Phase-21 exception-identity pins hold) | PASS |
| 8 | **SEAM-01** AlertSink port shape | port one-liner: has `record_alert`+`resolve_alert`, NOT `briefing_missed`/heartbeat; app `weatherbot.weather.store` satisfies it structurally (arg counts match) | PASS |
| 9 | Standing-gate self-proofs + oracle self-proof green | `uv run pytest tests/test_import_hygiene.py tests/test_oracle_selfproof.py -q` | `8 passed` (each gate's perturbation-must-fail half bites) | PASS |
| 10 | Focused regression (fire_slot byte-identical) | `uv run pytest tests/test_scheduler.py tests/test_reliability.py -x` | `80 passed` — same retry bursts, Retry-After honoring, no-retry-on-401/403, same record/resolve calls + reason taxonomy | PASS |

## Standing-gate status (D-13)

The three import-hygiene gates (grimp graph, isolated-import smoke, AST litmus) + their
perturbation self-proofs are GREEN over the **complete moved surface so far**:
`channels` (22-02) + `reliability`/`reliability.retry` + `ports`/`ports.alerts` (22-03).
This file documents them as the STANDING criterion **phases 23–27 re-run** as each further
real surface (scheduler, config, lifecycle, registry, Discord adapter) moves into the module.
No `--snapshot-update` was run (Phase-21 D-04).

## Deferred Gate-2 host obligation (milestone-close, NOT a phase blocker)

On host `yahir-mint` after the physical split (Phase 28 territory), the deferred human/host
UAT remains: `uv sync` → `sudo systemctl restart weatherbot` → confirm `import yahir_reusable_bot`
resolves and the daemon comes online against the pinned module, retry/alert path intact. Tracked
as a milestone-close item, consistent with the user's Two-Gate UAT policy — it does NOT block this
phase.

## Verdict

**PASS.** The complete channel + reliability + AlertSink extraction lands byte-identical: full
738-test oracle green, zero golden diff, all three import-hygiene gates green over the full module,
retry engine weather-clean with same-object shims, `AlertSink` port litmus-clean, `fire_slot`
orchestration byte-identical. Sufficient to complete the phase and proceed automatically.
