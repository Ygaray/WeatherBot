---
phase: 6
slug: shared-lookup-core-command-parser
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-15
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Validation Architecture detail lives in `06-RESEARCH.md` § "Validation Architecture".

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~few seconds (offline; recorded fixtures, no network) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

> Filled by the planner / Nyquist auditor against the final PLAN.md tasks. The four phase
> success criteria map to these test families (per 06-RESEARCH.md § Validation Architecture):

| Success Criterion | Test Type | Validation Approach |
|-------------------|-----------|---------------------|
| #1 `lookup_weather` resolves + fetches + renders + returns | unit | New `tests/test_lookup.py` against recorded fixtures (FakeClient + `load_fixture`); assert `.text`, `.forecast`, `.location` on the returned LookupResult |
| #2 zero store-writes from `lookup_weather` | unit | Monkeypatch all 7 store write fns (persist/claim_slot/record_alert/resolve_alert/stamp_tick/stamp_success/stamp_health) to raise; assert lookup completes; assert empty `tmp_db` |
| #3 `parse_weather_command` stable result | unit | New `tests/test_command.py` input matrix: `weather`, `weather home`, `weather New York`, whitespace/case variants → Command; `hello`/empty/`weatherman` → NotACommand |
| #4 `send_now` byte-identical | regression | Existing `tests/test_send_now.py` stays unmodified and green; assert rendered text unchanged for fixtures |

*Status tracked during execution: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_command.py` — parser input-matrix stubs (criterion #3)
- [ ] `tests/test_lookup.py` — lookup core + zero-store-writes stubs (criteria #1, #2)
- Existing `tests/conftest.py` fixtures (`load_fixture`, `tmp_db`, FakeClient/FakeChannel) cover the rest — no new infrastructure.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | All phase behaviors have automated verification. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-15 (gsd-plan-checker Dimension 8 PASS)
