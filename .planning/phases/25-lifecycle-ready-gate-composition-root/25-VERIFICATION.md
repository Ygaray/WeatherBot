---
phase: 25-lifecycle-ready-gate-composition-root
verified: 2026-06-28T00:00:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 25: Lifecycle READY-Gate + Composition Root Verification Report

**Phase Goal:** Extract the process-lifecycle layer (systemd Type=notify READY-gate, supervised-restart contract, heartbeat) into `yahir_reusable_bot` so it gates READY=1 on an app-provided health-check callback; consolidate WeatherBot's wiring at a single composition root (`build_runtime`) with zero duplicated module mechanism; prove the four leak points are injected, not baked (litmus: no weather term in the module); behavior byte-identical (Phase-21 goldens + full suite as oracle).
**Verified:** 2026-06-28
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (4 ROADMAP success criteria, consolidated against PLAN must_haves)

| # | Truth (ROADMAP SC) | Status | Evidence |
| - | ------------------ | ------ | -------- |
| 1 | Lifecycle layer gates READY=1 on an app-provided health-check callable; READY reaches systemd only after the app probe passes; no weather code / no `weatherbot` literal in the module lifecycle | ✓ VERIFIED | `ReadyGate.run()` (ready_gate.py L90-119) loops on injected `self._health_check()`, fires `on_online` then `notifier.ready()` only on first pass. `ReadyGate.__init__` `health_check` has NO default (REQUIRED → no baked probe, confirmed via inspect.signature). `grep weatherbot yahir_reusable_bot/lifecycle/*.py` = 0 hits. `auth_failed`/`network_not_ready` = none (severity-branched, L103). `time.sleep` = prose only (L12/80/116 docstrings); code uses `stop.wait(interval)` L117. SELF-UAT C1: real `AF_UNIX` socket captured `b'READY=1'`, order probe-pass(2) < scheduler.start()(3) < READY(6); zero datagrams on stop-preempt. |
| 2 | WeatherBot wires the module at a single composition root (`build_runtime`) registering commands/config/health probe/render_embed/selected-location, zero duplicated module mechanism | ✓ VERIFIED | `def build_runtime` defined once (wiring.py:107); exactly one call site (daemon.py:1389). ReadyGate constructed once in wiring.py L314 with injected `_health_check`/`on_online`/`on_fail`. run_daemon keeps load-bearing ordering inline: write_pid before gate (L1431), `ready_gate.run(stop)` (L1465), `identity.pid_file.unlink` in finally (L1589). |
| 3 | The four leak points injected at the root, not baked — proven by litmus (no weather term in module) AND positive injection-registry test | ✓ VERIFIED | `tests/test_injection_registry.py` + `tests/test_import_hygiene.py` + `tests/test_lifecycle_module.py` = 23 passed. Zero `location`/`render` symbol in `yahir_reusable_bot/`. Leak points app-side: `_selected_location` (panel.py), `render_embed` (bot.py:194), `run_self_check` (selfcheck.py:63), id-deriver via ReloadEngine `desired_jobs`. ReadyGate `health_check` required (TypeError without it). |
| 4 | Shipped systemd unit is a parameterized template (identity supplied by the app) | ✓ VERIFIED | `deploy/bot.service.template` exists with `<NAME>`/`<RUNTIME_DIR>` placeholders. `diff <(sed <NAME>=WeatherBot,<RUNTIME_DIR>=weatherbot template) deploy/weatherbot.service` = EMPTY (byte-identical render). |

**PLAN must_haves cross-check (key load-bearing ones, all VERIFIED):**

| Must-have | Status | Evidence |
| --------- | ------ | -------- |
| Default `LifecycleIdentity` reproduces `/run/weatherbot/weatherbot.pid` + `b"weatherbot"` | ✓ VERIFIED | `default_identity()` → pid_file `/run/weatherbot/weatherbot.pid`, proc_marker `b'weatherbot'`. `WEATHERBOT_PROC_MARKER = b"weatherbot"` (pidfile.py:34). |
| sdnotify is a shim resolving to the identical module object | ✓ VERIFIED | `from weatherbot.ops import SystemdNotifier is L.SystemdNotifier` → True. |
| pid guard byte-identical under generalized `proc_marker` | ✓ VERIFIED | argv0-basename / `python -m` / non-match: app wrapper == module guard for all three (True/True/False). |
| READY NOT emitted inside build_runtime | ✓ VERIFIED | No actual `notifier.ready()` CALL in wiring.py (only docstring L30 + comment L295). READY fired only by gate path post-start. |
| on_online runs scheduler.start() FIRST so READY is strictly after start | ✓ VERIFIED | wiring.py L300: `scheduler.start()` is first line of `_on_online`, before stamp_health/tick/ping. |
| Full suite + Phase-21 goldens green, zero golden diff | ✓ VERIFIED | Full suite 777 passed, 0 test failures. Goldens 29 passed / 25 snapshots, zero diff, git status clean (no golden edited). |

**Score:** 7/7 must-haves verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `yahir_reusable_bot/lifecycle/{sdnotify,health,identity,ready_gate,__init__}.py` | reusable lifecycle surface | ✓ VERIFIED | All present, substantive, weather-noun-free; imported by wiring.py |
| `weatherbot/scheduler/wiring.py` | `build_runtime` single root | ✓ VERIFIED | Defined once, called once from run_daemon |
| `weatherbot/ops/sdnotify.py` | re-export shim | ✓ VERIFIED | Resolves to identical module object |
| `deploy/bot.service.template` | parameterized unit | ✓ VERIFIED | `<NAME>`/`<RUNTIME_DIR>` placeholders; byte-identical render |
| `tests/test_injection_registry.py` | positive injected-not-baked proof | ✓ VERIFIED | Green; paired baked-default self-proofs |
| `tests/test_import_hygiene.py` | 3-gate litmus over grown module | ✓ VERIFIED | Green; `_LITMUS` term set unchanged (D-13 lock) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| default_identity byte-identical | `python -c default_identity()` | pid `/run/weatherbot/weatherbot.pid`, marker `b'weatherbot'` | ✓ PASS |
| sdnotify shim identity | `SystemdNotifier is L.SystemdNotifier` | True | ✓ PASS |
| pid guard byte-identity | app wrapper vs module guard, 3 cmdlines | True/True/False match | ✓ PASS |
| ReadyGate health_check required | inspect.signature default check | empty (required) | ✓ PASS |
| .service render byte-identity | `diff <(sed template) weatherbot.service` | empty | ✓ PASS |
| injection/litmus/lifecycle tests | `pytest test_injection_registry test_import_hygiene test_lifecycle_module` | 23 passed | ✓ PASS |
| Phase-21 golden oracle | `pytest golden_*` | 29 passed, 25 snapshots, 0 diff | ✓ PASS |
| Full suite (BHV-01) | `pytest -q` | 777 passed, 0 test failures | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| SEAM-05 | 25-01/02/03 | Lifecycle layer gates READY on app-provided health-check; weather probe stays app-side | ✓ SATISFIED | ReadyGate injected health_check; run_self_check app-side; READY ordering proven |
| APP-01 | 25-02/03 | Single composition root registering commands/config/probe/render_embed/selected-location | ✓ SATISFIED | build_runtime defined once / called once; four leak points injected at root |
| APP-02 | 25-02/03 | Four leak points injected not baked; litmus no weather term in module | ✓ SATISFIED | Litmus clean (0 weatherbot hits); positive injection-registry test green |
| BHV-01 (cross-cutting) | re-run | Full suite green at boundary | ✓ SATISFIED | 777 passed, 0 failures |
| BHV-02 (cross-cutting) | re-run | Goldens byte-identical | ✓ SATISFIED | 29 golden / 25 snapshots, 0 diff, no golden edited |
| PKG-01 (cross-cutting) | re-run | Module imports zero app code, litmus gate | ✓ SATISFIED | Litmus green over grown lifecycle edges |

All three phase requirement IDs (SEAM-05, APP-01, APP-02) plus the cross-cutting grep gates (BHV-01/02, PKG-01) are accounted for and SATISFIED. No orphaned requirements.

### Anti-Patterns Found

None. Zero debt markers (TBD/FIXME/XXX) in any phase-25 modified file. No `time.sleep` in gate code (interruptible `stop.wait` only). No reason-string severity branching.

One documented additive note (25-02 deviation): the module's `ReadyGate` logs a generic severity line in addition to the app's classified startup-failure log via the `on_fail` hook. Confirmed additive (failure-path only, not golden-pinned) — no suite assertion or golden depends on the line count. Not a defect.

`gate_until_healthy` / `emit_online` remain DEFINED but uncalled in daemon.py (documented carried-forward dead code, no imports, no coverage gate). Harmless; flagged for a future cleanup phase. Not a blocker.

### Human Verification Required

None at the mechanism level — all four success criteria were discharged autonomously with byte-level evidence (Gate-1 self-UAT, READY=1 socket capture, empty golden diff, green suite).

One DEFERRED Gate-2 obligation (correct disposition per CLAUDE.md Two-Gate UAT, NOT a phase blocker): live `yahir-mint` host reboot — `sudo systemctl restart weatherbot` confirming `active` via the real unit socket only after the startup self-check passes. The mechanism + result are PASS via the driven socket; only the physical reboot is outstanding (recorded for Phase 28 / PKG-02 milestone-close).

### Gaps Summary

No gaps. Every ROADMAP success criterion is observably TRUE in the codebase, verified independently of SUMMARY claims:

1. ReadyGate gates READY=1 on the injected health_check (no baked probe), READY strictly after probe-pass + scheduler.start(), module is weather-noun-free (0 `weatherbot` literals, severity-branched not reason-branched, interruptible loop).
2. build_runtime is the single composition root (defined once, called once); run_daemon keeps the load-bearing ordering inline.
3. The four leak points are injected app-side (zero location/render symbols in the module); litmus clean + positive injection-registry test green.
4. The .service ships as a `<NAME>`/`<RUNTIME_DIR>` template rendering byte-identical to weatherbot.service.

Byte-identical oracle intact: 777 passed, Phase-21 goldens zero diff, no golden file edited. The "2 snapshots failed" syrupy line is the documented pre-existing unused-snapshot tally (present at baseline, zero pytest assertion failures) — NOT a regression.

---

_Verified: 2026-06-28_
_Verifier: Claude (gsd-verifier)_
