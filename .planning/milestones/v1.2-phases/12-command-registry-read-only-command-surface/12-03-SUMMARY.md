---
phase: 12-command-registry-read-only-command-surface
plan: 03
subsystem: interactive-command-surface
tags: [registry-dispatch, cli-subparsers, daemon-state, failure-isolation, read-only]
requirements-completed: [CMD-09, CMD-10, CMD-11, CMD-12, CMD-13, CMD-14, CMD-15, CMD-16]
requires:
  - "weatherbot/interactive/registry.py — CommandSpec/COMMANDS/parse_command (Plan 01)"
  - "weatherbot/interactive/commands/ — handlers + CommandReply (Plan 02)"
  - "weatherbot/interactive/state.py — DaemonState accessor (Plan 02)"
  - "weatherbot/interactive/bot.py — guard ladder + non-propagating envelope (Phase 11)"
  - "weatherbot/cli.py — add_subparsers + run_weather exit-code precedent (Phase 7)"
  - "weatherbot/scheduler/daemon.py — run_daemon bot construction site (Phase 11)"
provides:
  - "weatherbot/interactive/bot.py — registry-driven on_message dispatch + render_embed; daemon_state threaded"
  - "weatherbot/interactive/registry.py — COMMANDS handlers wired (lazy _wire_handlers)"
  - "weatherbot/cli.py — registry-generated subparsers + render_text + dispatch"
  - "weatherbot/scheduler/daemon.py — read-only DaemonState constructed + threaded into the bot"
  - "weatherbot/interactive/__init__.py — registry/command/state surface exported"
affects:
  - "Phase 13 (on-demand forecast commands register through this same registry/dispatch)"
  - "Phase 14 (uv command rides the same CLI/Discord dispatch)"
  - "Phase 15 (DaemonState.monitor_alive slot reported by status)"
tech-stack:
  added: []
  patterns:
    - "lazy handler wiring via dataclasses.replace (acyclic import discipline)"
    - "single non-propagating envelope wrapping registry dispatch (Pitfall 5, CMD-16)"
    - "registry-generated argparse subparsers (derive-from-one-list, CMD-09)"
    - "late-binding bot_alive lambda over a read-only DaemonState"
key-files:
  created: []
  modified:
    - weatherbot/interactive/bot.py
    - weatherbot/interactive/registry.py
    - weatherbot/interactive/__init__.py
    - weatherbot/cli.py
    - weatherbot/scheduler/daemon.py
    - tests/test_bot.py
    - tests/test_interactive_package.py
    - tests/test_cli.py
    - tests/test_scheduler.py
    - tests/test_registry.py
decisions:
  - "Handlers wired via a single _wire_handlers(replace(...)) pass with LAZY handler imports (not per-spec handler= literals) to keep registry.py importable by command.py without an import cycle"
  - "render_embed (Discord) and render_text (CLI) render the SAME frozen CommandReply — the D-04 same-content seam; build_inbound_embed retained but no longer on the dispatch path"
  - "DaemonState.bot_alive is a late-binding lambda over the local bot so it reports CURRENT liveness; CLI status uses a CLI-scoped DaemonState (empty-jobs scheduler, bot_alive=False, live heartbeat read only)"
  - "CLI has no Discord guard ladder (Open Question 3: terminal == operator) but inherits registry + read-only + failure isolation"
metrics:
  duration: "~30 min"
  completed: "2026-06-19"
  tasks: 3 (of 4; Task 4 is the live operator checkpoint)
  files-created: 0
  files-modified: 10
  tests-added: 14
---

# Phase 12 Plan 03: Registry-Wired Command Surface (Discord + CLI + Daemon) Summary

Wired the Plan 01 registry and Plan 02 handlers into both surfaces and the daemon:
the Discord `on_message` now dispatches every registered command through the registry
INSIDE the unchanged guard ladder + non-propagating envelope (CMD-16), the CLI
generates one subparser per registry spec from the SAME list (CMD-09 anti-drift), and
`run_daemon` constructs a read-only `DaemonState` and threads it into the bot so
`status` answers live (CMD-12). Full suite green at 358 passed. The remaining work is
the live operator verification on `yahir-mint` (Task 4 checkpoint).

## What Was Built

### Task 1 — Registry-driven Discord dispatch + handler wiring (commit `e53f40b`)
- `registry.py`: replaced the Plan 01 `handler=None` placeholders with the real
  callables via `_wire_handlers(_SPECS)` — a single pass using
  `dataclasses.replace(spec, handler=...)` with LAZY handler imports (inside the
  function) so `registry.py` stays importable by `command.py` with no import cycle.
  `alerts`/`sun`/`wind`/`next-cloudy` ← `commands.weather_views`, `help`/`locations`
  ← `commands.info`, `status` ← `commands.status`.
- `bot.py`: `build_on_message` step (4) now calls `parse_command` (registry); a
  `spec is None` (non-command) returns exactly as before. The WHOLE registry dispatch
  lives INSIDE the EXISTING non-propagating try/except (Pitfall 5 — no second
  envelope): location-taking specs go through `cache.lookup` off-loop
  (`run_in_executor`) then call the handler (`next-cloudy` also gets
  `config.cloud_threshold`); `status` runs its handler off-loop against the injected
  `daemon_state`; `locations`/`help` call directly (no fetch). A new `render_embed`
  helper turns the returned `CommandReply` into a `discord.Embed` (the
  `build_inbound_embed` house style). The `UnknownLocationError` sub-except is
  preserved. A new `daemon_state` param (default `None`) is threaded through
  `build_on_message`/`build_client`/`BotThread`. Guard steps (1)-(3) and the outer
  envelope are byte-for-byte unchanged.
- `__init__.py`: exported the registry surface (`COMMANDS`, `CommandSpec`,
  `ParsedCommand`, `parse_command`, `render_help`, `render_embed`, `DaemonState`).
- `tests/test_bot.py`: registry dispatch for a weather view (stubbed handler + fake
  cache), `help`/`locations` (no fetch), `status` (fake DaemonState), non-command
  drop, unknown-location hint, off-loop dispatch, and the **CMD-16 isolation test**
  (a raising handler does NOT propagate out of `on_message` and yields the generic
  reply). `tests/test_interactive_package.py`: a new test for the registry exports +
  every spec carries a callable handler.

### Task 2 — Registry-generated CLI subparsers + daemon DaemonState (commit `7df327c`)
- `cli.py`: a loop over `registry.COMMANDS` generates one subparser per spec
  (`help` skips `config_parent`; `takes_location` specs get `location nargs="?",
  default=None`). A registry-driven dispatch branch (`_run_registry_command`) resolves
  the spec via `registry.BY_NAME`, loads config where needed (exit 2 on bad config),
  resolves+fetches via the shared `lookup_weather` core for weather views (unknown →
  exit 1 with the hint; fetch failure → exit 3), and prints the `CommandReply` via a
  new `render_text` helper (same content as the embed, D-04). A CLI-scoped
  `_cli_daemon_state` gives `status` a read-only accessor (empty-jobs scheduler,
  `bot_alive=False`, live heartbeat read). A code comment documents the no-guard-ladder
  CLI posture (Open Question 3).
- `daemon.py`: `run_daemon` captures `started_at = datetime.now(timezone.utc)` and,
  in the bot-construction block, builds `DaemonState(scheduler, holder, db_path,
  started_at, bot_alive=lambda: bot is not None and bot.is_alive())` (read-only,
  late-binding liveness), threaded into the `BotThread` alongside `cache`. No write
  capability is handed to DaemonState (D-02). The scheduler/heartbeat/reload wiring is
  untouched.
- `tests/test_cli.py`: every-spec-parses (CMD-09 derive-from-one-list), help prints all
  commands, locations lists names, `sun <loc>` prints + exits 0 (fake lookup),
  unknown-location exits 1 with the hint, `status` prints + exits 0, bad-config exits
  2. `tests/test_scheduler.py`: a new test asserts `run_daemon` threads a non-None
  read-only `DaemonState` (live scheduler, db_path, callable bot_alive, no mutation
  API) into the bot.

### Task 3 — Full suite gate + deploy note (commit `dc5f7db`)
- Ran the per-wave sampling set and the WHOLE suite. The Plan 01
  `test_handlers_are_placeholders_this_plan` (asserting handlers are `None`) is now
  intentionally inverted by Plan 03's wiring → updated to `test_handlers_are_wired`
  (every handler callable). Full suite: **358 passed** (Plan 02 was 344; +14), 1
  pre-existing audioop warning.

## Deploy Step Required Before the Live Checkpoint (Task 4)

**The running `weatherbot` systemd service on `yahir-mint` MUST be RESTARTED after
deploy.** New Python modules (`commands/`, `state.py`, the registry handlers, the
bot/CLI/daemon dispatch wiring) and the widened One Call `exclude` (Plan 01) only load
on the NEXT process start — the hot-reload path covers config/templates, NOT modules
(12-RESEARCH Runtime State Inventory; MEMORY weatherbot-live-systemd-service). So:

```
sudo systemctl restart weatherbot
systemctl status weatherbot     # expect active/running, no CRITICAL in the journal
```

Until the restart, the live daemon will not have the new command surface even though
the code is deployed.

## Verification

- `uv run pytest` → **358 passed**, 1 pre-existing audioop warning.
- Per-wave sampling: `uv run pytest tests/test_registry.py tests/test_command.py
  tests/test_bot.py tests/test_command_views.py tests/test_status.py tests/test_cli.py
  tests/test_client.py tests/test_store.py tests/test_config.py` → 171 passed.
- `grep -c 'parse_command' weatherbot/interactive/bot.py` → 3 (dispatch is
  registry-driven); `parse_weather_command` now only in the docstring (old call
  replaced).
- Guard steps (1)-(3) + the outer non-propagating envelope are byte-for-byte
  unchanged; the whole registry dispatch sits inside the existing try/except (Pitfall
  5 — no net-new envelope).
- `grep -c 'registry\|COMMANDS' weatherbot/cli.py` → 12 (subparsers + dispatch derive
  from the registry — no second list, CMD-09 anti-drift).
- `grep -c 'DaemonState' weatherbot/scheduler/daemon.py` → 4; `grep -c 'started_at'`
  → 3. No `add_job`/`holder.replace`/`stamp_`/`persist` introduced on the DaemonState
  path.
- Behavior: a wired handler that raises does NOT propagate out of `on_message`
  (CMD-16); `!sun home` / `weatherbot sun <loc>` produce a reply; a non-operator and a
  non-command are dropped.
- `ruff check` + `ruff format` clean on all changed files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated Plan 01 placeholder test that Plan 03 invalidates**
- **Found during:** Task 3 (full suite gate)
- **Issue:** `tests/test_registry.py::test_handlers_are_placeholders_this_plan` asserted
  every `COMMANDS` handler is `None` — the Plan 01 contract. Plan 03's defining job is
  to wire those handlers, so the assertion is now inverted and failed.
- **Fix:** Renamed to `test_handlers_are_wired` asserting every handler is `callable`
  (the new Plan-03 invariant). Same file/seam the plan's scope covers.
- **Files modified:** tests/test_registry.py
- **Commit:** dc5f7db

**2. [Rule 3 - Blocking] Updated existing bot-thread test stubs to accept daemon_state**
- **Found during:** Task 2 (daemon DaemonState threading)
- **Issue:** `run_daemon` now passes `daemon_state=` to `BotThread`. The existing
  `_RecordingBotThread`/`_ExplodingBotThread` stubs in `tests/test_scheduler.py` had a
  fixed `__init__(self, token, *, holder, operator_id, cache)` signature and would
  raise `TypeError: unexpected keyword argument 'daemon_state'`.
- **Fix:** Added `daemon_state=None` to both stub signatures (a keyword-only param with
  a default, matching the real `BotThread`). No behavior change to those tests.
- **Files modified:** tests/test_scheduler.py
- **Commit:** 7df327c

No bugs, no missing critical functionality, no architectural changes. The dispatch
preserved the guard ladder + isolation envelope exactly as specified.

## Known Stubs

None. Every registry command is wired end-to-end on both surfaces; the only intentional
"not running" value is `status`'s UV-monitor line, which is the clean Phase-15 slot
(`DaemonState.monitor_alive=None` → "not running" until Phase 15 supplies the callable,
A4) — documented and tracked, not a data stub.

## Notes for Downstream

- Phase 13/14 commands register by adding a `CommandSpec` + handler to the registry;
  both surfaces pick them up automatically (the derive-from-one-list invariant is now
  load-bearing on the CLI AND Discord).
- `render_embed` (Discord) / `render_text` (CLI) are the two renderers of the single
  `CommandReply` — keep new replies surface-agnostic.
- The CLI `status` scope is intentionally narrower than the live-daemon `!status`
  (no live scheduler/bot in a one-shot — only the heartbeat read is live).

## Self-Check: PASSED

- FOUND commit e53f40b (Task 1 — Discord dispatch + handler wiring)
- FOUND commit 7df327c (Task 2 — CLI subparsers + daemon DaemonState)
- FOUND commit dc5f7db (Task 3 — full suite gate)
- FOUND: weatherbot/interactive/bot.py, registry.py, __init__.py modified (registry dispatch + render_embed + exports)
- FOUND: weatherbot/cli.py modified (registry subparsers + render_text + dispatch)
- FOUND: weatherbot/scheduler/daemon.py modified (DaemonState + started_at)
- VERIFIED: `uv run pytest` → 358 passed
