---
phase: 33-interactive-panel-robustness
plan: 01
subsystem: interactive
tags: [F02, F27, HARD-UI-01, HARD-UI-03, bare-command, default-resolution, discord]
requires:
  - "yahir_reusable_bot.registry.dispatch_spec (hub guard `arg is not None or spec.needs_flags`)"
  - "weatherbot.config.resolve_location (CLI default-location resolver)"
  - "weatherbot.interactive.registry.CommandSpec.takes_location / needs_flags signals"
provides:
  - "Bare location commands resolve the default location app-side over Discord (F02 fixed)"
  - "Inbound reply renders the 📍 header (F27 restore) with a '(default)' marker on bare (D-05)"
affects:
  - "weatherbot/interactive/dispatch.py"
  - "weatherbot/interactive/bot.py"
tech-stack:
  added: []
  patterns:
    - "App-side default pre-resolution shim in front of the shared hub dispatcher (keeps hub weather-domain-free)"
    - "Additive cosmetic marker computed defensively so it can only drop, never break a rendered reply"
key-files:
  created: []
  modified:
    - "weatherbot/interactive/dispatch.py — app-side default-resolution branch before the hub delegation"
    - "weatherbot/interactive/bot.py — was_bare capture + _location_label + location= passed to render_embed"
    - "tests/test_bot.py — bare-command crash-then-default regression + named-marker parity"
    - "tests/test_dispatch.py — all-six takes_location default-resolve parametrization"
decisions:
  - "D-01: fix lives entirely in weatherbot/ app code (dispatch.py + bot.py); zero hub/.venv change"
  - "D-02: verify-crash-first — the RED crash-repro committed (cf90e53) before the fix (a3629e7)"
  - "D-05: bare reply header renders '📍 {default} (default)'; named renders '📍 {name}' unmarked"
  - "F27: inbound path now passes location= to render_embed so the 📍 header is no longer suppressed"
metrics:
  duration: 9min
  tasks: 2
  files: 4
  completed: 2026-07-13
status: complete
---

# Phase 33 Plan 01: Bare-command default resolution (F02) + inbound 📍 marker Summary

App-side default-location resolution for bare location commands over Discord — a bare
`!weather` (and `!alerts`/`!sun`/`!wind`/`!next-cloudy`/`!uv`) now resolves
`config.locations[0]` and returns a real weather embed instead of crashing to the
generic error, with the inbound 📍 header restored (F27) and a `(default)` marker on
bare replies (D-05) — all with zero change to the pinned hub wheel.

## What Was Built

**Task 1 — Verify-crash-first RED (commit `cf90e53`):**
- `tests/test_bot.py::test_bare_weather_no_longer_crashes` (authored as the RED
  crash-repro `test_bare_weather_crashes_pre_fix`, flipped to GREEN in Task 2) — a
  faithful `on_message` harness proving a bare `!weather` PRE-fix hit the hub
  skip-fetch guard, left `result=None`, and crashed on `None.forecast` → the generic
  `_ERROR_REPLY`. Passed against pre-fix behavior at commit time (D-02 evidence).
- GREEN siblings `test_bare_weather_default` + `test_named_weather_no_default_marker`
  pinning the default-location embed, the `📍 Toronto (default)` marker, and the F27
  named-path `📍 London` header.
- `tests/test_dispatch.py::test_takes_location_default_resolves` — parametrized over
  all six `takes_location=True` non-flags commands, asserting `arg=None` resolves the
  default name into the fetch. (All GREEN siblings were confirmed RED pre-fix,
  crashing on `None.forecast` exactly as F02 describes.)

**Task 2 — App-side fix (commit `a3629e7`):**
- `dispatch.py`: before the `_module_dispatch_spec` delegation, when `arg is None and
  flags is None and spec.takes_location and not spec.needs_flags`, set
  `arg = resolve_location(config, None).name`. This makes the hub guard
  `arg is not None or spec.needs_flags` fire, so the existing fetch/render path runs —
  matching the CLI's `resolve_location(None)` behavior on Discord.
- `bot.py`: capture `was_bare = arg is None and spec.takes_location` BEFORE dispatch
  resolves the default; add `_location_label(spec, arg, was_bare, config)` computing
  the 📍 header (default name + `" (default)"` when bare per D-05, resolved named
  location otherwise per F27, `None` for argless/forecast commands); pass it as
  `location=` to `render_embed`.

## Root Cause (F02)

The hub dispatcher (`yahir_reusable_bot/registry/dispatch.py:76`) guards the fetch with
`if arg is not None or spec.needs_flags:`. For a bare plain-weather command both are
False → the fetch is SKIPPED → `result` stays `None` → the bind closure calls
`weather_views.weather(None)` → `None.forecast` → AttributeError → the `on_message`
envelope answers with the generic `_ERROR_REPLY`. The CLI's documented default-location
behavior was dead over Discord. The dispatcher had a `needs_flags` signal but no
`takes_location` fetch trigger — so the app pre-resolves the default to make `arg`
non-None, without touching the hub.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test alignment] Widened existing `render_embed` monkeypatch stubs to the real signature**
- **Found during:** Task 2 (full-suite regression check)
- **Issue:** Three pre-existing tests (`test_registry_weather_view_builds_embed`,
  `test_uv_command_builds_embed`, `test_weekend_forecast_dispatch_builds_embed`) and two
  others monkeypatched `render_embed` with a single-positional-arg lambda
  `lambda reply: …`. The real signature has always been `render_embed(reply, *,
  location=None)`; those stubs only worked because the old inbound call site passed no
  `location=`. The F27 change (passing `location=`) made the narrow stubs raise
  `TypeError` → caught by the envelope → generic error → assertion failure.
- **Fix:** Widened all five stubs to `lambda reply, *, location=None: …` (matching the
  real, always-`location=`-capable signature). Production behavior is correct; the test
  doubles were incomplete.
- **Files modified:** tests/test_bot.py
- **Commit:** a3629e7

**2. [Rule 2 - Robustness] `_location_label` guards resolution failure to drop-not-break**
- **Found during:** Task 2
- **Issue:** `dispatch_spec` already resolved the location successfully (the fetch ran);
  re-resolving at the render call site for the display name is redundant and could raise
  on minimal test-fake configs (or a hot-reload edge). An exception there would turn an
  already-rendered good reply into the generic error.
- **Fix:** Wrapped the re-resolve in a guarded `try/except` that falls back to `None`
  (drops the cosmetic 📍 marker) — the header is strictly additive to an already-good
  reply and must never break it. Not a new blanket envelope catch (prohibition
  respected); it is scoped to the marker computation only.
- **Files modified:** weatherbot/interactive/bot.py
- **Commit:** a3629e7

## Verification

- `uv run pytest tests/test_bot.py tests/test_dispatch.py tests/test_import_hygiene.py`
  → 68 passed.
- Full suite: `uv run pytest` → **854 passed**, exit 0. The "2 snapshots failed" banner
  is the known pre-existing syrupy noise (trust the exit code + no `.ambr` diff, per
  the pytest snapshot-report quirk); no golden `.ambr`/`__snapshots__` files were
  modified by this change.
- **Litmus/grimp (D-01):** `git diff` touches ONLY `weatherbot/` + `tests/`; zero bytes
  changed under `.venv/` or `../Reusable/YahirReusableBot/` — hub stays weather-domain-free.
  `tests/test_import_hygiene.py` green.

## Threat Surface

No new network endpoints, auth paths, or trust-boundary changes. The default location
crosses into `lookup_weather` as a config-derived NAME (never raw user text — the
default is `resolve_location(config, None)`, no user string reaches the flag parser),
preserving the V5 input-validation boundary (T-33-01-02). The fix does not broaden the
generic `_ERROR_REPLY` (T-33-01-03). No package installs (T-33-01-SC).

## Known Stubs

None. Both tasks wire real behavior end-to-end; the default fetch runs and renders a
real embed. Test stubs are limited to handler/render doubles that decouple assertions
from payload shape (standard unit-test practice), not production placeholders.

## Self-Check: PASSED

- SUMMARY.md, dispatch.py, bot.py, test_bot.py, test_dispatch.py all present on disk.
- Commits cf90e53 (RED) and a3629e7 (fix) both present in git history.
