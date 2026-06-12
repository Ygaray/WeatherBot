---
phase: 5
slug: deployment-reboot-survival
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-11
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 05-RESEARCH.md §"Validation Architecture". Requirements: OPS-01, OPS-02.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (+ `time-machine` for time control; both in `[dependency-groups].dev`) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`) |
| **Quick run command** | `uv run pytest tests/test_ops_selfcheck.py tests/test_sdnotify.py tests/test_daemon.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~15–30 seconds |

---

## Sampling Rate

- **After every task commit:** Run the matching quick-run command for the touched file.
- **After every plan wave:** Run `uv run pytest`.
- **Before `/gsd-verify-work`:** Full suite green + `systemd-analyze verify deploy/weatherbot.service` clean + a real host reboot UAT (OPS-01 SC#1).
- **Max feedback latency:** ~30 seconds (unit); the reboot UAT is manual-only.

---

## Per-Task Verification Map

> Task IDs are provisional (planner finalizes plan/wave split). Mapped to requirement + secure behavior + automated command.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-xx | 01 | 1 | OPS-02 | T-05-ID | Probe transient error → `network_not_ready` (no secret in detail) | unit | `uv run pytest tests/test_ops_selfcheck.py -k transient -x` | ❌ W0 | ⬜ pending |
| 05-01-xx | 01 | 1 | OPS-02 | T-05-ID | 401/403 → `auth_failed`, key never logged | unit | `uv run pytest tests/test_ops_selfcheck.py -k auth -x` | ❌ W0 | ⬜ pending |
| 05-01-xx | 01 | 1 | OPS-02 | — | `sd_notify` no-op when `NOTIFY_SOCKET` unset; sends `READY=1` when set | unit | `uv run pytest tests/test_sdnotify.py -x` | ❌ W0 | ⬜ pending |
| 05-01-xx | 01 | 1 | OPS-02 | T-05-ID | `stamp_health` upserts single `health` row (reason/detail, no secret) | unit | `uv run pytest tests/test_store.py -k health -x` | ❌ W0 | ⬜ pending |
| 05-02-xx | 02 | 2 | OPS-02 | T-05-DoS | Re-probe loop stays alive on failure, exits cleanly when `stop` set | unit | `uv run pytest tests/test_daemon.py -k gate_stop -x` | ❌ W0 | ⬜ pending |
| 05-02-xx | 02 | 2 | OPS-02 | — | Online signal fires exactly once (log+stamp+ready+ping); not re-fired | unit | `uv run pytest tests/test_daemon.py -k online_once -x` | ❌ W0 | ⬜ pending |
| 05-02-xx | 02 | 2 | OPS-01 | T-05-IPC/EoP | Unit correctness (`Type=notify`, `Restart=always`, `After=/Wants=network-online.target`, `User=` non-root, no secrets) | manual + lint | `systemd-analyze verify deploy/weatherbot.service` + reboot UAT | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_ops_selfcheck.py` — classified self-check (transient / auth / pass), mocking the injected client to raise `httpx` errors / return ok. Covers OPS-02.
- [ ] `tests/test_sdnotify.py` — bind a throwaway `AF_UNIX`/`SOCK_DGRAM` socket, set `NOTIFY_SOCKET`, assert `READY=1` received; assert no-op + no error when unset. Covers OPS-02.
- [ ] Extend `tests/test_daemon.py` — re-probe loop stays alive + breaks on `stop.set()`; online-signal-once; SIGTERM-during-gate clean shutdown.
- [ ] Extend store tests (`tests/test_store.py`) — `stamp_health` single-row upsert.
- [ ] `systemd-analyze verify deploy/weatherbot.service` as a non-pytest lint gate (statically verifies the unit; can't be unit-tested in CI).

*No new framework install needed — pytest + time-machine already present.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Auto-restart after host reboot under systemd | OPS-01 (SC#1) | Real reboot survival can only be confirmed on the target host | Install the unit (`systemctl enable --now weatherbot`), reboot the host, confirm `systemctl is-active weatherbot` returns `active` and an "online" signal appears without manual intervention |
| `READY=1` reaches systemd after self-check passes | OPS-02 (SC#3) | Requires a live systemd `Type=notify` supervisor | `systemctl start weatherbot`; confirm unit reaches `active (running)` only after the self-check passes (not immediately on spawn); `systemctl show -p StatusText` if set |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
