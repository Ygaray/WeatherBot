---
phase: quick-260626-u8y
plan: 01
subsystem: interactive-panel
status: complete
tags: [panel, discord, ux, forecast, gate-2]
requires:
  - panel-dead-after-first-tap clone-routing fix (commit b48abc6)
provides:
  - always-visible 2×2 forecast grid (no toggle, no _expanded state)
affects:
  - weatherbot/interactive/panel.py
  - tests/test_panel.py
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
tech-stack:
  added: []
  patterns:
    - "_render_view rebuilds every child via _clone_child (live callback-bearing subclasses)"
key-files:
  created: []
  modified:
    - weatherbot/interactive/panel.py
    - tests/test_panel.py
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
decisions:
  - "Forecast 2×2 grid made always-visible per product-owner Gate-2 UX request; toggle/reveal dropped"
  - "b48abc6 live-callback clone routing preserved verbatim — _render_view never reverts to plain Button/Select"
metrics:
  duration: ~12m
  completed: 2026-06-26
  tasks: 3
  files: 4
requirements: [PANEL-07]
---

# Quick Task 260626-u8y: Always-Visible 2×2 Forecast Grid Summary

Replaced the v1.3 panel's two-tier Forecast toggle (reveal/collapse a hidden 2×2 sub-grid)
with an always-visible 2×2 forecast grid — the four variant buttons (Weekday/Weekend ×
Detailed/Compact) are now permanently shown on a fixed 12-child / 5-row panel — while
preserving the just-shipped clone-routing fix (b48abc6) so taps never go dead after the first.

## What Changed

**Task 1 — `weatherbot/interactive/panel.py` (commit 394162b):**
- Deleted the `ForecastToggleButton` class (and removed it from `__all__`), the
  `on_forecast_toggle` method, the `_expanded` instance state and every read/write of it,
  and the `ForecastToggleButton` branch in `_clone_child`.
- Simplified `_render_view` to `def _render_view(self, *, disabled: bool = False)` —
  dropped the `expanded` knob and the `if not expanded and row in (3,4): continue` skip,
  so every render now carries all rows 0–4. **The `_clone_child` live-callback rebuild
  (CmdButton/LocationSelect/ForecastButton bound to `self`) is preserved verbatim** — the
  hard invariant from b48abc6 is intact; the clone never reverts to plain
  `discord.ui.Button`/`Select`.
- `__init__` row 2 now holds only the two argless CmdButtons (Status · Alerts).
- Updated `_assert_layout` / `_MAX_*` prose from 13-child to 12-child; all five layout
  assertions kept. Updated module prose (`_FORECAST_CMDS`, `_EMOJI`, `ForecastButton`
  docstring) to drop reveal/toggle language.
- `dispatch_spec` seam, registry, and `ForecastFlags(variant, location=_selected_location)`
  flow in `on_forecast` are unchanged.

**Task 2 — `tests/test_panel.py` (commit b977d66):**
- Removed obsolete `test_forecast_toggle_reveal` and `test_collapse_on_action`.
- Rewrote `test_transient_ack_and_error_views_honor_collapsed_state` →
  `test_transient_ack_disables_full_panel`: asserts the command-tap ack view carries the
  full 12-child / 5-row panel with every child disabled (double-tap guard).
- Renamed `test_forecast_and_toggle_buttons_carry_locked_emoji` →
  `test_forecast_buttons_carry_locked_emoji`; dropped `_FC_TOGGLE_ID` and the
  `wb:forecast:toggle` entry from `_EXPECTED_FC_EMOJI`.
- Updated layout/emoji/dropdown-clone tests to 12 children and the `expanded`-free
  `_render_view()` signature.
- **Kept the two b48abc6 clone-routing regressions** (`..._command_button_...`,
  `..._dropdown_...`) green and **added `test_rendered_clone_forecast_button_routes_to_handler`**
  proving a cloned forecast button routes live to `on_forecast` through the message-bound clone.
- Fixed the now-stale "rebuilds PLAIN discord.ui.Button/Select" docstrings in the two
  clone-survival tests (per plan-checker EXTRA note) to describe the real-subclass clone.

**Task 3 — planning docs (commit 21fe30d):**
- Reworded PANEL-07 in `.planning/REQUIREMENTS.md` to the always-visible 2×2 grid framing
  (still `[x]` SATISFIED, still mapped to Phase 19), with a one-line supersession note.
- Annotated Phase 19 in `.planning/ROADMAP.md` (summary line + Goal block) as superseded by
  the always-visible grid at Gate-2 — history preserved, mapping/criteria left intact.

## Hard Invariant Re-Proof (self-UAT)

| Criterion | Evidence | Verdict |
|-----------|----------|---------|
| Cloned command button routes live on 2nd tap | `test_rendered_clone_command_button_routes_to_handler` green | PASS |
| Cloned dropdown routes live on 2nd tap | `test_rendered_clone_dropdown_routes_to_handler` green | PASS |
| Cloned forecast button routes live on 2nd tap | `test_rendered_clone_forecast_button_routes_to_handler` (new) green | PASS |
| `_render_view` still clones via `_clone_child` (no plain Button/Select) | import/introspection smoke check + grep clean | PASS |
| Forecast still dispatches `ForecastFlags` via `dispatch_spec(..., flags=)` | `test_on_forecast_dispatch` green | PASS |
| `_assert_layout` guards the 12-child / 5-row panel | `test_layout_full_panel_fits` (==12) green | PASS |

## Final Gates

| Gate | Command | Result |
|------|---------|--------|
| Full suite | `uv run pytest -q` | **651 passed** (baseline 652 − 2 obsolete + 1 new) |
| Lint | `uv run ruff check weatherbot tests` | clean |
| Format | `uv run ruff format --check weatherbot tests` | clean (79 files) |

## Deviations from Plan

None — plan executed exactly as written. (ruff auto-reformatted `tests/test_panel.py` after
the edits; the reformat was applied and re-verified green, not a logic deviation.)

## Gate-2 Deferred Obligation

Live verification on host `yahir-mint` — `!panel`, confirm the four forecast variant buttons
are visible without an expand step and tap each twice+ to confirm the clone stays live —
remains a human-UAT item per the Two-Gate policy. The in-process clone-routing repro is
covered by automated regression (the three `test_rendered_clone_*` nodes).

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file access, or schema changes; this is a
UI-layout simplification within the existing component surface.

## Self-Check: PASSED

- SUMMARY.md present on disk.
- All three task commits present in git history (394162b, b977d66, 21fe30d).
- panel.py has zero `ForecastToggleButton` / `_expanded` / `expanded=` references.
