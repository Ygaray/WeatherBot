# Phase 19 — Deferred Items

Out-of-scope discoveries logged during execution (not fixed — Rule scope boundary).

| Item | Found during | File | Notes |
|------|--------------|------|-------|
| Ruff F841 `unused variable view` in `test_dropdown_rederives_on_hot_reload` | 19-02 Task 3 | `tests/test_panel.py:194` | Pre-existing Phase-17 test node (identical in commit before this plan). Test passes; the node rebinds `rebuilt` and reads from it, leaving the earlier `view` assignment unused. Out of scope for PANEL-07 (touches an unrelated Phase-17 node). Trivial: assign to `_` or drop the line. |
