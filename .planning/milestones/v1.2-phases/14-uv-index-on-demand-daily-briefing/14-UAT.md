---
status: complete
phase: 14-uv-index-on-demand-daily-briefing
source: [14-VERIFICATION.md]
started: 2026-06-19T18:30:00Z
updated: 2026-06-23T17:55:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live `uv <loc>` command on Discord + CLI
expected: After restart, !uv <loc> (Discord) and `weatherbot uv <loc>` (CLI) return the UV summary + compact daytime HH:UV line; read-only.
result: pass
notes: CLI run live — `weatherbot uv Carlsbad` exit 0, read-only. Output had current (11 Extreme), today's max (12 Extreme), peak (12 at 13:00), crossing ("climbs above 6 around 11:00"), protect window, and compact HH:UV hourly line. User confirmed Discord `!uv` (shared render path).

### 2. UV section in a live daily briefing
expected: The next scheduled daily briefing carries the UV line — current UV, today's max UV, and the predicted local crossing time (or "stays below threshold today") — and the sunscreen hint uses the configured threshold.
result: pass

### 3. Live `[uv]` config hot-reload
expected: Editing `[uv]` threshold / pre_warn_lead_minutes in the live config.toml is picked up on reload without a code change; an invalid value / unknown key fails loud (keep-old).
result: pass
notes: Demoed live on yahir-mint. (1) Added [uv] threshold=8.0 → daemon "reload applied", CLI recomputed crossing to "climbs above 8". (2) threshold=25.0 → daemon "reload rejected: uv.threshold must be between 0 and 20, got 25.0" (keep-old, scheduler untouched). (3) Removed [uv] → reload applied, CLI back to "climbs above 6". config.toml reverted (clean diff).

### 4. Briefing-spine isolation under live data
expected: With real OpenWeather data, the UV section degrades gracefully when hourly/uvi is absent and never delays or drops the scheduled briefing.
result: pass
notes: User accepted without live re-test — missing hourly/uvi can't be reliably induced against the real API without mocking; graceful-degradation + briefing-isolation covered by phase automated tests.

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
