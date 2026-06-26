# Phase 20: Isolation Hardening + Polish - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning

<domain>
## Phase Boundary

The assembled operator `PanelView` (Phases 17–19) gets its v1.3-closing hardening
and polish. Two independent threads of work:

1. **Isolation re-proof (PANEL-11)** — Re-prove the milestone's load-bearing
   failure-isolation guarantee for the new interaction-callback path: a panel
   callback that **raises or hangs** never delays, drops, or stops a
   concurrently-scheduled briefing. The raising case already has a seam
   (per-callback non-propagating `try/except` + `View.on_error` backstop) and a
   test (`test_callback_raise_isolated`); this phase adds the **hanging** case,
   re-proven against a **live scheduler** (mirroring the Phase-15 raising-tick
   proof).

2. **Panel polish (PANEL-12 / PANEL-13)** — A visible selected-location
   indicator, emoji-coded command-button labels, and an "updated `<time>`" stamp
   on rendered results so an in-place edit is visibly distinct from the prior one.

**In scope:**
- A visible selected-location indicator (embed line + dropdown highlight).
- Emoji on all command/forecast buttons (via discord.py `emoji=` param, text kept).
- A dynamic "Updated …" stamp in the result embed body.
- A live-scheduler isolation test for a **hanging** (await-shaped) callback +
  a one-time audit that the briefing path doesn't share the panel's default
  executor.

**Out of scope (deferred):**
- A defensive callback timeout/watchdog (gateway-loop responsiveness is not
  PANEL-11's guarantee — see D-08; candidate for v2 if panel *responsiveness*
  ever becomes a requirement).
- Grey-out command buttons until a location is selected (PANEL-V2-01).
- Per-user/multi-user state, config editing via panel, modals, auto-refresh,
  arbitrary-city lookup (milestone Out of Scope). No new commands or weather
  content — only polish on the existing surface.

</domain>

<decisions>
## Implementation Decisions

### Selected-location indicator (PANEL-12) — D-01–D-03
- **D-01 (authoritative indicator = embed line):** Render a `📍 {location}` line
  in the result embed, derived from `self._selected_location` **on every render**.
  This is the indicator of record: restart-safe by construction (it's computed
  from in-memory state at render time, already inside the existing
  `edit_original_response` path), costs **zero component slots** (critical — the
  panel is at 5/5 rows / full grid when the forecast sub-grid is revealed), and is
  unmissable. Chosen over a disabled "pill" button (rejected: no spare slot) and
  over relying on the dropdown alone (rejected: fragile, see D-02).
- **D-02 (dropdown highlight = cosmetic reinforcement, NOT source of truth):**
  ALSO mark the current location's `SelectOption(default=True)` so the dropdown
  control visibly highlights the active option. This is **decorative
  reinforcement only**. Hard constraints, because Discord/discord.py do not
  persist select state on their own:
  - Selection state lives **only** in `self._selected_location`; never read it
    back from `Select.values` (empty for default options until the operator
    actively changes the dropdown — discord.py #7284).
  - The correct `default=True` mark must be **re-applied from
    `self._selected_location` on every view rebuild** (each edit AND on restart /
    `add_view` reconstruction). Any render path that forgets silently reverts the
    dropdown to its bare `placeholder` — so the embed line (D-01) remains the
    guarantee; the dropdown highlight is best-effort.
- **D-03 (startup default already locked):** The startup default is
  `locations[0]` (home/first), already implemented (`panel.py:304-319`, mirrors
  `resolve_location(config, None)`). PANEL-12 only makes that selection
  **visible** — no change to the default-resolution logic.

### Emoji-coded labels (PANEL-13a) — D-04–D-05
- **D-04 (structure = `emoji=` param + keep text label):** Use discord.py's
  separate `emoji=<unicode>` Button param and **keep the existing Title-Case text
  labels** (the `_LABELS` dict at `panel.py:103-113`). The client renders icon +
  text with correct spacing; text preserves screen-reader naming and disambiguates
  the genuinely-confusable buttons. Chosen over emoji-baked-into-label-string
  (fights the API, inconsistent rendering) and over emoji-only (loses names /
  accessibility). Emoji-only stays a **narrow fallback** for just the 4 forecast
  sub-buttons IF real label truncation ever shows up on the operator's client —
  not adopted now.
- **D-05 (the emoji set — locked, "keep all"):**

  | Command | Emoji | Command | Emoji |
  |---|---|---|---|
  | weather | 🌡️ | status | 🟢 |
  | uv | 🧴 | alerts | ⚠️ |
  | next-cloudy | ☁️ | Forecast (toggle) | 📅 |
  | sun | ☀️ | Weekday Detailed / Compact | 📋 / 📝 |
  | wind | 💨 | Weekend Detailed / Compact | 🏖️ / 🌴 |

  Single-codepoint unicode glyphs (well-supported across Discord desktop/mobile).
  Deliberate disambiguation: ☁️/☀️ as a cloud↔sun pair; 🟢-status (steady-state
  health) vs ⚠️-alerts (exception signal) split by intent. User reviewed the
  flagged-debatable picks (weather/uv/status/weekend) and chose **keep all**.

### "Updated <time>" stamp (PANEL-13b) — D-06–D-07
- **D-06 (dynamic `<t:>` token in the embed body):** Add an
  `Updated <t:{unix}:t> (<t:{unix}:R>)` line to the result embed **description**,
  where `unix = int(discord.utils.utcnow().timestamp())` computed per render.
  This gives: an explicit "Updated" label; absolute clock time auto-rendered in
  the **operator's local tz and their own 12h/24h preference** (no hardcoded
  tz / no DST math); and a relative `:R` clause that Discord re-renders ~every
  minute, so the stamp visibly ages ("a few seconds ago" → "2 minutes ago") and
  **snaps back to "now" on each in-place edit** — satisfying "visibly distinct
  from the prior render." Chosen over a hardcoded static `Updated HH:MM` footer
  (manual tz/DST, no self-refresh) and over the native-timestamp-only status quo
  (correct but too subtle).
- **D-07 (keep native `embed.timestamp` too):** Leave the existing
  `embed.timestamp = discord.utils.utcnow()` (`bot.py:260`) in place — zero cost,
  redundant-but-harmless, and a second always-correct time signal in the footer.
  Note `<t:>` markdown works in description/field/footer-text but **not** in the
  embed title, so the stamp goes in the body, not the title.

### Hanging-callback isolation scope (PANEL-11) — D-08–D-09
- **D-08 (test-only thread-isolation proof — Option A):** Re-prove the guarantee
  with a **test/UAT that fires a real briefing while a panel callback hangs**, and
  asserts the briefing still fires on time. **No production change to the
  isolation path.** Rationale (the load-bearing fact): the briefing runs on
  APScheduler 3.x `BackgroundScheduler`'s own `ThreadPoolExecutor` on a separate
  OS thread, independent of the asyncio gateway loop. A hanging callback can take
  three shapes and only one could even touch the briefing:
  - an **infinite `await`** (e.g. `await asyncio.Event().wait()`) freezes only
    that coroutine — loop and all threads keep running → briefing untouched;
  - a **sync blocking call left on the loop** freezes the gateway loop but
    **releases the GIL** during I/O → briefing thread runs → briefing untouched;
  - only a **pure-CPU spin** holds the GIL and could *throttle* (not stop) the
    briefing — and a callback timeout can't interrupt that anyway (see D-09).
  PANEL-11's guarantee is explicitly about the **briefing**, not gateway-loop
  responsiveness, so this discharges it.
- **D-08a (test must hang via `await`):** The hanging-callback test MUST hang via
  a loop-yielding `await` (e.g. `await asyncio.Event().wait()`), the realistic
  callback shape since all blocking work is already pushed off-loop via
  `run_in_executor`. A pure-CPU `while True: pass` would be an unrealistic GIL-spin
  that proves something different — document this choice in the test.
- **D-08b (executor-sharing audit — the one real check):** As part of this phase,
  **verify** that the briefing path does NOT borrow the asyncio **default**
  executor that `dispatch.py` uses (`loop.run_in_executor(None, …)`,
  ~`dispatch.py:166-180`). APScheduler has its own pool, so this should come back
  clean — but confirming it closes the only genuine cross-thread coupling for
  free. If (unexpectedly) the audit finds real default-pool sharing, escalate:
  the dedicated-bounded-executor option (Option C) becomes warranted; otherwise
  ship the test alone.
- **D-09 (callback timeout/watchdog = OUT of scope, NOT a silent drop):** A
  defensive `asyncio.wait_for(callback, timeout=N)` is **deliberately not added**.
  It would self-heal a wedged *gateway loop* (panel responsiveness) but: (a) that
  is not PANEL-11's guarantee; (b) it adds a tunable foot-gun to the milestone's
  load-bearing isolation path the user is regression-averse about; and (c) it
  **cannot** interrupt the one hang (CPU spin) that could actually throttle the
  briefing, since cancellation only fires at an `await`. Recorded as a v2
  candidate IF panel responsiveness ever becomes an explicit requirement.

### Claude's Discretion
- Exact embed-render insertion points for the `📍 {location}` line and the
  `Updated <t:…>` line (title vs first description line vs author) — keep
  consistent with the existing `render_embed` structure in `bot.py:194-261`; the
  `<t:>` stamp MUST be in description/field/footer-text (never title).
- Whether the `📍` indicator and `Updated` stamp share one description block or
  separate lines; exact wording around them.
- The helper that re-applies `SelectOption(default=True)` from
  `_selected_location` on rebuild, and where it lives (keep `interactive/`
  import-acyclic).
- Test structure/placement for the hanging-callback live-scheduler proof
  (mirror the Phase-15 pattern and the existing `test_callback_raise_isolated`);
  whether the executor-sharing audit is a test assertion or a documented
  code-path verification.
- Whether emoji are applied via a parallel `_EMOJI` dict keyed like `_LABELS`, or
  inline at button construction.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **PANEL-11**, **PANEL-12**, **PANEL-13** (this
  phase's three requirements) + the Out of Scope table (single-operator boundary,
  no new commands/deps/intents). PANEL-V2-01 (grey-out buttons) is the v2 sibling.
- `.planning/ROADMAP.md` §"Phase 20" — goal + 4 success criteria; the Phase-15
  raising-tick-vs-live-scheduler proof it says to mirror for PANEL-11.

### The panel being hardened/polished (Phases 17–19)
- `weatherbot/interactive/panel.py` — the load-bearing file. Key landmarks:
  - `_LABELS` (lines 103-113) — add the parallel emoji mapping (D-04/D-05).
  - `CmdButton.__init__` (lines 164-251) — where `label=` is set; add `emoji=`.
  - `LocationSelect` (per-construction options from `holder.current().locations`)
    — add `SelectOption(default=True)` re-mark from `_selected_location` (D-02).
  - `PanelView.__init__` / `_selected_location = locations[0]` (lines 286-319) —
    the startup default (D-03), unchanged.
  - `on_command` / `on_select` / `on_forecast` + `_render_view` (lines 481-541,
    654-701) — the in-place render paths where the indicator line + `Updated`
    stamp + dropdown re-mark must be applied on EVERY render.
  - Per-callback `try/except` envelope + `View.on_error` (lines 481-541, 634-652)
    — the existing isolation seam PANEL-11 re-proves (the hanging path inherits it).
- `weatherbot/interactive/bot.py` — `render_embed(reply)` (lines 194-261), where
  `embed.timestamp = discord.utils.utcnow()` already lives (D-07); the natural
  home for the `📍` line (D-01) and the `Updated <t:…>` description line (D-06).
- `weatherbot/interactive/dispatch.py` — `dispatch_spec` and its
  `loop.run_in_executor(None, …)` off-loop fetch (~lines 166-180) — the **default**
  executor referenced by the D-08b audit.
- `weatherbot/config/loader.py` — `resolve_location(config, None)` returns
  `config.locations[0]` (lines 40-64); confirms the positional "home/first"
  default (D-03; no `is_home` flag exists — order is the contract).

### Isolation proof to mirror (PANEL-11)
- `tests/test_panel.py` — `test_callback_raise_isolated` (~lines 475-497), the
  existing raising-callback isolation test; extend the pattern for the hanging case.
- `tests/test_scheduler.py` / `tests/test_reliability.py` — the Phase-15
  live-scheduler raising-tick proof to mirror (fire a real job while a fault
  occurs; assert other jobs unaffected).

### Prior-phase context (the panel's correctness model)
- `.planning/phases/19-forecast-two-tier-sub-options/19-CONTEXT.md` — the
  single-ack defer-then-edit (D-14/D-15) + per-callback envelope + collapse-on-
  action model; explicitly defers PANEL-11/12/13 to here.
- `.planning/phases/18-persistence-summon-lifecycle-restart-durability/18-CONTEXT.md`
  + `18-PATTERNS.md` — persistent-view `add_view` registration and restart
  behavior the D-02 dropdown re-mark must survive.
- `.planning/phases/16-extract-shared-dispatch-spec/16-CONTEXT.md` — the
  one-shared-ladder dispatch design + `interactive/` import-acyclicity constraint.

### Tests that must stay green (anti-drift)
- `tests/test_dispatch.py`, `tests/test_bot.py`, `tests/test_command_views.py`,
  `tests/test_panel.py`, `tests/test_interactive_package.py` — the contractual
  reply suite. The polish additions (indicator line, emoji, stamp) change rendered
  output, so byte-identical embed snapshots WILL need updating — do so
  deliberately, confirming only the intended additions changed.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `render_embed(reply)` (`bot.py:194-261`) — single surface-agnostic embed
  builder; both the `📍` indicator line and the `Updated <t:…>` stamp belong here
  so panel/bot/CLI can't drift. Already sets `embed.timestamp = utcnow()` (D-07).
- `_LABELS` dict (`panel.py:103-113`) — clean keyed-by-command-name structure;
  mirror it with an emoji map (D-05) rather than scattering literals.
- `PanelView` machinery — single-ack defer-then-edit, per-callback non-propagating
  envelope + `View.on_error`, `_disabled_copy`, `_render_view` clone-swap are all
  reused; the hanging-callback path inherits the SAME envelope (PANEL-11).
- `test_callback_raise_isolated` (`tests/test_panel.py`) — direct template for the
  new hanging-callback isolation test.

### Established Patterns
- **One shared render path** — every surface renders via `render_embed`; the
  indicator + stamp must be added there, not per-surface.
- **All blocking work OFF the loop** via `run_in_executor` — already inside
  `dispatch_spec`; the isolation guarantee rests on this + the separate scheduler
  thread (D-08).
- **Selection state in `_selected_location`, never `Select.values`** — the
  Pitfall-3 rule from Phase 17/19 directly governs D-02's dropdown re-mark.
- **Build-time fail-loud layout assert** (`_assert_layout`) — no new component
  slots are added this phase (emoji/indicator/stamp are all non-component), so the
  5/5-row guard is untouched; confirm nothing new trips it.
- **`interactive/` modules import-acyclic** — keep any new helper light-import.

### Integration Points
- `render_embed` (`bot.py`) — gains the `📍 {location}` line + `Updated <t:…>`
  description line. (Needs the selected location passed through, or rendered from
  reply context — planner to wire the location into the embed-build call.)
- `LocationSelect` rebuild — gains a `default=True` re-mark from
  `_selected_location` on every view construction (D-02).
- Each `CmdButton` / forecast sub-button — gains an `emoji=` (D-04/D-05).
- A new test in `tests/test_panel.py` (hanging callback) + a live-scheduler
  assertion mirroring Phase 15; plus the D-08b executor-sharing audit.

</code_context>

<specifics>
## Specific Ideas

- The user is **regression-averse** (consistent with Phases 18–19): the
  isolation decision (D-08/D-09) deliberately adds **zero** production code to the
  load-bearing isolation path — a test-only proof + a free audit — rather than a
  callback-timeout that would touch that path for a guarantee PANEL-11 doesn't
  actually make. Surfaced and explicitly chosen over the more "defensive" options.
- The `<t:>` dynamic-timestamp choice (D-06) was picked specifically because it
  off-loads timezone/DST/12h-24h to each viewer's Discord client (the operator
  never hardcodes a tz) AND self-ages so an in-place edit visibly reads as fresh —
  a tighter fit to "visibly distinct" than a static string.
- The emoji set was reviewed against the researcher's flagged-debatable picks
  (weather 🌡️, uv 🧴, status 🟢, weekend 🏖️/🌴) and **kept as-is** ("keep all").

</specifics>

<deferred>
## Deferred Ideas

- **Defensive callback timeout/watchdog** (`asyncio.wait_for` around panel
  callbacks) — out of scope here (D-09); would protect gateway-loop
  *responsiveness*, not the briefing. v2 candidate IF panel responsiveness becomes
  an explicit requirement.
- **Dedicated bounded `ThreadPoolExecutor` for panel fetches** (Option C) — only
  warranted if the D-08b audit finds real default-pool sharing with the briefing
  path; expected to come back clean, so not planned.
- **Grey-out command buttons until a location is selected (PANEL-V2-01)** — v2;
  the D-03 default-location makes a no-location state unreachable anyway.
- **Emoji-only forecast sub-buttons** — held as a narrow fallback only if real
  label truncation appears on the operator's client (D-04); not adopted now.

None of these were scope creep into other domains — discussion stayed within the
Phase-20 polish + isolation boundary.

</deferred>

---

*Phase: 20-isolation-hardening-polish*
*Context gathered: 2026-06-26*
