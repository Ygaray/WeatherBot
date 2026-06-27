---
phase: 16
slug: extract-shared-dispatch-spec
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-27
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Reconstructed from artifacts (State B) on 2026-06-27 — phase executed 2026-06-23 without a VALIDATION.md.
> This is a pure, behavior-preserving refactor (PANEL-10): its validation IS the existing
> contractual suite staying byte-identical green, augmented by the dedicated `test_dispatch.py`
> per-branch resolution tests.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (`uv run pytest`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["tests"]`) |
| **Quick run command** | `uv run pytest tests/test_dispatch.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~2s (dispatch+bot+cli+registry+command set); ~6s full suite |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_dispatch.py tests/test_bot.py tests/test_cli.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~6 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | PANEL-10 | T-16-01 / T-16-02 | Acyclic import graph; read-only ladder — no store/sent-log/scheduler writes | unit | `uv run pytest tests/test_dispatch.py -q` | ✅ | ✅ green |
| 16-01-02 | 01 | 1 | PANEL-10 | T-16-03 | `on_message` routes via `dispatch_spec`; off-loop SQLite read never blocks gateway loop; byte-identical replies | unit | `uv run pytest tests/test_bot.py -q` | ✅ | ✅ green |
| 16-01-03 | 01 | 1 | PANEL-10 | T-16-02 | CLI routes via sync `dispatch_reply`; identical output + exit codes 0/1/2/3 | unit | `uv run pytest tests/test_cli.py -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Coverage detail (PANEL-10 — single source of truth, no command drift)

`tests/test_dispatch.py` (16 nodes, all green) directly exercises the shared dispatcher:

- **Per-branch ladder resolution** (criterion #1) — one test per `dispatch_reply` branch: forecast
  (`handler(result, flags)`), next-cloudy (`handler(result, cloud_threshold)`), uv
  (`handler(result, uv.threshold)`), plain location (`handler(result)`), status
  (`handler(daemon_state)`), locations (`handler(config)`), help (`handler()`).
- **Read-only discipline** (criterion #4) — `test_dispatch_reply_does_no_fetch_or_render` asserts the
  ladder invokes only the handler and returns the `CommandReply` unchanged (no fetch/render/writes).
- **Async off-loop wrapper** — `dispatch_spec` forecast 3-arg cache-key widening, text-forecast
  flags-parse + suffix widening (WR-01, added 260626-rd8), plain-weather 2-arg lookup,
  unknown-location bubble, flags passthrough/byte-identical, argless never-fetches, and the
  D-08b executor audit (`test_briefing_path_not_on_default_executor`).
- **Byte-identical behavior** (criterion #2, the anti-drift / behavior-preservation gate) —
  `tests/test_bot.py` + `tests/test_cli.py` stay green, proving replies and CLI exit codes
  unchanged after the refactor.
- **Single-path source assertion** (criterion #3) — `tests/test_registry.py` anti-drift suite +
  grep gates (no parallel `spec.name == "next-cloudy"` ladder in `bot.py`/`cli.py`) confirm the
  ladder lives only in `dispatch.py`.

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. No Wave 0 install needed — pytest +
`tests/` were already established by v1.0/v1.1; `tests/test_dispatch.py` was created in this phase
(Task 1) and is green.

---

## Manual-Only Verifications

*All phase behaviors have automated verification.* This is a pure internal refactor with no
new user-visible behavior; the device-verifiable acceptance ("replies and exit codes unchanged")
is fully encoded by the contractual suite staying byte-identical green. No live-host UAT applies
to Phase 16 (no deferred Gate-2 items).

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none — existing infra)
- [x] No watch-mode flags
- [x] Feedback latency < 6s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-27

---

## Validation Audit 2026-06-27

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Reconstructed from artifacts (State B). All three tasks for PANEL-10 carry automated `<verify>`
commands that run green (`test_dispatch.py` 16/16, full phase-16 coverage set 136 passed). The
phase's behavior-preservation guarantee is proven by the existing contractual suite staying
byte-identical green. No coverage gaps — phase is Nyquist-compliant.
