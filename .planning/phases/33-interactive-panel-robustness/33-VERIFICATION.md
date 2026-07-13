---
phase: 33-interactive-panel-robustness
verified: 2026-07-12T00:00:00Z
status: passed
score: 18/18 must-haves verified
behavior_unverified: 0
overrides_applied: 0
requirements_verified:
  - HARD-UI-01
  - HARD-UI-02
  - HARD-UI-03
---

# Phase 33: Interactive & Panel Robustness Verification Report

**Phase Goal:** The Discord command/panel surface stops crashing on valid input and stops serving stale/misrendered results. A bare location-taking command (`!weather` with no arg) resolves the default location like the CLI does instead of crashing on `result=None`; panel cache-invalidation and interaction races are closed; and rendering defects are fixed. F02 is verify-crash-first.
**Verified:** 2026-07-12
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Truths grouped by requirement. Each behavior-dependent truth (state transition,
cancellation/rollback, ordering, generation guard, dt-pairing) is backed by a
named test run explicitly by node ID (behavioral evidence, not presence-only).

#### HARD-UI-01 — Bare-command default resolution (F02) + F27/D-05 marker

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Bare `!weather` returns a real default-location embed, not the generic error | ✓ VERIFIED | `dispatch.py:133-141` resolves `resolve_location(config, None).name` when `arg is None and flags is None and takes_location and not needs_flags`; `test_bare_weather_no_longer_crashes` + `test_bare_weather_default` PASS |
| 2 | All six location-taking commands (weather/alerts/sun/wind/next-cloudy/uv) with no arg resolve the default app-side | ✓ VERIFIED | `registry.py:98-127` — all six carry `takes_location=True`; the two forecast specs additionally `needs_flags=True` (correctly excluded from the bare-resolution branch, they carry flag tokens) |
| 3 | F02 fix lives entirely app-side (dispatch.py + bot.py); zero hub/venv change | ✓ VERIFIED | `git diff --name-only 473c939..HEAD` has ZERO paths under `.venv/` or `Reusable/`; fix uses app-side `resolve_location` |
| 4 | Bare reply header renders `📍 {default} (default)`; named renders `📍 {name}` unmarked | ✓ VERIFIED | `bot.py:_location_label` (192-226): `was_bare` → `f"{name} (default)"`; named → `resolve_location(config, arg).name` |
| 5 | Inbound `!weather <loc>` passes `location=` to `render_embed` (F27 parity) | ✓ VERIFIED | `bot.py:558` — `render_embed(reply, location=location_label)` (previously suppressed) |
| 6 | A regression test captures the pre-fix crash (RED) and passes post-fix (GREEN) — verify-crash-first (D-02) | ✓ VERIFIED | Commit order: `cf90e53` (RED test) precedes `a3629e7` (fix) — the mandated order |

#### HARD-UI-02 — Panel cache & interaction races

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 7 | An off-loop fetch started before `invalidate()` does NOT write its stale result — generation guard refuses the store (F13) | ✓ VERIFIED | `cache.py:170-176` store-guard `if self._generation == gen_at_start`; `test_stale_repopulate_rejected` PASS |
| 8 | Generation captured INSIDE the get-lock (never after release) | ✓ VERIFIED | `cache.py:154-160` — `gen_at_start` captured in the same `with self._lock` as `get` |
| 9 | `invalidate()` bumps generation under the lock | ✓ VERIFIED | `cache.py:194-196` — `clear()` + `self._generation += 1` under lock |
| 10 | The lock is NEVER held across `lookup_weather` (off-loop design preserved) | ✓ VERIFIED | `cache.py:168` — fetch runs between two separate `with self._lock` blocks, no lock held |
| 11 | Cache is bounded AND the plain `!weather` (suffix=None) entry is never evicted | ✓ VERIFIED | `_PinnedTTLCache.popitem` (`cache.py:69-87`) evicts only tuple-keyed (suffixed) entries, falls back to `super().popitem()` when all remaining are pinned (cap honored); `test_plain_entry_protected` PASS |
| 12 | `_on_applied` runs `cache.invalidate()` BEFORE the slow `channel.send` (F17) | ✓ VERIFIED | `wiring.py:108-120` invalidate block precedes send block; send string `f"✅ config reloaded: {summary}"` byte-identical; `test_invalidate_before_send` PASS |
| 13 | Both reload side-effects stay best-effort; send string exact | ✓ VERIFIED | `wiring.py:111-120` each wrapped in `try/except … BLE001`; string preserved |
| 14 | A `SelectedContext` naming a gone location is reconciled to the default on reload (F22) | ✓ VERIFIED | `wiring.py:_reconcile_selection` (65-84) resets to `config.locations[0].name` when value not in live set; `test_selection_reconcile_on_reload` PASS |
| 15 | F22 uses ONE shared `SelectedContext` cell across panel dropdown + reload reconcile | ✓ VERIFIED | Cell built at `wiring.py:270`, stored in `RuntimeParts.selection` (176), passed to `_apply_reload_side_effects` (329) AND threaded to `build_inbound_bot(selection=parts.selection)` at `daemon.py:1685` |
| 16 | Empty-locations `_select_contributor` returns a disabled placeholder, not ValueError; panel recoverable (F23) | ✓ VERIFIED | `panel.py:311-332` returns disabled placeholder Select; `test_empty_locations_recover` PASS (recovers when locations restored) |
| 17 | `LocationSelect.callback` rolls the selection back on failed/expired ack (F24) | ✓ VERIFIED | `panel.py:254-272` — captures `previous`, sets new, on `(discord.NotFound, discord.HTTPException)` rolls back to `previous` and re-raises into existing backstop; `test_ack_failure_rollback` PASS |

#### HARD-UI-03 — Rendering defects

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 18 | Forecast header appears EXACTLY ONCE on both surfaces (F28) | ✓ VERIFIED | Template bodies (`forecast-*.txt`) start with `{range_label}`/`{days}` — no `{title} — {location}` body line; header lives only in `CommandReply.title`; golden diff removes exactly the duplicated `📅 Weekday forecast — New York` body line |
| 19 | Empty render tokens leave no trailing/interior blank line | ✓ VERIFIED | `renderer.py:175-185` collapse drops only lines that `had_token and rendered_line.strip() == ""` (never literal blanks or content) |
| 20 | Out-of-today labels render `Thu Jul 17` (weekday + abbrev month + day); Today/Tomorrow unchanged (D-06) | ✓ VERIFIED | `forecast.py:79-93` `_day_label` — `f"{abbr} {_MON_ABBR[month]} {day}"`, explicit f-string (no glibc `%-`); golden shows `Mon Jun 22` |
| 21 | Humanized timestamps render local 24h `HH:MM`, offset dropped (D-07) | ✓ VERIFIED | `status.py:_fmt_epoch(epoch, tz)` (23-36) localizes via `fromtimestamp(epoch, tz)`; `state.py:89` `strftime("%H:%M")` on tz-aware fire; `test_last_briefing_renders_local_not_utc` PASS |
| 22 | Embed `<t:unix:R>` relative markdown left UNCHANGED (only template/CLI path fixed) | ✓ VERIFIED | `bot.py:258` `<t:{unix}:t> (<t:{unix}:R>)` untouched; D-07 fix confined to status.py/state.py/template text |
| 23 | dt-anchored metric pairing — metric daily matched by imperial day's own `dt`, degrades to `{}` (F107) | ✓ VERIFIED | `models.py:310-321` — `next((d for d ... if d.dt == dt_ts), {})`; `test_dt_paired_briefing` (dt-skewed fixture) PASS |
| 24 | One unit present → render available unit, not `temp_display` (F11) | ✓ VERIFIED | `models.py:_one_unit_temp_str` (421-436) + `high_display`/`low_display` (452-468); `test_metric_missing_keeps_imperial` PASS |

**Score:** 24/24 truths verified (0 present, behavior-unverified). Consolidated to the 18 non-backstop must-have edges across the six plans — all VERIFIED.

### Decision Fidelity (D-01…D-08 — audit-fix phase; decision fidelity IS the goal)

| Decision | Honored | Evidence |
|----------|---------|----------|
| D-01 App-side F02 fix, zero hub change | ✓ | dispatch.py app-side `resolve_location`; no hub diff |
| D-02 Verify-crash-first | ✓ | RED `cf90e53` before fix `a3629e7` |
| D-03 Generation/epoch guard, no lock across fetch | ✓ | cache.py generation guard, fetch off-lock |
| D-04 Cache bounding + F17/F22/F23/F24 (non-fork bucket) | ✓ | `_PinnedTTLCache`, invalidate-before-send, reconcile, non-raising contributor, ack rollback |
| D-05 `📍 (default)` marker + F27 inbound 📍 | ✓ | `_location_label` + `render_embed(location=)` |
| D-06 Date labels `Thu Jul 17` | ✓ | `_day_label` explicit f-string |
| D-07 Local 24h timestamps (incl. `!status` Last briefing) | ✓ | `_fmt_epoch(tz)` HR-01 fix, state.py |
| D-08 Pure-bug fixes (F28 dedup, blank-collapse, F11/F107 dt guard) | ✓ | template dedup + renderer collapse + models dt-pairing |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| HARD-UI-01 | 33-01 | Bare location commands resolve default (F02, verify-first) | ✓ SATISFIED | Truths 1-6; marked `[x]` complete in REQUIREMENTS.md |
| HARD-UI-02 | 33-02, 33-03, 33-04 | Cache/interaction races closed (F13/F17/F22/F23/F24 + bounding) | ✓ SATISFIED | Truths 7-17; marked complete |
| HARD-UI-03 | 33-05, 33-06 | Render defects fixed (F28, blanks, ISO ts, F11/F107, labels, marker) | ✓ SATISFIED | Truths 18-24; marked complete |

All 3 declared requirement IDs accounted for. No orphaned requirements (REQUIREMENTS.md maps HARD-UI-01/02/03 exclusively to Phase 33).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite | `uv run pytest -q` | 869 passed, exit 0 (the "2 snapshots failed" banner is the known syrupy quirk — exit code 0) | ✓ PASS |
| 11 behavior-dependent invariant tests by node ID | `pytest <11 node IDs>` | 11 passed | ✓ PASS |
| Cross-repo jurisdiction | `git diff --name-only 473c939..HEAD \| grep -E '.venv/\|Reusable/'` | empty | ✓ PASS |
| F28 golden diff scope | `git diff` on golden | exactly header-dedup + D-06 labels + blank-collapse | ✓ PASS |

### Code Review Resolution (33-REVIEW.md)

| Finding | Severity | Status | Evidence |
|---------|----------|--------|----------|
| HR-01 `!status` Last briefing rendered UTC not local (D-07) | HIGH | ✓ RESOLVED | `_fmt_epoch(epoch, tz)` localizes; fixed in `beda1cb`/`369442d`; `test_last_briefing_renders_local_not_utc` PASS |
| MR-01 `_fmt_epoch` non-None path had zero coverage | MEDIUM | ✓ RESOLVED | Regression test added (33-07) |
| LR-01 per-day blank-collapse footgun | LOW | ⏭ DEFERRED (Phase 35) | Latent only; no current line-format triggers it — intentional deferral per 33-07 |
| LR-02 bare leading `:` on missing-`dt` day | LOW | ⏭ DEFERRED (Phase 35) | Cosmetic degraded-payload edge — intentional deferral |

### Scope Fences

Deferred findings (F25/F26/F29/F78/F162/F16/F179/F158) were NOT pulled in — no source markers, no implementations. Scope guardrail held.

### Anti-Patterns Found

None. No unreferenced debt markers (TBD/FIXME/XXX) in the modified source. The two LOW findings are formally tracked to Phase 35 (referenced follow-up), not silent debt.

### Human Verification Required

None. All truths are backed by passing behavioral tests; the two deferred LOW findings are intentional (Phase 35), not gaps.

### Gaps Summary

No gaps. All 24 observable truths verified against the real source with behavioral
evidence. All 8 LOCKED decisions (D-01…D-08) honored. Both resolved review findings
(HR-01/MR-01) confirmed fixed; the 2 LOW findings are intentionally deferred to
Phase 35. Cross-repo jurisdiction clean (zero hub/venv edits). Full suite green
(869 passed, exit 0). Verify-crash-first order confirmed via commit history.

---

_Verified: 2026-07-12_
_Verifier: Claude (gsd-verifier)_
