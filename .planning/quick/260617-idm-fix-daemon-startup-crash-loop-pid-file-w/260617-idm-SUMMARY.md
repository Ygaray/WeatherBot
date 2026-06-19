---
phase: quick-260617-idm
plan: 01
status: complete
subsystem: ops/daemon-lifecycle
tags: [pidfile, systemd, runtime-dir, crash-loop, uat-fix, OPS-01, CFG-02]
requires:
  - "weatherbot/ops/pidfile.py PID_FILE constant (Phase 9-05)"
  - "deploy/weatherbot.service Type=notify unit (Phase 5)"
provides:
  - "Non-root daemon writes its PID into user-owned /run/weatherbot/ — no PermissionError crash-loop on restart"
  - "systemd RuntimeDirectory=weatherbot creates the writable per-service runtime dir"
affects:
  - "deploy/weatherbot.service (installed unit needs root re-copy)"
  - "weatherbot/cli.py + weatherbot/scheduler/daemon.py (both track PID_FILE automatically — unchanged)"
tech-stack:
  added: []
  patterns:
    - "systemd RuntimeDirectory= as the load-bearing mechanism for non-root PID-file writability"
key-files:
  created: []
  modified:
    - weatherbot/ops/pidfile.py
    - tests/conftest.py
    - tests/test_reload.py
    - deploy/weatherbot.service
    - deploy/README.md
decisions:
  - "PID_FILE default moved /run/weatherbot.pid -> /run/weatherbot/weatherbot.pid (inside RuntimeDirectory=weatherbot)"
  - "RuntimeDirectory=weatherbot (not StateDirectory/tmpfiles.d) is the writability mechanism — ephemeral PID matches /run semantics, auto-removed on stop"
  - "Override-parameter API (write_pid_atomic/read_pid pid_file=) left untouched — tests inject tmp paths"
metrics:
  duration: ~6 min
  completed: 2026-06-17
---

# Quick Task 260617-idm: Fix Daemon Startup Crash-Loop (PID-File Writability) Summary

Pointed the daemon's default `PID_FILE` at `/run/weatherbot/weatherbot.pid` and added
`RuntimeDirectory=weatherbot` to the systemd unit so the non-root (`User=<USER>`) daemon
can write its PID file without the `PermissionError [Errno 13]` that was crash-looping
`systemctl restart` against root-owned bare `/run`.

## ⚠️ MANUAL ROOT FOLLOW-UP REQUIRED (the agent cannot and did NOT run sudo)

The fix is complete in the repo, but the **already-deployed** unit at
`/etc/systemd/system/weatherbot.service` predates the `RuntimeDirectory=` line. Until it is
re-copied, systemd will NOT create `/run/weatherbot/` and the daemon's PID-file write will
still fail on the host. Run AS ROOT on the host (`yahir-mint`):

```bash
sudo cp deploy/weatherbot.service /etc/systemd/system/weatherbot.service
sudo systemctl daemon-reload
sudo systemctl restart weatherbot.service
systemctl status weatherbot.service   # expect active (running), no PermissionError crash-loop
ls -ld /run/weatherbot                  # dir exists, owned by the service user
cat /run/weatherbot/weatherbot.pid      # holds the live daemon PID
```

This is documented in `deploy/README.md` section "3c. Redeploy after the PID-runtime-dir fix".

## What Was Done

### Task 1 — Point PID_FILE at the systemd runtime dir (TDD) — commit `c1f6ad7`
- RED: added `test_default_pid_file_is_under_service_runtime_dir` in `tests/test_reload.py`
  (section 9c) asserting `PID_FILE == Path("/run/weatherbot/weatherbot.pid")` and
  `PID_FILE.parent.name == "weatherbot"`; confirmed it failed against the old
  `/run/weatherbot.pid` default.
- GREEN: changed the `PID_FILE` constant in `weatherbot/ops/pidfile.py` from
  `Path("/run/weatherbot.pid")` to `Path("/run/weatherbot/weatherbot.pid")` and rewrote
  its comment to explain the `RuntimeDirectory=weatherbot` pairing (the `parent.mkdir`
  in `write_pid_atomic` stays as a graceful fallback, no longer load-bearing).
- Refreshed the stale `tests/conftest.py` redirect-fixture docstring (default path text).
- Verified (not edited) that `weatherbot/cli.py` (reload sender, lines 49/465/640-641) and
  `weatherbot/scheduler/daemon.py` (writer, lines 67/1117/1287) both read the shared
  `PID_FILE` constant, so writer and reader track the new path automatically.
- `write_pid_atomic` / `read_pid` signatures and `pid_file=` override behavior unchanged;
  existing pidfile override tests (test_reload.py ~497-562) stay green.

### Task 2 — Add RuntimeDirectory to the unit + document root re-install — commit `5dcec80`
- `deploy/weatherbot.service`: added `RuntimeDirectory=weatherbot` under `[Service]` next to
  `User=`/`Restart=`, with an explanatory comment in the unit's existing commented style.
  `<REPO>`/`<USER>` placeholder template convention preserved (8 occurrences intact).
- `deploy/README.md`: added section "3c. Redeploy after the PID-runtime-dir fix" with the
  `sudo cp ... && sudo systemctl daemon-reload && restart` block, matching the style of
  sections 3 and 3b, and a note that without it `/run/weatherbot/` won't be created.

## Verification

- `uv run pytest -q` (full suite): **291 passed, 1 warning** (the warning is a pre-existing,
  unrelated `audioop` DeprecationWarning from discord.py — out of scope).
- `grep -rn "/run/weatherbot.pid" --include="*.py" weatherbot/` (non-comment): no matches.
- `deploy/weatherbot.service` contains `RuntimeDirectory=weatherbot`.
- `deploy/README.md` documents the root-only re-install + daemon-reload + restart.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- All 5 modified files exist on disk.
- Commits c1f6ad7 (Task 1) and 5dcec80 (Task 2) exist in git history.
- `weatherbot/ops/pidfile.py` contains `Path("/run/weatherbot/weatherbot.pid")`.
