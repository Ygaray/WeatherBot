---
status: testing
phase: 11-discord-inbound-gateway-bot
source: [11-VERIFICATION.md]
started: 2026-06-17T00:00:00Z
updated: 2026-06-17T00:00:00Z
---

## Current Test

number: 1
name: Type `!weather home` (and `!weather <unknown>`) in the real private Discord channel as the operator
expected: |
  An embed briefing reply for a known location (Now / High-Low / Rain fields); the configured-names
  error text for an unknown location; no "Heartbeat blocked" warning in logs.
awaiting: user response

## Tests

### 1. Live `!weather` command in the real Discord channel
expected: An embed briefing reply for a known location (Now / High-Low / Rain fields); the configured-names error text for an unknown location; no "Heartbeat blocked" warning in logs.
result: [pending]

### 2. Message Content Intent enabled in the Discord Developer Portal
expected: Message Content Intent (privileged) toggled ON for the bot application; on_ready logs "inbound bot ready" (not the CRITICAL "message_content intent missing" line). With it OFF, the bot reads empty message bodies.
result: [pending]

### 3. Token revocation / gateway failure isolation across a scheduled slot
expected: BotThread logs CRITICAL "invalid Discord token; inbound bot disabled, briefings unaffected" and dies alone; the next scheduled briefing still fires via the webhook; the systemd READY gate is unaffected.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
