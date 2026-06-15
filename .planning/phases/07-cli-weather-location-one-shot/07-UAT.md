---
status: complete
phase: 07-cli-weather-location-one-shot
source: [07-VERIFICATION.md]
started: 2026-06-15T22:55:00Z
updated: 2026-06-15T23:36:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live `weatherbot weather home` over real OpenWeather network/key
expected: Exits 0 and prints the home location's v1 briefing to stdout (no log lines on stdout); `... -v` additionally shows the `lookup complete` INFO line on stderr.
result: pass
note: "Live on host yahir-mint. `weather home` (placeholder name not in real config) correctly printed `No location named 'home'; configured locations: Carlsbad, El Paso` with no traceback (CMD-04). `weather Carlsbad` printed the v1 briefing to stdout, exit 0, no log lines on stdout (CMD-01/CMD-05/D-09 quiet confirmed)."

### 2. Redeploy the systemd unit on host yahir-mint
expected: After `git pull`, `uv sync`, editing `/etc/systemd/system/weatherbot.service` ExecStart to `weatherbot run`, `daemon-reload`, and restart — `systemctl status weatherbot.service` is active (running), the next scheduled briefing fires, and the deployed ExecStart no longer uses the removed `--run` flag.
result: pass
note: "Live on host yahir-mint. Deployed unit edited in place (venv form) `--run` → `run`; ExecStart now `/home/yahir/Projects/WeatherBot/.venv/bin/python -m weatherbot run`. After daemon-reload + restart: ActiveState=active, SubState=running, ExecMainStatus=0; journal shows `weatherbot online jobs=3`, scheduler started (Carlsbad mon-fri 07:00, El Paso sat,sun 08:30), `discord delivery ok status=200`. Backup saved at weatherbot.service.bak."

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
