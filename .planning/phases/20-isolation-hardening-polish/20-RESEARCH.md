# Phase 20: Isolation Hardening + Polish - Research

**Researched:** 2026-06-26
**Domain:** discord.py 2.7.1 component polish (emoji/SelectOption/`<t:>` timestamps) + APScheduler 3.11.2 live-scheduler failure-isolation proof
**Confidence:** HIGH

> All decisions are pre-locked in `20-CONTEXT.md` (D-01..D-09). This research de-risks the
> PLAN — it confirms exact seams, API signatures, test patterns, and the anti-drift blast
> radius — it does **not** re-decide. Every API claim below is `[VERIFIED]` against the
> *installed* discord.py 2.7.1 / APScheduler 3.11.2 in this repo (not training data).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Selected-location indicator (PANEL-12) — D-01–D-03**
- **D-01:** Render a `📍 {location}` line in the result embed, derived from
  `self._selected_location` **on every render**. This is the indicator of record
  (restart-safe by construction, zero component slots). Chosen over a disabled pill
  button and over relying on the dropdown alone.
- **D-02:** ALSO mark the current location's `SelectOption(default=True)` so the dropdown
  highlights the active option — **decorative reinforcement only, NOT source of truth**.
  Hard constraints: selection lives ONLY in `self._selected_location`; never read back from
  `Select.values` (empty for default options until actively changed — discord.py #7284).
  The `default=True` mark MUST be **re-applied from `_selected_location` on every view
  rebuild** (each edit AND on restart / `add_view` reconstruction). The embed line (D-01)
  is the guarantee; the dropdown highlight is best-effort.
- **D-03:** Startup default is `locations[0]` (home/first), already implemented
  (`panel.py:319`). PANEL-12 only makes that selection **visible** — no change to
  default-resolution logic.

**Emoji-coded labels (PANEL-13a) — D-04–D-05**
- **D-04:** Use discord.py's separate `emoji=<unicode>` Button param and **keep the
  existing Title-Case text labels** (`_LABELS` at `panel.py:105-113`). Chosen over
  emoji-baked-into-label and over emoji-only. Emoji-only stays a narrow fallback for the 4
  forecast sub-buttons IF real truncation appears — not adopted now.
- **D-05 (the emoji set — locked, "keep all"):**

  | Command | Emoji | Command | Emoji |
  |---|---|---|---|
  | weather | 🌡️ | status | 🟢 |
  | uv | 🧴 | alerts | ⚠️ |
  | next-cloudy | ☁️ | Forecast (toggle) | 📅 |
  | sun | ☀️ | Weekday Detailed / Compact | 📋 / 📝 |
  | wind | 💨 | Weekend Detailed / Compact | 🏖️ / 🌴 |

**"Updated <time>" stamp (PANEL-13b) — D-06–D-07**
- **D-06:** Add an `Updated <t:{unix}:t> (<t:{unix}:R>)` line to the result embed
  **description**, `unix = int(discord.utils.utcnow().timestamp())` computed per render.
  The `:R` relative clause self-ages and snaps back to "now" on each in-place edit
  (satisfies "visibly distinct from the prior render").
- **D-07:** Keep the existing `embed.timestamp = discord.utils.utcnow()` (`bot.py:260`).
  Note: `<t:>` markdown works in description/field/footer-text but **NOT** in the embed
  title — the stamp goes in the body, never the title.

**Hanging-callback isolation scope (PANEL-11) — D-08–D-09**
- **D-08:** Re-prove the guarantee with a **test/UAT that fires a real briefing while a
  panel callback hangs**, asserting the briefing still fires on time. **No production
  change to the isolation path.**
- **D-08a:** The hanging-callback test MUST hang via a loop-yielding `await` (e.g.
  `await asyncio.Event().wait()`) — the realistic shape. A pure-CPU `while True: pass`
  would prove something different; document the choice in the test.
- **D-08b:** **Verify** the briefing path does NOT borrow the asyncio **default** executor
  that `dispatch.py` uses (`loop.run_in_executor(None, …)`). If the audit unexpectedly
  finds real default-pool sharing, escalate (Option C dedicated bounded executor);
  otherwise ship the test alone.
- **D-09:** A defensive `asyncio.wait_for(callback, timeout=N)` is **deliberately NOT
  added** — OUT of scope, not a silent drop. Recorded as a v2 candidate.

### Claude's Discretion
- Exact embed-render insertion points for the `📍` line and the `Updated <t:…>` line
  (title vs first description line vs author) — keep consistent with `render_embed`
  (`bot.py:194-261`); the `<t:>` stamp MUST be in description/field/footer-text (never title).
- Whether `📍` and `Updated` share one description block or separate lines; exact wording.
- The helper that re-applies `SelectOption(default=True)` from `_selected_location` on
  rebuild, and where it lives (keep `interactive/` import-acyclic).
- Test structure/placement for the hanging-callback live-scheduler proof (mirror the
  Phase-15 pattern + `test_callback_raise_isolated`); whether the executor-sharing audit
  is a test assertion or a documented code-path verification.
- Whether emoji are applied via a parallel `_EMOJI` dict keyed like `_LABELS`, or inline
  at button construction.

### Deferred Ideas (OUT OF SCOPE)
- Defensive callback timeout/watchdog (`asyncio.wait_for`) — D-09; v2 candidate.
- Dedicated bounded `ThreadPoolExecutor` for panel fetches (Option C) — only if D-08b
  finds real default-pool sharing (expected clean).
- Grey-out command buttons until a location is selected (PANEL-V2-01) — v2.
- Emoji-only forecast sub-buttons — narrow fallback only if truncation appears.
- **DO NOT** add a new component slot (grid is 5/5). **DO NOT** add a callback timeout.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PANEL-11 | A panel/interaction error never delays, drops, or stops a scheduled briefing (failure-isolation re-proven for the interaction-callback path) | The exact Phase-15 live-scheduler proof to mirror is `tests/test_scheduler.py::test_raising_uvmonitor_tick_never_stops_scheduler` (lines 1919-1989). The existing raising-callback isolation test to mirror is `tests/test_panel.py::test_callback_raise_isolated` (lines 475-497). The hanging shape is `await asyncio.Event().wait()` (D-08a). APScheduler 3.11.2 runs the briefing on its own `ThreadPoolExecutor` on a separate OS thread (independent of the asyncio gateway loop). D-08b audit target confirmed: `dispatch.py:166-188` uses `loop.run_in_executor(None, …)` (the asyncio **default** executor); the briefing spine never touches it. |
| PANEL-12 | Visible "selected location" indicator + sensible startup default (home/first) | `render_embed(reply)` at `bot.py:194-261` is the single render path — `📍 {location}` line goes in the description here (needs selected location threaded in — see Integration Points). `SelectOption(default=True)` verified in discord.py 2.7.1. Re-mark must be re-applied in `LocationSelect.__init__` AND every `_render_view` Select clone (panel.py:691-700). Startup default `locations[0]` already at `panel.py:319`. |
| PANEL-13 | Emoji-coded button labels + "updated <time>" stamp on results | `discord.ui.Button(emoji=…)` and `SelectOption(emoji=…)` both verified to accept a single unicode `str`. `<t:{unix}:t>`/`<t:{unix}:R>` is native Discord markdown; `discord.utils.utcnow().timestamp()` verified. Both additions land in `render_embed` description (D-06). |
</phase_requirements>

## Summary

This phase has two independent, low-risk threads over the assembled Phase-17–19 panel, and
every design decision is already locked in CONTEXT.md. The research goal was to confirm the
*exact* seams so the planner can write tasks without re-discovery.

**Thread 1 — PANEL-11 isolation re-proof (zero production change).** APScheduler 3.11.2's
`BackgroundScheduler` runs each briefing on its own `ThreadPoolExecutor` on a dedicated OS
thread, structurally independent of the discord.py asyncio gateway loop. A panel callback
that hangs via `await asyncio.Event().wait()` (the realistic shape — all blocking work is
already pushed off-loop via `run_in_executor`) freezes only that coroutine; the loop and all
threads keep running, so the briefing is untouched. The proof is a **test** that mirrors two
existing patterns exactly: the Phase-15 live-scheduler proof
(`test_raising_uvmonitor_tick_never_stops_scheduler`, which starts a *real*
`BackgroundScheduler`, fires a sentinel interval job alongside a faulting job, and asserts
the sentinel still fires + scheduler stays alive) and the existing raising-callback
isolation test (`test_callback_raise_isolated`). The one genuine check is D-08b: confirm the
briefing path never borrows the asyncio *default* executor that `dispatch.py` uses — and the
code already shows it does not (APScheduler has its own pool; the default executor is only
touched by the panel's read-only fetch path).

**Thread 2 — Polish (PANEL-12/13).** All three polish additions are confirmed against the
*installed* discord.py 2.7.1: `Button(emoji=Optional[Union[str, Emoji, PartialEmoji]])` and
`SelectOption(emoji=…, default=False)` both accept the locked unicode glyphs directly, and
`<t:{unix}:t>`/`<t:{unix}:R>` is native client-rendered markdown valid in an embed
description. All three render through the **single** `render_embed` path (`bot.py`) +
`LocationSelect`/clone construction — there is no per-surface duplication.

**The one subtle implementation trap** the planner must task explicitly: the `_render_view`
clone path (`panel.py:654-701`) rebuilds bare `discord.ui.Button(...)` and
`discord.ui.Select(...)` clones that today copy `label`/`custom_id`/`style`/`row` but **NOT**
`emoji` or `SelectOption(default=)`. Unless the clone path is updated to carry `emoji=` (on
every Button) and to re-apply the `default=True` mark (on the Select's options), the emoji
will **vanish on every disabled-ack and collapse render**, and the dropdown highlight will
silently revert — defeating PANEL-12/13a on the most common render paths.

**Primary recommendation:** Add a parallel `_EMOJI` dict mirroring `_LABELS`; thread the
selected location into `render_embed` for the `📍` line and add the `Updated <t:…>` line
there; add a small helper that builds `LocationSelect` options with the `default=True`
re-mark from `_selected_location`; and **update `_render_view` to copy `emoji` on Button
clones and re-apply the default mark on Select clones**. For PANEL-11, add one
hanging-callback test mirroring Phase-15 + a D-08b audit (test assertion recommended).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Failure isolation (briefing vs panel) | APScheduler thread (briefing) | asyncio gateway loop (panel) | The guarantee is that the briefing thread is independent of the loop a panel callback runs on. Proven at the scheduler boundary, not in panel code. |
| Selected-location indicator (embed line) | Render layer (`render_embed`, `bot.py`) | Panel state (`_selected_location`) | The line is computed from in-memory panel state at render time; the render layer owns its appearance so panel/bot/CLI can't drift. |
| Dropdown highlight (`default=True`) | Panel component layer (`LocationSelect`/clone) | — | Discord won't persist select state; the mark is re-derived from panel state on every (re)build. Purely a component-construction concern. |
| Emoji labels | Panel component layer (Button construction + clone) | — | `emoji=` is a per-button construction param; lives entirely in `panel.py`. |
| "Updated <time>" stamp | Render layer (`render_embed`) | Discord client (renders `<t:>`) | Server emits a unix token; the *operator's own Discord client* renders tz/12h-24h/relative-age. No server-side tz math. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | 2.7.1 (`>=2.7.1,<3`) | Component API (`Button.emoji`, `SelectOption.default/emoji`, `<t:>` markdown via `utils.utcnow`) | Already pinned; the whole milestone forbids a bump/new dep. All needed params exist in 2.7.1. `[VERIFIED: installed discord.__version__ == 2.7.1]` |
| APScheduler | 3.11.2 (`>=3.11.2,<4`) | The briefing scheduler whose thread-isolation PANEL-11 re-proves | Already pinned. `BackgroundScheduler` + own `ThreadPoolExecutor` on a separate OS thread is the load-bearing isolation fact (D-08). `[VERIFIED: uv.lock apscheduler 3.11.2]` |
| pytest | (repo dev dep) | The hanging-callback + D-08b audit tests | Existing suite; the Phase-15 live-scheduler test is plain pytest + `threading.Event` + `time.monotonic` polling. `[VERIFIED: tests/test_scheduler.py]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio (stdlib) | 3.12 | `asyncio.Event().wait()` for the hanging shape; `asyncio.run` to drive callbacks in tests | The hanging-callback test (D-08a). `[VERIFIED: stdlib]` |
| threading (stdlib) | 3.12 | `threading.Event` sentinels in the live-scheduler proof | Mirror the Phase-15 pattern exactly. `[VERIFIED: tests/test_scheduler.py:1930-1944]` |

**Installation:** None. **No new dependency is added or permitted this phase** (milestone
Out of Scope: "New gateway intent / new dependency / discord.py bump"). `[VERIFIED: REQUIREMENTS.md:66]`

**Version verification (run in this session):**
```
discord.__version__ == 2.7.1                         # installed, confirmed
apscheduler == 3.11.2                                 # uv.lock + pyproject >=3.11.2,<4
SelectOption.__init__(*, label, value=…, description=None,
    emoji: Optional[Union[str, Emoji, PartialEmoji]]=None, default: bool=False)
Button.__init__(*, style=…, label=None, disabled=False, custom_id=None,
    url=None, emoji: Optional[Union[str, Emoji, PartialEmoji]]=None, row=None, …)
discord.utils.utcnow() -> aware datetime (UTC)        # .timestamp() → float unix
```

## Package Legitimacy Audit

> No external packages are installed this phase (all deps already pinned and present).
> Audit not applicable.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                          ┌───────────────────────────────────────────┐
  Operator taps a button  │  discord.py asyncio GATEWAY LOOP (1 thread)│
  ───────────────────────▶│  PanelView.interaction_check (operator gate)│
                          │       │                                     │
                          │       ▼                                     │
                          │  on_command / on_forecast / on_select       │
                          │   ├─ ① response.edit_message (ack, <3s)      │
                          │   │     view = _render_view(disabled=True)   │◀── emoji/default
                          │   │                                          │    must survive
                          │   ├─ await dispatch_spec(...)                │    the clone!
                          │   │     └─ loop.run_in_executor(None, …) ────┼──▶ asyncio DEFAULT
                          │   │        (panel's read-only fetch)         │    ThreadPoolExecutor
                          │   └─ ② edit_original_response                │    (panel only)
                          │         embed = render_embed(reply) ─────────┼──▶ 📍 line + Updated <t:>
                          │   [per-callback try/except + View.on_error]  │
                          │   A hang here = await Event().wait():        │
                          │   freezes ONLY this coroutine.               │
                          └───────────────────────────────────────────┘
                                          ╎ (no shared executor — D-08b)
                          ┌───────────────────────────────────────────┐
  Cron fires 09:00 local  │  APScheduler BackgroundScheduler           │
  ───────────────────────▶│  OWN ThreadPoolExecutor (separate OS thread)│──▶ briefing sends
                          │  Independent of the gateway loop.           │    ON TIME regardless
                          └───────────────────────────────────────────┘    of any panel hang
```

The PANEL-11 guarantee is the vertical gap between the two boxes: a hang in the top box
never reaches the bottom box. The proof fires the bottom box (a real `BackgroundScheduler`
job) while the top box's callback hangs, and asserts the job still fires on time.

### Recommended Project Structure
No new files required. All changes land in existing modules:
```
weatherbot/interactive/
├── bot.py          # render_embed: + 📍 line, + Updated <t:> line (thread selected loc in)
├── panel.py        # _EMOJI dict; Button emoji=; LocationSelect default re-mark;
│                   #   _render_view clone must copy emoji + re-apply default
tests/
├── test_panel.py        # + hanging-callback isolation test (mirror test_callback_raise_isolated)
├── test_scheduler.py    # (mirror target: test_raising_uvmonitor_tick_never_stops_scheduler)
└── (anti-drift snapshot updates across test_bot/test_command_views/test_panel/test_interactive_package)
```

### Pattern 1: Live-scheduler isolation proof (mirror Phase-15 exactly)
**What:** Start a REAL `BackgroundScheduler`, register a sentinel interval job + the fault,
poll a `threading.Event` with a deadline, assert the sentinel fired and the scheduler stayed
alive. For PANEL-11 the "fault" is a panel callback hanging on `await asyncio.Event().wait()`
running on a *separate* asyncio loop/thread, while the briefing-shaped sentinel job runs on
the scheduler thread.
**When to use:** The PANEL-11 hanging-callback proof (D-08).
**Example (the exact pattern to mirror — `tests/test_scheduler.py:1919-1989`):**
```python
# Source: tests/test_scheduler.py::test_raising_uvmonitor_tick_never_stops_scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import threading, time

sentinel_fired = threading.Event()
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: sentinel_fired.set(),
                  trigger=IntervalTrigger(seconds=0.1), id="__sentinel__",
                  misfire_grace_time=None, coalesce=True)
scheduler.start()
try:
    # ... start a panel callback hanging on await asyncio.Event().wait()
    #     on its own loop/thread (it never returns) ...
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not sentinel_fired.is_set():
        time.sleep(0.05)
    assert sentinel_fired.is_set()       # the "briefing" fired despite the hang
    assert scheduler.running is True     # scheduler thread alive
finally:
    scheduler.shutdown(wait=False)
```
**Adaptation for the hang (D-08a):** the hanging callback must yield via `await` (e.g. run
`asyncio.run(view.on_command(hanging_interaction, "sun"))` in a daemon thread where the
stubbed handler does `await asyncio.Event().wait()`), NOT a CPU spin. Document in the
test docstring why `await`-shaped (realistic — all blocking work is already off-loop via
`run_in_executor`) and not `while True: pass`.

### Pattern 2: Single shared render path for the indicator + stamp (D-01/D-06)
**What:** The `📍 {location}` line and `Updated <t:…>` line both go into `render_embed`'s
embed **description** (the one surface-agnostic builder) so panel/bot/CLI cannot drift.
**When to use:** PANEL-12 embed line + PANEL-13b stamp.
**Example (the insertion point — `bot.py:215-261`):**
```python
# Source: weatherbot/interactive/bot.py:194-261 (render_embed)
embed = discord.Embed(title=_clip(reply.title, _MAX_TITLE), color=BRIEFING_COLOR_INT)
# ... existing field-building ...
embed.timestamp = discord.utils.utcnow()   # KEEP (D-07) — bot.py:260
return embed
```
The planner threads the selected location into the `render_embed` call (see Integration
Points) and builds a description like:
`f"📍 {selected_location}\nUpdated <t:{unix}:t> (<t:{unix}:R>)"` where
`unix = int(discord.utils.utcnow().timestamp())`. The `<t:>` token is **never** placed in the
title (D-07 — markdown does not render there). For argless commands (`status`/`alerts`) the
selected location is irrelevant — decide whether the `📍` line is suppressed or still shown
(Claude's Discretion; suppressing on argless replies is the cleaner read).

### Pattern 3: Emoji via a parallel `_EMOJI` dict (D-04/D-05)
**What:** Mirror `_LABELS` (`panel.py:105-113`) with an `_EMOJI` dict keyed by command name;
pass `emoji=_EMOJI[name]` alongside `label=_LABELS[name]` in `CmdButton.__init__`. Apply the
forecast-button and toggle emoji at their construction sites (panel.py:241-362).
**Example (verified param — installed discord.py 2.7.1):**
```python
# Button accepts a single unicode str directly:
discord.ui.Button(label="Weather", emoji="🌡️", custom_id="wb:cmd:weather", style=..., row=1)
# SelectOption likewise (if any per-option emoji ever wanted — not required by D-05):
discord.SelectOption(label=n, value=n, default=(n == self._selected_location))
```

### Anti-Patterns to Avoid
- **Dropping `emoji`/`default` in the `_render_view` clone (THE trap):** `_render_view`
  (`panel.py:681-700`) builds fresh `discord.ui.Button(label=…, custom_id=…, style=…,
  row=…, disabled=…)` and `discord.ui.Select(custom_id=…, placeholder=…, options=…, row=…,
  disabled=…)` — it does **NOT** copy `emoji` or re-apply `SelectOption(default=…)`. If left
  as-is, the disabled-ack and every collapse render strip the emoji and reset the dropdown
  highlight. The clone path MUST carry `emoji=child.emoji` on Button clones and rebuild the
  Select options with the `default=True` re-mark. `[VERIFIED: panel.py:681-700 — no emoji/default copied today]`
- **Reading `Select.values` for the indicator:** never. Selection state is only
  `_selected_location` (D-02, discord.py #7284). The `default=True` mark is *derived from*
  `_selected_location`, not from the Select. `[CITED: panel.py:260-275, 318-319]`
- **Putting `<t:>` in the embed title:** does not render (D-07). Body only.
- **Adding `asyncio.wait_for` around callbacks:** D-09 — out of scope, regression-averse.
- **Adding any component slot:** the grid is 5/5; `_assert_layout` will trip. The
  emoji/indicator/stamp are all non-component (D-08 in CONTEXT). `[VERIFIED: panel.py:364, 812-823]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Showing "updated HH:MM" in the operator's local tz | A hardcoded `strftime` + tz/DST math footer | `<t:{unix}:t> (<t:{unix}:R>)` markdown | Discord renders tz, 12h/24h, and the self-ageing relative clause client-side per viewer. Zero server tz logic, and `:R` snaps to "now" on each edit = "visibly distinct" for free (D-06). |
| Briefing-vs-panel thread isolation | A custom watchdog / bounded executor | APScheduler's own `ThreadPoolExecutor` (already there) | The scheduler already runs briefings on a separate OS thread independent of the gateway loop. Adding an executor or timeout is the rejected Option C / D-09. |
| Emoji+text composition on a button | Concatenating an emoji into the label string | `Button(emoji=…)` separate param | The client renders icon+text with correct spacing; baking into the label fights the API and renders inconsistently (D-04). |
| Persisting selected location across restart | A new datastore | Default-on-restart to `locations[0]` (already done) | Milestone Out of Scope; D-03 makes the selection *visible*, not persistent. |

**Key insight:** Every "feature" in this phase is a thin presentation/affordance over state
that already exists in memory or over a guarantee the scheduler already provides. The only
*new code on a hot path* is in `render_embed` and the `_render_view` clone — and the trap is
forgetting the clone, not building too much.

## Runtime State Inventory

> This is a polish + test phase, not a rename/migration. No stored data, service config, OS
> state, secrets, or build artifacts change.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the `📍`/`Updated` lines are render-time only; selection is in-memory (`_selected_location`), never persisted. Verified: REQUIREMENTS.md Out of Scope explicitly excludes persisting selection. | none |
| Live service config | None — no new intent, no new perms, no webhook/embed-perm change. Verified: REQUIREMENTS.md:66 (no new gateway intent/dep). | none |
| OS-registered state | None — no systemd unit change. (Deploy still needs `sudo systemctl restart weatherbot` because new Python code doesn't hot-reload — a deploy step, not a state change.) | restart on deploy (existing tech debt, MEMORY: weatherbot-live-systemd-service) |
| Secrets/env vars | None — no new secret or env var. | none |
| Build artifacts | None — no package rename, no new module. | none |

## Common Pitfalls

### Pitfall 1: The `_render_view` clone silently drops emoji and the dropdown default
**What goes wrong:** Emoji appear on the freshly-built `__init__` view but vanish the instant
the panel re-renders (every ack/collapse), and the dropdown highlight reverts to the bare
placeholder.
**Why it happens:** `_render_view` (`panel.py:681-700`) constructs *new* bare
`Button`/`Select` objects copying only `label/custom_id/style/row/disabled` and
`placeholder/options/row/disabled` — `emoji` and `SelectOption.default` are not propagated.
**How to avoid:** Update the clone to set `emoji=child.emoji` on each Button clone, and
rebuild the Select clone's options applying `default=(opt.value == self._selected_location)`
(or copy `opt.default` from a freshly re-marked source). Add a test asserting the cloned
view's emoji/default survive.
**Warning signs:** A test that builds the panel and checks `child.emoji` passes, but a test
that drives `on_command` and inspects the ack/result `view=` kwarg finds emoji `None`.

### Pitfall 2: Anti-drift snapshot tests compare embed *fields*, not description — but some compare against a reference embed
**What goes wrong:** Adding a `📍`/`Updated` description line could break embed-equality
assertions.
**Why it happens:** Several tests assert `[(f.name, f.value) for f in embed.fields] ==
list(reply.lines)` or `== build_inbound_embed(...).fields` (field-level), and one asserts
`got.fields == render_embed(canonical).fields`. The new lines go in the **description**, not
fields — so field-only comparisons stay green. BUT any test asserting full embed equality or
checking `embed.description` directly will need a deliberate update.
**How to avoid:** Run the suite; for each break confirm ONLY the intended description
addition changed, then update the snapshot. See the anti-drift inventory below.
**Warning signs:** `test_command_views.py:73,80`, `test_panel.py:462-467,806-809` reference
`build_inbound_embed`/`render_embed` — if `render_embed` now adds a description but the
reference path is the same `render_embed`, comparisons that use `render_embed(canonical)` as
the *expected* stay green automatically; comparisons against `build_inbound_embed` (which
will NOT have the new line) only stay green because they compare fields, not description.

### Pitfall 3: The hanging-callback test hanging the wrong way
**What goes wrong:** Using `while True: pass` (CPU spin) instead of `await
asyncio.Event().wait()`.
**Why it happens:** A CPU spin "feels" like a stronger hang, but it holds the GIL and proves
GIL-throttling behavior, not the realistic loop-yield hang (D-08a). All real panel blocking
work is already off-loop via `run_in_executor`, so the realistic wedge is an `await` that
never completes.
**How to avoid:** Hang via `await asyncio.Event().wait()` and document the choice in the test
docstring (D-08a explicitly requires this).
**Warning signs:** The test's hang thread pegs a CPU core; the docstring doesn't explain the
shape choice.

### Pitfall 4: Forgetting the D-08b audit, or making it brittle
**What goes wrong:** Shipping the hang test but never confirming the briefing path doesn't
share the asyncio default executor.
**Why it happens:** It "looks obviously fine."
**How to avoid:** Either a code-path verification documented in the test/plan (the briefing
runs under `BackgroundScheduler`'s own pool; `loop.run_in_executor(None, …)` at
`dispatch.py:166-188` is reached only from the panel's read-only fetch, never from the
scheduler job) OR a test assertion. **Recommendation:** a lightweight test assertion is
preferable — assert that the scheduler's executor and the asyncio default executor are
distinct objects (grep/inspect that no scheduler-job code path calls
`loop.run_in_executor(None, …)`). A code-path note alone is acceptable per Claude's
Discretion, but an assertion is cheap insurance against a future regression that wires a
briefing through the loop. `[VERIFIED: dispatch.py:166-188 default executor is panel-only]`

## Code Examples

### Re-marking the dropdown default from `_selected_location` (D-02)
```python
# Source: derived from panel.py:265-271 (LocationSelect) + D-02
options = [
    discord.SelectOption(label=n, value=n, default=(n == selected_location))
    for n in locations
]
# In _render_view's Select clone (panel.py:691-700), rebuild options the same way
# so the highlight survives the clone — do NOT pass list(child.options) blindly if
# the source options weren't re-marked.
```

### The `Updated` + `📍` description block (D-01/D-06)
```python
# Source: derived from bot.py:215 + D-01/D-06
unix = int(discord.utils.utcnow().timestamp())
desc_lines = []
if selected_location is not None:          # suppress on argless? (Claude's Discretion)
    desc_lines.append(f"📍 {selected_location}")
desc_lines.append(f"Updated <t:{unix}:t> (<t:{unix}:R>)")
embed = discord.Embed(
    title=_clip(reply.title, _MAX_TITLE),
    description="\n".join(desc_lines),     # NEVER the title (D-07)
    color=BRIEFING_COLOR_INT,
)
# ... existing add_field loop, then KEEP: embed.timestamp = discord.utils.utcnow()  # D-07
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `Updated HH:MM` footer with server-side tz | `<t:unix:t> (<t:unix:R>)` markdown rendered client-side | Discord timestamp markdown (stable for years) | No server tz/DST math; self-ageing relative clause (D-06). |
| Emoji baked into label string | `emoji=` separate param | discord.py 2.x | Correct icon+text spacing, screen-reader-friendly label retained (D-04). |

**Deprecated/outdated:** none relevant — discord.py 2.7.1 and APScheduler 3.11.2 are the
current pinned, supported lines (APScheduler 4.x is pre-release and explicitly avoided).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The locked D-05 emoji glyphs (🌡️ ☀️ ☁️ etc., some multi-codepoint/variation-selector) all render as Discord button icons on the operator's desktop+mobile client. The `emoji=` param *accepts* them (verified by signature), but rendering is a client behavior not verifiable without the live gateway. | Standard Stack / D-05 | A glyph renders as a tofu box or wrong icon on the operator's client. Mitigation: this is exactly the Gate-1 self-UAT / Gate-2 human-UAT item — confirm on the live panel after deploy. Low risk (D-05 deliberately chose well-supported glyphs). |
| A2 | `<t:{unix}:R>` re-renders (self-ages) ~every minute and snaps to "now" on edit. Verified as documented Discord behavior; not re-confirmed live this session. | D-06 | The "visibly distinct on edit" criterion is weaker than expected. Mitigation: the absolute `:t` clause + `embed.timestamp` (D-07) still change; verify in self-UAT. |

## Open Questions

1. **Should the `📍` line appear on argless (`status`/`alerts`) replies?**
   - What we know: argless commands ignore the selected location (D-04); showing `📍 {loc}`
     on a `status` reply could read as "status for {loc}" which is misleading.
   - What's unclear: CONTEXT leaves wording/placement to Claude's Discretion.
   - Recommendation: suppress the `📍` line on argless replies (thread `None` for the
     location), keep the `Updated` stamp on all replies. The planner decides; flag in the
     plan so it's a conscious choice.

2. **D-08b audit: test assertion vs documented code-path note?**
   - What we know: Claude's Discretion (CONTEXT D-08b / Discretion list).
   - What's unclear: nothing blocking.
   - Recommendation: a lightweight test assertion (see Pitfall 4) — cheap regression
     insurance — with a code-path note in the test docstring.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| discord.py | All polish + emoji/SelectOption/`<t:>` | ✓ | 2.7.1 | — |
| APScheduler | PANEL-11 live-scheduler proof | ✓ | 3.11.2 | — |
| pytest + asyncio + threading | Both test threads | ✓ | repo / stdlib | — |
| Live Discord gateway (operator's client) | A1/A2 emoji + `<t:>` visual confirmation | ✗ (host `yahir-mint`, deferred) | — | Gate-2 human-UAT after deploy+restart (per project Two-Gate policy) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** Live visual confirmation of emoji rendering and
`<t:>` aging (A1/A2) is a deferred Gate-2 human-UAT item — the *mechanism* (param accepted,
token emitted) is fully verifiable in automated tests; only the pixel-level render is human.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (repo standard; `asyncio.run` to drive callbacks, no live gateway) |
| Config file | `pyproject.toml` (existing pytest config) |
| Quick run command | `uv run pytest tests/test_panel.py -x` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PANEL-11 | A hanging (`await`-shaped) panel callback never delays/drops/stops a concurrently-scheduled briefing — fired against a **live** `BackgroundScheduler`; assert the sentinel "briefing" still fires on time + scheduler stays alive | integration (live scheduler) | `uv run pytest tests/test_panel.py -k hang -x` (new test) | ❌ Wave 0 (mirror `test_scheduler.py::test_raising_uvmonitor_tick_never_stops_scheduler` + `test_panel.py::test_callback_raise_isolated`) |
| PANEL-11 (D-08b) | The briefing path does not borrow the asyncio default executor (`loop.run_in_executor(None,…)` is panel-only) | unit/audit | `uv run pytest tests/test_panel.py -k executor -x` (new assertion) | ❌ Wave 0 |
| PANEL-12 | The result embed carries a `📍 {selected_location}` description line derived from `_selected_location` on every render path (ack, result, collapse, error) | unit | `uv run pytest tests/test_panel.py -k indicator -x` | ❌ Wave 0 |
| PANEL-12 | The dropdown marks `SelectOption(default=True)` for the selected location on `__init__` AND after a `_render_view` clone | unit | `uv run pytest tests/test_panel.py -k default_mark -x` | ❌ Wave 0 |
| PANEL-12 | Startup default is `locations[0]` (already proven) | unit | `uv run pytest tests/test_panel.py -k defaults_location` | ✅ (`test_freshly_built_view_is_persistent_and_defaults_location`) |
| PANEL-13a | Each command/forecast/toggle button carries the locked D-05 `emoji=`, and the emoji **survives `_render_view` cloning** | unit | `uv run pytest tests/test_panel.py -k emoji -x` | ❌ Wave 0 |
| PANEL-13b | The result embed description carries `Updated <t:{unix}:t> (<t:{unix}:R>)`; `embed.timestamp` retained (D-07) | unit | `uv run pytest tests/test_panel.py -k updated_stamp -x` | ❌ Wave 0 |

### Observable-signal mapping (Nyquist — what proves each success criterion)
- **SC#1 (isolation):** observable = the sentinel `BackgroundScheduler` job's
  `threading.Event` is set within the deadline while a panel callback is provably hanging on
  `await asyncio.Event().wait()` on a separate loop/thread; AND `scheduler.running is True`.
  Sampling: one live-scheduler integration test (sub-second interval, 5s deadline poll —
  mirrors Phase-15's timing). This is the *timing* assertion — the "on time" is proven by the
  job firing within its interval despite the concurrent hang.
- **SC#2 (indicator):** observable = `render_embed` output `.description` contains
  `📍 {location}`; AND every panel render path (`on_command` ack + result, `on_select`,
  `on_forecast`, error edit) passes the correct location through. Sample by asserting the
  `view=`/`embed=` kwargs on the `AsyncMock` interaction across each callback.
- **SC#3 (emoji):** observable = each button's `.emoji` equals the D-05 glyph in the built
  view AND in the `_render_view` clone captured from an ack/result `view=` kwarg.
- **SC#4 ("updated" stamp distinct):** observable = description contains a `<t:` token with
  a per-render unix value; the `:R` clause + `embed.timestamp` differ between two successive
  renders (the unix advances). Pixel-level "ages visibly" is the Gate-2 human-UAT clause.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_panel.py -x`
- **Per wave merge:** `uv run pytest -q` (full suite — catches the anti-drift snapshot breaks)
- **Phase gate:** full suite green + a Gate-1 agent self-UAT log (drive the panel; confirm
  emoji render, `📍` line, ageing stamp, and a live-scheduler isolation observation) before
  `/gsd-verify-work`. Per project Two-Gate policy, live on-device emoji/`<t:>` rendering on
  host `yahir-mint` is a deferred Gate-2 human-UAT obligation (deploy + `sudo systemctl
  restart weatherbot`), NOT a per-phase blocker.

### Wave 0 Gaps
- [ ] `tests/test_panel.py::test_hanging_callback_never_stops_live_briefing` — PANEL-11
      (mirror `test_scheduler.py:1919` + `test_panel.py:475`); hang via `await
      asyncio.Event().wait()` (D-08a), fire a real `BackgroundScheduler` sentinel job.
- [ ] `tests/test_panel.py::test_briefing_path_not_on_default_executor` — PANEL-11 D-08b audit.
- [ ] `tests/test_panel.py::test_*_indicator_line` — PANEL-12 embed `📍` line on each render path.
- [ ] `tests/test_panel.py::test_dropdown_default_marked` + clone-survival — PANEL-12 D-02.
- [ ] `tests/test_panel.py::test_buttons_carry_emoji` + clone-survival — PANEL-13a D-05.
- [ ] `tests/test_panel.py::test_updated_stamp_in_description` — PANEL-13b D-06.
- [ ] Anti-drift snapshot updates (see inventory below) — confirm ONLY intended additions changed.

### Anti-Drift Snapshot Inventory (tests that render/compare embeds or options)
| Test | What it asserts | Expected impact of this phase |
|------|-----------------|-------------------------------|
| `tests/test_command_views.py:73,80` | `reply.title == embed.title`; `embed.fields == reply.lines` | **Green** — additions are description-level, not fields/title. Confirm. |
| `tests/test_panel.py:462-467` | panel weather `embed.fields`/`title` == `build_inbound_embed` reference | **Likely green** (field/title only) — but `build_inbound_embed` won't have the `📍`/`Updated` line; if any assert compares `description`, update. |
| `tests/test_panel.py:806-809` | panel forecast `embed.fields`/`title` == `render_embed(canonical)` | **Green** — expected is `render_embed` itself, so both sides gain the line. |
| `tests/test_panel.py:181-204` | `select.options` values | **Update** — options now carry `default=` marks; if asserting option *equality* beyond `.value`, refresh. Value list unaffected. |
| `tests/test_bot.py:733-768` | `render_embed` field/title bounding (WR-02/03) | **Likely green** (fields only); confirm the new description doesn't break the bound checks (it doesn't touch fields). |
| `tests/test_interactive_package.py` | imports/exports `render_embed` | **Green** — signature change (if location threaded) may need the call-site/export updated; confirm. |
| `tests/test_command_views.py` / any `_render_view`-driven view assertion | cloned button/select shape | **Update** — clones now carry `emoji`/`default`; add assertions, refresh any shape snapshot. |

> Note: if the planner threads the selected location into `render_embed` by changing its
> **signature** (e.g. `render_embed(reply, *, location=None)`), every `render_embed(...)`
> call site (bot.py panel paths, CLI, tests) must be updated — prefer a default-None keyword
> arg so existing callers (CLI, `build_inbound_embed` parity) stay source-compatible.

## Sources

### Primary (HIGH confidence)
- `weatherbot/interactive/panel.py` (read in full) — `_LABELS:105-113`, `CmdButton:164-186`,
  `ForecastButton:188-227`, `ForecastToggleButton:230-251`, `LocationSelect:254-275`,
  `PanelView.__init__/_selected_location:290-364`, `_assert_layout:366-416`,
  `on_command:481-541`, `on_forecast:543-612`, `on_select:461-479`, `on_error:634-652`,
  `_render_view:654-701` (the clone trap), `_safe_error_edit:703-743`.
- `weatherbot/interactive/bot.py:194-261` — `render_embed`, `embed.timestamp` at :260 (D-07).
- `weatherbot/interactive/dispatch.py:140-188` — `loop.run_in_executor(None, …)` (D-08b target).
- `tests/test_scheduler.py:1919-1989` — `test_raising_uvmonitor_tick_never_stops_scheduler`
  (the exact live-scheduler proof to mirror for PANEL-11).
- `tests/test_panel.py:42-163,460-497,780-823` — `_panel`/`_make_panel`/`_stub_handler`/
  `_SpyCache` harness, `test_callback_raise_isolated`, embed/options assertions.
- `tests/conftest.py:178-227` — `fake_interaction` factory (AsyncMock-shaped Interaction).
- Installed library introspection (this session): `discord.__version__ == 2.7.1`;
  `SelectOption.__init__(... emoji=..., default=False)`; `Button.__init__(... emoji=...)`;
  `discord.utils.utcnow()`. `apscheduler 3.11.2` from `uv.lock` + `pyproject.toml`.
- `.planning/phases/20-isolation-hardening-polish/20-CONTEXT.md` — D-01..D-09 (authoritative).
- `.planning/REQUIREMENTS.md` — PANEL-11/12/13 + Out of Scope (no new dep/intent/bump).

### Secondary (MEDIUM confidence)
- Discord `<t:unix:t>`/`<t:unix:R>` timestamp markdown rendering semantics (documented
  platform behavior; client-side render not re-confirmed live this session — A2).

### Tertiary (LOW confidence)
- Exact pixel rendering of the D-05 emoji glyphs on the operator's specific client (A1) —
  deferred to Gate-2 human-UAT.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every discord.py/APScheduler param verified against the *installed*
  versions in this repo, not training data.
- Architecture: HIGH — the isolation fact (APScheduler own-thread pool vs gateway loop) is
  confirmed in code and already proven once (Phase 15); the polish seams are read directly.
- Pitfalls: HIGH — the `_render_view` clone gap and the anti-drift field-vs-description
  distinction are confirmed by reading the exact lines.

**Research date:** 2026-06-26
**Valid until:** 2026-07-26 (stable pinned stack; no fast-moving deps).
