---
phase: quick-260615-fac
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - weatherbot/weather/store.py
  - tests/test_scheduler.py
  - .planning/phases/01-first-briefing-end-to-end/01-01-SUMMARY.md
  - .planning/phases/01-first-briefing-end-to-end/01-02-SUMMARY.md
  - .planning/phases/01-first-briefing-end-to-end/01-03-SUMMARY.md
  - .planning/phases/02-real-config-locations-content-templates/02-01-SUMMARY.md
  - .planning/phases/02-real-config-locations-content-templates/02-02-SUMMARY.md
  - .planning/phases/02-real-config-locations-content-templates/02-03-SUMMARY.md
  - .planning/phases/02-real-config-locations-content-templates/02-04-SUMMARY.md
  - .planning/phases/04-retry-then-alert-reliability/04-01-SUMMARY.md
  - .planning/phases/04-retry-then-alert-reliability/04-02-SUMMARY.md
  - .planning/phases/04-retry-then-alert-reliability/04-03-SUMMARY.md
  - .planning/phases/04-retry-then-alert-reliability/04-04-SUMMARY.md
autonomous: true
requirements: []

must_haves:
  truths:
    - "weatherbot/weather/store.py no longer defines record_sent"
    - "was_sent remains defined in store.py (still has production callers)"
    - "The full pytest suite (186 tests) passes after the change"
    - "tests/test_scheduler.py:test_sent_log_idempotent asserts the same idempotency guarantee via claim_slot/release_claim instead of record_sent"
    - "All 11 listed SUMMARY frontmatter blocks contain a requirements-completed field sourced from each phase's VERIFICATION.md coverage table"
  artifacts:
    - path: "weatherbot/weather/store.py"
      provides: "claim_slot/release_claim atomic idempotency; was_sent reader; no record_sent"
    - path: "tests/test_scheduler.py"
      provides: "Idempotency coverage on the live claim_slot/release_claim path"
  key_links:
    - from: "tests/test_scheduler.py::test_sent_log_idempotent"
      to: "weatherbot.weather.store.claim_slot"
      via: "import + call"
      pattern: "claim_slot"
---

<objective>
Resolve two independent tech-debt items from the v1.0 milestone audit:

1. Delete the orphaned dead-code function `record_sent()` from `weatherbot/weather/store.py` (superseded by the atomic `claim_slot`/`release_claim` pair that production uses), and migrate the one test that exercises it so idempotency coverage shifts to the live path. KEEP `was_sent` — it still has production callers.
2. Backfill the missing `requirements-completed:` YAML frontmatter field on 11 plan SUMMARY files, sourced from each phase's VERIFICATION.md "Requirements Coverage" table.

Purpose: Remove a dead non-atomic idempotency primitive so the codebase has exactly one (atomic) dedup path, and make the GSD planning-doc requirement ledger complete and accurate.
Output: One code-cleanup commit (store.py + test migration, full suite green) and one docs commit (11 SUMMARY frontmatter edits). Two atomic commits.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md
@weatherbot/weather/store.py
@tests/test_scheduler.py

# Pre-verified facts (do not re-derive; confirm with grep before deleting):
# - record_sent has ZERO production callers. Only references: tests/test_scheduler.py
#   lines 119, 124, 128 (the test being migrated). store.py docstrings of claim_slot
#   MENTION record_sent in prose but do not CALL it.
# - was_sent IS used in production: weatherbot/scheduler/daemon.py (import L71, call L435)
#   and weatherbot/scheduler/catchup.py. DO NOT DELETE was_sent.
# - claim_slot (store.py:267) and release_claim (store.py:307) are the live atomic
#   INSERT OR IGNORE / DELETE idempotency pair. test_concurrent_double_fire_delivers_once
#   (test_scheduler.py:488) already covers them; this plan adds the simpler unit-level
#   idempotency assertion that test_sent_log_idempotent currently expresses via record_sent.

# REQ-ID attribution per plan, read from each phase VERIFICATION.md Requirements Coverage
# table (authoritative source of truth). Apply EXACTLY these values:
#   01-01: [CONF-02]
#   01-02: [FCST-01, FCST-02, FCST-03, FCST-04]
#   01-03: [DATA-01, DATA-02, DATA-03]
#   02-01: [LOC-03, FCST-05, FCST-06]
#   02-02: [LOC-03, FCST-05, FCST-06]
#   02-03: [LOC-01, LOC-02, TMPL-01, TMPL-02, CONF-01, CONF-03]
#   02-04: [LOC-03, CONF-03, CONF-05]
#   04-01: [RELY-01, RELY-02]
#   04-02: [RELY-03, RELY-04, RELY-05]
#   04-03: [RELY-01, RELY-02, RELY-03, RELY-04, RELY-05, RELY-06]
#   04-04: [RELY-01]
</context>

<tasks>

<task type="auto">
  <name>Task 1: Delete dead record_sent, migrate idempotency test to claim_slot, full suite green</name>
  <files>weatherbot/weather/store.py, tests/test_scheduler.py</files>
  <action>
First CONFIRM the caller sets before deleting anything. Run `grep -rn "record_sent" --include="*.py" weatherbot/ tests/` and `grep -rn "was_sent" --include="*.py" weatherbot/`. Expected: record_sent appears ONLY as its def in store.py, in claim_slot's docstring prose, and at tests/test_scheduler.py:119/124/128. Expected: was_sent has live callers in weatherbot/scheduler/daemon.py and weatherbot/scheduler/catchup.py. If grep contradicts this (e.g. record_sent has any production caller), STOP and report — do not delete a function that has a remaining production caller. Do not break the build.

Given the confirmed state: delete ONLY the `record_sent` function definition from weatherbot/weather/store.py (the def block at roughly lines 242-264, ending before `def claim_slot`). Do NOT delete was_sent, claim_slot, release_claim, or any other function. Leave the prose mention of record_sent inside claim_slot's docstring as-is (it explains the history); it is documentation, not a call.

Then migrate tests/test_scheduler.py::test_sent_log_idempotent (lines ~118-141) so it asserts the SAME idempotency guarantee against the live atomic path instead of record_sent/was_sent:
- Change the import to `from weatherbot.weather.store import claim_slot, release_claim, was_sent`.
- Fresh-slot read: `was_sent(...)` is False before any claim.
- First `claim_slot(tmp_db, "Home", "07:00", "2026-06-10")` returns True (this caller won and wrote the row), and `was_sent(...)` is now True.
- A second `claim_slot(...)` on the same key returns False (row already exists) — this is the idempotency guarantee that the old double-`record_sent` asserted.
- Keep the existing COUNT(*)==1 sqlite assertion proving exactly one sent_log row exists for that key after the double claim.
- Preserve the distinct-key checks at the end: `was_sent(tmp_db, "Home", "07:00", "2026-06-11")` is False and `was_sent(tmp_db, "Home", "08:30", "2026-06-10")` is False (independent slots).
Keep the test name and its SCHD-07 section comment. Do not touch any other test (test_concurrent_double_fire_delivers_once already covers release_claim and should remain unchanged).
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot && ! grep -n "^def record_sent" weatherbot/weather/store.py && grep -q "^def was_sent" weatherbot/weather/store.py && ! grep -nE "(import|^\s+)record_sent" tests/test_scheduler.py && uv run pytest -q 2>&1 | tail -5</automated>
  </verify>
  <done>record_sent is gone from store.py; was_sent still defined; test_scheduler.py no longer imports/calls record_sent; test_sent_log_idempotent uses claim_slot/release_claim; full pytest suite (186 tests) passes; ruff clean.</done>
</task>

<task type="auto">
  <name>Task 2: Backfill requirements-completed frontmatter on 11 SUMMARYs from VERIFICATION evidence</name>
  <files>.planning/phases/01-first-briefing-end-to-end/01-01-SUMMARY.md, .planning/phases/01-first-briefing-end-to-end/01-02-SUMMARY.md, .planning/phases/01-first-briefing-end-to-end/01-03-SUMMARY.md, .planning/phases/02-real-config-locations-content-templates/02-01-SUMMARY.md, .planning/phases/02-real-config-locations-content-templates/02-02-SUMMARY.md, .planning/phases/02-real-config-locations-content-templates/02-03-SUMMARY.md, .planning/phases/02-real-config-locations-content-templates/02-04-SUMMARY.md, .planning/phases/04-retry-then-alert-reliability/04-01-SUMMARY.md, .planning/phases/04-retry-then-alert-reliability/04-02-SUMMARY.md, .planning/phases/04-retry-then-alert-reliability/04-03-SUMMARY.md, .planning/phases/04-retry-then-alert-reliability/04-04-SUMMARY.md</files>
  <action>
Add a single `requirements-completed: [...]` line to each of the 11 SUMMARY files' YAML frontmatter block. The field is currently ABSENT in all 11. Match the existing inline-list style already used by SUMMARYs that have it (e.g. 01-04-SUMMARY.md line 53: `requirements-completed: [DELV-01, DELV-02, DELV-03, CONF-04]`). Insert the line inside the frontmatter block on its own line immediately before the closing `---` fence (the same trailing position the existing examples use — after the dependency/tech/metrics keys, before the closing fence). Use the EXACT values below, sourced from each phase's VERIFICATION.md Requirements Coverage table (which credits each REQ-ID to its source plan id):

- 01-01-SUMMARY.md  → `requirements-completed: [CONF-02]`
- 01-02-SUMMARY.md  → `requirements-completed: [FCST-01, FCST-02, FCST-03, FCST-04]`
- 01-03-SUMMARY.md  → `requirements-completed: [DATA-01, DATA-02, DATA-03]`
- 02-01-SUMMARY.md  → `requirements-completed: [LOC-03, FCST-05, FCST-06]`
- 02-02-SUMMARY.md  → `requirements-completed: [LOC-03, FCST-05, FCST-06]`
- 02-03-SUMMARY.md  → `requirements-completed: [LOC-01, LOC-02, TMPL-01, TMPL-02, CONF-01, CONF-03]`
- 02-04-SUMMARY.md  → `requirements-completed: [LOC-03, CONF-03, CONF-05]`
- 04-01-SUMMARY.md  → `requirements-completed: [RELY-01, RELY-02]`
- 04-02-SUMMARY.md  → `requirements-completed: [RELY-03, RELY-04, RELY-05]`
- 04-03-SUMMARY.md  → `requirements-completed: [RELY-01, RELY-02, RELY-03, RELY-04, RELY-05, RELY-06]`
- 04-04-SUMMARY.md  → `requirements-completed: [RELY-01]`

Do NOT invent IDs not present in the VERIFICATION evidence. Do NOT touch 02-05 or any 03-xx/05-xx SUMMARY (02-05, 03-01, 03-02, 03-04, 03-05, 05-01, 05-02, 05-03 already have the field; 03-03 is intentionally out of this task's scope per the work order). Edit ONLY the frontmatter; leave all body content untouched. Each file's closing frontmatter fence is the FIRST `---` line after line 1 — insert the new line just above it.
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot && for f in 01-first-briefing-end-to-end/01-01 01-first-briefing-end-to-end/01-02 01-first-briefing-end-to-end/01-03 02-real-config-locations-content-templates/02-01 02-real-config-locations-content-templates/02-02 02-real-config-locations-content-templates/02-03 02-real-config-locations-content-templates/02-04 04-retry-then-alert-reliability/04-01 04-retry-then-alert-reliability/04-02 04-retry-then-alert-reliability/04-03 04-retry-then-alert-reliability/04-04; do c=$(grep -c "^requirements-completed:" ".planning/phases/${f}-SUMMARY.md"); [ "$c" = "1" ] || { echo "FAIL ${f}: $c"; exit 1; }; done && echo "all 11 backfilled" && uv run python -c "import yaml,glob,sys; [yaml.safe_load(open(p).read().split('---')[1]) for p in glob.glob('.planning/phases/0[124]-*/0*-SUMMARY.md')]; print('yaml frontmatter parses')"</automated>
  </verify>
  <done>All 11 listed SUMMARY files contain exactly one requirements-completed line with the VERIFICATION-sourced IDs; every modified frontmatter block still parses as valid YAML; no other SUMMARY files altered.</done>
</task>

</tasks>

<verification>
- `grep "^def record_sent" weatherbot/weather/store.py` returns nothing (deleted).
- `grep "^def was_sent" weatherbot/weather/store.py` still matches (preserved — has production callers).
- `uv run pytest -q` reports 186 passed.
- `uv run ruff check .` is clean.
- All 11 SUMMARY frontmatter blocks have exactly one `requirements-completed:` line; YAML still parses.
- Two separate commits: (1) `refactor: drop dead record_sent; migrate idempotency test to claim_slot`, (2) `docs: backfill requirements-completed frontmatter on 11 plan SUMMARYs`.
</verification>

<success_criteria>
- Dead `record_sent` removed; `was_sent`/`claim_slot`/`release_claim` intact.
- `test_sent_log_idempotent` proves idempotency via the live `claim_slot`/`release_claim` path.
- Full 186-test suite passes; ruff clean.
- 11 SUMMARYs carry accurate, VERIFICATION-sourced `requirements-completed` metadata.
- Work landed as two atomic commits.
</success_criteria>

<output>
Create `.planning/quick/260615-fac-resolve-two-milestone-audit-tech-debt-it/260615-fac-SUMMARY.md` when done.
</output>
