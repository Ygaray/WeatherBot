# Phase 17: Minimal Persistent Panel (Core Wiring) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-23
**Phase:** 17-minimal-persistent-panel-core-wiring
**Areas discussed:** Default & held location, Button set & layout, Non-operator reject UX, Slow-fetch feedback
**Mode:** advisor (standard calibration tier; technical owner — no product-outcome reframing). One `gsd-advisor-researcher` agent per area produced the comparison tables below.

---

## Default & held location

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory attribute on the single View instance | Set from `select.values[0]` in dropdown callback, read in button callbacks; default in `__init__` | ✓ (locked) |
| Re-read the Select's `values` in each button callback | No state to hold — but button interactions don't carry select `values`; bug #7284 makes `default=True` report empty until changed → functionally broken | |
| Encode selection in `custom_id` | Selection rides with the component — but breaks the static-`custom_id` persistent-view contract; fragile | |

**User's choice:** Mechanism locked to the in-memory attribute (the alternatives are broken/fragile per discord.py reality — presented as locked-with-rationale, user did not object). Default-on-load = `config.locations[0].name` (mirrors `resolve_location(config, None)`); argless buttons pass `arg=None`.
**Notes:** Restart amnesia is the only gap and is the agreed Phase-18 boundary.

---

## Button set & layout

| Option | Description | Selected |
|--------|-------------|----------|
| Curated name tuple | Explicit ordered tuple of 7 names, resolved via `BY_NAME` + build-time assert; reviewable order, no leak risk | ✓ |
| Derive from registry + eligibility predicate | Iterate `COMMANDS` with a predicate; max PANEL-10 purity but the predicate is curation and risks a future spec leaking a button | |

**Plus sub-decision — the "weather" button (no `weather` CommandSpec exists):**

| Option | Description | Selected |
|--------|-------------|----------|
| W1 — reuse existing path | Weather button calls `cache.lookup` → `build_inbound_embed` directly; no registry change (pure-UI charter) | |
| W2 — add a real `weather` spec | Add `CommandSpec("weather",...)` wrapping `lookup_weather` into a `CommandReply`; every button routes uniformly through `dispatch_spec` | ✓ |

**User's choice:** Curated tuple + W2.
**Notes:** W2 was flagged as NOT purely additive — it makes `weather` appear in `!help` + the CLI and reroutes the existing `!weather` text path through `dispatch_spec`/`render_embed`. The user accepted this for the sake of uniform routing; captured as the hard byte-identical-reply constraint D-08. Layout: row 0 dropdown, row 1 `weather·uv·next-cloudy·sun·wind`, row 2 `status·alerts`; help/locations/forecast excluded; minimal build-time layout assertion added now.

---

## Non-operator reject UX

| Option | Description | Selected |
|--------|-------------|----------|
| Ephemeral leak-free reply | `send_message(ephemeral=True)` + `return False`; acks (no "interaction failed" toast), can't clobber the shared panel, generic wording | ✓ |
| Silent swallow | `return False`, no ack; mirrors `on_message` — but foreign user gets a confusing client-side "This interaction failed" toast, no audit hook | |

**User's choice:** Ephemeral leak-free reply.
**Notes:** Generic identity-free wording ("This panel is in use by someone else."); rejected attempt logged server-side. `View.on_error` doesn't fire on a clean `return False`, so the log line is the sole audit record.

---

## Slow-fetch feedback

| Option | Description | Selected |
|--------|-------------|----------|
| Transient in-place edit + disable | `edit_message("⏳ Fetching…", view=disabled)` before fetch → `edit_original_response(result)` after; visible cue, in-place, double-tap-proof | ✓ |
| Disable-only | `edit_message(view=disabled)` then result edit; anti-double-tap + subtle cue, no transient text | |
| Silent defer | `defer()` then `edit_original_response`; simplest but inert on cold cache, re-tap risk | |
| `defer(thinking=True)` + ephemeral followup | Native spinner — but forces a separate ephemeral followup, splitting rendering across two surfaces (rejected) | |

**User's choice:** Transient in-place edit + disable.
**Notes:** Component `defer()` is `DEFERRED_UPDATE_MESSAGE` (no spinner), unlike `on_message`'s `typing()` — hence the explicit transient cue. The single `interaction.response.*` call is spent on `edit_message`; result lands via `edit_original_response`. Disable-only is the documented lighter fallback.

---

## Claude's Discretion

- Attribute/method names, disabled-view construction helper, new `panel.py` module location/style.
- Where the new `weather` handler lives (`commands/weather_views.py` vs own module).
- Exact plain-text button labels (emoji is Phase 20).

## Deferred Ideas

- Restart persistence of `message_id` / selected location — Phase 18.
- Forecast button + two-tier sub-options — Phase 19 (rows 3–4 reserved).
- Selected-location visual indicator, emoji labels, "updated <time>" stamp — Phase 20.
- Briefing failure-isolation re-proof (PANEL-11) — Phase 20 (seam starts here).
- Full component-layout build-time assertion — Phase 19.
- Grey-out buttons until a location is selected (PANEL-V2-01) — future release.
