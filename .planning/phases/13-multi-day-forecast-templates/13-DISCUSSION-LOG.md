# Phase 13 — Discussion Log

**Date:** 2026-06-18 · batch-discussed alongside phases 12, 14, 15.

| Gray area | Options presented | Decision |
|-----------|-------------------|----------|
| Date window | remaining-roll-when-empty / always-next-full / remaining-no-roll | **Remaining now, roll forward when block empty** |
| Detailed per-day fields | wind / UV max / feels-like hi-lo / sunrise-sunset (multi) | **All four** (on top of baseline hi/lo + sky + rain%) |
| Day flags | multiple-appended-deduped / add-and-subtract / single | **Combination: multiple `+day`/`-day`, appended, deduped, calendar-sorted** |
| Day labels | relative+date / weekday+date / weekday-name | **Combination: relative ("Today"/"Tomorrow") then weekday+date** |

Notes: weekday = Mon–Fri, weekend = Fri–Sat–Sun; detailed default, `--compact`/`+compact` for compact; each type schedulable per-location with its own slots + variant; templates editable, per-day line code-rendered; reuses One Call `daily[]` (no new fetch).
