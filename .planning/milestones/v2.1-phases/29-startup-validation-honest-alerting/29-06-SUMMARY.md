---
phase: 29-startup-validation-honest-alerting
plan: 06
subsystem: ops / deploy
tags: [systemd, restart-policy, crash-loop, hub-handoff, cross-repo]
requires:
  - "29-02 static service-unit directive tests (xfail RED contract)"
provides:
  - "deploy/weatherbot.service: Restart=on-failure + [Unit] start-limit (crash-loop bound)"
  - "HUB-FINDINGS-HANDOFF.md H18: deferred ReadyGate first-class fatal-outcome enhancement"
affects:
  - "yahir-mint live daemon (DEFERRED Gate-2: redeploy + daemon-reload not performed)"
  - "YahirReusableBot hub (DEFERRED: human-gated v0.1.2 tag cut)"
tech-stack:
  added: []
  patterns:
    - "StartLimit* MUST be in [Unit] (systemd silently ignores in [Service] — Pitfall 3)"
    - "Restart=on-failure exempts clean SIGTERM/exit-0; only fatal non-zero exit restarts"
key-files:
  created: []
  modified:
    - deploy/weatherbot.service
    - tests/test_service_unit.py
    - .planning/HUB-FINDINGS-HANDOFF.md
decisions:
  - "D-05: convert fatal config-exit crash-loop into a loud parked `failed` unit via on-failure + start-limit"
  - "D-06: live effect (redeploy + daemon-reload on yahir-mint) deferred to Gate-2 milestone close"
  - "D-10 (hub half): record ReadyGate fatal-outcome enhancement as human-gated hub handoff, not shipped"
metrics:
  duration_min: 3
  completed: 2026-07-08
status: complete
---

# Phase 29 Plan 06: systemd restart-policy hardening + hub handoff Summary

Bounded WeatherBot's fatal config-exit crash-loop at the OS layer by switching the systemd
unit to `Restart=on-failure` with a `[Unit]`-placed start-limit (5 restarts / 300s → parked
`failed`), keeping the transient slow-key path alive via the retained `TimeoutStartSec=infinity`;
flipped the three 29-02 static directive tests from `xfail` to standing green; and recorded the
deferred hub `ReadyGate` first-class-fatal-outcome enhancement in the handoff — no hub source
touched, no live daemon restarted.

## What Was Built

**Task 1 — `deploy/weatherbot.service` restart policy (D-05, HARD-STARTUP-02/03).** `commit c33a319`
- `[Service]`: `Restart=always` → `Restart=on-failure`. A clean `systemctl stop`/SIGTERM (exit 0)
  is now exempt from restart (requested-stop exemption); only a non-zero fatal exit restarts.
- `[Unit]`: added `StartLimitIntervalSec=300` + `StartLimitBurst=5`. Placed in `[Unit]`
  deliberately — systemd silently ignores `StartLimit*` in `[Service]` (Pitfall 3). 5 fatal
  restarts within 300s parks the unit `failed` instead of an infinite 5s crash-loop + infinite
  Discord alerts (D-04).
- KEPT `RestartSec=5` and `TimeoutStartSec=infinity` unchanged — the latter governs the
  never-exiting transient deferred-online re-probe path and is orthogonal to restart policy
  (Pitfall 2). Did not touch ExecStart / EnvironmentFile / User / RuntimeDirectory / placeholders.
- Red→green: removed the `xfail(strict=False)` markers (and the now-unused `_lands_in_29_06`
  marker + `pytest` import) from `tests/test_service_unit.py` so `test_service_restart_on_failure`,
  `test_service_start_limit_in_unit_section`, and `test_service_keeps_timeout_start_sec_infinity`
  are standing green directive gates.

**Task 2 — hub handoff append (D-10 hub half).** `commit 1aa3a66`
- Appended `### H18 — yahir_reusable_bot/lifecycle/ready_gate.py:run · medium · enhancement · lifecycle`
  to `.planning/HUB-FINDINGS-HANDOFF.md`: `ReadyGate.run` has no first-class fatal outcome, so
  WeatherBot overloads the `stop` Event + a fatal marker app-side; the clean long-term design is
  a distinct fatal outcome in the hub. Documented only — human-gated tag cut (v0.1.2). Names the
  app-side de-hack path for after repin (`wiring.py:_on_fail` fatal branch + `daemon.py`
  gate-return exit-code check). Updated the tally line: medium 4 → 5, total 17 → 18.

## Verification

- `uv run pytest tests/test_service_unit.py -x -q` → 3 passed (solid green, no xfail/xpass).
- `grep -c 'Restart=on-failure'` → 1; `grep -c 'Restart=always'` → 0.
- `StartLimitIntervalSec=300` + `StartLimitBurst=5` confirmed in `[Unit]` (before `[Service]`).
- `TimeoutStartSec=infinity` still present in `[Service]`.
- `grep -c 'ready_gate.py' .planning/HUB-FINDINGS-HANDOFF.md` → 1.
- Full suite: `787 passed, 10 xfailed, 1 xpassed` — **exit 0** (the xfails belong to 29-04/29-05,
  outside this plan).

## Deferred (Gate-2 / cross-repo obligations)

- **D-06 (Gate-2, milestone close):** the LIVE effect of the unit change — redeploy the file to
  host `yahir-mint` + `systemctl daemon-reload` + restart — was intentionally NOT performed this
  phase. No `systemctl`/`daemon-reload`/redeploy was run. Recorded as a deferred milestone-close
  human-UAT obligation.
- **D-10 hub half (human-gated):** the `ReadyGate` first-class fatal-outcome is documentation only
  in H18 — the upstream hub change + v0.1.2 tag cut + WeatherBot repin is a human step, not shipped
  here.

## Deviations from Plan

None — plan executed exactly as written.

## Cross-Repo Safety Confirmation

`git -C ../Reusable/YahirReusableBot status --porcelain` shows this plan changed no hub source
(pre-existing untracked/`uv.lock` noise is unrelated). ECOSYSTEM human-gated rule honored (T-29-09).

## Self-Check: PASSED
- FOUND: deploy/weatherbot.service (Restart=on-failure, StartLimit* in [Unit], TimeoutStartSec kept)
- FOUND: tests/test_service_unit.py (3 tests de-xfailed, green)
- FOUND: .planning/HUB-FINDINGS-HANDOFF.md (H18 appended, tally 18)
- FOUND commit: c33a319 (Task 1)
- FOUND commit: 1aa3a66 (Task 2)
