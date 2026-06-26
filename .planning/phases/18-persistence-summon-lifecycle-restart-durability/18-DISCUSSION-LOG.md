# Phase 18: Persistence + Summon/Lifecycle (Restart Durability) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-26
**Phase:** 18-persistence-summon-lifecycle-restart-durability
**Areas discussed:** Panel-find mechanism, Panel channel, Stray cleanup, Permission preflight, Startup behavior
**Mode:** Advisor (research-backed comparison tables; calibration tier `full_maturity`)

---

## Panel-find mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Pin-scan by `custom_id` (no persistence) | Scan channel pins for a bot-owned panel (author + static custom_id marker); reuse/recreate. Self-healing, zero persisted state, no stale-id class. | ✓ |
| Persist `message_id` to JSON | Store message_id+channel_id next to config; fetch on summon. Deterministic but forces a 404 fallback + 2nd source of truth. | |
| Hybrid (persist + scan fallback) | Persisted id fast-path + scan fallback. Production-grade, survives everything, but more code than warranted. | |
| New table in SQLite store | Persist in the briefing DB. Crosses the "dispatch writes nothing to the store" boundary; keeps the stale-id problem. | |

**User's choice:** Pin-scan by `custom_id`, no persistence.
**Notes:** Key enabling fact (from research) — persistent views re-bind by `custom_id` via `add_view` and the panel message persists server-side, so a durable `message_id` buys almost nothing. Scoped to pinned messages only (50-pin cap → trivial scan). → CONTEXT D-01/D-02/D-03.

---

## Panel channel

| Option | Description | Selected |
|--------|-------------|----------|
| Configured `[bot] panel_channel_id` | One key beside `operator_id`; known channel at startup enables autonomous restart re-find. Restart-boundary key. | ✓ |
| Invoked channel (zero-config) | Panel posts wherever `!panel` ran. No config, but no known channel after restart → PANEL-09 degrades to "re-run `!panel`." | |
| Hybrid (remember invoked channel in persistence) | Zero-config + autonomous re-find, but reintroduces the persistence the find-mechanism avoided. | |

**User's choice:** Configured `[bot] panel_channel_id`.
**Notes:** Coherent partner to the scan-based find — a scan needs a known channel at `on_ready`. Briefing rides a separate webhook, so no coupling. Channel-missing/misconfigured at startup → log + skip re-find, never crash. → CONTEXT D-04.

---

## Stray cleanup / idempotent summon

| Option | Description | Selected |
|--------|-------------|----------|
| Marker-strict, reuse-in-place, delete extras | Identity = author==bot AND static custom_id; reuse survivor via `edit()` (keeps pin position, stays live), delete additional owned panels. Scan pins only. | ✓ |
| Author-only, delete-and-recreate | Delete every bot-owned pin, post fresh. Simplest, but would delete unrelated pinned bot messages. | |
| Persisted-id reuse | Reuse the recorded message; can't sweep untracked strays; needs persistence. | |

**User's choice:** Marker-strict, reuse-in-place, delete extras.
**Notes:** Static `custom_id`s are an unforgeable bot-owned marker — never touches an unrelated pinned bot message. Delete-extras (not unpin/tombstone) because an unpinned-but-live View still responds to clicks. → CONTEXT D-05/D-06. `!panel` recorded as a lifecycle command outside the read-only dispatch seam (D-07).

---

## Permission preflight

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid: eager preflight + `Forbidden` catch | `permissions_for(guild.me)` before posting (CRITICAL + operator ephemeral, refuse summon) + per-action `Forbidden` catch for TOCTOU. | ✓ |
| Eager preflight only | Upfront check only; a perm revoked between check and act bubbles as an error. | |
| Attempt-and-catch only | Catch `Forbidden` per action; a mid-sequence 403 leaves an orphan message (the silent partial-failure SC#4 forbids). | |

**User's choice:** Hybrid (eager preflight + `Forbidden` catch).
**Notes:** Exact perm set = view_channel, send_messages, embed_links, read_message_history, **`pin_messages`**. Research surprise: discord.py 2.7 split `pin_messages` out of `manage_messages` (effective 2026-01-12) — check the new bit, not the legacy one. → CONTEXT D-09/D-10/D-11.

---

## Startup behavior (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Passive: `add_view` only at boot | Register the persistent view; reconcile (scan/re-pin/recreate/cleanup) only on explicit `!panel`. | ✓ |
| Active boot-reconcile | Also scan + ensure exactly one pinned panel at startup. Strongest hands-off guarantee, but startup scan + full find-or-create at boot. | |

**User's choice:** Passive boot — `add_view` only.
**Notes:** `add_view` re-binds the existing pinned panel's buttons so SC#1 holds without a boot scan; minimizes bot-thread startup I/O; "summon is the `!panel` path." → CONTEXT D-12.

---

## Claude's Discretion

- `!panel` command token/parse location + operator-gate reuse from `on_message`.
- Scan/cleanup helper module home and signature.
- `BotConfig.panel_channel_id` validator details.
- Precise `setup_hook` wiring mechanics (subclass vs. other) — direction locked to
  `setup_hook` (not `on_ready`), idempotent across reconnects (D-13).
- Exact CRITICAL/ephemeral copy strings; whether the optional `on_ready` perm
  sanity-check is included.

## Deferred Ideas

- Persist `message_id`/selected-location across restart — rejected for the milestone (v2 only).
- Active boot-reconcile — rejected in favor of passive boot.
- Forecast button + sub-tier (Phase 19); briefing-isolation re-proof + visual selected-location indicator + emoji labels + "updated" stamp (Phase 20).
- Hot-reloadable `[bot]` keys (`panel_channel_id`/`operator_id`) — carry-forward restart-boundary debt.
