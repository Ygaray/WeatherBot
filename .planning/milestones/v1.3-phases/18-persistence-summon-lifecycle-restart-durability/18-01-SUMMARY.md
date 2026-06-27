---
phase: 18-persistence-summon-lifecycle-restart-durability
plan: 01
subsystem: api
tags: [discord.py, persistent-views, setup_hook, add_view, pydantic, config, restart-durability]

# Dependency graph
requires:
  - phase: 17-minimal-persistent-panel-core-wiring
    provides: "PanelView (timeout=None, static wb: custom_ids, in-memory selected location, operator-guard interaction_check)"
provides:
  - "BotConfig.panel_channel_id: required int ([bot] table) threaded daemon -> BotThread -> build_client"
  - "Persistent-view registration: PanelView registered via client.add_view in setup_hook (NOT on_ready) so callbacks re-bind by custom_id after restart"
  - "_PANEL_MARKER ('wb:') + _is_owned_panel(msg, bot_user) marker-strict ownership matcher (D-05) for Plan 02's !panel scan"
  - "Wave-0 test fakes in conftest: async-iterator channel.pins() stand-in, pinned-Message builder, Permissions-shaped fake (pin_messages)"
affects: [18-02 (!panel summon consumes _is_owned_panel + panel_channel_id + the Wave-0 fakes), 19, 20]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "discord.py setup_hook via @client.event (no Client subclass) for once-per-process persistent-view registration"
    - "deferred PanelView import inside setup_hook to break the panel.py->bot.py render_embed import cycle"
    - "marker-strict bot-owned-panel identity (author == bot.user AND a wb:-prefixed child custom_id), defensive getattr component walk"

key-files:
  created: []
  modified:
    - weatherbot/config/models.py
    - weatherbot/interactive/bot.py
    - weatherbot/interactive/panel.py
    - weatherbot/scheduler/daemon.py
    - tests/conftest.py
    - tests/test_models.py
    - tests/test_config.py
    - tests/test_bot.py
    - tests/test_panel.py
    - tests/test_scheduler.py

key-decisions:
  - "panel_channel_id is a plain required int mirroring operator_id (no field_validator); a present [bot] table now requires BOTH keys, extra=forbid unchanged"
  - "PanelView registered in setup_hook (runs once per process, pre-connect) NOT on_ready (re-fires on every reconnect -> duplicate registrations) — D-13"
  - "PanelView imported deferred inside setup_hook because panel.py imports render_embed from bot.py (module-top import would cycle)"
  - "_is_owned_panel requires author==bot_user AND a wb: child (author-alone rejected: would risk deleting an unrelated bot pin)"

patterns-established:
  - "setup_hook persistent-view registration: @client.event async def setup_hook(): client.add_view(PanelView(...)) with deferred PanelView import"
  - "Wave-0 RED-then-GREEN per task with conftest fakes landed ahead of the Plan-02 consumer"

requirements-completed: [PANEL-09]

# Metrics
duration: 9min
completed: 2026-06-26
status: complete
---

# Phase 18 Plan 01: Persistence Foundation Summary

**Restart-durable panel foundation: required `[bot] panel_channel_id` threaded daemon→BotThread→client, PanelView registered via `add_view` in `setup_hook` (not `on_ready`), and the `_is_owned_panel`/`wb:` marker matcher + Wave-0 pins/Permissions fakes the Plan-02 `!panel` summon will consume.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-06-26T17:23:20Z
- **Completed:** 2026-06-26T17:32:xxZ
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments
- `BotConfig.panel_channel_id` is now a required `int` on the `[bot]` table (sibling of `operator_id`, `extra="forbid"`/`frozen` unchanged); a present `[bot]` table requires both keys, an unknown key still fails loud at load.
- `panel_channel_id` threads from `config.bot` through `daemon.py` → `BotThread.__init__` → `build_client` (both gained the keyword-only param).
- `PanelView` is registered as a persistent view via `client.add_view` inside a `setup_hook` coroutine — so the already-pinned panel's buttons/dropdown re-bind to their callbacks purely by `custom_id` after a `systemctl restart` (PANEL-09). Registration is in `setup_hook` (once per process), NOT `on_ready` (which re-fires on every reconnect).
- `_PANEL_MARKER = "wb:"` + `_is_owned_panel(msg, bot_user)` land in `panel.py` — marker-strict, defensive-`getattr` ownership matcher that Plan 02's `!panel` scan/cleanup keys on.
- Wave-0 test infrastructure for Plan 02 stood up in `conftest.py`: an async-iterator `channel.pins()` stand-in, a pinned-`Message` builder (with `wb:` children + AsyncMock `edit`/`pin`/`delete`), and a `Permissions`-shaped fake exposing `pin_messages` (NOT `manage_messages`, D-10).

## Task Commits

Each task committed atomically (TDD: RED tests + GREEN impl folded into one feat commit per task):

1. **Task 1: Add BotConfig.panel_channel_id field (D-04)** - `a5e3d49` (feat)
2. **Task 2: Thread panel_channel_id + register PanelView in setup_hook (PANEL-09, D-12/D-13)** - `dcd5092` (feat)
3. **Task 3: _PANEL_MARKER + _is_owned_panel matcher + Wave-0 fakes (D-05)** - `3888080` (feat)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified
- `weatherbot/config/models.py` - Added required `panel_channel_id: int` to `BotConfig`; docstring notes the restart-boundary read-once behavior.
- `weatherbot/interactive/bot.py` - `build_client`/`BotThread.__init__` gain keyword-only `panel_channel_id`; new `setup_hook` registers `PanelView` via `add_view` (deferred PanelView import).
- `weatherbot/interactive/panel.py` - `_PANEL_MARKER` constant + `_is_owned_panel` marker matcher.
- `weatherbot/scheduler/daemon.py` - Forwards `config.bot.panel_channel_id` into `BotThread(...)`.
- `tests/conftest.py` - Wave-0 fakes: `_AsyncPinsIterator`, `_make_fake_pinned_message`, `_make_fake_permissions` (+ fixtures).
- `tests/test_models.py` / `tests/test_config.py` - `panel_channel_id` required/happy/unknown-key + load-time cases; existing `[bot]` fixtures updated.
- `tests/test_bot.py` - `setup_hook` registers exactly one `PanelView`; `on_ready` registers zero; `build_client`/`BotThread` accept `panel_channel_id`; updated BotThread isolation call sites.
- `tests/test_panel.py` - fresh-view `is_persistent()` + default-`locations[0]`; `_is_owned_panel` positive/negatives + childless-row robustness.
- `tests/test_scheduler.py` - `_bot_config()` + fake-BotThread stubs accept `panel_channel_id`.

## Decisions Made
- **panel_channel_id is a plain required int** (mirrors `operator_id`) — no `field_validator` needed; the loader's `extra="forbid"` already rejects unknown keys. A present `[bot]` table now requires BOTH keys.
- **Registration lives in `setup_hook`, not `on_ready`** (D-13) — `setup_hook` runs once per process pre-connect; `on_ready` re-fires on every gateway reconnect and would multiply persistent-view registrations.
- **Deferred `PanelView` import inside `setup_hook`** — `panel.py` imports `render_embed` from `bot.py`, so a module-top `PanelView` import in `bot.py` would create an import cycle.
- **`_is_owned_panel` placed in `panel.py`** (co-located with the `wb:` custom_ids it keys on) and requires `author == bot_user` AND a `wb:` child — author-alone was rejected to avoid ever deleting an unrelated bot pin.

## Deviations from Plan

None - plan executed exactly as written. All three tasks landed their specified artifacts; no Rule 1-4 deviations were required (no bugs, missing critical functionality, blockers, or architectural changes surfaced).

## Issues Encountered

- **Pre-existing ruff drift (not introduced this plan).** `ruff format --check` and `ruff check tests/test_panel.py` flag formatting/lint issues on lines this plan did NOT touch (a `_build()` signature, an f-string in `models.py:149`, and an `F841` unused `view` at `test_panel.py:194` — all Phase 13/14/17 code, verified present at HEAD before Task 3). My additions are ruff-clean. Left untouched per the scope boundary and logged to `deferred-items.md`; `ruff check weatherbot` (all source) passes clean. Recommend a standalone repo-wide `ruff format`/lint sweep as its own quick task.

## User Setup Required

None for this plan's code. NOTE for operators: deploying this requires adding `panel_channel_id` under `[bot]` in `config.toml` (a present `[bot]` table now fails to load without it) and a process restart (the new `setup_hook` + module only load on next start — config hot-reload does not load new code). The full live persistent-view restart UAT on host `yahir-mint` is a deferred Gate-2 milestone obligation (after Plan 02 lands `!panel`).

## Next Phase Readiness
- Plan 02 (`!panel` summon) can now consume `panel_channel_id` (to locate the channel), `_is_owned_panel`/`_PANEL_MARKER` (to find-or-reuse exactly one panel + delete strays), and the conftest Wave-0 fakes (async-iterator pins, pinned-Message builder, Permissions-shaped fake).
- The persistent-view registration (`add_view` in `setup_hook`) is in place; restart durability is wired but only observable end-to-end once `!panel` exists and a live restart UAT runs.
- No blockers.

## Self-Check: PASSED

- SUMMARY.md exists on disk.
- All three task commits present in git (`a5e3d49`, `dcd5092`, `3888080`).
- All modified source/test files present.

---
*Phase: 18-persistence-summon-lifecycle-restart-durability*
*Completed: 2026-06-26*
