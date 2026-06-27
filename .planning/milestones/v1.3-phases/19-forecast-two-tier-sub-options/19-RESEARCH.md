# Phase 19: Forecast Two-Tier Sub-Options - Research

**Researched:** 2026-06-26
**Domain:** discord.py 2.7.1 persistent-view reveal/collapse mechanics + additive seam extension (Python 3.12)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Variant → dispatch path:** Extend `dispatch_spec` with an optional pre-built
  `flags` param (Option B). New signature:
  `dispatch_spec(spec, arg, *, cache, config, loop, daemon_state, flags=None)`. When
  `flags is not None`, `dispatch_spec` **skips** `parse_forecast_flags(arg)` and uses the
  passed flags directly: `lookup_name = flags.location`,
  `suffix = forecast_cache_suffix(spec.name, flags)`. The panel constructs
  `ForecastFlags(variant=<"detailed"|"compact">, location=self._selected_location)` with
  `add`/`drop` left **empty** (the command name encodes the day set; the panel adds no
  day deltas). Chosen over the arg-string-synthesis Option A because it matches ROADMAP's
  "building a `ForecastFlags(...)` directly" wording and is immune to location names
  containing flag-like tokens or leading `+`/`-`.
- **D-02 (HARD CONSTRAINT — byte-identical seam):** the `flags=` param is purely additive.
  Every existing caller (`bot.on_message`, the panel's non-forecast buttons, the CLI which
  doesn't use `dispatch_spec`) must keep `flags=None`, so the `parse_forecast_flags(arg)`
  path is untouched and the contractual byte-identical reply suites stay green. Treat the
  seam change as a behavior-preserving extension, NOT a refactor of the parse path.
- **D-03 — Reveal model:** Toggle disclosure that collapses after a result. Base
  (collapsed) panel shows rows 0–2 only. Tapping **Forecast** reveals rows 3–4 (the 2×2
  grid). Tapping a forecast variant renders the result in place AND returns to the
  collapsed base.
- **D-04 — Collapse on any action except the Forecast toggle:** Only the Forecast button
  shows the expanded view; every other interaction — a forecast variant tap, any other
  command button, a dropdown change (`on_select`) — renders the collapsed base. Re-tapping
  Forecast while expanded collapses it (plain toggle).
- **D-05 — Restart behavior (ties to Phase 18):** after a restart the panel resolves to the
  collapsed default. Discord persists whatever components were last edited onto the message,
  so a panel that was revealed at restart may still *display* the sub-grid until the next
  interaction re-renders it collapsed — acceptable, because the sub-buttons' `custom_id`s
  are registered on the persistent view (D-08) so taps still route, and the next action
  collapses.
- **D-06 — Sub-button layout & labels:** 2×2 grid, explicit labels. Row 3 = weekday pair,
  row 4 = weekend pair: `Weekday Detailed` · `Weekday Compact` / `Weekend Detailed` ·
  `Weekend Compact`. Revealed state = 5/5 rows, 13/25 children (full height). Plain text
  only — emoji-coded labels are Phase 20.
- **D-07 — Toggle placement:** the **Forecast** toggle button sits in row 2 alongside
  `Status`/`Alerts` (3 buttons in row 2). A textual/caret expand-collapse state on the
  toggle is acceptable as a functional affordance (Claude's discretion) — NOT the Phase-20
  emoji work.
- **D-08 — Build-time layout assertion:** `__init__` assert + a dedicated unit test.
  Extend `_assert_layout` to validate the full/revealed panel: ≤5 rows (present), **≤5 per
  row** (assert explicitly), **≤25 children total** (add it), `custom_id` ≤100 and `label`
  ≤80 (present). Add a dedicated test asserting the assembled/revealed panel fits. The
  panel is now at 5/5 rows — zero spare row; any new component row must trip the guard.
- **D-09 (`_disabled_copy` / IN-03):** the existing IN-03 note is already satisfied if the
  forecast variant buttons and the Forecast toggle are `discord.ui.Button` subclasses —
  `_disabled_copy`'s existing `isinstance(child, discord.ui.Button)` branch rebuilds them.
  No new branch is strictly required; the planner should **verify** this holds. (If the
  toggle/sub-buttons are NOT plain Button subclasses, a new branch IS required.)

### Claude's Discretion

- Exact `custom_id` scheme for the forecast buttons and toggle (e.g.
  `wb:fc:weekday:detailed`, `wb:forecast:toggle` — all well under 100 chars).
- Whether the forecast variant buttons reuse a parameterized `CmdButton` or get a small
  dedicated button class carrying `(command_name, variant)`; the new panel method that
  builds the flags + dispatches + collapses (e.g. `on_forecast`); the reveal/collapse
  helper that builds the expanded vs collapsed child set.
- Whether to show a caret/textual expand-collapse state on the Forecast label (functional
  affordance — NOT Phase-20 emoji work).
- Exact module placement of any new helpers (keep `interactive/` import-acyclic).

### Deferred Ideas (OUT OF SCOPE)

- **Selected-location visual indicator, emoji-coded labels, "updated <time>" stamp** —
  Phase 20 polish. (A functional caret on the Forecast toggle is in-scope here as an
  affordance, but decorative emoji is Phase 20.)
- **Briefing failure-isolation re-proof for the interaction-callback path (PANEL-11)** —
  Phase 20; the per-callback envelope + `View.on_error` seam already exists and the new
  `on_forecast` path inherits it.
- **Grey-out command buttons until a location is selected (PANEL-V2-01)** — future release.
- **Arbitrary/geocoded `weather <any city>` via a modal text-input (CMD-V2-02)** — v2.0.
- Per-user/multi-user state, config editing via panel, modals, auto-refresh, new
  deps/intents, discord.py bump (milestone Out of Scope).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PANEL-07 | Operator can tap the Forecast button to reveal Weekday/Weekend × Detailed/Compact sub-options and get the chosen variant for the selected location | Reveal/collapse pattern (§Architecture Patterns 1–3), additive `flags=` seam extension (Pattern 4), single-ack `on_forecast` mirroring `on_command` (Pattern 5), 2×2 grid layout under Discord caps (§Architecture + §Common Pitfalls), build-time `_assert_layout` extension (Pattern 6 + §Validation Architecture) |
</phase_requirements>

## Summary

This phase is **orchestration of existing discord.py 2.7.1 primitives plus one additive
seam param** — there is no new library mechanic to discover and no new dependency. The two
genuinely load-bearing questions both resolve cleanly against the installed source:

1. **Persistent-view routing after a reveal/collapse swap (the one flagged uncertainty).**
   Confirmed at the source level: `Client.add_view(view)` (called in `setup_hook` with **no
   `message_id`**, per Phase 18) registers **every** child component into a global dispatch
   table keyed on `(component_type, custom_id)` under the `None` bucket. `ViewStore.dispatch_view`
   resolves an incoming interaction by that `(type, custom_id)` key — it does **NOT** consult
   what components are currently displayed on the message. Therefore, the standard, safe
   pattern is: **one canonical persistent `PanelView` whose `__init__` builds ALL children
   (base + the 4 forecast variant buttons + the Forecast toggle), so every forecast
   `custom_id` is registered once at `add_view` time; reveal/collapse is purely a
   `edit_message(view=<view carrying a base-vs-expanded child subset>)` cosmetic swap.** A
   tap on a revealed sub-button after a restart routes because its `custom_id` is in the
   registered table, regardless of whether the post-restart message currently shows it
   (this is exactly the D-05 guarantee). **Do NOT dynamically `add_item`/`remove_item` from
   the registered persistent view** between renders — the registered view must hold the
   full custom_id set for routing to survive.

2. **Byte-identical seam extension (D-02).** Adding `flags=None` to `dispatch_spec` is a
   pure default-param extension: when `flags is None` the existing
   `parse_forecast_flags(arg)` branch runs verbatim; when `flags is not None` it is skipped
   and the passed dataclass is used. No existing caller passes `flags`, so every existing
   reply is structurally unchanged and the anti-drift suites stay green.

**Primary recommendation:** Keep ONE persistent `PanelView` that constructs all 13 children
in `__init__` (so all custom_ids register via the existing Phase-18 `add_view`); model
reveal/collapse as a `edit_message(view=...)` that swaps which already-registered children
are *attached* to a freshly-built render view (mirroring the existing `_disabled_copy`
rebuild pattern); add `flags=None` to `dispatch_spec` as a strictly-additive skip-the-parse
param; and complete `_assert_layout` (≤5 rows / ≤5 per row / ≤25 children / id≤100 /
label≤80) on the full 5/5-row revealed layout, backed by a dedicated test.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Forecast variant → flags construction | Panel component (`PanelView`/forecast button callback) | — | The panel owns the in-memory selected location and the chosen variant; it builds `ForecastFlags` directly (D-01) |
| Forecast fetch + reply binding | Shared dispatch seam (`dispatch_spec`/`dispatch_reply`) | ForecastCache (off-loop) | One shared ladder; the panel must not parallel-implement forecast logic (criterion 2 / PANEL-10) |
| Reveal/collapse rendering | Panel component (`edit_message(view=...)`) | Discord gateway (component re-delivery) | Pure presentation swap on the same pinned message; no new message, no new data |
| Persistent custom_id routing | discord.py `ViewStore` (registered at `add_view`) | `setup_hook` (Phase 18) | Routing is global-by-custom_id, independent of displayed components |
| Build-time cap enforcement | Panel `__init__` `_assert_layout` + CI test | discord.py `add_item` (per-row/total raises) | Fail-loud at construction for caps the library accepts silently (id/label) and assert the ones it raises on |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | 2.7.1 | Component UI (Button/Select/View), persistent-view registration, interaction lifecycle | Already pinned (`discord.py>=2.7.1,<3`); the milestone explicitly forbids a bump. Verified installed via `uv.lock`. [VERIFIED: uv.lock / installed source inspection] |
| Python | 3.12+ | Runtime (frozen dataclass `ForecastFlags`, `from __future__ import annotations`) | Project standard per CLAUDE.md. [CITED: ./CLAUDE.md] |

### Supporting

No new libraries. This phase reuses existing in-repo modules only:

| Module | Purpose | When to Use |
|--------|---------|-------------|
| `weatherbot/interactive/dispatch.py` | `dispatch_spec` (gets the additive `flags=` param) + `dispatch_reply` | The one seam edit |
| `weatherbot/interactive/command.py` | `ForecastFlags` (frozen dataclass), `forecast_cache_suffix` | Panel builds the dataclass directly; suffix used inside `dispatch_spec` when `flags` is passed |
| `weatherbot/interactive/panel.py` | `PanelView`, `CmdButton`, `_assert_layout`, `_disabled_copy`, `on_command`, `on_select` | Extended in place — toggle + 4 sub-buttons + reveal/collapse + assert |
| `weatherbot/interactive/registry.py` | `BY_NAME["weekday-forecast"]`/`["weekend-forecast"]`, `CommandSpec` (group=="Forecast", takes_location=True) | The specs the forecast buttons resolve |
| `weatherbot/interactive/bot.py` | `render_embed`, `setup_hook` `add_view` (unchanged registration, now carries the extra children) | In-place render; the existing `add_view` call already registers whatever children `PanelView.__init__` builds |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `flags=` param (Option B / D-01) | Synthesize an arg string like `"Home --compact"` and let `dispatch_spec` reparse (Option A) | REJECTED by D-01: brittle for location names containing flag-like tokens (`+`/`-` leading chars), and contradicts ROADMAP's "build a `ForecastFlags(...)` directly". Option B is immune. |
| One canonical view holding all custom_ids | Dynamically `add_item`/`remove_item` on the registered persistent view per reveal | REJECTED: removing items from the registered view (or registering a view that lacks the sub-buttons) drops those custom_ids from the dispatch table, breaking post-restart routing on a revealed panel. The registered view MUST carry the full set. |
| Dedicated `ForecastButton(command_name, variant)` class | Reuse parameterized `CmdButton` | Claude's discretion (D-01 discretion list). A dedicated class is cleaner because the callback path differs (builds flags + collapses, vs `on_command`'s plain dispatch). |

**Installation:** None — no new packages.

**Version verification:** discord.py 2.7.1 confirmed in `uv.lock`
(`discord_py-2.7.1-py3-none-any.whl`, upload-time `2026-03-03`) and by direct
`inspect.getsource` against the installed package. [VERIFIED: uv.lock + installed source]

## Package Legitimacy Audit

No external packages are installed in this phase (the milestone forbids new dependencies and
a discord.py bump). The only dependency exercised is the already-pinned `discord.py 2.7.1`.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| discord.py | PyPI | mature (2.x line) | very high | github.com/Rapptz/discord.py | OK | Already pinned — no install |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                         Pinned panel message (one PanelView, timeout=None)
                                          │
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  setup_hook → client.add_view(PanelView(...))   [Phase 18, message_id=None] │
   │  registers ALL child custom_ids into ViewStore._views[None]                 │
   │  keyed (component_type, custom_id):                                         │
   │    wb:loc:select, wb:cmd:weather … wb:cmd:alerts,                           │
   │    wb:forecast:toggle, wb:fc:weekday:detailed … wb:fc:weekend:compact       │
   └──────────────────────────────────────────────────────────────────────────┘
                                          │
            operator tap ─────────────────┤  ViewStore.dispatch_view(type, custom_id)
                                          │   resolves by KEY only (display-independent)
                                          ▼
              ┌────────────────────────────────────────────────────────┐
              │ interaction_check (operator gate, unchanged)             │
              └────────────────────────────────────────────────────────┘
                                          │
        ┌─────────────────────────────────┼───────────────────────────────────────┐
        ▼                                 ▼                                         ▼
  Forecast toggle tap            forecast variant tap                  any other tap (cmd / select)
  (on_forecast_toggle)           (on_forecast)                         (on_command / on_select)
        │                                 │                                         │
  edit_message(view=               ① edit_message(cue,                   render COLLAPSED base
   EXPANDED child set)               view=_disabled_copy)  ── D-04 ──►   (collapse on any non-toggle action)
   — re-tap collapses               build ForecastFlags(variant, location=selected)
   (D-03/D-04)                      await dispatch_spec(spec, None, …, flags=flags)
                                    ② edit_original_response(
                                       embed=render_embed(reply),
                                       view=COLLAPSED base)   — D-03 collapse-after-result
                                          │
                                          ▼
                            dispatch_spec(… flags=ForecastFlags)
                            flags is not None → SKIP parse_forecast_flags
                            lookup_name = flags.location
                            suffix = forecast_cache_suffix(spec.name, flags)
                            off-loop cache.lookup → dispatch_reply(spec, result, flags) → CommandReply
```

The diagram traces the primary use case: a tap enters via the global ViewStore (routing by
custom_id), passes the operator gate, and either toggles the reveal cosmetically or runs a
forecast variant through the **same** shared dispatcher the text command uses.

### Recommended Project Structure

No new files. All edits land in existing modules:

```
weatherbot/interactive/
├── dispatch.py     # + flags=None param on dispatch_spec (additive, D-01/D-02)
├── panel.py        # + Forecast toggle + 4 ForecastButton children + reveal/collapse +
│                   #   on_forecast / on_forecast_toggle + _assert_layout completion +
│                   #   on_select/on_command collapse-on-action (D-03..D-09)
└── command.py      # unchanged — ForecastFlags / forecast_cache_suffix reused as-is
tests/
├── test_dispatch.py   # + flags= passthrough + byte-identical-when-None assertions
└── test_panel.py      # + reveal/collapse, on_forecast flags-build + dispatch, full-layout assert test
```

### Pattern 1: One canonical persistent view carries ALL custom_ids; reveal/collapse swaps the *attached* subset

**What:** `PanelView.__init__` builds every child once — base (dropdown + cmd buttons +
status/alerts + Forecast toggle) AND the four forecast variant buttons. Because the existing
Phase-18 `setup_hook` does `client.add_view(PanelView(...))`, all of those custom_ids get
registered into the global dispatch table. Reveal/collapse never adds/removes children from
the *registered* view; it renders a freshly-built view object attaching either the base
subset or the expanded subset (the same "rebuild a fresh `timeout=None` view" technique
`_disabled_copy` already uses, `panel.py:396-432`).

**When to use:** Every reveal and every collapse render.

**Why this is the safe pattern (source-verified):**
```python
# discord.py 2.7.1 — discord/ui/view.py  ViewStore.add_view  (VERIFIED via inspect.getsource)
def add_view(self, view, message_id=None):
    ...
    for item in view.walk_children():
        ...
        elif item.is_dispatchable():
            dispatch_info[(item.type.value, item.custom_id)] = item   # ← every child registered
    ...
    if dispatch_info:
        self._views[message_id] = dispatch_info     # message_id is None for this project

# ViewStore.dispatch_view  (VERIFIED)
def dispatch_view(self, component_type, custom_id, interaction):
    key = (component_type, custom_id)
    item = self._views.get(message_id, {}).get(key)
    if item is None:
        item = self._views.get(None, {}).get(key)   # ← project's bucket; resolves by KEY only
    if item is None:
        return                                       # 3 lookups failed → discard
    task = item.view._dispatch_item(item, interaction)
```
Routing depends ONLY on whether `(type, custom_id)` was registered at `add_view` time — NOT
on what the message currently displays. Registering the full-child `PanelView` once
satisfies D-05: a revealed sub-button tapped after a restart still routes. [VERIFIED:
discord.py 2.7.1 installed source]

### Pattern 2: Reveal = `edit_message(view=expanded)`, collapse = `edit_message`/`edit_original_response(view=collapsed)`

**What:** The Forecast toggle callback acks with a single `interaction.response.edit_message(view=<expanded>)`.
Any non-toggle action renders the collapsed base. A forecast variant tap collapses *after*
its result (D-03): the result `edit_original_response(view=<collapsed base>)` is what
collapses it.

**When to use:** Toggle taps (reveal/collapse) and the tail of every action callback.

**Example:**
```python
# Reveal/collapse helper (Claude's discretion on exact name/shape). Mirrors _disabled_copy's
# "build a fresh timeout=None view attaching already-registered children" technique so the
# REGISTERED PanelView is never mutated.
def _render_view(self, *, expanded: bool, disabled: bool = False) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for child in self.children:
        if not expanded and getattr(child, "row", None) in (3, 4):
            continue            # collapsed: omit the forecast sub-grid rows
        view.add_item(<disabled-or-live clone of child>)   # same custom_id/label/style/row
    return view
```
Re-tapping the toggle while expanded calls the same helper with `expanded=False` (plain
toggle, D-04). The collapsed render omits rows 3–4; the expanded render includes them.

### Pattern 3: Single-ack `on_forecast` mirrors `on_command` exactly

**What:** The forecast variant callback follows the existing single-`response.*`-per-tap
contract: ① `interaction.response.edit_message(content=_FETCHING_CUE, view=<disabled copy>)`
(acks <3s, disables to neutralize double-taps), then ② `interaction.edit_original_response(...)`
for the result via the followup path. It differs from `on_command` only in that it builds
`ForecastFlags` directly and passes `flags=`, and that its result render collapses the panel
(D-03).

**Example:**
```python
async def on_forecast(self, interaction, *, command_name: str, variant: str) -> None:
    try:
        spec = registry.BY_NAME[command_name]   # "weekday-forecast" | "weekend-forecast"
        flags = ForecastFlags(variant=variant, location=self._selected_location)  # add/drop empty (D-01)
        await interaction.response.edit_message(            # ① single ack + disable
            content=_FETCHING_CUE, view=self._render_view(expanded=True, disabled=True)
        )
        loop = asyncio.get_running_loop()
        config = self._holder.current()
        try:
            reply = await dispatch_spec(
                spec, None, cache=self._cache, config=config,
                loop=loop, daemon_state=self._daemon_state, flags=flags,   # D-01
            )
        except UnknownLocationError as exc:
            await interaction.edit_original_response(
                content=str(exc), embed=None, view=self._render_view(expanded=False))  # collapse
            return
        await interaction.edit_original_response(           # ② result + collapse (D-03)
            content=None, embed=render_embed(reply),
            view=self._render_view(expanded=False),
        )
    except Exception:   # noqa: BLE001 — non-propagating envelope (mirrors on_command)
        _log.exception("panel forecast callback failed",
                       custom_id=f"wb:fc:{command_name}:{variant}")
        await self._safe_error_edit(interaction)
```
Note: `arg` is `None` and `flags.location` carries the location — `dispatch_spec` uses
`flags.location` as the lookup name (D-01), so the positional `arg` is irrelevant on this
path.

### Pattern 4: Additive `flags=` extension to `dispatch_spec` (byte-identical when None, D-02)

**What:** Add `flags: ForecastFlags | None = None` as a keyword-only param. When `None`, the
existing forecast branch runs `parse_forecast_flags(arg)` exactly as today. When provided,
that parse is skipped and the passed flags drive `lookup_name` and `suffix`.

**Example (the minimal diff to `dispatch_spec`):**
```python
async def dispatch_spec(spec, arg, *, cache, config, loop, daemon_state, flags=None):
    result = None
    if spec.takes_location:
        is_forecast = spec.group == "Forecast"
        lookup_name = arg
        suffix = None
        if is_forecast:
            if flags is None:                                  # ← existing path, untouched (D-02)
                flags = parse_forecast_flags(arg)
            # else: use the caller-provided flags directly (D-01)
            lookup_name = flags.location
            suffix = forecast_cache_suffix(spec.name, flags)
        if is_forecast:
            result = await loop.run_in_executor(None, cache.lookup, lookup_name, config, suffix)
        else:
            result = await loop.run_in_executor(None, cache.lookup, lookup_name, config)
    return await loop.run_in_executor(None, lambda: dispatch_reply(
        spec, result=result, config=config, flags=flags, daemon_state=daemon_state))
```
`dispatch_reply` is **unchanged** — it already accepts `flags` and binds
`handler(result, flags)` for the Forecast group (`dispatch.py:88-90`). Every existing caller
omits `flags`, so `flags=None` → the `parse_forecast_flags(arg)` branch is byte-for-byte the
prior behavior. [VERIFIED: dispatch.py source]

### Pattern 5: `_disabled_copy` already covers Button subclasses (D-09 verify, not build)

**What:** If the Forecast toggle and the four variant buttons are `discord.ui.Button`
subclasses, the existing `_disabled_copy` `isinstance(child, discord.ui.Button)` branch
(`panel.py:412-421`) rebuilds them with no new branch. The planner should add a test
asserting the disabled copy contains all expanded children rather than treating IN-03 as a
blocker.

**Caveat (D-09):** If a variant button is NOT a plain `Button` subclass, a new
`_disabled_copy` branch IS required. The reveal/collapse `_render_view` helper (Pattern 2)
should ideally subsume `_disabled_copy` (one rebuild path, parameterized by
`expanded`/`disabled`) to avoid two parallel child-cloning code paths drifting (IN-03 risk).

### Pattern 6: Complete `_assert_layout` on the full 5/5-row revealed panel (D-08)

**What:** Extend `_assert_layout` to assert all four Discord caps against the assembled
revealed panel: ≤5 rows (present), ≤5 per row (add — currently only `add_item` raises),
≤25 children total (add — currently unchecked), custom_id ≤100 and label ≤80 (present). The
revealed layout is 5/5 rows, 13/25 children — zero spare row.

**Example:**
```python
def _assert_layout(self, locations) -> None:
    from collections import Counter
    rows = [c.row for c in self.children if c.row is not None]
    assert len(set(rows)) <= _MAX_ROWS, f"panel uses {len(set(rows))} rows (>{_MAX_ROWS})"
    per_row = Counter(rows)
    for r, n in per_row.items():                                   # NEW (D-08)
        assert n <= _MAX_PER_ROW, f"row {r} has {n} components (>{_MAX_PER_ROW})"
    assert len(self.children) <= _MAX_CHILDREN, (                  # NEW (D-08)
        f"panel has {len(self.children)} children (>{_MAX_CHILDREN})")
    assert len(locations) <= _MAX_OPTIONS, ...
    for child in self.children:
        ... # custom_id ≤100, label ≤80 (present)
```
where `_MAX_PER_ROW = 5` and `_MAX_CHILDREN = 25`. Back this with a dedicated test that
builds a full `PanelView` and asserts `_assert_layout` passes at exactly 13 children / 5 rows
AND that a hypothetical 6th-row addition trips the guard (the "future addition can't silently
overflow" criterion 3).

### Anti-Patterns to Avoid

- **Mutating the registered persistent view** (`self.add_item`/`self.remove_item` on the
  `PanelView` instance registered via `add_view`) to reveal/collapse — drops sub-button
  custom_ids from the dispatch table, breaking post-restart routing (the opposite of D-05).
  Build a fresh render view instead (Pattern 2).
- **Registering a base-only view in `setup_hook`** then a different expanded view at reveal
  time — the expanded custom_ids would not be in the registered table; post-restart taps on
  a revealed grid would silently fail. Register the FULL-child `PanelView`.
- **A second `interaction.response.*` call** on the forecast path — raises
  `InteractionResponded`. Use `edit_original_response` for the result (Pattern 3).
- **Synthesizing an arg string** for the forecast variant (Option A) — D-01 rejects it;
  build `ForecastFlags` directly.
- **Two parallel child-cloning paths** (`_disabled_copy` and a separate reveal builder)
  drifting out of sync (IN-03) — prefer one parameterized `_render_view`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Forecast fetch + variant rendering | A panel-local forecast fetch/render path | `dispatch_spec(... flags=...)` + the registry `weekday/weekend-forecast` specs | Criterion 2 / PANEL-10 — one shared ladder, zero parallel forecast logic; the byte-identical text/panel guarantee depends on it |
| Forecast-flags object | Re-stringify `"Home --compact"` then reparse | `ForecastFlags(variant=…, location=…)` directly (D-01) | Immune to location names with flag-like tokens; matches ROADMAP wording |
| Cache key for the forecast variant | A panel-local key scheme | `forecast_cache_suffix(spec.name, flags)` (inside `dispatch_spec`) | Prevents a forecast result colliding with a plain `!weather` cache entry (A5); derived in ONE place so CLI/bot/panel never drift |
| Persistent routing after restart | A boot-time message scan / re-attach scheme | The existing `setup_hook` `add_view` (Phase 18) registering the full-child view | discord.py routes by global custom_id table; nothing else needed |
| Per-row / total-children cap enforcement | A hand-rolled send-time error handler | `_assert_layout` at construction (D-08) + discord.py `add_item` raising | Fail-loud at build, before any send; CI test makes overflow impossible to merge |
| Single-ack + failure isolation | A new envelope for `on_forecast` | The existing single-ack contract + per-callback `try/except` + `View.on_error` backstop | Already load-bearing from Phase 17; `on_forecast` inherits it by mirroring `on_command` |

**Key insight:** This phase adds **surface**, not **logic**. Every byte of forecast behavior
already exists and is exercised by the text command; the panel is a third caller of the same
seam. The only genuinely new code is component plumbing (a toggle, four buttons, a
reveal/collapse render swap) and one additive default param.

## Common Pitfalls

### Pitfall 1: Reveal/collapse breaks post-restart routing
**What goes wrong:** Sub-buttons stop responding after a `systemctl restart` if the bot
revealed-then-restarted, OR if the registered view doesn't include the sub-buttons.
**Why it happens:** discord.py routes interactions by the `(type, custom_id)` registered at
`add_view`; if those custom_ids aren't in the registered view, the lookup fails and the
interaction is silently discarded (`dispatch_view` returns).
**How to avoid:** Register the FULL-child `PanelView` in `setup_hook` (already the call
shape — `__init__` just builds more children now). Never mutate that registered view to
reveal/collapse; render a fresh view (Pattern 1/2).
**Warning signs:** A revealed sub-button shows "interaction failed" only after a restart; a
unit test that asserts all forecast custom_ids appear in `PanelView(...).children` would
catch a missing registration.

### Pitfall 2: Second `response.*` call on the forecast path
**What goes wrong:** `InteractionResponded` exception, caught by the envelope → generic
error edit instead of the forecast.
**Why it happens:** Calling `interaction.response.edit_message` (the ack) and then a second
`response.*` for the result.
**How to avoid:** Exactly one `response.*` (the ack/cue) then `edit_original_response` for the
result — mirror `on_command` (Pattern 3).
**Warning signs:** "Sorry — something went wrong." on every forecast tap; an
`InteractionResponded` in the logs.

### Pitfall 3: The byte-identical suite drifts because `flags` leaks into the None path
**What goes wrong:** An existing text-forecast reply changes, the anti-drift suite goes red.
**Why it happens:** Reordering or rewriting the `parse_forecast_flags(arg)` branch instead of
guarding it behind `if flags is None`.
**How to avoid:** Treat the change as purely additive — `flags is None` must run the existing
branch verbatim (Pattern 4). Add a `dispatch_spec(..., flags=None)` test that asserts
identical behavior to the no-`flags`-arg call.
**Warning signs:** Any diff inside the `is_forecast` block other than the `if flags is None`
guard.

### Pitfall 4: 5/5-row layout silently overflows on a future addition
**What goes wrong:** A later phase adds a 6th component row or a 26th child; Discord rejects
at send time with a generic `HTTPException`.
**Why it happens:** discord.py's `add_item` raises for some caps but `_assert_layout` didn't
assert per-row/total explicitly, and the panel is now at zero spare capacity.
**How to avoid:** Complete `_assert_layout` (D-08) AND add the dedicated test (criterion 3).
**Warning signs:** The phase is the moment the panel hits 5/5 rows — the guard is now
load-bearing, so the test must assert both "current layout fits" and "an over-cap layout
trips the assert".

### Pitfall 5: `Select.values` read inside a forecast callback
**What goes wrong:** Empty/incorrect location.
**Why it happens:** Reading `self.<select>.values` outside an active select interaction
(discord.py #7284, noted in `panel.py:171-180`).
**How to avoid:** Read `self._selected_location` (the in-memory selection), exactly as
`on_command` does (D-04). Never re-read the Select inside a button callback.

## Code Examples

### Building the toggle + 2×2 grid in `__init__` (rows 2–4)
```python
# row 2: status, alerts (existing) + Forecast toggle (D-07) — 3 buttons in row 2
for name in _ARGLESS_CMDS:
    self.add_item(CmdButton(name, self, row=2))
self.add_item(ForecastToggleButton(self, custom_id="wb:forecast:toggle", row=2))

# rows 3–4: the 2×2 variant grid (D-06). custom_ids registered once via add_view.
self.add_item(ForecastButton(self, "weekday-forecast", "detailed",
                             custom_id="wb:fc:weekday:detailed", label="Weekday Detailed", row=3))
self.add_item(ForecastButton(self, "weekday-forecast", "compact",
                             custom_id="wb:fc:weekday:compact",  label="Weekday Compact",  row=3))
self.add_item(ForecastButton(self, "weekend-forecast", "detailed",
                             custom_id="wb:fc:weekend:detailed", label="Weekend Detailed", row=4))
self.add_item(ForecastButton(self, "weekend-forecast", "compact",
                             custom_id="wb:fc:weekend:compact",  label="Weekend Compact",  row=4))
self._assert_layout(locations)   # now validates the full 5/5-row layout (D-08)
```
(All four `wb:fc:*` and the `wb:forecast:toggle` custom_ids are < 100 chars and the labels
< 80, so the existing id/label asserts pass; the new per-row/total asserts confirm 3-in-row-2,
2-in-rows-3/4, 13 total.)

### Registry resolution (verify the specs exist at import — mirrors the existing curated guard)
```python
# weekday-forecast / weekend-forecast both in BY_NAME, group=="Forecast", takes_location=True
# (registry.py:67-78) — add a build-time assert mirroring panel.py:80-84 so a registry rename
# trips at construction.
for _name in ("weekday-forecast", "weekend-forecast"):
    assert _name in registry.BY_NAME, f"forecast spec {_name!r} missing from registry"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Re-register views per message edit | One `add_view` (message_id=None) registers custom_ids globally; edits are cosmetic | discord.py 2.x persistent-view model | Reveal/collapse needs no re-registration; routing is display-independent |
| `await channel.pins()` awaitable | `async for m in channel.pins()` async iterator | discord.py 2.7.x (already adopted Phase 18) | N/A to this phase (no pin scan added) — noted for consistency |

**Deprecated/outdated:** none relevant to this phase. No discord.py bump (milestone Out of
Scope).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | (none) | — | All load-bearing claims (persistent routing, additive seam, `_disabled_copy` Button branch) were verified against installed discord.py 2.7.1 source and the repo's own source files. |

**All claims in this research were verified or cited — no user confirmation needed.** The one
flagged uncertainty (persistent-view reveal/collapse routing) is resolved at HIGH confidence
by direct source inspection of `ViewStore.add_view`/`dispatch_view`, corroborated by the
discord.py persistent-view community guidance.

## Open Questions

1. **Should `_render_view` subsume `_disabled_copy`?**
   - What we know: `_disabled_copy` already rebuilds a fresh view of Button/Select clones; the
     reveal/collapse helper does the same child-cloning with two extra knobs (`expanded`,
     `disabled`).
   - What's unclear: whether to merge them (one path) or keep two (less churn to existing
     Phase-17 tests).
   - Recommendation: merge into one parameterized `_render_view(expanded, disabled)` to kill
     the IN-03 drift risk; have `_disabled_copy` delegate (or be replaced) so there is a
     single child-cloning code path. Planner's call — both are Claude's discretion (D-09).

2. **Dedicated `ForecastButton` class vs parameterized `CmdButton`?**
   - What we know: forecast buttons carry `(command_name, variant)` and a distinct callback
     (build flags + collapse) that `CmdButton` does not.
   - Recommendation: a small dedicated `ForecastButton` (and `ForecastToggleButton`) is
     cleaner and keeps both Button subclasses so D-09's existing `_disabled_copy` branch
     covers them with no new branch. (Claude's discretion.)

## Environment Availability

This phase is a pure code/component change with no NEW external dependency — it runs against
the already-installed discord.py 2.7.1 and the existing OpenWeather-backed cache (exercised
only through the unchanged `dispatch_spec` fetch path). Live verification touches the running
systemd service on host `yahir-mint` (editable install, restart needed — see project memory),
but no new tool/runtime is introduced.

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| discord.py | Component UI + persistent views | ✓ | 2.7.1 (uv.lock) | — |
| Python | Runtime | ✓ | 3.12+ | — |
| pytest | Test suite (gateway-free) | ✓ | (existing dev dep) | — |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (gateway-free fakes; `asyncio.run` driver) |
| Config file | `pyproject.toml` (pytest config) + `tests/conftest.py` (`_make_fake_interaction`, `fake_interaction` fixture) |
| Quick run command | `uv run pytest tests/test_panel.py tests/test_dispatch.py -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PANEL-07 (criterion 1) | Forecast toggle reveals the 2×2 grid; re-tap collapses | unit | `uv run pytest tests/test_panel.py -k forecast_toggle_reveal -x` | ❌ Wave 0 |
| PANEL-07 (criterion 1) | A variant tap builds `ForecastFlags(variant, location=selected, add/drop empty)` and routes through `dispatch_spec` with `flags=` | unit | `uv run pytest tests/test_panel.py -k on_forecast_dispatch -x` | ❌ Wave 0 |
| PANEL-07 (criterion 1, D-03/D-04) | A variant tap (and any non-toggle action) renders the COLLAPSED base view | unit | `uv run pytest tests/test_panel.py -k collapse_on_action -x` | ❌ Wave 0 |
| PANEL-07 (criterion 1, D-05) | All forecast custom_ids are present on the constructed `PanelView` (so `add_view` registers them → post-restart routing) | unit | `uv run pytest tests/test_panel.py -k forecast_custom_ids_registered -x` | ❌ Wave 0 |
| PANEL-07 (criterion 2 / D-02) | `dispatch_spec(spec, arg, flags=None)` is byte-identical to the pre-extension behavior; `flags=<built>` skips `parse_forecast_flags` and uses the passed flags | unit | `uv run pytest tests/test_dispatch.py -k flags_passthrough -x` | ❌ Wave 0 |
| PANEL-07 (criterion 2) | The panel forecast result equals the registry forecast spec's reply (same content as text command) | unit | `uv run pytest tests/test_panel.py -k forecast_matches_registry -x` | ❌ Wave 0 |
| PANEL-07 (criterion 3 / D-08) | `_assert_layout` passes on the full 5/5-row, 13-child revealed panel | unit | `uv run pytest tests/test_panel.py -k layout_full_panel_fits -x` | ❌ Wave 0 |
| PANEL-07 (criterion 3 / D-08) | A 6th-row / 26th-child / 6-per-row / overlong-id / overlong-label panel TRIPS `_assert_layout` | unit | `uv run pytest tests/test_panel.py -k layout_overflow_trips_assert -x` | ❌ Wave 0 |
| Anti-drift (D-02) | Existing text `!weekday-forecast`/`!weekend-forecast` replies unchanged | regression | `uv run pytest tests/test_dispatch.py tests/test_bot.py tests/test_command.py tests/test_command_views.py tests/test_registry.py -q` | ✅ exists |

**Observable signals/seams proving each success criterion:**
- **Criterion 1 (reveal + chosen variant):** the `view` passed to
  `interaction.response.edit_message` / `edit_original_response` (AsyncMock on the
  `fake_interaction`) — assert its children include/exclude rows 3–4 for expanded/collapsed;
  and the `ForecastFlags` argument captured on a monkeypatched `dispatch_spec` (variant +
  `location == self._selected_location`, `add`/`drop` empty).
- **Criterion 2 (same dispatcher, no parallel logic):** assert `on_forecast` calls the SAME
  `dispatch_spec` (monkeypatched, call recorded) with the `weekday/weekend-forecast` spec
  from `registry.BY_NAME` and `flags=` set; and that `dispatch_spec(..., flags=None)` ==
  the existing parse-path output (byte-identical seam).
- **Criterion 3 (build-time layout assert):** call `PanelView(...)` (the assert runs in
  `__init__`) and assert no raise at 13 children/5 rows; construct an over-cap layout and
  assert `AssertionError`. This is a pure construction-time signal — no gateway needed.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_panel.py tests/test_dispatch.py -x -q`
- **Per wave merge:** `uv run pytest -q` (full suite — proves the byte-identical anti-drift
  guards stayed green, D-02)
- **Phase gate:** Full suite green before `/gsd-verify-work`; plus the live self-UAT
  (Gate 1) on host `yahir-mint`: summon the panel, tap Forecast → reveal, tap a variant →
  correct in-place forecast + collapse, then `systemctl restart weatherbot` and tap a
  forecast variant on the (still-revealed-display) panel to prove post-restart routing (D-05).

### Wave 0 Gaps
- [ ] `tests/test_panel.py` — add forecast reveal/collapse + `on_forecast` flags-build +
  dispatch + custom_id-registration + full/overflow layout nodes (covers PANEL-07 all
  criteria). Reuse the existing `fake_interaction` factory + `_patch_command_in_registry`
  monkeypatch pattern.
- [ ] `tests/test_dispatch.py` — add `flags=` passthrough + `flags=None`-byte-identical
  nodes (covers D-02 + criterion 2). The existing `_FakeSpec`/`_recording_handler` harness
  covers it.
- [ ] No new conftest fixtures needed — `fake_interaction` (AsyncMock response.*/
  edit_original_response, MagicMock is_done) already shapes every assertion seam.
- [ ] No framework install needed — pytest + the gateway-free harness already exist.

## Security Domain

> `security_enforcement` is not disabled in config; included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surface — the operator gate (`interaction_check`) is unchanged |
| V3 Session Management | no | No sessions; Discord interaction tokens handled by discord.py |
| V4 Access Control | yes | The existing `interaction_check` operator gate runs before EVERY child callback, including the new forecast buttons + toggle — no new bypass; a non-operator tap on a forecast button is rejected leak-free exactly as for command buttons (PANEL-08, unchanged) |
| V5 Input Validation | yes | No free-text input. `variant` is one of two compile-time literals (`"detailed"`/`"compact"`); `location` is the already-validated in-memory selection (a configured location). `ForecastFlags` is built from constants, never from user-typed strings — the `parse_forecast_flags` injection-safe parser is bypassed precisely because there is no string to parse (D-01) |
| V6 Cryptography | no | None |

### Known Threat Patterns for discord.py component panel

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Non-operator drives forecast buttons | Elevation of Privilege | `interaction_check` operator gate (existing) covers all children incl. forecast (V4) |
| Identity leak in reject/error copy | Information Disclosure | Generic identity-free reject + `_ERROR_REPLY` (existing, unchanged); the new `on_forecast` reuses `_safe_error_edit` so no user/custom_id/command is echoed |
| Raising/hanging forecast callback affects the briefing | Denial of Service | Per-callback non-propagating envelope + `View.on_error` backstop (existing); `on_forecast` mirrors it. Full re-proof is Phase 20 (PANEL-11) but the seam already contains the failure here |
| Cache-key collision (forecast vs `!weather`) | Tampering (data integrity) | `forecast_cache_suffix(spec.name, flags)` widens the key (A5), applied inside `dispatch_spec` on the `flags`-provided path identically to the parse path |

## Sources

### Primary (HIGH confidence)
- discord.py 2.7.1 installed source — `discord/ui/view.py` `ViewStore.add_view` /
  `ViewStore.dispatch_view` / `View.is_persistent`, `discord/client.py` `Client.add_view`
  (via `inspect.getsource`): persistent routing is by global `(type, custom_id)` table,
  display-independent — resolves the D-05 reveal/collapse question.
- Repo source: `weatherbot/interactive/dispatch.py`, `command.py`, `panel.py`,
  `registry.py`, `commands/forecast.py`, `bot.py` (`setup_hook`/`add_view`),
  `tests/test_panel.py`, `tests/test_dispatch.py`, `tests/conftest.py` — the exact seams
  extended and the test harness reused.
- `.planning/phases/18-...-restart-durability/18-PATTERNS.md` — `add_view` in `setup_hook`,
  default-on-restart, the persistent-view registration this phase rides.
- `uv.lock` — discord.py pinned at 2.7.1 (no bump).

### Secondary (MEDIUM confidence)
- discord.py persistent-views community guidance (thegamecracks tutorial; Rapptz/discord.py
  `examples/views/persistent.py`; discussion #9851) — corroborates the source-level finding
  that components must be re-registered via `add_view` after restart and routing keys on
  custom_id.

### Tertiary (LOW confidence)
- none.

## Metadata

**Confidence breakdown:**
- Persistent-view reveal/collapse routing (the flagged uncertainty): HIGH — verified by direct
  source inspection of `add_view`/`dispatch_view` + community corroboration.
- Additive `flags=` seam (byte-identical D-02): HIGH — verified against `dispatch.py` source;
  the change is a single `if flags is None` guard.
- Layout assertion completion (D-08): HIGH — verified against `_assert_layout` source; pure
  construction-time arithmetic on known caps.
- `_disabled_copy` D-09 coverage: HIGH — verified the existing Button branch covers Button
  subclasses; flagged the merge-with-`_render_view` recommendation.

**Research date:** 2026-06-26
**Valid until:** 2026-07-26 (stable — pinned discord.py, no fast-moving external surface)
