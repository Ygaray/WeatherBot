---
phase: 27
slug: discord-adapter-panelkit-render-cycle-fix
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-29
---

# Phase 27 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest -q tests/test_panel.py tests/test_bot.py tests/test_import_hygiene.py` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command
- **Before `/gsd-verify-work`:** Full suite must be green (incl. Phase-21 panel/clone-render goldens + custom_id byte snapshots)
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {planner fills per task} | | | SEAM-07 | — | | golden/unit | | | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- *Planner fills.* Likely none new — existing infrastructure (Phase-21 goldens, `test_panel.py`,
  `test_bot.py`, `test_import_hygiene.py`, `test_golden_custom_ids.py`, `test_golden_embeds.py`,
  `test_injection_registry.py`) covers SEAM-07; this phase **extends** the import-hygiene + injection
  assertions (core↔adapter isolation, PanelKit injection, marker-param test) rather than standing up
  new frameworks.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live `yahir-mint` panel keeps routing (no "interaction failed") after the adapter relocation | SEAM-07 | Requires the live Discord gateway + the editable-install systemd daemon restart | Deferred Gate-2 milestone obligation (Phase 28 carries the live restart UAT); Gate-1 proves the mechanism via the frozen `custom_id` byte-string test + the persistent-view registration tests |

*The byte-identical panel behavior is golden-checkable; only the live-gateway round-trip is manual (deferred to milestone close).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
