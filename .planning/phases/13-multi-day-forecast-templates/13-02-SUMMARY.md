---
phase: 13-multi-day-forecast-templates
plan: 02
subsystem: templates
tags: [forecast, renderer, templates, token-vocabulary, fail-loud, no-logic-in-templates]
requirements-completed: [FCAST-01, FCAST-02, FCAST-03, FCAST-06]
dependency-graph:
  requires:
    - "ForecastDay.day_tokens(detailed) token contract (Plan 13-01) — 4 compact / 11 detailed keys"
  provides:
    - "FORECAST_TOKENS / FORECAST_DAY_TOKENS_DETAILED / _COMPACT scopes (templates/renderer.py)"
    - "render_forecast(template_text, line_fmt, days, header_values, day_allowed) helper"
    - "8 editable forecast template files (weekday/weekend x detailed/compact + sibling .line.txt)"
  affects:
    - "Plan 13-04 on-demand forecast handler (calls render_forecast)"
    - "Plan 13-05 scheduled forecast (fire_forecast_slot renders via render_forecast)"
tech-stack:
  added: []
  patterns:
    - "Code-rendered per-day block — loop lives in render_forecast, never in a template (T-13-04)"
    - "Parameterized validate_template(allowed=...) reused for forecast scopes (no second engine)"
    - "Distinct forecast token scopes (NOT an extension of CANONICAL)"
    - "Sibling .line.txt per template carries the per-day line-format (A3; reuses load_template)"
key-files:
  created:
    - templates/forecast-weekday-detailed.txt
    - templates/forecast-weekday-detailed.line.txt
    - templates/forecast-weekday-compact.txt
    - templates/forecast-weekday-compact.line.txt
    - templates/forecast-weekend-detailed.txt
    - templates/forecast-weekend-detailed.line.txt
    - templates/forecast-weekend-compact.txt
    - templates/forecast-weekend-compact.line.txt
    - tests/test_forecast_render.py
  modified:
    - templates/renderer.py
decisions:
  - "render_forecast validates line_fmt (day_allowed) AND template_text (FORECAST_TOKENS) BEFORE any render — typo fails loud at load, never ships a literal (T-13-05)"
  - "Detailed .txt mirrors briefing-sectioned house style (emoji header + footer); compact .txt mirrors briefing-compact terse single-header style"
  - "Compact .line.txt deliberately drops rain/wind/uvi/feels/sun (only label/high/low/sky) per D-02 + RESEARCH Open Question 3"
  - "{notice} placed on its own line in every template so an empty notice renders as a blank line (out-of-horizon flag notes injected by Plan 04/05)"
metrics:
  duration: ~12 min
  tasks: 2
  files: 10
  tests-added: 14
  completed: 2026-06-19
---

# Phase 13 Plan 02: Forecast Token Vocabulary + Templates Summary

Extended the guarded renderer with a forecast-specific token vocabulary (distinct from the daily-briefing `CANONICAL` set) and a `render_forecast` helper that code-iterates the per-day block — keeping the project's "no logic in templates" invariant — then authored the four editable weekday/weekend × detailed/compact templates plus their sibling per-day line-format files. This establishes the exact rendering contract Plan 04 (on-demand) and Plan 05 (scheduled) both call.

## What Was Built

### Task 1 — Forecast token scopes + `render_forecast` (renderer.py)
- Three frozen scopes added DISTINCT from `CANONICAL`: `FORECAST_TOKENS = {location, title, range_label, days, footer_note, notice}`, `FORECAST_DAY_TOKENS_DETAILED` (11 keys), `FORECAST_DAY_TOKENS_COMPACT = {label, high, low, sky}`. These match `ForecastDay.day_tokens(detailed)` (Plan 13-01) exactly.
- `render_forecast(template_text, line_fmt, days, header_values, day_allowed)`: validates `line_fmt` against `day_allowed`, builds `block = "\n".join(render(line_fmt, d) for d in days)` (the ONLY per-day loop, in code), validates `template_text` against `FORECAST_TOKENS`, then `render(template_text, {**header_values, "days": block})`. Reuses the existing guarded `render`/`validate_template` — no second substitution engine, no `str.format`/`Formatter`/`eval`.

### Task 2 — Four templates + sibling line-format files
- `forecast-{weekday,weekend}-detailed.txt`: emoji header (`📅 {title} — {location}` / `{range_label}`), `{days}` block slot, `{notice}` line, `{footer_note}` — mirrors `briefing-sectioned.txt`.
- `forecast-{weekday,weekend}-compact.txt`: terse single header `{title} — {location} ({range_label})` + `{days}` + `{notice}` + `{footer_note}` — mirrors `briefing-compact.txt`.
- Each `.txt` has a sibling `.line.txt`: detailed line uses all 11 detailed tokens; compact line uses only `{label}: {high}/{low} {sky}`. Each line-format is a single line. No loop/conditional/`str.format` in any file — only `{token}` placeholders.

## Verification

- `uv run pytest tests/test_forecast_render.py -q` → 14 passed.
- `uv run pytest -q` full suite → **388 passed** (was 374; +14), no regressions. (One pre-existing third-party `audioop` DeprecationWarning from `discord` — out of scope.)
- `uv run ruff check templates/renderer.py tests/test_forecast_render.py` → clean.

### Acceptance criteria
- `grep "FORECAST_TOKENS\|FORECAST_DAY_TOKENS_DETAILED\|FORECAST_DAY_TOKENS_COMPACT" renderer.py` → 6 matches; `def render_forecast` present.
- No NEW `str.format`/`Formatter`/`eval` in renderer (test asserts it after stripping comments + docstring).
- All 8 template files exist; each whole-message `.txt` references `{days}` (`grep -rL "{days}"` over the 4 → empty).
- Detailed line validates against `FORECAST_DAY_TOKENS_DETAILED`; compact against `_COMPACT`; compact references NONE of the detailed-only tokens.
- Typo'd header token and typo'd line token each raise at validate time; `render_forecast` joins N day-dicts into N lines in the `{days}` slot.

## Deviations from Plan

None — plan executed as written.

## TDD Gate Compliance

Task 1 followed RED → GREEN:
- RED: `test(13-02)` (bf35a70) — import error / missing symbols, fails as expected.
- GREEN: `feat(13-02)` (93391d5) — token scopes + `render_forecast`, Task-1 subset green.

Task 2 (`type="auto"`, not TDD-gated): `feat(13-02)` (7e10710) authored the 8 templates and enabled the pre-written Task-2 validation tests (all 14 forecast tests green). No REFACTOR commits needed.

## Threat Surface

No new threat surface beyond the plan's `<threat_model>`. T-13-04 (template injection) and T-13-05 (typo'd token shipping a literal) are both mitigated as planned: `render_forecast` routes BOTH the header and every per-day line through the existing guarded `render`/`validate_template`, and validates both scopes fail-loud before any render. No secret token exists in any forecast scope (T-13-06 accept).

## Known Stubs

None. The renderer helper and all 8 templates are fully wired and tested. Consumers (the forecast handler in Plan 04 and `fire_forecast_slot` in Plan 05) will call `render_forecast` with live `ForecastDay.day_tokens(...)` dicts.

## Self-Check: PASSED

- FOUND: templates/renderer.py (FORECAST_TOKENS, render_forecast)
- FOUND: templates/forecast-weekday-detailed.txt + .line.txt
- FOUND: templates/forecast-weekday-compact.txt + .line.txt
- FOUND: templates/forecast-weekend-detailed.txt + .line.txt
- FOUND: templates/forecast-weekend-compact.txt + .line.txt
- FOUND: tests/test_forecast_render.py
- FOUND commits: bf35a70, 93391d5, 7e10710
