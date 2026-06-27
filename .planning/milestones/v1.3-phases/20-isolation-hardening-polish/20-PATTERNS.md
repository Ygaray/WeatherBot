# Phase 20: Isolation Hardening + Polish - Pattern Map

**Mapped:** 2026-06-26
**Files analyzed:** 5 modified (2 prod + 3 test areas) + 4 anti-drift snapshot test files
**Analogs found:** 5 / 5 (all analogs are in-file / sibling — this is a polish phase over assembled Phase 17–19 code, so every "new" behavior has a direct same-file precedent)

> This phase adds **zero new files** and **zero new component slots**. Every change is a thin
> edit to an existing hot path (`render_embed`, the `_render_view` clone, `CmdButton.__init__`,
> `LocationSelect.__init__`) or a new test mirroring an existing test. The analogs are therefore
> the *adjacent existing lines in the same file*, not a separate module. The load-bearing risk is
> the `_render_view` clone gap (Pattern A), not building anything new.

## File Classification

| Modified File | Role | Data Flow | Closest Analog (copy from) | Match Quality |
|---------------|------|-----------|----------------------------|---------------|
| `weatherbot/interactive/panel.py` (clone) | component (View) | request-response / render | `panel.py:681-700` itself (the clone) + `__init__` construction `panel.py:174-271` | exact (in-file) |
| `weatherbot/interactive/panel.py` (emoji) | component (Button) | request-response | `_LABELS` dict + `CmdButton.__init__` `panel.py:105-180` | exact (in-file) |
| `weatherbot/interactive/panel.py` (dropdown default) | component (Select) | request-response | `LocationSelect.__init__` `panel.py:265-271` | exact (in-file) |
| `weatherbot/interactive/bot.py` (`render_embed`) | utility (render) | transform | `render_embed` `bot.py:194-261` itself | exact (in-file) |
| `tests/test_panel.py` (hanging-callback) | test | event-driven (live scheduler) | `test_scheduler.py:1919-1989` + `test_panel.py:475-497` | exact (two templates) |
| `tests/test_panel.py` (executor audit) | test | audit | `dispatch.py:166-188` code-path | role-match |
| `tests/test_panel.py` (indicator/emoji/stamp/default unit tests) | test | unit | `test_panel.py:181-206, 451-467` | exact (in-file) |
| `tests/test_bot.py` / `test_command_views.py` / `test_interactive_package.py` | test (anti-drift) | snapshot | their own existing assertions | exact (refresh) |

---

## Pattern Assignments

### `_render_view` clone — THE TRAP (panel.py:654-701) — copy `emoji` + re-mark `default`

**Analog:** the clone path itself. It rebuilds **bare** Button/Select objects that today copy
ONLY `label/custom_id/style/row/disabled` (Button) and `placeholder/options/row/disabled`
(Select) — it does **NOT** carry `emoji` or re-apply `SelectOption(default=)`.

**Current Button clone (panel.py:681-690) — emoji NOT copied:**
```python
if isinstance(child, discord.ui.Button):
    view.add_item(
        discord.ui.Button(
            label=child.label,
            custom_id=child.custom_id,
            style=child.style,
            row=child.row,
            disabled=disabled,
        )
    )
```
**Planner task:** add `emoji=child.emoji,` to this clone (discord.py preserves `.emoji` as a
`PartialEmoji`/str on the source child, so `child.emoji` round-trips). Without it, emoji vanish
on every disabled-ack (`on_command`/`on_forecast` ① at panel.py:506-509, 575-578) and every
collapse render (② at panel.py:534-538, 602-606) — i.e. on the most common render paths.

**Current Select clone (panel.py:691-700) — `default` NOT re-applied:**
```python
elif isinstance(child, discord.ui.Select):
    view.add_item(
        discord.ui.Select(
            custom_id=child.custom_id,
            placeholder=child.placeholder,
            options=list(child.options),   # ← blind copy; default mark not re-derived
            row=child.row,
            disabled=disabled,
        )
    )
```
**Planner task:** rebuild the options from `self._selected_location` instead of `list(child.options)`:
```python
options=[
    discord.SelectOption(label=o.value, value=o.value,
                         default=(o.value == self._selected_location))
    for o in child.options
]
```
(or copy `o.default` from a source that was already re-marked). A test MUST assert the cloned
view's emoji + default survive — not just the freshly-built `__init__` view (Pitfall 1).

**Note:** `_render_view` builds a plain `discord.ui.View` (line 676) with plain
`discord.ui.Button`/`discord.ui.Select` clones — NOT the `CmdButton`/`LocationSelect` subclasses
(routing happens on the registered persistent `self`, not the clone). So the emoji/default must
be threaded into these **plain** constructors, independent of the `_EMOJI` dict used at `__init__`.

---

### Emoji on buttons (panel.py:105-113 `_LABELS`, panel.py:174-180 `CmdButton.__init__`)

**Analog:** the `_LABELS` keyed dict + `CmdButton.__init__`'s `super().__init__(label=_LABELS[name], …)`.

**Current `_LABELS` (panel.py:105-113):**
```python
_LABELS: dict[str, str] = {
    "weather": "Weather", "uv": "UV", "next-cloudy": "Next Cloudy",
    "sun": "Sun", "wind": "Wind", "status": "Status", "alerts": "Alerts",
}
```
**Current `CmdButton.__init__` (panel.py:174-180):**
```python
def __init__(self, name: str, panel: "PanelView", *, row: int) -> None:
    super().__init__(
        label=_LABELS[name],
        custom_id=f"wb:cmd:{name}",
        style=discord.ButtonStyle.primary,
        row=row,
    )
```
**Planner task (D-04/D-05, recommended parallel dict):** add an `_EMOJI` dict mirroring
`_LABELS`, then pass `emoji=_EMOJI[name]`. Emoji are a single unicode `str` (verified accepted by
`discord.ui.Button(emoji=…)` in installed 2.7.1). Locked set:
`weather 🌡️ · uv 🧴 · next-cloudy ☁️ · sun ☀️ · wind 💨 · status 🟢 · alerts ⚠️`.
The forecast/toggle buttons are constructed at their own sites — apply emoji there too:
- `ForecastToggleButton.__init__` (panel.py:241-247, `label="Forecast"`) → `emoji="📅"`.
- The four `ForecastButton` constructions in `PanelView.__init__` (panel.py:339-362) → `Weekday
  Detailed 📋 · Weekday Compact 📝 · Weekend Detailed 🏖️ · Weekend Compact 🌴` (thread an `emoji=`
  kwarg through `ForecastButton.__init__` at panel.py:204-219, mirroring its existing `label=` kwarg).

**`emoji=` is a separate param — NEVER concatenate into the label string** (D-04 / UI-SPEC).

---

### Dropdown `default=True` re-mark (panel.py:265-271 `LocationSelect.__init__`)

**Analog:** the existing options comprehension.

**Current (panel.py:265-271) — no `default`:**
```python
def __init__(self, panel: "PanelView", locations: list[str]) -> None:
    super().__init__(
        custom_id="wb:loc:select",
        placeholder="Location",
        options=[discord.SelectOption(label=n, value=n) for n in locations],
        row=0,
    )
```
**Planner task (D-02):** mark the selected option. Since `LocationSelect.__init__` runs *before*
`self._selected_location` is set in `PanelView.__init__` (the `add_item(LocationSelect(...))` at
panel.py:327 precedes nothing — `_selected_location` is set at panel.py:319, BEFORE line 327, so
it IS available), pass the selection in:
```python
options=[
    discord.SelectOption(label=n, value=n, default=(n == panel._selected_location))
    for n in locations
]
```
**Selection state lives ONLY in `_selected_location`** (panel.py:319, set by `on_select` at
panel.py:471) — NEVER read back from `Select.values` (empty for default options, discord.py
#7284; this is the existing Pitfall-3 rule already enforced at panel.py:260-262, 318-319).
The re-mark MUST also be rebuilt in the `_render_view` Select clone (see Pattern A above) and
survives `add_view` reconstruction because `__init__` re-derives it from in-memory state.

---

### `render_embed` — `📍` line + `Updated <t:>` stamp (bot.py:194-261)

**Analog:** the embed builder itself; `embed.timestamp = discord.utils.utcnow()` already lives at
**bot.py:260** (D-07 — keep it).

**Current head (bot.py:215-217) — title + color, no description:**
```python
embed = discord.Embed(
    title=_clip(reply.title, _MAX_TITLE), color=BRIEFING_COLOR_INT
)
```
**Current tail (bot.py:260-261) — KEEP the native timestamp (D-07):**
```python
embed.timestamp = discord.utils.utcnow()
return embed
```
**Planner task (D-01/D-06):** add a `description` built from a default-`None` `location` kwarg so
the line goes in the **body, never the title** (`<t:>` does not render in a title — D-07):
```python
def render_embed(reply: CommandReply, *, location: str | None = None) -> discord.Embed:
    ...
    unix = int(discord.utils.utcnow().timestamp())
    desc_lines = []
    if location is not None:                 # suppress on argless (status/alerts) — D-01
        desc_lines.append(f"📍 {location}")
    desc_lines.append(f"Updated <t:{unix}:t> (<t:{unix}:R>)")
    embed = discord.Embed(
        title=_clip(reply.title, _MAX_TITLE),
        description="\n".join(desc_lines),
        color=BRIEFING_COLOR_INT,
    )
```
**Signature must stay source-compatible.** Use a default-`None` keyword arg so the existing
callers that pass no location keep working unchanged. Call sites to thread the location through:

| Call site | File:line | Pass `location=` ? |
|-----------|-----------|--------------------|
| panel `on_command` result | `panel.py:536` | `location=arg` (the `_selected_location` or `None` for argless — already computed at panel.py:499) |
| panel `on_forecast` result | `panel.py:604` | `location=self._selected_location` (forecast always location-bearing) |
| inbound `on_message` reply | `bot.py:510` | optional — pass the resolved location if available, else leave `None` |
| idle panel embed | `bot.py:351` | leave `None` (no selection context) |
| `__init__.py` export | `interactive/__init__.py:3,43` | unchanged (re-export only) |

UI-SPEC line order: `📍` (line 1, suppressed when argless) → `Updated <t:>` (line 2, always) →
existing `add_field` loop. The `add_field`/overflow/body-split logic (bot.py:219-259) is
**unchanged** — the new lines are description-level, so field-only snapshot tests stay green.

---

### Hanging-callback live-scheduler proof (NEW test in tests/test_panel.py)

**Analog 1 — the live-scheduler skeleton (`test_scheduler.py:1919-1989`):** start a REAL
`BackgroundScheduler`, register a sentinel `IntervalTrigger(seconds=0.1)` job, poll a
`threading.Event` against a `time.monotonic() + 5.0` deadline, assert the sentinel fired AND
`scheduler.running is True`, `shutdown(wait=False)` in `finally`. Copy this structure verbatim:
```python
sentinel_fired = threading.Event()
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: sentinel_fired.set(),
                  trigger=IntervalTrigger(seconds=0.1), id="__sentinel__",
                  misfire_grace_time=None, coalesce=True)
scheduler.start()
try:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not sentinel_fired.is_set():
        time.sleep(0.05)
    assert sentinel_fired.is_set()    # the "briefing" fired despite the hang
    assert scheduler.running is True  # scheduler thread alive
finally:
    scheduler.shutdown(wait=False)
```

**Analog 2 — the panel isolation harness (`test_panel.py:475-497`
`test_callback_raise_isolated`):** use `_panel()`, `_FakeHolder`, `_make_panel(...)`,
`_stub_handler(monkeypatch, "sun", _hang)`, `fake_interaction(user_id=_OPERATOR_ID,
custom_id="wb:cmd:sun")`, and drive `view.on_command(...)`. The raising case asserts the
envelope swallows + `edit_original_response` still fires; the **hanging** case asserts the
*briefing sentinel* fires while the callback is provably wedged.

**The hang shape (D-08a — MUST be `await`, NOT CPU spin):** the stubbed handler must yield via
`await asyncio.Event().wait()` (run the callback via `asyncio.run(view.on_command(...))` in a
daemon thread so it never returns). Document in the docstring WHY `await`-shaped: all blocking
panel work is already off-loop via `run_in_executor` (dispatch.py:166-188), so the realistic
wedge is a never-completing `await`, not a GIL-holding `while True: pass` (which would prove
GIL-throttling, a different thing — Pitfall 3).

**Note:** `_stub_handler` swaps `registry.BY_NAME[name].handler`, but the handler runs *inside
`dispatch_spec`'s `run_in_executor`*. To hang the callback at the `await` level (D-08a), prefer
hanging at the panel-callback coroutine (e.g. monkeypatch `dispatch_spec` to `await
asyncio.Event().wait()`, or stub the handler to block and assert the executor thread is occupied)
— the planner picks the cleanest seam; what matters is the wedge yields via `await` on the loop,
not the briefing thread.

---

### D-08b executor-sharing audit (NEW test or documented note in tests/test_panel.py)

**Analog:** `dispatch.py:166-188` — the panel's read-only fetch path is the ONLY caller of the
asyncio **default** executor:
```python
result = await loop.run_in_executor(None, cache.lookup, lookup_name, config, suffix)   # 166-168
...
return await loop.run_in_executor(None, lambda: dispatch_reply(...))                    # 179-188
```
`run_in_executor(None, …)` = the asyncio default `ThreadPoolExecutor`. The briefing runs under
APScheduler `BackgroundScheduler`'s OWN pool on a separate OS thread (test_scheduler.py confirms),
so the two pools are distinct objects and the briefing spine never touches `dispatch.py`.
**Planner task (recommended: lightweight assertion):** assert no briefing/scheduler code path
calls `loop.run_in_executor(None, …)`, OR assert the scheduler's executor and the asyncio default
executor are distinct — cheap regression insurance (Pitfall 4). A documented code-path note alone
is acceptable per Claude's Discretion, but an assertion is preferred.

---

### Anti-drift snapshot updates

**Analog:** each test's own existing assertion. The new `📍`/`Updated` lines are **description**-
level; tests that compare `embed.fields`/`embed.title` stay green, tests that touch `description`
or option `default` need a deliberate refresh.

| Test | File:line | Asserts | Expected impact |
|------|-----------|---------|-----------------|
| panel weather parity | `test_panel.py:462-467` | `fields`/`title` vs `build_inbound_embed` | **green** (field/title only) — confirm |
| panel forecast parity | `test_panel.py:800-804` | `fields`/`title` vs `render_embed(canonical)` | **green** (both sides gain the line if same `render_embed`) — confirm |
| select options | `test_panel.py:181-206` | `[opt.value for opt in select.options]` | **green** for value list; **add** a `default=` assertion |
| `render_embed` bounds | `test_bot.py:733-768` | field/title bounding (WR-02/03) | **green** (fields only) — confirm description doesn't trip bounds |
| command-view parity | `test_command_views.py:60,73,80` | `title`/`fields` byte-identical | **green** (description-level addition) — confirm |
| package exports | `test_interactive_package.py:44,54` | imports/exports `render_embed` | **green**; if signature gains `location=` kwarg, confirm export unchanged |

For each: run the suite, confirm ONLY the intended description/`default` addition changed, then
refresh the snapshot deliberately.

---

## Shared Patterns

### Per-callback non-propagating envelope (the isolation seam PANEL-11 re-proves)
**Source:** `panel.py:497-541` (`on_command`), mirrored in `on_forecast` (567-612),
`on_forecast_toggle` (623-632), `on_select` (470-479), with `View.on_error` backstop (634-652).
**Apply to:** nothing new — the hanging-callback path **inherits** this same envelope unchanged
(D-08: zero production change to the isolation path). The shape every callback follows:
```python
try:
    ...   # ① response.edit_message ack  ② edit_original_response result
except Exception:  # noqa: BLE001 — non-propagating
    _log.exception("panel … callback failed", custom_id=…)
    await self._safe_error_edit(interaction)
```

### Single shared render path
**Source:** `render_embed` (`bot.py:194-261`) — the one surface-agnostic embed builder used by
panel result renders (panel.py:536, 604), the inbound `on_message` reply (bot.py:510), and the
idle embed (bot.py:351). **Apply to:** the `📍` line + `Updated` stamp go HERE, not per-callback,
so panel/bot/CLI cannot drift.

### Build-time layout guard (must stay untouched & green)
**Source:** `_assert_layout` / `_assert_layout_children` (`panel.py:366-416`), called at
panel.py:364. **Apply to:** confirm nothing this phase trips it — emoji/`📍`/`Updated` are all
**non-component** (no new slot); the grid stays 5/5 / 13 children.

### Gateway-free test harness
**Source:** `test_panel.py:42-163` (`_panel`, `_FakeHolder`/`_FakeConfig`/`_FakeLocation`,
`_SpyCache`, `_make_panel`, `_stub_handler`, `_run = asyncio.run`) + `conftest.py:178-227`
(`fake_interaction` — a `MagicMock` Interaction with AsyncMock `response.edit_message` /
`edit_original_response`). **Apply to:** all new PANEL-12/13 unit tests + the hanging-callback test
build on these — no live gateway, no network.

---

## No Analog Found

None. Every change has a direct in-file or sibling-file precedent (this is a polish phase over
fully-assembled Phase 17–19 code). The only genuinely new *test shape* — a live-scheduler proof
fired against a hanging asyncio callback — is composed from two existing templates
(`test_scheduler.py:1919` + `test_panel.py:475`), not invented.

## Metadata

**Analog search scope:** `weatherbot/interactive/` (panel.py, bot.py, dispatch.py, __init__.py),
`tests/` (test_panel.py, test_scheduler.py, test_bot.py, test_command_views.py,
test_interactive_package.py, conftest.py).
**Files scanned:** 11.
**Pattern extraction date:** 2026-06-26.
