---
status: testing
phase: 13-multi-day-forecast-templates
source: [13-VERIFICATION.md]
started: 2026-06-19T17:00:00Z
updated: 2026-06-19T17:00:00Z
---

## Current Test

number: 1
name: Live Discord on-demand multi-day forecast on yahir-mint
expected: |
  After restarting the live daemon on yahir-mint, !weekday-forecast <loc> and
  !weekend-forecast <loc> in Discord each post a multi-day forecast embed/message
  with one line per in-window day (detailed by default).
awaiting: user response

## Tests

### 1. Live Discord on-demand multi-day forecast
expected: After `sudo systemctl restart weatherbot`, !weekday-forecast <loc> and !weekend-forecast <loc> post a multi-day forecast (detailed default), one line per in-window day.
result: [pending]

### 2. Live CLI on-demand forecast with flags
expected: `weatherbot weekday-forecast <loc> +compact +sat` prints a compact forecast; +sat appends Saturday (or a horizon notice if beyond today+7); exit 0; no SQLite write.
result: [pending]

### 3. Scheduled forecast slot fires without colliding with briefing
expected: Adding a `[[locations.forecast]]` slot to live config.toml registers a namespaced cron job (id contains `|fc|`) at the location tz, fires at the configured time, posts the scheduled forecast, and never collides with or delays the briefing job.
result: [pending]

### 4. Forecast template live reload (file-watch + keep-old on typo)
expected: Editing a forecast template (e.g. templates/forecast-weekday-detailed.txt) triggers a file-watch reload; a typo'd {token} is rejected keep-old; a valid edit takes effect on the next fire.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
