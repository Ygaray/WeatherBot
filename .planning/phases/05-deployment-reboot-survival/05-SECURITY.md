---
phase: 05
slug: deployment-reboot-survival
status: secured
threats_open: 0
threats_closed: 14
asvs_level: 1
created: 2026-06-15
---

# SECURITY.md — Phase 05 Deployment / Reboot Survival

**Phase:** 05 — deployment-reboot-survival
**ASVS Level:** 1
**block_on:** high
**Audit date:** 2026-06-15
**Disposition (all threats):** mitigate
**Result:** SECURED — 14/14 threats CLOSED, 0 open, 0 unregistered flags

The register was authored at plan time. Each declared mitigation was verified against
the implemented code by grep + read at the cited file:line. Documentation/intent was
NOT accepted as evidence; every CLOSED row points at the actual code construct.

---

## Threat Verification (all CLOSED)

| Threat ID | Category | Disposition | Evidence (file:line) |
|-----------|----------|-------------|----------------------|
| T-05-ID-01 | Information Disclosure | mitigate | `weatherbot/weather/store.py:137-144` health table: `detail TEXT` documented outcome-only; `:439-442` parameterized `UPDATE health SET reason=?, detail=?, updated_at_utc=? WHERE id=1`. Callers pass only `result.reason`/`result.detail` (status code or `type(exc).__name__`) — `selfcheck.py:108,112,117`. No key/webhook substring written. |
| T-05-ID-02 | Information Disclosure | mitigate | `weatherbot/cli.py:342-350` auth-failure message echoes only `result.detail` (HTTP status code, e.g. "401") + fixed wording; no key/URL/`appid`/params interpolated. `selfcheck.py:103-109` sets `detail=str(exc.response.status_code)` only. |
| T-05-T-01 | Tampering | mitigate | `weatherbot/weather/store.py:439-442` parameterized `UPDATE ... WHERE id=1` with bound tuple `(reason, detail, now)`; no f-string into SQL (docstring T-03-01 at `:433-434`). |
| T-05-T-02 | Tampering | mitigate | `weatherbot/scheduler/daemon.py:528` `channel.send("WeatherBot online — startup self-check passed.")` — FIXED string literal, no template/user/`config` interpolation, no `@everyone`/mention. Plan 05-03 fallback (`:568-574`) only constructs the channel; it did NOT alter the ping literal — T-05-T-02 unweakened. |
| T-05-ID-03 | Information Disclosure | mitigate | `deploy/weatherbot.service:32-34` secrets via `EnvironmentFile=<REPO>/.env` only; no inline `Environment=KEY=...` anywhere in the unit. `deploy/README.md:47-51` documents `chmod 600 .env` + EnvironmentFile-only. Daemon logging is outcome-only (`daemon.py:485-495,525,530`). |
| T-05-DoS-01 | DoS (self) | mitigate | `weatherbot/ops/selfcheck.py:103-117` classifies 401/403 → `auth_failed`, non-auth HTTPStatusError (429/5xx) → `network_not_ready`, broad `Exception` (connect/timeout/DNS) → `network_not_ready`; reuses `is_auth_failure`/`is_transient` (`:35`). Transient never misclassified as fatal — gate re-probes (`daemon.py:478-500`). |
| T-05-DoS-02 | DoS (self) | mitigate | `deploy/weatherbot.service:27` `TimeoutStartSec=infinity` — deferred-online gate cannot become a disguised crash-loop with `Restart=always`. |
| T-05-DoS-03 | DoS (self) | mitigate | First-boot DNS/connect errors hit the broad `except Exception` in `selfcheck.py:113-117` → `network_not_ready`; gate `daemon.py:478-500` waits and re-probes instead of treating `network-online.target` as "internet up". |
| T-05-DoS-04 | DoS (self) | mitigate | `weatherbot/scheduler/daemon.py:452-500` `gate_until_healthy` — no `sys.exit`/`raise` on a failed self-check; loop logs (CRITICAL on auth `:485`, WARNING otherwise `:491`) and re-probes; returns True only on pass. Verified no `sys.exit` in the gate region. |
| T-05-DoS-05 | DoS (self) | mitigate | `deploy/weatherbot.service` — NO `WatchdogSec` directive present (absence confirmed by full-file read; comment at `:39-40` documents the deliberate omission, Pitfall 6). |
| T-05-DoS-06 | DoS (self) | mitigate | `weatherbot/scheduler/daemon.py:623` `signal.signal(signal.SIGTERM, _handle)` registered BEFORE `gate_until_healthy` (`:631`) and before `scheduler.start()` (`:640`). Gate blocks on `stop.wait(RE_PROBE_INTERVAL_S)` (`:498`) — a `systemctl stop` sets `stop` and breaks immediately; no `time.sleep` in the gate. |
| T-05-EoP | Elevation of Privilege | mitigate | `deploy/weatherbot.service:36` `User=<USER>` (non-root placeholder); `:35` comment + `deploy/README.md:41` mandate a non-root owner (V4 least privilege). |
| T-05-SC | Supply Chain (Tampering) | mitigate | `pyproject.toml:6-13` dependencies = apscheduler/discord-webhook/httpx/pydantic/pydantic-settings/structlog/tenacity only — ZERO new packages this phase. No `sdnotify`/`systemd-python` in `pyproject.toml` or `uv.lock` (both grepped, no match). sd_notify is pure stdlib (`ops/sdnotify.py:18-19` imports only `os`,`socket`). |

---

## Unregistered Flags

None. None of the three plan SUMMARY files (05-01/05-02/05-03) contain a
`## Threat Flags` section, and no new attack surface appeared during implementation
that lacks a register mapping.

---

## Plan 05-03 (gap-closure) re-check — T-05-T-02 integrity

Constraint from the audit request: confirm the 05-03 fix (run_daemon builds the
channel from settings when `channel is None`) did not weaken T-05-T-02.

- `daemon.py:568-574` only *constructs* the delivery channel via `build_channel(config, settings)`.
- The online ping text at `daemon.py:528` remains the exact fixed literal
  `"WeatherBot online — startup self-check passed."` with no interpolation.
- `emit_online`'s `if channel is not None` guard (`:527`) and best-effort warning
  (`:529-531`) are unchanged.

T-05-T-02 remains CLOSED and unweakened.

---

## Accepted Risks Log

None. All threats in the register carry disposition `mitigate` and are verified CLOSED.

## Notes (non-blocking, informational)

- OPS-01 SC#1 (live post-reboot auto-start) is recorded in 05-02-SUMMARY as a deferred
  *operational* host UAT, not a code mitigation. It does not map to any open threat in
  the register and is therefore not a security blocker for this audit.
