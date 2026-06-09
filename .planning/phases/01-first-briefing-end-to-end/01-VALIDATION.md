---
phase: 1
slug: first-briefing-end-to-end
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
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
| aggregate | FCST-02 | Buckets → today's high/low/rain on location-local date | unit | `uv run pytest tests/test_aggregate.py -x` | ❌ W0 | ⬜ pending |
| aggregate | FCST-02 | Clear-sky day (no `rain`, pop=0) → rain_chance 0, no error | unit | `uv run pytest tests/test_aggregate.py::test_clear_sky -x` | ❌ W0 | ⬜ pending |
| aggregate | FCST-02 | Local-midnight boundary (far +/− offset) selects local-today buckets | unit | `uv run pytest tests/test_aggregate.py::test_tz_boundary -x` | ❌ W0 | ⬜ pending |
| client | FCST-01 | Client builds correct URL/params; parses current+forecast (mocked httpx) | unit | `uv run pytest tests/test_client.py -x` | ❌ W0 | ⬜ pending |
| models | FCST-03/04 | Forecast normalized to imperial-primary display fields | unit | `uv run pytest tests/test_models.py -x` | ❌ W0 | ⬜ pending |
| store | DATA-01/03 | Persist writes current + forecast rows from one fetch; raw JSON + normalized cols present | unit | `uv run pytest tests/test_store.py -x` | ❌ W0 | ⬜ pending |
| store | DATA-02 | Generated columns queryable; forecast row carries `target_ts_utc` (accuracy-join key) | unit | `uv run pytest tests/test_store.py::test_target_ts -x` | ❌ W0 | ⬜ pending |
| channel | DELV-02/03 | `Channel.send(text)` takes str; embed never crosses interface (mock webhook) | unit | `uv run pytest tests/test_channel.py -x` | ❌ W0 | ⬜ pending |
| renderer | DELV-01 / D-01 | Renderer substitutes `{placeholder}`; missing key stays visible, no crash | unit | `uv run pytest tests/test_renderer.py -x` | ❌ W0 | ⬜ pending |
| config | CONF-02 | Secrets load from env/`.env`, absent from config model | unit | `uv run pytest tests/test_config.py -x` | ❌ W0 | ⬜ pending |
| send-now | CONF-04 / DELV-01 | `--send-now` composition runs end-to-end (all I/O mocked) | integration | `uv run pytest tests/test_send_now.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `uv add --dev pytest` — install framework
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths`, etc.
- [ ] `tests/conftest.py` — shared fixtures + a tmp SQLite DB fixture
- [ ] `tests/fixtures/` — **recorded OpenWeather JSON** for: clear-sky day, rainy day, far +offset, far −offset, imperial & metric variants (drive FCST-02 per SUMMARY.md)
- [ ] Test stubs: `tests/test_aggregate.py`, `test_client.py`, `test_models.py`, `test_store.py`, `test_channel.py`, `test_renderer.py`, `test_config.py`, `test_send_now.py`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| A real briefing actually posts to the live Discord channel | DELV-01 | Requires a live webhook URL + visual confirmation in Discord | With `.env` populated, run `--send-now`; confirm the message appears in the channel with the `WeatherBot ☀️` identity, plain-text body, and the enrichment embed |
| OpenWeather key returns live data within quota | FCST-01 | Depends on external API + ~2h new-key activation | Run `--send-now` against the live API once; confirm a 200 with populated current+forecast |

*All other phase behaviors have automated verification via recorded fixtures.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
