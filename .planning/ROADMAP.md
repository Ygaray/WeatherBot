**Plans**: 3 plans + 2 gap-closure (03-04, 03-05)
Plans:
**Wave 1**

- [x] 03-01-PLAN.md — Wave 1: Schedule config model + Location.schedule, days parser, sent_log idempotency table + was_sent/record_sent, test scaffold (SCHD-01/02/03/07-store)
- [x] 03-02-PLAN.md — Wave 1: ScheduleContext + schedule_placeholders, {sent_at}/{checked_at}/{schedule_note} canonical extension, send_now threading, template footers (SCHD-04 display)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-03-PLAN.md — Wave 2: daemon spine — plan_catchup 90-min recovery, run_daemon foreground lifecycle + fire_slot, per-location-tz CronTrigger firing, weatherbot --run (SCHD-05/06, SCHD-03 DST exactly-once)

**Gap closure** *(from 03-VERIFICATION.md — run via `/gsd-execute-phase 03 --gaps-only`)*

- [ ] 03-04-PLAN.md — DST transition-band fix: plan_catchup builds the scheduled instant via datetime(...).replace(tzinfo=tz), round-trip-detects+skips the spring-forward gap, compares aware instants; transition-band tests (02:30 gap / 01:30 fold) (SCHD-04 DST half / SC#3)
- [ ] 03-05-PLAN.md — Exactly-once delivery: atomic claim_slot (INSERT OR IGNORE + rowcount==1) gating delivery before the network send + release_claim on failure; fire_slot rewired; concurrent-double-fire test asserts one POST (SCHD-07 / SC#5)

