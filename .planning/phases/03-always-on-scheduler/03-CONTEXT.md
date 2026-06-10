# Phase 3: Always-On Scheduler - Context

**Gathered:** 2026-06-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 turns the manual `--send-now` pipeline into an **always-on daemon** that fires
each location's briefings automatically at the location's local wall-clock time. It
delivers per-location schedules (multiple send-times/day), per-send day-of-week
selection and on/off toggles, DST-safe firing, missed-send recovery within a grace
window, and idempotency so a slot is never sent twice (no restart replay, no DST
double-fire). It also adds **send-time / weather-check / late-send annotations** to the
briefing so a recovered late send is transparent about timing.

Requirements covered: SCHD-01, SCHD-02, SCHD-03, SCHD-04, SCHD-05, SCHD-06, SCHD-07.

**Explicitly NOT this phase** (later phases): retry-then-alert reliability, the
independent alert path, heartbeat/liveness (Phase 4); process supervision, reboot
survival, the startup self-check / "online" signal (Phase 5); weather-pattern analysis
(v2); SMS/Telegram channels (v2). The daemon here runs in the **foreground** — making it
survive reboots and run backgrounded is Phase 5's job, not this phase's.
</domain>

<decisions>
## Implementation Decisions

### Schedule config shape (SCHD-01/02/03)
- **D-01:** Schedule entries are **nested under each location** as a TOML array of tables,
  `[[locations.schedule]]`, so each place's send-times sit next to its name/coords/timezone
  and read as one unit. (Chosen over a separate top-level `[[schedule]]` table.)
- **D-02:** Each schedule entry has three fields:
  - `time` — local wall-clock send time as a `"HH:MM"` 24-hour string (e.g. `"07:00"`).
  - `days` — day-of-week selection accepting **friendly presets AND explicit lists**:
    presets `"mon-fri"`, `"weekends"`, `"daily"` (and the obvious `"weekdays"`), plus
    explicit comma lists like `"sat,sun"` / `"mon,wed,fri"`. Planner: define the exact
    accepted vocabulary and validate it at config load (fail loud on a bad token, in the
    Phase 2 fail-at-load tradition).
  - `enabled` — boolean, **default `true`**. Setting `enabled = false` pauses a send-time
    **without deleting it** (SCHD-02) — the entry stays in the file as a record.
- **D-03:** A location may carry **multiple** `[[locations.schedule]]` blocks (SCHD-01).
  Example shape:
  ```toml
  [[locations]]
  name = "Home"
  lat = 40.7128
  lon = -74.0060
  timezone = "America/New_York"

    [[locations.schedule]]
    time = "07:00"
    days = "mon-fri"
    enabled = true

    [[locations.schedule]]
    time = "08:30"
    days = "sat,sun"
    enabled = true
  ```

### Missed-send recovery (SCHD-06)
- **D-04:** Recovery uses a **bounded grace window of 90 minutes (hardcoded, not config)**.
  When the daemon recovers from downtime that spanned a send-time, it delivers the missed
  briefing **only if recovery is < 90 min after the scheduled time**; otherwise it
  **skips and logs** it. This resolves the Phase-2-flagged "always send late vs grace
  window" open question and satisfies success criterion #4 ("within the defined grace
  window"). The literal SCHD-06 "always send late" is intentionally capped at 90 min so a
  morning briefing never arrives as stale, mistimed noise.
- **D-05:** Because the pipeline **re-fetches live weather at send time**, a recovered send
  shows *current* weather (a 7:00 slot recovered at 7:30 carries 7:30 weather), not stale
  data. Recovery is purely about *timing relevance*, not data freshness.

### Idempotency / slot identity (SCHD-07)
- **D-06:** The dedup key is **`(location, send-time, local-date)`** — a slot is identified
  by its **send-time string** (`"HH:MM"`), not an explicit id or list index. Editing a
  send-time (e.g. `07:00` → `07:15`) naturally becomes a *new* slot, which is the intuitive
  behavior since the user changed *when* it fires. (Chosen over an explicit `id` field and
  over list-position identity, which is fragile to reordering.)
- **D-07:** A slot is marked **sent only AFTER successful delivery** (Discord confirms). A
  crash mid-send leaves the slot unsent so it can re-fire on restart; the tiny
  crash-after-send-before-record window is accepted for v1 and is hardened by Phase 4's
  retry-then-alert. (Chosen over mark-on-attempt, which would silently lose a failed send
  and conflict with Phase 4.)
- **D-08:** The "already sent" log is a **new table in the existing `data/weatherbot.db`**
  (alongside `weather_onecall`), keyed by the D-06 tuple. Planner: design it as a small
  idempotency/sent-log table; reuse the store's existing connection/secret-hygiene
  discipline.

### Daemon run command (SCHD-05)
- **D-09:** Add a new **`weatherbot --run`** command (flag style, consistent with the
  existing `--send-now` / `--check` / `--geocode`). It runs in the **foreground**, blocks,
  logs to stdout, and shuts down cleanly on Ctrl-C / SIGTERM. It does **NOT** self-daemonize
  — backgrounding, restart-on-crash, and run-on-boot are deferred to Phase 5 (systemd
  `Restart=always`). Manual `--send-now` stays available alongside the daemon.
- **D-10:** On startup the daemon **announces its schedule**: log every *enabled* slot
  (location, time, days) and its computed next-fire time, run the **missed-send catch-up
  scan** (the D-04 90-min window), then idle until the next trigger. This gives at-a-glance
  confirmation the config was read correctly.
- **D-11:** In-process scheduler is **APScheduler 3.x** (`BackgroundScheduler` + per-job
  `CronTrigger(timezone=<location IANA tz>)`), per STACK.md and PROJECT.md's locked
  "in-process scheduler, not OS cron" decision. Add `apscheduler` (3.11.x line — NOT 4.x)
  to `pyproject.toml` dependencies. Each enabled `(location, schedule-entry)` becomes one
  cron job whose timezone is the location's configured IANA zone (D-03 from Phase 2 —
  config tz is authoritative). DST safety comes from `CronTrigger` + the D-06 idempotency
  key together (per-day key prevents fall-back double-fire; cron-at-local-time prevents
  spring-forward miss for morning sends).

### Briefing send-time / weather-check / late-send annotation (NEW — user-requested)
- **D-12:** Add **three new editable template placeholders** so the user controls wording
  and position (consistent with Phase 2's template system, D-09/D-10 there):
  - `{sent_at}` — when the briefing was actually delivered.
  - `{checked_at}` — when the weather was fetched (maps to the existing fetch timestamp;
    given single-fetch-at-send this is usually within seconds of `{sent_at}`, but is kept
    **distinct** so the user can gauge forecast freshness).
  - `{schedule_note}` — a human note like *"intended for 7:00 AM, sent 7:30 AM"* (exact
    wording is Claude's discretion).
- **D-13:** **Display rule:** `{sent_at}` and `{checked_at}` render on **every** message
  (scheduled and manual `--send-now`). `{schedule_note}` is populated **only when the send
  is late / off-schedule** (recovered within the 90-min window); it is **empty** on on-time
  sends and on manual `--send-now` (no scheduled time exists there), collapsing cleanly like
  `{hint}` / `{alert}` already do.
- **D-14:** All displayed times use the **location's local time** (its configured IANA tz).
- **D-15:** These placeholders **extend Phase 2's canonical placeholder set** (Phase 2 D-09)
  — planner MUST add them to `Forecast.placeholders()` (or wherever the placeholder map is
  built) AND to the `validate_template` canonical set, and reference them in the three
  starter templates. **Integration note:** `{sent_at}` and `{schedule_note}` derive from
  **scheduler context** (scheduled time, actual send time), NOT from the weather payload —
  so the render call must thread scheduling metadata in alongside the `Forecast`. This is a
  seam change at the `send_now`/render boundary; design it so manual `--send-now` (no
  scheduler) still renders `{sent_at}`/`{checked_at}` with an empty `{schedule_note}`.

### Claude's Discretion
- Exact accepted `days` vocabulary/aliases and their parsing (D-02) — sensible, validated.
- Exact wording/format of `{schedule_note}` and the time formatting of `{sent_at}`/`{checked_at}`
  (e.g. `7:30 AM` vs `07:30`); carry a sensible default, user will edit.
- Sent-log table name/columns and the catch-up scan implementation (D-08/D-10).
- The dual-unit / two-call fetch strategy and module layout carry forward from Phase 2 —
  the scheduler invokes the existing `send_now` composition root; planner decides exactly
  how scheduling metadata is threaded into it (D-15).
- APScheduler job-build details (job ids, coalesce/misfire settings) — note that the
  cross-restart catch-up is OWNED by our D-08 sent-log scan (memory jobstore won't recover
  missed fires across a process restart), so don't rely on APScheduler's misfire handling
  alone for SCHD-06.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 3: Always-On Scheduler" — goal, mode (mvp), the 5 success criteria
- `.planning/REQUIREMENTS.md` — SCHD-01..07 (and the Phase 4 RELY-*/Phase 5 OPS-* boundaries this phase must NOT cross)
- `.planning/PROJECT.md` — core value + locked decisions, esp. "in-process scheduler on an always-on host (not OS cron)" and "per-location schedules with multiple toggleable send-times"
- `.planning/STATE.md` — the Phase 3 "backfill-vs-skip grace window" blocker (now resolved by D-04)

### Prior phase context (foundation this phase extends)
- `.planning/phases/02-real-config-locations-content-templates/02-CONTEXT.md` — D-03 (config IANA `timezone` is authoritative, `Location.units` override), D-09 (canonical placeholder set this phase EXTENDS), D-10/D-11 (`validate_template` wraps the renderer, fires at every load incl. send path), D-12 (`--check`)
- `.planning/phases/01-first-briefing-end-to-end/01-CONTEXT.md` — the `send_now` composition root, `Channel.send(text)`/`send_briefing` seam, SQLite store + analysis axes, dual-unit imperial-primary display

### Research (technical grounding)
- `.planning/research/STACK.md` — **APScheduler 3.11.x** (`BackgroundScheduler` + `CronTrigger(timezone=...)`, use 3.x NOT 4.x), `zoneinfo` for IANA tz, structlog logging, systemd-for-process-liveness (Phase 5, not here)
- `.planning/research/ARCHITECTURE.md` — scheduler→fetch→render→dispatch boundaries and build order
- `.planning/research/PITFALLS.md` — timezone/day-boundary and DST edges, OpenWeather quota/key gotchas

### External library docs (research for this phase)
- APScheduler 3.x user guide — `BackgroundScheduler`, `CronTrigger` with `day_of_week`/`hour`/`minute` + `timezone=`, coalesce/misfire semantics (and why cross-restart recovery is owned by our sent-log, D-08/D-15)

No external ADRs/specs beyond the planning + library docs above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weatherbot/cli.py` (`main`, `send_now`) — the composition root the scheduler invokes per
  slot. Add a `--run` branch in `main` (D-09); `send_now` keeps its fetch→persist→render→deliver
  shape but the render boundary must accept scheduling metadata (D-15).
- `weatherbot/config/models.py` (`Location`, `Config`) — `Location` is `extra="forbid"`; add a
  nested `schedule: list[Schedule]` field (new `Schedule` model: `time`, `days`, `enabled`) with
  validators for `"HH:MM"` and the `days` vocabulary (D-01/D-02). Mirror the existing
  IANA-tz/units validator style.
- `weatherbot/weather/store.py` (`persist`, `_SCHEMA`) — add the idempotency/sent-log table to
  `_SCHEMA` (idempotent `CREATE TABLE IF NOT EXISTS`) and a small helper to read/record
  `(location, time, local_date)` (D-08). Reuse the parameterized-`?` + secret-hygiene discipline.
- `weatherbot/weather/models.py` (`Forecast`, `placeholders()`) — extend `placeholders()` with
  `{sent_at}`/`{checked_at}`/`{schedule_note}` (D-12/D-15); `{checked_at}` derives from the
  fetch/observed timestamp the model already retains.
- `templates/renderer.py` (`render`, `validate_template`, canonical set) — add the three new
  placeholders to the canonical set so they validate (D-15). Renderer engine itself unchanged.
- `templates/*.txt` (briefing-sectioned / -multiline / -compact) — reference the new placeholders
  in a footer-style line.

### Established Patterns (from Phases 1–2 — keep)
- Fail-loud-at-load via pydantic validation — extend to schedule `time`/`days` (D-02).
- Config IANA `timezone` is authoritative for "today" and now for scheduling (Phase 2 D-03).
- Single-fetch reuse: one fetch feeds persist AND render (DATA-03) — `{checked_at}` reads that
  same fetch timestamp.
- Secrets only on `Settings`; logging is outcome-only, never the key/URL (T-04-01).
- Empty-placeholder collapse (`{hint}`/`{alert}`) — `{schedule_note}` follows the same pattern (D-13).

### Integration Points
- `pyproject.toml` — add `apscheduler` (3.11.x) to `dependencies` (D-11).
- `config.toml` / `config.example.toml` — add `[[locations.schedule]]` blocks documenting
  `time`/`days`/`enabled` and the preset vocabulary (D-01/D-02).
- `data/weatherbot.db` — new sent-log table (D-08), additive schema only (no destructive migration).
- The `send_now` → render call — thread scheduling metadata (scheduled time, actual send time) in
  for `{sent_at}`/`{schedule_note}` (D-15); manual `--send-now` passes none → empty `{schedule_note}`.
</code_context>

<specifics>
## Specific Ideas

- The user's mental model for late sends: *"a message intended to be sent at 7am fails and is
  sent at 7:30 — the message should say it was scheduled for 7, sent at 7:30, ideally use a 7:30
  weather check, and tell the user when the weather was checked so they can gauge accuracy."*
  This is the literal motivation for D-12/D-13.
- Example footer the user reacted to:
  `— sent 7:30 AM · weather checked 7:30 AM` then `(intended for 7:00 AM)` only when late.
- Weekday-home / weekend-travel split remains the driving use case: `Home` Mon–Fri, `Weekend`
  Sat–Sun, each at its own local time in its own IANA zone (SCHD-04 two-timezone criterion).
</specifics>

<deferred>
## Deferred Ideas

- **Configurable grace window** — user chose a hardcoded 90 min (D-04). Exposing it in config is
  a clean later enhancement (grows `--check`'s surface); revisit only if 90 min proves wrong.
- **Self-daemonizing / background `--run`** — explicitly rejected for Phase 3 (D-09); process
  supervision, reboot survival, and run-on-boot are Phase 5 (OPS-01/02).
- **Retry-then-alert on a failed scheduled send, heartbeat/liveness** — Phase 4 (RELY-*). Phase 3
  marks a slot sent only on success (D-07), leaving the failed-send handling to Phase 4.
- **Configurable hint/annotation thresholds & richer schedule semantics** (e.g. per-slot template
  overrides, skip-on-holiday) — not requested; out of scope.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 3-Always-On Scheduler*
*Context gathered: 2026-06-10*
