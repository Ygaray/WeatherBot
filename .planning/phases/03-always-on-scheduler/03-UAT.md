---
status: complete
phase: 03-always-on-scheduler
source: [03-01-SUMMARY.md, 03-02-SUMMARY.md, 03-03-SUMMARY.md, 03-04-SUMMARY.md, 03-05-SUMMARY.md]
started: 2026-06-11T00:08:45Z
updated: 2026-06-11T00:36:30Z
---

## Current Test
<!-- OVERWRITE each test - shows where we are -->

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running weatherbot daemon and clear nothing else. Run `weatherbot --run` from scratch. The process boots without a traceback, loads/validates config and settings, prepares the sent-log DB directory, and blocks in the foreground (keeps running, does not exit immediately).
result: pass

### 2. Schedule Announcement on Startup
expected: On `weatherbot --run`, the daemon announces each ENABLED (location, schedule-slot) it registered, each with a computed next-run time shown in that location's own local timezone (e.g. the home city's 09:00 weekday slot and the travel city's weekend slot appear with sensible next-fire datetimes).
result: pass
note: "Carlsbad mon-fri 07:00 → next 2026-06-11 (Thu) 07:00-06:00; El Paso sat,sun 08:30 → next 2026-06-13 (Sat) 08:30-06:00. jobs=2, both location-local, correct days."

### 3. Disabled / Day-of-Week Slots Honored
expected: A schedule entry with `enabled = false` produces NO registered job (it's absent from the announcement). Weekday-only slots (`weekdays`) and weekend-only slots (`weekends`) show next-run times that land on the correct days — a weekday slot never schedules onto Sat/Sun and vice versa.
result: pass
note: "Added disabled 12:00 daily slot to Carlsbad → announcement still jobs=2 (disabled slot skipped). Day-of-week proven in test 2 (mon-fri→Thu, sat,sun→Sat)."

### 4. Scheduled Briefing Fires and Delivers
expected: Set a schedule slot a minute or two in the future for an enabled location, run `weatherbot --run`, and wait. At the configured local time a weather briefing is delivered to Discord with live current weather for that location.
result: pass
note: "wed 18:25 slot fired at 18:25:01, discord status=200, delivered=True late=False, live Carlsbad conditions (99°F Clear). cron rescheduled to next wed."

### 5. Timing Footer in Delivered Message
expected: The delivered briefing carries a location-local timing footer — "— sent {time} · weather checked {time}" (e.g. "7:30 AM") in the location's timezone. A normal on-time send shows no extra schedule note line; the briefing reads cleanly.
result: pass
note: "Footer: '— sent 6:25 PM · weather checked 6:25 PM' (Carlsbad-local); on-time send, no schedule-note line present."

### 6. Exactly-Once on Restart (No Double-Send)
expected: After a slot has already fired and delivered today, stop the daemon (Ctrl-C) and start it again with `weatherbot --run`. The already-sent slot for today is NOT re-delivered — no duplicate briefing arrives in Discord on restart.
result: pass
note: "Restarted ~8 min after the 18:25 fire (inside 90-min grace). No catch-up fire, no discord delivery log, no duplicate in Discord. wed slot next_run_time correctly 2026-06-17."

### 7. Startup Catch-Up for a Recent Miss
expected: Arrange a slot whose scheduled local time passed LESS than 90 minutes ago today and has not yet been sent (e.g. daemon was down over that time). On `weatherbot --run`, the daemon performs a startup catch-up scan and delivers that one missed briefing once (with live current weather). A slot missed by MORE than 90 minutes is NOT caught up.
result: pass
note: "New 18:30 wed slot (passed ~5 min prior) caught up once on startup: late=True, delivered=True, status=200, live conditions. Already-sent 18:25 slot NOT re-sent. Late message rendered recovery note '(intended for 6:30 PM, sent 6:35 PM)' — confirms SCHD-04 late-display path."

### 8. Clean Shutdown
expected: With `weatherbot --run` running in the foreground, press Ctrl-C (or send SIGTERM). The daemon shuts down cleanly — it stops promptly without an unhandled traceback or hang.
result: pass
note: "Ctrl-C → 'Scheduler has been shut down' + 'daemon stopped', returned to shell, no KeyboardInterrupt traceback, no hang."

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
