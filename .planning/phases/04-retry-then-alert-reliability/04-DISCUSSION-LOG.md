# Phase 4: Retry-then-Alert Reliability - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-10
**Phase:** 4-Retry-then-Alert Reliability
**Areas discussed:** Out-of-band alert path, Heartbeat / liveness, Retry budget & policy, Alert behavior & anti-loop, Manual vs scheduled retry

---

## Out-of-band alert path

| Option | Description | Selected |
|--------|-------------|----------|
| Email (SMTP) | Alert via SMTP to inbox; truly independent of Discord | |
| Push service (ntfy/Pushover) | POST to a push service; buzzes phone immediately | |
| Second Discord webhook | Separate webhook; not independent of a Discord-wide outage | |
| Log + stderr only | No active notification; independent of Discord; relies on a watcher | ✓ |

**User's choice:** Log + stderr only.
**Notes:** Reframed by the user — "we will eventually also create a bot that monitors these logs, so choose what's best for that." Drove the follow-ups below toward machine-detectable + durable artifacts.

### Follow-up: how the log alert is "received"

| Option | Description | Selected |
|--------|-------------|----------|
| Distinct marker, watcher in Ph5 | Structured CRITICAL event; routing wired in Phase 5 | |
| Also write an alert file | Loud log line + durable marker artifact | |
| Keep pure stderr, revisit later | Just stderr, accept log-watching dependency | |

**User's choice:** Free-text — "we will eventually also create a bot that monitors these logs, so choose what's best for that." → resolved to: structured CRITICAL `briefing_missed` event + durable record optimized for a bot consumer.

### Follow-up: where the durable record lives

| Option | Description | Selected |
|--------|-------------|----------|
| Row in weatherbot.db | New alerts table; monitor queries SQL | ✓ |
| JSON-lines alert file | Append structured JSON to data/alerts.jsonl | |
| Both DB row + stderr | DB row + live stderr event | |

**User's choice:** Row in weatherbot.db (paired with the structured stderr/journald event, which happens regardless).

---

## Heartbeat / liveness

| Option | Description | Selected |
|--------|-------------|----------|
| Periodic tick + per-send | Interval liveness signal AND per-delivery success stamp | ✓ |
| Periodic tick only | Fixed-interval "alive" signal only | |
| Per successful run only | Stamp only on a delivered briefing (idle daemon looks dead) | |

**User's choice:** Periodic tick + per-send. Lets the monitor distinguish crashed (no tick) from failing-to-send (ticking, no recent success).

### Follow-up: where the heartbeat is recorded

| Option | Description | Selected |
|--------|-------------|----------|
| Heartbeat row in weatherbot.db | last_tick/last_success row upserted in place | |
| DB row + structured log | Durable DB row + periodic structured heartbeat log event | ✓ |
| Health file (timestamp) | Touch a data/heartbeat file; OS mtime is the signal | |

**User's choice:** DB row + structured log — same dual shape as the alert path.

---

## Retry budget & policy

| Option | Description | Selected |
|--------|-------------|----------|
| Moderate (~5 tries, ~2–3 min) | Exp backoff + jitter, capped at a couple minutes | |
| Tight (~3 tries, <30s) | Fail fast, alert almost immediately | |
| Patient (~8 tries, ~10 min) | More attempts over a longer (sub-90-min) window | |

**User's choice:** Free-text — "patient configuration 8 tries spread out in a 10 min range, wait 45 minutes, again 8 tries in a 10 minute range." → two-burst schedule, ~65 min total, under the 90-min grace window.

### Follow-up: scope of the two-burst schedule

| Option | Description | Selected |
|--------|-------------|----------|
| Both fetch and send | Same schedule for OpenWeather fetch and Discord send | ✓ |
| Send only; tighter fetch | Patient on send, shorter on fetch | |

**User's choice:** Both fetch and send.

### Follow-up: 401/403 auth-failure handling

| Option | Description | Selected |
|--------|-------------|----------|
| Short-circuit → alert now | Abandon the schedule immediately on 401/403, alert at once | ✓ |
| Alert only at end | Wait out the schedule before alerting | |

**User's choice:** Short-circuit → alert now (reason distinguishes auth from transient-exhausted).

### Follow-up: hardcoded vs config-exposed timings

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded constants | Named constants like Phase 3's 90-min grace window | |
| Config-exposed | In config.toml, validated at load, surfaced by --check | ✓ |

**User's choice:** Config-exposed.

---

## Alert behavior & anti-loop

### Dedup / anti-loop

| Option | Description | Selected |
|--------|-------------|----------|
| One alert per slot per day | At most one briefing_missed per (location, slot, local_date), INSERT-OR-IGNORE | ✓ |
| Alert each exhaustion | Alert on every retry-schedule exhaustion incl. re-attempts | |

**User's choice:** One alert per slot per day.

### Unexpected exception (RELY-06) → alert?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — alert with reason=internal_error | Alert + traceback + loop survives | ✓ |
| No — log traceback only | Traceback only; alerts table reserved for delivery/auth | |

**User's choice:** Yes — alert with reason=internal_error.

### Resolve on later success?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — mark resolved | resolved_at flag stamped if the slot later delivers | ✓ |
| No — alerts are immutable events | Append-only; monitor correlates alert vs success | |

**User's choice:** Yes — mark resolved.

---

## Manual vs scheduled retry

| Option | Description | Selected |
|--------|-------------|----------|
| Daemon only; manual = tight/none | Patient schedule + alert + heartbeat daemon-only; --send-now quick + terminal report | ✓ |
| Same patient retry everywhere | Manual also runs 8/45m/8 (could hang terminal ~65 min) | |
| Manual: tight retry, no alert | Manual short retry, no alert/heartbeat rows | |

**User's choice:** Daemon only; manual = tight/none.

---

## Claude's Discretion

- Heartbeat tick interval (~5–15 min default).
- `Retry-After` cap value (so an oversized 429 value can't blow the ~65-min budget).
- Exact transient-vs-permanent failure classification (retry timeouts/connection/5xx/429; never 400/404/auth).
- `tenacity` vs hand-rolled retry — implementation choice; long mid-pause sleep must stay SIGTERM-interruptible and must not block other scheduled jobs.
- Exact `alerts`/`heartbeat` table + column names and retry config section keys.

## Deferred Ideas

- Active push/email/SMS alert delivery (SMTP, ntfy/Pushover, second Discord webhook) — not v1.
- The future log-monitoring bot itself (consumes these events / queries the tables).
- Promoting the heartbeat tick interval / Retry-After cap into config later.
- Routing the structured log event to journald→email / external monitoring — Phase 5.
