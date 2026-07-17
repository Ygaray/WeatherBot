# Phase 33: Interactive & Panel Robustness - Pattern Map

**Mapped:** 2026-07-12
**Files analyzed:** 8 source touchpoints + 7 test targets
**Analogs found:** 8 / 8 (all in-repo; this is an audit-fix phase — every "analog" is the same-file or sibling-path existing pattern to lift/reuse)

> **Audit-fix phase, not greenfield.** Nearly every file is MODIFIED. The "closest analog" for most fixes is an *existing pattern already in the repo* (often in the same file or a sibling module) that must be wired into the path that lacks it. See RESEARCH.md "Key insight": the mechanisms already exist (`takes_location` field, off-loop lock discipline, the forecast-path dt-guard, Phase-32 `weather/dates.py`, the conftest harnesses) — the phase wires them into the paths missing them.

## File Classification

| Modified File | Role | Data Flow | Closest Analog (in-repo) | Match Quality |
|---------------|------|-----------|--------------------------|---------------|
| `weatherbot/interactive/dispatch.py` | dispatcher (app shim) | request-response | its own `dispatch_spec` body + panel's `_dispatch` reader (`wiring.py:489`) | exact (same-role, extend) |
| `weatherbot/interactive/cache.py` | cache/store | CRUD + off-loop fetch | its own `lookup`/`invalidate` lock discipline (cache.py:104-126) | exact (delta on existing) |
| `weatherbot/scheduler/wiring.py` (`_on_applied`, F17) | wiring/composition | event-driven (reload) | the ordered best-effort side-effects already in `_on_applied` (wiring.py:236-259) | exact (reorder) |
| `weatherbot/scheduler/wiring.py` (`SelectedContext`, F22) | wiring/composition | event-driven (reload) | `_prune_forecast_streaks(holder)` reconcile-on-reload sibling (wiring.py:252-255) | role-match (add sibling reconcile) |
| `weatherbot/interactive/panel.py` (`LocationSelect.callback`, F24) | component (Select) | event-driven (interaction) | discord.py 2.7.1 `NotFound`/`HTTPException` + `SelectedContext.value` roll-back | role-match (harden existing callback) |
| `weatherbot/interactive/panel.py` (`_select_contributor`, F23) | component (contributor) | event-driven | `_forecast_grid_contributor` non-raising sibling (panel.py:303-330) | role-match (make non-raising) |
| `weatherbot/interactive/bot.py` (`render_embed` call, F27/D-05) | render/embed | request-response | panel `_render_bridge` (wiring.py:452-453) — already passes `location=` | exact (lift call shape) |
| `weatherbot/interactive/commands/forecast.py` (F28 dup header) | render/text | transform | its own `CommandReply(title=…)` convention vs body first line (forecast.py:165) | exact (dedup) |
| `weatherbot/interactive/commands/weather_views.py` (bare-arg marker, D-05) | render/text | transform | its `weather()` `CommandReply(title=f"Weather — {f.location}")` (weather_views.py:112-113) | exact (marker rides existing header) |
| `weatherbot/weather/models.py` (F11/F107 dt guard) | model/domain | transform | forecast-path dt-pairing guard (forecast.py:126-129) — the in-repo analog to lift | exact (lift sibling pattern) |
| `weatherbot/interactive/commands/status.py` / `interactive/state.py` (D-07 ISO→human) | render/text | transform | `status.py:26` `strftime("%Y-%m-%d %H:%M UTC")`; `state.py:84` `.isoformat()` | exact (formatter swap) |

## Pattern Assignments

### `weatherbot/interactive/dispatch.py` — F02 bare-command default (D-01, D-02)

**Analog:** its own `dispatch_spec` shim (lines 93-129) + the panel reader that already reads `spec.takes_location` (`wiring.py:489`).

**Existing shim** (dispatch.py:119-129) — the delegation to preserve unchanged:
```python
return await _module_dispatch_spec(
    spec, arg, cache=cache, config=config, loop=loop,
    daemon_state=daemon_state, flags=flags,
    parse_flags=parse_forecast_flags, cache_suffix=forecast_cache_suffix,
)
```

**The carrier already exists** — `CommandSpec.takes_location` (registry.py:85), set `True` on all six location commands (`_SPECS`, registry.py:98-113). The panel path already reads it:
```python
# wiring.py:489 — the panel's _dispatch closure, the analog reader:
arg = selection.value if spec.takes_location else None  # D-04
```

**Fix pattern** (D-01): pre-resolve the default app-side when `arg is None` for a `takes_location` spec, so the hub guard `if arg is not None or spec.needs_flags:` fires. Reuse `resolve_location(config, None)` — **do not re-derive** (RESEARCH "Don't Hand-Roll"). `resolve_location` is imported in `cache.py:38` (`from weatherbot.config import resolve_location`); use the same import here.
```python
# BEFORE the delegation, in dispatch_spec:
if arg is None and getattr(spec, "takes_location", False) and flags is None:
    arg = resolve_location(config, None).name   # canonical CLI default (loader.py)
```
Keeps CLI/panel/inbound byte-identical for the non-bare case (arg already non-None). Carrier is planner discretion (A1) — passing the resolved name as `arg` is the least-surprise carrier.

**Verify-first (D-02):** reproduce the crash via the `fake_discord_message` → `on_message` harness (conftest.py:166) BEFORE landing the fix; same repro becomes the regression RED.

---

### `weatherbot/interactive/cache.py` — F13 generation guard + bounding (D-03, D-04)

**Analog:** its own existing lock discipline (cache.py:104-126). The guard is a small delta on the existing miss/store path.

**Existing miss/store** (cache.py:104-120) — the structure the guard threads through:
```python
loc_id = resolve_location(config, name).id
key = loc_id if suffix is None else (loc_id, suffix)
with self._lock:
    hit = self._cache.get(key)
if hit is not None:
    return hit
result = lookup_weather(name, config=config, settings=self._settings)  # NO lock held
with self._lock:
    self._cache[key] = result
return result
```

**Existing invalidate** (cache.py:122-126):
```python
def invalidate(self) -> None:
    with self._lock:
        self._cache.clear()
```

**F13 fix (D-03):** capture a generation counter **inside the same `with self._lock:`** as the `get` (Pitfall 2 — capturing after releasing the lock races `invalidate`); bump it under the lock in `invalidate`; on store, only write `if self._generation == gen_at_start`. **Do NOT hold the lock across `lookup_weather`** (Anti-Pattern; docstring lines 16-20). Init `self._generation = 0` in `__init__` (alongside `self._lock`, cache.py:80).

**Cache bounding (D-04):** already `TTLCache(maxsize=16)` (cache.py:79). Invariant: the plain `!weather` entry (suffix=None key = bare `loc_id`) is never the evicted one. Mechanism is planner discretion (A2) — protected key / per-namespace cap / size-cap LRU with pin. The `timer` injection (cache.py:63-77) is already present for deterministic tests.

---

### `weatherbot/scheduler/wiring.py` `_on_applied` — F17 invalidate-before-send (D-04)

**Analog:** the ordered best-effort side-effects already inside `_on_applied` (wiring.py:236-259). Each is wrapped `try/except … noqa: BLE001 — best-effort` and never aborts the reload — match that exact style.

**Current order** (wiring.py:236-247) — the bug is `channel.send` BEFORE `cache.invalidate`:
```python
if channel is not None:
    try:
        channel.send(f"✅ config reloaded: {summary}")   # slow Discord post
    except Exception: ...
if cache is not None:
    try:
        cache.invalidate()                                # runs AFTER the slow send
    except Exception: ...
```

**Fix (D-04):** move the `cache.invalidate()` block ABOVE the `channel.send` block so invalidation (which bumps the F13 generation) fires before the slow post. Keep both best-effort. The "SAME order + EXACT strings" comment (wiring.py:233) refers to the *send string*, not the invalidate ordering — the reorder is the intended change.

---

### `weatherbot/scheduler/wiring.py` `SelectedContext` — F22 reconcile-on-reload (D-04)

**Analog:** `_prune_forecast_streaks(holder)` (wiring.py:252-255) — the existing "reconcile in-process state against the reloaded config" sibling inside `_on_applied`, best-effort, keyed off the now-live desired set. F22's reconcile is a new sibling of the same shape.

**Fix (D-04):** add a best-effort reconcile in `_on_applied` — if the `SelectedContext` value names a location the reloaded config no longer has (renamed/removed), reset it (to the default / `config.locations[0].name`) so a later `resolve_location(selection.value)` can't raise `UnknownLocationError` for a location the user never sees selected. `SelectedContext.set`/`.value` are single-writer on the gateway loop (no lock; selection.py). Wrap in the same `try/except … best-effort` style as its siblings.

---

### `weatherbot/interactive/panel.py` `LocationSelect.callback` — F24 ack-before-mutate (D-04)

**Analog:** discord.py 2.7.1 `discord.NotFound` (10062 expired token) / `discord.HTTPException` sibling exceptions (verified present, RESEARCH §Interaction API) + the existing single-`edit_message` ack the callback already uses.

**Current (buggy) callback** (panel.py:246-255) — mutate THEN ack:
```python
panel = self._panel_getter()
try:
    self._selection.set(self.values[0])                         # commits FIRST
    await interaction.response.edit_message(view=panel._build_clone_view())
except Exception:  # noqa: BLE001
    _log.exception("panel select callback failed", custom_id="wb:loc:select")
    await panel._safe_error_edit(interaction)
```

**Fix (D-04, Pattern 2 / option A — roll-back):** `_build_clone_view()` re-derives `default=(n == selection.value)` from live `SelectedContext` (panel.py:224-229), so the value MUST be set before the clone is built (Pitfall 3). Capture `previous = self._selection.value`, `set(new)`, build+ack the clone, and roll back to `previous` on `discord.NotFound`/`HTTPException`:
```python
previous = self._selection.value
new_value = self.values[0]
self._selection.set(new_value)
try:
    await interaction.response.edit_message(view=panel._build_clone_view())
except (discord.NotFound, discord.HTTPException):
    self._selection.set(previous)   # nothing silently advanced
    raise                            # let the existing except/backstop handle it
```
Read `SelectedContext.value` (NOT `self.values`) outside the active select interaction (Anti-Pattern / Pitfall 3). Roll-back is the smallest diff (Open Q 2 recommendation).

---

### `weatherbot/interactive/panel.py` `_select_contributor` — F23 empty-locations degrade (D-04)

**Analog:** `_forecast_grid_contributor` (panel.py:303-330) — a sibling contributor that NEVER raises; it always returns a list of items. Make `_select_contributor` match that non-raising contract.

**Current (buggy) contributor** (panel.py:290-301) — raises on zero locations:
```python
def _select_contributor(selection):
    locations = [loc.name for loc in holder.current().locations]
    if not locations:
        raise ValueError(                                   # recurses through _safe_error_edit
            "panel requires at least one configured location; config.locations is empty"
        )
    return [LocationSelect(_panel_getter, selection, locations)]
```

**Why it freezes the panel:** the hub's `_safe_error_edit` → `_build_clone_view()` re-invokes this same contributor (panelkit.py, both success AND error paths) → same `ValueError` → swallowed → frozen (Pitfall 4). The cure MUST be app-side (hub is frozen `v0.1.1`).

**Fix (D-04, Pattern 3):** degrade to a disabled placeholder Select instead of raising, so `_build_clone_view()` always succeeds and `_safe_error_edit` renders a recovery cue:
```python
if not locations:
    placeholder = discord.ui.Select(
        custom_id="wb:loc:select",
        placeholder="No locations configured — edit config.toml",
        options=[discord.SelectOption(label="(none)", value="__none__")],
        disabled=True, row=0,
    )
    return [placeholder]
```
Exact recovery cue is planner discretion (D-04). Invariant: the contributor is non-raising so the clone path never poisons.

---

### `weatherbot/interactive/bot.py:504` — F27 inbound 📍 + D-05 default marker

**Analog:** panel `_render_bridge` (wiring.py:452-453) — already passes `location=` to `render_embed`:
```python
def _render_bridge(reply, render_arg):
    return render_embed(reply, location=render_arg)
```
And `render_embed` (bot.py:192, 219-220) already emits `📍 {location}` when `location is not None`:
```python
if location is not None:  # suppress on argless replies — D-01
    desc_lines.append(f"📍 {location}")
```

**Current (buggy) inbound call** (bot.py:504) — no `location=`, so inbound `!weather <loc>` suppresses the 📍 the panel always shows (parity drift):
```python
payload = render_embed(reply)
```

**Fix (F27/D-05):** the inbound path parses `arg = parsed.arg` (bot.py:473, None → default). Pass a `location=` label built from the resolved name, appending `" (default)"` when the command was bare (`arg is None`), plain otherwise:
```python
# was_bare = (arg is None) captured before dispatch_spec resolves the default;
# resolved_name = the location dispatch_spec/cache resolved (config.locations[0].name when bare)
location_label = resolved_name + (" (default)" if was_bare else "")
payload = render_embed(reply, location=location_label)
```
Named-location replies stay unmarked (`📍 London`); bare → `📍 Toronto (default)`. Threading the resolved name back to the call site is planner discretion — coordinate with the F02 fix (dispatch.py resolves the default name; surface it to the render site).

---

### `weatherbot/interactive/commands/forecast.py:165` — F28 duplicated header (D-08)

**Analog:** the `weather_views.py` `CommandReply(title=…)` convention (weather_views.py:112-113, 137, 162, 190, 208 …) — every reply uses `title=f"{Kind} — {location}"` as the SINGLE header. The forecast path duplicates it into both title AND the rendered body's first line.

**Current (buggy)** (forecast.py:165):
```python
return CommandReply(title=f"{title} — {result.location.name}", text=rendered)
```
`rendered` (the template body) ALSO starts with `"{title} — {location}"` (header_values `title`/`location`, forecast.py:150-156 → `render_forecast`), so both the embed (title + first body field) and CLI `render_text` show it twice.

**Fix (D-08, Open Q 1 recommendation):** drop the duplicate from the **body** (keep the embed `title` as the single header) so the embed keeps a proper title and the body starts with content. Then regenerate the golden snapshot with `--snapshot-update`. **Trust exit code + `.ambr` diff, not the "N snapshots failed" banner** (MEMORY: pytest-snapshot-report-quirk); the diff must be exactly the removed header line (Pitfall 5).

---

### `weatherbot/interactive/commands/weather_views.py` — bare-arg default marker (D-05)

**Analog:** its own `weather()` (weather_views.py:112-113): `CommandReply(title=f"Weather — {f.location}")`. All six location-command handlers (`weather`/`alerts`/`sun`/`wind`/`next_cloudy`/`uv`) build the header from `result.location.name` / `f.location`.

**Note:** the `(default)` marker (D-05) rides the **render-side `location=` header** (bot.py `render_embed`, panel `_render_bridge`), NOT the `CommandReply.title` — the handlers don't know whether the arg was bare. The marker is applied where the render location is chosen (bot.py:504 for inbound, per F27/D-05). This file is the location for verifying the bare-arg path renders a `CommandReply` at all (post-F02); no per-handler edit is required for the marker itself unless the planner routes the marker through the reply title.

---

### `weatherbot/weather/models.py:300-301, 415-426` — F11/F107 dt-paired dual-unit (D-08)

**Analog (in-repo, the pattern to LIFT):** the forecast-path dt-pairing guard — `forecast.py:114-129`:
```python
day_imp = daily_imp[i] if i < len(daily_imp) else {}
dt_ts = (day_imp or {}).get("dt")
if dt_ts is not None:
    day_met = next((d for d in daily_met if (d or {}).get("dt") == dt_ts), {})
else:
    day_met = daily_met[i] if i < len(daily_met) else {}
```

**F107 site** (models.py:300-301) — imperial/metric daily selected INDEPENDENTLY, no cross-dt check:
```python
day_i = select_today_daily(onecall_imp.get("daily"), loc_tz, local_date) or {}
day_m = select_today_daily(onecall_met.get("daily"), loc_tz, local_date) or {}
```
`select_today_daily` / `local_date_for` come from Phase-32 `weather/dates.py` (models.py:291) — **reuse that anchoring**, don't invent new date math (RESEARCH "Don't Hand-Roll"). Fix: after selecting `day_i` by local date, pick `day_m` by matching `day_i`'s `dt` (not an independent selection over the metric array), falling back to `{}` on no match (degrade gracefully, never mispair).

**F11 site** (models.py:415-426) — `high/low_display` discards a valid imperial high when the metric twin is missing:
```python
if self.high_imp is None or self.high_met is None:
    return self.temp_display          # throws away a valid imperial high
return self._temp_str(self.high_imp, self.high_met)
```
Fix: when ONE unit is present, render THAT unit rather than falling back to `temp_display`.

**F107 test:** needs a deliberately dt-SKEWED briefing fixture (existing fixtures are pre-aligned → false-green). See Wave 0 gaps.

---

### `weatherbot/interactive/commands/status.py:26` + `interactive/state.py:84` — D-07 ISO→human

**Analog / fix sites** (formatter swap only):
```python
# status.py:26 — current raw UTC:
return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
# state.py:84 — current ISO:
fires[location.name] = earliest.isoformat()
```
**Fix (D-07):** render local 24-hour (`09:00`), timezone offset dropped (already localized). The embed *description* already uses discord `<t:>` relative markdown (bot.py:221) — the raw-ISO problem is ONLY in the template/CLI text path (status.py, state.py, and `{sent_at}`/`{checked_at}` via `scheduler/context.py`), NOT the embed description (A3). Locale ordering of the formatter is planner discretion.

## Shared Patterns

### Reuse-don't-re-derive (the phase's spine)
**Apply to:** all fixes. Each fix wires an existing repo mechanism into the path that lacks it:
| Need | Reuse (do NOT rebuild) |
|------|------------------------|
| Default-location resolution (F02) | `resolve_location(config, None)` (imported cache.py:38) |
| dt→local-date anchoring (F11/F107, D-06) | `weather/dates.py` `select_today_daily`/`local_date_for` (Phase 32) |
| Interaction ack/expiry (F24) | discord.py 2.7.1 `NotFound`/`HTTPException`, `SelectedContext.value` |
| TTL cache + bounding (F13) | `cachetools.TTLCache` maxsize + LRU/pin (cache.py:79) |
| The 📍 render call shape (F27) | panel `_render_bridge` (wiring.py:452-453) |
| dt-pairing guard (F11/F107) | forecast.py:126-129 (lift into models.py) |

### Best-effort side-effect wrapping (reload path)
**Source:** `_on_applied` blocks (wiring.py:236-259).
**Apply to:** F17 reorder + F22 reconcile — every reload side-effect is `try/except … noqa: BLE001 — best-effort; reload already committed`, never aborting the committed reload. New reconcile matches this style.

### Failure-isolation envelope — turn silent-swallow into CORRECT behavior
**Source:** `on_message` envelope (bot.py:506-511), hub `View.on_error`.
**Apply to:** F02, F23. These fixes turn silent-swallow into correct behavior / visible recovery — **do NOT add more blanket `except`** (Anti-Pattern; CONTEXT §code_context). Also: do NOT broaden any `except` to render exception text into a reply (Security V7 — the `appid=<key>` leak path exists in the fetch exception; keep the generic `_ERROR_REPLY`).

### Hub is frozen (v2.0 litmus)
**Apply to:** F02, F23 especially. No edits under `.venv/.../yahir_reusable_bot/` or `../Reusable/YahirReusableBot/` — a source edit won't take effect (pinned wheel) and a hub tag is human-gated. `grimp` import-hygiene gate + litmus grep enforce hub-cleanliness. All fixes land in `weatherbot/`.

### Test harnesses (all exist — no new fixtures except the dt-skewed one)
**Source:** `tests/conftest.py`.
| Harness | Location | Drives |
|---------|----------|--------|
| `fake_discord_message` | conftest.py:166 | `on_message` end-to-end (F02 verify-first + regression) |
| `fake_interaction` | conftest.py:242 | `LocationSelect.callback`/`PanelKit.on_command` (F23/F24); make `response.edit_message` raise `discord.NotFound` for F24 expiry |
| `load_fixture` | conftest.py:27 | payload fixtures (F107 skewed fixture) |
| injectable `timer` | `ForecastCache(timer=…)` (cache.py:63) | F13 TTL/generation race (call `invalidate()` mid-flight) |

**Test-shaped-fix convention (from Phase 32):** each fix ships with a regression hook that fails pre-fix / passes post-fix; comprehensive backfill is Phase 34. Quick run: `uv run pytest tests/test_dispatch.py tests/test_cache.py tests/test_panel.py tests/test_models.py -x`.

## No Analog Found

None. Every touchpoint has an in-repo analog (same-file existing pattern, sibling module, or Phase-32/26/27 established helper). This is an audit-fix phase — the fixes wire existing mechanisms into paths that lack them.

## Metadata

**Analog search scope:** `weatherbot/interactive/`, `weatherbot/scheduler/`, `weatherbot/weather/`, `weatherbot/config/`, `tests/`, installed hub `yahir_reusable_bot` (read-only).
**Files scanned:** 11 source + conftest.
**Pattern extraction date:** 2026-07-12
