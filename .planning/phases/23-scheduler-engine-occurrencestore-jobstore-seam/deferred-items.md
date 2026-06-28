# Deferred Items — Phase 23

## Out-of-scope discoveries (do NOT fix in this plan)

- **Pre-existing syrupy "2 snapshots failed" report-summary line.** Present on the
  full-suite run BEFORE any Phase-23 test files were added (verified by running the
  suite with `--ignore=tests/test_scheduler_engine.py --ignore=tests/test_ports.py`:
  still `740 passed, 2 snapshots failed`). These are syrupy "unused snapshot"
  detections — stored snapshots no test asserts against in a given run — not a test
  failure (`748 passed` / `0 failed`). Unrelated to the scheduler/ports extraction.
  Triage separately (likely `--snapshot-update` or a stale `.ambr` prune).
