---
status: testing
phase: 02-real-config-locations-content-templates
source: [02-VERIFICATION.md]
started: 2026-06-10T14:50:02Z
updated: 2026-06-10T14:50:02Z
---

## Current Test

number: 1
name: Run `weatherbot --check` against a real config.toml with a live OpenWeather One Call key
expected: |
  Exits 0 on a valid + reachable config; exits 1 with the subscription-not-propagated
  message on a 401/403; delivers no Discord briefing.
awaiting: user response

## Tests

### 1. Run `weatherbot --check` against a real config.toml with a live OpenWeather One Call key
expected: Exits 0 on a valid + reachable config; exits 1 with the subscription-not-propagated message on a 401/403; delivers no Discord briefing
why_human: Requires a live OpenWeather One Call 3.0 subscription and network; the reachability probe cannot be exercised offline
result: [pending]

### 2. Run `weatherbot --send-now Home` (imperial/unset) and `weatherbot --send-now Weekend` (units="metric") against the live API and inspect the delivered Discord messages
expected: |
  Home's message leads with °F/mph (imperial-primary); Weekend's message leads with °C/m/s
  (metric-primary). Each shows the correct location, today's high/low/rain, feels-like, any
  firing hints, and any active severe-weather alert line.
why_human: End-to-end delivery, real payload content, the per-location units override visible effect, and visual correctness of the briefing require a live key and the Discord channel
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
