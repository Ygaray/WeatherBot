# Phase 6: Shared Lookup Core & Command Parser - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the read-only foundation that the Phase 7 CLI and the Phase 11 Discord bot will both stand on — and nothing user-facing ships here:

1. A read-only **fetch→render core** in `interactive/lookup.py` — `lookup_weather(name, *, config, settings, …)` resolves a configured location, fetches via the existing v1 One Call client, renders via the existing v1 template, and returns the briefing. Writes **nothing** to the store.
2. A single **command parser** in `interactive/command.py` — `parse_weather_command()` turns `weather` / `weather <loc>` / garbage into a stable result, unit-tested independently of any surface.
3. The v1.0 `send_now` path stays **byte-identical** after the extraction (criterion #4).

**Out of scope (own phases):** the CLI subcommand itself (P7), the Discord bot (P11), short-TTL caching (P11/CMD-06), config hot-reload (P8–10), embed formatting (P11). This phase only guarantees the seams those phases plug into exist.
</domain>

<decisions>
## Implementation Decisions

### Command parser (`interactive/command.py`)
- **D-01: Parse, don't validate.** `parse_weather_command()` decides only "is this a `weather` command?" and extracts the raw location string. It does **not** check the name against configured locations — that is `lookup_weather`'s job. This preserves a distinct downstream signal for "unknown location" (needed for CMD-04 in P7/P11) and keeps the parser config-free and trivially unit-testable.
- **D-02: Three-state result.** Outcomes are `NotACommand` (input isn't a weather command → Discord bot ignores it) | bare-command "use default location" (e.g. `Command(location=None)`) | `Command(location="<raw name>")`. The exact type name/shape is the planner's call; the three states are the contract.
- **D-03: Input is the full command text** including the `weather` keyword (per ROADMAP: inputs are `weather`, `weather <loc>`, garbage). Both surfaces feed raw text and get identical semantics.
- **D-04: Location extraction = everything after the `weather` keyword, trimmed; matched case-insensitively.** So `weather   New York ` → location `"New York"`. Multi-word configured names work without quoting (config names may contain spaces). No first-token-only truncation.

### Read-only core (`interactive/lookup.py`)
- **D-05: `lookup_weather` returns a small `LookupResult` object** bundling `.text` (the rendered v1 briefing string), `.forecast` (the structured `Forecast`), and `.location` (the resolved `Location`). P7's CLI uses `.text`; P11's Discord surface can build a richer embed reply from `.forecast` **without re-fetching**. Mirrors the existing outbound `channel.send_briefing(text, forecast)` pairing. (Chosen over returning a bare `str` to leave a clean P11 seam at near-zero cost.)
- **D-06: Read-only is absolute.** `lookup_weather` writes **none** of: `weather_onecall` (`persist`), `sent_log` (`claim_slot`), `alerts` (`record_alert`/`resolve_alert`), `heartbeat` (`stamp_tick`/`stamp_success`), `health` (`stamp_health`). Enforced by test (criterion #2). It otherwise reuses v1 behavior exactly: dual imperial+metric fetch, `units` override leads display, exact v1 template (FCST-04 / CR-01 / CMD-05).

### Unknown-location error contract
- **D-07: `lookup_weather` raises a typed `UnknownLocationError` that subclasses `ValueError`**, carrying the requested name + the list of valid configured location names. P7 (stderr + non-zero exit) and P11 (channel message) each catch it and format CMD-04 their own way; the valid-names list travels with the error so neither surface re-derives it. Subclassing `ValueError` keeps the existing `resolve_location`/`send_now` behavior and tests green (no behavior change for the v1.0 path).

### `send_now` refactor strategy
- **D-08: `send_now` delegates to `lookup_weather()`.** `send_now` calls the new read-only core for fetch→render, then runs its **existing** send + persist tail on the returned `LookupResult` (`.forecast`, `.text`). One read-only core, zero duplicated fetch/render logic, single source of truth. Only the read-only *head* of `send_now` changes; the delivery + `persist` ordering that underpins exactly-once is **not** touched. Byte-identical output is the acceptance bar — guarded by criterion #4 and the existing `tests/test_send_now.py`.

### Claude's Discretion (planner/researcher decide)
- Exact module/type names and where `LookupResult` + `UnknownLocationError` live within `weatherbot/interactive/`.
- `lookup_weather`'s injectable seams for tests — mirror `send_now`'s injectable `client`/`settings`/`templates_dir` so unit tests run against recorded payloads (criterion #1).
- Whether `resolve_location` itself is upgraded to raise `UnknownLocationError` (backward-compatible via the `ValueError` subclass) or `lookup_weather` wraps it.
- Precise signature/keyword args of `lookup_weather` and `parse_weather_command`.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 6: Shared Lookup Core & Command Parser" — goal + the 4 success criteria this phase is judged against.
- `.planning/REQUIREMENTS.md` — CMD-04 (unknown-location error lists valid names, no geocoding), CMD-05 (reuse exact v1 template), plus the "read-only w.r.t. the scheduled series" out-of-scope note. Phase 6 is a foundation phase (closes no requirement) but underpins CMD-01..05 and CMD-02/06/07.
- `.planning/research/PITFALLS.md` — project pitfalls log; relevant here: on-demand reads must not pollute the scheduled `weather_onecall` time series or trip liveness logic (criterion #2).

### v1.0 code seams the extraction reuses (paths verified during scout)
- `weatherbot/cli.py` — `send_now()` (~L90–185, the path being refactored), `resolve_location()` (~L40), `run_send_now()` / CLI dispatch (`main()` ~L402+).
- `weatherbot/weather/client.py` — `fetch_onecall(loc, key, units)` (~L42); One Call 3.0 client reused as-is.
- `templates/renderer.py` — `render(template_text, values)` (~L75), `validate_template()`, canonical placeholder set.
- `weatherbot/weather/store.py` — the write methods `lookup_weather` must NOT call: `persist`, `claim_slot`, `record_alert`, `resolve_alert`, `stamp_tick`, `stamp_success`, `stamp_health`.
- `weatherbot/config/models.py` — `Location` (`name`, `lat`, `lon`, `timezone`, `units`, `schedule`) and `Config` (`locations`, `template`, …); first location = implicit default (D-07 in v1.0).
- `weatherbot/weather/models.py` — `Forecast.from_payloads(...)`, `.placeholders()`.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `resolve_location(config, name|None)` — already does case-insensitive match and `None → config.locations[0]`; reuse verbatim (raises on no match — see D-07 about upgrading to `UnknownLocationError`).
- `fetch_onecall` + `Forecast.from_payloads` + `render` — the exact fetch→render chain `send_now` runs today; this *is* the read-only core to extract.
- Recorded OpenWeather fixtures in `tests/fixtures/` (`onecall_imperial_clear.json`, `onecall_metric_clear.json`, etc.) — deterministic test inputs for the new core (criterion #1).

### Established Patterns
- `send_now` already takes injectable `client` / `settings` / `channel` / `templates_dir` — the new core should follow the same injectable style for offline tests.
- v1 renders plain text via a regex `{token}` substitution (no `str.format`/`eval`); the on-demand path reuses this untouched (CMD-05).
- The dual-unit fetch (imperial+metric in one round) is a v1 contract (DATA-03/FCST-04) — the core fetches both, exactly like `send_now`.

### Integration Points
- New package `weatherbot/interactive/` (does **not** exist yet) holding `lookup.py` and `command.py`.
- `send_now` (`weatherbot/cli.py`) becomes the first consumer of `lookup_weather` (D-08); its send+persist tail stays.
- Future consumers: P7 CLI subcommand and P11 Discord bot both call `lookup_weather` + `parse_weather_command`.
</code_context>

<specifics>
## Specific Ideas

- The "byte-identical" bar for `send_now` (criterion #4) is concrete: `tests/test_send_now.py` and the renderer/store tests must stay green after the refactor; the rendered briefing text for a given fixture must not change.
- Parser test matrix should cover at minimum: `weather`, `weather home`, `weather New York` (spaced), `weather   home  ` (whitespace), mixed case (`Weather HOME`), and non-commands (`hello`, empty string) → `NotACommand`.
</specifics>

<deferred>
## Deferred Ideas

- **Short-TTL fetch cache (CMD-06)** — belongs to Phase 11; that phase wraps `lookup_weather` with caching. No caching seam is baked into the Phase 6 core.
- **Discord embed formatting** — Phase 11 consumes `LookupResult.forecast`; Phase 6 only guarantees the structured forecast is available on the return, not any embed rendering.
- **Geocoded / arbitrary-city lookup (CMD-V2-02)** — explicitly out of v1.1; the parser stays configured-locations-only (raw name passed through, validated against config by `lookup_weather`).

None of these were folded into Phase 6 scope.
</deferred>

---

*Phase: 6-Shared Lookup Core & Command Parser*
*Context gathered: 2026-06-15*
