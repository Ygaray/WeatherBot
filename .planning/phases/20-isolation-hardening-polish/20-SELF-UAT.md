---
status: resolved
phase: 20-isolation-hardening-polish
gate: 1
result: all_pass
started: 2026-06-27T00:00:00Z
updated: 2026-06-27T22:25:00Z
resolved: 2026-06-27T22:25:00Z   # Gate-1 PASS (autonomous); Gate-2 on-device visual (A1–A3) driven on yahir-mint at v1.3 close
---

# Phase 20 — Agent Self-UAT Log (Gate-1, autonomous)

**Plan:** 20-03 (panel polish — emoji, dropdown default, `📍` indicator, clone-survival)
**Run by:** executor agent (autonomous Gate-1)
**Date:** 2026-06-27
**Verdict:** **PASS** (all four phase success criteria proven at the data/byte level; on-device
visual confirmation deferred to Gate-2 as PARTIAL — see Deferred Obligations).

> Two-Gate UAT policy: Gate-1 is the autonomous self-UAT below (drives the real render path
> + live scheduler, byte-level evidence). Gate-2 (human on-device visual on host `yahir-mint`)
> is a deferred milestone-close obligation, NOT a phase blocker.

---

## Success-criterion evidence table

| SC | Criterion | Exact command | Evidence | Verdict |
|----|-----------|---------------|----------|---------|
| SC#1 | Briefing isolation (panel callback that hangs/raises never stops a live briefing) | `uv run pytest tests/test_scheduler.py::test_hanging_callback_never_stops_live_briefing tests/test_dispatch.py::test_briefing_path_not_on_default_executor -v` | Both PASSED (see §SC#1). A real `BackgroundScheduler` keeps firing its sentinel while the panel callback is wedged on `await asyncio.Event().wait()`; the briefing path provably does not share the asyncio default executor. | **PASS** |
| SC#2 | Visible selected-location indicator — embed `📍` line + dropdown highlight | `uv run python -c "…render_embed…"` + clone snippet (see §SC#2) | Location-bearing description = `'📍 home\nUpdated <t:…:t> (<t:…:R>)'`; argless description suppresses `📍`. Dropdown clone option `travel` `default=True`, `home` `default=False` — survives `_render_view`. | **PASS** |
| SC#3 | Emoji-coded button labels (locked D-05 set, text label kept), surviving the clone | clone snippet (see §SC#3) | All 12 controls carry their exact D-05 glyph on the `_render_view(expanded=True)` clone, with the Title-Case text label intact (emoji never concatenated). | **PASS** |
| SC#4 | "Updated" self-ageing stamp (`<t:…:t> (<t:…:R>)`) in description, never title | `uv run python -c "…render_embed…"` (see §SC#2) | Description carries `<t:…:t>` and `<t:…:R>`; `<t:` is ABSENT from the title. | **PASS** |
| Guard | `_assert_layout` stays green (zero new component slot) | `uv run pytest tests/test_panel.py -k layout -q` | `3 passed` — the full 13-child / 5×5 panel constructs without tripping the guard. | **PASS** |
| Suite | Full regression suite | `uv run pytest -q` | `649 passed` (up from 641 at 20-02; +8 new Phase-20 tests, zero anti-drift breaks). | **PASS** |

---

## SC#1 — Briefing isolation (live scheduler)

```
$ uv run pytest tests/test_scheduler.py::test_hanging_callback_never_stops_live_briefing \
                tests/test_dispatch.py::test_briefing_path_not_on_default_executor -v
tests/test_scheduler.py::test_hanging_callback_never_stops_live_briefing PASSED [ 50%]
tests/test_dispatch.py::test_briefing_path_not_on_default_executor PASSED        [100%]
========================= 2 passed, 1 warning in 0.52s =========================
```

This plan (20-03) makes ZERO production change to the isolation path — the property is
re-proven (not re-implemented) here as the load-bearing regression gate. The hang is shaped as
an `await asyncio.Event().wait()` (D-08a), the realistic wedge since all blocking panel work is
already off-loop via `run_in_executor`.

## SC#2 / SC#4 — `📍` indicator line + `Updated <t:>` stamp (byte-level)

```
$ uv run python -c "
from weatherbot.interactive.bot import render_embed
from weatherbot.interactive.commands import CommandReply
reply = CommandReply(title='Weather — home', lines=())
loc = render_embed(reply, location='home')
arg = render_embed(reply)
print(repr(loc.description)); print(repr(arg.description)); print('<t: in title:', '<t:' in (loc.title or ''))
"

=== LOCATION-BEARING description ===
'📍 home\nUpdated <t:1782521387:t> (<t:1782521387:R>)'
has 📍 home: True
has <t: in desc: True
has :t> clause: True
has :R> clause: True
<t: in TITLE: False

=== ARGLESS description ===
'Updated <t:1782521387:t> (<t:1782521387:R>)'
has 📍 (should be False): False
has <t: in desc: True
```

- Location-bearing result: `📍 home` is line 1, `Updated <t:…:t> (<t:…:R>)` is line 2 (UI-SPEC order).
- Argless (status/alerts) result: `📍` SUPPRESSED, the `Updated` line stands alone (D-01).
- The `<t:` token is in the DESCRIPTION, never the title (D-07 — it would not render in a title).

The panel result-render call sites that thread the location through (grep evidence):

```
$ grep -n "render_embed(reply, location=" weatherbot/interactive/panel.py
572:                embed=render_embed(reply, location=arg),                      # on_command (arg=None for argless)
642:                embed=render_embed(reply, location=self._selected_location),  # on_forecast (always location-bearing)
```

## SC#2 (dropdown) / SC#3 (emoji) — clone-survival (the Pitfall-1 trap, byte-level)

```
$ uv run python -c "<construct PanelView from gateway-free fakes, select 'travel', _render_view(expanded=True)>"

=== EMOJI SURVIVES CLONE (expanded=True) ===
wb:cmd:weather               emoji='🌡️'  label='Weather'
wb:cmd:uv                    emoji='🧴'  label='UV'
wb:cmd:next-cloudy           emoji='☁️'  label='Next Cloudy'
wb:cmd:sun                   emoji='☀️'  label='Sun'
wb:cmd:wind                  emoji='💨'  label='Wind'
wb:cmd:status                emoji='🟢'  label='Status'
wb:cmd:alerts                emoji='⚠️'  label='Alerts'
wb:forecast:toggle           emoji='📅'  label='Forecast'
wb:fc:weekday:detailed       emoji='📋'  label='Weekday Detailed'
wb:fc:weekday:compact        emoji='📝'  label='Weekday Compact'
wb:fc:weekend:detailed       emoji='🏖️'  label='Weekend Detailed'
wb:fc:weekend:compact        emoji='🌴'  label='Weekend Compact'

=== DROPDOWN default SURVIVES CLONE (selected=travel) ===
  option 'home' default=False
  option 'travel' default=True
```

This is the LOAD-BEARING proof: the evidence is captured from the `_render_view` **clone**
(the disabled-ack / collapse render path), not the freshly-built `__init__` view. All 12 D-05
glyphs survive on PLAIN `discord.ui.Button` clones (via `emoji=child.emoji`), labels intact;
the dropdown `default=True` is re-derived from `_selected_location` (via the rebuilt `SelectOption`
list), not blind-copied. Without the Task-1 fix both would have silently vanished on every
ack/collapse render.

## Layout guard + full suite

```
$ uv run pytest tests/test_panel.py -k layout -q
3 passed, 31 deselected, 1 warning in 0.35s

$ uv run pytest -q
649 passed, 1 warning in 38.29s
```

`649 passed` = 641 (20-02 baseline) + 8 new Phase-20 tests (emoji construction ×2, emoji
clone-survival, dropdown default construction, dropdown default clone-survival, indicator
location-bearing, indicator argless-suppression, forecast indicator). Zero anti-drift snapshot
breaks — the additions are description/`default`-level only, so the field/title parity tests
(`test_weather_spec_byte_identical`, `test_forecast_matches_registry`) stayed green untouched.

---

## Deferred Gate-2 obligations (human on-device UAT — milestone-close, NOT a phase blocker)

These verify the **pixel/visual** layer that the agent cannot drive headlessly. Each is
**PARTIAL** — the mechanism + data are proven above; only the on-device visual is outstanding.
Requires a deploy + `sudo systemctl restart weatherbot` on host `yahir-mint` (new module code +
the panel's emoji/indicator render only load on next process start; config hot-reload does not
load new code).

| ID | Deferred visual item | Verdict | Why deferred |
|----|----------------------|---------|--------------|
| A1 | Emoji glyphs render as expected pixels on the operator's own Discord client (no `□`/tofu, correct variation-selector rendering for 🌡️/🏖️) | PARTIAL | `emoji=` param + clone-survival proven; actual font rendering is client-side. |
| A2 | `<t:…:R>` relative stamp visibly self-ages (re-renders ~every minute) and snaps to "now" on each in-place edit | PARTIAL | Token shape (`:t`/`:R`) proven byte-level; Discord-side re-render is observed only on a live client. |
| A3 | The `📍 {selected}` line + dropdown highlight visually reflect the current selection on the live pinned panel after a tap/restart | PARTIAL | Render-path threading + clone-survival proven; on-device visual confirmation outstanding. |

**Recommended Gate-2 drive (host `yahir-mint`):** deploy the new `panel.py`, `sudo systemctl
restart weatherbot`, then on the pinned panel: confirm each button shows its emoji + text label;
tap `Weather` → confirm the result embed shows `📍 home` + a live `Updated …` stamp; change the
dropdown to `travel`, tap a forecast → confirm `📍 travel` and the dropdown highlight follows;
watch the `<t:…:R>` clause re-age over ~1–2 minutes.
