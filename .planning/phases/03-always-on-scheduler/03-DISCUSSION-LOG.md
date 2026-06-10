# Phase 3: Always-On Scheduler - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-10
**Phase:** 3-Always-On Scheduler
**Areas discussed:** Schedule config shape, Missed-send recovery, Idempotency / slot identity, Daemon run command, Send-time/weather-check annotation (user-added)

---

## Schedule config shape

### Structure
| Option | Description | Selected |
|--------|-------------|----------|
| Nested under each location | `[[locations.schedule]]` blocks inside the location | ✓ |
| Separate top-level table | `[[schedule]]` referencing a location by name | |

### Days expression
| Option | Description | Selected |
|--------|-------------|----------|
| Presets + explicit days | `mon-fri`/`weekends`/`daily` plus explicit `sat,sun` | ✓ |
| Explicit day list only | Always a list of day names, no shorthand | |
| Cron-style | Raw cron day-of-week field | |

### Toggle
| Option | Description | Selected |
|--------|-------------|----------|
| `enabled = true/false` field | Pause a send-time without deleting it | ✓ |
| Comment it out | Disable by commenting the block out | |

**User's choice:** Nested blocks; friendly presets + explicit lists; `enabled` field.
**Notes:** Keeps each place's send-times next to its name/coords.

---

## Missed-send recovery

| Option | Description | Selected |
|--------|-------------|----------|
| Within a grace window | Deliver only if recovery < N min after the slot, else skip+log | ✓ |
| Same local date, any time | Always deliver while still that local date | |
| Always, even across days | Literal "always send late" regardless of downtime | |

### Window length
| Option | Description | Selected |
|--------|-------------|----------|
| 90 minutes | Research-suggested default | ✓ |
| 60 minutes | Tighter | |
| 120 minutes | More forgiving | |
| Configurable | Expose in config.toml | |

**User's choice:** Grace window, 90 minutes (hardcoded).
**Notes:** Resolves the Phase-2-flagged open question. A late-but-fresh morning briefing is fine within 90 min; beyond that it's noise.

---

## Idempotency / slot identity

### Slot identity
| Option | Description | Selected |
|--------|-------------|----------|
| The send-time itself | Key = location + time-of-day; editing time = new slot | ✓ |
| Explicit id per entry | User-assigned `id` survives time edits | |
| List position / index | Fragile to reordering | |

### Mark sent
| Option | Description | Selected |
|--------|-------------|----------|
| Only after successful delivery | Crash mid-send → retries; tiny race accepted | ✓ |
| On attempt (before sending) | Never-twice even on crash, but loses failed sends | |

**User's choice:** Slot = send-time; mark sent only after successful delivery.
**Notes:** Sent-log stored in the existing `data/weatherbot.db` (Claude proposed; user did not object).

---

## Daemon run command

> First presented; the user asked for an explanation of the options before answering, then answered in plain text.

### Launch + run mode
| Option | Description | Selected |
|--------|-------------|----------|
| `--run`, foreground | Flag style, blocks, logs to stdout, clean shutdown; backgrounding deferred to Phase 5 | ✓ |
| `--run`, self-daemonize | Forks/detaches with a PID file | |
| `run` subcommand | Positional subcommand instead of a flag | |

### On boot
| Option | Description | Selected |
|--------|-------------|----------|
| Announce schedule + catch up | Log each enabled slot + next-fire, run catch-up, idle | ✓ |
| Catch up, log minimally | Terse "started, N jobs" only | |

**User's choice:** `--run` foreground; announce schedule on startup.
**Notes:** User initially rejected the question to ask for clarification; after a plain-language explanation of daemon/foreground vs background, chose the recommended foreground + announce options.

---

## Send-time / weather-check / late-send annotation (user-added)

> User raised this as a new requirement when asked "ready for context?".

### Appearance
| Option | Description | Selected |
|--------|-------------|----------|
| Editable template placeholders | `{sent_at}`, `{checked_at}`, `{schedule_note}` the user can position/reword | ✓ |
| Auto-appended footer | Fixed footer the bot always adds, bypassing the template | |

### On-time / manual behavior
| Option | Description | Selected |
|--------|-------------|----------|
| Only annotate when late | sent_at + checked_at always; schedule_note only when late | ✓ |
| Always show scheduled time | Show "scheduled for X" even on-time | |

**User's choice:** Editable placeholders; `{sent_at}` + `{checked_at}` on every message; `{schedule_note}` only when late (confirmed twice).
**Notes:** Motivation — a 7am send that fails and lands at 7:30 should say it was intended for 7, sent at 7:30, with a weather-check time so the user can gauge accuracy. Times in location-local time.

---

## Claude's Discretion

- Exact accepted `days` vocabulary/aliases and parsing.
- Wording/format of `{schedule_note}` and time formatting of `{sent_at}`/`{checked_at}`.
- Sent-log table name/columns and catch-up scan implementation.
- APScheduler job-build details; how scheduling metadata is threaded into `send_now`/render.

## Deferred Ideas

- Configurable grace window (chose hardcoded 90 min).
- Self-daemonizing / background `--run` (Phase 5 owns supervision/reboot survival).
- Retry-then-alert + heartbeat on failed scheduled sends (Phase 4).
- Per-slot template overrides / skip-on-holiday / configurable annotation thresholds (out of scope).
