---
status: complete
phase: 02-real-config-locations-content-templates
source: [02-VERIFICATION.md]
started: 2026-06-10T14:50:02Z
updated: 2026-06-10T17:05:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Run `weatherbot --check` against a real config.toml with a live OpenWeather One Call key
expected: Exits 0 on a valid + reachable config; exits 1 with the subscription-not-propagated message on a 401/403; delivers no Discord briefing
why_human: Requires a live OpenWeather One Call 3.0 subscription and network; the reachability probe cannot be exercised offline
result: pass
note: |
  Live `--check` exits 0 ("config check passed locations=2") against a valid, reachable
  config with no Discord send — confirmed. During testing a real robustness gap surfaced:
  a malformed config (missing `[[locations]]` header / missing required `timezone`) crashed
  with a raw Python traceback instead of the clean loud error SC-05 promises. Fixed in this
  session (cli.py `_load_config_reporting`, commit 2437b44) with 4 regression tests
  (test_cli.py, commit 2c2c97f); malformed config now reports a single clean error line and
  exits 1. Gap found-and-resolved, not deferred.

### 2. Run `weatherbot --send-now Carlsbad` (imperial/unset) and `weatherbot --send-now "El Paso"` (units="metric") against the live API and inspect the delivered Discord messages
expected: |
  Carlsbad's message leads with °F/mph (imperial-primary); El Paso's leads with °C/m/s
  (metric-primary). Each shows the correct location, today's high/low/rain, feels-like,
  any firing hints, and any active severe-weather alert line.
why_human: End-to-end delivery, real payload content, the per-location units override visible effect, and visual correctness of the briefing require a live key and the Discord channel
result: pass
note: User confirmed both Discord messages render correctly — Carlsbad imperial-primary (°F/mph), El Paso metric-primary (°C/m/s). The per-location units override works end-to-end.

## Summary

total: 2
passed: 1
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
