# Phase 29: Startup Validation & Honest Alerting - Context

**Gathered:** 2026-07-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the daemon `run` boot path fail *loudly* on a misconfiguration instead of
booting green and silently dropping every briefing. Three defects, one per
requirement:

- **HARD-STARTUP-01 (F05, `cli.py:986`)** — `run` currently loads config via
  `_load_config_reporting` → `load_config()`, which does NOT run
  `assert_unique_names` or template-token validation. `check-config` and
  hot-reload both run the fuller `validate_config_and_templates`
  (`config/loader.py:99`); `run` skips it, so a duplicate location id/name or a
  typo'd `{token}`/missing template file boots green.
- **HARD-STARTUP-02 (F06, `ops/selfcheck.py:116`)** — the catch-all classifies
  *permanent* config/template/empty-locations errors as `NETWORK_NOT_READY`. The
  readiness loop then re-probes forever, sending nothing, and never Discord-alerts
  (the online ping only fires on success).
- **HARD-STARTUP-03** — two ordering/logging findings: F90 (`daemon.py:1042`
  `_announce_schedule` omits forecast slots from the boot schedule log, so a
  disabled forecast slot is invisible) and F07 (`wiring.py:305` online-ping runs
  *before* systemd `READY=1`, so a slow webhook can make systemd kill startup).

Scope is fixed by the roadmap: clarify HOW to fix these, not WHETHER to add
capabilities. This is the highest real-world-impact class and gates v2.1.

</domain>

<decisions>
## Implementation Decisions

### Fatal-error behavior (STARTUP-02)
- **D-01:** On a **permanent** config/template/empty-locations error, the daemon
  **alerts then exits non-zero** — it does NOT warm-loop and does NOT stay alive
  inert. Introduce a distinct fatal reason (e.g. `CONFIG_INVALID`) separate from
  `NETWORK_NOT_READY` and `AUTH_FAILED`.
- **D-02:** Stamp the durable health row with the fatal reason **before** exiting,
  so a later `!status` (after a systemd restart) still reads the fatal reason from
  the DB — no need for an inert live process to answer status.
- **D-03:** `AUTH_FAILED` (401/403) behavior is **unchanged** — it keeps
  re-probing. A single 401/403 cannot distinguish a permanently-bad key from one
  still propagating (~2h activation, D-06). ONLY config/template/empty-locations
  become fatal.

### Alert-spam control (STARTUP-02 / ops)
- **D-04:** Fatal Discord alert is **best-effort, once per process boot**. Bound the
  restart churn at the **systemd layer**, not with new app-side persistence.
- **D-05:** This REQUIRES a `deploy/weatherbot.service` change:
  `Restart=always` → `Restart=on-failure`, plus `StartLimitIntervalSec` +
  `StartLimitBurst` in `[Unit]` so a fatal-exit config error trips the start-limit
  and parks the unit in `failed` (loud at the OS layer) instead of an infinite 5s
  crash-loop + infinite alerts. **Keep `TimeoutStartSec=infinity`** — it exists
  deliberately so the *transient* slow-key re-probe (which stays alive, never
  exits) is not turned into a disguised crash-loop (unit comment lines 24-27). The
  fatal path exits; the transient path does not — the two are compatible.
- **D-06:** The unit change is in-repo (`deploy/weatherbot.service`) but the live
  effect needs a redeploy + `systemctl daemon-reload` on host `yahir-mint` →
  **deferred Gate-2 obligation** (see live-service note in Deferred).

### Boot validation placement (STARTUP-01)
- **D-07:** `run()` calls the full offline `validate_config_and_templates(args.config)`
  **before** `run_daemon` — same validator `check-config`/reload use, zero network,
  fail-fast. This is the **PRIMARY** fatal mechanism and it is **fully app-side**:
  because it runs before the ReadyGate, every real permanent-config case is caught
  before the hub readiness loop ever runs, so the alert+exit lives in app code with
  no hub change.
- **D-08:** On boot-gate failure, build the channel best-effort from `settings` and
  fire the fatal operator alert (D-01/D-04), then exit non-zero. This threads
  STARTUP-01's detection into STARTUP-02's fatal handling — one code path.

### Probe-time fatal & cross-repo jurisdiction (STARTUP-02)
- **D-09:** The live readiness loop is the **hub's** `ReadyGate.run(stop)`
  (`yahir_reusable_bot/lifecycle/ready_gate.py`). It has **no fatal path** — every
  non-ok result re-probes forever; it only branches *log level* on `severity`.
  Changing it is a human-gated hub tag-cut (ECOSYSTEM), out of scope to ship
  autonomously here.
- **D-10 (chosen: A + hub handoff):** Ship the app-side fatal-stop **now** AND log
  the hub enhancement for later — they are complementary, not exclusive:
  - **App-side (Phase 29):** fix `selfcheck.py` classification to return the fatal
    reason with CRITICAL severity, AND make the app-injected `on_fail` hook, on a
    fatal result, **set the `stop` Event + a fatal marker + fire the alert**. After
    `ready_gate.run()` returns `False`, the composition root distinguishes fatal
    (marker set → exit non-zero) from a clean SIGTERM shutdown (marker unset →
    exit 0). Uses the hub's existing extension points (`on_fail` hook + `stop`
    Event) → **no hub change**.
  - **Hub handoff (deferred, human-gated):** add a first-class "fatal outcome" to
    `ReadyGate.run` (break + signal fatal cleanly instead of the app overloading
    `stop`). Routes to `.planning/HUB-FINDINGS-HANDOFF.md` for the next
    `YahirReusableBot` tag; WeatherBot repins after and can de-hack the app-side
    `stop`-overload to use the first-class path. See Deferred.

### STARTUP-03 scope
- **D-11:** Fix **F90** — `_announce_schedule` (`daemon.py:1042`) must iterate the
  forecast slots too, so the boot schedule log shows *every* scheduled job
  (briefing + forecast) with `next_run_time`. A disabled/misconfigured forecast
  slot must be visible at the one point the schedule is announced.
- **D-12:** Fix **F07** — move the one-time Discord online-ping to *after*
  `notifier.ready()` (`READY=1`), so a slow/hung webhook can't block systemd
  readiness past `TimeoutStartSec` (real v2.0 refactor regression).
- **D-13:** **Fold F89** into this phase (user chose to, since the file is already
  open): `_forecast_failure_streaks` module dict (`daemon.py:392`) is keyed by
  `location.name` and never pruned on config reload — a renamed/removed forecast
  slot leaks its entry forever (only `_note_forecast_success` pops it, which never
  fires for a removed slot). Prune dead entries on reload.

### Claude's Discretion
- Exact fatal reason constant name (`CONFIG_INVALID` vs similar), the concrete
  `StartLimitIntervalSec`/`StartLimitBurst` values, and the fatal-marker plumbing
  shape are left to research/planning — the *behavior* above is locked.
- Whether `wait_ready_gate`/`gate_until_healthy` (`daemon.py:1108-1156`) is dead
  app-side code superseded by `ready_gate.run()` (line 1465): confirm during
  planning; if dead, removing it is in-scope cleanup (same file, already open).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & audit
- `.planning/ROADMAP.md` — Phase 29 goal, depends-on, success criteria (3).
- `.planning/REQUIREMENTS.md` §"Startup Validation & Honest Alerting (HARD-STARTUP)"
  — HARD-STARTUP-01/02/03 with finding ids.
- `.planning/WHOLE-PROJECT-REVIEW.md` — finding-level detail: **F05** (run-path
  validation gap), **F06** (selfcheck misclassification), **F07** (ping-before-READY
  regression), **F90** (announce omits forecast slots), **F89** (streak-dict leak).
- `.planning/audit-raw.json` — machine-readable finding records.

### Code sites (this phase's surface)
- `weatherbot/cli.py:986` — `run` command; `cli.py:569` `_load_config_reporting`
  (the load path that skips full validation).
- `weatherbot/config/loader.py:67` `assert_unique_names`, `:99`
  `validate_config_and_templates` (the shared offline validator to reuse in `run`).
- `weatherbot/ops/selfcheck.py:44-46` (reason constants), `:79-124`
  `run_self_check` (the `except Exception` at :116 that misclassifies config errors).
- `weatherbot/scheduler/daemon.py:1042` `_announce_schedule` (F90), `:392`
  `_forecast_failure_streaks` (F89), `:1108-1156` `gate_until_healthy`/
  `wait_ready_gate` (likely-dead app gate), `:1465` `ready_gate.run(stop)` (live path).
- `weatherbot/scheduler/wiring.py:305/315` — `ReadyGate` construction + the injected
  `on_fail`/`on_online` hooks (where the app-side fatal-stop wires in), and the F07
  ping-ordering site.
- `deploy/weatherbot.service:45-46` — `Restart=always`/`RestartSec=5` (change to
  `Restart=on-failure` + start-limit); `:27` `TimeoutStartSec=infinity` (KEEP).

### Cross-repo (hub)
- `../Reusable/YahirReusableBot/ECOSYSTEM.md` — cross-repo jurisdiction rules
  (hub tag cut + repin is human-gated). **Read before any hub-touching thought.**
- `../Reusable/YahirReusableBot/yahir_reusable_bot/lifecycle/ready_gate.py` — the
  hub `ReadyGate.run` loop (no fatal path; D-09/D-10).
- `.planning/HUB-FINDINGS-HANDOFF.md` — destination for the deferred `ReadyGate`
  fatal-outcome enhancement (D-10 hub half).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `validate_config_and_templates` (`config/loader.py:99`) — the ONE shared offline
  validator (TOML+schema+unique-names+template-tokens, zero network). `run` should
  call it exactly like `check-config` does (via `ReloadEngine.check`, `cli.py:958`).
- The alert spine (`record_alert`/`resolve_alert`, imported in `daemon.py`) exists
  if a DB-backed cooldown were ever wanted — NOT used here (D-04 chose systemd-layer
  bounding).
- `stamp_health` (`daemon.py`) — durable single-row health table already used on
  every probe outcome; reuse to stamp the fatal reason (D-02).
- `ReadyGate` hooks `on_fail(HealthResult)` / `on_online` + the `stop` Event
  (`wiring.py:315`) — the app-side extension points the fatal-stop rides (D-10).

### Established Patterns
- App owns classification; hub stays weather-noun-free. `selfcheck.to_health_result`
  maps app `reason` → neutral `Severity` for the hub gate. A new fatal reason must
  map to `Severity.CRITICAL` so the hub logs it critical.
- Interruptible `stop.wait(...)`, never `time.sleep` (Pitfall 2) — any new wait/exit
  must preserve prompt `systemctl stop`.
- Clean-failure contract: config problems fail with an actionable log line, never a
  raw traceback, and never echo secrets (relevant to the fatal alert `detail`).

### Integration Points
- `run()` (cli.py) → new boot-gate → `run_daemon` (the fail-fast seam).
- `run_daemon` composition root (`daemon.py` ~1380-1465) → `ready_gate.run(stop)`
  return-value branch (where the fatal marker is checked for exit code).
- `deploy/weatherbot.service` → live host `yahir-mint` (redeploy = Gate-2).

</code_context>

<specifics>
## Specific Ideas

- User's mental model, confirmed: run A (app-side fatal-stop) now AND fix the hub
  itself — captured as complementary (ship A; hub fix is a human-gated handoff).
- "Honest alerting" = the human actually hears about it on Discord AND the OS layer
  shows a failed unit — not one or the other. Both channels on a fatal.

</specifics>

<deferred>
## Deferred Ideas

- **Hub `ReadyGate` first-class fatal outcome** — the clean long-term design for
  D-10; human-gated hub tag cut. Log to `.planning/HUB-FINDINGS-HANDOFF.md`;
  WeatherBot repins after the next `YahirReusableBot` tag and can then de-hack the
  app-side `stop`-overload. NOT built in Phase 29.
- **Gate-2 (live host) obligation** — the `deploy/weatherbot.service` restart-policy
  change (D-05) only takes effect after a redeploy + `systemctl daemon-reload` on
  host `yahir-mint` (the live editable-installed daemon). Batched to milestone-close
  human UAT.
- Other v2.1 findings stay in their assigned phases (30–35) — correctness-first,
  cleanup-last; not pulled forward here (except F89, folded per D-13).

</deferred>

---

*Phase: 29-startup-validation-honest-alerting*
*Context gathered: 2026-07-08*
