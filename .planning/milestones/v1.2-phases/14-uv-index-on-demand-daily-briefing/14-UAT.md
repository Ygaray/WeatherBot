---
status: testing
phase: 14-uv-index-on-demand-daily-briefing
source: [14-VERIFICATION.md]
started: 2026-06-19T18:30:00Z
updated: 2026-06-19T18:30:00Z
---

## Current Test

number: 1
name: Live `uv <loc>` command on Discord + CLI (yahir-mint)
expected: |
  After `sudo systemctl restart weatherbot`, !uv <loc> on Discord and `weatherbot uv <loc>`
  on the CLI each return the UV summary (current / today's max + WHO category / peak /
  threshold-crossing time or "stays below threshold today") plus the compact daytime HH:UV
  hourly line; read-only, exit 0.
awaiting: user response

## Tests

### 1. Live `uv <loc>` command on Discord + CLI
expected: After restart, !uv <loc> (Discord) and `weatherbot uv <loc>` (CLI) return the UV summary + compact daytime HH:UV line; read-only.
result: [pending]

### 2. UV section in a live daily briefing
expected: The next scheduled daily briefing carries the UV line — current UV, today's max UV, and the predicted local crossing time (or "stays below threshold today") — and the sunscreen hint uses the configured threshold.
result: [pending]

### 3. Live `[uv]` config hot-reload
expected: Editing `[uv]` threshold / pre_warn_lead_minutes in the live config.toml is picked up on reload without a code change; an invalid value / unknown key fails loud (keep-old).
result: [pending]

### 4. Briefing-spine isolation under live data
expected: With real OpenWeather data, the UV section degrades gracefully when hourly/uvi is absent and never delays or drops the scheduled briefing.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
