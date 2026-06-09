# Phase 1: First Briefing End-to-End - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 1 proves the entire pipeline in one vertical slice: a single correct, correctly-located weather briefing is **fetched** from OpenWeather (free 2.5 endpoints + 3-hour bucket aggregation), **persisted** to a local SQLite store, **rendered** from an editable plain-text template (imperial-primary with metric in parentheses), and **delivered** to Discord on demand via `--send-now`. Secrets load from `.env`; delivery sits behind a plain-text-first `Channel.send(text)` interface with Discord as the one implementation.

Requirements covered: FCST-01, FCST-02, FCST-03, FCST-04, DATA-01, DATA-02, DATA-03, DELV-01, DELV-02, DELV-03, CONF-02, CONF-04.

**Explicitly NOT this phase** (later phases): multiple locations / geocoding / per-location units (Phase 2), actionable hints + severe-weather line + placeholder-validation (Phase 2), scheduling (Phase 3), retry/alert/heartbeat (Phase 4), deployment/supervision (Phase 5), weather-pattern analysis itself (v2).
</domain>

<decisions>
## Implementation Decisions

### Templating subsystem (foundation established here; deepened in Phase 2)
- **D-01:** Templates live in a dedicated top-level **`templates/`** directory as plain-text **`.txt`** files using simple **`{placeholder}`** substitution (e.g. `{temp}`, `{high}`, `{low}`, `{rain}`, `{wind}`, `{humidity}`, `{conditions}`, `{location}`, `{date}`). Editable from day one — rendering reads from files, never hardcoded strings.
- **D-02:** Flat naming convention **`{type}-{style}.txt`** so it scales to type × style (× platform later) without nesting churn.
- **D-03:** Author a **starter set of three daily-briefing layouts**, all editable:
  - `briefing-sectioned.txt` — **DEFAULT**. Header line + grouped sections, light emoji (e.g. `☀️ WEATHER — {location}` / date / sections).
  - `briefing-multiline.txt` — one labeled field per line with a light header.
  - `briefing-compact.txt` — dense one/two-liner, **plain (no emoji)**, sized for character-constrained channels (the SMS-safe variant seam).
- **D-04:** This pulls the *template-directory + file-based editable rendering* seam into Phase 1. Phase 2's TMPL-01/TMPL-02 then formalize the editable-template contract (canonical placeholder set, missing-field-fails-loudly validation) and add the richer content fields (hints, severe-weather). Planner: build Phase 1's renderer so Phase 2 extends it, not replaces it.

### Location configuration
- **D-05:** Phase 1 locations are specified by **raw `lat`/`lon` + a display `name`** in config. No geocoding code in Phase 1 — city-name → coordinates resolution is Phase 2 (LOC-03).
- **D-06:** Config is a **list of locations** even in Phase 1 (one entry for now) — a clean seam into Phase 2 multi-location, no later refactor.
- **D-07:** `--send-now` takes an **optional** location argument: bare `--send-now` sends the default/first location; `--send-now <name>` targets a specific one.

### Persistence & analysis-ready schema (DATA-01/02/03)
- **D-08:** Store **one row per API fetch** (not daily roll-ups), each with: location, fetch timestamp (**UTC + local**), the **raw JSON payload**, and **normalized fields**. Maximum future flexibility, intraday resolution.
- **D-09:** Persist **both current conditions AND the forecast buckets** (the briefing already fetches both). Forecast rows must retain their **target/valid timestamp** so later "actuals" can be joined for forecast-accuracy analysis.
- **D-10:** The schema is designed up front (DATA-02) to support **four analysis axes**: (1) temperature trends, (2) rain/precipitation frequency, (3) wind & humidity patterns, (4) **forecast-vs-actual accuracy**. Forecast-accuracy is the most demanding (predicted-keyed-by-target-time + later actuals join) and is the primary schema-shaping constraint. **Research-worthy** — see canonical refs; the researcher should design the table layout to avoid a v2 migration. Analysis features themselves remain v2.
- **D-11:** Persistence **reuses the briefing's existing fetch** — no extra OpenWeather calls solely to store data (DATA-03).

### Discord delivery & styling
- **D-12:** The rendered **plain-text template is the canonical message body** passed through `Channel.send(text)` — the exact text SMS/Telegram will reuse later. Keep this path channel-agnostic.
- **D-13:** Additionally render a **basic Discord embed** (Discord-only enrichment) from the same forecast data. The embed is an implementation detail of the Discord channel and must NOT leak into the channel interface or the canonical text path (DELV-03).
- **D-14:** The webhook posts with a **custom identity**: username like `WeatherBot ☀️` plus a **configurable avatar URL** (webhook supports both for free).

### Claude's Discretion
- Exact wording/spacing inside the three starter templates (sensible defaults; user will edit).
- Internal module/package layout, library wiring, and SQLite table/column specifics — defer to research + planner (grounded by the research docs in canonical refs).
- Rounding/precision of displayed values (e.g. whole-degree temps) — pick a sensible default.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 1: First Briefing End-to-End" — goal, mode (mvp), success criteria
- `.planning/REQUIREMENTS.md` — FCST-01..04, DATA-01..03, DELV-01..03, CONF-02, CONF-04 (and the v2/out-of-scope boundaries this phase must not cross)
- `.planning/PROJECT.md` — core value, locked project decisions (imperial(metric), Discord-first, secrets-from-env, channel abstraction, SQLite-from-v1)

### Research (technical grounding — prescriptive)
- `.planning/research/STACK.md` — Python/uv stack, **OpenWeather free 2.5 endpoints decision** (no credit card), httpx, Jinja2/templating, discord-webhook, pydantic config + `.env` secrets
- `.planning/research/ARCHITECTURE.md` — scheduler→fetch→render→dispatch boundaries, the **`Channel.send(text)` contract** (plain text in, `DeliveryResult` out), data-layer/cache shape, build order
- `.planning/research/PITFALLS.md` — OpenWeather 2.5/3.0 + quota + key-activation gotchas, **bucket-aggregation day-boundary/timezone edges**, secrets-handling, template-formatting pitfalls
- `.planning/research/FEATURES.md` — table-stakes vs anti-features (e.g. avoid a full template *engine*; plain-text-first)
- `.planning/research/SUMMARY.md` — synthesis; flags **3-hour-bucket → daily high/low/rain aggregation** as the trickiest unit-testable piece (recorded JSON fixtures should drive its tests)

No external ADRs/specs beyond the planning docs above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — greenfield repository. No source code exists yet (only `.planning/`, `CLAUDE.md`, gitignored `API-key.md`/`.env`).

### Established Patterns
- None yet. Phase 1 establishes the foundational patterns (config/secrets loading, the `Channel` interface, the `templates/` directory, the SQLite data layer) that every later phase builds on.

### Integration Points
- `.env` provides `OPENWEATHER_API_KEY` and the Discord webhook URL (gitignored).
- `templates/` directory is the rendering source.
- SQLite database file is the persistence sink (location TBD by planner; should be gitignored or in a data dir).
</code_context>

<specifics>
## Specific Ideas

- Default briefing reads like a morning glance: header (`☀️ WEATHER — {location}` + date), then current conditions, high/low, and a rain/wind/humidity line — see `briefing-sectioned.txt`.
- The `compact` template is intentionally the SMS-safe / character-constrained variant, authored plain (no emoji) — it is the seam for v2 SMS/Telegram even though those channels aren't built here.
- "WeatherBot ☀️" is the desired webhook display identity.
</specifics>

<deferred>
## Deferred Ideas

- **Weekly-briefing message type** — a NEW capability (not in v1 requirements at all). Note for the roadmap backlog; do not build in Phase 1.
- **Alert message templates** — failure/missed-briefing alerts belong to Phase 4 (RELY-03/04); the passive severe-weather line belongs to Phase 2 (FCST-06). The `templates/` naming convention (`alert-{style}.txt`) is ready for them.
- **SMS / Telegram channel-specific templates & delivery** — v2 (CHAN-V2-01/02). The plain-text-first canonical body + `compact` template already lay the seam.
- **Per-platform template selection / character-budget enforcement** — v2 concern once multiple channels exist.
- **On-demand `weather <location>` command interface** — v2 (CMD-V2-01).
- **Weather-pattern analysis / query / export** — v2 (ANLY-V2-01/02); Phase 1 only *stores* the data the analysis will later read.

### None of the above were folded into Phase 1 scope — captured so they're not lost.
</deferred>

---

*Phase: 1-First Briefing End-to-End*
*Context gathered: 2026-06-09*
