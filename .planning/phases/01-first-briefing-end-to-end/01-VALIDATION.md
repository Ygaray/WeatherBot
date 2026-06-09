---
phase: 1
slug: first-briefing-end-to-end
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-09
validated: 2026-06-09
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `01-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via `uv add --dev pytest`) |
| **Config file** | none yet — Wave 0 adds `[tool.pytest.ini_options]` to `pyproject.toml` |
| **Quick run command** | `uv run pytest -x -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~5–15 seconds (all I/O mocked; recorded JSON fixtures) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -x -q`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

> Task IDs are assigned by the planner. Rows below map each phase requirement to its
> intended automated proof (from RESEARCH.md § Validation Architecture). The planner/executor
> binds Task ID + Wave to each row.

| Plan | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|------|-------------|----------|-----------|-------------------|-------------|--------|
| aggregate | FCST-02 | Buckets → today's high/low/rain on location-local date | unit | `uv run pytest tests/test_aggregate.py -x` | ✅ | ✅ green |
| aggregate | FCST-02 | Clear-sky day (no `rain`, pop=0) → rain_chance 0, no error | unit | `uv run pytest tests/test_aggregate.py::test_clear_sky -x` | ✅ | ✅ green |
| aggregate | FCST-02 | Local-midnight boundary (far +/− offset) selects local-today buckets | unit | `uv run pytest "tests/test_aggregate.py::test_tz_boundary_plus" "tests/test_aggregate.py::test_tz_boundary_minus" -x` | ✅ | ✅ green |
| client | FCST-01 | Client builds correct URL/params; parses current+forecast (mocked httpx) | unit | `uv run pytest tests/test_client.py -x` | ✅ | ✅ green |
| models | FCST-03/04 | Forecast normalized to imperial-primary display fields | unit | `uv run pytest tests/test_models.py -x` | ✅ | ✅ green |
| store | DATA-01/03 | Persist writes current + forecast rows from one fetch; raw JSON + normalized cols present | unit | `uv run pytest tests/test_store.py -x` | ✅ | ✅ green |
| store | DATA-02 | Generated columns queryable; forecast row carries `target_ts_utc` (accuracy-join key) | unit | `uv run pytest tests/test_store.py::test_target_ts -x` | ✅ | ✅ green |
| channel | DELV-02/03 | `Channel.send(text)` takes str; embed never crosses interface (mock webhook) | unit | `uv run pytest tests/test_channel.py -x` | ✅ | ✅ green |
| renderer | DELV-01 / D-01 | Renderer substitutes `{placeholder}`; missing key stays visible, no crash | unit | `uv run pytest tests/test_renderer.py -x` | ✅ | ✅ green |
| config | CONF-02 | Secrets load from env/`.env`, absent from config model | unit | `uv run pytest tests/test_config.py -x` | ✅ | ✅ green |
| send-now | CONF-04 / DELV-01 | `--send-now` composition runs end-to-end (all I/O mocked) | integration | `uv run pytest tests/test_send_now.py -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> **Audit note (2026-06-09):** The `tz_boundary` row is covered by two tests —
> `test_tz_boundary_plus` (Sydney, far +offset) and `test_tz_boundary_minus` (Honolulu, far −offset).
> An additional `tests/test_review_hardening.py` (10 tests) landed from `/gsd-code-review` hardening,
> beyond the per-task map above. Full suite: **67 passed, 0 failed, 0 xfail**.

---

## Wave 0 Requirements

- [x] `uv add --dev pytest` — installed (pytest 9.0.3, ruff 0.15.16)
- [x] `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths`/`pythonpath`/`addopts` present
- [x] `tests/conftest.py` — `tmp_db` fixture + `load_fixture` helper present
- [x] `tests/fixtures/` — 7 recorded OpenWeather JSON payloads present (imperial/metric clear, rainy, far +offset, far −offset)
- [x] Test files: `tests/test_aggregate.py`, `test_client.py`, `test_models.py`, `test_store.py`, `test_channel.py`, `test_renderer.py`, `test_config.py`, `test_send_now.py` — all present and green

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| A real briefing actually posts to the live Discord channel | DELV-01 | Requires a live webhook URL + visual confirmation in Discord | With `.env` populated, run `--send-now`; confirm the message appears in the channel with the `WeatherBot ☀️` identity, plain-text body, and the enrichment embed |
| OpenWeather key returns live data within quota | FCST-01 | Depends on external API + ~2h new-key activation | Run `--send-now` against the live API once; confirm a 200 with populated current+forecast |

*All other phase behaviors have automated verification via recorded fixtures.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s (full suite runs in ~0.67s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-06-09 — all 11 mapped requirements COVERED by green automated tests; 2 manual-only items justified (live external API/Discord).

---

## Validation Audit 2026-06-09

| Metric | Count |
|--------|-------|
| Requirements audited | 11 |
| COVERED (automated, green) | 11 |
| PARTIAL | 0 |
| MISSING | 0 |
| Gaps found | 0 |
| Resolved | 0 (none needed) |
| Escalated | 0 |
| Manual-only (justified) | 2 |

**Result:** NYQUIST-COMPLIANT. Suite: 67 passed, 0 failed, 0 xfail. No auditor spawn required — every automatable requirement already had a green test at audit time.
