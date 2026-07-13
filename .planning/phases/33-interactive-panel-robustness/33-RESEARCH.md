# Phase 33: Interactive & Panel Robustness - Research

**Researched:** 2026-07-12
**Domain:** discord.py 2.7.1 interaction lifecycle · off-loop cache concurrency (generation guard) · bounded/pinned TTLCache · dt-anchored dual-unit pairing · render formatting · verify-crash-first regression harnessing
**Confidence:** HIGH (this is a self-contained audit-fix phase; every finding has a file:line, a locked decision, and the code was read directly this session — no external unknowns)

## Summary

This is an **audit-driven correctness phase**, not greenfield. The diagnosis is done: every fix has a file:line in `WHOLE-PROJECT-REVIEW.md` and a LOCKED decision (D-01…D-08) in CONTEXT.md. My job was to verify the *implementation mechanics* by reading the actual code and the pinned hub, and to confirm the discord.py 2.7.1 API surface the interaction fixes rely on. I read all touchpoints directly — `interactive/dispatch.py`, `interactive/cache.py`, `interactive/panel.py`, `scheduler/wiring.py`, `weather/models.py`, `interactive/commands/forecast.py`, `interactive/bot.py`, `interactive/registry.py`, plus the installed hub `panelkit.py`, `registry/dispatch.py`, `registry/spec.py`, `selection.py` — so the findings below are `[VERIFIED: codebase]` from source, not inferred.

The single most important discovery for **F02** is that the app-side carrier the fix needs **already exists**: the app's `CommandSpec` (registry.py:85) already has a `takes_location: bool` field, and the panel path already reads `spec.takes_location` (wiring.py:489). The bug is that the *inbound* path (`bot.py` `on_message` → `dispatch_spec`) passes `arg=None` straight through, and the hub's fetch guard is `if arg is not None or spec.needs_flags:` (registry/dispatch.py:76) — so a bare location command **skips the fetch**, `result` stays `None`, and the bind closure derefs `result.forecast` → AttributeError. Critically, `cache.lookup(None, config)` **already resolves the default** via `resolve_location(config, None)` → `config.locations[0]` (cache.py:104, loader.py:52). So the fix is purely to make the app-side shim force the fetch for a `takes_location` spec when `arg is None` — no hub change, no domain leak.

The hub is **weather-domain-free and frozen** (pinned `v0.1.1`; the app runs the installed wheel in `.venv`, not the source). Every fix in this phase must land in `weatherbot/` app code. For F23 specifically, the recursion lives in the hub's `_safe_error_edit` → `_build_clone_view()` → app `_select_contributor` (panel.py:297) `raise ValueError`, but the *cure* must be app-side (the contributor stops raising and degrades) because the hub cannot be edited here.

**Primary recommendation:** F02 fix = app `dispatch.py` shim resolves the default name app-side (`resolve_location(config, None).name`) and passes it as a non-`None` `arg` for `takes_location` specs, so the existing hub fetch path runs unchanged. Verify the crash first via the gateway-free `fake_discord_message` → `on_message` harness (conftest already provides it). Every other fix reuses machinery that already exists in-repo (the dt-pairing guard from forecast.py:126-129, the Phase-32 `weather/dates.py` anchoring, the `fake_interaction` factory with `is_done`/`edit_original_response`/`followup`).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Bare-command default resolution (F02) | App dispatch shim (`interactive/dispatch.py`) | App config (`resolve_location`) | Default resolution is weather-domain; the hub guard is generic and stays untouched (D-01) |
| Off-loop cache generation guard (F13) | App cache (`interactive/cache.py`) | — | `ForecastCache` is app-owned; the guard is a local counter, no hub involvement (D-03) |
| Reload side-effect ordering (F17) | App wiring (`scheduler/wiring.py` `_on_applied`) | — | The closure is authored app-side at the composition root |
| SelectedContext reconcile on reload (F22) | App wiring (`scheduler/wiring.py`) | Hub `SelectedContext` (read-only, `.set()`) | The reconcile hook is app wiring; the hub holder just holds a value |
| Empty-locations render recovery (F23) | App panel contributor (`interactive/panel.py`) | Hub PanelKit (routes into it) | The `ValueError` originates in the app contributor; the hub cannot be edited → cure app-side |
| Ack-before-mutate ordering (F24) | App panel (`LocationSelect.callback`, `interactive/panel.py:236`) | discord.py 2.7.1 response API | The callback body is app code; it uses the hub's clone path |
| Bounded/pinned cache (F13 bound) | App cache (`interactive/cache.py`) | `cachetools` | Eviction policy is a local `ForecastCache` concern |
| dt-paired dual-unit temps (F11/F107) | App weather model (`weather/models.py`) | `weather/dates.py` (Phase 32) | Pairing/selection is domain logic; reuse the existing anchoring helper |
| Render formatting (F27/F28/D-05/06/07) | App render (`bot.py`, `commands/forecast.py`, `commands/status.py`) | templates/renderer | The embed/text builders and label formatters are app-side |

## User Constraints (from CONTEXT.md)

### Locked Decisions

**HARD-UI-01 — Bare-command default resolution (F02)**
- **D-01 — App-side fix only; zero hub change.** In the app's `dispatch_spec` shim (`interactive/dispatch.py`), when `arg is None` for a location-taking spec, resolve the default location app-side and pass it through so the existing fetch path runs (the CLI's `resolve_location(None)` behavior, now on Discord). The app needs a "which specs take a location" signal; it already owns `_SPECS`/`_wire_handlers`, so that lives app-side too — exact carrier (per-spec flag vs. app-side set) is planner discretion.
- **D-02 — Verify the crash first.** Reproduce bare `!weather` → AttributeError → generic error on the Discord surface (or a faithful harness of `on_message` → `dispatch_spec`) and capture that evidence BEFORE landing the fix; the same repro becomes the regression test's RED.

**HARD-UI-02 — Panel cache & interaction races**
- **D-03 — Generation/epoch guard for the stale re-populate (F13).** `invalidate()` bumps a generation counter; an in-flight off-loop fetch captures the generation at start and refuses to write its result if the generation has moved. Kills the stale re-populate WITHOUT serializing fetches — preserves the deliberate off-loop-fetch design (rejected: lock-around-fetch). Counter placement / generation-vs-epoch naming is planner discretion.
- **D-04 — The rest of the cache bucket is fixed regardless (not forks):**
  - Reorder `on_applied` so `cache.invalidate` runs BEFORE the (slow) Discord `channel.send` (F17).
  - Reconcile `SelectedContext` on hot-reload — a renamed/removed selected location must not leave a stale name that `resolve_location` rejects (F22).
  - Guard the empty-locations re-render so `_safe_error_edit` cannot recurse into the same `_build_clone_view()` ValueError and freeze the panel (F23) — fail into a user-visible recoverable state, not a swallowed log.
  - Ack before mutating the shared selection (or roll back on ack failure) so a failed/expired interaction can't leave selection silently advanced (F24).
  - Bound the cache with the plain-weather entry protected from eviction. Bounding mechanism (protected key vs. per-namespace caps vs. size-cap LRU with pin) is planner discretion; the invariant: the plain `!weather` entry is never the one evicted.

**HARD-UI-03 — Rendering formatting (user-visible choices)**
- **D-05 — Default-location marker: 📍 + "(default)" suffix.** On bare/no-arg location commands, append " (default)" to the location name in the 📍 header (`📍 Toronto (default)`); named-location replies stay unmarked (`📍 London`). ALSO restores the 📍 header on the inbound path (F27) — pass `location=` to `render_embed` at `interactive/bot.py:504`.
- **D-06 — Out-of-today date labels: weekday + abbreviated month + day** (`Thu Jul 17`). Replaces the current ambiguous labels.
- **D-07 — Humanized timestamps: local 24-hour** (`09:00`), timezone offset dropped. Replaces raw ISO (`2026-07-12T09:00:00+00:00`).
- **D-08 — Pure-bug render fixes (fix + regression-test):** remove the F28 duplicated header line; strip trailing blank lines from empty render tokens; add the dt-pairing guard so imperial/metric daily temps are matched by their own `dt`/local date, not positional index (F11/F107).

### Claude's Discretion
- Exact carrier of the app-side "takes_location" signal (D-01) — **note: a `takes_location: bool` field already exists on the app `CommandSpec`**; generation counter placement/naming (D-03); cache-bounding mechanism (D-04); how the empty-locations recovery cue is surfaced (D-04/F23); locale ordering details of the date/time formatters. All bounded by the invariants stated above.

### Deferred Ideas (OUT OF SCOPE)
- F25 (bare `+`/`-` flag → generic error), F26 (flag-grammar footgun), F29 (`next_cloudy` drops nocturnal cloudy hours), F78 (`!panel` trailing-text silent-drop), F162 (add/drop same-day) → **Phase 35 Cleanup Sweep**. Do NOT pull them in.
- F16 cached-timestamp staleness (cosmetic) — deferred unless trivial once the ISO→human formatter lands.
- F179 reconnect supervisor, F158 reconcile reject-hook — separate lifecycle findings, not this phase's UI buckets.
- Any HUB-rooted dispatcher change → upstream `yahir_reusable_bot`, human-gated.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-UI-01 | Bare location-taking commands resolve the default instead of crashing on `result=None`; Discord matches CLI's default-location behavior (F02, verify first). | F02 mechanism fully traced: hub guard `arg is not None or spec.needs_flags` (registry/dispatch.py:76) skips fetch for bare arg; `cache.lookup(None)` already resolves default (cache.py:104 → loader.py:52). App-side carrier `takes_location` already on `CommandSpec` (registry.py:85). Verify-first harness = conftest `fake_discord_message` → `on_message`. |
| HARD-UI-02 | Panel cache-invalidation and interaction races closed (stale reads, double-ack/expired-interaction, unbounded/mis-evicting cache). | F13 generation guard (cache.py:104-120), F17 reorder (wiring.py:236-247), F22 SelectedContext reconcile (wiring.py:452 seed; SelectedContext.set), F23 empty-locations recursion (panel.py:297 raise → hub `_safe_error_edit`→`_build_clone_view` recursion), F24 ack ordering (panel.py:248 set-before-ack; discord.py 2.7.1 `is_expired`/`is_done` verified), cache bounding (`cachetools.TTLCache` maxsize=16). |
| HARD-UI-03 | Rendering defects fixed — no duplicated headers, empty-token trailing blanks, raw ISO timestamps, mispaired metric-on-missing-dt, ambiguous date labels, unmarked default location. | F28 dup header (forecast.py:165 title == body first line), empty-token blanks (renderer.py:194 `render` leaves empty substitutions), ISO timestamps (status.py:26 `%Y-%m-%d %H:%M UTC`, state.py:84 `.isoformat()`), F11/F107 (models.py:418-425 `high/low_display` discards valid imperial when metric missing; models.py:300-301 select imperial/metric daily independently with no cross-dt check), date labels (forecast.py:60-73 `_day_label` `f"{abbr} {month}/{day}"`), F27 marker (bot.py:504 `render_embed(reply)` no `location=`). |

## Standard Stack

No new dependencies. This phase edits existing app code only. Relevant installed versions (from `uv.lock`, verified this session):

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | 2.7.1 | Interaction lifecycle (F24 ack ordering, F23 recovery) | Already pinned; the hub PanelKit + app panel components use its `InteractionResponse`/`Interaction` API |
| cachetools | (installed) | `TTLCache` backing `ForecastCache` (F13 guard + bounding) | Already the cache backend (cache.py:36); bounding = its `maxsize` + an LRU/pin policy |
| yahir_reusable_bot | v0.1.1 (pinned wheel) | Hub dispatcher / PanelKit / SelectedContext (READ-ONLY here) | Frozen; the app runs the installed `.venv` copy, not source. **No hub edits this phase.** |

### discord.py 2.7.1 Interaction API — verified present this session
`InteractionResponse` methods: `defer`, `edit_message`, `is_done`, `send_message`, `send_modal`, `pong`, `type`, `autocomplete`, `launch_activity`.
`Interaction` attributes/methods: `is_expired`, `followup`, `edit_original_response`.

`[VERIFIED: codebase]` — imported discord 2.7.1 from `.venv` and enumerated the methods directly. All the primitives D-04/F23/F24 need exist: single-ack via `response.edit_message`/`defer`, post-ack via `edit_original_response`/`followup.send`, ack-state check via `response.is_done()`, token-expiry check via `interaction.is_expired()`.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| generation counter (D-03) | lock-around-fetch | Rejected by D-03: serializes lookups, risks blocking the gateway path — kills the deliberate off-loop-fetch design |
| `cachetools.LRUCache`/pin (F13 bound) | separate protected slot + TTLCache for the rest | Both satisfy "plain-weather entry never evicted"; planner discretion. `TTLCache` already gives TTL; a size-cap LRU with a pinned key or a per-namespace cap keeps the plain entry safe |
| pass resolved default `arg` (F02) | app shim calls `cache.lookup(None)` directly | Passing `resolve_location(config, None).name` as `arg` keeps the hub fetch path byte-identical and CLI/panel/inbound behavior-preserving — the least-surprise carrier |

**Installation:** none — no `uv add`.

## Package Legitimacy Audit

Not applicable — this phase installs **zero** external packages. All work edits existing `weatherbot/` app modules. The only third-party libraries touched (`discord.py`, `cachetools`, `yahir_reusable_bot`) are already pinned in `uv.lock` and unchanged by this phase.

## Architecture Patterns

### System Architecture Diagram

```
Discord inbound message                    Discord panel interaction (Select / buttons)
        │                                            │
        ▼                                            ▼
  bot.on_message                             PanelKit.on_command / LocationSelect.callback
  (D-11 envelope)                            (single-ack contract; failure isolation)
        │                                            │
        │ parse_command → (spec, arg)                │ ① response.edit_message (ack + disable)  ← F24: ack BEFORE mutate
        │  arg=None for bare command                 │    SelectedContext.set(...)               ← F22: reconciled on reload
        ▼                                            ▼
  dispatch_spec (APP SHIM, interactive/dispatch.py) ─────────────┐
        │  F02 FIX: if spec.takes_location and arg is None →      │
        │           arg = resolve_location(config, None).name     │
        ▼                                                         │
  _module_dispatch_spec (HUB, registry/dispatch.py)              │
        │  guard: if arg is not None or spec.needs_flags:  ← fetch now fires (arg non-None)
        ▼                                                         │
  loop.run_in_executor(None, cache.lookup, name, config)  ◄──────┘  (OFF the gateway loop, D-10)
        │
        ▼
  ForecastCache.lookup (interactive/cache.py)
        │  key = resolve_location(config, name).id   (None → default, cache.py:104)
        │  miss → lookup_weather(...) WITHOUT lock   ◄── F13: capture generation at start
        │  store → if generation unchanged: cache[key]=result  ◄── F13: refuse stale re-populate
        │  bound: TTLCache maxsize + pin plain-weather key       ◄── D-04 cache bounding
        ▼
  LookupResult → bind closure (weather_views.weather(result), etc.)
        │
        ▼
  render_embed(reply, location=…)   ◄── F27/D-05: pass location=, "(default)" suffix on bare
        │  Forecast/ForecastDay dual-unit temps ◄── F11/F107: dt-paired, not positional
        │  labels "Thu Jul 17" (D-06); timestamps "09:00" (D-07); no dup header (F28); no empty-token blanks
        ▼
  Discord embed / CLI text

  Config hot-reload ──► wiring._on_applied:  F17 ORDER: cache.invalidate()  BEFORE  channel.send(...)
                                             (invalidate bumps F13 generation)
```

### Pattern 1: Generation-guarded off-loop cache write (F13, D-03)
**What:** Capture a monotonically-increasing generation counter at fetch start; on `invalidate()` bump it under the lock; when the in-flight fetch returns, only store if the generation is unchanged.
**When to use:** F13 — the in-flight fetch that started before an `invalidate()` must not re-insert a pre-reload result.
**Example (source: `weatherbot/interactive/cache.py`, existing lock/off-loop structure — the guard is the delta):**
```python
# Source: weatherbot/interactive/cache.py (current miss path, lines 104-120) + D-03 guard
def lookup(self, name, config, suffix=None):
    loc_id = resolve_location(config, name).id
    key = loc_id if suffix is None else (loc_id, suffix)
    with self._lock:
        hit = self._cache.get(key)
        gen_at_start = self._generation          # capture INSIDE the lock, before releasing
    if hit is not None:
        return hit
    result = lookup_weather(name, config=config, settings=self._settings)  # NO lock held
    with self._lock:
        if self._generation == gen_at_start:     # refuse a stale re-populate (D-03)
            self._cache[key] = result
    return result

def invalidate(self):
    with self._lock:
        self._cache.clear()
        self._generation += 1                    # bump so in-flight fetches self-reject
```
Key rules: capture the generation *inside* the same lock as the `get` so it's consistent with the miss; do **not** hold the lock across `lookup_weather` (preserves the off-loop design, D-03 rationale, cache.py docstring lines 10-24).

### Pattern 2: Ack-before-mutate for a Select callback (F24, D-04)
**What:** In `LocationSelect.callback`, ack the interaction (or make the mutation reversible) so a failed/expired `edit_message` cannot leave `SelectedContext` silently advanced with no re-render.
**When to use:** F24 — currently `self._selection.set(...)` (panel.py:248) commits *before* `response.edit_message` (panel.py:252); if the ack fails the selection has moved with no visible change.
**Example (source: `weatherbot/interactive/panel.py:236-256`, current callback):**
```python
# Current (panel.py:247-255) — mutate THEN ack (the F24 bug):
try:
    self._selection.set(self.values[0])                     # commits first
    await interaction.response.edit_message(view=panel._build_clone_view())
except Exception:
    _log.exception(...); await panel._safe_error_edit(interaction)

# Fix option A — ack first, then mutate (edit_message renders the NEW selection, so
#   compute the value, ack with the clone reflecting it, then set):
new_value = self.values[0]
self._selection.set(new_value)
try:
    await interaction.response.edit_message(view=panel._build_clone_view())
except (discord.NotFound, discord.HTTPException):           # expired/failed token
    self._selection.set(previous_value)                      # roll back — nothing advanced
    raise
```
Note the tension: `edit_message` must render the *new* selection (the dropdown shows `default=True` on the selected option, panel.py:224-229), so a pure "ack then set" needs the clone built from the intended value. The planner picks A (set → ack → roll back on failure, capturing `previous = self._selection.value` first) or a defer-then-edit variant. discord.py raises `discord.NotFound` (10062 Unknown interaction) on an expired 3s token and `discord.HTTPException` on other failures — both verified as siblings, catchable.

### Pattern 3: App-side empty-locations degrade (F23, D-04)
**What:** The `_select_contributor` (panel.py:290-301) currently `raise ValueError` on zero locations. Because the hub's `_safe_error_edit` → `_build_clone_view()` re-invokes that same contributor, the error path *re-raises the same ValueError*, which the hub swallows → panel frozen. The cure must be **app-side** (the hub is frozen).
**When to use:** F23 — config hot-reloaded to zero `[[locations]]` while a panel interaction fires.
**Example (source: `weatherbot/interactive/panel.py:290-301`):**
```python
# Current (panel.py:296-300) — fail LOUD, which recurses through _safe_error_edit:
if not locations:
    raise ValueError("panel requires at least one configured location; ...")

# Fix: degrade to a disabled, user-visible placeholder Select instead of raising, so
# _build_clone_view() ALWAYS succeeds and _safe_error_edit can render a recovery cue.
if not locations:
    placeholder = discord.ui.Select(
        custom_id="wb:loc:select", placeholder="No locations configured — edit config.toml",
        options=[discord.SelectOption(label="(none)", value="__none__")], disabled=True, row=0,
    )
    return [placeholder]
```
This makes the clone path non-raising, so `_safe_error_edit`'s `edit_original_response(view=self._build_clone_view())` succeeds and the operator sees a disabled, self-documenting panel rather than a frozen one. (Planner discretion on the exact recovery cue per D-04.)

### Pattern 4: dt-paired dual-unit selection for the daily briefing (F11/F107, D-08)
**What:** `Forecast.from_onecall` (models.py:300-301) selects `day_i` and `day_m` **independently** via `select_today_daily` over two separate imperial/metric payloads. F107: no test proves they're the same day; F11: `high/low_display` (models.py:418-425) falls back to the *current* temp when only the metric side is missing, discarding a valid imperial high. Reuse the forecast path's existing dt-guard idea (forecast.py:126-129).
**When to use:** F11/F107 — a length/ordering skew between the imperial and metric `daily[]` (e.g. one fetch crosses local midnight) mispairs °F to the wrong day's °C.
**Example (source: `weatherbot/interactive/commands/forecast.py:114-129` — the pattern to lift into models.py):**
```python
# Source: forecast.py:126-129 — the EXISTING dt-pairing guard the briefing lacks (F107):
dt_ts = (day_imp or {}).get("dt")
if dt_ts is not None:
    day_met = next((d for d in daily_met if (d or {}).get("dt") == dt_ts), {})
else:
    day_met = daily_met[i] if i < len(daily_met) else {}
```
For F11 in `high/low_display` (models.py:415-426): when one unit is present, render *that* unit rather than falling back to `temp_display`. The current `if self.high_imp is None or self.high_met is None: return self.temp_display` throws away a valid imperial high whenever the metric twin is missing.

### Anti-Patterns to Avoid
- **Editing the hub to fix F02/F23:** the hub is pinned `v0.1.1` and runs from `.venv`; a source edit won't even take effect without an editable overlay, and cutting a hub tag is human-gated (ECOSYSTEM.md §2, CLAUDE.md). All fixes are app-side.
- **Holding the cache lock across `lookup_weather` (F13):** re-introduces serialization the off-loop design deliberately avoids (D-03 rejected alternative; cache.py docstring lines 16-20).
- **Adding another blanket `except` for F02/F23:** the failure-isolation envelope already swallows to a generic reply (bot.py:506, hub `on_error`). These fixes turn silent-swallow into *correct behavior* / *visible recovery*, not more catches (CONTEXT.md §code_context "Failure-isolation envelope").
- **Positional imperial/metric pairing (F11/F107):** never trust `daily[i]` alignment across two independent fetches — match by `dt`.
- **Re-reading `Select.values` outside an active select interaction:** empty outside the callback (panel.py:210-211, Pitfall 3). F24 must read `SelectedContext.value`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Default-location resolution (F02) | new "if arg is None pick first" logic in the shim | `resolve_location(config, None)` (loader.py:52) | Canonical CLI behavior; already handles empty-config `ValueError` and casefold matching. CONTEXT.md §code_context: "do not re-derive it." |
| dt→local-date anchoring (F11/F107, D-06) | new date math | `weather/dates.py` `select_today_daily` / `local_date_for` (Phase 32) | The single source of truth for "which local day"; already DST/naive-UTC-safe (dates.py:39-108) |
| Interaction ack/expiry handling (F24) | manual token TTL tracking | discord.py 2.7.1 `interaction.is_expired()`, `response.is_done()`, `discord.NotFound`/`HTTPException` | Verified present; the library models the 3s/15min token lifecycle |
| TTL cache + bounding (F13) | a dict + manual timestamps | `cachetools.TTLCache` `maxsize` + LRU/pin policy | Already the backend (cache.py:36); adding a pinned/protected key is a small policy delta |
| Panel clone/re-render | new view-cloning | hub `PanelKit._build_clone_view()` (panelkit.py:401) | The live-routing fix already lives there; the app contributor just must not raise (F23) |

**Key insight:** Almost every mechanism this phase needs already exists in the repo — the `takes_location` field, the off-loop lock discipline, the dt-pairing guard (in the *forecast* path), the Phase-32 date anchoring, the `fake_interaction`/`fake_discord_message` harnesses. The phase is about *wiring existing mechanisms into the paths that lack them*, not building new ones.

## Runtime State Inventory

Not a rename/refactor/migration phase — this is in-process code correctness with no stored-state, OS-registration, or secrets implications. Explicit per-category:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the `ForecastCache` is in-memory (TTLCache); no persisted key uses a value this phase changes. F13/F17 affect only in-memory cache lifetime. | None |
| Live service config | None — no external service config embeds anything this phase renames. | None |
| OS-registered state | None — no systemd/Task Scheduler change; the live `weatherbot` systemd unit on `yahir-mint` restarts to pick up new code but registers no new state. | Restart the daemon after deploy (existing ops, see MEMORY: weatherbot-live-systemd-service). |
| Secrets/env vars | None — no new secret or env var; no rename of an existing one. | None |
| Build artifacts | None — no package rename; no `pyproject.toml` name change. Hub stays pinned `v0.1.1`. | None |

**Nothing found in any category** — verified by reading every touchpoint; this phase adds no persisted key, no schema change, no new registration.

## Common Pitfalls

### Pitfall 1: Fixing F02 by editing the hub guard
**What goes wrong:** Adding a `takes_location` branch to the hub `dispatch_spec` guard (registry/dispatch.py:76) seems natural, but the hub is domain-free and frozen.
**Why it happens:** The guard lives in the hub, so the bug *looks* upstream. But default-location resolution is weather-domain and belongs app-side (D-01).
**How to avoid:** Fix in the app shim (`interactive/dispatch.py`), pre-resolving the default so `arg` is non-`None`. The hub guard fires unchanged. `grimp` import-hygiene gate + the litmus grep enforce hub-cleanliness (CONTEXT.md §code_context).
**Warning signs:** Any diff under `.venv/.../yahir_reusable_bot/` or `../Reusable/YahirReusableBot/` — those are out of jurisdiction for this phase.

### Pitfall 2: F13 generation captured outside the lock
**What goes wrong:** Reading `self._generation` after releasing the `get` lock races with `invalidate()` and can capture a *post*-invalidate generation, defeating the guard.
**Why it happens:** The natural place to read the counter is right before the fetch, but that's after the lock is released.
**How to avoid:** Capture the generation *inside* the same `with self._lock:` block as the cache `get` (Pattern 1). The store re-check under the lock then compares apples to apples.
**Warning signs:** A test where `invalidate()` fires between the `get` and the fetch still serves stale.

### Pitfall 3: F24 ack renders the wrong selection
**What goes wrong:** "Ack first, then set" acks with a clone built from the *old* selection, so the dropdown shows the wrong `default=True` option until the next render.
**Why it happens:** `_build_clone_view()` re-derives the Select options with `default=(n == selection.value)` (panel.py:224-229) — it reads live `SelectedContext`, so the value must be set before the clone is built.
**How to avoid:** Capture `previous = self._selection.value`, `set(new)`, build+ack the clone, and roll back to `previous` on ack failure (Pattern 2). This keeps the rendered selection correct while making the mutation reversible.
**Warning signs:** A test that expires the token and asserts `selection.value` reverted — if it doesn't revert, the selection silently advanced.

### Pitfall 4: F23 fix that still raises inside the clone path
**What goes wrong:** Any app-side fix that still raises on empty locations recurses through `_safe_error_edit` → `_build_clone_view()` again → swallowed → frozen panel.
**Why it happens:** The hub calls `_build_clone_view()` in *both* the success and error paths (panelkit.py:353, 361, 371, 448); a raising contributor poisons both.
**How to avoid:** Make `_select_contributor` **non-raising** — degrade to a disabled placeholder Select (Pattern 3) so `_build_clone_view()` always succeeds.
**Warning signs:** A zero-locations test where the panel shows the disabled cue but never re-renders after config is fixed.

### Pitfall 5: F28 dedup that breaks the golden snapshot silently
**What goes wrong:** Removing the duplicated header from the wrong side (title vs. body first line) changes the embed AND the CLI text; the syrupy golden must be regenerated intentionally.
**Why it happens:** `CommandReply.title` = `f"{title} — {location}"` (forecast.py:165) AND the template body's first line render the same string; both surfaces (embed title + first body field, CLI `render_text`) show it twice.
**How to avoid:** Decide *which* copy to drop (D-08 says "drop the dup from title or body so it appears once on both surfaces"), then regenerate the golden with `--snapshot-update` and eyeball the `.ambr` diff. **Trust the exit code + `.ambr` diff, not the "N snapshots failed" banner** (MEMORY: pytest-snapshot-report-quirk — the suite can print "N snapshots failed" but exit 0).
**Warning signs:** A golden diff that changes more lines than the single header — means the wrong copy or an over-broad edit.

## Code Examples

### Verify the F02 crash first (D-02) — gateway-free harness
```python
# Source: tests/conftest.py fake_discord_message factory (lines 122-160) + tests/test_bot.py pattern.
# RED (pre-fix): bare "!weather" with no arg → result stays None → weather_views.weather(None)
#   → result.forecast → AttributeError → on_message envelope → generic _ERROR_REPLY.
def test_bare_weather_crashes_pre_fix(fake_discord_message, monkeypatch):
    msg = fake_discord_message(author_bot=False, author_id=_OPERATOR_ID, content="!weather")
    handler = bot.build_on_message(holder=holder, operator_id=_OPERATOR_ID, cache=cache)
    # PRE-FIX: assert the generic error reply is sent (proves the crash faithfully).
    # POST-FIX: assert a real weather embed for the DEFAULT location (config.locations[0]) is sent.
    await handler(msg)
    msg.channel.send.assert_awaited()  # inspect the sent embed/text to distinguish crash vs. correct reply
```
The same repro is the regression test's RED (D-02): capture the "something went wrong" evidence pre-fix, then flip the assertion to expect the default-location reply post-fix.

### F02 fix — app shim resolves the default (D-01)
```python
# Source: weatherbot/interactive/dispatch.py:93-129 (dispatch_spec shim) + config/loader.py:52.
async def dispatch_spec(spec, arg, *, cache, config, loop, daemon_state, flags=None):
    # F02 (D-01): a location-taking spec with no arg must resolve the default APP-SIDE so the
    # hub's `arg is not None` fetch guard fires. resolve_location(config, None) → config.locations[0].
    if arg is None and getattr(spec, "takes_location", False) and flags is None:
        arg = resolve_location(config, None).name        # canonical CLI default (loader.py:52)
    return await _module_dispatch_spec(
        spec, arg, cache=cache, config=config, loop=loop, daemon_state=daemon_state,
        flags=flags, parse_flags=parse_forecast_flags, cache_suffix=forecast_cache_suffix,
    )
```
This keeps CLI/panel/inbound byte-identical for the non-bare case (arg already non-`None`) and reuses the existing fetch/render path for the bare case. (Carrier is planner discretion — the panel path already passes an explicit arg via `spec.takes_location`, wiring.py:489, so only the *inbound* bare path needs this.)

### D-05 default marker + F27 inbound 📍
```python
# Source: weatherbot/interactive/bot.py:192-221 render_embed + :504 call site.
# F27: inbound !weather <loc> must pass location= (currently render_embed(reply) with no location=).
# D-05: bare command → "(default)" suffix; named → plain.
location_label = resolved_name + (" (default)" if was_bare else "")
payload = render_embed(reply, location=location_label)   # bot.py:504 — add location=
# render_embed already emits `📍 {location}` when location is not None (bot.py:219-220).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Positional imperial/metric daily pairing | dt-anchored `select_today_daily` | Phase 32 (`weather/dates.py`) | The *forecast* path already dt-pairs (forecast.py:126-129); this phase extends the same idea to the daily briefing (F11/F107) |
| `_local_date_iso` copies in 3 modules | single `weather/dates.py` helpers | Phase 32 | Reuse, don't re-derive — CONTEXT.md §code_context |
| In-app dispatcher ladder | hub `registry` dispatcher + app `bind` closures | Phase 26 | The F02 guard lives in the hub now; the fix stays in the app shim (D-01) |
| In-memory `_selected_location` | generic `SelectedContext` | Phase 27 (D-02) | F22/F24 operate on `SelectedContext.set`/`.value`; single-writer on the gateway loop (no lock) |

**Deprecated/outdated:** none introduced by this phase. discord.py 2.7.1 `<t:unix:R>` relative-timestamp markdown (bot.py:221) is already used for the embed "Updated" line — the raw-ISO problem (D-07) is only in the *template/CLI text* timestamps (status.py:26, state.py:84, and the `{sent_at}`/`{checked_at}` path via `scheduler/context.py`), not the embed description.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The F02 carrier of choice is "pre-resolve default name and pass as arg"; planner may instead call `cache.lookup(None)` directly in the shim. | F02 fix | Low — both satisfy D-01 (app-side, no hub change); D-01 explicitly leaves the carrier to planner discretion. |
| A2 | Cache bounding = `TTLCache` maxsize + a pinned/protected plain-weather key; exact mechanism (LRU+pin vs. per-namespace caps vs. protected key) is planner discretion per D-04. | Cache bounding | Low — the invariant ("plain `!weather` entry never evicted") is fixed; the mechanism is explicitly discretionary. |
| A3 | The raw-ISO timestamps (D-07) render in the template/CLI text path (status.py:26, state.py:84, `scheduler/context.py`), NOT the discord embed description (which uses `<t:>` markdown). | D-07 / State of the Art | Low — verified by grepping every `.isoformat()`/`strftime` in the render paths; if a surface I didn't enumerate also shows ISO, it's the same one-line formatter swap. |
| A4 | The empty-token trailing-blank issue originates in `renderer.render` (renderer.py:156-168) leaving a blank line when a token like `{notice}`/`{footer_note}` substitutes to `""`. | Empty-token blanks | Low — the fix is a post-render `rstrip`/blank-line collapse; the exact template(s) affected are pinned by the golden snapshot diff. |

## Open Questions (RESOLVED)

1. **Which copy of the F28 duplicated header to drop (title vs. body first line)?**
   - What we know: `CommandReply.title = f"{title} — {location}"` (forecast.py:165) AND the template body's first line both render it; both embed and CLI duplicate.
   - What's unclear: dropping from the title changes the embed title; dropping from the body changes the field/CLI text. D-08 says "drop the dup from title or body so it appears once on both surfaces."
   - RESOLVED: drop the body's first line (keep the embed title as the single header) so the embed keeps a proper title and the body starts with content; regenerate the golden and verify the `.ambr` diff is exactly the removed line. Adopted in Plan 06 Task 2.

2. **F24 fix shape: roll-back vs. defer-then-edit?**
   - What we know: current order is set→ack (panel.py:248→252); ack can fail on an expired 3s token.
   - What's unclear: whether to (a) set → ack → roll back on `NotFound`/`HTTPException`, or (b) `defer()` first then `edit_original_response`.
   - RESOLVED: (a) roll-back — it's the smallest diff, keeps the single-`edit_message` ack the panel already uses, and the `previous = selection.value` capture makes the mutation reversible. Both are testable via `fake_interaction(is_done=...)` and by making `edit_message` raise. Adopted in Plan 04 Task 2.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| discord.py | F23/F24 interaction API | ✓ | 2.7.1 | — |
| cachetools | F13 guard + bounding | ✓ | installed (cache backend) | — |
| yahir_reusable_bot | hub PanelKit/dispatcher (read-only) | ✓ | v0.1.1 (pinned wheel in `.venv`) | — |
| pytest + syrupy | regression tests + golden | ✓ | pytest 9.0.3, syrupy 5.3.4 | — |
| uv | run tests / sync | ✓ | (project standard) | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — all machinery is in-repo/installed.

**Note (ops):** the live `weatherbot` systemd service on `yahir-mint` runs an editable install; a deploy needs a daemon restart to pick up new code (MEMORY: weatherbot-live-systemd-service). Not a build dependency, an ops step.

## Validation Architecture

> `nyquist_validation` is enabled (config.json `workflow.nyquist_validation: true`). Every fix lands **test-shaped**: a regression hook that fails pre-fix / passes post-fix ships with the fix (the comprehensive backfill is Phase 34). No live gateway or network — everything drives through the existing gateway-free harnesses.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + syrupy 5.3.4 (golden `.ambr` snapshots) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=`["tests"]`, addopts=`-ra`) |
| Quick run command | `uv run pytest tests/test_dispatch.py tests/test_cache.py tests/test_panel.py tests/test_models.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HARD-UI-01 | Bare `!weather` PRE-fix → generic error (crash reproduced) | unit | `uv run pytest tests/test_bot.py -k bare_weather_crashes -x` | ❌ Wave 0 |
| HARD-UI-01 | Bare `!weather` POST-fix → default-location embed | unit | `uv run pytest tests/test_bot.py -k bare_weather_default -x` | ❌ Wave 0 |
| HARD-UI-01 | All six bare location commands (`weather/sun/wind/alerts/uv/next-cloudy`) resolve default | unit | `uv run pytest tests/test_dispatch.py -k takes_location_default -x` | ❌ Wave 0 |
| HARD-UI-02 | F13: in-flight fetch that started before `invalidate()` does NOT re-populate | unit | `uv run pytest tests/test_cache.py -k stale_repopulate_rejected -x` | ❌ Wave 0 |
| HARD-UI-02 | F17: `_on_applied` invalidates cache BEFORE `channel.send` | unit | `uv run pytest tests/test_wiring.py -k invalidate_before_send -x` | ❌ Wave 0 (check test_lifecycle_module) |
| HARD-UI-02 | F22: renamed/removed selected location reconciled on reload (no stale `resolve_location` reject) | unit | `uv run pytest tests/test_lifecycle_module.py -k selection_reconcile -x` | ❌ Wave 0 |
| HARD-UI-02 | F23: zero-locations reload → panel degrades (no recursion, `_build_clone_view` non-raising) | unit | `uv run pytest tests/test_panel.py -k empty_locations_recover -x` | ❌ Wave 0 |
| HARD-UI-02 | F24: failed/expired ack rolls back selection (not silently advanced) | unit | `uv run pytest tests/test_panel.py -k ack_failure_rollback -x` | ❌ Wave 0 |
| HARD-UI-02 | Cache bounding: heavy forecast/flag entries never evict the plain `!weather` entry | unit | `uv run pytest tests/test_cache.py -k plain_entry_protected -x` | ❌ Wave 0 |
| HARD-UI-03 | F28: forecast header appears exactly once (embed + CLI) | golden | `uv run pytest tests/test_forecast_render.py tests/test_golden_embeds.py --snapshot-update` then review `.ambr` | ✅ (regen) |
| HARD-UI-03 | Empty-token render leaves no trailing blank line | unit/golden | `uv run pytest tests/test_forecast_render.py -k empty_token -x` | ❌ Wave 0 |
| HARD-UI-03 | D-07: timestamps render `09:00`, not raw ISO | unit | `uv run pytest tests/test_command_views.py -k humanized_timestamp -x` | ❌ Wave 0 |
| HARD-UI-03 | F11/F107: metric-missing daily → imperial high preserved (not current temp) | unit | `uv run pytest tests/test_models.py -k metric_missing_keeps_imperial -x` | ❌ Wave 0 |
| HARD-UI-03 | F107: briefing dt-pairs imperial/metric daily by dt, not index (skewed payload) | unit | `uv run pytest tests/test_models.py -k dt_paired_briefing -x` | ❌ Wave 0 |
| HARD-UI-03 | D-06: out-of-today label renders `Thu Jul 17` | unit/golden | `uv run pytest tests/test_forecast_render.py -k date_label -x` | ❌ Wave 0 |
| HARD-UI-03 | D-05/F27: bare → `📍 Toronto (default)`; named → `📍 London`; inbound shows 📍 | unit/golden | `uv run pytest tests/test_golden_embeds.py -k default_marker -x` | ❌ Wave 0 |

### Critical behaviors + sampling/edge cases (Nyquist targets)
The audit hid behind **pre-aligned fixtures and false-greens**; these are the exact edges to sample:
- **F107 dt-boundary temp mispairing (highest-value):** feed a briefing payload where the metric `daily[]` index 0 is a *different* local day than imperial (length/ordering skew, or one fetch across local midnight). Assert the rendered °F high pairs with the *same-dt* °C, not `daily[0]`. Existing tests pass because fixtures are pre-aligned (F107 scenario) — the new fixture must be deliberately skewed.
- **F11 metric-missing:** metric `daily[0].temp` partial/absent while imperial has a real max → assert the imperial high renders (not `temp_display`).
- **F13 generation race:** deterministic — inject a controllable fetch that lets the test call `invalidate()` between miss and store (the `timer`-injection pattern in test_cache.py already controls the clock; add a fetch-blocking hook). Assert the post-invalidate store is refused.
- **F24 ack-failure path:** `fake_interaction` with `response.edit_message` set to raise (`discord.NotFound`) → assert `selection.value` reverted to `previous`.
- **F23 empty-locations:** `holder.current().locations == []` → drive a Select/command callback → assert `_build_clone_view()` returns (no `ValueError`) and a disabled placeholder renders; then restore config and assert re-render works.
- **F22 reconcile:** seed `SelectedContext` with a name, hot-reload config removing/renaming it → assert the selection is reconciled (not left pointing at a name `resolve_location` rejects).

### How to test discord.py callbacks + off-loop writes without a gateway
- **Interaction callbacks:** the conftest `fake_interaction` factory (conftest.py:174-244) — a MagicMock shaped like `discord.Interaction` with `AsyncMock` `response.edit_message`/`send_message`/`edit_original_response`/`followup.send` and a `MagicMock` `response.is_done()`. Drive `LocationSelect.callback`/`PanelKit.on_command` directly; assert on the awaited mocks (test_panel.py already does this, lines 12-26, 300-317). For F24 expiry, make `response.edit_message` raise `discord.NotFound`.
- **Off-loop cache writes:** test_cache.py already injects a controllable `timer` for TTL boundaries and a stubbed `lookup_weather` (test_cache.py:73-190). For F13, add a fetch hook that pauses so the test can `invalidate()` mid-flight, then assert the store is rejected — no executor/loop needed (the cache method is plain blocking code called synchronously in tests).
- **Inbound path:** the `fake_discord_message` factory (conftest.py:122-160) drives `on_message` end-to-end with `AsyncMock` `channel.send` and a mocked `typing()` context manager — the F02 verify-first + regression harness.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_<touched>.py -x` (the quick subset above).
- **Per wave merge:** `uv run pytest` (full suite) — **trust exit code + `.ambr` diff, not the "N snapshots failed" banner** (syrupy quirk, MEMORY: pytest-snapshot-report-quirk).
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_bot.py` — F02 bare-command crash (RED) + default-resolution (GREEN); covers HARD-UI-01
- [ ] `tests/test_dispatch.py` — `takes_location` + `arg=None` forces fetch with default name; covers HARD-UI-01
- [ ] `tests/test_cache.py` — F13 stale-repopulate rejection + cache-bounding plain-entry protection; covers HARD-UI-02
- [ ] `tests/test_panel.py` — F22 reconcile, F23 empty-locations recovery, F24 ack-failure rollback; covers HARD-UI-02
- [ ] `tests/test_wiring.py` (or extend `test_lifecycle_module.py`) — F17 invalidate-before-send ordering; covers HARD-UI-02
- [ ] `tests/test_models.py` — F11 metric-missing keeps imperial; F107 dt-paired briefing (skewed fixture); covers HARD-UI-03
- [ ] `tests/test_forecast_render.py` / `test_golden_embeds.py` — F28 dedup (golden regen), empty-token blanks, D-05/06/07 formatting; covers HARD-UI-03
- [ ] A deliberately dt-skewed briefing fixture under `tests/fixtures/` for F107 (existing fixtures are pre-aligned)

*(Framework already installed — no `uv add` needed. All harnesses (`fake_interaction`, `fake_discord_message`, `load_fixture`, injectable `timer`) already exist in conftest.py.)*

## Security Domain

> `security_enforcement: true`, ASVS level 1. This is an internal, single-operator Discord surface (operator-gated panel, `.env` secrets). The phase touches error-rendering, cache, and interaction paths — the relevant ASVS categories:

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Operator gate is an existing hub concern (`interaction_check`, panelkit.py:320); unchanged this phase |
| V3 Session Management | no | discord.py owns the interaction token lifecycle; F24 handles expiry via `is_expired`/`NotFound` |
| V4 Access Control | no | Panel operator gate unchanged; no new command surface |
| V5 Input Validation | yes | F02 must NOT let user text reach the flag parser — the default is resolved via `resolve_location(None)` (no user string), and forecast taps build `ForecastFlags` directly (panel.py:350-358, Security V5 already established). New render formatters must clip provider-controlled text (existing `_clip`, bot.py:249). |
| V6 Cryptography | no | No crypto in scope |
| V7 Error Handling / Logging | yes | F02/F23 turn silent-swallow into correct behavior; must NOT log secrets. Note F12 (out of scope) shows the `appid=<key>` leak path exists in the *fetch* exception — this phase's error-rendering edits must not widen exception text exposure. |

### Known Threat Patterns for the Discord surface

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Stale-config served after reload (F13/F17/F22) | Tampering/Info-disclosure | Generation guard + invalidate-before-send + selection reconcile (D-03/D-04) — serve current config, not a pre-reload snapshot |
| Frozen panel / DoS-on-empty-config (F23) | Denial of Service | App-side degrade to a disabled, self-documenting Select (Pattern 3) — recoverable, never a swallowed freeze |
| Interaction token replay / expiry (F24) | Tampering | Ack-before-mutate + roll-back on `NotFound`/expired token so a failed ack can't silently advance shared state |
| Secret leak via exception text (F12, out of scope but adjacent) | Info-disclosure | Do NOT broaden any `except` to render exception text into a reply; keep the generic `_ERROR_REPLY` |

## Sources

### Primary (HIGH confidence — read directly this session)
- `weatherbot/interactive/dispatch.py` — F02 shim, hub delegation, `takes_location` carrier
- `weatherbot/interactive/cache.py` — F13 off-loop lock discipline, `invalidate`, `TTLCache` bound
- `weatherbot/interactive/panel.py` — F23 `_select_contributor` raise, F24 `LocationSelect.callback` set-before-ack
- `weatherbot/scheduler/wiring.py` — F17 `_on_applied` send-before-invalidate ordering, F22 `SelectedContext` seed
- `weatherbot/weather/models.py` — F11 `high/low_display` fallback, F107 independent imperial/metric daily selection
- `weatherbot/interactive/commands/forecast.py` — F28 dup header (title == body), the EXISTING dt-pairing guard to reuse, `_day_label`
- `weatherbot/interactive/bot.py` — F27 `render_embed(reply)` no `location=`, `on_message` envelope, embed `<t:>` timestamps
- `weatherbot/interactive/registry.py` — `CommandSpec.takes_location` field, `_SPECS`, `_wire_handlers` bind closures
- `weatherbot/config/loader.py` — `resolve_location(config, None)` default resolution
- `weatherbot/weather/dates.py` — Phase-32 `select_today_daily`/`local_date_for` anchoring to reuse
- `templates/renderer.py` — `render`/`render_forecast` (empty-token substitution)
- `.venv/.../yahir_reusable_bot/discord/panelkit.py` — `on_command`, `_build_clone_view`, `_safe_error_edit` (the F23 recursion mechanism)
- `.venv/.../yahir_reusable_bot/registry/dispatch.py` — the guard `if arg is not None or spec.needs_flags:` (F02 root)
- `.venv/.../yahir_reusable_bot/discord/selection.py` — `SelectedContext.set`/`.value` (single-writer, no lock)
- `discord` 2.7.1 (imported) — verified `InteractionResponse.{defer,edit_message,is_done,send_message}`, `Interaction.{is_expired,followup,edit_original_response}`
- `.planning/WHOLE-PROJECT-REVIEW.md` — F02/F11/F13/F17/F22/F23/F24/F27/F28/F107 scenarios + file:line
- `.planning/ROADMAP.md` §Phase 33, `.planning/REQUIREMENTS.md` HARD-UI-01/02/03
- `../Reusable/YahirReusableBot/ECOSYSTEM.md` §1-2 — hub-clean invariant, pinned-wheel jurisdiction

### Secondary (MEDIUM confidence)
- `tests/conftest.py`, `tests/test_panel.py`, `tests/test_cache.py`, `tests/test_bot.py`, `tests/test_dispatch.py` — existing harness patterns (fake_interaction, fake_discord_message, injectable timer)

### Tertiary (LOW confidence)
- none — every claim is grounded in a file read this session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all versions verified from `uv.lock` and live import.
- Architecture / fix mechanics: HIGH — every touchpoint read from source; hub read from the installed wheel; discord.py API enumerated live.
- Pitfalls: HIGH — derived from the actual code structure (hub recursion, lock discipline, clone-view re-derivation), not generic advice.
- Validation: HIGH — the harnesses referenced already exist in conftest.py; test-shaped-fix convention inherited from Phase 32.

**Research date:** 2026-07-12
**Valid until:** 2026-08-11 (30 days — stable; no fast-moving external deps. Only invalidated by a hub repin or a discord.py major bump.)
