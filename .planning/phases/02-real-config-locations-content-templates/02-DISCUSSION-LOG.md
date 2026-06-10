# Phase 2: Real Config — Locations, Content & Templates - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 2-Real Config — Locations, Content & Templates
**Areas discussed:** Severe-weather source, Hint rules & feels-like, Geocoding setup UX, --check & template validation

---

## Severe-weather source

### Q1 — Where should the severe-weather alert data (FCST-06) come from?

| Option | Description | Selected |
|--------|-------------|----------|
| NWS free API (US) | api.weather.gov alerts, free/no-card, but US-only | |
| Graceful-absent stub | Wire `{alert}` but populate from nothing in v1 | |
| One Call 3.0 (card) | OpenWeather One Call 3.0 alerts[], global, requires card on file | ✓ |

**User's choice:** One Call 3.0. The user already has a card on file ("no friction") and noted prior experience with 3.0, asking whether its free quota applied.
**Notes:** Clarified that One Call 3.0 has a 1k/day free allotment but requires a card on file (free-if-capped); uses the same `OPENWEATHER_API_KEY` once the "One Call by Call" subscription is active — no separate key.

### Q2 — How should One Call 3.0 fit into the existing pipeline?

| Option | Description | Selected |
|--------|-------------|----------|
| Add 3.0 for alerts only | Keep tested 2.5 current+forecast+aggregation; add one 3.0 call for alerts[] | |
| Migrate fully to 3.0 | Replace 2.5 + bucket aggregation with a single 3.0 fetch | ✓ |

**User's choice:** Migrate fully. The user first asked "does 2.5 output something 3.0 does not."
**Notes:** Confirmed 3.0 is a functional superset for this bot (current+feels_like+uvi, ready-made `daily[0]` high/low/pop, IANA timezone string, alerts[]); the only thing 2.5 returns that 3.0 doesn't is reverse-geocoded place name, which we configure ourselves. Dual-unit still needs two systems either way. Decision supersedes the locked free-2.5/no-card decision; retires `aggregate.py` + tests and reshapes persistence.

---

## Hint rules & feels-like

### Q1 — Which actionable hints should v1 compute?

| Option | Description | Selected |
|--------|-------------|----------|
| Umbrella (rain) | rain > 40% → umbrella | ✓ |
| Coat / cold | feels-like below cold threshold | ✓ |
| Heat warning | feels-like above hot threshold | ✓ |
| Wind advisory | wind above threshold | ✓ |

**User's choice:** All four, plus a user-added **sunscreen** hint above a "dangerous" UV index, skipped if the day stays below the threshold.
**Notes:** Sunscreen is a natural fit because One Call 3.0 provides `uvi`, and `daily[0].uvi` (day max) makes "skip if below threshold all day" automatic.

### Q2 — How should multiple applicable hints fill the single {hint} placeholder?

| Option | Description | Selected |
|--------|-------------|----------|
| One per line | Each hint on its own line; empty collapses | ✓ |
| Inline, separated | All hints on one line with a separator | |
| Top one only | Single highest-priority hint by severity | |

**User's choice:** One per line; empty when none apply.

### Q3 — How should feels-like appear?

| Option | Description | Selected |
|--------|-------------|----------|
| Own {feels_like} | New imperial+metric placeholder like {temp} | ✓ |
| Fold into {temp} | {temp} shows 'actual (feels X)' | |
| Hints only | Not shown; only drives hint thresholds | |

**User's choice:** Its own `{feels_like}` placeholder.

### Q4 — Where should hint thresholds live?

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded defaults | Baked into code | ✓ |
| Configurable | Exposed in config.toml | |

**User's choice:** Hardcoded defaults.

### Q5 — What UV index should trigger the sunscreen hint?

| Option | Description | Selected |
|--------|-------------|----------|
| UV >= 6 (High) | WHO 'High' band | ✓ |
| UV >= 8 (Very High) | Only strong days | |
| UV >= 3 (Moderate) | More cautious | |

**User's choice:** UV >= 6 (High).

---

## Geocoding setup UX

### Q1 — How should city-name → lat/lon resolution work at setup time (LOC-03)?

| Option | Description | Selected |
|--------|-------------|----------|
| `--geocode` helper | Command prints lat/lon to paste; config stores only coords | ✓ |
| Auto-resolve + cache | Config accepts a city name, resolved+cached on first run | |
| Manual only | User enters lat/lon by hand; no geocoding code | |

**User's choice:** `--geocode "City"` helper that prints coordinates to paste into config.

---

## --check & template validation

### Q1 — What should `--check` validate?

| Option | Description | Selected |
|--------|-------------|----------|
| Config schema & types | TOML/types/IANA-tz/units valid (CONF-03) | ✓ |
| Template placeholders | Unknown/typo'd {token} reported (TMPL-02) | ✓ |
| Live API reachability | One lightweight 3.0 call confirms key+subscription | ✓ |
| Locations resolve | Well-formed + names unique | ✓ |

**User's choice:** All four.

### Q2 — When should template validation fire?

| Option | Description | Selected |
|--------|-------------|----------|
| Load + --check | Validate on every load incl. --send-now; abort send on typo | ✓ |
| Only --check | Lenient --send-now keeps Phase 1's visible-token behavior | |

**User's choice:** Load + --check — a typo'd template aborts the send loudly, never renders blank.

---

## Claude's Discretion

- Exact hint wording/emoji and the `{alert}` summary phrasing.
- Dual-unit fetch strategy for One Call 3.0 (two calls vs fetch-one-convert-other).
- One Call 3.0 → normalized-field mapping, persistence schema migration specifics, module layout.
- Displayed-value rounding/precision (carry Phase 1's whole-degree convention).
- Whether `--geocode` accepts a `--limit`/country hint for ambiguous names.

## Deferred Ideas

- Configurable hint thresholds (chose hardcoded for v1).
- Real-time / push severe-weather monitoring (v2 ENH-V2-03; the `{alert}` line here is passive).
- Auto-resolve + cache geocoding (rejected in favor of the explicit helper).
- Extra template fields like sunrise/sunset (v2 ENH-V2-02, even though 3.0 now returns them).
- Richer startup self-check distinguishing key-not-active vs auth error (Phase 5 OPS-02).
