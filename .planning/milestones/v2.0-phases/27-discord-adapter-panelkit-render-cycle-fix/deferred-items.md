# Phase 27 — Deferred Items

## From Plan 27-02 (app rewire)

### Test-harness rewire — owned by Plan 27-04 (Wave 3) + Plan 27-03 (oracle re-run)
The byte-identical relocation moved `build_client` / `BotThread` / the `!panel` summon
machinery / `PanelView` out of `weatherbot/interactive/{bot,panel}.py` into the module
adapter `yahir_reusable_bot/discord/`. The following test harnesses are still bound to the
OLD app-side API and fail at collection/call until 27-04 rewires them onto the module
`PanelKit` / `BotThread` + the app contributors. These are EXPECTED failures, explicitly
deferred by the 27-02 plan's verification section (the byte-identical panel/custom_id oracle
re-run is 27-04 + 27-03):

- `tests/test_panel.py` (34) — `_make_panel` constructs `panel.PanelView(...)` (deleted).
- `tests/test_golden_custom_ids.py` (2) — imports `_make_panel` from `test_panel`.
- `tests/test_oracle_selfproof.py` (1) — imports `_make_panel` from `test_panel`.
- `tests/test_bot.py` (17) — the `test_build_client_*` / `test_setup_hook_*` /
  `test_on_ready_*` / `test_bot_thread_*` / `test_panel_*` tests drive the relocated
  `bot.build_client` / `bot.BotThread` / the old `!panel` summon. (The `render_embed`,
  guard-ladder, and inbound-dispatch tests in the same file PASS — 23 green.)
- `tests/test_scheduler.py` (3) — `test_bot_thread_starts_strictly_after_online_signal`,
  `test_run_daemon_threads_read_only_daemon_state_into_bot`,
  `test_hanging_callback_never_stops_live_briefing` patch the OLD lazy import
  `monkeypatch.setattr(interactive_mod, "BotThread", ...)`. daemon.py now constructs the bot
  via `wiring.build_inbound_bot(...)`, so the mock injection point must move to
  `daemon_mod.build_inbound_bot` (the daemon bot behavior — construct + start-after-READY +
  finally stop — is unchanged; only the mock target drifted).

Total: 57 deferred-harness failures across 5 files; 721 pass. No non-harness regression.

### Argless 📍 suppression through the panel path — reconcile in 27-04
The `_render_bridge(reply, ctx) -> render_embed(reply, location=(ctx.value if ctx is not None
else None))` closure is implemented EXACTLY per the 27-02 acceptance criteria. The module
`PanelKit.on_command` passes `self._selection` to `render`, so a panel argless tap
(status/alerts) would forward the selected location into `location=` (📍 would show). The v1
behavior suppressed 📍 on argless via `arg = _selected_location if spec.takes_location else
None`. The `_dispatch` closure already computes that `arg`; the reconciliation (so the panel
argless path nulls the rendered location) lands with the 27-04 harness rewire + the 27-03
byte-identical oracle (`test_panel.py::test_argless_result_suppresses_indicator`). The Task-1
embed goldens (which call `render_embed` directly with explicit `location=`) are byte-identical
and pass — `render_embed`'s own suppression branch is untouched.

## Out of scope (pre-existing — NOT introduced by 27-02)

- `weatherbot/scheduler/daemon.py:1405` `notifier = parts.notifier` — ruff F841 "assigned but
  never used". Confirmed pre-existing at HEAD (`git show HEAD:...` flags it identically). Not
  touched by this plan; left as-is per the executor scope boundary.
