# Phase 33: Interactive & Panel Robustness - Context

**Gathered:** 2026-07-12
**Status:** Ready for planning
**Mode:** advisor (interactive). Audit-driven correctness phase — the WHAT is
fixed by ROADMAP success criteria + `WHOLE-PROJECT-REVIEW.md` findings, so the
decisions below encode the audit's diagnosis. Unlike the pure-backend tz phase
(32, run `--auto`), the user actively chose the three forking decisions here —
two mechanism forks and the user-visible render formatting — because this is the
Discord-facing surface. Mechanism-level detail beyond these picks is
planner/researcher discretion. See `[[decide-for-me-on-deep-technical-phases]]`.

<domain>
## Phase Boundary

The Discord command/panel surface stops crashing on valid input and stops
serving stale/misrendered results. Three locked requirements, each a bucket of
`WHOLE-PROJECT-REVIEW.md` findings:

1. **HARD-UI-01 — bare location commands resolve the default (F02, `interactive/dispatch.py:119`, SWEEP-NEW critical).**
   Bare `!weather`/`!sun`/`!wind`/`!alerts`/`!uv`/`!next-cloudy` (arg=None,
   needs_flags=False) hit the guard `if arg is not None or spec.needs_flags:`,
   which is False → the fetch is SKIPPED → `result` stays None → the bind
   closure calls `weather_views.weather(None)` → `result.forecast` →
   AttributeError → `on_message` envelope → generic "something went wrong".
   The CLI's documented default-location behavior (`resolve_location(None)`) is
   dead over Discord. Root cause: the dispatcher has a `needs_flags` signal but
   no `takes_location` signal. **Verify-crash-first is mandatory** — reproduce
   the bare `!weather` crash on the Discord surface before landing the fix.

2. **HARD-UI-02 — panel cache & interaction races closed.**
   - **F13 (`interactive/cache.py:119`) stale re-populate:** an off-loop fetch
     that started before a hot-reload `invalidate()` re-inserts a pre-reload
     result (old lat/lon/units/template) that survives to TTL. No epoch guard.
   - **F17 (`scheduler/wiring.py:213`) send-before-invalidate ordering:**
     `on_applied` calls `channel.send` before `cache.invalidate`, so a slow
     Discord post delays invalidation and inbound `!weather <loc>` serves OLD
     coords until invalidate finally fires.
   - **F22 (`scheduler/wiring.py:452`) stale selection on reload:**
     `SelectedContext` seeded once at wiring, never reconciled on hot-reload; a
     renamed/removed selected location → stale name → `resolve_location` →
     UnknownLocationError for a location the user never sees selected.
   - **F23 (`interactive/panel.py:252`) empty-locations render recursion:**
     select/command re-render raises on zero locations; `_safe_error_edit` ALSO
     calls `_build_clone_view()` → same ValueError → swallowed → panel frozen.
   - **F24 (`interactive/panel.py:248`, PLAUSIBLE) ack ordering:**
     `LocationSelect.callback` mutates the shared selection BEFORE acking; a
     failed/expired `edit_message` leaves selection advanced with no re-render.
   - **Unbounded/mis-evicting cache:** bound the cache so heavy forecast/flag
     use can't evict the plain-weather entry it should protect.

3. **HARD-UI-03 — rendering defects fixed.**
   - **F28 (`interactive/commands/forecast.py:165`) duplicated header:**
     `CommandReply.title` AND the rendered body's first line are both
     "{title} — {location}" (frozen into the golden snapshot; both surfaces).
   - **Empty-token trailing blank lines** from empty render tokens.
   - **Raw ISO timestamps** (e.g. sent-at/checked-at) rendered un-humanized.
   - **F11/F107 dt-mispaired temps:** imperial/metric daily paired POSITIONALLY
     (`models.py:302`) with no dt guard → °C high paired to the wrong day's °F
     near a boundary (F107 is the missing test).
   - **Ambiguous date labels** for out-of-today forecast buckets.
   - **F27 (`interactive/bot.py:504`) unmarked location:** inbound
     `!weather <loc>` calls `render_embed` with no `location=`, so the 📍
     header the panel always shows is suppressed — a D-07 parity drift.

**In scope:** the findings above, each fixed **test-shaped** (a regression hook
that fails pre-fix / passes post-fix lands with each fix; the comprehensive
suite is Phase 34). F02 fixed only after the Discord-surface crash is
reproduced.

**Out of scope:**
- Other interactive/command findings NOT in the three HARD-UI buckets — F25
  (bare `+`/`-` flag token → ValueError → generic error), F26 (flag-grammar
  footgun), F29 (`next_cloudy` drops nocturnal cloudy hours), F78 (`!panel`
  trailing text silent-drop), F162 (add/drop same-day) → **Phase 35 Cleanup
  Sweep** (their assigned home; do not pull them in here — scope guardrail).
- F16 timestamp *staleness* on a cached read (cosmetic) — the ISO→human
  *format* fix is in HARD-UI-03; the "cached read shows a stale clock" behavior
  is a separate cosmetic item, deferred unless it falls out trivially.
- F179 reconnect supervisor, F158 PHASE-2 reconcile reject-hook — scheduler/
  lifecycle, not the UI buckets.
- All HUB findings route UPSTREAM to `yahir_reusable_bot` (human-gated repin) —
  do NOT fix hub source here.
- No new user features (scope creep → deferred).

</domain>

<decisions>
## Implementation Decisions

### HARD-UI-01 — Bare-command default resolution (F02)
- **D-01 — App-side fix only; zero hub change.** In the app's `dispatch_spec`
  shim (`interactive/dispatch.py`), when `arg is None` for a location-taking
  spec, resolve the default location app-side and pass it through so the
  existing fetch path runs (the CLI's `resolve_location(None)` behavior, now on
  Discord). **Rationale:** the skip-fetch guard lives in the shared hub
  dispatcher, but default-location resolution (`resolve_location(None)`) is
  weather-domain and lives app-side — a hub `takes_location` signal would still
  need an injected default-resolver hook, adding coupling and a human-gated
  repin for no benefit. App-side keeps the hub weather-domain-free (v2.0 litmus)
  and ships this phase. *The app needs a "which specs take a location" signal;
  it already owns `_SPECS`/`_wire_handlers`, so that lives app-side too —
  exact carrier (per-spec flag vs. app-side set) is planner discretion.*
- **D-02 — Verify the crash first.** Reproduce bare `!weather` →
  AttributeError → generic error on the Discord surface (or a faithful harness
  of `on_message` → `dispatch_spec`) and capture that evidence BEFORE landing
  the fix; the same repro becomes the regression test's RED.

### HARD-UI-02 — Panel cache & interaction races
- **D-03 — Generation/epoch guard for the stale re-populate (F13).**
  `invalidate()` bumps a generation counter; an in-flight off-loop fetch
  captures the generation at start and refuses to write its result if the
  generation has moved. Kills the stale re-populate WITHOUT serializing
  fetches — preserves the deliberate off-loop-fetch design (rejected:
  lock-around-fetch, which serializes lookups and risks blocking the gateway
  path). *Counter placement / generation-vs-epoch naming is planner discretion.*
- **D-04 — The rest of the cache bucket is fixed regardless (not forks):**
  - Reorder `on_applied` so `cache.invalidate` runs BEFORE the (slow) Discord
    `channel.send` (F17).
  - Reconcile `SelectedContext` on hot-reload — a renamed/removed selected
    location must not leave a stale name that `resolve_location` rejects (F22).
  - Guard the empty-locations re-render so `_safe_error_edit` cannot recurse
    into the same `_build_clone_view()` ValueError and freeze the panel (F23) —
    fail into a user-visible recoverable state, not a swallowed log.
  - Ack before mutating the shared selection (or roll back on ack failure) so a
    failed/expired interaction can't leave selection silently advanced (F24).
  - Bound the cache with the plain-weather entry protected from eviction so
    heavy forecast/flag use can't evict it. *Bounding mechanism (protected key
    vs. per-namespace caps vs. size-cap LRU with pin) is planner discretion; the
    invariant: the plain `!weather` entry is never the one evicted.*

### HARD-UI-03 — Rendering formatting (user-visible choices)
- **D-05 — Default-location marker: 📍 + "(default)" suffix.** On bare/no-arg
  location commands, append " (default)" to the location name in the 📍 header
  (e.g. `📍 Toronto (default)`); named-location replies stay unmarked
  (`📍 London`). This ALSO restores the 📍 header on the inbound path (F27) —
  pass `location=` to `render_embed` on `interactive/bot.py:504` so inbound
  matches the panel's always-present indicator.
- **D-06 — Out-of-today date labels: weekday + abbreviated month + day**
  (e.g. `Thu Jul 17`). Most explicit; never ambiguous past a week/month
  boundary. Replaces the current ambiguous labels the audit flags.
- **D-07 — Humanized timestamps: local 24-hour** (e.g. `09:00`), timezone
  offset dropped (already localized). Replaces raw ISO (`2026-07-12T09:00:00+00:00`).
- **D-08 — Pure-bug render fixes (no choice, fix + regression-test):** remove
  the F28 duplicated header line (drop the dup from title or body so it appears
  once on both surfaces; the golden snapshot updates with it); strip trailing
  blank lines from empty render tokens; add the dt-pairing guard so
  imperial/metric daily temps are matched by their own `dt`/local date, not
  positional index (F11/F107).

### Claude's Discretion
- Exact carrier of the app-side "takes_location" signal (D-01); generation
  counter placement/naming (D-03); cache-bounding mechanism (D-04); how the
  empty-locations recovery cue is surfaced (D-04/F23); locale ordering details
  of the date/time formatters. All bounded by the invariants stated above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Findings source (authoritative — the phase's spec)
- `.planning/WHOLE-PROJECT-REVIEW.md` — F02, F11, F13, F17, F22, F23, F24, F27,
  F28, F107 full scenarios/evidence; the exact file:line and repro for each.
- `.planning/ROADMAP.md` §"Phase 33: Interactive & Panel Robustness" — goal,
  success criteria, F02 verify-first mandate, UI-gate-skipped note.
- `.planning/REQUIREMENTS.md` — HARD-UI-01/02/03 wording + traceability.

### Cross-repo jurisdiction (F02 fix stays app-side)
- `CLAUDE.md` §"Ecosystem — consumer of `yahir_reusable_bot`" — placement
  litmus (reusable mechanism → hub; app-specific wiring/domain → here),
  human-gated repin rule.
- `../Reusable/YahirReusableBot/ECOSYSTEM.md` — read before any cross-repo work;
  confirms the hub dispatcher stays weather-domain-free.

### Code touchpoints
- `weatherbot/interactive/dispatch.py` — `dispatch_spec` shim + the hub guard it
  delegates to (F02 fix site, app-side).
- `weatherbot/interactive/cache.py` §~119 — `ForecastCache` (F13 generation
  guard; bounding).
- `weatherbot/scheduler/wiring.py` §213/§452 — `on_applied` ordering (F17),
  `SelectedContext` seed (F22).
- `weatherbot/interactive/panel.py` §248/§252 — ack ordering (F24),
  `_safe_error_edit`/`_build_clone_view` recursion (F23).
- `weatherbot/interactive/bot.py` §504 — inbound `render_embed` location= (F27).
- `weatherbot/interactive/commands/forecast.py` §165 — duplicated header (F28).
- `weatherbot/interactive/commands/weather_views.py` — bare-arg render path;
  default marker (D-05).
- `weatherbot/weather/models.py` §302 — positional imperial/metric daily pairing
  (F11/F107 dt guard).

### Prior-phase carry-forward
- `.planning/phases/32-timezone-date-boundary-correctness/32-CONTEXT.md` —
  test-shaped-fix convention, cross-repo jurisdiction, audit-diagnosis-is-truth
  pattern this phase inherits.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The panel path already passes `location=` to `render_embed` via
  `_render_bridge` (v2.0) and shows the 📍 indicator — F27 fix reuses that exact
  call shape on the inbound path; the marker (D-05) rides the same header.
- `resolve_location(None)` (CLI default-location behavior) is the canonical
  default-resolution the app-side F02 fix reuses — do not re-derive it.
- `compute_uv`/forecast already compute per-bucket dt/local date — the dt-pairing
  guard (D-08) can lean on the same date anchoring Phase 32 unified in
  `weather/dates.py` rather than inventing new date math.

### Established Patterns
- **Off-loop fetch (D-10):** `dispatch_spec` fetches off the gateway loop; the
  F13 fix must NOT reintroduce a lock held across the fetch (D-03 rationale).
- **Failure-isolation envelope:** `on_message`/`View.on_error` swallow to a
  generic reply — the F02/F23 fixes must turn silent-swallow into correct
  behavior / visible recovery, not add more blanket catches.
- **Hub is weather-domain-free (v2.0 litmus + grimp gate):** the F02 fix must
  keep it that way (D-01).

### Integration Points
- `scheduler/wiring.py` `on_applied` is the reload→cache/channel seam (F17/F22).
- `interactive/dispatch.py` is the single dispatcher all three surfaces route
  through — the F02 fix must stay behavior-preserving for CLI + panel + inbound.

</code_context>

<specifics>
## Specific Ideas

- Render previews the user locked (D-05/06/07):
  - Bare `!weather` → `📍 Toronto (default)`; named → `📍 London`.
  - Out-of-today buckets → `Thu Jul 17` / `Fri Jul 18` / `Sat Jul 19`.
  - Timestamps → `checked 09:00` (was `2026-07-12T09:00:00+00:00`).

</specifics>

<deferred>
## Deferred Ideas

- F25 (bare `+`/`-` flag → generic error), F26 (flag-grammar footgun), F29
  (`next_cloudy` drops nocturnal cloudy hours), F78 (`!panel` trailing-text
  silent-drop), F162 (add/drop same-day) → **Phase 35 Cleanup Sweep**.
- F16 cached-timestamp staleness (cosmetic) — deferred unless trivial once the
  ISO→human formatter lands.
- F179 reconnect supervisor, F158 reconcile reject-hook — separate lifecycle
  findings, not this phase's UI buckets.
- Any HUB-rooted dispatcher change → upstream `yahir_reusable_bot`, human-gated.

</deferred>

---

*Phase: 33-Interactive & Panel Robustness*
*Context gathered: 2026-07-12*
