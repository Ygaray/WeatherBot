# Roadmap: WeatherBot

## Milestones

- ✅ **v1.0 WeatherBot MVP** — Phases 1–5 (shipped 2026-06-15) — full details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- 🚧 **v1.1 Interactive & Live-Config** — Phases 6–11 (in progress)
- 📋 **v2.0** — channels (Telegram/SMS), arbitrary/geocoded lookup, weather-pattern analysis + history export, extra template fields, real-time severe-weather push (planned — define via `/gsd-new-milestone`)

## Phases

**Phase Numbering:**

- Integer phases (6, 7, 8…): Planned milestone work (v1.1 continues from v1.0's Phase 5)
- Decimal phases (e.g. 9.1): Urgent insertions (marked INSERTED)

<details>
<summary>✅ v1.0 WeatherBot MVP (Phases 1–5) — SHIPPED 2026-06-15</summary>

- [x] Phase 1: First Briefing End-to-End (4/4 plans) — completed 2026-06-09
- [x] Phase 2: Real Config — Locations, Content & Templates (5/5 plans) — completed 2026-06-10
- [x] Phase 3: Always-On Scheduler (5/5 plans) — completed 2026-06-11
- [x] Phase 4: Retry-then-Alert Reliability (4/4 plans) — completed 2026-06-11
- [x] Phase 5: Deployment & Reboot Survival (3/3 plans) — completed 2026-06-15

Full phase goals, plans, and details archived in [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md).

</details>

### 🚧 v1.1 Interactive & Live-Config (In Progress)

**Milestone Goal:** Make the running daemon responsive without a restart — answer on-demand `weather <location>` requests (CLI + Discord bot) and pick up config edits live (file-watch + explicit trigger), all without ever regressing v1.0's "the morning briefing always goes out, exactly once" guarantee.

- [x] **Phase 6: Shared Lookup Core & Command Parser** - Extract the read-only fetch→render core out of `send_now` and add the `weather <loc>` parser both surfaces share. (completed 2026-06-15)
- [ ] **Phase 7: CLI `weather [location]` One-Shot** - Standalone daemon-free CLI subcommand that prints a configured location's briefing and exits.
- [ ] **Phase 8: ConfigHolder & `fire_slot` Reads-From-Holder Refactor** - Atomic-swap config holder + the mandatory correctness fix so jobs render live config (prerequisite for any reload).
- [ ] **Phase 9: Reload Engine & Explicit Trigger** - `reload_config` (validate → atomic swap → job diff) via SIGHUP / `weatherbot reload`, plus `--check-config` dry-run; preserves exactly-once across reloads.
- [ ] **Phase 10: File-Watch Auto-Reload** - watchfiles directory-watch with debounce that funnels edits into the Phase 9 reload engine.
- [ ] **Phase 11: Discord Inbound Gateway Bot** - In-channel `weather <loc>` replies on an isolated thread/loop, short-TTL cache, loop guard, failure isolation, Discord reload confirmation.

## Phase Details

### Phase 6: Shared Lookup Core & Command Parser

**Goal**: One read-only fetch→render core (`interactive/lookup.py`) and one `weather <loc>` parser (`interactive/command.py`) exist and are unit-tested, so the CLI and the Discord bot can both call identical code with identical semantics.
**Depends on**: Nothing new (builds on shipped v1.0 `send_now`, client, renderer, store)
**Requirements**: (foundation — no v1.1 requirement closes here; underpins CMD-01..05 in Phase 7 and CMD-02/06/07 in Phase 11)
**Success Criteria** (what must be TRUE):

  1. A `lookup_weather(name, *, config, settings, …)` function resolves a configured location, fetches via the existing One Call client, renders via the existing v1 template, and returns briefing text — covered by unit tests against recorded payloads.
  2. `lookup_weather` writes NO sent-log, alert, or heartbeat rows (verified by test), so on-demand reads never pollute the scheduled `weather_onecall` time series or trip liveness logic.
  3. A single `parse_weather_command()` turns `weather`, `weather <loc>`, and unknown/garbage input into a stable result (location name | default | None), unit-tested independently of either surface.
  4. `send_now` still produces byte-identical scheduled briefings after the extraction (no regression in the v1.0 path; existing tests stay green).**Plans**: 3 plans

**Wave 1**

- [x] 06-01-PLAN.md — Pure three-state `weather <loc>` command parser (`interactive/command.py`) + matrix tests (criterion #3)
- [x] 06-02-PLAN.md — Read-only `lookup_weather` core + `LookupResult` + `UnknownLocationError`, `resolve_location` raise-upgrade + tests (criteria #1, #2)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 06-03-PLAN.md — `send_now` delegates to `lookup_weather` (byte-identical) + `interactive` package barrel (criterion #4)

### Phase 7: CLI `weather [location]` One-Shot

**Goal**: A user can run `weatherbot weather [location]` as a standalone command — no daemon required — and get the configured location's briefing (or a clear error) printed, reusing the v1 template.
**Depends on**: Phase 6
**Requirements**: CMD-01, CMD-03, CMD-04, CMD-05
**Success Criteria** (what must be TRUE):

  1. `weatherbot weather home` prints the briefing for the configured location `home` and exits 0, with NO running daemon (CMD-01).
  2. Bare `weatherbot weather` (no argument) returns the briefing for the designated default/primary configured location (CMD-03).
  3. `weatherbot weather <unknown>` prints a clear error that lists the valid configured location names and exits non-zero — no geocoding fallback (CMD-04).
  4. The printed briefing uses the exact v1 briefing template/format — no separate on-demand format exists (CMD-05).

**Plans**: TBD

### Phase 8: ConfigHolder & `fire_slot` Reads-From-Holder Refactor

**Goal**: The live config is owned by a lock-guarded `ConfigHolder` that hands out immutable snapshots, and `fire_slot` reads `holder.current()` instead of a captured `config` kwarg — the mandatory correctness prerequisite so a later reload actually changes what unchanged jobs render.
**Depends on**: Phase 6 (shares the `interactive`/holder seams); must land BEFORE any reload logic (Phase 9)
**Requirements**: (prerequisite refactor — no v1.1 requirement closes here; unblocks CFG-01/05 in Phase 9)
**Success Criteria** (what must be TRUE):

  1. A `ConfigHolder` exposes `current()` (snapshot read under a lock) and `swap(new_cfg)` (atomic rebind), unit-tested for concurrent read/swap safety.
  2. `fire_slot` reads `holder.current()` at the top of the job and uses that one snapshot for its entire fetch→render→persist lifecycle (per-job snapshot — Pitfall #9), proven by a test where the holder is swapped mid-job and the in-flight job still uses its original snapshot.
  3. With no reload yet wired, the scheduler daemon behaves identically to v1.0 (all 186 existing tests green; scheduled briefings unchanged).

**Plans**: TBD

### Phase 9: Reload Engine & Explicit Trigger

**Goal**: The running daemon applies edits to `config.toml` and template files to schedules, locations, units, and templates via an explicit trigger (SIGHUP / `weatherbot reload`) — validate → atomic all-or-nothing swap → diff-and-re-register jobs — keeping the old config on any failure and preserving v1.0's exactly-once delivery across the reload. Also ships `--check-config` dry-run.
**Depends on**: Phase 8 (requires ConfigHolder + holder-reading `fire_slot`)
**Requirements**: CFG-01, CFG-02, CFG-04, CFG-05, CFG-06, CFG-08
**Success Criteria** (what must be TRUE):

  1. After editing `config.toml` (schedule/location/units) or a template file and triggering reload via SIGHUP or `weatherbot reload`, the running daemon applies the change without a restart and a new send-time fires on its new schedule (CFG-01, CFG-02).
  2. An invalid edit (bad TOML, duplicate names, unknown template token) is rejected: the daemon logs the validation reason and keeps running on the previous valid config — never a half-applied or torn live state, even if job re-registration fails midway (CFG-04, CFG-06; Pitfalls #6 all-or-nothing apply).
  3. Reload reconciles scheduler jobs by stable `(location, send_time, days)` id — adds new, removes deleted/disabled, leaves unchanged slots untouched; reloading the identical config produces zero job changes and no duplicate fires (CFG-05; Pitfall #7).
  4. **Exactly-once is preserved across a reload:** changing a slot's location name, IANA timezone, or send_time for a slot already delivered today does NOT cause a duplicate or skipped briefing for that morning — verified by an explicit test of a tz/name change on an already-sent slot (CFG-05; Pitfall #8, HIGHEST RISK).
  5. `weatherbot --check-config` loads and fully validates a config edit (parse + unique names + template tokens) and reports pass/fail without applying or sending anything (CFG-08).

**Plans**: TBD
**Research flag**: PITFALLS.md flags this phase as a deeper-research candidate — the exactly-once idempotency-key interaction (Pitfall #8) is the failure most likely to silently break a shipped guarantee. Consider `/gsd-plan-phase --research-phase 9` to nail the policy for tz/name/send_time changes on an already-sent slot, the stable-location-id key change, and the two-phase apply/rollback. (Secrets/`.env` are out of reload scope — restart boundary, Pitfall #12; reload does not touch the systemd ready gate, Pitfall #13.)

### Phase 10: File-Watch Auto-Reload

**Goal**: The daemon auto-detects saves to the config/template files and reloads automatically, debounced to absorb editor save-storms and partial writes — a thin convenience layer over the trusted Phase 9 reload engine.
**Depends on**: Phase 9 (funnels into the same `reload_config`)
**Requirements**: CFG-03
**Success Criteria** (what must be TRUE):

  1. Saving an edit to `config.toml` (or a watched template) triggers an automatic reload with no manual trigger, and the change takes effect (CFG-03).
  2. A multi-event / truncate-then-write / temp-then-rename editor save produces exactly ONE reload and never parses a half-written file (debounce + directory-watch; Pitfall #5).
  3. The watcher is a single long-lived observer that shuts down cleanly on SIGTERM and keeps file-descriptor count stable over a long-uptime soak (no inotify leak / reload loop; Pitfall #11).
  4. A failed auto-reload (bad edit on save) follows the Phase 9 keep-old-config-on-failure path — the live daemon keeps running on the previous config.

**Plans**: TBD

### Phase 11: Discord Inbound Gateway Bot

**Goal**: A user can type `weather <location>` in the Discord channel and get the briefing as an in-channel reply, served by an isolated gateway bot whose failures can never stop a scheduled briefing; the bot also posts each reload outcome to Discord.
**Depends on**: Phase 6 (shared lookup), Phase 8 (reads live config via the holder); built LAST on proven foundations
**Requirements**: CMD-02, CMD-06, CMD-07, CMD-08, CFG-07
**Success Criteria** (what must be TRUE):

  1. Typing `weather home` in the Discord channel returns the briefing as an in-channel reply, and an unknown location returns the configured-names error (CMD-02), with all blocking fetch/SQLite work run off the event loop via `asyncio.to_thread` (no "Heartbeat blocked"; Pitfall #1).
  2. Repeated requests for the same location within a short TTL serve from a cached fetch instead of calling OpenWeather again (CMD-06; quota guard, Pitfall #10).
  3. The bot responds only to explicit `weather` commands and never to its own replies or to the outbound briefing webhook's posts — verified by feeding a simulated webhook-authored message and asserting no command fires (CMD-07; `author.bot` guard, Pitfall #2).
  4. A bot/gateway failure (revoked token, disconnect, handler exception) never prevents a scheduled briefing from firing — verified by revoking the token and confirming the next scheduled briefing still sends; bot health does NOT flip the systemd ready gate (CMD-08; Pitfalls #3, #4).
  5. Each reload outcome (applied summary / rejection reason) is also posted to Discord so the operator need not tail logs (CFG-07).

**Plans**: TBD
**UI hint**: no
**Research flag**: PITFALLS.md flags this phase as a deeper-research candidate — the asyncio-loop-in-a-thread coexistence with the sync `BackgroundScheduler` and the `client.start()` lifecycle/shutdown wiring are the highest-blast-radius integration mechanics (Pitfalls #1, #4). Consider `/gsd-plan-phase --research-phase 11` for thread lifecycle + failure isolation + the prefix-vs-slash command-type decision (message_content intent). The bot token is a NEW secret in git-ignored `.env` (Pitfall #3); the outbound webhook stays the briefing path (do not reuse it for replies).

### 📋 v2.0 (Planned)

To be defined via `/gsd-new-milestone`. Candidate goals (see PROJECT.md → Requirements → Future candidates):
Telegram + SMS channels (CHAN-V2-01/02), arbitrary/geocoded `weather <any city>` lookup (CMD-V2-02), weather-pattern analysis + history/CSV export over the v1 SQLite store (ANLY-V2-01/02), extra template fields (ENH-V2-02), real-time severe-weather push alerts (ENH-V2-03).

## Progress

**Execution Order:**
Phases execute in numeric order: 6 → 7 → 8 → 9 → 10 → 11

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. First Briefing End-to-End | v1.0 | 4/4 | ✅ Complete | 2026-06-09 |
| 2. Real Config — Locations, Content & Templates | v1.0 | 5/5 | ✅ Complete | 2026-06-10 |
| 3. Always-On Scheduler | v1.0 | 5/5 | ✅ Complete | 2026-06-11 |
| 4. Retry-then-Alert Reliability | v1.0 | 4/4 | ✅ Complete | 2026-06-11 |
| 5. Deployment & Reboot Survival | v1.0 | 3/3 | ✅ Complete | 2026-06-15 |
| 6. Shared Lookup Core & Command Parser | v1.1 | 3/3 | Complete    | 2026-06-15 |
| 7. CLI `weather [location]` One-Shot | v1.1 | 0/TBD | Not started | - |
| 8. ConfigHolder & `fire_slot` Refactor | v1.1 | 0/TBD | Not started | - |
| 9. Reload Engine & Explicit Trigger | v1.1 | 0/TBD | Not started | - |
| 10. File-Watch Auto-Reload | v1.1 | 0/TBD | Not started | - |
| 11. Discord Inbound Gateway Bot | v1.1 | 0/TBD | Not started | - |
