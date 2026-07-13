---
phase: 33-interactive-panel-robustness
plan: 06
subsystem: ui
tags: [render, forecast, discord-embed, timestamps, golden-snapshots, jinja-free-templates]

# Dependency graph
requires:
  - phase: 33-interactive-panel-robustness (plan 05)
    provides: F107/F11 dt-paired imperial/metric daily temps (prior HARD-UI-03 slice)
  - phase: 32-timezone-date-boundary-correctness
    provides: local-date anchoring convention + test-shaped-fix pattern this plan inherits
provides:
  - "Forecast header rendered exactly once per surface (embed title + CLI title print; body no longer duplicates it) — F28 closed"
  - "renderer.render collapses lines left blank solely by an empty-token substitution ({notice}/{footer_note}) while preserving literal blank spacing"
  - "Out-of-today forecast date labels render weekday + abbreviated month + day ('Wed Jun 24') — D-06"
  - "status/next-fires timestamps humanized to local 24h 'HH:MM', raw ISO/UTC dropped — D-07 (embed <t:> markdown untouched)"
  - "HARD-UI-03 fully closed (F28/blanks/D-06/D-07 land here; F107/F11 landed in 33-05)"
affects: [phase-34-comprehensive-tests, phase-35-cleanup-sweep, discord-render-surface]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Empty-token blank-line collapse: line-by-line substitution in renderer.render — drop a line only when it carried a token AND rendered blank; never a literal blank line or a line with surviving content."
    - "Explicit weekday/month abbreviation tables (_ABBR/_MON_ABBR) for date labels — portable, never glibc-only %-d/%-m/%b directives."

key-files:
  created: []
  modified:
    - weatherbot/interactive/commands/forecast.py
    - templates/renderer.py
    - weatherbot/interactive/commands/status.py
    - weatherbot/interactive/state.py
    - templates/forecast-weekday-detailed.txt
    - templates/forecast-weekend-detailed.txt
    - templates/forecast-weekday-compact.txt
    - templates/forecast-weekend-compact.txt
    - tests/test_forecast_render.py
    - tests/test_command_views.py
    - tests/test_status.py
    - tests/test_golden_coverage_fill.py

key-decisions:
  - "F28 carrier: drop the duplicated header from the four forecast TEMPLATE bodies (templates/*.txt), keeping CommandReply.title as the single header. Cleaner than stripping tokens in forecast.py and keeps the render-boundary in the templates."
  - "Empty-token blank collapse implemented in the shared renderer.render (not a forecast-only post-pass) so any template with an empty trailing/interior token benefits; guarded to preserve literal blank spacing."
  - "D-07 scope held to the raw-ISO leak sites (status._fmt_epoch '%Y-%m-%d %H:%M UTC', state.next_fires .isoformat()). The {sent_at}/{checked_at} path (scheduler/context.py) already renders a humanized '7:30 AM' — NOT a raw-ISO leak — so it was left as-is (12h vs 24h is cosmetic style, out of the raw-ISO defect scope and outside the plan's files_modified)."

patterns-established:
  - "Golden regen discipline: regenerate via --snapshot-update, re-run to confirm GREEN, then diff the .ambr/.raw to prove the change is exactly the intended edits (removed header + D-06 labels + collapsed blanks)."

requirements-completed: [HARD-UI-03]

coverage:
  - id: D1
    description: "Forecast header appears exactly once per surface (no rendered body line equals the embed title) — F28."
    requirement: HARD-UI-03
    verification:
      - kind: unit
        ref: "tests/test_forecast_render.py#test_forecast_header_appears_once"
        status: pass
      - kind: unit
        ref: "tests/test_golden_embeds.py#test_weekday_forecast_detailed_embed_golden (regenerated golden)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Empty render tokens ({notice}/{footer_note}) leave no trailing/interior blank line; literal blank spacing preserved."
    requirement: HARD-UI-03
    verification:
      - kind: unit
        ref: "tests/test_forecast_render.py#test_empty_token_no_trailing_blank"
        status: pass
      - kind: unit
        ref: "tests/test_forecast_render.py#test_empty_token_interior_blank_collapsed"
        status: pass
    human_judgment: false
  - id: D3
    description: "Out-of-today forecast buckets render weekday + abbreviated month + day ('Wed Jun 24'); Today/Tomorrow unchanged — D-06."
    requirement: HARD-UI-03
    verification:
      - kind: unit
        ref: "tests/test_forecast_render.py#test_out_of_today_date_label"
        status: pass
    human_judgment: false
  - id: D4
    description: "status/next-fires timestamps render local 24h 'HH:MM' (raw ISO/UTC dropped); embed <t:> markdown unchanged — D-07."
    requirement: HARD-UI-03
    verification:
      - kind: unit
        ref: "tests/test_command_views.py#test_humanized_timestamp"
        status: pass
      - kind: unit
        ref: "tests/test_status.py#test_next_fires_uses_running_next_run_time"
        status: pass
    human_judgment: false

# Metrics
duration: ~35min
completed: 2026-07-12
status: complete
---

# Phase 33 Plan 06: HARD-UI-03 Render-Formatting Slice Summary

**Forecast header de-duplicated to once-per-surface (F28), empty-token blank lines collapsed in the shared renderer, out-of-today date labels humanized to 'Wed Jun 24' (D-06), and status/next-fires timestamps humanized to local 24h '09:00' (D-07) — leaving the embed `<t:>` relative markdown untouched — closing HARD-UI-03.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-07-12T22:20Z (approx)
- **Completed:** 2026-07-12
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 12 source/template/test (+ 8 regenerated golden snapshots)

## Accomplishments
- **F28 duplicated header removed** — dropped the `📅 {title} — {location}` (detailed) / `{title} — {location} (…)` (compact) line from all four forecast `.txt` templates. The embed keeps its title; the CLI keeps its title print; the body no longer repeats it. No rendered body line equals the embed title.
- **Empty-token blank collapse** — `renderer.render` now drops a line only when it carried a `{token}` AND that token substituted to `""` (so `{notice}`/`{footer_note}` leave no trailing/interior blank), while a literal blank line (no token) — intentional spacing — is preserved.
- **D-06 date labels** — `forecast._day_label` out-of-today branch renders `weekday + abbreviated-month + day` (`Wed Jun 24`) via explicit `_ABBR`/`_MON_ABBR` tables (no glibc `%-d`/`%b`); Today/Tomorrow unchanged.
- **D-07 humanized timestamps** — `status._fmt_epoch` (`%Y-%m-%d %H:%M UTC` → `%H:%M`) and `state.next_fires` (`.isoformat()` → `%H:%M`) now emit a bare local 24-hour clock. The embed description `<t:unix:R>` markdown in `bot.py` is untouched (verified: `bot.py` not in the diff).
- **Golden regen** — 4 embed + 4 CLI forecast goldens regenerated; diffs are exactly the removed header line + D-06 label swaps + collapsed trailing blanks. Re-run GREEN post-regen (exit 0).

## Task Commits

Each task committed atomically (TDD):

1. **Task 1: RED regressions** - `f2cdd12` (test) — 5 failing tests: header-appears-once, empty-token no-trailing-blank, empty-token interior-collapse, out-of-today date label, humanized timestamp.
2. **Task 2: GREEN implementation + golden regen** - `9047fa8` (feat) — templates deduped, renderer blank-collapse, D-06 label, D-07 timestamps, 8 goldens regenerated, 2 pre-existing tests updated.

**Plan metadata:** _(final docs commit)_

## Files Created/Modified
- `templates/forecast-{weekday,weekend}-{detailed,compact}.txt` — removed the duplicated header line (F28 carrier).
- `templates/renderer.py` — `render` collapses empty-token blank lines (D-08).
- `weatherbot/interactive/commands/forecast.py` — `_MON_ABBR` table + D-06 out-of-today label f-string.
- `weatherbot/interactive/commands/status.py` — `_fmt_epoch` → local 24h `HH:MM` (D-07).
- `weatherbot/interactive/state.py` — `next_fires` → local 24h `HH:MM` (D-07).
- `tests/test_forecast_render.py`, `tests/test_command_views.py` — new regressions.
- `tests/test_status.py`, `tests/test_golden_coverage_fill.py` — updated two pre-existing assertions that pinned the old UTC/ISO/date-label formats (Rule 1).
- `tests/__snapshots__/test_golden_{cli,embeds}/…` — 8 regenerated forecast goldens.

## Decisions Made
- **F28 carrier = template edit.** Dropped the header line from the four `.txt` templates rather than un-wiring `title`/`location` tokens in `forecast.py`. The `header_values` dict still carries `title`/`location` harmlessly (templates simply no longer reference them). Cleanest single-source-of-truth change and keeps the render boundary in the templates.
- **D-07 scope held to raw-ISO leaks only.** `status._fmt_epoch` and `state.next_fires` were the actual raw-ISO/UTC leak sites. The `{sent_at}`/`{checked_at}` path (`scheduler/context.py`) already renders humanized `7:30 AM` — not a raw-ISO leak — and is outside the plan's `files_modified`; changing its 12h→24h style would cascade into 4+ deliberate `7:30 AM`/`7:00 AM` assertions (test_send_now/test_renderer/test_scheduler) for a cosmetic-only gain. Left as-is.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated two pre-existing tests pinning the pre-D-07 formats**
- **Found during:** Task 2 (D-07 timestamp change)
- **Issue:** `tests/test_golden_coverage_fill.py::test_fmt_epoch_none_yet` asserted `_fmt_epoch(0).endswith("UTC")`; `tests/test_status.py` asserted `"2026-06-20"`/`"2026-06-21"` in `next_fires`. Both pin the old raw-ISO/UTC forms the D-07 fix intentionally removes.
- **Fix:** Re-pointed them at the new `HH:MM` form (`_fmt_epoch(0)` matches `\d{2}:\d{2}`; `next_fires["Home"] == "09:00"`).
- **Files modified:** tests/test_golden_coverage_fill.py, tests/test_status.py
- **Verification:** both suites green.
- **Committed in:** `9047fa8` (Task 2 commit)

**2. [Rule 1 - Bug] Regenerated the 4 CLI stdout forecast goldens (beyond the plan's named golden set)**
- **Found during:** Task 2 (full-suite run after the fix)
- **Issue:** The plan's golden-regen command named only `tests/test_golden_embeds.py`, but the CLI stdout goldens (`tests/test_golden_cli.py`) render the SAME forecast templates, so F28/D-06/blank-collapse changed their output too (4 failing snapshots).
- **Fix:** Regenerated the 4 CLI goldens via `--snapshot-update`; diffs are exactly the removed header line + D-06 labels + collapsed blanks. CLI still prints its own title line 1 (its header), so "header once per surface" holds.
- **Files modified:** tests/__snapshots__/test_golden_cli/*.raw (×4)
- **Verification:** `test_golden_cli.py` green; full suite exit 0.
- **Committed in:** `9047fa8` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — pre-existing/collateral test-fixture updates required by the intended behavior change).
**Impact on plan:** No scope creep. Both are the necessary test-side follow-through of the D-06/D-07/F28 output changes.

## Issues Encountered
- **Syrupy "N snapshots failed" banner with exit 0** — the full suite prints "2 snapshots failed" but exits 0; these come from `tests/test_oracle_selfproof.py`, which itself passes (it deliberately exercises a snapshot-mismatch path to prove the oracle). Per the `pytest-snapshot-report-quirk` memory, trusted exit code (0) + the fact that only the 8 intended goldens are dirty. Not a real golden regression.

## Prohibitions honored
- Embed `<t:>` relative markdown (`bot.py:258`) **untouched** — `bot.py` is absent from the plan diff.
- Source diff touches **only** `weatherbot/` + `templates/` + `tests/` — no hub-source edit under `.venv/` or `../Reusable/`.
- Date/time formatters use explicit tables/`%H:%M` — no glibc-only `%-d`/`%-m`/`%b` directives.

## Threat surface
- No new network endpoints, auth paths, file access, or schema changes. T-33-06-01 (raw-ISO info-disclosure) mitigated by the D-07 humanization; T-33-06-02 (golden tamper) mitigated by the verified, intentional regen. No install checkpoints (no package installs).

## Next Phase Readiness
- **HARD-UI-03 fully closed** (F28/blanks/D-06/D-07 here + F107/F11 in 33-05). ROADMAP plan 33-06 and the HARD-UI-03 requirement can be marked complete.
- Phase 33 complete pending the autonomous Gate-1 behavioral verification of the interactive/render surface. No blockers.

## Self-Check: PASSED

- SUMMARY.md present.
- Commits `f2cdd12` (test/RED), `9047fa8` (feat/GREEN) present in git log.
- All modified source files present on disk.
- TDD gate compliance: `test(...)` RED commit precedes `feat(...)` GREEN commit.

---
*Phase: 33-interactive-panel-robustness*
*Completed: 2026-07-12*
