# Phase 12 — Discussion Log

**Date:** 2026-06-18 · batch-discussed alongside phases 13–15 (front-loaded for a chained build).

| Gray area | Options presented | Decision |
|-----------|-------------------|----------|
| Command naming & default location | short names + default loc / short names require loc / let-me-name | **Short names + default loc** — `!uv`/`!wind`/`!alerts`/`!sun`/`!status`/`!locations`/`!help`/`!next-cloudy`; loc commands default to the default location |
| `status` content | next-send-per-loc / alive+uptime / bot+monitor state / last-briefing (multi) | **All four** |
| `next-cloudy` granularity | daily 8-day / daytime-weighted / hourly-48h-then-daily | **Hybrid (daytime-weighted + hourly near-term)**; configurable threshold default 60% |
| `help` format | grouped one-line / flat list | **Grouped, one line each**, same content CLI + Discord |

Notes: registry is the single source for Discord dispatch, CLI subparsers, and auto-generated `help`. All commands inherit the operator guard ladder + failure isolation (CMD-16).
