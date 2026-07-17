---
phase: 33-interactive-panel-robustness
reviewed: 2026-07-12T00:00:00Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - weatherbot/interactive/dispatch.py
  - weatherbot/interactive/bot.py
  - weatherbot/interactive/cache.py
  - weatherbot/interactive/panel.py
  - weatherbot/interactive/commands/forecast.py
  - weatherbot/interactive/commands/status.py
  - weatherbot/interactive/state.py
  - weatherbot/scheduler/wiring.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/weather/models.py
  - templates/renderer.py
findings:
  blocker: 0
  high: 1
  medium: 1
  low: 2
  total: 4
status: issues
---

# Phase 33: Code Review Report

**Reviewed:** 2026-07-12
**Depth:** deep (cross-file: dispatch→cache→wiring→daemon call chains, TTLCache eviction internals, golden-snapshot parity)
**Files Reviewed:** 11 source files
**Status:** issues_found

## Summary

Phase 33 is an audit-fix phase against locked decisions D-01…D-08. I traced every
focus item the prompt called out. The concurrency-sensitive fixes are **correct**:

- **F13 generation guard (cache.py):** generation is captured INSIDE the same lock
  as the `get` (line 154-160), re-checked at store under the lock (line 170-176),
  and the `lookup_weather` fetch runs with NO lock held (line 168). No TOCTOU
  window admits a stale write — a reload mid-fetch bumps the generation and the
  store self-rejects. Off-loop design preserved.
- **`_PinnedTTLCache` eviction (cache.py):** verified against the installed
  `cachetools` `Cache.__setitem__`/`TTLCache.popitem`. `popitem` scans LRU order
  and evicts the first tuple-keyed (suffixed) entry, protecting the str-keyed plain
  `!weather` entry under heavy forecast/flag load. When ALL live entries are pinned
  str keys it falls back to `super().popitem()`, so the size cap is still honored —
  **no unbounded growth**. The plain-weather entry can never be the evicted one
  under tuple churn (the stated invariant holds).
- **F24 ack-before-mutate (panel.py):** rolls the shared selection back to
  `previous` on `discord.NotFound`/`HTTPException` (line 261-272) and re-raises into
  the EXISTING module `View.on_error`/`_safe_error_edit` backstop — no NEW blanket
  swallow is added. No path leaves the mutation persisted after a failed ack.
- **F23 non-raising contributor (panel.py):** the empty-locations branch returns a
  disabled placeholder `discord.ui.Select` (line 322-332) instead of raising, so
  `_build_clone_view()` cannot recurse into the same ValueError. Restoring locations
  re-renders a normal enabled `LocationSelect` (recoverable, not permanent).
- **F22 selection reconcile (wiring.py/daemon.py):** ONE shared `SelectedContext`
  cell is created at `build_runtime` (wiring.py:270), threaded through
  `RuntimeParts.selection` → `run_daemon` → `build_inbound_bot(selection=parts.selection)`
  (daemon.py) → used-if-non-None in the factory (wiring.py:592). The panel dropdown
  and the reload reconcile genuinely share one cell. `_reconcile_selection` and the
  best-effort wrapping are correct.
- **F17 ordering (wiring.py):** `_apply_reload_side_effects` runs `cache.invalidate()`
  (line ~100) provably BEFORE `channel.send` (line ~106). The reload-outcome send
  string `f"✅ config reloaded: {summary}"` is byte-identical to the pre-fix form.
- **F107/F11 dt-pairing (models.py:310-321):** pairs the metric daily entry by the
  imperial day's OWN `dt`, degrades to `{}` on no match (never a mispair), and falls
  back to local-date selection only when the imperial entry carries no `dt`. F11
  `_one_unit_temp_str` (line 421-436) correctly keeps the PRESENT unit's high/low
  (not the current temp) and only falls back to `temp_display` when BOTH sides are
  missing.
- **F28 header dedup:** confirmed against the updated goldens — the duplicated body
  header line is removed from all four templates; the header now appears exactly once
  (as the CLI `CommandReply.title` line / the embed title) on both surfaces.
- **Cross-repo jurisdiction:** `git diff --name-only 473c939..HEAD` has ZERO paths
  under `.venv/` or `../Reusable/`. All fixes are app-side. Hub stays
  weather-domain-free.

One genuine correctness defect remains: the `status` "Last briefing" timestamp is
rendered in **UTC** while decision **D-07 mandates local** time and the code's own
docstring claims local — producing a time that is both wrong and inconsistent with
the (correctly-local) "Next send" times on the same status card.

## High

### HR-01: `status` "Last briefing" timestamp renders UTC, not local (violates D-07)

**File:** `weatherbot/interactive/commands/status.py:34`
**Issue:** `_fmt_epoch` claims (docstring, line 23-30) to render "a humanized
**local** 24-hour `HH:MM` clock (D-07)" with the "already-localized clock" offset
dropped, but the implementation formats in UTC:

```python
return datetime.fromtimestamp(epoch, timezone.utc).strftime("%H:%M")
```

`last_success_utc` is a Unix-UTC epoch; converting it with `tz=timezone.utc` and
formatting `%H:%M` yields the **UTC** wall clock, not local. D-07 (locked) says
"Humanized timestamps: **local** 24-hour (e.g. `09:00`)". This is user-visible and
self-inconsistent: on the same `!status` card, "Next send — Home" is genuinely local
(state.py `next_fires` formats an already-tz-aware fire time, correct), so an
operator in a non-UTC zone sees e.g. "Next send — Home: 09:00" (local) beside
"Last briefing: 13:00" (UTC) for a briefing that fired at 09:00 local. The whole
project is timezone-aware (home/travel cities), so this drift is real, not
hypothetical.

The bug is uncovered: the only golden that touches this path
(`test_status_stdout_golden`) deliberately hits the `None` → "none yet" branch
(test_golden_cli.py:121-139), so `_fmt_epoch`'s formatting never runs in tests.

**Fix:** Format in the operator's local zone. "Last briefing" is not per-location,
so pick a defensible local zone — the first configured location's tz (the same
default the panel/F02 default-resolution use), threaded in from the live config, or
the daemon's configured display tz. Minimal shape:

```python
def _fmt_epoch(epoch: int | None, tz: ZoneInfo) -> str:
    if epoch is None:
        return "none yet"
    # last_success_utc is a Unix-UTC epoch; localize to the display tz (D-07 local).
    return datetime.fromtimestamp(epoch, tz).strftime("%H:%M")
```

and pass the resolved zone at the call site (status.py:99), e.g.
`ZoneInfo(daemon_state.holder.current().locations[0].timezone)` with a UTC fallback
when no locations are configured. Add a regression test that stamps a known epoch and
asserts the LOCAL `HH:MM` (the missing coverage that let this slip).

## Medium

### MR-01: `_fmt_epoch` non-None path has zero test coverage

**File:** `weatherbot/interactive/commands/status.py:32-34` (gap:
`tests/test_golden_cli.py:121`, `tests/test_status.py`)
**Issue:** Phase 33 is explicitly "each fix lands test-shaped (RED pre-fix / GREEN
post-fix)". The `_fmt_epoch` change (ISO→`HH:MM`) shipped with NO test exercising a
non-`None` epoch — the status golden isolates the `None`/"never run yet" branch on
purpose (a determinism/host-leak guard), and `test_status.py` only asserts
`last_success_utc is not None` at the store level, never the rendered string. That
coverage hole is exactly why HR-01 (UTC vs local) went unnoticed.
**Fix:** Add a unit test that constructs a `DaemonState` with a heartbeat holding a
fixed `last_success_utc` epoch and a known location tz, then asserts the rendered
"Last briefing" line equals the expected LOCAL `HH:MM`. This both closes the gap and
pins HR-01's fix. (Pairs directly with HR-01 — do them together.)

## Low

### LR-01: empty-token line collapse also runs on per-day `line_fmt`, can drop a blank day line

**File:** `templates/renderer.py:171-185` (via `render_forecast` line 211:
`render(line_fmt, day)`)
**Issue:** The new blank-line collapse in `render()` runs for EVERY `render()` call,
including the per-day `render(line_fmt, day)` inside `render_forecast`. If a day's
`line_fmt` is a single line and every token on it substitutes to "" for that day, the
whole day line is dropped (`had_token and rendered_line.strip() == ""`). Today's day
line-formats always carry a non-empty `{temp}`/`{low}` so this cannot fire in
practice, but the collapse was designed for the whole-message header/footer
(`{notice}`/`{footer_note}`), not the per-day loop — applying it to per-day lines is
a latent footgun if a future compact line-format ever reduces to a single optional
token. A day silently vanishing from a forecast is a data-loss shape, not a cosmetic
one.
**Fix:** Scope the collapse to the whole-message render only — e.g. add a
`collapse_blank_tokens: bool = True` parameter to `render()` and call the per-day
`render(line_fmt, day, collapse_blank_tokens=False)` from `render_forecast`, so the
per-day loop keeps every selected day regardless of token emptiness. (Low now because
no current line-format can trigger it; flagging to prevent a future regression.)

### LR-02: missing-`dt` day renders a leading `":"` in compact forecast lines

**File:** `weatherbot/interactive/commands/forecast.py:150-154`
**Issue:** When a selected day's imperial bucket carries no `dt`, `label` is set to
`""` (line 154). The compact per-day line-format leads with `{label}:` so that day
renders as `": 80°F (27°C)/… Clouds"` — a bare leading colon with no day name. It's a
degraded payload edge (dt absent), non-crashing and non-lossy (the line is kept
because it's non-blank), but the output is slightly malformed. Consistent with the
F107/F11 "degrade gracefully" intent, just cosmetically rough.
**Fix:** When `label` is empty, fall back to a neutral stand-in (e.g. the day index
or a `"—"`) before building `day_tokens`, or omit the leading `": "` when the label
token is empty in the compact line-format. Cosmetic; safe to defer to Phase 35 if not
folded in here.

---

_Reviewed: 2026-07-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
