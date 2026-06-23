# Pitfalls Research

**Domain:** Discord interactive components (buttons / string selects / persistent views with in-place editing) added to an existing long-running, restart-prone, single-operator, systemd-supervised discord.py gateway bot
**Researched:** 2026-06-23
**Confidence:** HIGH (every API fact below verified against the discord.py readthedocs API reference and the project's own `weatherbot/interactive/bot.py`; a few operational/UX points are MEDIUM and tagged inline)

> **Reading note for the roadmap.** This bot is NOT a `commands.Bot` / app-command bot. It is a bare `discord.Client` with a hand-written `on_message` guard ladder (see `weatherbot/interactive/bot.py`). That single fact shifts several "standard" pitfalls: there is no `commands.Bot.add_view` convenience, no automatic `setup_hook` wiring from a framework, and the existing failure-isolation envelope was written for `on_message`, NOT for view/interaction callbacks. The v1.3 panel introduces an **entirely new inbound code path** (`on_interaction` / view item callbacks) that the v1.1 isolation envelope does not currently cover. Pitfall 1 and Pitfall 8 below are the load-bearing ones for this project.

---

## Critical Pitfalls

### Pitfall 1: The interaction callback path bypasses the v1.1 `on_message` isolation envelope

**What goes wrong:**
The hard invariant from v1.1/v1.2 is that inbound-bot failures NEVER gate, delay, or stop a scheduled briefing. That guarantee is implemented in exactly two places: the `try/except Exception` wrapping the whole `on_message` body (`bot.py:270-337`) and the `BotThread._run` swallow (`bot.py:458-474`). **Button clicks and select changes do NOT arrive through `on_message`.** They arrive as `InteractionType.component` events dispatched to `View.interaction_check` → the item's callback (or, if you wire it manually, `Client.on_interaction`). None of that code is inside the existing `on_message` try/except. A panel callback that raises an unhandled exception is caught by discord.py's `View.on_error` (which by default just logs) — so it won't crash the process today — but any code you add *outside* a view callback (e.g. a raw `on_interaction` handler, or work you do on the briefing scheduler's thread/objects) can absolutely leak.

**Why it happens:**
Developers assume "the bot is already failure-isolated" and reuse that mental model for the new component path. But the isolation was scoped to one handler. The new path is structurally separate.

**How to avoid:**
- Treat every view item callback and any `on_interaction` handler as a NEW isolation boundary. Wrap each callback body in the same non-propagating `try/except Exception` pattern already proven in `on_message`, logging via `_log.exception` and replying with a generic message — never re-raising.
- Override `View.on_error` (and `Item` callbacks) explicitly rather than relying on the default, so the failure is logged in WeatherBot's structlog format and an operator gets a generic "something went wrong" edit instead of a silent dead button.
- Re-establish, as an explicit success criterion, the test that already exists for `on_message` ("a raising handler never propagates / never touches the scheduler thread", CMD-16) but for the component callback path: a button whose handler raises must not stop or delay a concurrently-scheduled briefing.

**Warning signs:**
A panel callback that touches anything other than the read-only command registry + `ForecastCache`; any `await`/call against the APScheduler `BackgroundScheduler` or `ConfigHolder.replace()` from a button; absence of a try/except inside a view callback.

**Phase to address:**
The phase that introduces the View/component callbacks (the core panel-wiring phase). It must port the isolation envelope before any interactive feature is considered "done."

---

### Pitfall 2: The 3-second ack window — "This interaction failed", and choosing `defer` vs `edit_message`

**What goes wrong:**
Discord invalidates the interaction token if you do not acknowledge within ~3 seconds, and the user sees a red "This interaction failed". This bot's command handlers do a network fetch (OpenWeather One Call) off-loop via `run_in_executor`. Even with the TTL cache, a cache-miss weather/forecast tap can easily exceed 3s (httpx round-trip + render). If the callback computes the reply *before* acknowledging, the window blows and the tap visibly fails.

**Why it happens:**
The reply is expensive (a real fetch). The naive structure is "do work, then `response.edit_message(...)`". `edit_message` is itself the acknowledgement, so it must complete within 3s — which a cold fetch won't.

**How to avoid:**
- **Acknowledge first, then work.** For an in-place panel edit, the correct shape is: `await interaction.response.defer()` (a component defer is `deferred_message_update` — it does NOT post a "thinking…" placeholder and does not change the message), then run the off-loop fetch, then `await interaction.edit_original_response(embed=..., view=...)` (or `interaction.message.edit(...)`) to render the result in place.
- Use `interaction.response.edit_message(...)` (the synchronous-ack edit) ONLY when the new content is already in hand and cheap (e.g. reflecting a select change, disabling a button, showing a sub-menu) — i.e. work that finishes well under 3s.
- Decision rule for the roadmap: **cheap/instant in-place change → `response.edit_message`; anything that does a fetch → `response.defer()` then `edit_original_response`.**
- Note the timing budget shrinks under load: the bot runs its event loop on its own thread; if the loop is briefly busy the effective window is < 3s. Defer early.

**Warning signs:**
"This interaction failed" on weather/forecast taps but not on instant ones; a callback that does `run_in_executor(... fetch ...)` *before* any `interaction.response.*` call.

**Phase to address:**
The panel-wiring phase (ack discipline is foundational), reinforced in the phase that wires the fetch-backed command buttons.

---

### Pitfall 3: Double-acking the same interaction (`InteractionResponded`)

**What goes wrong:**
Calling two of `response.send_message` / `response.defer` / `response.edit_message` on the same interaction raises `discord.InteractionResponded`. A very common shape here: `await interaction.response.defer()` then later `await interaction.response.edit_message(...)` — the second call is a re-ack and raises. (The correct post-defer edit is `interaction.edit_original_response(...)` or `interaction.message.edit(...)`, which go through the followup/REST path, not the response path.)

**Why it happens:**
`response.edit_message` and `edit_original_response` look interchangeable but live on different objects with different semantics (one acks, one is a followup). Mixing a defer with a second `response.*` call is the classic mistake.

**How to avoid:**
- Pick ONE ack per interaction. Patterns: (a) `response.edit_message(...)` alone (cheap, instant), or (b) `response.defer()` then `interaction.edit_original_response(...)` / `interaction.message.edit(...)` (fetch-backed). Never `defer()` + `response.edit_message()`.
- Guard error paths: in the callback's `except`, check `interaction.response.is_done()` before deciding whether to `response.send_message(..., ephemeral=True)` vs `followup.send(..., ephemeral=True)`. After a defer, the error reply MUST go through `followup`, not `response`.

**Warning signs:**
`InteractionResponded` in logs; an error reply that itself raises because the interaction was already acked.

**Phase to address:**
The panel-wiring phase, codified as a small helper (e.g. `respond_or_followup(interaction, ...)`) reused by every callback.

---

### Pitfall 4: Persistent view not actually persistent after restart — the four classic causes

**What goes wrong:**
After a `systemctl restart weatherbot` (deploys are frequent here — editable install + restart is the documented ops loop), every button/select on the pinned panel shows "This interaction failed" because the running process no longer knows the view exists. The pinned message still renders the components (Discord stored them), but nothing is listening for their `custom_id`s.

**Why it happens (four independent causes, all must be avoided):**
1. **No `timeout=None`.** A `View` defaults to a 180s timeout; after timeout it stops listening and (by definition) is not persistent. `View.is_persistent()` returns False unless `timeout is None` AND every component has an explicit `custom_id`.
2. **Missing/auto-generated `custom_id`.** If any component lacks an explicit `custom_id`, discord.py generates a random one per process start — so it can never match the `custom_id` baked into the already-pinned message. `add_view` will also raise `ValueError` ("view is not persistent") for such a view.
3. **Forgot to re-register on startup.** A persistent view only resumes listening if you call `client.add_view(MyPanel())` at startup. **For this bare `discord.Client`, the right place is `setup_hook` — `discord.Client` has `setup_hook` (confirmed in docs), so subclass `discord.Client` (or assign it) and call `add_view` there.** Do NOT call `add_view` in `on_ready` (which can fire multiple times on reconnect, re-registering duplicates) and do NOT rely on a `commands.Bot` helper that doesn't exist here.
4. **`custom_id` > 100 chars.** Discord's hard cap on `custom_id` is 100 characters. If you encode state (location id + command + variant + flags) into the id and it overflows, Discord silently rejects/truncates and the match fails after restart.

**How to avoid:**
- Subclass the view: `class WeatherPanelView(discord.ui.View): def __init__(self): super().__init__(timeout=None)`.
- Give every button/select a **static, deterministic** `custom_id` (e.g. `"wb:cmd:weather"`, `"wb:loc:select"`). Centralize them as named constants so they can't drift between the rendered panel and the registered view.
- In `setup_hook` (NOT `on_ready`), call `client.add_view(WeatherPanelView())`. Add an `is_persistent()` assertion (or a unit test) that fails loudly if a component ever loses its `custom_id` or the view loses `timeout=None`.
- Keep every `custom_id` short (well under 100). Do NOT pack mutable state (selected location) into the `custom_id` — keep ids static and hold selection in process state / the message itself (see Pitfall 6).
- Optionally pass the pinned `message_id` to `add_view(view, message_id=...)` so discord.py can refresh the view's state on message-update events.

**Warning signs:**
Buttons work until the first restart/deploy, then every tap fails; `ValueError: ... not persistent` at startup; `View.is_persistent()` returning False in a test.

**Phase to address:**
The persistence/durability phase (this is the v1.3 headline requirement: "buttons survive bot restarts"). It deserves its own phase or a hard success criterion with a restart-and-tap UAT on the live `yahir-mint` daemon.

---

### Pitfall 5: Operator guard gap — a PUBLIC pinned panel anyone in the channel can click

**What goes wrong:**
The panel is a pinned message visible to everyone in the channel; the buttons are clickable by anyone, not just the operator. The v1.1 guard ladder lives in `on_message` and checks `message.author.id != operator_id` — but **component interactions never pass through `on_message`**, so that guard does not apply. A non-operator click would execute a command unless a new guard is added on the interaction path. Worse, a naive rejection (e.g. `response.send_message("not allowed")` non-ephemeral, or echoing the user/id) leaks the panel's existence/behavior or operator info to the channel.

**Why it happens:**
The existing guard is on the message path; developers assume it covers all inbound events. It doesn't.

**How to avoid:**
- Implement the guard in `View.interaction_check(self, interaction) -> bool`: return `interaction.user.id == operator_id`. Returning False stops all child callbacks for that interaction — discord.py's built-in, intended mechanism for "only this user may use this view." (Confirmed: `interaction_check` is "useful... to ensure that the interaction author is a given user"; an exception inside it counts as failure and routes to `on_error`.)
- On a False check, send a **silent ephemeral** reject so nothing leaks to the channel: `await interaction.response.send_message("This panel is operator-only.", ephemeral=True)`. Ephemeral = visible only to the clicker. Do NOT echo the user's id/name, do NOT post publicly, do NOT reveal command names.
- Bake `operator_id` the same way the v1.1 bot does (construction-time; changing it is a restart boundary — consistent with the documented v1.1 behavior, no surprise).
- Defense in depth: keep an `interaction.user.bot` short-circuit too (mirrors the `author.bot` first rung of the existing ladder).

**Warning signs:**
Any callback that runs before an operator check; a reject that is non-ephemeral; a reject that names the user or the command.

**Phase to address:**
The panel-wiring phase, as a non-negotiable success criterion (operator-only enforced on EVERY interaction, reject is ephemeral and leak-free). Add a test that a non-operator id is rejected and no command handler runs.

---

### Pitfall 6: Selected-location state lost across restart (and across the panel's own lifecycle)

**What goes wrong:**
The panel model is "pick a location in the dropdown, then tap a command." If the selected location is held only in a Python instance attribute on the View, it is gone after any restart/deploy — and the pinned panel re-registered in `setup_hook` starts with no selection, so the next command tap has no location and either errors or silently uses the default. The operator's last selection silently resets on every deploy.

**Why it happens:**
Persistent views survive as *interaction listeners* but the *process* (and any in-memory state) does not survive restart. `add_view` re-creates a fresh View object with default state.

**How to avoid:**
- Treat the **panel message itself as the state store.** Render the currently-selected location into the message (e.g. the select's `default=True` option, and/or the embed title/footer "Showing: Home"). On startup, the operator can see and re-confirm; or read it back from the pinned message content if you need to recover the selection.
- Keep `custom_id`s static (Pitfall 4) and carry selection in the *message*, not the id.
- Decide and document the **default-on-restart behavior** explicitly: either (a) no selection → command buttons prompt "pick a location first" (ephemeral), or (b) fall back to a configured default location. Pick one; don't let it be accidental.
- The argless commands (`status`, `locations`, `help`, `alerts` per the registry) must work with NO selection — make sure the "no location selected" state doesn't block them.

**Warning signs:**
After a deploy, tapping a location command does the wrong city or errors; the dropdown shows no highlighted selection after restart.

**Phase to address:**
The persistence/durability phase (alongside Pitfall 4) — restart durability of *state*, not just of the listener. Verify with a "select → restart → tap → correct location" UAT.

---

### Pitfall 7: Component layout limits and label/`custom_id` collisions

**What goes wrong:**
Discord enforces hard structural limits; exceeding any of them makes the message send raise `HTTPException` (which, via the v1.1 generic-error pattern, would surface as "something went wrong" with no panel — bad during exactly the moment the operator wants the panel). Limits:
- **5 action rows** per message, **5 buttons per row** (max 25 buttons), but a **select menu occupies an entire row** (so a row with the location select holds nothing else).
- A select menu has **max 25 options** (`add_option` raises `ValueError` past 25).
- `custom_id` max **100 chars**; **button label max 80 chars**; select option **label/value/description max 100 chars each**.
- Duplicate `custom_id`s within one message are invalid — two buttons sharing an id is ambiguous and breaks dispatch.

The v1.3 command set is: weather, uv, next-cloudy, sun, wind, alerts, status, locations, help, plus a Forecast button that expands to Weekday/Weekend × Detailed/Compact (4 variants). With the location select taking one full row, that leaves 4 rows × 5 buttons = 20 button slots for ~9 commands + the forecast expansion — tight but feasible only if planned.

**Why it happens:**
The command set grows organically; the forecast sub-options (4 variants) plus 9 commands plus the select row quietly approach the 5-row ceiling. Long, human-readable `custom_id`s with packed state hit the 100-char cap.

**How to avoid:**
- Lay out the grid deliberately: row 0 = location select (full row); rows 1-4 = command buttons. Keep the **Forecast button as a single button that swaps the view to a sub-menu** (Weekday/Weekend × Detailed/Compact) rather than rendering all 4 variants inline — this keeps the main grid under budget and mirrors the text command's variant model.
- Generate the button grid **from the v1.2 command registry** (the stated single source of truth) and add a build-time assertion that the layout fits 5 rows / ≤5 per row — so adding a command can't silently overflow.
- Centralize `custom_id`s as constants; assert uniqueness within the view at construction; keep them short (`"wb:cmd:<name>"`). Clip/verify labels ≤80 and select option strings ≤100 at build time (the bot already has a `_clip` helper pattern for embed limits — reuse the discipline).
- If a future location count could exceed 25, the select needs pagination — but for a 2-location personal bot this is a non-issue; just assert `len(locations) <= 25` with a clear error.

**Warning signs:**
`HTTPException` on panel send/edit; `ValueError` from `add_option`; truncated/garbled labels; a button that triggers the wrong command (duplicate id).

**Phase to address:**
The panel-layout/build phase (the phase that turns the registry into the component grid). Make "layout fits Discord limits" a build-time-asserted success criterion.

---

### Pitfall 8: A panel exception leaking onto the briefing scheduler's thread/objects

**What goes wrong:**
This is the worst-case version of Pitfall 1 and the single biggest threat to the v1.1 isolation envelope. The bot runs on its OWN thread + event loop (`BotThread`). The briefing spine runs on APScheduler's `BackgroundScheduler` thread, reading config from a lock-guarded `ConfigHolder`. If a panel callback (a) calls into the scheduler (e.g. to "show next send time" by touching scheduler internals), (b) mutates shared config/state without the holder's lock, or (c) does long blocking work directly on the bot's event loop (blocking the heartbeat, which can cascade to reconnect storms), it can delay, corrupt, or destabilize the briefing path.

**Why it happens:**
The panel naturally wants to *show* live daemon state (the `status` command already reads `DaemonState`). It's tempting to reach into the scheduler or shared mutable state directly from a hot callback.

**How to avoid:**
- The panel must drive **only** the existing read-only command registry + `ForecastCache` + the read-only `DaemonState` accessor — exactly the surface `on_message` already uses. No new write paths, no scheduler mutation, no `holder.replace()` from a callback (the panel is explicitly a "pure UI layer, no new features").
- All blocking work (the fetch) stays OFF the bot event loop via `run_in_executor`, exactly as `on_message` does today — never `time.sleep`/blocking httpx directly in a callback.
- Read config via `holder.current()` (lock-free snapshot), never reach across to the scheduler's job store.
- Re-prove the v1.1 guarantee for the new path: a UAT/test where a button callback raises (or hangs) while a briefing is scheduled to fire, asserting the briefing still fires on time. This is the milestone's load-bearing isolation re-verification.

**Warning signs:**
Any import of / reference to the scheduler from the interactive layer beyond the read-only `DaemonState`; `holder.replace(...)` in a callback; blocking I/O without `run_in_executor`; missed/late briefings correlating with panel use.

**Phase to address:**
A dedicated isolation-verification gate at the end of the milestone (mirrors the UV-monitor "raising-tick-doesn't-stop-scheduler" proof in Phase 15). Also enforced as a code-review constraint in every panel phase.

---

### Pitfall 9: Interaction-token expiry (15 min) for any follow-up after a defer

**What goes wrong:**
After acknowledging an interaction, the interaction token is valid for **15 minutes** for follow-ups/edits. The initial ack must still be within 3s (Pitfall 2). For a panel that edits in place this is rarely hit — but it bites if you defer and then do something slow, or if you try to edit the original response long after the click (e.g. a delayed all-clear). After 15 min, `edit_original_response` / `followup.send` fail with a 404/`NotFound`.

**Why it happens:**
Developers conflate the 3s ack window with the 15-min followup window, or hold an interaction object intending to edit it much later.

**How to avoid:**
- Do all in-place edits promptly after the defer (the fetch is seconds, not minutes — fine).
- If you ever need to update the panel *outside* an interaction (not in v1.3 scope, but e.g. a future push), edit the **message by id** (`channel.get_partial_message(panel_message_id).edit(...)`), which uses the bot token and has no 15-min limit — don't rely on a stale interaction token.
- Use `interaction.is_expired()` to guard a late edit rather than letting it raise.

**Warning signs:**
`NotFound` (404) on `edit_original_response`/`followup` for slow paths; attempts to store an interaction for later use.

**Phase to address:**
The panel-wiring phase (defer-then-edit discipline). Low risk for v1.3 given fast fetches; document the message-id-edit fallback for any future out-of-band update.

---

### Pitfall 10: Gateway intents — `message_content` is for text commands, NOT for components

**What goes wrong:**
A subtle but real trap: component interactions arrive over the gateway as `INTERACTION_CREATE` and **do NOT require the privileged `message_content` intent** (the interaction payload carries the `custom_id` and values directly). The existing bot enables `guilds`, `guild_messages`, and the privileged `message_content` (with the `on_ready` assertion at `bot.py:368-375`) — those stay required for the v1.1 `!weather` text commands. The pitfall is two-sided: (a) assuming you need a NEW privileged intent for buttons (you don't), and (b) accidentally narrowing intents and breaking the text path. Also: to **post and pin** the panel and to **edit** it, the bot needs the right *permissions* (not intents) in the channel.

**Why it happens:**
Intents vs permissions confusion; assuming interactive components need more privileged access than message reading.

**How to avoid:**
- Keep the existing intents exactly as-is; do NOT add a new privileged intent for the panel. Reuse `discord.Client(intents=...)` from `build_client`.
- Keep the `on_ready` `message_content` assertion (it protects the still-present text path).
- Separately verify channel **permissions** (next pitfall).

**Warning signs:**
Adding new intents "to make buttons work"; the `message_content` assertion firing after a refactor (text path silently broken).

**Phase to address:**
The panel-wiring phase — explicitly note "no new intents required" so nobody adds one. Verification = text `!weather` still works after the panel ships.

---

### Pitfall 11: Editing / pinning the panel message — permissions and message-id loss

**What goes wrong:**
Two failure modes around the pinned message itself:
1. **Message-id loss.** The "single pinned panel that edits in place" requires knowing the panel's `message_id` to edit it out-of-band (and to pass to `add_view(message_id=...)`). If the id is held only in memory, a restart loses it; the bot can't find "its" panel and either edits the wrong message or posts a duplicate. Result: orphaned dead panels accumulate (Pitfall 12).
2. **Permission gaps.** Editing a message the bot authored needs nothing special, but **pinning** requires `Manage Messages`, and posting needs `Send Messages` / `Embed Links` in the channel. A missing permission makes the panel post/pin/edit raise `Forbidden` (403) at exactly the wrong moment.

**Why it happens:**
The panel is summonable but "meant to live pinned"; the lifecycle (where does the id live, who pins it, what perms are needed) is under-specified.

**How to avoid:**
- **Persist the panel `message_id`** (and channel id) durably — e.g. a small state file or a row in the existing SQLite store — written when the panel is created, read on startup. On startup, validate the message still exists (fetch it); if missing, recreate and re-pin; if present, just `add_view(view, message_id=...)`.
- Make the panel **idempotent on summon**: a `!panel` (or equivalent) summon should find-or-create the single panel, never spawn a second. De-pin/delete any previous panel it owns.
- Verify required channel permissions at startup (or on first summon) and log a clear CRITICAL if `Manage Messages` / `Embed Links` is missing, rather than failing silently mid-operation. (MEDIUM confidence on exact perm set — verify against Discord's channel-permission docs during implementation.)

**Warning signs:**
Duplicate panels after restart; `Forbidden` (403) on pin/edit; "panel disappeared" because the bot lost track of the id.

**Phase to address:**
The persistence/durability phase (message-id persistence sits with view persistence). Permission checks belong in the panel-summon/bootstrap phase.

---

### Pitfall 12: Stale / dead buttons on old panel messages

**What goes wrong:**
Each time the panel is re-summoned (or recreated after the bot lost the id), a NEW message with the same `custom_id`s is posted. Old panel messages still in the channel still show clickable buttons. Clicking an old one: discord.py dispatches by `custom_id` to the *registered* view, so it may "work" but edits the OLD message (confusing), or — if the operator expects in-place edit on the new one — produces split-brain. If the old message predates the current `custom_id` scheme, its buttons just fail.

**Why it happens:**
Non-idempotent summon (Pitfall 11) + persistent views matching by id regardless of which message hosts them.

**How to avoid:**
- Enforce **exactly one panel** (find-or-create + delete-old, Pitfall 11). The single-operator/single-channel model makes "delete the previous panel on summon" safe and simple.
- Because `custom_id`s are static and version-able, if you ever change the layout, **bump a version prefix** (`"wb:v2:cmd:weather"`) so old-message buttons cleanly stop matching (they'll show "This interaction failed", which is the correct signal for an abandoned panel) and delete the old panel.

**Warning signs:**
Multiple panels in the channel; clicking edits an unexpected message; intermittent "This interaction failed" on what looks like a valid button.

**Phase to address:**
The panel-summon/lifecycle phase (idempotent single-panel guarantee).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hold selected location only in a View instance attribute | Trivial to code | Silently resets every deploy (frequent here); wrong-city commands | Never — render selection into the message (Pitfall 6) |
| Pack state (location/command/flags) into `custom_id` | No external state store | 100-char cap overflow; ids not deterministic across restart; harder to keep unique | Never for mutable state; static ids only |
| Skip the per-callback try/except, lean on `View.on_error` default | Less boilerplate | Silent dead buttons; structlog gets nothing; isolation pattern not uniform | Never — port the v1.1 envelope (Pitfall 1) |
| `add_view` in `on_ready` instead of `setup_hook` | Looks like it works | `on_ready` re-fires on reconnect → duplicate registrations | Never — use `setup_hook` |
| Hand-build the button grid instead of generating from the registry | Faster first cut | Drifts from the real command set (the exact thing the registry was built to prevent) | Only a throwaway spike; production must generate from registry |
| Keep panel `message_id` in memory only | No persistence wiring | Duplicate/orphan panels after restart | Never — persist id (Pitfall 11) |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Discord interaction ack | `edit_message` after a cold fetch (>3s) | `defer()` first, then `edit_original_response` (Pitfall 2) |
| Discord interaction ack | `defer()` then `response.edit_message()` (double-ack) | `defer()` then `edit_original_response`/`message.edit` (Pitfall 3) |
| Persistent views | Forgetting `timeout=None` and/or static `custom_id`s | `super().__init__(timeout=None)` + explicit ids; assert `is_persistent()` (Pitfall 4) |
| Persistent views | Never calling `add_view` on startup | `client.add_view(...)` in `setup_hook` (`discord.Client` has it) (Pitfall 4) |
| Gateway intents | Adding a privileged intent "for buttons" | Components need NO extra intent; keep existing set (Pitfall 10) |
| Channel permissions | Assuming the bot can pin/embed | Verify `Manage Messages` (pin) + `Embed Links`/`Send Messages`; CRITICAL-log if missing (Pitfall 11) |
| APScheduler spine | Touching the scheduler/holder from a callback | Read-only registry + `DaemonState` + `holder.current()` only (Pitfall 8) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Blocking the bot event loop in a callback (sync httpx / `time.sleep`) | Gateway heartbeat misses → reconnects, "This interaction failed" cascades | All blocking work via `run_in_executor` (as `on_message` already does) | Even one slow callback under a single operator |
| Cold fetch inside the 3s ack window | Intermittent interaction failures on the first tap of the day | Defer before fetching; the TTL cache absorbs repeats | First tap after cache TTL expiry |
| Re-fetch per panel render of multi-call data | Burns OpenWeather quota | Reuse the shared `ForecastCache`; the panel is read-only over existing commands | Many rapid taps (still tiny for one user) |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| No operator guard on the component path (only on `on_message`) | Any channel member drives the bot via the pinned panel | `View.interaction_check` returns `user.id == operator_id` (Pitfall 5) |
| Non-ephemeral or info-leaking reject | Leaks panel/command existence, or operator id/name, to the channel | Ephemeral, generic reject; never echo user/command (Pitfall 5) |
| Token/URL in a callback error reply or log | Leaks the bot token or webhook URL | Reuse the v1.1 rule: generic reply, no secret ever in a log/message |
| Trusting `custom_id`/select values as safe input | Spoofed/odd values reach handlers | Validate values against the registry / configured location ids before dispatch |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Command tap with no location selected silently uses default | Operator gets the wrong city without realizing | Explicit "pick a location first" ephemeral, or a clearly-labeled default; argless commands exempt (Pitfall 6) |
| New-message spam instead of in-place edit | Channel clutter; defeats the "smart panel" goal | Edit the panel message in place (`edit_original_response`) |
| Dead buttons after restart with no signal | Operator thinks the bot is broken | Persistent views done right (Pitfall 4); recreate panel on startup if id is stale |
| Forecast variants rendered as 4+ inline buttons crowding the grid | Cluttered, near the 5-row limit | Single Forecast button → sub-menu view (Pitfall 7) |
| No "working…" feedback on a multi-second fetch | Operator double-taps, thinks it failed | `defer()` acks instantly (button stops spinning); optionally show a transient state in the embed |

## "Looks Done But Isn't" Checklist

- [ ] **Persistent view:** works in dev but never restarted — verify with an actual `systemctl restart weatherbot` then tap every button (live `yahir-mint` UAT).
- [ ] **Operator guard:** enforced in `on_message` but NOT in `interaction_check` — verify a non-operator id is rejected ephemerally and no handler runs.
- [ ] **Isolation envelope:** `on_message` is wrapped but the new view callbacks are not — verify a raising callback never stops/delays a scheduled briefing.
- [ ] **Ack discipline:** instant taps work but a cold-cache weather tap shows "This interaction failed" — verify with cache cleared.
- [ ] **Selected location across restart:** select Home, restart, tap weather — verify it still uses Home (or the documented default), not silently the wrong city.
- [ ] **Single panel:** summon twice / restart — verify exactly one live panel, no orphan dead panels.
- [ ] **Layout limits:** verify the generated grid asserts ≤5 rows / ≤5 buttons-per-row / ≤25 select options / ids ≤100 / labels ≤80 at build time.
- [ ] **Intents/permissions:** text `!weather` still works (intents unchanged) AND the bot can post+pin+edit (permissions present).

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Persistent view broken after restart | LOW | Add `timeout=None` + static ids + `add_view` in `setup_hook`; redeploy; resummon panel |
| Orphaned/duplicate panels | LOW | Make summon idempotent (find-or-create + delete old); manually unpin/delete strays once |
| Operator guard missing on components | LOW (but urgent) | Add `interaction_check`; ephemeral reject; redeploy immediately |
| Panel exception leaked toward scheduler | MEDIUM | Audit interactive layer for scheduler/holder writes; restore read-only-only surface; add isolation test |
| `custom_id` scheme change stranding old panels | LOW | Version-prefix ids; delete old panel; old buttons fail cleanly (expected) |
| Lost panel `message_id` | LOW | Persist id to SQLite/state file; on startup fetch-or-recreate |

## Pitfall-to-Phase Mapping

> Phase names are indicative; the roadmap will assign exact numbers. The grouping is what matters.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Callback bypasses isolation envelope | Panel-wiring (core) | Raising callback never propagates / never touches scheduler thread (port CMD-16 test) |
| 2. 3s ack window / defer-vs-edit | Panel-wiring (core) | Cold-cache weather tap succeeds (no "interaction failed") |
| 3. Double-ack (`InteractionResponded`) | Panel-wiring (core) | No `InteractionResponded` in logs; error path uses followup after defer |
| 4. Persistent view broken on restart | Persistence/durability | `systemctl restart` + tap-all UAT on `yahir-mint`; `is_persistent()` test |
| 5. Operator guard gap on components | Panel-wiring (core) | Non-operator rejected ephemerally; no handler runs |
| 6. Selected-location lost on restart | Persistence/durability | Select → restart → tap → correct location |
| 7. Component limits / id collisions | Panel-layout/build | Build-time assertions for rows/buttons/options/id-length/label-length/uniqueness |
| 8. Exception leaks onto briefing spine | Milestone isolation gate | Briefing fires on time while a callback raises/hangs (mirror Phase-15 proof) |
| 9. 15-min token expiry on followups | Panel-wiring (core) | Defer-then-edit happens promptly; message-id edit fallback documented |
| 10. Intents confusion | Panel-wiring (core) | Text `!weather` still works; no new privileged intent added |
| 11. Message-id loss / pin permissions | Persistence/durability + summon/bootstrap | id persisted + fetch-or-recreate on startup; perm check CRITICAL-logs |
| 12. Stale/dead old panels | Panel-summon/lifecycle | Idempotent single-panel; resummon/restart leaves exactly one |

## Sources

- discord.py API reference — `View.is_persistent`, `add_view` (raises `ValueError` if not persistent; optional `message_id`), `View.interaction_check`, `InteractionResponse.defer` / `.edit_message` / `.send_message` (all raise `InteractionResponded`), `Interaction.is_expired`, `SelectMenu`/`add_option` (max 25, `ValueError` beyond), `Button` (`custom_id` ≤100, label ≤80), `ActionRow` (≤5 children), `setup_hook` on `discord.Client`: https://discordpy.readthedocs.io/en/latest/interactions/api.html — HIGH
- discord.py FAQ — disabling items on timeout, persistent view patterns, `setup_hook` subclassing: https://github.com/rapptz/discord.py/blob/master/docs/faq.rst , https://github.com/rapptz/discord.py/blob/master/docs/migrating.rst — HIGH
- discord.py "This interaction failed" discussion (3s ack window, defer remedy, `timeout=None` + `custom_id` for restart-survival): https://github.com/Rapptz/discord.py/discussions/9865 ; basic interactions guide: https://gist.github.com/AkshuAgarwal/bc7d45bcecd5d29de4d6d7904e8b8bd8 — MEDIUM (community, corroborated by official API behavior above)
- Project source: `weatherbot/interactive/bot.py` (existing `on_message` guard ladder, non-propagating envelope, `BotThread` thread isolation, minimal intents + `on_ready` `message_content` assertion, embed limit `_clip`/`_split_body` discipline) — HIGH
- Project context: `.planning/PROJECT.md` (v1.3 goal, "pure UI layer / drives existing read-only commands", registry as single source of truth, operator-id guard expectation, frequent restart/deploy ops loop, briefing-spine isolation invariant) — HIGH

---
*Pitfalls research for: Discord interactive components on an existing single-operator gateway bot*
*Researched: 2026-06-23*
