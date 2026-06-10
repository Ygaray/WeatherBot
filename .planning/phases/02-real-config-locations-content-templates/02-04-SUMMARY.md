---
phase: 02-real-config-locations-content-templates
plan: 04
subsystem: cli/operability
tags: [geocode, check, reachability-probe, loc-03, conf-05, conf-03, d-04, d-12, pitfall-1]
requires:
  - weatherbot/weather/client.py (geocode + fetch_onecall from 02-02)
  - weatherbot/config/loader.py (assert_unique_names + resolve_location)
  - weatherbot/config/models.py (Location timezone/units validators from 02-03)
  - templates/renderer.py (validate_template + CANONICAL from 02-03)
provides:
  - "weatherbot --geocode \"City, ST\": setup-time lat/lon lookup -> paste-ready [[locations]] snippet (never writes config, never on send path)"
  - "weatherbot --check: D-12 four-step validation (config+template, unique-names, resolve, ONE reachability probe) with no delivery"
  - do_geocode / do_check handlers (injectable client/channel for offline tests)
  - send_now templates_dir param (template pre-flight aborts on non-canonical token)
affects:
  - Phase 02 close (CONF-05 --check and LOC-03 --geocode are the last two phase requirements)
tech-stack:
  added: []
  patterns:
    - "argparse.SUPPRESS + hasattr(args, ...) dispatch model extended to --geocode/--check (mirrors --send-now)"
    - "--check 401/403 raises a subscription-not-active/not-propagated message WITHOUT echoing the key (Pitfall 1 / T-04-02)"
    - "handlers take an injectable client/channel so the whole CLI runs offline in tests"
key-files:
  created: []
  modified:
    - weatherbot/cli.py
    - tests/test_cli.py
decisions:
  - "D-04 enacted: --geocode prints only — never writes config; the send path never geocodes (LOC-03), so quota protection holds by construction."
  - "D-12 enacted: --check runs config+template validation, unique-names, per-location resolve, and exactly ONE live One Call reachability probe, delivering no briefing (CONF-05)."
  - "Pitfall 1 mitigation: a 401/403 from the reachability probe reports subscription-not-active/not-yet-propagated distinctly from a generic error, never leaking the key (T-04-02)."
metrics:
  duration_min: 9
  completed: "2026-06-10"
  tasks: 2
  files_changed: 2
---

# Phase 2 Plan 04: Operability — --geocode + --check Summary

The operability slice closes the last two phase requirements (LOC-03 `--geocode`,
CONF-05 `--check`) and makes the migrated One Call pipeline operable end-to-end.
`weatherbot --geocode "City, ST"` resolves coordinates once at setup time and
PRINTS a paste-ready `[[locations]]` snippet — never writing config and never on
the send path. `weatherbot --check` validates the whole config (schema + IANA tz +
units via load, template placeholders, unique location names, per-location
resolve) and makes EXACTLY ONE live One Call reachability probe whose 401/403
distinguishes "subscription not active / not yet propagated" from a generic error
— all without delivering any briefing. The 6 Plan 02-01 CLI xfail scaffolds are
flipped to real passing tests with zero xfail markers remaining and the full suite
green at 91 passed.

## What Was Built

### Task 1 — --geocode / --check argparse args + handlers (RED 6d69831 / GREEN f72ec38)
- **weatherbot/cli.py:**
  - `do_geocode(query, *, settings=None, client=None) -> int`: builds the client
    from `settings` (or uses the injected one), calls `client.geocode(query)` ONCE,
    and prints each match as `f"{name}, {state}, {country} -> lat={lat}  lon={lon}"`
    plus a commented paste-ready `[[locations]]` snippet (name/lat/lon/timezone). It
    NEVER writes the config file and NEVER touches `send_now`. An HTTP error is
    logged outcome-only (status code, never the URL/key — T-04-01) and returns 1.
  - `do_check(*, config, settings=None, client=None, channel=None) -> int`:
    implements D-12 in order — (1) config already validated at load (IANA tz +
    units fired there) plus a non-empty locations guard; (2)
    `validate_template(load_template(config.template))`; (4a) `assert_unique_names`;
    (4b) `resolve_location` for each location; (3) ONE
    `client.fetch_onecall(config.locations[0], "imperial")` reachability probe
    wrapped so a 401/403 raises a "subscription not active or not yet propagated —
    wait a few hours and retry" `ValueError` (Pitfall 1 / T-04-02), other statuses
    re-raise. Delivers NOTHING (the optional `channel` is accepted only to assert it
    stayed empty). Returns 0 on success, 1 on any caught failure.
  - `send_now` gained an optional `templates_dir` param so a non-canonical template
    can be loaded from a temp dir and its pre-flight abort exercised (D-11).
  - `main`: added `--geocode QUERY` (SUPPRESS default) and `--check`
    (`store_true`, SUPPRESS default) alongside `--send-now`, dispatched via the
    existing `hasattr(args, ...)` model — `--geocode` loads ONLY secrets (no
    config/channel), `--check` loads config+settings then `do_check` (no channel),
    else the existing `--send-now` path.

### Task 2 — tests/test_cli.py flipped to passing, full suite (c4c9c8c)
- **tests/test_cli.py:** replaced the Plan 02-01 xfail scaffolds with real
  asserting tests using an injectable `_FakeClient` (records `geocode`/
  `fetch_onecall` calls, returns the `geocode_austin`/`geocode_ambiguous` and
  `onecall_*_clear` fixtures) and a `_FakeChannel` (proves `--check` delivers
  nothing). Cases: `test_geocode_prints_coords` (lat/lon + name + snippet, one
  geocode call), `test_geocode_ambiguous_lists_all_matches`,
  `test_send_now_never_geocodes` (geocode never called on the send path),
  `test_check_validates_config`, `test_check_bad_units_fails_before_network`,
  `test_check_bad_timezone_fails_before_network`,
  `test_check_reachability_one_call` (exactly ONE `fetch_onecall`, no delivery),
  `test_check_reachability_subscription_message` (401 -> non-zero),
  `test_check_unique_names`, `test_check_bad_template_fails`,
  `test_send_now_bad_template_aborts` (non-canonical `{temprature}` aborts before
  delivery). All xfail markers removed.

## Verification Results

- `uv run pytest tests/test_cli.py -x -q` -> 11 passed.
- `uv run pytest tests/test_cli.py -k "check or geocode" -q` -> 10 passed, 1 deselected.
- **Full suite** `uv run pytest -q` -> **91 passed** (was 80 passed + 6 xfailed; the
  6 CLI scaffolds are now real passing tests). No xfail markers remain anywhere.
- `grep -c "xfail" tests/test_cli.py` -> 0 (markers and docstring mentions both gone).
- `grep -c "geocode" weatherbot/cli.py` -> 14 (handler + dispatch + client seam).
- `grep -c "do_check\|--check" weatherbot/cli.py` -> 5.
- Neither `do_geocode` nor `do_check` calls `send_now` (verified by grep — only
  docstrings/comments and the `main` send dispatch reference it).
- `uv run ruff check weatherbot/cli.py tests/test_cli.py` -> All checks passed.

## Deviations from Plan

None — plan executed exactly as written.

The plan's handler signatures (`do_geocode(query, *, settings, client=None)` /
`do_check(*, config, settings, client=None)`) were implemented with `settings`
made OPTIONAL (defaulting to `None`) so an injected `client` alone suffices in
tests — this is the documented "or uses the injected one" branch, not a behavior
change. `do_check` also accepts an optional `channel` purely to assert non-delivery,
matching the plan's "delivering NO briefing (never builds/uses a channel)" intent.

## Manual-Only Verifications (deferred to live smoke, per 02-VALIDATION.md)

- Live `uv run weatherbot --check` against a real `.env`: confirm "reachable" when
  the One Call subscription is active and the distinct not-active/not-propagated
  message otherwise.
- Live `uv run weatherbot --geocode "Austin, TX"`: confirm paste-ready lat/lon.

## Self-Check: PASSED
- FOUND: weatherbot/cli.py (modified — do_geocode/do_check/templates_dir/dispatch)
- FOUND: tests/test_cli.py (modified — 11 real tests, 0 xfail)
- FOUND commits: 6d69831 (Task 1 RED test), f72ec38 (Task 1 GREEN feat), c4c9c8c (Task 2 test)
- FOUND: full suite green at 91 passed, 0 xfailed
