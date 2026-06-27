---
phase: 19-forecast-two-tier-sub-options
plan: 02
subsystem: interactive-panel
status: complete
tags: [panel, forecast, reveal-collapse, two-tier, discord-components, layout-guard]
requirements-completed: [PANEL-07]
dependency-graph:
  requires:
    - "weatherbot/interactive/dispatch.py::dispatch_spec (flags= seam, Plan 19-01)"
    - "weatherbot/interactive/command.py::ForecastFlags (frozen dataclass, built directly)"
    - "weatherbot/interactive/registry.py::BY_NAME[weekday-forecast|weekend-forecast]"
    - "weatherbot/interactive/panel.py::PanelView (Phases 17-18 single-ack + envelope + gate)"
  provides:
    - "PanelView Forecast two-tier reveal/collapse (toggle + 2x2 sub-grid → dispatch_spec flags=)"
    - "PanelView._render_view(expanded, disabled) — single parameterized child-clone path"
    - "Completed load-bearing _assert_layout (≤5 rows / ≤5 per row / ≤25 children / id≤100 / label≤80)"
  affects:
    - "Phase 20 isolation re-proof (PANEL-11) inherits the new on_forecast / on_forecast_toggle paths"
    - "setup_hook add_view now registers 13 children (the 5 forecast custom_ids) — no code change there"
tech-stack:
  added: []
  patterns:
    - "One canonical persistent view holds ALL custom_ids; reveal/collapse is a cosmetic edit_message(view=) swap that never mutates the registered view (Pattern 1, D-05)"
    - "Single parameterized clone path (_render_view) feeding both reveal/collapse and the disabled-cue ack (kills IN-03 two-path drift, D-09)"
    - "Build-time fail-loud layout guard split into _assert_layout_children so an over-cap set is testable without add_item's own ValueError"
    - "Panel builds ForecastFlags from constants → bypasses parse_forecast_flags (no user-typed string, V5)"
key-files:
  created: []
  modified:
    - "weatherbot/interactive/panel.py"
    - "tests/test_panel.py"
decisions:
  - "D-01: on_forecast builds ForecastFlags(variant, location=_selected_location) directly (add/drop empty), routes dispatch_spec(spec, None, flags=) via registry.BY_NAME — no parallel forecast logic"
  - "D-03/D-04: reveal only on the Forecast toggle; every non-toggle action (variant tap, other command, dropdown change) renders the collapsed base + resets _expanded"
  - "D-05: all 13 children (incl. 5 forecast custom_ids) build in __init__ so add_view registers them — post-restart routing is display-independent; reveal/collapse never add_item/remove_item the registered view"
  - "D-08: _assert_layout completed (per-row + total-children asserts) via a split _assert_layout_children helper that the overflow test drives directly"
  - "D-09: forecast toggle + 4 sub-buttons are plain discord.ui.Button subclasses, so the existing isinstance(child, Button) clone branch covers them with NO new branch; _disabled_copy now delegates to _render_view"
metrics:
  duration: "~5 min"
  completed: "2026-06-26"
  tasks: 3
  files: 2
---

# Phase 19 Plan 02: Forecast Two-Tier Reveal/Collapse Sub-Grid Summary

Extended `PanelView` with the PANEL-07 Forecast two-tier disclosure: a **Forecast toggle** in row 2 (`Status · Alerts · Forecast`) reveals a **2×2 sub-grid** in rows 3–4 (`Weekday Detailed · Weekday Compact` / `Weekend Detailed · Weekend Compact`). Each variant button builds a `ForecastFlags(variant=…, location=self._selected_location)` directly and routes through the Plan-01 `dispatch_spec(..., flags=…)` seam — the panel is now the third caller of the shared forecast core, with no parallel logic. Reveal/collapse is a cosmetic `edit_message(view=…)` swap built by ONE parameterized `_render_view`; every non-toggle action collapses (D-04), a variant renders its result then collapses (D-03). The revealed panel hits **5/5 rows, 13/25 children**, so `_assert_layout` is completed and backed by a dedicated fits-and-overflow test (D-08).

## What Was Built

- **`ForecastButton(discord.ui.Button)`** — carries `(command_name, variant)` + a `PanelView` back-ref; uniform `primary` style (no per-variant colour); `callback` delegates to `on_forecast`. The four sub-grid buttons use the byte-exact `wb:fc:weekday:detailed` / `:compact` / `wb:fc:weekend:detailed` / `:compact` custom_ids and `Weekday Detailed` … `Weekend Compact` labels.
- **`ForecastToggleButton(discord.ui.Button)`** — `wb:forecast:toggle`, label `Forecast`, `secondary` style; `callback` delegates to `on_forecast_toggle`. Both classes added to `__all__`.
- **`__init__` rows 2–4 wiring** — row 2 now `Status · Alerts · Forecast` (toggle LAST per UI-SPEC); rows 3–4 hold the 2×2 grid in the locked order. All 13 children build in `__init__` so `add_view` registers every custom_id (Pattern 1 — never `add_item`/`remove_item` post-registration). Added the `_expanded` in-memory reveal flag (default `False`).
- **`_render_view(*, expanded, disabled=False)`** — the single parameterized clone path: builds a fresh `timeout=None` view, skips rows 3–4 clones when `not expanded` (collapsed base), and disables every clone when `disabled` (the cue ack). `_disabled_copy` now delegates to `_render_view(expanded=True, disabled=True)` — one child-cloning path (kills the IN-03 two-path drift, D-09). The new buttons are plain `Button` subclasses so the existing `isinstance(child, Button)` branch rebuilds them with no new branch.
- **`_assert_layout` completed (D-08)** — split into `_assert_layout(self)` → `_assert_layout_children(children, locations)`. Added a per-row `Counter` assert (`≤ _MAX_PER_ROW = 5`) and a total-children assert (`≤ _MAX_CHILDREN = 25`) alongside the existing rows / options / custom_id / label asserts. The split helper lets the overflow test drive a hand-built over-cap child set without `add_item` raising first.
- **`on_forecast(interaction, *, command_name, variant)`** — mirrors `on_command`'s single-ack contract + per-callback envelope; builds `ForecastFlags(variant=variant, location=self._selected_location)` (add/drop at `frozenset()` defaults, D-01), single `response.edit_message` ack with the disabled-expanded view, `dispatch_spec(spec, None, …, flags=flags)`, and both the result AND the `UnknownLocationError` catch render the COLLAPSED base via `edit_original_response` (D-03). Envelope log custom_id `wb:fc:{command_name}:{variant}`.
- **`on_forecast_toggle(interaction)`** — flips `self._expanded` and renders the matching view via exactly one `response.edit_message` (Pattern 2), wrapped in the same non-propagating envelope.
- **`on_select` + `on_command` collapse-on-action** — their terminal renders now attach `self._render_view(expanded=False)` (instead of `view=self`) and reset `self._expanded = False`, so a dropdown change or any non-forecast command tap collapses (D-04).
- **Import-time registry allow-list** — extended with `weekday-forecast` / `weekend-forecast` so a registry rename trips at import. `ForecastFlags` imported at module top (acyclic — `dispatch.py` already imports from `command` at module top).
- **`tests/test_panel.py`** — 7 new nodes: `test_forecast_toggle_reveal`, `test_on_forecast_dispatch`, `test_collapse_on_action`, `test_forecast_custom_ids_registered`, `test_forecast_matches_registry`, `test_layout_full_panel_fits`, `test_layout_overflow_trips_assert`. They reuse the existing `_FakeHolder` / `_SpyCache` / `_make_panel` / `_stub_handler` + `fake_interaction` harness — no new conftest fixtures.

## How It Works

The panel never duplicates forecast fetch/render. A variant tap builds the `ForecastFlags` from two constants (the button's `variant` literal + the in-memory `_selected_location`) and hands it to `dispatch_spec(registry.BY_NAME[command_name], None, …, flags=flags)`. Because Plan 01 made `dispatch_spec` skip `parse_forecast_flags` when `flags is not None`, the panel and the `!weekday-forecast` text command converge on the identical lookup/suffix/handler — proven by `test_forecast_matches_registry` (the spied shared reply is what `render_embed` puts in the panel embed). Reveal/collapse is purely cosmetic: `_render_view(expanded=…)` produces a fresh clone view for `edit_message`; the registered persistent view always holds all 13 children, so a sub-button tapped after a restart still routes regardless of what the message currently displays (D-05).

## Deviations from Plan

None — plan executed exactly as written. TDD order honored: the 7 RED nodes (commit `5917811`) failed on missing callbacks/buttons/`_assert_layout_children` before the implementation, then went GREEN across Task 2 (`79b18ef`) and Task 3 (`50870e7`).

One implementation discretion within the plan's latitude: the overflow test (and the build-time guard) are factored through a new `_assert_layout_children(children, locations)` helper so the test can validate a hand-built over-cap child set directly — `_assert_layout(self)` is now a thin delegate. This is the natural way to satisfy the D-08 "an over-cap layout trips the assert" obligation without `discord.ui.View.add_item` raising its own `ValueError` first.

## Verification

- `uv run pytest tests/test_panel.py -q` → **25 passed** (the 7 new forecast nodes + every inherited Phase-17/18 node).
- `uv run pytest -q` → **634 passed** (full suite — the contractual anti-drift / byte-identical suite + the Plan-01 dispatch seam tests stay green alongside the panel extension).
- `uv run python -c "import weatherbot.interactive.panel"` → exit 0 (acyclic — `ForecastFlags` at module top introduces no cycle).
- `uv run ruff check weatherbot/interactive/panel.py` → All checks passed.
- `git diff HEAD~3 -- weatherbot/interactive/panel.py` → `interaction_check` body, the byte-exact reject copy, and `_safe_error_edit` logic unchanged (inherited gate + envelope not regressed; `on_error`/`_safe_error_edit` appear in the diff only because the two new callbacks were inserted before them).
- Forecast custom_ids present in `panel.py`: `wb:forecast:toggle`, `wb:fc:weekday:detailed`, `wb:fc:weekday:compact`, `wb:fc:weekend:detailed`, `wb:fc:weekend:compact`.

## Threat Mitigations Applied

- **T-19-02-01 (EoP — non-operator drives the toggle/sub-buttons):** mitigated — inherited `interaction_check` runs before every child callback (the new children are children of the same gated `PanelView`); no new gate code, no new bypass.
- **T-19-02-02 (Info disclosure — reject/error copy):** mitigated — the new paths reuse the inherited identity-free reject and `_safe_error_edit`; `on_forecast` echoes no user/command/secret; the envelope log (`wb:fc:…`) is server-side structlog only.
- **T-19-02-03 (Input validation — bypassed parser):** mitigated — `variant` is one of two compile-time literals; `location` is the already-validated in-memory `_selected_location`; `ForecastFlags` is built from constants, so no user-typed string reaches the bypassed `parse_forecast_flags` (V5).
- **T-19-02-04 (DoS — raising/hanging callback affecting the briefing):** mitigated — `on_forecast` / `on_forecast_toggle` inherit the per-callback non-propagating `try/except` + `View.on_error` backstop; all blocking work stays off-loop inside `dispatch_spec`'s `run_in_executor`. (Full re-proof is Phase 20 / PANEL-11.)
- **T-19-02-05 (DoS — double-tap during cold fetch):** mitigated — the single `response.edit_message` ack renders `_render_view(expanded=True, disabled=True)`, disabling all children before the off-loop fetch; exactly one `response.*` per tap.
- **T-19-02-06 (Tampering — mutating the registered view drops custom_ids):** mitigated — `__init__` builds all 13 children once; reveal/collapse builds a FRESH `_render_view` and never `add_item`/`remove_item`s the registered view, so every forecast custom_id stays in the dispatch table (verified by `test_forecast_custom_ids_registered`).
- **T-19-02-SC (package install):** accepted — no package install, no dependency, no discord.py bump, no new intent.

No new unmitigated threat surface — the change is a UI-layer extension over the already-shipped read-only forecast seam (no new endpoint/auth/file/schema).

## Known Stubs

None.

## Deferred Issues

- Pre-existing ruff `F841 unused variable view` in `tests/test_panel.py:194` (`test_dropdown_rederives_on_hot_reload`, a Phase-17 node — identical before this plan). Out of scope for PANEL-07; logged to `deferred-items.md`. The test passes; trivial fix is to assign to `_` or drop the line.

## What This Unblocks

PANEL-07 is complete: the operator can tap Forecast to reveal the 2×2 grid and get any Weekday/Weekend × Detailed/Compact variant for the selected location; re-tap or any other action collapses. Phase 20 inherits the new `on_forecast` / `on_forecast_toggle` paths for the whole-panel briefing-isolation re-proof (PANEL-11), and owns the deferred polish (selected-location indicator, emoji labels, "updated <time>" stamp).

## Deferred to Gate-2 Host UAT (non-blocking for this phase)

Per the global Verification Policy, live `yahir-mint` UAT is a deferred milestone-close obligation (new Python modules don't hot-reload — needs deploy + `sudo systemctl restart weatherbot`): summon `!panel` → tap Forecast (reveal) → tap a variant (correct in-place forecast + collapse) → `systemctl restart weatherbot` → tap a forecast variant on the still-revealed display to prove post-restart routing (D-05). See `19-VALIDATION.md` Manual-Only Verifications.

## Commits

- `5917811` test(19-02): add RED scaffold for forecast reveal/collapse + dispatch + layout
- `79b18ef` feat(19-02): forecast buttons + rows 2-4 wiring + merged _render_view + full _assert_layout
- `50870e7` feat(19-02): on_forecast + on_forecast_toggle callbacks + collapse-on-action (PANEL-07)

## Self-Check: PASSED

- FOUND: weatherbot/interactive/panel.py (modified — ForecastButton, ForecastToggleButton, on_forecast, on_forecast_toggle, _render_view, _assert_layout_children)
- FOUND: tests/test_panel.py (modified — 7 new forecast nodes)
- FOUND commit: 5917811
- FOUND commit: 79b18ef
- FOUND commit: 50870e7
