# Phase 6: Shared Lookup Core & Command Parser - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 6-Shared Lookup Core & Command Parser
**Areas discussed:** Parser contract, lookup_weather return shape, Unknown-location errors, send_now refactor risk

---

## Parser contract

### Q1 — Should parse_weather_command() validate the location, or detect-and-extract?

| Option | Description | Selected |
|--------|-------------|----------|
| Parse, don't validate | Parser answers "is this a weather command?" + extracts raw location string; config-check is lookup_weather's job. `weather faketown` → Command(faketown); `hello` → NotACommand. Preserves CMD-04 signal, parser config-free. | ✓ |
| Validating parser | Parser checks name against config, returns None for unknown names too. Collapses garbage and unknown-location into one None — loses CMD-04 signal. | |

**User's choice:** Parse, don't validate.

### Q2 — How to extract the location from command text (config names can have spaces)?

| Option | Description | Selected |
|--------|-------------|----------|
| Everything after keyword, trimmed, case-insensitive | `weather   New York ` → "New York". Supports multi-word configured names without quoting. | ✓ |
| First token only | `weather New York` → "New" (rest ignored). Single-word names only; "New York" unreachable. | |

**User's choice:** Everything after keyword, trimmed, case-insensitive.
**Notes:** Parser input is the full command text including the `weather` keyword (per ROADMAP); three-state result NotACommand | bare-default | Command(name).

---

## lookup_weather return shape

### Q3 — What should lookup_weather() return?

| Option | Description | Selected |
|--------|-------------|----------|
| Small result object | LookupResult bundling .text + .forecast + .location. P7 uses .text; P11 builds embed from .forecast without re-fetch. Mirrors send_briefing(text, forecast). | ✓ |
| Plain str | Briefing text only, matches ROADMAP wording. If P11 wants an embed it re-fetches/refactors later (YAGNI — embeds not a stated requirement). | |

**User's choice:** Small result object.

---

## Unknown-location errors

### Q4 — How should lookup_weather signal an unknown / unconfigured location?

| Option | Description | Selected |
|--------|-------------|----------|
| Typed UnknownLocationError (subclasses ValueError) | Carries requested name + valid configured names. P7/P11 each catch and format CMD-04 their own way. Subclassing ValueError keeps the v1.0 send_now path and tests green. | ✓ |
| Reuse plain ValueError | Least change; each surface must re-pull valid names from config and parse the message string. Weaker contract. | |
| In-band error variant on LookupResult | No exception; Result/Either style. Mixes success/failure into one shape; less idiomatic for this sync codebase. | |

**User's choice:** Typed UnknownLocationError (subclasses ValueError).

---

## send_now refactor risk

### Q5 — How should the shared core relate to the proven v1.0 send_now path?

| Option | Description | Selected |
|--------|-------------|----------|
| send_now delegates to lookup_weather | send_now calls lookup_weather() for fetch→render, then runs its existing send + persist tail on the LookupResult. One core, no duplicated logic, single source of truth. Only the read-only head changes; delivery/persist ordering untouched. Byte-identical guarded by criterion #4 + test_send_now.py. | ✓ |
| Shared low-level helper both call | Private _fetch_and_render() both call; send_now keeps its outer orchestration. Similar DRY, one extra indirection. | |
| Independent lookup_weather, send_now untouched | lookup_weather duplicates fetch→render; v1.0 path not modified. Max safety but two copies that can drift; not really "extracting out of send_now". | |

**User's choice:** send_now delegates to lookup_weather.

---

## Claude's Discretion

- Exact module/type names and placement of `LookupResult` + `UnknownLocationError` within `weatherbot/interactive/`.
- `lookup_weather`'s injectable test seams (mirror send_now's injectable client/settings/templates_dir).
- Whether `resolve_location` itself is upgraded to raise `UnknownLocationError` (via the ValueError subclass) or `lookup_weather` wraps it.
- Precise signatures of `lookup_weather` and `parse_weather_command`.

## Deferred Ideas

- Short-TTL fetch cache (CMD-06) — Phase 11 wraps lookup_weather; no caching seam in the P6 core.
- Discord embed formatting — Phase 11 consumes LookupResult.forecast; P6 only guarantees the seam.
- Geocoded / arbitrary-city lookup (CMD-V2-02) — out of v1.1; parser stays configured-locations-only.

## Process note

- `/gsd-discuss-phase 6` was initially blocked by `init.phase-op` reporting `phase_found: false`. Root cause: the multi-milestone `ROADMAP.md` placed the global `## Phase Details` section after the `### 📋 v2.0` heading, so the current-milestone slice (`extractCurrentMilestone`) cut off the `### Phase 6–11` blocks. Fixed by relocating `## Phase Details` ahead of the v2.0 subsection (commit `c3fddbb`). This also unblocks `/gsd-plan-phase` and `/gsd-execute-phase` for all v1.1 phases.
