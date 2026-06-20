# Phase 9: Reload Engine & Explicit Trigger - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

The running daemon applies edits to `config.toml` **and** the template files it
references — schedules, locations, units, templates — via an **explicit trigger**
(SIGHUP / `weatherbot reload`), with the pipeline: **validate → atomic all-or-nothing
swap → diff-and-re-register scheduler jobs**, keeping the old config on any failure and
preserving v1.0's exactly-once delivery across the reload. Also ships a
`weatherbot check-config` offline dry-run.

This builds directly on Phase 8: the live config is already owned by a lock-guarded
`ConfigHolder` whose `replace(new_config)` swap exists but does **not** validate — Phase
9 hangs the validate-before-swap boundary in front of it (CONTEXT 08 D-04). Jobs already
read `holder.current()` per-fire (Pitfall #9 mitigated) and key on the stable job id
`name|time|days` (Pitfall #7 reconcile key).

**Closes:** CFG-01 (edit applies without restart), CFG-02 (explicit signal/command
trigger), CFG-04 (invalid edit rejected, keep-old, all-or-nothing), CFG-05 (job
re-register without drop/double-fire; exactly-once preserved), CFG-06 (per-reload
outcome log line), CFG-08 (`check-config` dry-run).

**Out of scope (own phases):**
- File-watch auto-reload / debounce (Phase 10, CFG-03; Pitfalls #5, #11).
- Discord posting of reload outcome (Phase 11, CFG-07) — this phase logs only.
- `.env`/secrets reloadability — **permanent restart boundary** (Pitfall #12). The holder
  owns `Config` only, never `Settings`.
- The inbound Discord bot and all its concerns (Pitfalls #1–4, #10).
</domain>

<decisions>
## Implementation Decisions

### Exactly-once preservation across reload (Pitfall #8 — HIGHEST RISK)
- **D-01: Add an optional stable `id` to each `Location`.** The sent-log exactly-once key
  moves from the display `name` to this stable `id`, so renaming a location's display name
  never resets its "already sent today" state. `id` is **optional and defaults to the
  current `name` VERBATIM (raw, NOT casefolded)** — the sent-log stores `location.name` raw
  today, so a raw-name default makes the key **byte-identical** for any config where `id` is
  omitted, keeping existing rows valid with **zero migration**. Casefolding is used ONLY for
  the **uniqueness check** (so `Home` and `home` still collide as duplicate ids), never for
  the stored key value. The operator adds an explicit `id` only when they want rename-safety.
  Rejected: `id` required (breaking config change); a casefolded-slug default (would change
  the key for any uppercase name → first-day duplicate briefing unless rows are migrated —
  breaks the zero-migration promise; see RESEARCH.md A1); keeping `name` as the key with
  heuristic rename-detection (fragile — the exact Pitfall #8 failure).
  **Note:** the `id` value flows through FOUR sent-log/alert store functions (`claim_slot`,
  `was_sent`, `release_claim`, `record_alert`/`resolve_alert`) which must switch in lockstep;
  the DB column stays named `location_name` (change the value, not the schema — no migration).
- **D-02: An already-sent-today slot is protected against NAME and TZ changes (NOT send_time).**
  If the sent-log shows this location `id` already delivered today, a reload that changes the
  location's **name** or **IANA timezone** does **not** re-fire it that morning — those edits
  keep the slot's `send_time` (and thus the same logical slot), and the stable-`id` +
  already-sent-today guard suppresses a re-send/skip. This is the "no duplicate, no skip"
  guarantee for the genuinely risky edits (rename, tz-shift-across-midnight; Pitfall #8).
  **A `send_time` change is, by design, a NEW slot, not the same slot moved.** The exactly-once
  key is `(location_id, send_time, local_date)` and the APScheduler job id is `name|time|days`
  — both treat a different time as a distinct slot. So changing a slot's `send_time` produces a
  new key/job that **fires today if its new time is still ahead** (then settles to the new time
  from the next day). This is intentional and operator-confirmed: e.g. "I got the 08:00 briefing,
  then at 08:30 I move it to 09:00 — I WANT the 09:00 briefing today, and only 09:00 thereafter."
  A blanket location-level "already sent today" guard was **rejected** because it would break
  legitimate **multi-slot-per-day** locations (a morning + evening briefing for the same place).
  **Mandatory explicit test** (roadmap SC#4, Pitfall #8): reload a **tz/name** change for an
  already-sent slot and assert no re-send and no skip. (A `send_time` change firing today when
  ahead is the accepted, documented behavior — see RESEARCH A3, resolved.)

### Reload trigger plumbing (Pitfall #13)
- **D-03: `weatherbot reload` uses a PID file + SIGHUP.** The daemon writes its PID to a
  known file on startup (atomically) and unlinks it in the existing clean-shutdown path;
  `weatherbot reload` reads the file and sends `SIGHUP` to that PID, **after verifying via
  `/proc/<pid>/cmdline` that the PID is actually a weatherbot process** (stale-PID guard
  against PID recycling after a hard kill). Chosen over systemd-only (`systemctl reload` →
  `ExecReload`) because it is self-contained: it works identically on a bare dev box / Pi /
  container **and** under systemd, and it is required anyway given D-04 declines `ExecReload`
  (so `weatherbot reload` must discover the PID itself rather than lean on systemd's
  `MAINPID`).
- **D-04: Reload stays always-ready — no `ExecReload`, no sd_notify reload handshake.**
  Because reload is always either old-good or new-good (keep-old-on-failure, D-02/CFG-04), it
  can never make the process unhealthy, so it does **not** touch the systemd ready/health
  state. Do not wire `ExecReload` or emit `RELOADING=1`→`READY=1`. Only a **restart**
  re-runs `gate_until_healthy`. This is Pitfall #13's "simplest correct choice." SIGHUP is
  delivered directly via D-03, not via `systemctl reload`.

### Offline config dry-run (CFG-08)
- **D-05: `check-config` is a NEW offline-only validation — zero network.** It performs
  parse + full pydantic validate + unique `id`/`name` + template-token validation and
  applies/sends **nothing**. It is **distinct** from the existing `check` subcommand (which
  also runs a live OpenWeather reachability probe). Critically, this offline validation is
  the **same single function** the reload engine runs before swapping — `check-config` and
  reload-validate share ONE code path so a config that passes `check-config` is exactly a
  config reload will accept.
- **D-06: Surface it as a `weatherbot check-config` subcommand** — a new subparser
  alongside the Phase 7 `weather` / `check` / `run` / `send-now` subcommands, consistent
  with the established `add_subparsers` grammar. (Roadmap wording `--check-config` reads as a
  flag, but a subcommand fits the existing CLI structure; honored as a subcommand.)

### Reload outcome reporting & scope (CFG-06)
- **D-07: A successful reload logs a job-diff summary.** The CFG-06 success log line reports
  the reconciliation result — slots **added / removed / changed / unchanged** (e.g.
  `reload applied: +1 -0 ~2 =3`) — so the operator can confirm exactly what took effect. A
  rejected reload logs the validation reason. (Discord posting of this outcome is Phase 11 /
  CFG-07, out of scope.)
- **D-08: An explicit reload re-reads template FILES too, not just `config.toml`.** It
  re-reads both `config.toml` and the template files it references, validating template
  tokens **before** the swap (part of D-05's shared validation). A template-file edit alone
  (no `config.toml` change) is therefore picked up on the next explicit trigger. Matches the
  phase goal's explicit "config.toml and template files" wording and CFG-01.
  **Note (RESEARCH correction):** the project has **no Jinja2** — token validation is the
  existing regex allow-list `templates/renderer.py::validate_template`, which already detects
  unknown/typo'd `{token}`s offline with no render and no network. D-05/D-08 reuse it; no
  `jinja2.meta`/`StrictUndefined` work.

### Claude's Discretion
Left to research/planning — no operator preference expressed, and the roadmap flags this
phase for `/gsd-plan-phase --research-phase 9`:
- **Two-phase build-then-commit apply** (Pitfall #6): build & fully validate the complete new
  application state (config + implied job set + validated templates) off to the side, then
  commit by swapping the live `holder` reference and reconciling jobs only after phase 1 fully
  succeeds. Rollback mechanics if job re-registration itself fails midway (snapshot the old job
  set). "All-or-nothing apply" is a phase success criterion.
- **Job diff/reconcile mechanics** (Pitfall #7): `add_job(..., id=..., replace_existing=True)`
  on the stable `name|time|days` id, computing the add/update/remove delta — never
  `remove_all_jobs()`. What precisely counts as a "changed" slot for the diff.
- **PID file location/path** (e.g. `/run/weatherbot.pid` vs a configurable path) and atomic
  write mechanics.
- **Where SIGHUP handoff does its work**: the signal handler must not run the
  validate→swap→re-register work re-entrantly inside the handler — recommend it sets a
  flag/Event and the actual reload runs on the main loop (or a dedicated reload path),
  mirroring how the existing SIGTERM handler sets `stop`. Planner to confirm.
- **Units-change handling** within the same swap (units are a `Config` field; covered by the
  atomic swap, but confirm no special-casing needed).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & requirements
- `.planning/ROADMAP.md` — Phase 9 entry (goal, depends-on Phase 8, the 5 success criteria,
  and the "Research flag" recommending `--research-phase 9` for the Pitfall #8 policy).
- `.planning/REQUIREMENTS.md` — CFG-01, CFG-02, CFG-04, CFG-05, CFG-06, CFG-08 (the six
  requirements this phase closes); CFG-03 (Phase 10) and CFG-07 (Phase 11) are explicitly OUT.

### Pitfalls research (this phase is the primary target)
- `.planning/research/PITFALLS.md` — **MANDATORY.** Pitfall #6 (all-or-nothing apply),
  Pitfall #7 (job double-fire/drop on reload — stable id + diff-reconcile), **Pitfall #8
  (exactly-once key break — HIGHEST RISK, drives D-01/D-02)**, Pitfall #9 (in-flight snapshot —
  already mitigated in Phase 8), Pitfall #12 (secrets are a restart boundary — out of scope),
  Pitfall #13 (systemd reload signaling — drives D-04). See also the "Looks Done But Isn't"
  hot-reload checklist and the Integration Gotchas table.

### Prior-phase context this phase builds on
- `.planning/phases/08-configholder-fire-slot-reads-from-holder-refactor/08-CONTEXT.md` —
  the `ConfigHolder` seam, `frozen=True` snapshots, per-fire `holder.current()` read, and
  D-04 deferring validate-before-swap to **this** phase.
- `.planning/phases/08-configholder-fire-slot-reads-from-holder-refactor/08-SECURITY.md` —
  T-08-07 (unvalidated config via `replace()`) was **accepted/deferred to Phase 9 / CFG-04**;
  this phase owns it.

### Code this phase extends
- `weatherbot/config/holder.py` — `ConfigHolder.replace()` (the swap seam; validate hangs in
  front of it) and `current()`.
- `weatherbot/config/loader.py` — `load_config` (`Config.model_validate`), `assert_unique_names`
  (the unique-name check to extend to unique `id`); the offline-validation function (D-05) lives
  here or beside it.
- `weatherbot/config/models.py` — `Location` gains the optional `id` field (D-01).
- `weatherbot/scheduler/daemon.py` — `run_daemon` (SIGTERM handler at ~line 657, `stop.wait()`
  block, scheduler ownership; SIGHUP handler + PID-file write/unlink hook here), `_register_jobs`
  (`add_job(..., id=..., replace_existing=True)` diff-reconcile target), `fire_slot` (the
  `claim_slot(db_path, location.name, …)` call at ~line 168 — the exactly-once key that moves to
  `id`).
- `weatherbot/scheduler/catchup.py` — `plan_catchup` / `was_sent(loc.name, …)` at ~line 170 (the
  other exactly-once key callsite that moves to `id`).
- `weatherbot/weather/models.py` — `_local_date_iso(loc, now_utc)` (~line 34) and the
  sent-log/idempotency key construction (`local_date`, `date` fields).
- `weatherbot/cli.py` — `add_subparsers` block (~line 534), `do_check` (~line 393, the existing
  network-probing `check`), where the `reload` and `check-config` subcommands slot in.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`ConfigHolder.replace()`** (Phase 8) — the atomic lock-guarded swap is ready; Phase 9 only
  adds the validate-before-swap gate in front of it. No new concurrency primitive needed.
- **`load_config` + `assert_unique_names`** (`loader.py`) — the existing parse/validate path is
  the basis for D-05's shared offline validation; extend `assert_unique_names` to also enforce
  unique `id`.
- **Existing SIGTERM handler pattern** (`daemon.py` ~657: `signal.signal(SIGTERM, _handle)` →
  sets `stop` Event → `stop.wait()`). SIGHUP follows the same install-before-start pattern; the
  handler should set a reload flag rather than do reload work re-entrantly.
- **Phase 7 `add_subparsers` CLI** (`cli.py` ~534) — `reload` and `check-config` are new
  subparsers in the same grammar; `do_check` shows the validate-and-report shape to mirror
  (minus the network probe).
- **Stable job id `name|time|days`** (Phase 8 / P3 D-06) — the reconcile key for the
  add/update/remove diff; `replace_existing=True` makes re-adding an unchanged job a no-op.

### Established Patterns
- **Exactly-once key is `(location.name, slot.time, local_date)`** today, claimed atomically via
  `claim_slot` and checked via `was_sent`, with `local_date` derived from the location's IANA tz.
  D-01 moves the `location.name` component to the stable `id`; with `id` defaulting to `name`,
  existing sent-log rows remain valid (key unchanged for un-`id`'d configs).
- **`frozen=True` Config snapshots** (Phase 8) — the validated new config built off-to-the-side
  is a frozen `Config`; the swap hands out an immutable reference (readers see fully-old or
  fully-new).
- **`misfire_grace_time=None` + sent-log/catch-up ownership of recovery** — reload changes WHAT
  config a job reads and WHICH jobs exist, not the misfire/recovery semantics.
- **systemd `Type=notify` + `gate_until_healthy`** — only startup/restart runs the health gate;
  reload deliberately never touches READY (D-04).

### Integration Points
- `reload` CLI invocation → PID file → `SIGHUP` → daemon reload path (validate → `holder.replace`
  → job diff-reconcile). This is the new cross-process control path.
- Reload-validate ↔ `check-config`: ONE shared offline-validation function (D-05).
- New config's exactly-once key ↔ the sent-log: the `id`-based key must agree between
  `fire_slot`/`claim_slot` (daemon) and `was_sent` (catchup) so a reload can't desync them.
- The validated job set ↔ APScheduler live job set: diff-reconcile on stable ids.
</code_context>

<specifics>
## Specific Ideas

- The single most important verification (roadmap SC#4, Pitfall #8): a test that takes a slot
  **already marked sent today**, reloads a config that **changes that slot's tz / name /
  send_time**, and asserts **no duplicate and no skipped** briefing for that morning. This is
  the failure most likely to silently break a shipped guarantee — give it an explicit test.
- The all-or-nothing test (SC#2, Pitfall #6): inject a failure during job re-registration and
  assert the OLD schedule still fires fully intact (not torn).
- The idempotent-reload test (SC#3, Pitfall #7): reloading the identical config produces zero
  job changes and no duplicate fires.
- `check-config` and reload-validate must be proven to share one path (a config that passes
  `check-config` is accepted by reload, and vice-versa).
</specifics>

<deferred>
## Deferred Ideas

- **File-watch auto-reload + debounce** — Phase 10 (CFG-03); reuse this phase's reload engine as
  the funnel (Pitfalls #5, #11).
- **Discord posting of reload outcome** (success summary / rejection reason) — Phase 11 (CFG-07);
  this phase logs only (CFG-06).
- **`.env`/secrets hot-reload** — permanently out of scope; secrets are a restart boundary
  (Pitfall #12). Reload is config-only.
- **systemd `ExecReload` / sd_notify reload handshake** — considered and explicitly declined
  (D-04); reload stays always-ready. Revisit only if a future requirement makes `systemctl
  reload` a needed surface.

None of the above were in scope — discussion stayed within the Phase 9 boundary.

</deferred>

---

*Phase: 9-Reload Engine & Explicit Trigger*
*Context gathered: 2026-06-15*
