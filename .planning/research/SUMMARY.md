# Project Research Summary

**Project:** WeatherBot — v1.3 Discord Control Panel
**Domain:** Discord interactive components (buttons / string selects / restart-durable persistent views with in-place editing) layered onto an existing single-operator discord.py gateway bot
**Researched:** 2026-06-23
**Confidence:** HIGH

## Executive Summary

v1.3 is a **pure UI layer**, not a feature build. The "tap-to-drive" panel (a location dropdown + a grid of command buttons, results rendering in-place) is built entirely from the message-component API that already ships in the **already-pinned `discord.py>=2.7.1,<3`**. There is **no new dependency, no version bump, no migration to slash/app commands, and no new gateway intent** — component clicks ride the *existing* gateway connection straight into View callbacks. The roadmap should therefore carry **zero stack/dependency tasks**. Every "feature" is an interaction behavior whose actual answer comes from an already-shipped v1.2 registry command, the existing `ForecastCache`, and the existing `render_embed`. The panel is a *third caller* of the same dispatch core that `on_message` and the CLI already use.

The single most important structural move is **reuse, not addition**: extract the heterogeneous arg-adaptation ladder out of `on_message` into one shared `dispatch_spec(...)` function that *both* text commands and panel callbacks call. This makes command-set drift structurally impossible (the milestone's stated single-source-of-truth goal) and means a future 8th command appears as a panel button for free if buttons are derived from `registry.COMMANDS`. Do this refactor **first**, before any panel code can copy a dispatch ladder.

The risks are concentrated and well-understood, and they almost all stem from one fact: **the panel is an entirely NEW inbound code path that the v1.1/v1.2 safety machinery does not yet cover.** The v1.1 failure-isolation envelope and the operator guard were both written for `on_message`; component interactions never pass through it. The load-bearing work is therefore (1) re-porting the non-propagating try/except envelope to the new interaction-callback path; (2) moving the operator guard to `View.interaction_check` (component clicks bypass the `on_message` guard ladder); (3) getting persistent-view restart durability exactly right (`timeout=None` + static `custom_id`s + `add_view` in `setup_hook`); and (4) acking within Discord's 3-second window via defer-then-edit because the weather fetch is a real network call. The briefing spine stays untouched, and its isolation must be re-proven for the new path as an explicit milestone gate.

## Key Findings

### Recommended Stack

See [STACK.md](STACK.md). **Bottom line: nothing to install.** The entire component/view/persistence/edit stack is internal to the already-pinned `discord.py 2.7.1` (verified the current latest PyPI release as of 2026-06-23, so the existing pin is already at HEAD). The whole capability is present on the **bare `discord.Client`** the bot already uses — `commands.Bot` is **not** required (both `add_view` and `setup_hook` are inherited from `discord.Client` since 2.0). v1.3 is a code-only change inside the existing `interactive/bot.py` `BotThread`.

**Core technologies (all reused, none new):**
- **discord.py `>=2.7.1,<3`** (already pinned): `discord.ui.Button` / `discord.ui.Select` / `discord.ui.View`, persistent views (`View(timeout=None)` + static `custom_id` + `add_view` in `setup_hook`), and in-place edit (`interaction.response.edit_message` / `defer` -> `edit_original_response`). Already the inbound-gateway dependency since v1.1.
- **v1.2 `registry.COMMANDS`** (reused): single source of truth for the button grid — buttons are *derived from* it, never a parallel hardcoded list.
- **Existing `ForecastCache` + `lookup_*` + `render_embed`** (reused verbatim): off-loop read-only fetch and rendering, so panel output cannot drift from text/CLI output.
- **`operator_id` from pydantic-settings** (reused): the per-tap guard, now applied at the interaction layer.

**Explicitly do NOT:** add any package, bump/unpin discord.py, migrate prefix `on_message` -> slash/app commands (`tree.sync()`), switch to `commands.Bot`, add a gateway intent "for buttons," or build a new datastore "to remember the panel."

### Expected Features

See [FEATURES.md](FEATURES.md). This is a pure UI layer over the v1.2 registry — no new weather capabilities. The UX decisions (one pinned smart panel, in-place editing, location dropdown + button grid, Forecast sub-options, operator-only) are **locked** from milestone questioning; research validated the behaviors such a panel must have and the hard Discord constraints those decisions imply (5 action rows max; a select consumes a whole row -> 4 rows / 20 button-slots for commands; 3-second ack deadline; 15-minute post-ack window; persistent views require `timeout=None` + static `custom_id` + re-`add_view` on startup; Discord does NOT persist a select's chosen value server-side).

**Must have (table stakes / P1):**
- Location dropdown populated from configured locations (re-derived on hot-reload).
- One-tap command buttons (weather / uv / next-cloudy / sun / wind) dispatching through the registry.
- Argless commands (status / alerts) that ignore the dropdown.
- **Defer-then-edit fast ack + in-place rendering** — the single most important correctness behavior.
- **Operator-only guard on every interaction + ephemeral, leak-free reject.**
- **Persistent pinned panel that survives restart/deploy** — highest-risk table-stakes item.
- Forecast button -> Weekday/Weekend x Detailed/Compact sub-options (the one two-tier flow).

**Should have (polish / P2):**
- Summon/recreate command (`!panel`) — idempotent find-or-create.
- Visible selected-location indicator + sensible startup default.
- Emoji-coded labels + "updated <time>" stamp (disambiguates that an in-place edit happened).

**Defer (out of scope / already on v2 list):**
- Per-user / multi-user panels, config editing via the panel (violates locked boundaries).
- Arbitrary/geocoded location input via modal (CMD-V2-02); auto-refresh / live push (ENH-V2-03).
- A new datastore to persist the selected location across restart (cosmetic; default-on-restart instead).

### Architecture Approach

See [ARCHITECTURE.md](ARCHITECTURE.md). The panel is a NEW thin presentation surface that **reuses the EXISTING dispatch core** and introduces zero new fetch/render logic. The briefing spine (APScheduler, sent-log, `lookup.py`, `ConfigHolder`) stays untouched on the main thread; the panel runs inside the already-isolated `BotThread` on its own loop. Both `on_message` and the panel callbacks converge on **one shared `dispatch_spec(...)`** -> `cache.lookup` (off-loop) -> `spec.handler` -> `render_embed`.

**Major components:**
1. **`interactive/panel.py` (`PanelView`, NEW)** — the persistent `discord.ui.View`: location `Select`, command `Button` grid, Forecast sub-row; one `interaction_check` operator guard; in-memory selected-location state; per-callback isolation envelope.
2. **Shared `dispatch_spec(...)` (extracted from `on_message`, REFACTOR)** — maps `custom_id` -> `CommandSpec`, threads the selected location + flags, calls `spec.handler`. The single anti-drift move; both surfaces call it.
3. **`bot.py` `setup_hook` + `!panel` summon (MODIFIED)** — register the persistent View once via `client.add_view(...)`; add one branch to post + pin a fresh panel. No new `BotThread`/`daemon.py` constructor args (operator_id, holder, cache, daemon_state already flow in).
4. **Existing core (REUSED, unmodified)** — `registry.COMMANDS`, `ForecastCache`, `lookup_*`, `render_embed`.

### Critical Pitfalls

See [PITFALLS.md](PITFALLS.md). The four load-bearing risks (all stem from the panel being a NEW inbound path the v1.1 machinery doesn't cover):

1. **Isolation envelope bypass** — button/select callbacks do NOT pass through the `on_message` try/except. **Avoid:** wrap every callback body in the same non-propagating `try/except Exception` (log + best-effort ephemeral, never re-raise), add a `View.on_error` backstop, and re-prove the CMD-16 "raising handler never reaches the scheduler thread" test for the component path.
2. **Operator guard gap** — the `on_message` guard does NOT fire for component clicks, so anyone in the channel could drive the public pinned panel. **Avoid:** implement the guard in `View.interaction_check` (`return user.id == operator_id`); on False send a **silent ephemeral** reject that never echoes user/command. Keep an `interaction.user.bot` short-circuit.
3. **Persistent view not actually persistent after restart** (the v1.3 headline requirement) — four independent causes: missing `timeout=None`; missing/auto-generated `custom_id`; not calling `add_view` on startup (do it in `setup_hook`, NOT `on_ready` which re-fires on reconnect -> duplicates); `custom_id` > 100 chars. **Avoid:** `super().__init__(timeout=None)`, static centralized `custom_id` constants, `add_view` in `setup_hook`, an `is_persistent()` assertion, and a real `systemctl restart` + tap-all UAT on `yahir-mint`.
4. **3-second ack window** — a cache-miss OpenWeather fetch easily exceeds 3s, so computing the reply before acking shows "This interaction failed." **Avoid:** `interaction.response.defer()` first, run the fetch off-loop via `run_in_executor`, then `edit_original_response(...)`. Rule: cheap/instant change -> `response.edit_message`; anything that fetches -> `defer()` then `edit_original_response`. **Never** `defer()` + `response.edit_message()` (double-ack `InteractionResponded`).

Secondary but real: selected-location state lost across restart (render it into the message / default-on-restart; do NOT pack it into `custom_id`); component layout limits (assert <=5 rows / <=5 per row / <=25 options / id <=100 / label <=80 at build time); message-id loss + pin permissions (`Manage Messages`, `Embed Links`); stale/dead old panels (idempotent single-panel summon); the worst-case spine leak (callback must touch ONLY read-only registry + `ForecastCache` + `DaemonState`, never the scheduler or `holder.replace`).

## Implications for Roadmap

The architecture research supplies a dependency-ordered build sequence; the pitfalls research maps cleanly onto it. Suggested phase structure:

### Phase 1: Extract the shared dispatch path (`dispatch_spec`)
**Rationale:** Must come first — it makes command-set drift structurally impossible *before* any panel code can copy a dispatch ladder. Pure groundwork, behavior-preserving.
**Delivers:** `on_message`'s arg-adaptation ladder lifted into one shared async `dispatch_spec(spec, *, arg, holder, cache, daemon_state, loop) -> CommandReply` that `on_message` now calls; locked by the existing anti-drift / registry tests.
**Addresses:** the milestone's single-source-of-truth invariant.
**Avoids:** Pitfall — duplicated dispatch / command-set drift (the exact thing the registry exists to prevent).
**Uses:** existing `registry.COMMANDS`, `ForecastCache`, `command.py` flag helpers.

### Phase 2: Minimal persistent panel (core wiring)
**Rationale:** The bulk of the value (7 simple commands, tap-to-drive, in-place rendering) and where every load-bearing correctness behavior lives. Depends on Phase 1.
**Delivers:** `interactive/panel.py` `PanelView(timeout=None)` with the location `Select` + the 7 read-only command buttons (static `custom_id`s); `interaction_check` operator guard with ephemeral reject; per-callback non-propagating envelope + `View.on_error` backstop; defer-then-edit + off-loop fetch + in-place `edit_original_response`.
**Implements:** `PanelView` component; reuses `dispatch_spec` from Phase 1.
**Addresses:** FEATURES P1 — dropdown, one-tap buttons, argless handling, fast ack + in-place render, operator guard.
**Avoids:** Pitfalls 1 (isolation bypass), 2 (3s ack), 3 (double-ack), 5 (operator gap), 10 (intents — note "no new intent"), 9 (defer-then-edit promptness).

### Phase 3: Persistence + summon/lifecycle (restart durability)
**Rationale:** The v1.3 headline ("buttons survive restarts/deploys") — its own phase because durability of both the *listener* and the *state* needs a live restart UAT. Depends on Phase 2.
**Delivers:** `setup_hook` override on the existing `discord.Client` calling `add_view(PanelView(...))`; an idempotent `!panel` summon that find-or-creates + pins exactly one panel and deletes strays; selected-location default-on-restart behavior decided and documented; channel-permission check (`Manage Messages` / `Embed Links`) that CRITICAL-logs if missing. **Open design decision to resolve here:** whether to persist the pinned `message_id` (and selected location) durably vs. recreate-on-startup.
**Addresses:** FEATURES P1 persistence + P2 summon/recreate + selected-location indicator.
**Avoids:** Pitfalls 4 (persistence broken on restart), 6 (selected-location lost), 11 (message-id loss / pin perms), 12 (stale/dead old panels).
**Verification:** `systemctl restart weatherbot` on `yahir-mint`, then tap every button; select -> restart -> tap -> correct location; resummon leaves exactly one panel.

### Phase 4: Forecast two-tier sub-options
**Rationale:** The one layout-fiddly flow; deferred until the simple grid is proven so layout-limit pressure is handled deliberately. Depends on Phase 2 (ideally 3).
**Delivers:** the Forecast button + 4 Weekday/Weekend x Detailed/Compact sub-buttons (static sub-row), building `ForecastFlags(variant=..., location=...)` directly and routing through `dispatch_spec`; build-time layout assertion (<=5 rows / <=5 per row / ids <=100 / labels <=80).
**Addresses:** FEATURES P1 Forecast sub-options.
**Avoids:** Pitfall 7 (component limits / id collisions).

### Phase 5: Isolation hardening + polish
**Rationale:** Hardening that depends on everything else existing — the milestone's load-bearing isolation re-proof plus optional polish. Depends on 2–4.
**Delivers:** the explicit "a raising/hanging panel callback never stops or delays a concurrently-scheduled briefing" gate (mirror the Phase-15 raising-tick proof); optional re-derive Select options on the config-reload hook so renames track without restart; emoji labels + "updated <time>" stamp; confirm `render_embed` clip discipline covers the panel path.
**Addresses:** FEATURES P2 polish.
**Avoids:** Pitfall 8 (exception leaking onto the briefing spine).

### Phase Ordering Rationale

- **Refactor-first (Phase 1)** is mandatory: drift-prevention must exist before any panel callback could copy a dispatch ladder. This is the single most important reuse move.
- **Core before durability before layout** (2 -> 3 -> 4): the simple-command panel delivers most of the value and exercises every correctness behavior; restart-durability is verifiable only once a panel exists; the Forecast sub-row is the only layout-pressure item and is isolated last among feature work.
- **Isolation re-proof last (Phase 5)** because it asserts a property of the whole assembled panel against the live scheduler — but the per-callback envelope itself is built in Phase 2, not deferred.
- Every phase keeps the briefing spine untouched and re-verifies isolation; the panel only ever drives read-only paths.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Persistence/lifecycle):** the only genuinely open design decisions — *where/whether to persist the pinned `message_id` and the selected location across restart*, idempotent-summon strategy, and the exact channel-permission set (MEDIUM confidence on the precise perms). Worth a focused `--research-phase` pass or at least an explicit decision record.

Phases with standard, well-documented patterns (skip research-phase):
- **Phase 1 (dispatch extraction):** pure local refactor of code already read in full.
- **Phase 2 (core panel):** the persistent-view + defer-then-edit + `interaction_check` patterns are HIGH-confidence and documented against discord.py 2.7.1.
- **Phase 4 (Forecast sub-row):** standard two-tier component layout within known hard limits.
- **Phase 5 (isolation re-proof):** directly mirrors the existing Phase-15 isolation test.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new deps; every API verified present on bare `discord.Client` in the pinned `discord.py 2.7.1` (latest PyPI release, checked 2026-06-23) against official docs + the Rapptz persistent-view example + the repo's own `pyproject.toml`/`uv.lock`. |
| Features | HIGH | Discord component limits, the 3s/15min interaction windows, and persistent-view mechanics confirmed against discord.py docs/examples + Discord developer docs; per-user select-state non-persistence confirmed against upstream issue #7284. UX decisions are locked, not speculative. |
| Architecture | HIGH | Existing code (`bot.py`, `registry.py`, `lookup.py`, `cache.py`, `command.py`, `commands/`, `daemon.py`) read directly; integration points and the four-deps-already-flow-in claim verified against `daemon.py` BotThread construction; persistence API verified against official examples. |
| Pitfalls | HIGH | Every API fact verified against the discord.py API reference and the project's own `bot.py`; a few operational/UX points (exact pin permission set, some community ack discussions) tagged MEDIUM inline. |

**Overall confidence:** HIGH

### Gaps to Address

- **Persist `message_id` and/or selected-location vs. recreate-on-restart** — the one real open decision. Default leaning from research: persist `message_id` durably (small state file or a row in the existing SQLite store) for idempotent find-or-recreate; treat selected-location as in-memory best-effort with a sensible default-on-restart (don't build a datastore for a cosmetic nicety). Resolve explicitly in Phase 3 planning.
- **Exact channel permission set for pin/edit/embed** — MEDIUM confidence; verify `Manage Messages` (pin) + `Embed Links` / `Send Messages` against Discord channel-permission docs during Phase 3, and CRITICAL-log a missing perm rather than failing mid-operation.
- **`[bot]` settings read-once-at-startup tech debt** — confirm the panel's channel/operator binding sits on the right side of that boundary (changing them needs a restart, which is acceptable but should be documented), per the v1.1 known tech debt.

## Sources

### Primary (HIGH confidence)
- `/rapptz/discord.py` (Context7) + `examples/views/persistent.py` — `View(timeout=None)`, `@discord.ui.button(custom_id=...)`, `@discord.ui.select(options=...)`, `edit_message(view=...)`, `add_view` in `setup_hook`.
- https://discordpy.readthedocs.io/en/stable/api.html and .../interactions/api.html — `Client.add_view` / `Client.setup_hook` on bare `discord.Client` (New in 2.0); `View.is_persistent`/`interaction_check`/`on_error`; `InteractionResponse.defer`/`.edit_message`/`.send_message` (`InteractionResponded`); `Interaction.is_expired`; Select/Button/ActionRow limits.
- https://pypi.org/pypi/discord.py/json (checked 2026-06-23) — latest release `2.7.1`; existing pin is at HEAD.
- https://discord.com/developers/docs/interactions/receiving-and-responding — 3-second ack rule, 15-minute post-ack window.
- Repo source read directly — `weatherbot/interactive/bot.py` (BotThread isolation, `on_message` guard ladder + dispatch lines 270-337, `render_embed` clip discipline, intents + `on_ready` assertion), `registry.py`, `lookup.py`, `cache.py`, `command.py`, `commands/`, `scheduler/daemon.py` (BotThread start-after-READY + finally teardown), `pyproject.toml` / `uv.lock` (`discord.py>=2.7.1,<3`, resolved 2.7.1), `.planning/PROJECT.md` (locked v1.3 scope).
- https://github.com/Rapptz/discord.py/issues/7284 + Discord support — select selection state is client-side only, not persisted server-side.

### Secondary (MEDIUM confidence)
- https://apiscout.dev / community 2025-2026 comparisons (carried from prior stack research; not re-evaluated this milestone).
- https://discordjs.guide/slash-commands/response-methods + interactive-components guides — defer vs immediate reply timing; 5 rows x 5 units layout (same gateway interaction model as discord.py).
- https://github.com/Rapptz/discord.py/discussions/9865 — "This interaction failed" 3s-ack/defer + persistence discussion (corroborated by official API behavior).

### Tertiary (LOW confidence)
- Exact channel-permission set for pin/edit/embed — to be confirmed against Discord channel-permission docs during Phase 3 implementation.

---
*Research completed: 2026-06-23*
*Ready for roadmap: yes*
