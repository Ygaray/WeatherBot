---
phase: 10
slug: file-watch-auto-reload
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-16
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest 9.0.3` (pinned in `pyproject.toml`/`uv.lock`; `time-machine 2.16` for clocks). fd counts via stdlib `/proc/<pid>/fd` — `psutil` is NOT installed and is intentionally not added. |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| **Quick run command** | `uv run pytest tests/test_filewatch.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | quick: ~5–10s; full suite: ~25–40s (the SC#3 ≥50-save soak + bounded settle windows dominate the file-watch slice) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_filewatch.py -x`
- **After every plan wave:** Run `uv run pytest` (full suite; `tests/test_reload.py` is the Phase-9 regression guard for the inherited reload engine)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds (quick command)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 0 | CFG-03 | T-10-01 / T-10-02 | RED scaffold pins exactly-one-reload (SC#2) + keep-old (SC#4) + `.env` ZERO-reload (Pitfall #12) before wiring exists | scaffold (collect+RED) | `uv run pytest tests/test_filewatch.py --collect-only -q` (8 nodes) then `uv run pytest tests/test_filewatch.py -x` (RED) | ❌ W0 (this task CREATES it) | ⬜ pending |
| 10-02-CK | 02 | 1 | CFG-03 | T-10-SC | watchfiles legitimacy verified on pypi.org (author/version/source/non-typosquat) BEFORE install | checkpoint:human-verify (blocking-human) | manual — pypi.org/project/watchfiles | N/A | ⬜ pending |
| 10-02-01 | 02 | 1 | CFG-03 | T-10-SC | `watchfiles>=1.2.0` lands in runtime deps (not dev), importable | smoke/import | `uv run python -c "import watchfiles; print(watchfiles.__version__)" && grep -c 'watchfiles>=1.2.0' pyproject.toml` | ✅ | ⬜ pending |
| 10-02-02 | 02 | 1 | CFG-03 | T-10-03 / T-10-04 | `[reload]` table is frozen `extra="forbid"` (unknown key → ValidationError); carries only a bool, no secret | unit (tdd) | `uv run pytest tests/test_models.py -x && uv run python -c "from weatherbot.config.models import Config, ReloadConfig; assert Config(locations=[]).reload.watch is True; assert ReloadConfig(watch=False).watch is False; print('ok')"` | ✅ (extends `tests/test_models.py`) | ⬜ pending |
| 10-03-01 | 03 | 2 | CFG-03 | T-10-01 / T-10-02 / T-10-07 | observer is flag-set-only (no `_do_reload` on observer thread); `step=400` coalesces save-storms; `.env` filtered out | integration (tdd) | `uv run pytest tests/test_filewatch.py::test_save_triggers_reload tests/test_filewatch.py::test_editor_save_patterns_one_reload tests/test_filewatch.py::test_env_save_never_reloads -x` | ✅ (W0 file from 10-01) | ⬜ pending |
| 10-03-02 | 03 | 2 | CFG-03 | T-10-05 / T-10-06 / T-10-08 | single long-lived observer, clean SIGTERM teardown, fd-stable soak (incl. A4 re-derive); keep-old on invalid save (SC#4) | integration/soak (tdd) | `uv run pytest tests/test_filewatch.py -x && uv run pytest tests/test_reload.py -x` | ✅ (W0 file from 10-01) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### SC / Specific-Idea → Test Node coverage (from RESEARCH Test Map)

| SC / Idea | Test Node | Verified In Task |
|-----------|-----------|------------------|
| SC#1 (save → reload) | `test_save_triggers_reload` | 10-03-01 |
| SC#2 (editor save-storms → one reload) | `test_editor_save_patterns_one_reload` | 10-03-01 |
| SC#3 (fd-stable soak + clean SIGTERM teardown) | `test_fd_stable_and_clean_teardown` | 10-03-02 |
| SC#4 (invalid save → keep-old) | `test_invalid_save_keeps_old_config` | 10-03-02 |
| Idempotence (identical save → +0 -0 ~0) | `test_identical_save_zero_job_changes` | 10-03-02 |
| Toggle D-03 (`[reload] watch = false`) | `test_watch_toggle_off_no_observer` | 10-03-02 (toggle advances past 10-02-02) |
| `.env` filter (Pitfall #12) | `test_env_save_never_reloads` | 10-03-01 |
| Watch-set re-derive (D-04) | `test_watch_set_rederived_on_reload` | 10-03-02 |

---

## Wave 0 Requirements

- [ ] `tests/test_filewatch.py` — RED scaffold (created by Task 10-01-01): the 8 named nodes above + local helpers `truncate_write` / `temp_then_rename` / `multi_event_burst` + deferred-import wrappers for `_run_watch_observer` / `_derive_watch_dirs` / `_make_watch_filter`. Must COLLECT 8 node IDs and fail RED on genuine missing-symbol errors.
- [ ] No shared `tests/conftest.py` change — local config builders (`_loc`/`_cfg`/`_slot`) are copied from `tests/test_reload.py` into `test_filewatch.py` (mirrors the project's Wave-0 idiom; no new shared fixtures).
- [ ] Framework already present (`pytest 9.0.3`); the only new dependency is `watchfiles>=1.2.0`, installed in Wave 1 (10-02-01) before the observer module imports it. No `psutil` install — fd counts use stdlib `/proc/<pid>/fd`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `watchfiles` package legitimacy on PyPI | CFG-03 (T-10-SC) | slopcheck was not installable this session; supply-chain trust requires a human eyeball before `uv add` | Open https://pypi.org/project/watchfiles/ — confirm `1.2.0` (2026-05-18), `Requires: Python >=3.10`, maintainer `samuelcolvin`, source `github.com/samuelcolvin/watchfiles`, not a typosquat. Then approve the 10-02 checkpoint. |

*All Phase-10 runtime behaviors (SC#1–4 + idempotence + toggle + `.env`-filter + watch-set re-derive) have automated verification; only the one-time supply-chain check is manual.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (every plan task carries an `<automated>` command; the one manual item is a supply-chain checkpoint, not a behavior)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (`tests/test_filewatch.py` is the RED scaffold; all 8 nodes are MISSING at W0 and created by 10-01-01)
- [x] No watch-mode flags (no `--watch`/`pytest-watch`; the observer's own `watch()` runs with bounded `rust_timeout=500` and a `stop_event`, never an unbounded test watcher)
- [x] Feedback latency < 10s (quick command)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-16
