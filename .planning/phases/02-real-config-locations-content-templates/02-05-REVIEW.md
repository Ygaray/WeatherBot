---
phase: 02-05-real-config-locations-content-templates
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - weatherbot/weather/models.py
  - weatherbot/cli.py
  - config.example.toml
  - tests/test_models.py
  - tests/test_send_now.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 02-05: Code Review Report

**Reviewed:** 2026-06-10
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

This gap-closure threads a per-location `units` override end-to-end so `--send-now`
produces a correctly-united briefing per location, and guards `_hints` against
degraded payloads (WR-01). The core change is sound and well-tested: the
`primary` display axis is threaded `config → cli.send_now → Forecast.from_payloads`,
sourced from the pydantic-validated `Location.units`, and the dual-fetch
single-round contract (DATA-03) is preserved. All 20 tests in scope pass, and the
Discord embed inherits the override for free because it consumes the same
`*_display` properties.

No blockers. Three warnings concern robustness gaps the diff introduced or
deliberately left in place: the `primary` selection axis is unvalidated at the
`Forecast` boundary and silently falls back to imperial for any non-`"metric"`
string; the WR-01 fix guards hints but deliberately keeps `or 0.0` on display
fields, which can render a self-contradictory unit pair (`0°F (19°C)`) on a
partially-degraded payload; and `_check` does not exercise a metric location, so a
units-override regression would not be caught by `--check`. Two info items note a
test-fixture mislabeling and a config-comment nuance.

## Warnings

### WR-01: `primary` selection is unvalidated and silently falls back to imperial

**File:** `weatherbot/weather/models.py:228-246`, `weatherbot/cli.py:114`
**Issue:** The display methods branch on `self.primary == "metric"` and treat
every other value — including typos, `"Metric"`, `"IMPERIAL"`, `""`, or any future
unit string — as imperial. `from_payloads(primary=...)` accepts an arbitrary
`str` with no validation. In the current production path this is contained because
`location.units` is pydantic-validated to `{"imperial", "metric", None}` and
`cli.py:114` coalesces `None → "imperial"`, so only two valid values can reach the
model. But the contract is fragile: the model silently mis-renders rather than
failing loud, and the `== "metric"` equality (vs membership in a known set) means
any drift in the upstream validator or a future caller passing the value through a
different path produces a silently-wrong briefing — exactly the failure class
CR-01 was meant to eliminate.
**Fix:** Validate `primary` at the model boundary (fail loud on an unknown value)
and branch on an explicit imperial-vs-metric decision rather than treating
"not metric" as imperial:
```python
_VALID_PRIMARY = {"imperial", "metric"}

@classmethod
def from_payloads(cls, loc, onecall_imp, onecall_met, now_utc=None, primary="imperial"):
    if primary not in _VALID_PRIMARY:
        raise ValueError(f"primary must be one of {sorted(_VALID_PRIMARY)}, got {primary!r}")
    ...
```

### WR-02: WR-01 display fields coalesce a missing primary unit to a contradictory pair

**File:** `weatherbot/weather/models.py:186-192, 228-246`
**Issue:** The WR-01 change deliberately split behavior: hints read the
not-None-guarded raw imperial values, but the display fields keep `or 0.0`
(`feels_imp = feels_imp_raw or 0.0`, line 189). When the imperial payload omits
`feels_like`/`wind_speed` but the metric payload has it (a realistic partial-degrade,
since both payloads are independent fetches), the paired display renders a
self-contradictory value. Verified at runtime:
```
feels_like_display: 0°F (19°C)   # 0°F is -17°C, not 19°C
wind_display:       0 mph (3.6 m/s)  # 0 mph is not 3.6 m/s
```
This ships a briefing that looks authoritative but is internally inconsistent. The
hint guard correctly avoids fabricating a "cold" line from the coalesced `0.0`, but
the user still sees a wrong number. The diff touched exactly these lines, so the
inconsistency is in scope for this change.
**Fix:** Either propagate `None` into the display path and show a single-unit or
em-dash fallback when a side is missing, or derive the missing primary side from
the present secondary side. Minimal version — when one side is absent, render only
the available side instead of a mismatched pair:
```python
def _temp_str(self, imp, met):
    if imp is None and met is None:
        return "—"
    if self.primary == "metric":
        if met is None:
            return f"{round(imp)}°F"
        return f"{round(met)}°C" + (f" ({round(imp)}°F)" if imp is not None else "")
    if imp is None:
        return f"{round(met)}°C"
    return f"{round(imp)}°F" + (f" ({round(met)}°C)" if met is not None else "")
```
(This requires keeping `feels_imp`/`wind_imp` etc. as `float | None` on the
dataclass rather than coalescing to `0.0` at construction.)

### WR-03: `--check` never exercises a metric location, so a units regression escapes it

**File:** `weatherbot/cli.py:231`
**Issue:** `do_check` probes reachability with
`client.fetch_onecall(config.locations[0], "imperial")` only. It never builds a
`Forecast` and never renders, so the per-location `units` override — the exact
behavior this gap closes — is not validated by `--check`. The config example ships
a `units = "metric"` location specifically to demonstrate the feature, yet
`--check` would report "passed" even if the override silently regressed to inert
again (the original CR-01 bug). The end-to-end regression coverage lives only in
the pytest suite, not in the user-facing validation command.
**Fix:** Out of strict scope for this gap (no delivery is `--check`'s contract),
but consider having `--check` build a `Forecast` per location from the probe
payload (or a recorded sample) and assert `forecast.primary == (loc.units or
"imperial")`, so the override is validated without delivering. At minimum, document
that `--check` does not exercise units rendering.

## Info

### IN-01: Misleading test fixture pairing (imperial fixture used as metric input)

**File:** `tests/test_models.py:174-176, 181-184, 191-193, 207-208, 214-215`
**Issue:** Several hint/alert tests pass the same imperial fixture for BOTH the
imperial and metric arguments, e.g.
`_build(load_fixture, imp="onecall_imperial_highuv.json", met="onecall_imperial_highuv.json")`.
The tests pass because they assert only on imperial-driven content (hints/alerts
read imperial values), but feeding an imperial payload as the metric payload means
the metric display side of these forecasts is wrong. A future test that asserts
on `*_display` for these fixtures would silently inherit imperial numbers in the
metric slot.
**Fix:** Use the matching `onecall_metric_*.json` fixture for the metric argument
where one exists, or add metric fixtures for the highuv/extreme/alert/multialert
cases.

### IN-02: `from_payloads` always reads `alerts` from the imperial payload only

**File:** `weatherbot/weather/models.py:172`
**Issue:** `alerts = onecall_imp.get("alerts") or []` — alerts are sourced solely
from the imperial payload. This is correct today (alerts are unit-independent and
both payloads carry the same `alerts[]`), and not introduced by this diff, but it
is an implicit coupling: if the imperial fetch degrades while the metric one
succeeds, the alert line is lost even though the data was available. Noted for
awareness; no change required for this gap.

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
