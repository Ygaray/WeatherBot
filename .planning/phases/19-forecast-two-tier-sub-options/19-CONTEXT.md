# Phase 19: Forecast Two-Tier Sub-Options - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning

<domain>
## Phase Boundary

The persistent operator `PanelView` (Phases 17–18) gains a **Forecast** toggle
button that reveals a **2×2 grid of four forecast variant buttons** —
Weekday/Weekend × Detailed/Compact. Each variant button builds a
`ForecastFlags(variant=…, location=<in-memory selected location>)` **directly**
and routes through the same Phase-16 `dispatch_spec` seam as the text command —
so the panel mirrors `!weekday-forecast` / `!weekend-forecast` variants exactly,
with **no parallel forecast logic**. This is the milestone's one layout-pressure
flow, deliberately isolated after the simple grid (Phase 17) is proven, and it
lands the **complete** build-time layout assertion (the revealed panel is at
**5/5 rows** — full height — so the guard is now load-bearing).

**In scope (PANEL-07):**
- A `Forecast` toggle button on the base panel (row 2, next to `status`/`alerts`).
- Reveal/collapse of a four-button forecast sub-grid (rows 3–4).
- Four variant buttons → `dispatch_spec` via pre-built `ForecastFlags` for the
  currently selected location.
- A `flags=` extension to `dispatch_spec` (backward-compatible) so the panel
  passes flags directly instead of re-parsing an arg string.
- The complete build-time layout assertion + a dedicated unit test.

**Out of scope:** selected-location *visual indicator*, emoji-coded labels,
"updated <time>" stamp, and the briefing failure-isolation re-proof for the
interaction path (all **Phase 20**). Per-user/multi-user state, config editing
via panel, modals, auto-refresh, arbitrary-city forecast, new deps/intents
(milestone Out of Scope). No new forecast *content* or commands — only a new
surface onto the existing two forecast commands.
</domain>

<decisions>
## Implementation Decisions

### Variant → dispatch path (D-01)
- **D-01:** **Extend `dispatch_spec` with an optional pre-built `flags` param**
  (Option B). Signature becomes
  `dispatch_spec(spec, arg, *, cache, config, loop, daemon_state, flags=None)`.
  When `flags is not None`, `dispatch_spec` **skips** `parse_forecast_flags(arg)`
  and uses the passed flags directly: `lookup_name = flags.location`,
  `suffix = forecast_cache_suffix(spec.name, flags)`. The panel constructs
  `ForecastFlags(variant=<"detailed"|"compact">, location=self._selected_location)`
  with `add`/`drop` left **empty** (the command name `weekday-forecast` /
  `weekend-forecast` already encodes the day set; the panel adds no day deltas).
  Chosen over Option A (synthesize an arg string like `"Home --compact"` and let
  `dispatch_spec` reparse) because it matches the ROADMAP's "building a
  `ForecastFlags(...)` directly" wording and is immune to location names that
  contain flag-like tokens or leading `+`/`-`.
- **D-02 (HARD CONSTRAINT — byte-identical seam):** the `flags=` param is purely
  additive. **Every existing caller (`bot.on_message`, the panel's non-forecast
  buttons, and the CLI which doesn't use `dispatch_spec`) must keep
  `flags=None`**, so the `parse_forecast_flags(arg)` path is untouched and the
  contractual byte-identical reply suites stay green. Treat the seam change as a
  behavior-preserving extension, not a refactor of the existing parse path.

### Reveal model & collapse behavior (D-03–D-05)
- **D-03:** **Toggle disclosure that collapses after a result.** The base
  (collapsed) panel shows rows 0–2 only. Tapping **Forecast** reveals rows 3–4
  (the 2×2 grid). Tapping a forecast variant renders the result in place AND
  returns the view to the **collapsed** base.
- **D-04:** **Collapse on any action except the Forecast toggle itself.** Only
  the Forecast button shows the expanded view; every other interaction — a
  forecast variant tap, any other command button, and a dropdown change
  (`on_select`) — renders the **collapsed** base view. Re-tapping Forecast while
  expanded collapses it (a plain toggle). This keeps reveal state transient and
  the interaction model simple.
- **D-05 (restart behavior, ties to Phase 18):** after a restart the panel
  resolves to the **collapsed default**. Discord persists whatever components were
  last edited onto the message, so a panel that was revealed at restart may still
  *display* the sub-grid until the next interaction re-renders it collapsed —
  acceptable, because the sub-buttons' `custom_id`s are registered on the
  persistent view (see D-08) so taps still route, and the next action collapses.

### Sub-button layout & labels (D-06–D-07)
- **D-06:** **2×2 grid, explicit labels.** Row 3 = the weekday pair, row 4 = the
  weekend pair:
  - row 3: `Weekday Detailed` · `Weekday Compact`
  - row 4: `Weekend Detailed` · `Weekend Compact`
  Revealed state = **5/5 rows, 13/25 children** (full height). Plain text only —
  emoji-coded labels are Phase 20.
- **D-07:** The **Forecast** toggle button sits in **row 2** alongside
  `Status` / `Alerts` (3 buttons in row 2). A simple textual/caret state
  indicator on the toggle (e.g. collapsed vs expanded) is acceptable as a
  *functional* affordance and is **not** the Phase-20 emoji work — but it is
  Claude's discretion (see below); plain "Forecast" with the row appearing/
  disappearing as the affordance is also fine.

### Build-time layout assertion (D-08–D-09)
- **D-08:** **`__init__` assert + a dedicated unit test** (the "complete" guard
  criterion 3 asks for). Extend `_assert_layout` to validate the **full /
  revealed** panel, not just the base:
  - ≤ 5 rows (already present),
  - **≤ 5 per row** (currently only relied on `add_item` raising — assert it
    explicitly),
  - **≤ 25 children total** (currently unchecked — add it),
  - `custom_id` ≤ 100 and `label` ≤ 80 (already present).
  Add a dedicated test asserting the assembled/revealed panel fits, so "a future
  addition can't silently overflow" (criterion 3) is enforced in CI as well as at
  construction. **The panel is now at 5/5 rows — there is zero spare row;** any
  new component row must trip this guard.
- **D-09 (`_disabled_copy` / IN-03):** the existing IN-03 maintenance note is
  **already satisfied** if the forecast variant buttons and the Forecast toggle
  are `discord.ui.Button` subclasses — `_disabled_copy`'s existing
  `isinstance(child, discord.ui.Button)` branch rebuilds them (variant is
  irrelevant in the disabled ack because callbacks don't fire). No new branch is
  strictly required; the planner should **verify** this holds rather than treat it
  as a blocker. (If the toggle/sub-buttons are NOT plain Button subclasses, a new
  branch IS required.)

### Claude's Discretion
- Exact `custom_id` scheme for the forecast buttons and toggle (e.g.
  `wb:fc:weekday:detailed`, `wb:forecast:toggle` — all well under 100 chars).
- Whether the forecast variant buttons reuse a parameterized `CmdButton` or get a
  small dedicated button class carrying `(command_name, variant)`; the new panel
  method that builds the flags + dispatches + collapses (e.g. `on_forecast`);
  and the reveal/collapse helper that builds the expanded vs collapsed child set.
- Whether to show a caret/textual expand-collapse state on the Forecast label
  (functional affordance — NOT the Phase-20 emoji work).
- Exact module placement of any new helpers (keep `interactive/` import-acyclic).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **PANEL-07** (this phase's sole requirement) + the
  Out of Scope table (single-operator boundary, no new messages/deps/intents).
- `.planning/ROADMAP.md` §"Phase 19" — goal + 3 success criteria; §"Phase 20" for
  what is deliberately deferred (selection indicator, emoji labels, "updated"
  stamp, isolation re-proof).

### The shared dispatch seam (being extended — D-01/D-02)
- `weatherbot/interactive/dispatch.py` — `dispatch_spec` (extend with `flags=`;
  the forecast branch already does `parse_forecast_flags` + `forecast_cache_suffix`
  + off-loop `cache.lookup(name, config, suffix)`) and `dispatch_reply` (the
  `group == "Forecast"` branch calls `handler(result, flags)`). **Keep the
  `flags=None` parse path byte-identical (D-02).**
- `weatherbot/interactive/command.py` — `ForecastFlags` (frozen dataclass:
  `variant`, `add`, `drop`, `location`), `parse_forecast_flags`,
  `forecast_cache_suffix` (the panel builds the dataclass directly; do not
  re-stringify).
- `weatherbot/interactive/commands/forecast.py` — `weekday_forecast(result, flags)`
  / `weekend_forecast(result, flags)` handlers (the day set comes from the command
  name; `flags.add`/`drop` empty from the panel).

### The panel being extended (Phases 17–18)
- `weatherbot/interactive/panel.py` — `PanelView.__init__` (rows 0–2 today; rows
  3–4 reserved), `_assert_layout` (extend per D-08), `_disabled_copy` (IN-03 note,
  D-09), `on_command` (single-ack defer-then-edit + per-callback envelope to
  mirror for `on_forecast`), `on_select` (must collapse per D-04),
  `CmdButton`/`LocationSelect`, `_PANEL_MARKER`/`_is_owned_panel`.
- `weatherbot/interactive/registry.py` — `BY_NAME["weekday-forecast"]` /
  `["weekend-forecast"]` (the specs the forecast buttons resolve), `CommandSpec`
  (`group == "Forecast"`, `takes_location=True`).
- `.planning/phases/17-minimal-persistent-panel-core-wiring/17-CONTEXT.md` — D-10
  layout decision that reserved rows 3–4 + the minimal assertion this phase
  completes; the single-ack / envelope / operator-gate correctness model to mirror.
- `.planning/phases/18-persistence-summon-lifecycle-restart-durability/18-CONTEXT.md`
  + `18-PATTERNS.md` — persistent-view registration (`add_view` in `setup_hook`)
  and the default-on-restart behavior D-05 ties to.
- `.planning/phases/16-extract-shared-dispatch-spec/16-CONTEXT.md` +
  `16-PATTERNS.md` — the two-layer dispatch design ("one shared ladder, each
  surface keeps its own fetch/retry/render") and `interactive/` import-acyclicity.

### Tests that must stay green (anti-drift / byte-identical guards)
- `tests/test_dispatch.py`, `tests/test_bot.py`, `tests/test_registry.py`,
  `tests/test_command.py`, `tests/test_command_views.py`, and the panel test
  module(s) — the contractual suite proving registry-derived replies don't drift.
  The `flags=` extension must not change any `flags=None` reply (D-02).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dispatch_spec` / `dispatch_reply` (`interactive/dispatch.py`) — reused
  verbatim; only the additive `flags=` param is new. Off-loop fetch + suffix-keyed
  cache + whole-ladder-off-loop already handled.
- `ForecastFlags` + `forecast_cache_suffix` (`command.py`) — the panel builds the
  dataclass directly; the suffix keeps a forecast result from colliding with a
  plain `!weather` cache entry (A5).
- `render_embed(reply)` (`bot.py`) — turns the `CommandReply` into the in-place
  embed; panel/bot/CLI can't drift.
- `PanelView` machinery (`panel.py`) — single-ack defer-then-edit (D-14/D-15),
  per-callback non-propagating envelope + `View.on_error`, operator gate, and
  `_disabled_copy` are all reused; `on_forecast` mirrors `on_command`'s contract.

### Established Patterns
- **One shared ladder, no parallel logic** — every surface routes through
  `dispatch_spec`; the panel forecast path must too (criterion 2 / PANEL-10).
- **All blocking work OFF the loop** via `run_in_executor` — already inside
  `dispatch_spec`; `on_forecast` adds no on-loop I/O.
- **Single `interaction.response.*` per tap** — `edit_message` cue/ack +
  `_disabled_copy`, then result via `edit_original_response`; `on_forecast` follows
  the same single-ack contract.
- **Build-time fail-loud for caps discord.py accepts silently** (custom_id/label,
  and now total-children / per-row) — `_assert_layout` in `__init__`.
- **`interactive/` modules are import-acyclic** — module-top light imports, heavy
  types under `TYPE_CHECKING`.

### Integration Points
- `dispatch_spec` signature extension (`flags=`) — the single edit to the shared
  seam; all non-panel callers keep `flags=None`.
- New forecast buttons + Forecast toggle added to `PanelView` (rows 2–4), with
  static `wb:`-prefixed `custom_id`s so they are **registered on the persistent
  view** (`add_view`, Phase 18) and route after restart.
- `on_select` updated to collapse the reveal (D-04).

</code_context>

<specifics>
## Specific Ideas

- **2×2 grid chosen via visual mockups** — the weekday-row / weekend-row grouping
  read as the most scannable; the user explicitly compared rendered layouts and
  picked the full-height (5/5 rows) explicit-label grid over the single-row and
  detailed-implicit options. The explicit `Detailed`/`Compact` labels were
  preferred over bare `Weekday`/`Weekend` (no ambiguity).
- The ROADMAP's "building a `ForecastFlags(...)` directly" was taken at face value
  → the seam gets a `flags=` param (D-01) rather than a string round-trip.
- The user is regression-averse: the byte-identical `flags=None` constraint (D-02)
  and the assert-**and**-test layout guard (D-08) were both chosen to keep the
  existing surfaces provably unchanged while the panel grows.

</specifics>

<deferred>
## Deferred Ideas

- **Selected-location visual indicator, emoji-coded labels, "updated <time>"
  stamp** — Phase 20 polish. (A functional caret on the Forecast toggle is
  in-scope here as an affordance, but decorative emoji is Phase 20.)
- **Briefing failure-isolation re-proof for the interaction-callback path
  (PANEL-11)** — Phase 20; the per-callback envelope + `View.on_error` seam
  already exists, the new `on_forecast` path inherits it and will be re-proven
  there.
- **Grey-out command buttons until a location is selected (PANEL-V2-01)** — future
  release; the D-03 default-location makes a no-location state unreachable.
- **Arbitrary / geocoded `weather <any city>` via a modal text-input on the panel
  (CMD-V2-02)** — v2.0.

### Research flag (for `/gsd-yahir-batch-research` / plan-phase)
- **Persistent-view + reveal/collapse mechanics** — the one genuinely uncertain
  discord.py detail: how to render a base (collapsed) vs expanded message while a
  **single** registered persistent `PanelView` (one `add_view` instance) carries
  ALL forecast `custom_id`s so post-restart taps on a revealed panel still route.
  Confirm the standard pattern (one canonical view holding all children; reveal =
  `edit_message(view=<expanded child set>)`, collapse = `edit_message(view=<base
  child set>)`, both using already-registered custom_ids) against discord.py 2.7.1.

</deferred>

---

*Phase: 19-forecast-two-tier-sub-options*
*Context gathered: 2026-06-26*
