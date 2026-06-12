---
phase: 05-deployment-reboot-survival
plan: 02
subsystem: infra
tags: [systemd, sd_notify, self-check, daemon, sigterm, reboot-survival, type-notify, ops-uat]

# Dependency graph
requires:
  - phase: 05-deployment-reboot-survival
    plan: 01
    provides: run_self_check / CheckResult / reason constants + SystemdNotifier.ready() + single-row health table / stamp_health
  - phase: 04-reliability
    provides: stop_event-interruptible sleep idiom (sleep=stop_event.wait) + heartbeat stamp_tick + is_auth_failure/is_transient classifiers
  - phase: 03-scheduler
    provides: run_daemon foreground lifecycle + SIGTERM handler + scheduler.start()/shutdown + _announce_schedule/_run_catchup
provides:
  - "run_daemon startup self-check GATE: classified self-check runs BEFORE scheduler.start(), never crash-loops on failure (D-04)"
  - "SIGTERM-interruptible re-probe loop (stop.wait(RE_PROBE_INTERVAL_S=120), no time.sleep, no sys.exit) — clean systemctl stop during the loop (Pitfall 2)"
  - "one-time three-part online signal: stamp_health(online) + stamp_tick + structured log + SystemdNotifier.ready()/READY=1 + one-time fixed-literal Discord ping (D-05/D-07)"
  - "deploy/weatherbot.service — Type=notify Restart=always TimeoutStartSec=infinity EnvironmentFile= After=/Wants=network-online.target non-root User= no WatchdogSec systemd unit (OPS-01)"
  - "deploy/README.md — install + .env-format + ExecStart uv-vs-venv decision + reboot-UAT + clean-stop deploy notes"
affects: [v1.0-milestone-close, ops-runbook]

# Tech tracking
tech-stack:
  added: []  # ZERO new dependencies — systemd is a host facility, sd_notify is stdlib from 05-01
  patterns:
    - "Startup gate-before-scheduler: a classified self-check loop runs to first-pass before scheduler.start(), so Type=notify READY=1 means 'config + key good', not 'process spawned'"
    - "Never-exit-on-failed-self-check: a dead process can't answer a future status query, so the daemon re-probes interruptibly forever instead of sys.exit (D-04)"
    - "SIGTERM-handler-before-gate ordering: the stop Event is wired before the re-probe loop so a systemctl stop mid-loop shuts down cleanly without starting the scheduler"
    - "Fixed-literal online ping (no template/user interpolation, no @mention) — markdown-injection-safe (T-05-T-02)"

key-files:
  created:
    - deploy/weatherbot.service
    - deploy/README.md
  modified:
    - weatherbot/scheduler/daemon.py
    - weatherbot/scheduler/__init__.py
    - tests/test_scheduler.py

key-decisions:
  - "RE_PROBE_INTERVAL_S = 120 (Claude's discretion per D-04, 60–300s band; documented as promotable to config, not added now)"
  - "SIGTERM handler MOVED to before gate_until_healthy (load-bearing ordering change, Pitfall 2) so a stop during the re-probe loop breaks stop.wait() and skips scheduler.start()"
  - "online signal fires exactly once because the gate returns immediately on first pass — no later-recovery path within one run_daemon call, so once-ness is structurally satisfied (D-05/D-07)"
  - "OPS-02 SC#3 (READY=1 reaches systemd only after self-check passes) CONFIRMED on host yahir-mint via journal ordering; OPS-01 SC#1 (reboot survival) DEFERRED at operator's request (would reboot their primary workstation) — service is enabled/configured to survive but post-reboot auto-start not yet observed"

requirements-completed: [OPS-02]
requirements-pending-uat: [OPS-01]

# Metrics
duration: post-checkpoint finalization
completed: 2026-06-11
---

# Phase 5 Plan 02: Daemon supervisor wiring + systemd unit + host UAT Summary

**Wired the Plan 05-01 foundation into `run_daemon` — a SIGTERM-interruptible startup self-check gate + re-probe loop that fires a one-time three-part online signal (health + heartbeat + log + READY=1 + Discord ping) only after the check first passes — and shipped the `Type=notify`/`Restart=always` systemd unit + deploy notes; the operator installed and ran the unit on host `yahir-mint`, confirming OPS-02 SC#3 (READY=1 reaches systemd only after the self-check passes) while deferring the live `sudo reboot` power-cycle test for OPS-01 SC#1.**

## Performance

- **Tasks:** 3 (2 code — DONE/committed pre-finalization; 1 blocking human-action checkpoint — APPROVED-with-deferral)
- **Files modified:** 5 (2 created in `deploy/`, 3 modified in `weatherbot/scheduler/` + `tests/`)
- **Full suite:** 184 tests passing; ruff clean (recorded at Task 1 completion)
- **Static lint:** `systemd-analyze verify deploy/weatherbot.service` clean

## Accomplishments

- `run_daemon` now runs the classified `run_self_check` BEFORE `scheduler.start()` (D-03): the daemon gates on config + key health and only enters the scheduler once the check first passes.
- Never-crash-loop re-probe loop: on any failure (including a genuine 401/403 `auth_failed`) the daemon logs (CRITICAL on auth, WARNING otherwise), stamps the health row on every outcome (D-08), and re-probes on an interruptible `stop.wait(RE_PROBE_INTERVAL_S=120)` — never `time.sleep`, never `sys.exit`/`raise` (D-04).
- Load-bearing SIGTERM-ordering change (Pitfall 2): the `signal.signal(signal.SIGTERM, ...)` handler is registered BEFORE the gate loop, so a `systemctl stop`/`restart` during the re-probe loop sets the stop Event, breaks the wait, and shuts down cleanly without ever starting the scheduler.
- One-time three-part online signal on first pass (D-05/D-07): `stamp_health(reason="online")` + `stamp_tick` heartbeat + `_log.info("weatherbot online", jobs=...)` + `SystemdNotifier.ready()` (READY=1, no-op when `NOTIFY_SOCKET` unset) + a one-time **fixed-literal** Discord "WeatherBot online — startup self-check passed." ping (no template/user interpolation, markdown-injection-safe, T-05-T-02). A non-ok ping `DeliveryResult` is logged but never blocks startup or re-fires.
- Shipped `deploy/weatherbot.service`: `Type=notify`, `NotifyAccess=main`, `Restart=always`, `RestartSec=5`, `TimeoutStartSec=infinity` (Pitfall 1 — the deferred-online gate can legitimately take minutes-to-hours without becoming a disguised crash-loop), absolute `ExecStart=`, `WorkingDirectory=`, `EnvironmentFile=`-only secrets, non-root `User=`, `After=`/`Wants=network-online.target`, `WantedBy=multi-user.target`, and **no** `WatchdogSec` (Pitfall 6).
- Shipped `deploy/README.md`: ExecStart uv-vs-venv decision (Open Question 1), `.env` lowest-common-denominator format (Pitfall 3), `chmod 600` + non-root security notes, install/enable sequence, reboot-UAT, and clean-stop check.

## Task Commits

1. **Task 1: startup self-check gate + re-probe loop + one-time online signal in `run_daemon`** — `c2d3e92` (feat) — `weatherbot/scheduler/daemon.py`, `weatherbot/scheduler/__init__.py` (lazy `run_daemon` exposure via PEP 562 `__getattr__`), `tests/test_scheduler.py` (gate_stop + online_once + auth-stays-alive; +439/−21). Full suite 184 passing, ruff clean.
2. **Task 2: `Type=notify` `Restart=always` systemd unit + deploy notes** — `1825bd9` (feat) — `deploy/weatherbot.service` (44 lines), `deploy/README.md` (131 lines). `systemd-analyze verify` clean (substituted-placeholder copy; raw `<REPO>` trips the absolute-path lint as documented).
3. **Task 3: real-host install + reboot UAT** — `checkpoint:human-action` (blocking). Operator ran it on host `yahir-mint` 2026-06-11 — **APPROVED WITH ONE DEFERRAL** (see Host UAT below).

Plus the post-checkpoint doc fix (this finalization):

4. **Doc fix: deploy README section 4 env-var verification** — `e1595bc` (docs) — corrected the false-alarm guidance (see Deviations).

## Host UAT (Task 3 checkpoint — host `yahir-mint`, 2026-06-11)

### Verified on host — PASSED

- `.venv/bin/python -m weatherbot --check` passed (config check passed, `locations=2`).
- Unit installed to `/etc/systemd/system/weatherbot.service`; `daemon-reload`, `enable --now` succeeded (symlink into `multi-user.target.wants` created).
- `systemctl status` → `active (running)`; `ExecStart` confirmed as the venv interpreter `/home/yahir/Projects/WeatherBot/.venv/bin/python -m weatherbot --run`.
- **OPS-02 SC#3 CONFIRMED:** journal ordering proves `[info] weatherbot online jobs=3` appears, THEN `systemd[1]: Started weatherbot.service` — i.e. systemd reaches `active` only AFTER the startup self-check passes and `READY=1` is sent. Secrets loaded correctly via `EnvironmentFile=` (the self-check probes OpenWeather with the key and passed). **OPS-02 / OPS-02 SC#3 is fully CONFIRMED on host.**

### Deferred — PENDING host UAT (not failed)

- **OPS-01 SC#1 (reboot survival):** the operator chose to defer the `sudo reboot` power-cycle test (it would reboot their primary workstation). The service is `enabled` (symlinked into `multi-user.target.wants`), so it is **configured** to survive reboot, but the actual post-reboot auto-start has NOT yet been observed. This is a deferred/pending host UAT, **not a failure**.

  **Exact verification commands to run after the next host reboot:**

  ```bash
  systemctl is-active weatherbot        # expect: active
  journalctl -u weatherbot -b | tail    # expect: the "weatherbot online" log post-boot
  ```

## Decisions Made

- `RE_PROBE_INTERVAL_S = 120` chosen within the D-04 60–300s band (Claude's discretion); documented as promotable to config but not added now.
- SIGTERM handler registration MOVED to before the gate loop (load-bearing, Pitfall 2) so a `systemctl stop` during the re-probe loop shuts down cleanly and never starts the scheduler.
- Online signal once-ness is structural: the gate returns immediately on first pass, so there is no "later recovery" path within a single `run_daemon` call — the signal naturally fires exactly once (D-05/D-07).
- OPS-02 closed (CONFIRMED on host); OPS-01 left **met-pending-reboot-UAT** rather than silently marked fully verified — the live power-cycle is the only remaining evidence and was deferred at the operator's request.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected `deploy/README.md` section 4 env-var verification (false-alarm guidance)**
- **Found during:** Task 2 / surfaced during the host UAT
- **Issue:** Section 4 instructed the operator to run `systemctl show -p Environment weatherbot` to confirm secrets loaded — but that property ONLY reflects inline `Environment=` directives, NOT `EnvironmentFile=` contents, so it always prints an empty `Environment=` for our unit (which uses `EnvironmentFile=` exclusively). This caused a false alarm during the UAT (the empty output looked like "the key didn't load").
- **Fix:** Section 4 now states the empty `Environment=` is EXPECTED, gives the correct proof (the `Type=notify` self-check reaching `active (running)` / the `weatherbot online` log is itself confirmation the key loaded, because the self-check probes OpenWeather and would classify `auth_failed` otherwise), and adds the root-only `/proc/<MainPID>/environ` direct check as an option. Also corrected the stale forward-reference in section 2.
- **Files modified:** `deploy/README.md`
- **Verification:** documentation-only; no code/test change.
- **Committed in:** `e1595bc` (docs(05-02), committed atomically before this finalization commit)

---

**Total deviations:** 1 auto-fixed (1 documentation accuracy fix surfaced by the host UAT). The two code tasks executed exactly as planned.

## Issues Encountered

None blocking. The only issue was the section-4 documentation inaccuracy above, surfaced by the host UAT and corrected.

## Known Stubs

None — no stubbed data paths. `RE_PROBE_INTERVAL_S` is a documented module constant (not a stub) and is intentionally not yet promoted to config.

## TDD Gate Compliance

Task 1 was `tdd="true"`: the gate_stop / online_once / auth-stays-alive tests were written and committed together with the implementation in `c2d3e92` per the sequential-executor convention. Full suite green (184) at task completion. Task 2 (systemd unit) is not unit-testable; it was statically gated via `systemd-analyze verify`.

## User Setup Required / Outstanding

- **One outstanding host UAT (deferred, not blocking the build):** OPS-01 SC#1 reboot survival. After the next reboot of host `yahir-mint`, run `systemctl is-active weatherbot` (expect `active`) and `journalctl -u weatherbot -b | tail` (expect the post-boot `weatherbot online` log) to close OPS-01 SC#1. The service is already `enabled` so no further install is required.

## Next Phase Readiness

- Phase 5 (the final v1.0 phase) is functionally complete: OPS-02 confirmed on host, OPS-01 built + installed + enabled and confirmed `active (running)`, with only the live reboot power-cycle deferred.
- **Do NOT run `/gsd-complete-milestone` claiming OPS-01 SC#1 fully verified** until the post-reboot UAT above is observed. OPS-01 is recorded as met-pending-reboot-UAT.

## Self-Check: PASSED
- FOUND: deploy/weatherbot.service
- FOUND: deploy/README.md
- FOUND commit: c2d3e92 (Task 1 — gate + re-probe loop + online signal)
- FOUND commit: 1825bd9 (Task 2 — systemd unit + deploy notes)
- FOUND commit: e1595bc (doc fix — README section 4)

---
*Phase: 05-deployment-reboot-survival*
*Completed (build): 2026-06-11 — OPS-01 SC#1 reboot UAT deferred/pending on host yahir-mint*
