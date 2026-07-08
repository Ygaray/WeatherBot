# Deferred Items — Phase 24

Out-of-scope discoveries logged during execution (NOT fixed; not caused by the current plan's changes).

## From Plan 24-01

- **Pre-existing test-ordering flake:** `tests/test_golden_coverage_fill.py::test_load_settings_no_env_file_uses_default`
  fails under the full random-ordered `uv run pytest` run but PASSES in isolation. Confirmed
  pre-existing at the pre-Plan-24 baseline (commit `3567e48`): the baseline full run also reports
  this hard failure plus the identical `2 snapshots failed. 27 snapshots passed.` syrupy summary.
  Root cause: env-var pollution / settings-default test ordering — unrelated to the config-reload
  seam. Out of scope for SEAM-04 (Rule: only auto-fix issues directly caused by the current task).
- **Syrupy "2 snapshots failed" summary line:** a pre-existing artifact (snapshots whose owning
  test is not executed in some collection orderings). Tally is byte-identical pre/post Plan-24
  (`2 failed / 27 passed` in both), so Plan 24 introduced zero golden diff. Not investigated
  further here; flag for a future test-hygiene pass if desired.
