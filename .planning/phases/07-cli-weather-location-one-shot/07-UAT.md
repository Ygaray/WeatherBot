---
status: testing
phase: 07-cli-weather-location-one-shot
source: [07-VERIFICATION.md]
started: 2026-06-15T22:55:00Z
updated: 2026-06-15T22:55:00Z
---

## Current Test

number: 1
name: Live `weatherbot weather home` over real OpenWeather network/key
expected: |
  On host yahir-mint, `uv run weatherbot weather home` exits 0 and prints the
  home location's v1 briefing to stdout (no log lines on stdout); `... -v`
  additionally shows the `lookup complete` INFO line on stderr.
awaiting: user response

## Tests

### 1. Live `weatherbot weather home` over real OpenWeather network/key
expected: Exits 0 and prints the home location's v1 briefing to stdout (no log lines on stdout); `... -v` additionally shows the `lookup complete` INFO line on stderr.
result: [pending]

### 2. Redeploy the systemd unit on host yahir-mint
expected: After `git pull`, `uv sync`, editing `/etc/systemd/system/weatherbot.service` ExecStart to `weatherbot run`, `daemon-reload`, and restart — `systemctl status weatherbot.service` is active (running), the next scheduled briefing fires, and the deployed ExecStart no longer uses the removed `--run` flag.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
