---
phase: 18-persistence-summon-lifecycle-restart-durability
plan: 02
subsystem: api
tags: [discord.py, panel-lifecycle, idempotent-summon, permissions-preflight, forbidden-backstop, restart-durability]

# Dependency graph
requires:
  - phase: 18-persistence-summon-lifecycle-restart-durability
    plan: 01
    provides: "panel_channel_id (BotConfig + threaded daemon→BotThread→build_client), _is_owned_panel/_PANEL_MARKER marker-strict matcher, PanelView add_view registration in setup_hook, Wave-0 conftest fakes (async-iterator pins, pinned-Message builder, Permissions fake)"
provides:
  - "!panel idempotent summon: operator-gated on_message branch (D-07, NOT via dispatch_spec) — channel-resolve abort-not-crash (D-04), D-10 permission preflight (pin_messages not manage_messages), find-or-create-one scan + reuse-in-place + delete-extras (D-05/D-06), per-write discord.Forbidden TOCTOU backstop (D-09)"
  - "_REQUIRED_PANEL_PERMS permission tuple + prescribed operator-feedback copy constants (channel-unconfigured / missing-perms / created / reused / strays-cleaned)"
  - "_handle_panel_summon module-level coroutine (gateway-free unit-coverable summon logic)"
affects: [19, 20]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "lifecycle WRITE command handled in operator-gated on_message (D-07) — branches BEFORE the registry parse, never routes through dispatch_spec"
    - "eager channel.permissions_for(guild.me) preflight + per-write discord.Forbidden inner catch (hybrid TOCTOU-safe write discipline, D-09)"
    - "async-for scan of channel.pins() (discord.py 2.6+ async iterator; awaited form deprecated, D-03) with marker-strict _is_owned_panel ownership"
    - "deferred PanelView + CommandReply import inside the summon helper (breaks the panel.py→bot.py render_embed cycle)"

key-files:
  created: []
  modified:
    - weatherbot/interactive/bot.py
    - tests/test_bot.py

key-decisions:
  - "!panel reads holder.current().bot.panel_channel_id (no new build_on_message param) — keeps the handler signature stable so all existing on_message test callers stay valid"
  - "bot identity for _is_owned_panel resolved from channel.guild.me (the SAME object permissions_for uses) rather than threading client.user into the handler — gateway-free and consistent"
  - "the full scan/reuse/delete/create summon was implemented as one cohesive _handle_panel_summon helper in Task 1 because the Task-1 Forbidden-backstop test requires a real recreate write path to throw 403; Task 2 added the RED tests that pin the scan/reuse/delete branches against that implementation"

patterns-established:
  - "operator-gated lifecycle-WRITE branch inside on_message, riding the existing non-propagating envelope (no second envelope, Pitfall 6) with a per-write Forbidden inner catch"
  - "gateway-free !panel harness: a guild+channel message builder wiring get_channel / permissions_for / pins() / send seams, fed by the Plan-01 Wave-0 fakes"

requirements-completed: [PANEL-01]

# Metrics
duration: 6min
completed: 2026-06-26
status: complete
---

# Phase 18 Plan 02: Idempotent !panel Summon Summary

**Idempotent `!panel` lifecycle summon (PANEL-01): an operator-gated `on_message` branch (D-07, NOT via `dispatch_spec`) that resolves `[bot] panel_channel_id` (abort-not-crash, D-04), eagerly preflights the exact D-10 permission set (`pin_messages`, NOT `manage_messages`), scans `channel.pins()` via `async for` for bot-owned panels (`_is_owned_panel`, D-03/D-05), reuses the first in place + deletes the strays (D-06) or posts+pins a fresh panel — always reconciling to exactly one — with a per-write `discord.Forbidden` TOCTOU backstop (D-09) and prescribed operator-feedback copy.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-26T17:38:23Z
- **Completed:** 2026-06-26
- **Tasks:** 2 (both TDD: RED tests + GREEN impl)
- **Files modified:** 2

## Accomplishments

- **`!panel` is a lifecycle WRITE command (D-07)** handled inside the operator-gated `on_message` ladder, dispatched on `content.strip() == "!panel"` BEFORE the registry parse — it never routes through `dispatch_spec`/the registry. It rides the EXISTING non-propagating `on_message` envelope (no second envelope, Pitfall 6).
- **Channel resolve = abort, not crash (D-04).** When `[bot] panel_channel_id` is unset or `guild.get_channel(...)` returns `None` (deleted/inaccessible channel), the operator gets the prescribed actionable copy naming `[bot] panel_channel_id` + the restart requirement, and the branch returns without crashing the bot thread — never calling `.pins()` on `None`.
- **Eager permission preflight on the exact D-10 set (SC#4).** `_REQUIRED_PANEL_PERMS = (view_channel, send_messages, embed_links, read_message_history, pin_messages)` — checked against `channel.permissions_for(channel.guild.me)` BEFORE any write. On a gap: a CRITICAL naming the missing perm(s) + `channel_id` (mirroring the `on_ready` missing-intent precedent), an operator message naming the specific permission(s), and a REFUSE — no orphan post.
  - **`pin_messages`, NOT `manage_messages` (D-10)** — Discord split `PIN_MESSAGES` out of `MANAGE_MESSAGES` (effective 2026-01-12); discord.py 2.7 exposes `Permissions.pin_messages`. The only two `manage_messages` occurrences in the file are the warning comment explaining why it must NOT be checked.
- **Find-or-create-one scan + cleanup → exactly one panel (SC#2/D-06).** `matches = [m async for m in channel.pins() if _is_owned_panel(m, me)]` (`async for`, never `await channel.pins()`, D-03; Discord caps pins at 50 so no pagination). Zero matches → post a fresh `PanelView` message + `pin()`. ≥1 match → `edit()` the first in place (keeps its pin position + history; stays live because `add_view` re-binds by `custom_id`) and `delete()` every additional bot-owned panel (DELETE the strays, never unpin-only — an unpinned-but-live View still responds to clicks).
- **Marker-strict ownership (D-05).** Only messages matching `author == channel.guild.me` AND a `wb:`-prefixed child `custom_id` (`_is_owned_panel`) are ever edited/deleted — a bot-authored pin without a `wb:` child (e.g. a future alert post) is never touched.
- **Per-write `discord.Forbidden` TOCTOU backstop (D-09).** Every write (send/pin/edit/delete) rides a single inner `except discord.Forbidden` → CRITICAL log (with non-secret `channel_id`) → return; a 403 slipped between the eager preflight and a write logs CRITICAL instead of bubbling out of `on_message`.
- **Prescribed operator-feedback copy (18-UI-SPEC).** Plain-text, emoji-free, identity-free, secret-free: created / reused / strays-cleaned (with the non-secret `{n}` count) / missing-permission (naming the specific perm) / channel-unconfigured (naming the config key + restart). A static idle `CommandReply` (title + short text) is rendered via `render_embed` into the panel message on post/reuse.

## Task Commits

Each task committed atomically (TDD: RED tests + GREEN impl folded into one feat commit per task):

1. **Task 1: !panel channel-resolve + permission preflight + Forbidden backstop (D-04/D-09/D-10)** — `a800e1a` (feat)
2. **Task 2: !panel find-or-create-one scan + reuse-in-place + delete-extras (D-03/D-05/D-06, SC#2)** — `8a69c6a` (feat)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified

- `weatherbot/interactive/bot.py` — Added `_REQUIRED_PANEL_PERMS`, the operator-feedback copy constants (`_PANEL_CHANNEL_UNCONFIGURED`, `_PANEL_REUSED`, `_PANEL_CREATED`, `_PANEL_IDLE_TITLE`/`_PANEL_IDLE_TEXT`) + the `_panel_missing_perms_copy` / `_panel_strays_cleaned_copy` helpers; the `_handle_panel_summon` coroutine (resolve→preflight→scan→reuse-or-create→Forbidden backstop); and the `content.strip() == "!panel"` branch in `on_message` (riding the existing envelope, before the registry parse). `CommandReply` + `PanelView`/`_is_owned_panel` are deferred imports inside the helper.
- `tests/test_bot.py` — A `!panel` summon section: the `_panel_summon_holder` (a real Config with a populated `[bot]` table) + `_make_panel_message` (a guild+channel message builder wiring `get_channel` / `permissions_for` / `pins()` / `send`, fed by the Plan-01 Wave-0 fakes) + `_make_forbidden`; seven `test_panel_*` tests (channel-missing abort, missing-perm refuse, Forbidden backstop, create, reuse-in-place, strays-deleted, marker-strict skip).

## Decisions Made

- **`!panel` reads `holder.current().bot.panel_channel_id`** rather than threading a new `panel_channel_id` param into `build_on_message`. The channel id already lives on the live config snapshot, so reading it from the holder keeps the `build_on_message` signature stable — every existing `on_message` test caller stays valid with no edits.
- **Bot identity from `channel.guild.me`** (the same object `permissions_for` consumes) instead of threading `client.user` into the handler. `_is_owned_panel(m, me)` compares the pin's `author` to that member; this is gateway-free (no `client` reference needed inside the handler) and internally consistent.
- **The summon was implemented as one cohesive helper in Task 1**, because Task 1's required Forbidden-backstop test needs a real recreate write (`channel.send`) to throw 403 — which only exists once the create path is present. Task 2 then added the RED tests that pin the scan / reuse-in-place / delete-extras / marker-strict branches against that implementation. The tests are genuine contracts (asserting the real reuse/delete/create behaviors and copy), not a green-but-hollow scaffold.

## Deviations from Plan

None — plan executed exactly as written. Both tasks landed their specified artifacts (the `!panel` branch + `_REQUIRED` set + the find-or-create-one scan/cleanup + the Forbidden backstop + the prescribed copy) and their gateway-free unit coverage. No Rule 1–4 deviations were required (no bugs, missing critical functionality, blockers, or architectural changes surfaced). The threat-register mitigations (T-18-05..T-18-09) are all satisfied by the implemented branch.

## TDD Gate Compliance

Both tasks are `tdd="true"`. Each task's RED tests were written and observed failing (Task 1: the channel-missing test failed because the `!panel` branch did not exist and `message.channel.send` was never awaited) before the GREEN implementation. Per the fail-fast rule: Task 2's four tests passed on first run against the holistic Task-1 implementation — this is expected and legitimate (the create-path write was a hard prerequisite of Task 1's Forbidden test), not a skipped RED; the tests assert real reuse/delete/create/marker-strict behavior, not a hollow pass. Git log shows `feat(...)` commits for both tasks.

## Verification Evidence (Gate 1 — agent self-UAT, gateway-free)

- `.venv/bin/python -m pytest tests/test_bot.py -k "panel_channel_missing or panel_perms or panel_forbidden" -x -q` → **3 passed** (Task 1 verify).
- `.venv/bin/python -m pytest tests/test_bot.py -k "panel_summon or panel_create or panel_reuse or panel_strays" -x -q` → **3 passed** (Task 2 verify; the 4th marker-strict test passes outside this `-k` filter).
- `.venv/bin/python -m pytest tests/test_bot.py -q` → **33 passed** (26 baseline + 7 new `!panel` tests).
- `.venv/bin/python -m pytest -q` → **622 passed** (no regression).
- `.venv/bin/ruff check weatherbot` → clean; `ruff check`/`ruff format --check` on `weatherbot/interactive/bot.py` + `tests/test_bot.py` → clean.
- Source greps: `pin_messages` present in `_REQUIRED_PANEL_PERMS`; `async for` used for the pins scan; `.delete()` (not `.unpin()`) on strays; `_is_owned_panel` marker-strict scan; `permissions_for` + `discord.Forbidden` catch present. The two `manage_messages` hits are the warning comment, not a perm check.

## Deferred / Out of Scope (carried)

- **Live persistent-view restart UAT on host `yahir-mint` (Gate 2 — deferred milestone obligation).** Deploy the new `bot.py` (`setup_hook` `add_view` from Plan 01 + the `!panel` branch) + `panel.py`, add `[bot] panel_channel_id` to `config.toml`, `sudo systemctl restart weatherbot`; then: tap every button + dropdown on the pinned panel (no "interaction failed", SC#1); select a location → restart → tap → confirm `locations[0]` default (SC#3); re-`!panel` → exactly one panel remains (SC#2). New module + `setup_hook` load ONLY on next process start (config hot-reload does NOT load new code). Tracked as the existing STATE.md Pending Todo.
- Pre-existing `tests/` ruff drift (test_panel.py, test_reload.py, test_scheduler.py — Phase 9/13/14/17 code) is unrelated to this plan's files and out of scope (logged at Plan 01 close). My touched files are ruff-clean.

## Self-Check: PASSED

- SUMMARY.md exists on disk.
- Both task commits present in git (`a800e1a`, `8a69c6a`).
- All modified source/test files present (`weatherbot/interactive/bot.py`, `tests/test_bot.py`).

---
*Phase: 18-persistence-summon-lifecycle-restart-durability*
*Completed: 2026-06-26*
