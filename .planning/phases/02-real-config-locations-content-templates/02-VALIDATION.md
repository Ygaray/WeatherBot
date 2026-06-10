---
phase: 02
slug: real-config-locations-content-templates
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> See `02-RESEARCH.md` → "## Validation Architecture" for the requirement→test mapping
> and the recorded-fixture list this strategy is derived from.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (existing, from Phase 1) |
| **Config file** | `pyproject.toml` (existing `[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest -q` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~5–15 seconds (all-mocked; no live network) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

> Filled by the planner during Phase 2 planning — one row per task. Derived from
> `02-RESEARCH.md` "## Validation Architecture" (requirement → pytest command mapping).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| _pending planning_ | — | — | LOC-01/02/03, FCST-05/06, TMPL-01/02, CONF-01/03/05 | — | — | unit | `uv run pytest -q` | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> From research: new test files + fixtures are needed; the 2.5 bucket-aggregation
> tests are retired in this phase.

- [ ] `tests/test_cli.py` — `--check` and `--geocode` subcommand stubs (CONF-05, LOC-03)
- [ ] One Call 3.0 recorded fixtures: clear, rainy (`pop`), with-`alerts[]`, high-`uvi`, extreme feels-like
- [ ] Geocoding (`/geo/1.0/direct`) recorded fixture
- [ ] Retire `weatherbot/weather/aggregate.py` + `tests/test_aggregate.py` + 2.5 bucket fixtures
- [ ] `tests/conftest.py` — shared One Call 3.0 / httpx-mock fixtures (extend existing)

*Refine against the planner's task breakdown.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live One Call 3.0 reachability via `--check` | CONF-05 | Hits the real API + live subscription state; cannot assert in CI without leaking the key / depending on network | Run `weatherbot --check` against a real `.env`; confirm it reports reachable when the subscription is active |
| `--geocode "City, ST"` against live Geocoding API | LOC-03 | Live network lookup | Run `weatherbot --geocode "Austin, TX"`; confirm paste-ready lat/lon output |

*Automated tests mock httpx; the two live behaviors above are manual smoke checks.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
