# Phase 5: Deployment & Reboot Survival - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-11
**Phase:** 5-Deployment & Reboot Survival
**Areas discussed:** Supervisor target, Startup self-check & failure behavior, Online signal shape, Reboot network-readiness, Permanent-auth-failure behavior, Online signal timing, Discord ping anti-spam

---

## Supervisor target (OPS-01)

| Option | Description | Selected |
|--------|-------------|----------|
| systemd unit | .service file w/ Restart=always + EnvironmentFile=.env, runs `weatherbot --run`. CLAUDE.md's lightest-reliable Pi/server recommendation. | ✓ |
| Docker + compose | Dockerfile + compose w/ restart: always. Portable; heavier on a Pi. | |
| Both | Ship systemd AND Docker. More to build/verify. | |

**User's choice:** systemd unit
**Notes:** Matches the always-on Pi/personal-host deploy frame in CLAUDE.md/PROJECT.md.

---

## Startup self-check & failure behavior (OPS-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Self-check in daemon, exit nonzero on fail | Daemon runs do_check at startup; exits nonzero so supervisor retries. Crash-loops on not-yet-active key. | |
| Self-check, but stay up & retry internally | Daemon self-checks; on transient/key-not-active failure stays alive and re-probes; only exits on genuine permanent auth error. | ✓ |
| Operator runs --check separately | Daemon does not self-check; relies on operator/deploy script. | |

**User's choice:** Self-check, but stay up & retry internally
**Notes:** Refined further below — on a *genuine permanent* auth error the daemon ALSO stays alive (does not exit), per the reachability intent.

---

## Online signal shape (OPS-02 SC#3)

| Option | Description | Selected |
|--------|-------------|----------|
| Log + DB row (monitoring-bot frame) | Structured `online`/`started` event + durable DB stamp; Phase 4 future-monitoring-bot frame. | ✓ (all three) |
| systemd sd_notify (Type=notify) | Daemon sends READY=1 after self-check passes; systemctl status tracks readiness. | ✓ (all three) |
| Human-facing ping (Discord post) | Post 'I'm online' to the Discord webhook on healthy start. | ✓ (all three) |

**User's choice:** All three
**Notes:** User wants redundant detectability of a healthy start — machine (log+DB), systemd-native (sd_notify), and immediate human visibility (Discord).

---

## Reboot network-readiness

| Option | Description | Selected |
|--------|-------------|----------|
| After=network-online.target + treat net errors as transient | Unit waits for network-online; startup probe classifies connection/timeout errors as 'not ready' (retry) vs 401/403 bad key (fail loud). | ✓ |
| Ordering only, no special net handling | Add After=network-online.target but treat any probe failure uniformly. | |
| You decide | Planner picks the standard approach. | |

**User's choice:** After=network-online.target + treat net errors as transient

---

## Permanent-auth-failure behavior (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Stay up, log CRITICAL, keep re-probing | Never exit on auth failure; log CRITICAL + durable row; keep re-probing forever. Process stays alive & detectable. | ✓ (via free-text) |
| Exit nonzero, let supervisor crash-loop | Treat bad key as fatal; supervisor crash-loops until fixed. | |
| Stay up, but stop re-probing after N attempts | Bounded re-probe then sit idle-but-alive. | |

**User's choice (free text):** *"i want the bot to still be reachable thru discord, eventually we will implement a parser so id like to for example send 'status' thru discord, the bot reads and tells me which error he is experiencing if possible"*
**Notes:** Maps to "stay up, log CRITICAL, keep re-probing" — the process must remain alive/reachable so a future inbound-`status` command can query its current error state. Confirmed by user: the inbound-`status` command is a deferred new capability (needs a Discord gateway bot, not the current webhook); Phase 5 only lays the seam by persisting current health/error state to the DB (CONTEXT D-08).

---

## Online signal timing (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Once, after first successful self-check (deferred if needed) | Online fires once per process start, only after self-check first passes; deferred until re-probe succeeds if startup probe fails. sd_notify READY=1 waits for this gate. | ✓ |
| Immediately on process start, regardless of self-check | Emit online as soon as process is up. Weaker OPS-02 guarantee. | |

**User's choice:** Once, after first successful self-check (deferred if needed)

---

## Discord ping anti-spam (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Once per process start only | Post 'online' once when a freshly-started process passes self-check; re-probe recoveries don't re-post. | ✓ |
| Suppress if restarted recently (cooldown) | Post on start but suppress within a cooldown window. Needs cooldown + persisted timestamp. | |
| You decide | Planner picks standard anti-spam handling. | |

**User's choice:** Once per process start only

---

## Claude's Discretion

- Self-check re-probe interval (sensible default, may promote to config later).
- systemd unit filename, `User=`/`WorkingDirectory=`/`RestartSec=` values, install instructions.
- Health/status row table/column names + online-event key (follow store conventions).
- Transient-vs-permanent probe classification details (reuse Phase 4 `is_transient`/`is_auth_failure`).
- Whether the online stamp reuses `heartbeat` or a dedicated health/status row.
- Whether `sd_notify` uses a tiny direct `NOTIFY_SOCKET` write vs a dependency.

## Deferred Ideas

- Inbound Discord `status` command (gateway bot + bot token; reads the D-08 health row). Future phase.
- Docker / container deployment. Not v1.
- Promoting re-probe interval to config.
- Routing the online/health log event to journald→email / external monitoring (future monitoring bot).
