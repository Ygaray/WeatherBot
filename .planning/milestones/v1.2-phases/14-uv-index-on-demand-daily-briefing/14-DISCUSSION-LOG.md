# Phase 14 — Discussion Log

**Date:** 2026-06-18 · batch-discussed alongside phases 12, 13, 15.

| Gray area | Options presented | Decision |
|-----------|-------------------|----------|
| Threshold default & scope | default-6 global+per-loc / default-3 global+per-loc / default-6 global-only | **Default 6, global only** — unifies the existing hint + briefing line + Phase 15 monitor |
| UV info extras (beyond current/max/crossing) | protect-window / peak-time / category-word (multi) | **All three** |
| Crossing-time precision | hourly / interpolated | **Interpolated (~minute)** |
| `uv` command depth | summary only / + hourly line | **Add compact hourly line** (briefing stays summary-only) |

Notes: configured threshold replaces the hardcoded `uvi_max >= 6` hint. WHO UVI category bands. Helper computing current/max/crossing/window/peak/category is reused by Phase 15.
