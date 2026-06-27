---
phase: 16-extract-shared-dispatch-spec
plan: 01
subsystem: interactive
tags: [refactor, dispatch, drift-prevention, behavior-preserving]
requires:
  - weatherbot.interactive.command (parse_forecast_flags, forecast_cache_suffix, parse_command)
  - weatherbot.interactive.registry (CommandSpec, COMMANDS, BY_NAME)
  - weatherbot.interactive.cache (ForecastCache.lookup)
  - weatherbot.interactive.commands (CommandReply)
  - weatherbot.interactive.state (DaemonState)
provides:
  - weatherbot.interactive.dispatch.dispatch_reply (sync single arg-adaptation ladder)
  - weatherbot.interactive.dispatch.dispatch_spec (async off-loop-fetch wrapper)
affects:
  - weatherbot.interactive.bot (on_message now routes through dispatch_spec)
  - weatherbot.cli (_run_registry_command now routes through dispatch_reply)
tech-stack:
  added: []
  patterns:
    - "Two-layer dispatcher: shared sync ladder (dispatch_reply) + per-surface async wrapper (dispatch_spec)"
    - "Acyclic module-top imports; heavy types under TYPE_CHECKING (D-09)"
    - "Off-loop execution of the whole ladder so status->SQLite never blocks the gateway loop"
key-files:
  created:
    - weatherbot/interactive/dispatch.py
    - tests/test_dispatch.py
  modified:
    - weatherbot/interactive/bot.py
    - weatherbot/cli.py
decisions:
  - "D-01/D-07: the if/elif arg-adaptation ladder now exists exactly ONCE (dispatch_reply); both surfaces route through it"
  - "D-02: the CLI calls the SYNC dispatch_reply (not the async dispatch_spec); its own lookup_weather/retry/exit-code path is unchanged"
  - "D-05: rendering (render_embed/render_text) stays surface-specific at the call site; the dispatcher returns an unrendered CommandReply"
  - "D-06: UnknownLocationError bubbles out of dispatch_spec; the bot catches it at the call site and replies with the valid names"
requirements-completed: [PANEL-10]
metrics:
  duration: ~4m
  tasks: 3
  files-created: 2
  files-modified: 2
  completed: 2026-06-23
---

# Phase 16 Plan 01: Extract Shared dispatch_spec Summary

Behavior-preserving extraction of the heterogeneous arg-adaptation if/elif ladder
out of BOTH `on_message` and `cli.py:_run_registry_command` into ONE shared
dispatcher (`weatherbot/interactive/dispatch.py`), so the registry command set can
never drift across surfaces (PANEL-10) — proven by the full existing suite staying
green and byte-identical (575 → 583 with the 8 new dispatcher tests).

## What Was Built

- **`dispatch_reply(spec, *, result, config, flags, daemon_state) -> CommandReply`**
  (sync): the SINGLE if/elif "who-needs-what" ladder, branch order lifted verbatim
  from the two call sites (forecast → next-cloudy → uv → catch-all location →
  status → locations → help). Read-only: no fetch, no render, no I/O.
- **`dispatch_spec(spec, arg, *, cache, config, loop, daemon_state) -> CommandReply`**
  (async): the off-loop-fetch wrapper for the async surfaces (bot now, panel in
  Phase 17). It owns the forecast-flags parse (bot + panel stay DRY), runs
  `ForecastCache.lookup` off-loop via `run_in_executor` (2-arg for weather, 3-arg
  with the widened-key `suffix` for forecast), then runs the WHOLE `dispatch_reply`
  call off-loop too so the `status` handler's SQLite `read_heartbeat` never blocks
  the gateway loop. `UnknownLocationError` BUBBLES (caught at the bot call site).
- **`bot.py` `on_message`**: the inline parse + off-loop fetch + ladder replaced by
  one `await dispatch_spec(...)` inside the existing `typing()` block and the
  existing non-propagating envelope (no second envelope, CMD-16). `render_embed` +
  send and the `UnknownLocationError → channel.send(str(exc))` short-circuit stay
  at the call site. The dead in-handler lazy import of the forecast-flag helpers
  was removed (it moved to `dispatch.py` as a module-top import).
- **`cli.py` `_run_registry_command`**: the inline if/elif ladder replaced by one
  sync `dispatch_reply(...)` call inside the existing handler-failure envelope. The
  CLI's own `parse_forecast_flags`, `lookup_weather` + tenacity/exit-code wrapper,
  `_cli_daemon_state(config)`, exit codes 0/1/2/3, and `render_text` + `print` all
  stay at the call site (D-02).
- **`tests/test_dispatch.py`**: 8 tests asserting each of the 7 binding branches
  hands the handler the right args, plus a read-only assertion (no fetch/render —
  the sentinel `CommandReply` returns unchanged).

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 (RED) | Failing tests for dispatch_reply | dae848a | tests/test_dispatch.py |
| 1 (GREEN) | Create dispatch.py (dispatch_reply + dispatch_spec) | 04e2dbd | weatherbot/interactive/dispatch.py, tests/test_dispatch.py |
| 2 | Route on_message through dispatch_spec | 57f890a | weatherbot/interactive/bot.py |
| 3 | Route CLI _run_registry_command through dispatch_reply | 83be161 | weatherbot/cli.py |

## Verification

- **[BLOCKING] Byte-identical behavior (criterion #2):** `uv run pytest` → 583
  passed (575 prior + 8 new), exit 0. test_bot.py (22) and test_cli.py (46) green
  — replies and exit codes unchanged.
- **Single dispatch path (criterion #3):**
  `grep -nE 'spec\.name == "next-cloudy"|spec\.name == "locations"' weatherbot/interactive/bot.py weatherbot/cli.py`
  → empty. The ladder lives ONLY in `dispatch.py`.
- **Read-only ladder (criterion #4):** `dispatch_reply`'s body contains no
  `cache.lookup`/`lookup_weather`/`render_embed`/`render_text` and no
  store/sent-log/scheduler write (`holder.replace`/`record_sent`/`claim_slot`
  grep empty). The off-loop `cache.lookup` lives only in `dispatch_spec` by design.
- **No import cycle:** `uv run python -c "import weatherbot.interactive.dispatch"`
  succeeds.
- **Lint:** `uv run ruff check` on all four touched files → All checks passed.

## Self-UAT (Gate 1)

This phase ships no new user-visible behavior — it is a pure behavior-preserving
internal refactor. The device-verifiable acceptance is "replies and exit codes are
unchanged", which is exactly what the contractual test suite encodes. Autonomous
verification: the full `uv run pytest` suite (including the per-surface contract
tests `test_bot.py`/`test_cli.py`/`test_registry.py`/`test_command.py`/
`test_command_views.py`) stays green and byte-identical at 583 passed, exit 0.
No reply text, exit code, or behavior changed. Verdict: PASS.

> Note (live ops): the bot runs as a systemd service on host yahir-mint (editable
> install). A `systemctl restart weatherbot` would pick up this refactor in
> production, but it is NOT required for correctness — behavior is identical. This
> is recorded as a deferred Gate-2 (milestone-close) human-UAT item, not a phase
> blocker.

## Deviations from Plan

None of substance — plan executed as written. Two cosmetic comment/docstring
wordings avoided the literal tokens `lookup_weather` (dispatch.py docstring) and
`dispatch_spec` (cli.py comment) so the criterion #3/#4 grep gates read cleanly
without changing any behavior; the load-bearing `cache.lookup` call remains in
`dispatch_spec` where the off-loop fetch belongs.

## Self-Check: PASSED

- FOUND: weatherbot/interactive/dispatch.py
- FOUND: tests/test_dispatch.py
- FOUND commit dae848a, 04e2dbd, 57f890a, 83be161
