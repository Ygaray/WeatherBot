# Phase 17: Minimal Persistent Panel (Core Wiring) - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning

<domain>
## Phase Boundary

A tap-to-drive Discord control panel — a `PanelView` (`discord.ui.View`,
`timeout=None`, static `custom_id`s) carrying a location dropdown + read-only
command buttons — living inside the existing `BotThread`. A tap is acknowledged
within Discord's 3-second window, runs the off-loop fetch through the Phase-16
`dispatch_spec`, and renders the result **in-place** by editing the panel message
with components reattached. One `interaction_check` operator guard gates every
interaction; a per-callback non-propagating envelope plus a `View.on_error`
backstop keep any failure contained. This phase carries the load-bearing
interaction correctness.

**In scope (PANEL-02, -03, -04, -05, -06, -08):** dropdown populated from
configured locations (re-derived on hot-reload); location buttons
(weather/uv/next-cloudy/sun/wind) acting on the selected location; argless
buttons (status/alerts) ignoring it; defer/edit fast-ack; in-place render;
operator guard + leak-free reject.

**Out of scope:** persistence across restart + summon/lifecycle (Phase 18);
Forecast button + two-tier sub-options (Phase 19); briefing-isolation re-proof,
selected-location *visual indicator*, emoji labels, "updated <time>" stamp
(Phase 20). Per-user/multi-user state, config editing via panel, new
messages-per-result, modals, auto-refresh, new deps/intents (milestone Out of
Scope).
</domain>

<decisions>
## Implementation Decisions

### Selected location — held state & default (LOCKED by discord.py reality)
- **D-01:** Hold the currently-selected location as an **in-memory attribute on
  the single `PanelView` instance** (e.g. `self._selected_location`), set from
  `select.values[0]` in the dropdown callback and read in the location-button
  callbacks. This is the only viable mechanism — see D-02.
- **D-02:** Do **NOT** try to re-read the Select's `values` inside a button
  callback. A button interaction does not carry the dropdown's `values`, and
  discord.py bug #7284 means even a `default=True` option reports empty `values`
  until the operator *actively changes* the selection. Likewise do **not** encode
  selection in `custom_id` (breaks the persistent-view / static-`custom_id`
  contract).
- **D-03:** **Default-on-load = `config.locations[0].name`**, mirroring the
  existing `resolve_location(config, None)` semantics, so the first button tap
  *before any dropdown use* resolves to a valid location. Set in `__init__`.
- **D-04:** Argless buttons (status/alerts) pass `arg=None` to `dispatch_spec`
  and never read the held selection (PANEL-04).
- **D-05:** Restart amnesia (the held attribute is lost on process restart) is
  the *only* gap and is **explicitly deferred to Phase 18** — do not build a
  store for it here.

### Button set & layout
- **D-06:** **Curated name tuple** — an explicit, ordered tuple of the seven
  intended button names, each resolved to a `CommandSpec` via `registry.BY_NAME`
  with a **build-time `assert name in BY_NAME`** so a registry rename fails loud
  at construction. Chosen over a derive-from-`COMMANDS`-predicate approach to
  ship exactly Phase-17 scope with reviewable order and zero risk of a future
  spec leaking a button. (Predicate-derive was the runner-up; PANEL-10's
  "never drift" is preserved by the `BY_NAME` assert + the W2 decision below.)
- **D-07:** **`weather` becomes a real registry command (W2).** Add a
  `CommandSpec("weather", "Weather", ..., takes_location=True)` whose handler
  wraps the existing `lookup_weather` result into a `CommandReply`, so **every**
  panel button — including weather — routes uniformly through `dispatch_spec` →
  `render_embed`. No panel-side special-case for the bare-weather path.
- **D-08:** **W2 is NOT purely additive — treat the existing `!weather` command
  as a behavior-preserving refactor (HARD CONSTRAINT).** Because every surface
  derives from the registry, adding the `weather` spec means:
  (a) `weather` now appears in `!help` output and as a CLI subcommand, and
  (b) the existing `!weather [loc]` text path will (depending on how
  `parse_command` matches it) reroute through `dispatch_spec`/`render_embed`
  instead of today's `build_inbound_embed` path. The existing `!weather` reply
  MUST stay **byte-identical** (there are contractual anti-drift tests — keep
  them green). The planner must scope this rerouting as a deliberate
  behavior-preserving refactor with a byte-identical-reply guard, not a
  greenfield add. The new `weather` handler's `CommandReply` must render to the
  same embed fields as `build_inbound_embed` (Now / High·Low / Rain).
- **D-09:** **help / locations get no buttons** (PANEL-04 names only
  status/alerts as argless buttons); **weekday/weekend-forecast excluded**
  (Phase 19).
- **D-10:** **Proposed layout** (within Discord's 5-row × 5-per-row / ≤25-child
  hard cap): row 0 = location `Select` (occupies its own row), row 1 =
  `weather · uv · next-cloudy · sun · wind` (5 buttons), row 2 =
  `status · alerts` (2 buttons). Rows 3–4 left free for Phase 19 (forecast tier)
  / Phase 20 (polish). Add a **minimal build-time layout assertion now**
  (rows ≤ 5, ≤ 5 per row, each `custom_id` ≤ 100, each `label` ≤ 80) as a cheap
  `__init__` guard the Phase-19 full assertion can build on.

### Non-operator reject UX (PANEL-08)
- **D-11:** **Ephemeral, leak-free reply then block.** In `interaction_check`,
  on a non-operator tap: `await interaction.response.send_message(<generic>,
  ephemeral=True)` then `return False`. This acks the interaction (so the foreign
  user does NOT get the confusing client-side "This interaction failed" toast),
  is visible only to the tapper (so it physically cannot edit/clobber the shared
  pinned panel), and runs before any command handler.
- **D-12:** **Wording is generic and identity-free** — e.g. *"This panel is in
  use by someone else."* NEVER interpolate `interaction.user`, the `custom_id`,
  the command, or the operator's identity into the reply.
- **D-13:** **Log the rejected attempt server-side** (structlog `info`/`warning`
  with user_id / custom_id) — operator-side observability only, never echoed to
  the foreign user. Note: `View.on_error` fires only when `interaction_check`
  *raises*, NOT on a clean `return False`, so this log line is the sole audit
  record of a rejection — add it explicitly here.

### Slow-fetch in-progress feedback (PANEL-05 / -06)
- **D-14:** **Transient in-place edit + disable.** On tap (within the 3s window):
  `await interaction.response.edit_message(content="⏳ Fetching…",
  view=<disabled copy of the panel>)` BEFORE the fetch — this single
  `interaction.response.*` call simultaneously acks (PANEL-05), paints a visible
  "working" cue in-place with no new message (PANEL-06), and disables the
  components to neutralize double-taps. After the off-loop fetch returns, render
  via `await interaction.edit_original_response(content=None, embeds=[...],
  view=<re-enabled panel>)`.
- **D-15:** **Rationale for the transient cue:** a component `defer()` is
  `DEFERRED_UPDATE_MESSAGE`, which shows **no** spinner (unlike `on_message`'s
  `async with channel.typing()`), so a silent defer would leave the panel inert
  during a cold-cache 1–3s OpenWeather fetch and invite re-taps. Do **not** use
  `defer(thinking=True)` — it forces `DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE` and
  obligates a *separate* ephemeral followup, splitting result-rendering across
  two surfaces (rejected). The single permitted `interaction.response.*` call is
  spent on `edit_message`; the result therefore MUST land via
  `edit_original_response` (or `followup`), never a second `response.*` call.
  ("Disable-only, no transient text" is the acceptable lighter fallback if the
  transient-content bookkeeping proves troublesome — keeps the anti-double-tap
  guarantee.)

### Claude's Discretion
- Exact attribute/method names, the disabled-view construction helper, and where
  the `PanelView` class file lives (likely a new `interactive/panel.py` mirroring
  `bot.py`/`dispatch.py` module style).
- Whether the new `weather` handler lives in `commands/weather_views.py` (next to
  the sibling view handlers) or its own module — researcher/planner's call.
- Exact emoji-free button labels (emoji is Phase 20; pick clear text labels now).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — PANEL-02/-03/-04/-05/-06/-08 (this phase's
  requirements) + the Out of Scope table (single-operator boundary, no new
  messages, no new deps/intents).
- `.planning/ROADMAP.md` §"Phase 17" — goal + 5 success criteria; §"Phase 18/19/20"
  for what is deliberately deferred (persistence, forecast tier, polish).

### Phase-16 dispatch seam (the panel is its third caller)
- `weatherbot/interactive/dispatch.py` — `dispatch_spec(spec, arg, *, cache,
  config, loop, daemon_state)` (async off-loop wrapper) and `dispatch_reply`
  (sync ladder). The panel callback is `custom_id → spec`, `selected location →
  arg`. Returns a `CommandReply`.
- `.planning/phases/16-extract-shared-dispatch-spec/16-CONTEXT.md` — the
  two-layer design + the explicit "Phase 17 PanelView will be the third caller"
  hand-off note (keep "one shared ladder, each surface keeps its own
  fetch/retry/render" mental model intact).
- `.planning/phases/16-extract-shared-dispatch-spec/16-PATTERNS.md` — module
  style + the `interactive/` import-acyclicity discipline a new `panel.py`
  should follow.

### Existing interaction surfaces & registry (patterns to mirror / not regress)
- `weatherbot/interactive/bot.py` — `build_on_message` guard ladder (operator
  guard precedent, non-propagating envelope, off-loop fetch), `render_embed`
  (CommandReply → embed; reuse for the panel), `build_inbound_embed` (the
  current `!weather` embed shape the new weather spec MUST match byte-for-byte),
  `BotThread` (the thread the panel lives in).
- `weatherbot/interactive/registry.py` — `COMMANDS`, `BY_NAME`, `CommandSpec`;
  where the new `weather` spec (D-07) is added + `_wire_handlers` wiring.
- `weatherbot/interactive/command.py` — `parse_command` (how `!weather` currently
  resolves to `spec=None`; D-08 rerouting touches this), forecast-flag helpers.
- `weatherbot/config/loader.py` — `resolve_location(config, name)` (the
  default-on-`None` = `locations[0]` semantics D-03 mirrors).
- `weatherbot/config/holder.py` — `holder.current()` lock-free snapshot (how the
  dropdown re-derives its options on hot-reload, PANEL-02).

### Tests that must stay green (anti-drift / byte-identical guards)
- `tests/test_dispatch.py`, `tests/test_bot.py`, `tests/test_registry.py`,
  `tests/test_command.py`, `tests/test_command_views.py` — the contractual suite
  proving registry-derived replies don't drift. D-08's `weather` rerouting is
  verified against these.

### Failure isolation (re-proven fully in Phase 20, but seam starts here)
- `.planning/research/PITFALLS.md` — note that the `on_message` envelope does NOT
  cover panel taps; the panel needs its own per-callback envelope + `View.on_error`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dispatch_spec` / `dispatch_reply` (`interactive/dispatch.py`) — the panel
  reuses these verbatim for every button except (pre-W2) weather; with D-07
  (W2) weather routes through them too. Off-loop fetch + status-SQLite-off-loop
  already handled inside.
- `render_embed(reply)` (`bot.py`) — turns a `CommandReply` into a Discord embed;
  the panel renders results with the same function so panel/bot/CLI can't drift.
- `build_inbound_embed(forecast)` (`bot.py`) — the *reference* shape the new
  `weather` `CommandReply` must reproduce (Now / High·Low / Rain fields).
- `resolve_location(config, None) → locations[0]` — the default-selection
  precedent (D-03).
- `holder.current()` — lock-free config snapshot for dropdown option re-derivation
  on hot-reload (PANEL-02).

### Established Patterns
- **Guard order is load-bearing** (`on_message`): bot-author drop → operator
  check → prefix/parse. The panel's `interaction_check` is the operator gate;
  the bot-author drop is irrelevant (components can't be clicked by webhooks).
- **All blocking work OFF the loop** via `loop.run_in_executor` — already inside
  `dispatch_spec`; the panel must not add on-loop I/O.
- **Non-propagating envelope** — the bot wraps the whole handler so nothing
  reaches the scheduler thread. The panel needs the SAME discipline per callback
  (its own try/except) PLUS `View.on_error`, because the `on_message` envelope
  does not extend to component callbacks.
- **`interactive/` modules are import-acyclic** — module-top light imports, heavy
  types under `TYPE_CHECKING` (mirror `dispatch.py`/`cache.py` for a new
  `panel.py`).

### Integration Points
- A new `PanelView` (likely `interactive/panel.py`) instantiated with
  `holder` + `operator_id` + `cache` + `daemon_state` (same deps as
  `build_on_message`), registered on the client. Phase 18 makes it a persistent
  view via `add_view` in `setup_hook`; Phase 17 wires the callbacks + correctness.
- New `weather` `CommandSpec` + handler added to `registry.py` / `commands/`
  (D-07), with `parse_command`/`!weather` rerouting guarded byte-identical (D-08).
- The panel lives inside the existing `BotThread` / `build_client`; no new client,
  thread, or intent.
</code_context>

<specifics>
## Specific Ideas

- The user explicitly chose **W2** (real `weather` registry spec) over the
  lighter "reuse the existing path only on the panel" option — accepting that
  `weather` becomes a first-class, help/CLI-visible command for the sake of a
  fully uniform `dispatch_spec` routing. The flagged consequence (existing
  `!weather` text path reroutes; must stay byte-identical) was surfaced and
  accepted; it is captured as the hard constraint D-08, not a re-open.
- Transient feedback copy: a "⏳ Fetching…" in-place state (D-14) — the operator
  should always get a visible "working" cue, since the component defer shows no
  spinner. The user is design-conscious; the inert-panel footgun was the deciding
  factor.
- Reject wording should read as an intentional access decision, not a bug —
  generic "This panel is in use by someone else." (D-12).
</specifics>

<deferred>
## Deferred Ideas

- **Persist `message_id` / selected-location across restart** — Phase 18 (the
  milestone's one genuinely-open design decision). D-05's restart amnesia is its
  problem to solve.
- **Forecast button + Weekday/Weekend × Detailed/Compact sub-tier** — Phase 19
  (uses rows 3–4 the D-10 layout leaves free).
- **Selected-location visual indicator, emoji-coded labels, "updated <time>"
  stamp** — Phase 20 polish (D-10 reserves the label slot; pick plain text now).
- **Briefing failure-isolation re-proof for the interaction path (PANEL-11)** —
  Phase 20 (the per-callback envelope + `View.on_error` seam starts here, proven
  there).
- **Full component-layout build-time assertion** — Phase 19 lands the complete
  guard; D-10 adds only the minimal version now.
- **Grey-out buttons until a location is selected (PANEL-V2-01)** — future
  release; the D-03 sensible default makes a no-location state unreachable, so
  likely unnecessary.

</deferred>

---

*Phase: 17-minimal-persistent-panel-core-wiring*
*Context gathered: 2026-06-23*
