# Phase 19: Forecast Two-Tier Sub-Options - Pattern Map

**Mapped:** 2026-06-26
**Files analyzed:** 6 (all MODIFIED in place — no new files)
**Analogs found:** 6 / 6 (every new symbol has an in-file analog in the same module)

> **Important framing:** This phase adds **surface, not logic** (RESEARCH "Key
> insight"). Every new symbol has a *same-module* analog — the closest analog for
> each new panel symbol lives **inside `panel.py` itself**, and for the seam edit
> **inside `dispatch.py` itself**. The job is to copy the established in-file shape,
> not import a pattern from a distant module. Honor `interactive/` import-acyclicity:
> module-top light imports, heavy types under `TYPE_CHECKING` (already the discipline
> in every file below).

---

## File Classification

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------|------|-----------|----------------|---------------|
| `weatherbot/interactive/dispatch.py` | service (shared dispatcher) | request-response / off-loop fetch | `dispatch_spec` itself (the existing forecast `parse_forecast_flags` branch) | exact (same function, additive param) |
| `weatherbot/interactive/panel.py` — `on_forecast` | provider (component callback) | request-response / off-loop | `PanelView.on_command` | exact (mirror the callback contract) |
| `weatherbot/interactive/panel.py` — `ForecastButton` / `ForecastToggleButton` | component (Button subclass) | event-driven (tap) | `CmdButton` | exact (Button subclass + back-ref + delegate) |
| `weatherbot/interactive/panel.py` — `_render_view` / `_disabled_copy` extension | utility (view builder) | transform (clone children) | `PanelView._disabled_copy` | exact (same fresh-view clone technique) |
| `weatherbot/interactive/panel.py` — `_assert_layout` extension | utility (build-time guard) | batch (validation) | `PanelView._assert_layout` body | exact (extend the assert body) |
| `weatherbot/interactive/panel.py` — `on_select` collapse update | provider (component callback) | request-response | `PanelView.on_select` | exact (one-line render change) |
| `weatherbot/interactive/command.py` — `ForecastFlags` construction | model (frozen dataclass) | — | `parse_forecast_flags` return-site usage | read-only reuse (panel constructs directly) |
| `weatherbot/interactive/registry.py` — `BY_NAME["weekday/weekend-forecast"]` | config (registry lookup) | — | `panel.py:80-84` curated build-time assert | read-only resolve (+ optional import-time assert) |
| `tests/test_dispatch.py` — flags= seam tests | test | request-response | `test_dispatch_spec_forecast_widens_cache_key_with_3arg_lookup` | exact (same `_SpyCache`/`_FakeSpec` harness) |
| `tests/test_panel.py` — reveal/collapse + on_forecast + layout tests | test | request-response | `test_location_button_uses_selection` / `test_view_persistent_and_layout_bounded` | exact (same `fake_interaction` + `_stub_handler` harness) |

---

## Pattern Assignments

### `weatherbot/interactive/dispatch.py` — additive `flags=None` on `dispatch_spec`

**Analog:** `dispatch_spec` itself, `dispatch.py:105-179`. This is a behavior-preserving
extension (D-02 HARD CONSTRAINT), NOT a refactor. The `flags is None` branch must run the
existing parse path **byte-for-byte**.

**Current signature** (`dispatch.py:105-113`):
```python
async def dispatch_spec(
    spec: CommandSpec,
    arg: str | None,
    *,
    cache: ForecastCache,
    config: Config,
    loop: asyncio.AbstractEventLoop,
    daemon_state: DaemonState | None,
) -> CommandReply:
```
→ add **one** keyword-only param: `flags: ForecastFlags | None = None`. (`ForecastFlags` is
already imported under `TYPE_CHECKING`, `dispatch.py:51` — keep it there.)

**The existing forecast branch to guard** (`dispatch.py:142-163`) — the ONLY change is wrapping
the parse in `if flags is None:`:
```python
    flags: ForecastFlags | None = None          # ← becomes the param default; drop this local
    result: LookupResult | None = None

    if spec.takes_location:
        is_forecast = spec.group == "Forecast"
        lookup_name = arg
        suffix = None
        if is_forecast:
            flags = parse_forecast_flags(arg)            # ← guard: only when flags is None (D-02)
            lookup_name = flags.location
            suffix = forecast_cache_suffix(spec.name, flags)
        if is_forecast:
            result = await loop.run_in_executor(
                None, cache.lookup, lookup_name, config, suffix
            )
        else:
            result = await loop.run_in_executor(
                None, cache.lookup, lookup_name, config
            )
```
Target shape (RESEARCH Pattern 4 — minimal diff):
```python
        if is_forecast:
            if flags is None:                            # NEW guard (D-02): existing path untouched
                flags = parse_forecast_flags(arg)
            # else: caller-provided flags drive lookup_name/suffix directly (D-01)
            lookup_name = flags.location
            suffix = forecast_cache_suffix(spec.name, flags)
```
`dispatch_reply` (`dispatch.py:60-102`) is **unchanged** — its `group == "Forecast"` branch
already does `spec.handler(result, flags)` (`dispatch.py:88-90`), and `flags` is threaded down
verbatim in the existing tail `run_in_executor` call (`dispatch.py:170-179`).

**Anti-drift rule (Pitfall 3):** the only diff inside the `is_forecast` block is the
`if flags is None:` guard. Any other reorder/rewrite of the parse breaks the byte-identical
suite (`test_dispatch.py`, `test_bot.py`, `test_command.py`, `test_command_views.py`).

---

### `weatherbot/interactive/panel.py` — `on_forecast` callback

**Analog:** `PanelView.on_command`, `panel.py:328-374`. Mirror its single-ack contract +
per-callback envelope exactly; differ ONLY in (a) build `ForecastFlags` directly + pass
`flags=`, (b) collapse on the result render (D-03).

**The contract to mirror** (`panel.py:344-374`):
```python
        try:
            spec = registry.BY_NAME[name]  # allow-list (KeyError → caught below)
            arg = self._selected_location if spec.takes_location else None  # D-04
            # ① the SINGLE response.* call — acks (<3s), shows the cue, disables taps.
            await interaction.response.edit_message(
                content=_FETCHING_CUE, view=self._disabled_copy()
            )
            loop = asyncio.get_running_loop()
            config = self._holder.current()  # per-tap snapshot (hot-reload picked up)
            try:
                reply = await dispatch_spec(
                    spec, arg, cache=self._cache, config=config,
                    loop=loop, daemon_state=self._daemon_state,
                )
            except UnknownLocationError as exc:
                await interaction.edit_original_response(
                    content=str(exc), embed=None, view=self
                )
                return
            # ② result lands via the FOLLOWUP path — NOT a second response.* call.
            await interaction.edit_original_response(
                content=None, embed=render_embed(reply), view=self
            )
        except Exception:  # noqa: BLE001 — non-propagating
            _log.exception("panel command callback failed", custom_id=f"wb:cmd:{name}")
            await self._safe_error_edit(interaction)
```

**`on_forecast` deltas** (RESEARCH Pattern 3):
- resolve `spec = registry.BY_NAME[command_name]` where `command_name ∈ {"weekday-forecast","weekend-forecast"}`
- build flags directly: `flags = ForecastFlags(variant=variant, location=self._selected_location)` — `add`/`drop` left at their `frozenset()` defaults (D-01); read `self._selected_location`, **never** re-read the Select (Pitfall 5, mirrors `on_command`'s `arg` source)
- ack with the disabled-expanded view: `view=self._render_view(expanded=True, disabled=True)` (so double-taps on the revealed grid are neutralized)
- dispatch with `arg=None` + `flags=flags`: `await dispatch_spec(spec, None, ..., flags=flags)`
- **both** terminal renders (result AND the `UnknownLocationError` catch) attach the **collapsed** base view (`view=self._render_view(expanded=False)`) — this is the "result-then-collapse" of D-03
- envelope log custom_id: `f"wb:fc:{command_name}:{variant}"`

`ForecastFlags` import: add `from weatherbot.interactive.command import ForecastFlags` at
**module top** (it is a light frozen dataclass — acyclic; `dispatch.py` already imports from
`command` at module top, `dispatch.py:43-46`). Do NOT lazy-import it in the handler.

---

### `weatherbot/interactive/panel.py` — `ForecastButton` / `ForecastToggleButton`

**Analog:** `CmdButton`, `panel.py:147-168`. A `discord.ui.Button` subclass holding a
back-reference to its `PanelView` and delegating its `callback` to a panel method.

**Full analog to copy** (`panel.py:147-168`):
```python
class CmdButton(discord.ui.Button):
    def __init__(self, name: str, panel: "PanelView", *, row: int) -> None:
        super().__init__(
            label=_LABELS[name],
            custom_id=f"wb:cmd:{name}",
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self._name = name
        self._panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_command(interaction, self._name)
```

**`ForecastButton` deltas** (carries `(command_name, variant)`, RESEARCH Pattern 3 / Open
Question 2 — a small dedicated class is the recommended discretion call):
- `__init__(self, panel, command_name, variant, *, custom_id, label, row)` — stores `self._command_name`, `self._variant`, `self._panel`
- `super().__init__(label=label, custom_id=custom_id, style=discord.ButtonStyle.primary, row=row)` — uniform `primary` style (UI-SPEC Color: variant buttons share ONE style; no per-variant color)
- `callback` → `await self._panel.on_forecast(interaction, command_name=self._command_name, variant=self._variant)`

**`ForecastToggleButton` deltas:**
- `custom_id="wb:forecast:toggle"`, `label="Forecast"` (optionally `"Forecast ▸"`/`"Forecast ▾"` textual caret — D-07 discretion, structural glyph not emoji), `row=2`, `ButtonStyle.secondary` (UI-SPEC: disclosure affordance — meaning carried by label, not color)
- `callback` → a `on_forecast_toggle` method that flips reveal state via a single `interaction.response.edit_message(view=self._render_view(expanded=<toggled>))` (RESEARCH Pattern 2)

**Why both stay `discord.ui.Button` subclasses (D-09):** keeps the existing `_disabled_copy`
`isinstance(child, discord.ui.Button)` branch (`panel.py:412-421`) covering them with **no new
branch**. Add these to `__all__` (`panel.py:62`) per the export convention.

**`custom_id`/`label` budget** (all pass the existing asserts): `wb:fc:weekday:detailed`,
`wb:fc:weekday:compact`, `wb:fc:weekend:detailed`, `wb:fc:weekend:compact`, `wb:forecast:toggle`
(all < 100 chars); `Weekday Detailed` … `Weekend Compact` (all < 80 chars).

---

### `weatherbot/interactive/panel.py` — `__init__` row 2-4 wiring

**Analog:** the existing `__init__` curated-loop wiring, `panel.py:238-248`:
```python
        # row 0: the location dropdown.
        self.add_item(LocationSelect(self, locations))
        # row 1: the five location-taking command buttons (curated order).
        for name in _LOCATION_CMDS:
            self.add_item(CmdButton(name, self, row=1))
        # row 2: the two argless command buttons (curated order).
        for name in _ARGLESS_CMDS:
            self.add_item(CmdButton(name, self, row=2))
        # rows 3–4 intentionally empty (Phase 19/20).      ← THIS phase fills them

        self._assert_layout(locations)
```
**Delta:** after the `_ARGLESS_CMDS` loop, add the `ForecastToggleButton(self, row=2)` (row 2
now 3 buttons: Status · Alerts · Forecast — Forecast LAST per UI-SPEC ordering), then the four
`ForecastButton`s (row 3 = weekday pair, row 4 = weekend pair, exact order per UI-SPEC). All 13
children build in `__init__` so `add_view` registers every `custom_id` (RESEARCH Pattern 1 — the
registered view MUST carry the full set; never `add_item`/`remove_item` post-registration).

**Optional import-time registry assert** (mirrors `panel.py:80-84` curated allow-list guard):
```python
for _name in (*_LOCATION_CMDS, *_ARGLESS_CMDS):
    assert _name in registry.BY_NAME, (  # existing
        f"panel curated command {_name!r} is not in registry.BY_NAME ..."
    )
```
→ extend the tuple with `"weekday-forecast", "weekend-forecast"` (or add a parallel assert) so a
registry rename trips at import (RESEARCH "Registry resolution" example).

---

### `weatherbot/interactive/panel.py` — `_render_view` / `_disabled_copy`

**Analog:** `PanelView._disabled_copy`, `panel.py:396-432`. The "build a fresh `timeout=None`
view carrying clones of every child" technique — the SAME mechanism reveal/collapse needs.

**Full analog to copy/parameterize** (`panel.py:410-432`):
```python
        view = discord.ui.View(timeout=None)
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                view.add_item(
                    discord.ui.Button(
                        label=child.label, custom_id=child.custom_id,
                        style=child.style, row=child.row, disabled=True,
                    )
                )
            elif isinstance(child, discord.ui.Select):
                view.add_item(
                    discord.ui.Select(
                        custom_id=child.custom_id, placeholder=child.placeholder,
                        options=list(child.options), row=child.row, disabled=True,
                    )
                )
        return view
```

**Recommended merge (RESEARCH Pattern 2 + Open Question 1 — kills the IN-03 two-path drift):**
parameterize into `_render_view(self, *, expanded: bool, disabled: bool = False)`:
- iterate `self.children`; **skip** clones whose `row in (3, 4)` when `not expanded` (collapsed omits the forecast sub-grid)
- clone each remaining child with `disabled=disabled` (so `disabled=True` reproduces today's `_disabled_copy` behavior; `disabled=False` is a live render view)
- have `_disabled_copy` delegate to `_render_view(expanded=True, disabled=True)` (or replace its call sites) so there is ONE child-cloning path

**IN-03 / D-09 verification obligation:** because the new buttons are plain `discord.ui.Button`
subclasses, the `isinstance(child, discord.ui.Button)` branch already rebuilds them — verify
(via test), don't add a branch. If a sub-button were NOT a plain `Button`, a new branch is
required (D-09 caveat).

---

### `weatherbot/interactive/panel.py` — `_assert_layout` extension (D-08)

**Analog:** the existing `_assert_layout` body, `panel.py:250-274`:
```python
    def _assert_layout(self, locations: list[str]) -> None:
        rows = {child.row for child in self.children if child.row is not None}
        assert len(rows) <= _MAX_ROWS, (  # noqa: S101
            f"panel uses {len(rows)} rows (>{_MAX_ROWS})"
        )
        assert len(locations) <= _MAX_OPTIONS, (  # noqa: S101
            f"panel has {len(locations)} locations (>{_MAX_OPTIONS} Select options)"
        )
        for child in self.children:
            custom_id = getattr(child, "custom_id", None)
            assert custom_id is not None and len(custom_id) <= _MAX_CUSTOM_ID, (...)
            label = getattr(child, "label", None)
            if label is not None:
                assert len(label) <= _MAX_LABEL, (...)
```

**Deltas (D-08 — the panel is now 5/5 rows, the guard is load-bearing):**
- add module constants beside the existing caps (`panel.py:69-72`, which already has
  `_MAX_CUSTOM_ID`/`_MAX_LABEL`/`_MAX_ROWS`/`_MAX_OPTIONS`): `_MAX_PER_ROW = 5`,
  `_MAX_CHILDREN = 25`
- **per-row assert** (NEW — currently only `add_item` raises): `Counter` the child rows, assert
  each `n <= _MAX_PER_ROW`
- **total-children assert** (NEW — currently unchecked): `assert len(self.children) <= _MAX_CHILDREN`
- keep the existing rows / options / custom_id / label asserts verbatim

RESEARCH Pattern 6 gives the exact target body (uses `collections.Counter`).

---

### `weatherbot/interactive/panel.py` — `on_select` collapse (D-04)

**Analog:** `PanelView.on_select`, `panel.py:312-326`:
```python
        try:
            self._selected_location = value
            await interaction.response.edit_message(view=self)   # ← renders the live panel
        except Exception:  # noqa: BLE001
            _log.exception("panel select callback failed", custom_id="wb:loc:select")
            await self._safe_error_edit(interaction)
```
**Delta:** the ack render must attach the **collapsed** base view, not `self` —
`view=self._render_view(expanded=False)` (a dropdown change is a non-toggle action → collapse,
D-04). Same single-`response.edit_message` ack, same envelope. The same "attach collapsed base"
substitution applies to `on_command`'s terminal renders (`panel.py:365,370`) so any non-forecast
command tap also collapses (D-04).

---

### `weatherbot/interactive/command.py` — `ForecastFlags` (read-only reuse)

**No edit to `command.py`.** The panel **constructs** `ForecastFlags` directly. Analog usage —
the dataclass + its defaults (`command.py:117-135`):
```python
@dataclass(frozen=True)
class ForecastFlags:
    variant: str = "detailed"
    add: frozenset[str] = frozenset()
    drop: frozenset[str] = frozenset()
    location: str | None = None
```
Panel builds `ForecastFlags(variant=<"detailed"|"compact">, location=self._selected_location)` —
`add`/`drop` stay at the `frozenset()` defaults (D-01: the command name encodes the day set; the
panel adds no day deltas). Consumed by `_render` (`commands/forecast.py:76-110`), which reads
`flags.variant` / `flags.add` / `flags.drop`. The `parse_forecast_flags` parser
(`command.py:138-186`) is deliberately **bypassed** — `variant` is a compile-time literal, never
user-typed (Security V5).

---

### `weatherbot/interactive/registry.py` — `BY_NAME` forecast lookups (read-only)

**No edit to `registry.py`.** Both specs already exist (`registry.py:67-78`):
`weekday-forecast` / `weekend-forecast`, `group="Forecast"`, `takes_location=True`, handlers
wired to `forecast.weekday_forecast` / `forecast.weekend_forecast` (`registry.py:111-112`). The
panel resolves them read-only via `registry.BY_NAME[command_name]` (exactly as `on_command` does
at `panel.py:345`). The only registry *touch* is the optional import-time presence assert noted
in the `__init__` section above (analog: `panel.py:80-84`).

---

## Test Pattern Assignments

### `tests/test_dispatch.py` — `flags=` seam tests

**Analogs:** `test_dispatch_spec_forecast_widens_cache_key_with_3arg_lookup`
(`test_dispatch.py:226-259`) and `test_dispatch_spec_plain_weather_uses_2arg_lookup`
(`test_dispatch.py:262-289`). Reuse the existing `_FakeSpec` (`test_dispatch.py:28-36`) +
`_SpyCache` (`test_dispatch.py:212-223`) + `_recording_handler` (`test_dispatch.py:50-55`) +
the `asyncio.new_event_loop()` driver pattern verbatim.

**Harness to copy** (`test_dispatch.py:236-259`):
```python
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(
            dispatch_spec(spec, "home +sat", cache=cache, config=_FakeConfig(),
                          loop=loop, daemon_state=None)
        )
    finally:
        loop.close()
    (name, _config, rest), = cache.calls
    assert name == "home"
    assert len(rest) == 1 and rest[0] is not None
    (handler_args, _kwargs), = calls
    fetched_result, flags = handler_args
    assert flags is not None and flags.location == "home"
```

**New nodes (RESEARCH Test Map / Wave 0 Gaps):**
- `test_dispatch_spec_flags_passthrough_skips_parse` — pass `flags=ForecastFlags(variant="compact", location="travel")` with `arg=None` (or a deliberately *different* arg string); assert the recorded `cache.lookup` name == `"travel"` (from `flags.location`, NOT the arg) and the handler received the **same** flags object → proves `parse_forecast_flags` was skipped (D-01).
- `test_dispatch_spec_flags_none_is_byte_identical` — assert `flags=None` (explicit) yields the identical lookup-name/suffix/handler-args as the existing no-`flags`-kwarg call → proves the additive seam is behavior-preserving (D-02). (Import `ForecastFlags` from `weatherbot.interactive.command` at module top, alongside the existing imports `test_dispatch.py:23-25`.)

### `tests/test_panel.py` — reveal/collapse + on_forecast + layout tests

**Analogs:** `test_location_button_uses_selection` (`test_panel.py:211-241`),
`test_single_ack_before_fetch` (`test_panel.py:280-302`),
`test_view_persistent_and_layout_bounded` (`test_panel.py:398-417`). Reuse the existing
`_FakeHolder` / `_SpyCache` / `_make_panel` / `_stub_handler` stand-ins (`test_panel.py:87-163`)
and the `fake_interaction` fixture (conftest `test_panel.py` consumers) verbatim — **no new
conftest fixtures needed** (RESEARCH Wave 0 Gaps).

**Selection-then-dispatch harness to copy** (`test_panel.py:232-241`):
```python
    select_interaction = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:loc:select")
    _run(view.on_select(select_interaction, "travel"))
    sun_interaction = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:cmd:sun")
    _run(view.on_command(sun_interaction, "sun"))
    assert cache.calls[-1][0] == "travel", "the fetch must use _selected_location"
```

**Single-ack assertion shape to copy** (`test_panel.py:301-302`):
```python
    interaction.response.edit_message.assert_awaited_once()
    interaction.response.send_message.assert_not_awaited()
```

**New nodes (RESEARCH Phase Requirements → Test Map, `test_panel.py` column):**
- `test_forecast_toggle_reveal` — tap the toggle (`view.on_forecast_toggle`), assert the `view` passed to `response.edit_message` *includes* rows 3-4 children; re-tap → collapsed view *excludes* rows 3-4 (D-03 reveal + plain-toggle re-collapse).
- `test_on_forecast_dispatch` — select "travel", monkeypatch/spy `dispatch_spec` (or use `_stub_handler` on the forecast handler), drive `view.on_forecast(interaction, command_name="weekday-forecast", variant="compact")`; assert the captured `ForecastFlags` has `variant=="compact"`, `location=="travel"`, `add==frozenset()`, `drop==frozenset()`, and that `dispatch_spec` got the `BY_NAME["weekday-forecast"]` spec with `flags=` set (criterion 1/2 — same shared seam).
- `test_collapse_on_action` — after `on_forecast` (and after a non-forecast `on_command`, and after `on_select`), assert the terminal `edit_original_response`/`edit_message` `view=` argument *excludes* rows 3-4 (D-04 collapse-on-any-non-toggle-action).
- `test_forecast_custom_ids_registered` — assert all four `wb:fc:*` + `wb:forecast:toggle` appear in `PanelView(...).children` custom_ids (so `add_view` registers them → post-restart routing, D-05). Analog: the child-walk in `test_view_persistent_and_layout_bounded` (`test_panel.py:410-417`).
- `test_forecast_matches_registry` — the panel forecast reply renders to the same fields as the registry `weekday-forecast` spec's reply (no parallel logic). Analog: `test_weather_spec_byte_identical` (`test_panel.py:442-464`).
- `test_layout_full_panel_fits` — construct a full `PanelView` (the `__init__` assert runs); assert no raise at 13 children / 5 rows / ≤5 per row. Analog: `test_view_persistent_and_layout_bounded`.
- `test_layout_overflow_trips_assert` — build an over-cap layout (6th row / 26th child / 6-per-row / 101-char custom_id / 81-char label) and assert `AssertionError` (criterion 3 — "a future addition can't silently overflow"). Use `pytest.raises(AssertionError)` around a `_assert_layout` call on a hand-built over-cap child set.

---

## Shared Patterns

### Single-ack defer-then-edit (D-14/D-15)
**Source:** `panel.py:344-371` (`on_command`).
**Apply to:** `on_forecast` and `on_forecast_toggle`.
Exactly ONE `interaction.response.*` per tap (the `edit_message` cue/ack); results land via
`interaction.edit_original_response` (the followup path — a 2nd `response.*` raises
`InteractionResponded`, Pitfall 2).

### Per-callback non-propagating envelope + `on_error` backstop
**Source:** `panel.py:372-374` (the `except Exception` tail) + `panel.py:376-394` (`on_error`) +
`panel.py:434-465` (`_safe_error_edit`).
**Apply to:** `on_forecast` / `on_forecast_toggle` — wrap the whole body, log via
`_log.exception(..., custom_id=...)`, recover via `await self._safe_error_edit(interaction)`,
never re-raise. The new callbacks inherit `on_error` + `_safe_error_edit` unchanged.

### Operator gate
**Source:** `panel.py:276-310` (`interaction_check`). **Unchanged** — it already runs before
EVERY child callback, so the new toggle + 4 sub-buttons are gated with no edit (a non-operator
tap is rejected leak-free, V4). No code change; verify by test if desired.

### Fresh-view child-clone (never mutate the registered view)
**Source:** `panel.py:410-432` (`_disabled_copy`).
**Apply to:** `_render_view` (reveal/collapse) AND the merged `_disabled_copy`. Build a fresh
`discord.ui.View(timeout=None)` attaching child clones; NEVER `self.add_item`/`self.remove_item`
on the registered `PanelView` (RESEARCH Anti-Pattern 1 — would drop custom_ids from the dispatch
table and break post-restart routing).

### Build-time fail-loud assert
**Source:** `panel.py:250-274` (`_assert_layout`) + the import-time curated assert
`panel.py:80-84`.
**Apply to:** the extended `_assert_layout` (per-row + total-children, D-08) and the optional
forecast-spec import-time presence assert.

### Import acyclicity
**Source:** `panel.py:44-60` and `dispatch.py:36-55`. Module-top light imports
(`asyncio`/`discord`/`structlog`/`registry`/`render_embed`/`dispatch_spec`/`UnknownLocationError`,
and now `ForecastFlags` from `command`), heavy types under `TYPE_CHECKING`, no in-handler lazy
import.
**Apply to:** the `ForecastFlags` import in `panel.py` (module-top — it is a light frozen
dataclass; `dispatch.py:43-46` already imports from `command` at module top, proving acyclic).

---

## No Analog Found

None. Every new symbol has a same-module analog (the closest analog for each panel symbol lives
inside `panel.py`; for the seam edit, inside `dispatch.py`). This phase is surface-only —
no genuinely new mechanic, so RESEARCH.md's invented `_render_view` / `on_forecast` skeletons are
shapes derived FROM these in-file analogs, not from a foreign pattern.

## Metadata

**Analog search scope:** `weatherbot/interactive/` (panel.py, dispatch.py, command.py,
registry.py, commands/forecast.py, bot.py) + `tests/` (test_panel.py, test_dispatch.py,
conftest.py).
**Files scanned:** 9 source/test files read in full + 1 targeted (forecast.py handler signature).
**Pattern extraction date:** 2026-06-26
