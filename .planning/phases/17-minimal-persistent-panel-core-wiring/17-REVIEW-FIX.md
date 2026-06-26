---
phase: 17-minimal-persistent-panel-core-wiring
fixed_at: 2026-06-25T00:00:00Z
review_path: .planning/phases/17-minimal-persistent-panel-core-wiring/17-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 4
skipped: 1
status: partial
---

# Phase 17: Code Review Fix Report

**Fixed at:** 2026-06-25
**Source review:** .planning/phases/17-minimal-persistent-panel-core-wiring/17-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (fix_scope: all — Warnings + Info)
- Fixed: 4
- Skipped: 1 (IN-03, by design — Phase-18 traceability note, no code change)

**Test verification:** `uv run pytest tests/test_panel.py tests/test_registry.py tests/test_command_views.py` → **49 passed, 1 warning** (the pre-existing `audioop` DeprecationWarning from discord.py, unrelated to these fixes). No regressions.

## Fixed Issues

### WR-01: Empty `config.locations` crashes `PanelView.__init__` and builds an invalid Select

**Files modified:** `weatherbot/interactive/panel.py`
**Commit:** b7890fc
**Applied fix:** Added a build-time guard in `__init__` immediately after computing `locations`, before `self._selected_location = locations[0]`. An empty config now raises `ValueError("panel requires at least one configured location; config.locations is empty")` instead of a bare `IndexError` (and instead of constructing a `Select` with `options=[]` that Discord rejects only at send time). Applied the panel-local guard (the minimum fix for this phase); did NOT add `min_length=1` to `Config.locations` in `config/models.py` — that broader change is optional per the finding and touches a surface outside this phase's scope.

### WR-02: Bot-reject branch in `interaction_check` is silent — no log, no audit record

**Files modified:** `weatherbot/interactive/panel.py`
**Commit:** efab7b0
**Applied fix:** Added a `_log.info("panel reject (bot)", user_id=..., custom_id=...)` line before `return False` in the `if interaction.user.bot:` branch, mirroring the existing non-operator reject log. This closes the "a clean `return False` is invisible" gap so every reject path leaves the audit record the docstring promises.

### IN-01: `_safe_error_edit` if/else branches are redundant

**Files modified:** `weatherbot/interactive/panel.py`
**Commit:** 914fa6b
**Applied fix:** Collapsed the duplicated `is_done()`-True / `else` branches (both of which called `edit_original_response` first) into a single path that always attempts `edit_original_response` and falls back to `response.send_message` only when `not interaction.response.is_done()`, logging via `_log.exception` otherwise. Behavior preserved; the one meaningful distinction (un-acked `send_message` fallback) is now the only conditional. Verified by the existing failure-isolation tests in `test_panel.py`.

### IN-02: "byte-identical render" claim is narrower than stated

**Files modified:** `weatherbot/interactive/commands/weather_views.py`
**Commit:** 69868d8
**Applied fix:** Docstring-only change. Reworded the `weather` handler docstring from "renders byte-identically" to "renders to the identical title + Now/High·Low/Rain fields," and added a parenthetical noting the two excluded edges (independently-stamped `timestamp` and `render_embed`'s cap-clipping), so the documented invariant matches what `test_weather_spec_byte_identical` actually enforces. No behavior change.

## Skipped Issues

### IN-03: `PanelView` is not yet instantiated in the runtime (intentional, noted for traceability)

**File:** `weatherbot/interactive/panel.py` (whole module)
**Reason:** skipped by design — the finding's own Fix section states "None required for Phase 17." This is a Phase-18 traceability note (the panel ships dark this phase; Phase 18 must add the `add_view` registration + on-ready re-attach and test the persistent re-bind path). No code change is appropriate for Phase 17.
**Original issue:** A grep of `weatherbot/` finds no runtime caller of `PanelView`/`add_view` outside the module itself — by design per the module docstring (lines 40-41), which defers persistent `add_view` registration to Phase 18.

---

_Fixed: 2026-06-25_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
