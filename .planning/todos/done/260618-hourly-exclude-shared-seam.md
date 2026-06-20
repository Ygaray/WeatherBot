---
created: 2026-06-18
title: Widen One Call `exclude` to keep `hourly[]` (shared seam for next-cloudy + UV)
area: weather/client
resolves_phase: 12
files:
  - weatherbot/weather/client.py
  - tests/fixtures/onecall_*.json
  - tests/test_client.py
---

## Problem

`weatherbot/weather/client.py:58` (`fetch_onecall`) sends `"exclude": "minutely,hourly"`,
a v1.0 bandwidth trim from when the briefing only needed `current`/`daily[0]`/`alerts`.
v1.2 makes `hourly[]` required by three phases:

- **Phase 12** `next-cloudy` → `hourly[].clouds` (near-term half of the hybrid lookahead)
- **Phase 14** UV interpolation → `hourly[].uvi` (crossing time / protect window / peak)
- **Phase 15** UV monitor → reuses Phase 14's helper (same `hourly[].uvi`)

The trap: the 8 `tests/fixtures/onecall_*.json` also lack `hourly[]`, so UV/clouds logic
tested against them passes green against empty data — the gap stays hidden until a live
UAT on host `yahir-mint`.

## Solution (owned by Phase 12 — first phase to need it)

1. `weatherbot/weather/client.py`: change `"exclude": "minutely,hourly"` → `"exclude": "minutely"`; update the now-false docstring ("trims the unused minutely/hourly blocks"). ~48 hourly entries/fetch — trivial vs free-tier + the 10s timeout; same single fetch (no extra API call); `Forecast.from_payloads` is untouched.
2. Add realistic `hourly[]` (with `dt` + `clouds`) to the fixtures `next-cloudy` tests use.
3. Add a regression canary test: `fetch_onecall`'s parsed payload contains a non-empty `hourly[]` — guards Phases 14/15 against a future payload-trim edit.

## Split ownership (do NOT double-do)

- **Phase 12** owns the code change (#1), its own `clouds` fixtures (#2), and the canary (#3).
- **Phase 14** owns adding `hourly[].uvi` to the UV fixtures + a Wave-0 verify that `hourly[].uvi` is present before building UV interpolation.
- **Phase 15** owns nothing here — it only verifies (Phase-14 Dependency Contract).

See `12-CONTEXT.md` D-06, `14-CONTEXT.md` D-05, `15-CONTEXT.md` D-07, and the three phases' RESEARCH.md (Pitfall 1 in each).
