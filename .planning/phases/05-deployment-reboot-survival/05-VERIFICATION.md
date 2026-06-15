---
phase: 05-deployment-reboot-survival
verified: 2026-06-11T00:00:00Z
status: passed
score: 17/17 must-haves verified (16 code + 1 live observation)
overrides_applied: 0
human_verification_resolved: "OPS-01 SC#1 live host-reboot power-cycle CONFIRMED by operator 2026-06-15 on host yahir-mint: after `sudo reboot`, `systemctl is-active weatherbot` returned `active` and the post-boot journal showed the `weatherbot online` log. The previously-deferred observation is now directly observed; all 3 OPS-01 success criteria hold."
human_verification: []
---

# Phase 5: Deployment & Reboot Survival Verification Report

**Phase Goal:** The bot runs as a supervised long-running process that comes back automatically after a crash or host reboot and announces itself online only after confirming its config and API key are good.
**Verified:** 2026-06-11
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal decomposes into three roadmap Success Criteria. SC#2 (distinguishable
self-check) and SC#3 (online signal) are fully verified in code AND confirmed on host
`yahir-mint` (journal ordering proves READY=1 reaches systemd only after the self-check
passes). SC#1 (live reboot survival) is code-complete, installed, enabled, and confirmed
`active (running)` — only the live `sudo reboot` power-cycle observation is outstanding
(operator-deferred), routed to human verification.

### Observable Truths

**Roadmap Success Criteria (the contract):**

| #   | Truth (Roadmap SC) | Status | Evidence |
| --- | ------------------ | ------ | -------- |
| R1  | After a host reboot the bot restarts automatically under a supervisor without manual intervention (OPS-01 SC#1) | ? UNCERTAIN (human) | `deploy/weatherbot.service` ships `Restart=always` + `[Install] WantedBy=multi-user.target`; on host the unit is `enable`d (symlinked into multi-user.target.wants) and `active (running)`. Live `sudo reboot` observation deferred by operator → human_verification. |
| R2  | On startup the bot self-checks config + key reachability, failing loudly and distinguishably (key-not-yet-active vs genuine auth error) (OPS-02 SC#2) | ✓ VERIFIED | `run_self_check` (selfcheck.py:62) classifies online/network_not_ready/auth_failed via Phase-4 `is_auth_failure`/`is_transient`; `do_check` (cli.py:339-350) emits the distinct "subscription may not be active or not yet propagated" wording on auth_failed; daemon logs CRITICAL on auth vs WARNING otherwise (daemon.py:484-495). Tests for transient/401/403/429/5xx/pass all green. |
| R3  | On a healthy start the bot emits an "online" signal so a silent death is detectable (OPS-02 SC#3) | ✓ VERIFIED | `emit_online` (daemon.py:503) fires once: stamp_health(online)+stamp_tick+log+`ready()` READY=1+one-time Discord ping. Confirmed on host: journal shows `weatherbot online` THEN `Started weatherbot.service` (READY=1 only after self-check passes). `test_online_once` asserts exactly-once. |

**PLAN frontmatter must-haves (plan-specific detail):**

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | Classified self-check returns network_not_ready for transient/connection error (D-06) | ✓ VERIFIED | selfcheck.py:113-117 + test_ops_selfcheck transient case green |
| 2   | Returns auth_failed for 401/403, reusing key-not-active wording (D-03/D-06) | ✓ VERIFIED | selfcheck.py:104-109; cli.py:339-350 wording; test green |
| 3   | Clean probe returns ok=True reason=online | ✓ VERIFIED | selfcheck.py:119; test green |
| 4   | sd_notify silent no-op when NOTIFY_SOCKET unset; READY=1 AF_UNIX/SOCK_DGRAM when set (D-05) | ✓ VERIFIED | sdnotify.py:38-51 (stdlib only, `\0` abstract fixup, OSError swallowed); behavioral no-op check + test_sdnotify green |
| 5   | Single-row health table records latest reason/detail/timestamp, no secret leakage (D-08) | ✓ VERIFIED | store.py:137-144 (CHECK id=1 + INSERT OR IGNORE seed), stamp_health:424-443 parameterized UPDATE; no-secret test green |
| 6   | do_check delegates to shared self-check engine (D-03) | ✓ VERIFIED | cli.py:337 `run_self_check(...)`; --check surface preserved (retry budget echo, deliver-nothing guard) |
| 7   | Daemon runs classified self-check BEFORE scheduler.start() (D-03) | ✓ VERIFIED | gate_until_healthy:607 precedes scheduler.start():616 |
| 8   | On failure daemon stays alive + re-probes interruptibly, never crash-loops, incl. genuine 401/403 (D-04) | ✓ VERIFIED | gate loop daemon.py:478-500 — no sys.exit/raise, stamp_health every outcome, CRITICAL on auth; `test_gate_auth_failed_then_ok_stays_alive` green |
| 9   | SIGTERM handler registered BEFORE the re-probe loop (Pitfall 2) | ✓ VERIFIED | signal.signal(SIGTERM):599 precedes gate_until_healthy:607; `test_gate_stop_stays_alive_then_clean_exit_no_online` green |
| 10  | Once self-check first passes, online signal fires exactly once (log+health+tick+READY=1+one ping) (D-05/D-07) | ✓ VERIFIED | emit_online:503-533; `test_online_once` asserts ready==[1], send len==1, health==online |
| 11  | systemd unit runs `--run` with Restart=always + EnvironmentFile=, no Docker (D-01) | ✓ VERIFIED | deploy/weatherbot.service: Restart=always, EnvironmentFile=, ExecStart `weatherbot --run` |
| 12  | Unit declares Type=notify, Restart=always, EnvironmentFile=, After/Wants=network-online.target, TimeoutStartSec=infinity, non-root User=, NO WatchdogSec, passes systemd-analyze verify | ✓ VERIFIED | All 11 required directives present; no `^WatchdogSec` directive (only a comment); no inline `Environment=` secret; systemd-analyze verify clean (only benign "/usr/bin/uv not on this host" note — venv ExecStart used+confirmed on deploy host) |
| 13  | After a host reboot the bot restarts automatically under systemd (OPS-01 SC#1) | ? UNCERTAIN (human) | Same as R1 — code/config complete, enabled+active on host, live reboot observation deferred |

**Score:** 16/16 must-have code/config truths VERIFIED; 1 live observation (R1/#13) routed to human.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `weatherbot/ops/selfcheck.py` | run_self_check + CheckResult + reason constants | ✓ VERIFIED | 119 lines, substantive, imported by cli.py + daemon.py |
| `weatherbot/ops/sdnotify.py` | SystemdNotifier.ready() stdlib READY=1, no-op when unset | ✓ VERIFIED | stdlib os/socket only, `\0` fixup, OSError swallowed |
| `weatherbot/ops/__init__.py` | ops package re-export surface | ✓ VERIFIED | `__all__` exports SystemdNotifier/run_self_check/CheckResult/reason constants |
| `weatherbot/weather/store.py` | health table in _SCHEMA + stamp_health | ✓ VERIFIED | additive single-row table + parameterized upsert |
| `weatherbot/scheduler/daemon.py` | gate + re-probe loop + one-time online signal | ✓ VERIFIED | gate_until_healthy + emit_online wired into run_daemon |
| `deploy/weatherbot.service` | Type=notify reboot-surviving unit | ✓ VERIFIED | all directives present; static-verify clean |
| `deploy/README.md` | install + reboot-UAT + .env-format notes | ✓ VERIFIED | install seq, ExecStart uv-vs-venv, .env format, reboot UAT, clean-stop |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| cli.py::do_check | selfcheck.py::run_self_check | shared engine call | ✓ WIRED | cli.py:337 |
| daemon.py::run_daemon | selfcheck.py::run_self_check | startup gate before scheduler.start() | ✓ WIRED | via gate_until_healthy:479, before start:616 |
| daemon.py::run_daemon | sdnotify.py::SystemdNotifier | READY=1 on first pass | ✓ WIRED | emit_online:526 `notifier.ready()` |
| daemon.py::run_daemon | store.py::stamp_health | health stamp every outcome + online | ✓ WIRED | gate:481, emit_online:523 |
| selfcheck.py | reliability | is_transient/is_auth_failure import | ✓ WIRED | selfcheck.py:35 |
| deploy/weatherbot.service | weatherbot --run | absolute ExecStart | ✓ WIRED | ExecStart=/usr/bin/uv run weatherbot --run (+ venv alt documented/used on host) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| ops + daemon symbols import | `python -c "from weatherbot.ops import ...; from weatherbot.scheduler.daemon import ..."` | imports OK; RE_PROBE_INTERVAL_S=120 | ✓ PASS |
| sd_notify no-op when NOTIFY_SOCKET unset | `python -c "SystemdNotifier().ready()"` | no-op, no raise | ✓ PASS |
| systemd unit static lint | `systemd-analyze verify` (placeholders substituted) | clean (only benign uv-not-on-this-host note) | ✓ PASS |
| Phase 5 test files | `pytest test_ops_selfcheck test_sdnotify test_store test_scheduler` | 51 passed | ✓ PASS |
| Full suite | `uv run pytest` | 184 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| OPS-02 | 05-01, 05-02 | Startup self-check (config valid + key reachable) + "online" signal | ✓ SATISFIED | run_self_check + emit_online; confirmed on host (journal ordering) |
| OPS-01 | 05-02 | Long-running supervised process surviving crashes + reboot | ? NEEDS HUMAN | Restart=always unit built/installed/enabled/active; live reboot observation deferred |

Both PLAN-declared requirement IDs (OPS-01, OPS-02) are accounted for. REQUIREMENTS.md
maps exactly OPS-01 + OPS-02 to Phase 5 — no orphaned requirements. OPS-01 is recorded as
"Met (pending reboot UAT)" in REQUIREMENTS.md traceability, consistent with this finding.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | None | — | No debt markers (TBD/FIXME/XXX) in any phase-5 file. No stubs/hardcoded-empty data paths. RE_PROBE_INTERVAL_S=120 is a documented constant, not a stub. |

### Human Verification Required

#### 1. Live host-reboot power-cycle survival (OPS-01 SC#1)

**Test:** On host `yahir-mint`, run `sudo reboot`. After the host comes back, WITHOUT touching anything, run `systemctl is-active weatherbot` and `journalctl -u weatherbot -b | tail`.
**Expected:** `systemctl is-active weatherbot` returns `active`; the journal shows a post-boot `weatherbot online` log (and the one-time Discord online ping reappears).
**Why human:** The code and systemd config for reboot survival are complete and present; the service is `enabled` (symlinked into `multi-user.target.wants`) so it is configured to auto-start on boot, and was confirmed `active (running)`. Only the live power-cycle observation remains — deferred by the operator because it would reboot their primary workstation. This is a pending observation, not a code gap.

### Gaps Summary

No code gaps. All 16 implementation/config must-haves are verified in the codebase, the
full test suite (184) passes, the systemd unit passes static verification, and OPS-02 is
confirmed on the real host via journal ordering. The single outstanding item is the live
`sudo reboot` observation for OPS-01 SC#1 — the implementation and systemd configuration
for reboot survival are complete; only the direct observation of post-reboot auto-start
has not yet been performed. Status is `human_needed` (not `gaps_found`).

---

_Verified: 2026-06-11_
_Verifier: Claude (gsd-verifier)_
