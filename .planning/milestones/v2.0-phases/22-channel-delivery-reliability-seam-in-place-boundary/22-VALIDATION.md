---
phase: 22
slug: channel-delivery-reliability-seam-in-place-boundary
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-27
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Behavior must stay **byte-identical**: the 732-test suite + the Phase-21 golden snapshots
> are the oracle. Any non-empty snapshot diff is a failure to investigate, never `--snapshot-update`-ed away.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest `>=9.0.3` (+ syrupy `>=5.3.4` goldens, time-machine `>=2.16`) — VERIFIED in pyproject.toml |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| **Quick run command** | `uv run pytest tests/test_channel.py tests/test_reliability.py tests/test_import_hygiene.py -x` |
| **Full suite command** | `uv run pytest` (VERIFIED: **732 tests** collected) |
| **Golden update (oracle)** | `uv run pytest --snapshot-update` — only when a diff is INTENTIONAL; here it must NOT be |
| **Estimated runtime** | ~quick <5s / full ~tens of seconds |

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/test_channel.py tests/test_reliability.py tests/test_import_hygiene.py -x`
- **After every plan wave:** `uv run pytest` (full 732) + confirm **zero golden diff**
- **Before `/gsd-verify-work`:** full suite green + all three new gates green + zero snapshot diff
- **Max feedback latency:** ~5 seconds (quick), full suite under a minute

---

## Per-Task Verification Map

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| SEAM-01 | `Channel.send(text)->DeliveryResult` identical after move | characterization | `uv run pytest tests/test_channel.py -x` | ✅ |
| SEAM-01 | retry bursts / `Retry-After` honoring / no-retry-401-403 identical | characterization | `uv run pytest tests/test_reliability.py -x` | ✅ |
| SEAM-01 | delivery byte-identical (embed fields/order, CLI bytes, schedule plan, DB rows) | golden oracle | `uv run pytest tests/test_golden_*.py` | ✅ (Phase 21) |
| SEAM-01 | out-of-band alert path intact (`record_alert`/`resolve_alert` via injected port) | characterization | `uv run pytest tests/test_reliability.py tests/test_scheduler.py -x` | ✅ |
| PKG-01 | module imports zero app code (one-way dependency) | **NEW** import-graph gate | `uv run pytest tests/test_import_hygiene.py::test_module_imports_zero_app_code` | ❌ W0 |
| PKG-01 | module imports in isolation (app blocked) | **NEW** isolated-import smoke | `uv run pytest tests/test_import_hygiene.py::test_module_imports_with_app_blocked` | ❌ W0 |
| PKG-01 / APP-02 | no weather noun in module public surface | **NEW** AST litmus | `uv run pytest tests/test_import_hygiene.py::test_litmus_clean` | ❌ W0 |
| BHV-01 | whole suite green at the boundary | regression | `uv run pytest` | ✅ |
| BHV-02 | every Phase-21 golden snapshot byte-unchanged | golden oracle | `uv run pytest tests/test_golden_*.py tests/test_oracle_selfproof.py` | ✅ |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## What "fully covered" means per NEW gate (sampling/edge cases)

- **Import-graph gate (grimp):** must FAIL on a deliberately-introduced `TYPE_CHECKING` app
  import (e.g. a temporary `if TYPE_CHECKING: from weatherbot.weather.models import Forecast` in
  the moved `base.py`) — proven by the live probe that the `Forecast` edge IS visible by default
  (grimp 3.14 `exclude_type_checking_imports=False`). A passing gate after D-03 = the edge is
  gone. **Self-proof required:** a meta-test that temporarily adds a leak edge and asserts the
  gate catches it (mirrors Phase-21 `test_oracle_selfproof.py`).
- **Isolated-import smoke:** must FAIL (raise `ImportError` through the `sys.meta_path` blocker)
  if a module-import-time OR TYPE_CHECKING-realized app import exists; must PASS for the clean
  moved code (VERIFIED to pass for `reliability.retry` this session). Edge case: a purely
  *function-local* app import won't trip this — the static grimp gate is the authority there;
  document the complementarity.
- **AST litmus:** must catch a weather noun added to a `def`/`class`/param/annotation name (e.g.
  re-adding `send_briefing` or a `forecast:` param to the *module* surface); must IGNORE the same
  nouns in docstrings (`retry.py`'s "OpenWeather"/"Discord"/"briefing" prose → VERIFIED zero
  signature hits). Known gap: `\buv\b` misses `uv_index`-style names (underscore is a word char)
  — document, do not fix (D-13 locks the pattern).
- **Byte-identical oracle:** zero diff across ALL `tests/__snapshots__/` after the move. A
  non-empty diff is investigated, never `--snapshot-update`-ed away (Phase-21 D-04).

---

## Wave 0 Requirements

- [ ] `tests/test_import_hygiene.py` — the three new gates (import-graph, isolated-import, AST litmus) + self-proof meta-test. Covers PKG-01 / APP-02.
- [ ] `uv add --dev grimp` (grimp `>=3.14`) — confirmed NOT yet installed.
- [ ] `pyproject.toml`: `[tool.hatch.build.targets.wheel] packages = ["weatherbot", "yahir_reusable_bot"]` + `[tool.coverage.run] source` extension (no `[tool.hatch]` block exists today — VERIFIED hatchling backend).
- [ ] `yahir_reusable_bot/` package scaffold (`__init__.py` + `channels/`, `reliability/`, `ports/`).
- [ ] Re-export shims in `weatherbot/channels/__init__.py` and `weatherbot/reliability/__init__.py`.

*Existing test infra — conftest fixtures, syrupy goldens, the 732-test suite — covers all
behavior-preservation requirements; only the three import-hygiene gates are genuinely new.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | All phase behaviors have automated verification (the gates + the oracle suite) | — |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (3 new gates + grimp dep + packaging)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
