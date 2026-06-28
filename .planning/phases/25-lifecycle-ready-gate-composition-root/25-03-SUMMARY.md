---
phase: 25-lifecycle-ready-gate-composition-root
plan: 03
subsystem: testing
tags: [litmus, injection-registry, app-02, gate-1-self-uat, ready-gate, sd-notify, byte-identical, two-gate-uat]

# Dependency graph
requires:
  - phase: 25-lifecycle-ready-gate-composition-root
    provides: "build_runtime composition root + ReadyGate (no default probe) + the four injected leak points wired at the single root (25-02)"
provides:
  - "tests/test_injection_registry.py — the POSITIVE half of APP-02 (four leak points injected-at-root, not baked; each paired with a baked-default self-proof)"
  - "tests/test_import_hygiene.py extension — the 3-gate litmus re-run + lifecycle-in-scope tripwire, D-13 term set UNCHANGED"
  - "25-SELF-UAT.md — persistent Gate-1 self-UAT log: byte-level READY=1 socket capture + zero golden diff + green suite + clean litmus, per-criterion PASS"
affects: [26-command-registry, 27-panelkit-relocation, 28-physical-split, reminder-bot-reuse]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Positive injection-registry test: AST-introspect the single root (build_runtime) for the injected closures + inspect.signature for required (no-default) constructor params — proves 'injected, not baked' structurally with zero weather noun added"
    - "Gate-1 self-UAT drives the REAL ReadyGate + SystemdNotifier over a captured AF_UNIX/SOCK_DGRAM NOTIFY_SOCKET to prove READY=1 byte-level + ordering (mechanism-on-a-real-socket, not a mock)"
    - "Every positive assertion paired with a deliberately-baked-default self-proof (mirrors test_import_hygiene's _injected_app_leak / test_oracle_selfproof discipline)"

key-files:
  created:
    - tests/test_injection_registry.py
    - .planning/phases/25-lifecycle-ready-gate-composition-root/25-SELF-UAT.md
  modified:
    - tests/test_import_hygiene.py

key-decisions:
  - "Injection-registry assertions are STRUCTURAL (inspect.signature for required params + AST walk of build_runtime for injected kwargs/callees) — no app import needed (avoids discord.py/live-config), zero weather noun added to the module surface, litmus stays clean"
  - "health-check leak proven via ReadyGate REQUIRING health_check (no default → TypeError without it) — the module has no baked weather probe to fall back on; the strongest form of 'not baked'"
  - "config id-deriver leak proven via ReloadEngine REQUIRING desired_jobs + build_runtime injecting desired_jobs=/excluded_ids= — the module names no job id literal"
  - "selected-location + render leaks proven via app-side residence (panel.py:_selected_location, bot.py:render_embed) + zero location/render symbol under yahir_reusable_bot/ — Phase 27 relocates the panel; here only the injection seam is proven"
  - "_LITMUS pattern at L61 left UNCHANGED (D-13 lock) — added only a lifecycle-in-scope coverage tripwire + a scope-note docstring; generic seam names (health/ready/identity) are exactly what the module exposes"
  - "Gate-1 self-UAT proves READY=1 byte-level on a REAL captured socket (b'READY=1', order probe-pass<scheduler.start()<READY; zero READY on stop-preempt) — the live host reboot is the only deferred Gate-2 PARTIAL (physical step), not a phase blocker (CLAUDE.md Two-Gate UAT)"

patterns-established:
  - "Structural injection-registry proof (signature + single-root AST) for the 'injected-not-baked' half of a no-app-noun litmus"
  - "Driven-socket Gate-1 self-UAT for sd_notify READY ordering (real NOTIFY_SOCKET datagram capture)"

requirements-completed: [SEAM-05, APP-01, APP-02]

# Metrics
duration: 6min
completed: 2026-06-28
status: complete
---

# Phase 25 Plan 03: Injection Registry + Gate-1 Self-UAT Summary

**Proved APP-02's BOTH halves — kept the 3-gate negative litmus green over the grown `lifecycle/` module with the D-13 term set unchanged, and ADDED a positive injection-registry test asserting all four leak points (health-check, config id-deriver/exactly-once key, selected-location context, render_embed) are injected at the single root `build_runtime` with no module-side baked default (each paired with a baked-default self-proof) — then drove the REAL ReadyGate + SystemdNotifier over a captured `AF_UNIX`/`SOCK_DGRAM` `NOTIFY_SOCKET` to prove byte-level that `READY=1` reaches systemd strictly after probe-pass + `scheduler.start()` (and never on stop-preempt), and wrote a persistent Gate-1 self-UAT log with per-criterion PASS for criteria 1–4 + zero Phase-21 golden diff + 777-test green suite, leaving only the physical host reboot as a deferred Gate-2 obligation.**

## Performance

- **Duration:** ~6 min
- **Completed:** 2026-06-28
- **Tasks:** 2
- **Files:** 2 created, 1 modified

## Accomplishments

- **Task 1 — litmus extension + positive injection-registry (D-05):**
  - `tests/test_import_hygiene.py`: added a lifecycle-in-scope coverage tripwire to `test_litmus_clean` (asserts `ready_gate.py`/`sdnotify.py`/`health.py`/`identity.py` are in the `rglob` scan tree, so a future relocation can't silently drop the lifecycle seam from litmus coverage) + a scope-note documenting the grimp/isolated-import gates auto-scale to the new lifecycle edges. `_LITMUS` at L61 UNCHANGED (D-13 lock).
  - `tests/test_injection_registry.py` (new, 9 tests): the POSITIVE half of APP-02. Four leak-point assertions, each with a baked-default self-proof — health-check (`ReadyGate` requires `health_check`, no default), config id-deriver (`ReloadEngine` requires `desired_jobs`; root injects `desired_jobs=`/`excluded_ids=`), selected-location (app-side in `panel.py`; zero `location` symbol in the module), render (app-side in `bot.py`; zero `render` symbol in the module) — plus a cross-cutting single-root assertion (both engines constructed + all hooks injected at `build_runtime`) and three meta self-proofs that the introspection helpers bite.
- **Task 2 — Gate-1 autonomous self-UAT:** wrote `25-SELF-UAT.md` discharging all four success criteria with byte-level evidence:
  - **C1 (READY ordering) PASS:** drove the real `ReadyGate`+`SystemdNotifier` over a captured datagram socket — `b'READY=1'` emitted in order probe-pass(2) < `scheduler.start()`(3) < READY(6); zero datagrams + `rc=False` on stop-preempt.
  - **C2 (single root) PASS:** `build_runtime` defined once / called once; 777 passed.
  - **C3 (litmus clean) PASS:** 17 passed (3 negative gates + injection registry); `_LITMUS` unchanged.
  - **C4 (byte-identical oracle) PASS:** Phase-21 goldens 29 tests / 25 snapshots, zero diff, no golden edited.
  - Live `yahir-mint` reboot recorded as deferred Gate-2 PARTIAL (physical step only).

## Task Commits

1. **Task 1: extend litmus over lifecycle + positive injection-registry (APP-02 D-05)** - `cc9cdea` (test)
2. **Task 2: Gate-1 self-UAT — READY=1 socket capture + byte-identical oracle** - `2db533e` (test)

## READY=1 ordering capture method (C1 evidence)

Bound an `AF_UNIX`/`SOCK_DGRAM` socket, exported it as `$NOTIFY_SOCKET`, constructed
`SystemdNotifier()` AFTER the env was set (exactly as `build_runtime` does), drove
`ReadyGate.run(stop)` with the `on_online` hook modeling `scheduler.start()` as its FIRST step
(the real wiring), then `sock.recv()`'d the datagram. Captured `b'READY=1'` byte-identical with
strict ordering `probe-pass < scheduler.start() < READY datagram`; the stop-preempt scenario
sent zero datagrams and returned `False`. This drives the live sd_notify mechanism on a real
socket — the only unexercised step is a physical systemd-supervised host reboot.

## Golden-diff result (C4 evidence)

`uv run pytest -q` over the six Phase-21 golden files → **29 passed, 25 snapshots passed**,
zero non-empty diff. `git status` confirms NO golden snapshot file or golden test file was
modified (no `--snapshot-update`). BHV-02 intact.

## Deferred Gate-2 item

Live `yahir-mint` host restart UAT (`sudo systemctl restart weatherbot`, confirm `active` via
real unit-socket READY only after the startup self-check passes) — deferred to Gate-2
(milestone-close, Phase 28 / PKG-02). The mechanism + result are PASS via the driven socket;
only the physical reboot is outstanding. NOT a per-phase blocker (CLAUDE.md Two-Gate UAT).

## Deviations from Plan

None — plan executed exactly as written. (Two operational notes, not deviations: `python`
is not on PATH in this `uv` project, so all commands ran via `uv run`; and the structural
introspection approach for the injection-registry test was chosen to avoid importing the app —
which needs discord.py + a live config — keeping the assertions dependency-free and weather-noun-free,
within the plan's "keep the assertions structural" direction.)

## Known Stubs

None. The injection-registry test and the self-UAT log are the explicit scope of this plan;
both are complete and green.

## Threat Flags

None. No new network endpoint / auth path / file-access pattern / schema change. The self-UAT
binds a stdlib datagram socket in `/tmp` (T-25-07 repudiation mitigation: persistent auditable
log with exact commands); no golden edited (T-25-08 tampering mitigation); zero new dependency
(T-25-SC: stdlib `socket`/`inspect`/`ast` + existing pytest/grimp only).

## Next Phase Readiness

- APP-02 is now proven on BOTH halves — the negative litmus + the positive injection registry
  are standing gates Phase 26/27 re-run as the registry + Discord adapter relocate.
- `build_runtime` is established as the single composition root; Phase 26 registers commands
  there, Phase 27 injects `render` into the relocated PanelKit (the render leak seam proven here).
- The byte-identical oracle (Phase-21 goldens + 777-test suite) is green with zero diff — the
  mandate Phase 28's physical split re-runs against the git-pinned module.

## Self-Check: PASSED

All created files exist on disk (`tests/test_injection_registry.py`,
`.planning/phases/25-lifecycle-ready-gate-composition-root/25-SELF-UAT.md`); the modified
`tests/test_import_hygiene.py` is committed; both task commits (`cc9cdea`, `2db533e`) are
present in git history.

---
*Phase: 25-lifecycle-ready-gate-composition-root*
*Completed: 2026-06-28*
