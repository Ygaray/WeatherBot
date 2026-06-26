# Phase 19: Forecast Two-Tier Sub-Options - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-26
**Phase:** 19-forecast-two-tier-sub-options
**Areas discussed:** Variant→dispatch path, Reveal model, Sub-button layout & labels, Layout assertion scope

---

## Variant → dispatch path

| Option | Description | Selected |
|--------|-------------|----------|
| B — pre-built flags param | Add optional `flags: ForecastFlags \| None = None` to `dispatch_spec`; panel builds `ForecastFlags(variant=…, location=selected)` directly, skipping the reparse | ✓ |
| A — synth arg string + reparse | Panel builds `"Home --compact"` string; `dispatch_spec` parses as today — zero seam change but fragile on odd location names | |

**User's choice:** B — pre-built flags param
**Notes:** Matches the ROADMAP's "building a `ForecastFlags(...)` directly" wording; immune to location names with flag-like tokens. Captured as D-01 + the byte-identical `flags=None` constraint D-02.

---

## Reveal model (+ collapse behavior)

| Option | Description | Selected |
|--------|-------------|----------|
| Toggle, collapse after result | Forecast button reveals the sub-grid; tapping a variant renders the result and collapses back to base | ✓ |
| Toggle, stay expanded | Reveal persists for repeated taps; collapse only on re-tap or dropdown change | |
| Always-shown (no toggle) | 4 forecast buttons permanently shown; no Forecast button | |

**User's choice:** Toggle, collapse after result
**Notes:** Refined to D-04 — collapse on ANY action except the Forecast toggle itself (variant tap, other command, dropdown change all render the collapsed base). Restart resolves to collapsed default (D-05).

---

## Sub-button layout & labels

| Option | Description | Selected |
|--------|-------------|----------|
| 1 row, detailed implicit | Single row of 4; bare `Weekday`/`Weekend` = detailed, `Compact` suffix marks compact | |
| 1 row, explicit | Single row of 4; every button spells out Detailed/Compact | |
| 2×2 grid | Weekday pair on row 3, weekend pair on row 4; explicit Detailed/Compact | ✓ |

**User's choice:** 2×2 grid (explicit labels) — selected after reviewing rendered ASCII mockups of all three.
**Notes:** Weekday-row / weekend-row grouping read as most scannable; explicit labels preferred over bare for clarity. Revealed state = 5/5 rows (full height) — makes the build-time assertion load-bearing. Forecast toggle sits in row 2 (D-07).

---

## Layout assertion scope

| Option | Description | Selected |
|--------|-------------|----------|
| __init__ assert + unit test | Extend `_assert_layout` (≤5 rows, ≤5/row, ≤25 children) + dedicated CI test | ✓ |
| __init__ assert only | Construction-time assert, no separate test | |
| Test only | Unit test, rely on discord.py runtime errors at construction | |

**User's choice:** __init__ assert + unit test
**Notes:** Matches criterion 3's "asserted at build time so a future addition can't silently overflow" (assert) plus regression-averse preference for CI coverage (test). `_disabled_copy`/IN-03 is already satisfied if forecast buttons are `Button` subclasses (D-09) — planner to verify.

---

## Claude's Discretion

- Exact `custom_id` scheme for forecast buttons + toggle (e.g. `wb:fc:weekday:detailed`, `wb:forecast:toggle`).
- New parameterized button class vs reusing `CmdButton`; the `on_forecast` method; the reveal/collapse view-builder helper.
- Whether to show a functional caret/text expand-collapse state on the Forecast label (not Phase-20 emoji).
- Module placement of any new helpers (keep `interactive/` import-acyclic).

## Deferred Ideas

- Selected-location visual indicator, emoji-coded labels, "updated <time>" stamp — Phase 20.
- Briefing failure-isolation re-proof for the interaction path (PANEL-11) — Phase 20.
- Grey-out buttons until a location is selected (PANEL-V2-01) — future release.
- Arbitrary/geocoded `weather <any city>` via panel modal (CMD-V2-02) — v2.0.
- **Research flag:** persistent-view + reveal/collapse mechanics (single registered view carrying all forecast custom_ids) — for the research/plan phase to confirm against discord.py 2.7.1.
