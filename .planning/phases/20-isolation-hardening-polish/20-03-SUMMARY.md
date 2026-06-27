---
phase: 20-isolation-hardening-polish
plan: 03
subsystem: interactive
tags: [discord, panel, emoji, dropdown, indicator, clone-survival, polish]
status: complete
dependency-graph:
  requires:
    - "weatherbot/interactive/bot.py render_embed(reply, *, location=None) — the 20-02 📍 + Updated stamp builder"
    - "weatherbot/interactive/panel.py PanelView assembled across Phases 17–19 (_LABELS, CmdButton, ForecastButton, ForecastToggleButton, LocationSelect, _render_view)"
  provides:
    - "Emoji-coded panel buttons (locked D-05 set) surviving the _render_view clone"
    - "Dropdown SelectOption(default=True) re-marked from _selected_location, surviving the clone"
    - "Panel result renders threading the selected location into render_embed (📍 on every location-bearing path)"
  affects:
    - "Phase 20 close — PANEL-12 + PANEL-13 satisfied; ROADMAP SC#2/SC#3 proven"
tech-stack:
  added: []
  patterns:
    - "Parallel _EMOJI dict keyed like _LABELS; emoji applied via the SEPARATE discord.py emoji= param (never concatenated into the label)"
    - "Clone-path re-derivation: PLAIN discord.ui.Button/Select clones carry emoji=child.emoji and rebuild SelectOption(default=) from in-memory state (NOT a blind options copy)"
    - "Default-None location kwarg threaded into the shared render_embed so the 📍 line auto-suppresses on argless replies"
key-files:
  created:
    - ".planning/phases/20-isolation-hardening-polish/20-SELF-UAT.md (Gate-1 self-UAT log)"
  modified:
    - "weatherbot/interactive/panel.py (_EMOJI dict; emoji= on all buttons; dropdown default; _render_view clone fix; location= on both result renders)"
    - "tests/test_panel.py (8 new Phase-20 tests + default= augmentation on test_dropdown_from_config)"
decisions:
  - "Parallel _EMOJI dict (recommended over inline) mirrors _LABELS for the seven command buttons; forecast/toggle glyphs applied at their own construction sites (D-04/D-05)"
  - "THE TRAP fixed: _render_view Button clones carry emoji=child.emoji; Select clone rebuilds options with default=(o.value == _selected_location) — emoji + highlight survive every ack/collapse render (Pitfall 1)"
  - "Dropdown default derived ONLY from _selected_location, never Select.values (Pitfall 3 / discord.py #7284)"
  - "on_command threads location=arg (None for argless → 📍 auto-suppresses); on_forecast threads location=_selected_location (always location-bearing)"
  - "Tests exercise the CLONE path (_render_view), not just __init__, to actually prove the fix"
metrics:
  duration: "7m"
  completed: "2026-06-27"
status_note: complete
---

# Phase 20 Plan 03: Panel polish — emoji, dropdown default, 📍 indicator + the clone-survival fix Summary

Emoji-coded every panel button with the locked D-05 glyph set (text labels kept), re-marked the location dropdown's `SelectOption(default=True)` from `_selected_location`, threaded the selected location into both panel result renders so the 20-02 `📍` indicator shows on every location-bearing path — and closed THE load-bearing trap: the `_render_view` clone now carries `emoji=child.emoji` and re-derives the dropdown `default` from in-memory state, so emoji AND the highlight survive every disabled-ack and collapse render (not just the freshly-built `__init__` view).

## What Was Built

- **`_EMOJI` dict** (`panel.py`) mirroring `_LABELS`, keyed by command name, with the locked D-05 glyphs (`weather 🌡️ · uv 🧴 · next-cloudy ☁️ · sun ☀️ · wind 💨 · status 🟢 · alerts ⚠️`).
- **`CmdButton.__init__`** passes `emoji=_EMOJI[name]` as a SEPARATE param alongside `label=_LABELS[name]` (D-04 — never concatenated).
- **`ForecastButton.__init__`** gained an `emoji: str` kwarg (mirroring its `label=`); the four construction sites pass `📋 / 📝 / 🏖️ / 🌴`. **`ForecastToggleButton`** carries `emoji="📅"`.
- **`LocationSelect.__init__`** rebuilds options as `SelectOption(label=n, value=n, default=(n == panel._selected_location))` — the highlight derived from the in-memory selection (`_selected_location` is set at `panel.py:319` before `add_item` at :327), never from `Select.values` (Pitfall 3).
- **`_render_view` clone fix (THE TRAP, Pitfall 1):** the PLAIN `discord.ui.Button` clones now carry `emoji=child.emoji`; the PLAIN `discord.ui.Select` clone rebuilds its options with `default=(o.value == self._selected_location)` instead of `list(child.options)`. Emoji + highlight now survive the disabled-ack and collapse renders (the most common paths).
- **Result-render location threading (PANEL-12):** `on_command` → `render_embed(reply, location=arg)` (`arg` is `_selected_location` for location-taking commands, `None` for argless so the `📍` auto-suppresses on status/alerts); `on_forecast` → `render_embed(reply, location=self._selected_location)` (always location-bearing).
- **`_assert_layout` UNTOUCHED** — emoji/indicator/stamp are all non-component; the grid stays 5/5 / 13 children.

## Tests Added (tests/test_panel.py — 8 new + 1 augmentation)

- `test_command_buttons_carry_locked_emoji` — every CmdButton carries its D-05 glyph via `emoji=`, label kept, glyph not in label.
- `test_forecast_and_toggle_buttons_carry_locked_emoji` — toggle `📅` + four sub-buttons `📋/📝/🏖️/🌴`.
- `test_emoji_survives_render_view_clone` — all 12 glyphs survive the `expanded=True` clone AND the disabled-ack collapse clone (clone children disabled).
- `test_dropdown_default_marks_selected_location` — `home` (default `locations[0]`) `default is True`, others `False`.
- `test_dropdown_default_mark_survives_render_view_clone` — after selecting `travel`, the clone's `travel` option `default is True`, `home` re-marks off.
- `test_location_bearing_result_carries_indicator` — `on_command("weather")` result `.description` contains `📍 home`.
- `test_argless_result_suppresses_indicator` — `on_command("status")` result `.description` has no `📍`.
- `test_forecast_result_carries_indicator` — `on_forecast(weekday/detailed)` result `.description` contains `📍 home`.
- Augmented `test_dropdown_from_config` with a `default=` assertion (value list intact).

## Verification

- `uv run pytest tests/test_panel.py -k "emoji or default_mark or default_marks or layout" -x` → 8 passed.
- `uv run pytest tests/test_panel.py -q` → **34 passed** (anti-drift field/title parity tests stayed green — additions are description/`default`-level).
- `uv run pytest -q` → **649 passed** (641 at 20-02 + 8 new; zero anti-drift breaks).
- `uv run ruff check weatherbot/interactive/panel.py` → all checks passed.
- `grep -n "render_embed(reply, location=" weatherbot/interactive/panel.py` → both call sites present (lines 572, 642).
- `_assert_layout` `-k layout` → 3 passed (grid untouched).
- Gate-1 self-UAT log written with byte-level evidence (`.planning/phases/20-isolation-hardening-polish/20-SELF-UAT.md`).

## TDD Gate Compliance

Both implementation tasks followed RED → GREEN:
- Task 1: RED `test(20-03)` `879d928` (emoji/dropdown-default clone-survival fail) → GREEN `feat(20-03)` `66db9a4` (emoji + dropdown + clone fix).
- Task 2: RED `test(20-03)` `efb6e92` (render-path indicator fail) → GREEN `feat(20-03)` `1ffbcbc` (location threaded into both result renders).
- REFACTOR: none needed (edits were minimal and clean).

## Requirements Satisfied

- **PANEL-12** (visible selected-location indicator — embed line + dropdown highlight): the `📍 {selected}` line renders on every location-bearing panel result; the dropdown `default=True` highlight is re-marked from `_selected_location` and survives the clone.
- **PANEL-13** (emoji-coded labels + Updated stamp): all 12 controls carry their locked D-05 emoji (text label kept), surviving the clone; the `Updated <t:>` stamp ships in `render_embed` (20-02) and now shows on the location-threaded panel results.

## Deviations from Plan

None — plan executed exactly as written. The recommended parallel `_EMOJI` dict was chosen (D-04/D-05 executor discretion). No package installs, no new component slot, no architectural change.

## Threat Surface

- **T-20-06 (Tampering — clone dropping emoji/default):** mitigated — Task 1 fixes the clone to carry `emoji=child.emoji` + re-derive `default`; clone-survival asserted from the `_render_view` clone (not just `__init__`).
- **T-20-07 (DoS — extra component slot tripping `_assert_layout`):** mitigated — zero new slots; `-k layout` green.
- **T-20-08 (Info Disclosure — error path altered):** accept/confirmed — the `UnknownLocationError`/error branches (`embed=None`) are untouched; `📍`/`Updated` render only on the result embed path.
- No new untrusted input, network, auth, or dependency surface. No threat flags raised.

## Deferred (Gate-2 on-device, milestone-close — NOT a phase blocker)

A1 emoji pixel rendering, A2 `<t:R>` self-ageing visual, A3 live `📍`/dropdown highlight on the pinned panel — all PARTIAL (mechanism + data proven; on-device visual outstanding). Requires deploy + `sudo systemctl restart weatherbot` on host `yahir-mint`. Recorded in `20-SELF-UAT.md`.

## Self-Check: PASSED

- FOUND: weatherbot/interactive/panel.py (_EMOJI + emoji= + dropdown default + clone fix + location= on both renders)
- FOUND: tests/test_panel.py (8 new Phase-20 tests + default= augmentation)
- FOUND: .planning/phases/20-isolation-hardening-polish/20-SELF-UAT.md
- FOUND commit 879d928 (Task 1 RED)
- FOUND commit 66db9a4 (Task 1 GREEN)
- FOUND commit efb6e92 (Task 2 RED)
- FOUND commit 1ffbcbc (Task 2 GREEN)
- FOUND commit f575030 (Task 3 self-UAT)
