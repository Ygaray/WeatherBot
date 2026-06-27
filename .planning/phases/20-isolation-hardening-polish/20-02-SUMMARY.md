---
phase: 20-isolation-hardening-polish
plan: 02
subsystem: interactive
tags: [discord, embed, render, panel, polish]
status: complete
dependency-graph:
  requires:
    - "weatherbot/interactive/bot.py render_embed (the single surface-agnostic embed builder)"
  provides:
    - "render_embed(reply, *, location=None) — 📍 indicator line + Updated <t:> stamp in the embed description"
  affects:
    - "Plan 20-03 (wires panel.py:536/604 call sites to pass location=)"
tech-stack:
  added: []
  patterns:
    - "Default-None keyword-only kwarg keeps existing positional callers source-compatible"
    - "Discord <t:{unix}:t>/<t:{unix}:R> dynamic timestamp markdown in embed description (never title)"
key-files:
  created: []
  modified:
    - "weatherbot/interactive/bot.py (render_embed signature + description lines)"
    - "tests/test_bot.py (4 new render_embed description tests)"
decisions:
  - "📍 line + Updated stamp added in the single shared render_embed so panel/bot/CLI cannot drift (D-01/D-06)"
  - "Both lines in embed DESCRIPTION, never the title — <t:> markdown does not render in a title (D-07)"
  - "location threaded via default-None keyword-only arg; 4 existing call sites unchanged this plan"
  - "📍 suppressed when location is None (argless status/alerts replies) — T-20-04 mitigation"
requirements-completed: [PANEL-12, PANEL-13]
metrics:
  duration: "2m"
  completed: "2026-06-27"
status_note: complete
---

# Phase 20 Plan 02: render_embed 📍 indicator + Updated stamp Summary

Added the `📍 {location}` selected-location indicator (PANEL-12/D-01) and the self-ageing `Updated <t:{unix}:t> (<t:{unix}:R>)` stamp (PANEL-13b/D-06) to the single surface-agnostic `render_embed` embed builder, both in the embed description (never the title, D-07), threaded via a default-`None` keyword-only `location` kwarg so all 4 existing call sites stay source-compatible.

## What Was Built

- **`render_embed` signature** changed to `def render_embed(reply, *, location: str | None = None) -> discord.Embed` — keyword-only, default `None`, so every existing positional caller (idle embed `bot.py:351`, inbound `on_message` `bot.py:510`, panel `panel.py:536/604`) is unchanged this plan.
- **Description lines (built before constructing the `discord.Embed`)**, per UI-SPEC line order:
  1. `📍 {location}` — appended only when `location is not None` (argless suppression, D-01).
  2. `Updated <t:{unix}:t> (<t:{unix}:R>)` — always appended, where `unix = int(discord.utils.utcnow().timestamp())` computed per render (D-06).
  - Joined with `\n` and passed as `description=` into the `discord.Embed(...)` constructor.
- **Retained** `embed.timestamp = discord.utils.utcnow()` at the tail (D-07) — a second always-correct time signal.
- **Unchanged**: the `add_field` / overflow / `_split_body` body logic (`bot.py:219-259`), the `render_embed` export (`bot.py:61`, `__init__.py:3,43`), and the two in-file call sites' behavior (left at `location=None` default).

## Tests Added (tests/test_bot.py)

- `test_render_embed_indicator_line` — `render_embed(reply, location="home").description` first line is `📍 home`.
- `test_render_embed_indicator_suppressed_when_argless` — argless `render_embed(reply).description` contains no `📍`; the `Updated …` line stands alone (no leading blank line).
- `test_render_embed_updated_stamp_in_description` — `.description` carries `<t:` with both `:t>` and `:R>` clauses; `.title` carries no `<t:`.
- `test_render_embed_keeps_native_timestamp` — `embed.timestamp` is non-`None` (D-07 retained).

## Verification

- `uv run pytest tests/test_bot.py -k "indicator or updated_stamp or native_timestamp"` → 4 passed (GREEN).
- `uv run pytest tests/test_bot.py -q` → 39 passed (existing field/title anti-drift snapshots stay green — the additions are description-level only).
- `uv run pytest -q` → **641 passed** (no caller drift; panel parity tests green since both sides share `render_embed`).
- `uv run ruff check` → all checks passed.
- `render_embed` export at `bot.py:61` and `__init__.py:3,43` confirmed unchanged.

## TDD Gate Compliance

- RED: `test(20-02)` commit `68b01eb` — 4 tests failed with `TypeError: render_embed() got an unexpected keyword argument 'location'` before implementation.
- GREEN: `feat(20-02)` commit `18c3b5f` — implementation made all 4 pass; full suite green.
- REFACTOR: none needed (implementation was minimal and clean).

## Deviations from Plan

None — plan executed exactly as written. Tasks 1 (implementation) and 2 (tests) were executed as a single TDD RED→GREEN cycle on the shared `render_embed` change, producing two atomic gate commits.

## Threat Surface

- T-20-04 (Information Disclosure — `📍` misreading on argless replies) mitigated by D-01 argless suppression, asserted by `test_render_embed_indicator_suppressed_when_argless`. No new untrusted input, network, auth, or dependency surface introduced.

## Notes for Plan 20-03

`render_embed` now accepts `location=`. Plan 20-03 wires the panel result-render call sites (`panel.py:536` → `location=arg`, `panel.py:604` → `location=self._selected_location`) to pass the selected location through. This plan only made the kwarg available and proved the render shape.

## Self-Check: PASSED

- FOUND: weatherbot/interactive/bot.py (render_embed with location= kwarg)
- FOUND: tests/test_bot.py (4 new tests)
- FOUND commit 68b01eb (RED)
- FOUND commit 18c3b5f (GREEN)
