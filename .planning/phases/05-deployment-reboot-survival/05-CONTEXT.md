# Phase 5: Deployment & Reboot Survival - Context

**Gathered:** 2026-06-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 turns the Phase 3/4 **foreground** daemon (`weatherbot --run`) into a
**supervised, reboot-surviving** process that **self-checks before announcing
itself online** — the final milestone phase. It covers exactly two requirements:

- **OPS-01:** The bot runs as a long-running **supervised** process that survives
  crashes and host reboot, restarting automatically without manual intervention.
- **OPS-02:** On startup the bot **self-checks** (config valid + OpenWeather key
  reachable, distinguishing *key-not-yet-active / not-propagated* from a *genuine
  auth error*) and emits an **"online" signal** so a silent death after deploy or
  reboot is detectable.

The daemon today (`run_daemon` in `weatherbot/scheduler/daemon.py`) explicitly
*"Does NOT self-daemonize (systemd owns process liveness, Phase 5)"* and already
logs `daemon started` + stamps a startup heartbeat tick. Phase 5 wraps it in a
**systemd supervisor unit**, adds a **startup self-check gate**, and formalizes
the **online signal**.

**Explicitly NOT this phase** (deferred / out of scope):
- **Inbound Discord commands** (e.g. messaging the bot `status` and it replies
  with its current error/health state). This is a *new capability* needing a
  Discord **gateway bot** (`discord.py` + bot token), not the fire-and-forget
  **webhook** this project uses — a real architectural addition. Deferred to its
  own future phase. (Phase 5 *does* lay the seam — see D-08.)
- Docker/container deployment (systemd chosen for v1, D-01).
- SMS/Telegram channels, weather-pattern analysis (v2).
- The future log-monitoring bot itself (Phase 4 deferred item) — Phase 5 only
  produces the online/health artifacts it will consume.

Requirements covered: OPS-01, OPS-02.
</domain>

<decisions>
## Implementation Decisions

### Supervisor target (OPS-01)
- **D-01:** Ship a **systemd unit** (a `.service` file with `Restart=always` +
  `EnvironmentFile=` for `.env` secrets) that runs `weatherbot --run`. This is
  CLAUDE.md's "lightest reliable" recommendation for a Pi/server and avoids
  container overhead. **Docker/compose is NOT shipped** in this phase.
- **D-02:** The unit declares **`After=network-online.target`** (+
  `Wants=network-online.target`) so on a host reboot the daemon does not start
  until the network is up — the realistic Pi-just-booted case (D-06).

### Startup self-check (OPS-02)
- **D-03:** The daemon **runs the self-check itself at startup** (does NOT rely
  on an operator running `--check` separately). Reuse the **existing `do_check`
  logic** in `weatherbot/cli.py` — config + template validation + ONE OpenWeather
  reachability probe whose 401/403 message already distinguishes "subscription
  not active / not yet propagated" from a generic error (Pitfall 1). This runs
  **before** the online signal fires (D-05).
- **D-04 (stay-up, never crash-loop):** On a self-check **failure the daemon
  stays alive and re-probes internally** — it does **NOT** exit-and-let-the-
  supervisor-restart. This holds for **both**:
  - *Transient / not-ready* failures (network-not-up-yet, key still propagating):
    keep re-probing until success, then fire the deferred online signal (D-05).
  - *Genuine permanent auth failure* (a confirmed 401/403 that is NOT
    network-not-ready and NOT a still-propagating new key): **still stay alive** —
    log a **CRITICAL** event + write a durable health/alert row (Phase 4 frame,
    D-07), and **keep re-probing**. Rationale (user-stated): the process must
    remain **reachable/alive** so a future inbound-`status` feature (D-08) can
    query its current error state; a dead/crash-looping process can't be queried.
  - The re-probe **interval** is **Claude's discretion** (sensible default, e.g.
    ~60–300s; may promote to config later — same posture as Phase 4 D-06).

### "Online" signal (OPS-02 SC#3)
- **D-05 (all three signals, fired once after first successful self-check):** The
  online signal is emitted via **all three** of:
  1. **Log + durable DB row** — a structured `online`/`started` event + a DB stamp
     (the Phase 4 future-monitoring-bot frame; `run_daemon` already logs
     `daemon started` + stamps a heartbeat tick — formalize this into the online
     signal). This is the primary machine-detectable path.
  2. **systemd `sd_notify` `READY=1`** — the unit is **`Type=notify`**; the daemon
     signals readiness only **after** the self-check passes, so `systemctl status`
     reflects genuine readiness, not just "process spawned".
  3. **Discord "online" ping** — a one-time human-facing post to the configured
     webhook on a healthy start.
  - **Timing:** the online signal fires **exactly once per process start, only
    AFTER the self-check first passes.** If the startup probe initially fails
    (network not ready / key propagating), the online signal is **DEFERRED** until
    the internal re-probe (D-04) first succeeds, then fires. `sd_notify READY=1`
    waits for this same gate (systemd shows "starting" until genuinely ready).
- **D-06 (reboot network-readiness):** Startup probe failures are **classified**:
  connection/timeout/DNS errors (and the not-yet-active key) are treated as
  **transient "not ready"** → re-probe/wait (D-04), distinct from a confirmed
  401/403 bad key. Combined with the unit's `After=network-online.target` (D-02),
  this makes a real Pi reboot (network comes up slightly after the process is
  eligible) robust rather than a false "bad key" failure.
- **D-07 (Discord ping anti-spam — once per process start):** The Discord online
  ping posts **exactly once when a freshly-started process passes its self-check**.
  Internal re-probe recoveries do **NOT** re-post (only one online per process
  lifetime). A supervisor crash-loop would still post per *new* process start —
  accepted as an honest "I restarted" signal. (Note: this is the one place the
  webhook carries a status message; Phase 4 kept *failure alerts* off Discord, but
  the *online* ping is a deliberate, user-chosen human-facing signal — see
  Specific Ideas.)

### Future-extensibility seam
- **D-08 (queryable health/status state):** So the deferred inbound-`status`
  feature has something to read, Phase 5 makes the daemon's **current health/error
  state durable and queryable** — a health/status row in `data/weatherbot.db`
  reflecting the **last self-check result + current reason** (e.g. `online`,
  `network_not_ready`, `auth_failed`, `key_propagating`), reusing the existing
  `alerts`/`heartbeat` `INSERT OR IGNORE` / single-row-upsert pattern. This is the
  clean seam for a future Discord-gateway "status" command — it reads the row, it
  does not re-run a probe. **In scope:** writing/maintaining the row. **Out of
  scope:** the inbound command that reads it (deferred).

### Claude's Discretion
- Self-check re-probe interval (D-04) — sensible default, may promote to config.
- Exact systemd unit filename, `User=`/`WorkingDirectory=`/`RestartSec=` values,
  and whether to provide an install snippet/instructions — follow standard
  systemd conventions for a personal always-on service.
- Exact health/status row table/column names (D-08) and the online-event key —
  follow the `weatherbot/weather/store.py` conventions (`alerts`/`heartbeat`).
- The precise transient-vs-permanent probe classification (D-06) — reuse Phase 4's
  `is_transient`/`is_auth_failure` reliability classifiers where they fit.
- Whether the online DB stamp reuses the `heartbeat` row or adds a dedicated
  `online`/`status` row (likely the D-08 health row).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 5: Deployment & Reboot Survival" — goal, mode
  (mvp), the 3 success criteria
- `.planning/REQUIREMENTS.md` — OPS-01, OPS-02 (the only two requirements this
  phase covers; the milestone completes when both ship)
- `.planning/PROJECT.md` — core value (reliable hands-off morning briefing) +
  Constraints: *"Long-running process on an always-on host (server/Pi)… must
  survive across days without manual restarts"* and *"systemd with Restart=always
  so the bot survives crashes/reboots — complements the in-process scheduler"*
- `.planning/STATE.md` — milestone status (Phase 5 is the last phase; running
  `/gsd-complete-milestone` should follow Phase 5 verification)

### Prior phase context (the foundation this phase wraps)
- `.planning/phases/04-retry-then-alert-reliability/04-CONTEXT.md` — **the design
  north-star**: alert/heartbeat artifacts are **log + durable queryable DB rows**
  for a **future monitoring bot** ("machine-detectable and durable, not human push
  in v1"). The online signal + health-state row (D-05/D-08) extend this frame.
  D-05 (single `heartbeat` row pattern), D-11 (`INSERT OR IGNORE` dedup) are the
  models for the new health/online state. Note Phase 4 deliberately kept *failure
  alerts off Discord* — D-07 here is a scoped, user-chosen exception for the
  *online* ping only.
- `.planning/phases/03-always-on-scheduler/03-CONTEXT.md` — the daemon lifecycle
  (`run_daemon` foreground, SIGTERM/`threading.Event` shutdown, `misfire_grace_time=None`)
  that systemd now supervises; clean-shutdown contract systemd must respect.
- `.planning/phases/02-real-config-locations-content-templates/02-CONTEXT.md` —
  fail-loud-at-load config validation + the `--check` surface that `do_check`
  (the self-check engine, D-03) belongs to.
- `.planning/phases/01-first-briefing-end-to-end/01-CONTEXT.md` — secrets-from-env
  (`.env` via `Settings`, never committed) — the systemd `EnvironmentFile=` must
  preserve this (D-01); SQLite store the health/online row joins (D-08).

### Research (technical grounding)
- `.planning/research/STACK.md` — systemd unit with `Restart=always` +
  `EnvironmentFile=.env` as the lightest reliable supervisor; structlog logging
- `.planning/research/ARCHITECTURE.md` — process supervision complements (does not
  replace) the in-process scheduler
- `.planning/research/PITFALLS.md` — **Pitfall 1**: OpenWeather 401/403 =
  subscription not active / not yet propagated / new key takes up to ~2h
  (drives the self-check's key-not-yet-active vs genuine-auth distinction, D-03/D-06);
  secret-in-URL/log hygiene (no key/webhook in any log or DB row)

### Key code touchpoints (read before planning)
- `weatherbot/cli.py` — `do_check` (lines ~314–394: the **ready-made self-check
  engine** — config + template validation + 401/403-distinguishing reachability
  probe — to invoke from daemon startup, D-03); `main`'s `--run` branch (~482–496)
  that calls `run_daemon`
- `weatherbot/scheduler/daemon.py` — `run_daemon` (~439–511: register jobs →
  announce → catch-up → `scheduler.start()` → `stamp_tick` + `_log.info("daemon
  started")` → block on `threading.Event` w/ SIGTERM handler). The self-check gate
  (D-03/D-04) + online signal (D-05) wire in around `scheduler.start()`; the
  internal re-probe loop (D-04) must stay SIGTERM-interruptible like the existing
  `stop` event. `HEARTBEAT_INTERVAL_S`/`_heartbeat_tick`/`stamp_tick` are the
  liveness frame the online/health state joins.
- `weatherbot/weather/store.py` — `_SCHEMA` (`alerts` table ~117, single-row
  `heartbeat` table ~129), `record_alert`/`resolve_alert`/`stamp_tick`/
  `stamp_success` — the **template** for the new health/status row (D-08) and the
  online DB stamp (D-05); reuse `INSERT OR IGNORE` / single-row upsert + secret
  hygiene
- `weatherbot/reliability/retry.py` — Phase 4 `is_transient`/`is_auth_failure`
  classifiers to reuse for the startup probe's transient-vs-permanent split (D-06)
- `pyproject.toml` — if `sd_notify`/`Type=notify` (D-05) needs a helper, prefer a
  tiny direct `NOTIFY_SOCKET` write over a new dependency (Claude's discretion)

No external ADRs/specs beyond the planning + research docs above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weatherbot/cli.py::do_check` — **already implements the OPS-02 self-check**:
  config validation, template validation, `assert_unique_names`/`resolve_location`,
  and ONE `fetch_onecall` reachability probe that distinguishes 401/403
  "subscription not active / not yet propagated" from a generic error. The daemon
  startup gate (D-03) should call this logic rather than re-implement it. (May need
  light refactor so the daemon can call it and branch on transient-vs-auth, D-06.)
- `weatherbot/scheduler/daemon.py::run_daemon` — the foreground lifecycle systemd
  supervises; already stamps a startup `stamp_tick` + logs `daemon started`
  (~497–498) — the natural place to formalize the online signal (D-05). Its
  `threading.Event` (`stop`) + SIGTERM handler is the interruptible-wait primitive
  the re-probe loop (D-04) reuses.
- `weatherbot/weather/store.py` — `alerts` (keyed dedup, `record_alert`/
  `resolve_alert`) + single-row `heartbeat` (`stamp_tick`/`stamp_success`) are the
  exact template for the durable health/status row (D-08) and the online DB stamp
  (D-05).
- `weatherbot/reliability/retry.py` — `is_transient`/`is_auth_failure` for the
  startup probe classification (D-06).

### Established Patterns (from Phases 1–4 — keep)
- **Foreground daemon, SIGTERM-clean shutdown** (Phase 3 D-09) — systemd sends
  SIGTERM on stop/restart; the unit must let the existing handler shut down
  cleanly (the re-probe loop must honor the same `stop` event).
- **Secrets only from `.env`/`Settings`, never logged/committed** (T-01/T-04) —
  systemd `EnvironmentFile=` carries `.env`; no key/webhook in any online/health
  log line or DB row.
- **Fail-loud-but-clean** (Phase 2 CONF-05) — startup self-check failures surface
  as outcome-only CRITICAL events (no raw traceback for config errors), distinct
  reasons (`auth_failed` vs `network_not_ready` vs `key_propagating`).
- **Additive SQLite schema** (`CREATE TABLE IF NOT EXISTS`) — the health/status
  row (D-08) is additive, no destructive migration; analysis/monitor-ready like
  `alerts`/`heartbeat`/`weather_onecall`.
- **Durable + queryable for a future bot** (Phase 4 north-star) — every online/
  health artifact optimized for "easy for a bot to detect/query reliably".

### Integration Points
- **New systemd unit file** (e.g. `deploy/weatherbot.service` — location is
  planner's call): `Restart=always`, `Type=notify`, `EnvironmentFile=`,
  `After=/Wants=network-online.target`, `ExecStart=… weatherbot --run`.
- `weatherbot/scheduler/daemon.py::run_daemon` — self-check gate + deferred online
  signal + internal re-probe loop wire in around `scheduler.start()`.
- `data/weatherbot.db` — new health/status row + online stamp (D-05/D-08).
- `weatherbot/cli.py` — `do_check` becomes the shared self-check engine the daemon
  invokes (possibly extracted so both `--check` and startup reuse it).
</code_context>

<specifics>
## Specific Ideas

- **User's stay-alive-and-reachable intent (verbatim source of D-04/D-08):**
  *"I want the bot to still be reachable thru Discord; eventually we will implement
  a parser so I'd like to for example send 'status' thru Discord, the bot reads and
  tells me which error he is experiencing if possible."* This is why the daemon
  **never exits on an auth failure** (a dead process can't answer a status query)
  and why Phase 5 **persists current health/error state** as the seam the future
  inbound-`status` command will read.
- **All three online signals chosen deliberately** (D-05): log+DB (for the future
  monitoring bot), `sd_notify` (for `systemctl status`), AND a one-time Discord
  ping (immediate human visibility) — the user wants redundant detectability of a
  healthy start.
- **systemd specifically** (not Docker) for a Pi/personal-host deploy (D-01).
</specifics>

<deferred>
## Deferred Ideas

- **Inbound Discord `status` command** (the user messages the bot and it replies
  with its current error/health state). New capability — needs a Discord **gateway
  bot** (`discord.py` + bot token), not the current fire-and-forget **webhook**.
  Its own future phase. Phase 5 lays the seam (D-08: durable queryable health
  state) but does NOT build the inbound reader.
- **Docker / container deployment** (`Dockerfile` + compose `restart: always`) —
  not shipped in v1; systemd chosen (D-01). Revisit if a containerized host is
  wanted.
- **Promoting the re-probe interval to config** (D-04) — carried as a discretion
  default now; expose later if it proves wrong (same posture as Phase 4 D-06).
- **Routing the structured online/health log event to journald→email / external
  monitoring** — that's the future monitoring bot's job (Phase 4 deferred item),
  not Phase 5.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 5-Deployment & Reboot Survival*
*Context gathered: 2026-06-11*
