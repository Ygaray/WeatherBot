---
phase: 01-first-briefing-end-to-end
plan: 01
subsystem: config-and-test-foundation
tags: [scaffold, config, secrets, pydantic, pytest, fixtures, supply-chain]
requires: []
provides:
  - "weatherbot.config.models: Location, WebhookIdentity, Config"
  - "weatherbot.config.settings: Settings (secrets-from-env)"
  - "weatherbot.config.loader: load_config, load_settings, resolve_location"
  - "tests/conftest.py: tmp_db fixture + load_fixture helper"
  - "tests/fixtures/*.json: 7 recorded OpenWeather payloads (FCST-02 edge matrix)"
  - "tests/test_send_now.py: xfail end-to-end contract (drives Plans 02-04 green)"
affects:
  - "All downstream Phase 01 plans depend on this config + fixture + test scaffold"
tech-stack:
  added:
    - "uv 0.11.19 (project + dependency manager)"
    - "httpx 0.28.1"
    - "discord-webhook 1.4.1"
    - "pydantic 2.13.4"
    - "pydantic-settings 2.14.1"
    - "structlog 26.1.0"
    - "pytest 9.0.3 (dev)"
    - "ruff 0.15.16 (dev)"
  patterns:
    - "Secrets-from-env via pydantic-settings BaseSettings; Config model holds NO secret field (CONF-02)"
    - "locations as a LIST even with one entry (D-06)"
    - "resolve_location: None -> first; name -> case-insensitive match; else ValueError (D-07)"
    - "stdlib tomllib (binary mode) + Pydantic validation for fail-loud config loading"
    - "strict xfail end-to-end test as the 'definition of done' that later plans drive green (CONF-04)"
key-files:
  created:
    - pyproject.toml
    - uv.lock
    - .python-version
    - .env.example
    - config.example.toml
    - weatherbot/__init__.py
    - weatherbot/config/__init__.py
    - weatherbot/config/models.py
    - weatherbot/config/settings.py
    - weatherbot/config/loader.py
    - tests/conftest.py
    - tests/fixtures/current_imperial_clear.json
    - tests/fixtures/current_metric_clear.json
    - tests/fixtures/forecast_imperial_clear.json
    - tests/fixtures/forecast_metric_clear.json
    - tests/fixtures/forecast_imperial_rainy.json
    - tests/fixtures/forecast_imperial_offset_plus.json
    - tests/fixtures/forecast_imperial_offset_minus.json
    - tests/test_config.py
    - tests/test_send_now.py
  modified:
    - .gitignore
decisions:
  - "Pinned all 7 deps to RESEARCH/CLAUDE.md-verified versions; uv resolved exactly to those lines"
  - "jinja2 and python-dotenv deliberately excluded (guarded str-substitution renderer; pydantic-settings reads .env natively)"
  - "End-to-end test marked strict xfail until Plan 04 wires weatherbot.cli.send_now"
metrics:
  duration: "continuation (Tasks 1-3 prior session; Task 4 gate + closeout this session)"
  completed: "2026-06-09"
  tasks: 4
  files: 21
requirements-completed: [CONF-02]
---

# Phase 1 Plan 1: Config + Test Foundation Summary

Stood up the WeatherBot walking-skeleton foundation — uv scaffold, the secrets-from-env + non-secret-TOML config layer (`Settings` / `Config` / `load_config` / `resolve_location`), seven recorded OpenWeather JSON fixtures covering the FCST-02 edge matrix, a tmp-SQLite conftest, and a strict-xfail end-to-end `--send-now` test that defines "done" for the rest of the phase. The blocking package-legitimacy gate (Task 4, T-01-SC) was human-approved.

## What Was Built

- **Task 1 — uv scaffold (commit e9e764f):** `pyproject.toml` (`requires-python >=3.12`, `[tool.pytest.ini_options]` with `testpaths`/`pythonpath`/`addopts`), `uv.lock`, runtime deps (httpx, discord-webhook, pydantic, pydantic-settings, structlog) + dev deps (pytest, ruff), empty `weatherbot/__init__.py`, and `.gitignore` extended for `data/`, `__pycache__/`, `.venv/`. jinja2 and python-dotenv intentionally excluded.
- **Task 2 — config models + secrets + loaders (RED feb662c / GREEN 3bae722, CONF-02):** Pydantic v2 `Location`, `WebhookIdentity` (`username` default "WeatherBot ☀️"), and `Config` (locations LIST per D-06, no secret field per CONF-02); `Settings(BaseSettings)` reading `OPENWEATHER_API_KEY` + `DISCORD_WEBHOOK_URL` from `.env`; `load_config`/`load_settings`/`resolve_location` (D-07); `.env.example` + `config.example.toml`; `tests/test_config.py` asserting the secrets boundary, fail-loud `ValidationError` on missing `lat`, and D-07 resolution.
- **Task 3 — fixtures + conftest + failing e2e (commit f7d4416):** Seven recorded OpenWeather payloads (imperial/metric clear, rainy, +/− large tz-offset), `tmp_db`/`load_fixture` in `tests/conftest.py`, and `tests/test_send_now.py::test_send_now_posts_briefing` marked `xfail(strict=True)` — failing for the right reason (the `weatherbot.cli.send_now` composition does not exist until Plan 04).
- **Task 4 — package-legitimacy gate (T-01-SC), HUMAN-APPROVED:** No code written. The blocking human-verify checkpoint paused the prior executor; the human reviewed all seven packages against their canonical PyPI/repo sources and confirmed the locked versions are real published releases (httpx 0.28.1, discord-webhook 1.4.1, pydantic 2.13.4, pydantic-settings 2.14.1, structlog 26.1.0, pytest 9.0.3, ruff 0.15.16) with uv installed via Astral's official installer (0.11.19). Gate cleared — no typo-squats.

## Verification

- `uv run pytest -q` → **9 passed, 1 xfailed** (`test_send_now_posts_briefing` strict-xfail until Plan 04). Matches expected suite state.
- `uv run ruff check .` → **All checks passed.**
- Locked dependency versions confirmed in `uv.lock` and match the RESEARCH/CLAUDE.md-verified lines.

## Acceptance Criteria

- [x] `uv run pytest -x -q` runs; config tests pass; end-to-end test is declared xfail.
- [x] Secrets reachable only via `Settings`, absent from `Config` and `config.toml` (CONF-02).
- [x] `.env` and `data/` gitignored before any real key.
- [x] D-06 list-of-locations + D-07 `resolve_location` seam in place.
- [x] All seven fixtures parse and cover the FCST-02 edge matrix.
- [x] Supply-chain gate (T-01-SC) human-verified and cleared.

## Deviations from Plan

None — plan executed exactly as written. Tasks 1-3 completed in the prior session; this continuation session cleared the Task 4 blocking gate via human approval and performed closeout.

## Checkpoints / Gates

**Task 4 (checkpoint:human-verify, gate="blocking-human", T-01-SC):** Package-legitimacy audit. The prior executor paused here per the blocking-human gate (not auto-approvable — supply-chain verification). The human reviewed and explicitly APPROVED the full dependency set against canonical registry sources. Gate treated as PASSED; execution resumed and the plan closed out.

## TDD Gate Compliance

Task 2 followed RED → GREEN cleanly: `test(01-01)` failing-tests commit (feb662c) precedes the `feat(01-01)` implementation commit (3bae722). No separate refactor commit needed.

## Self-Check: PASSED

- Created files verified present on disk (config package, 7 fixtures, conftest, both test files, pyproject/uv.lock/.env.example/config.example.toml).
- Prior commits verified in git log: e9e764f, feb662c, 3bae722, f7d4416.
