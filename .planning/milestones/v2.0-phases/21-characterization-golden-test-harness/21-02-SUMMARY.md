---
phase: 21-characterization-golden-test-harness
plan: 02
subsystem: testing
tags: [syrupy, golden-snapshot, characterization, time-machine, discord-embed, custom-id, oracle-selfproof, interactive-panel]

# Dependency graph
requires:
  - phase: 21-01
    provides: "tests/conftest.py shared harness (FROZEN epoch 1781960400, json_snapshot/bytes_snapshot fixtures, embed_to_golden serializer); confirmed time_machine freezes discord.utils.utcnow() (A3); syrupy 5.3.4 use_extension(class) call shape (A1)"
provides:
  - "tests/test_golden_embeds.py: 11 byte-exact embed goldens — one per command (weather/uv/next-cloudy/sun/wind/alerts) + each forecast variant (weekday/weekend × detailed/compact); 📍-on once (location replies), 📍-off once (argless status)"
  - "tests/test_golden_custom_ids.py: inline wb:loc:select pin (D-03) + full ordered-set raw-bytes golden (D-02 SingleFile)"
  - "tests/test_oracle_selfproof.py: two standing meta-tests proving the oracle's teeth (field-reorder + custom_id byte-flip each raise AssertionError, D-12/SC2)"
  - "committed goldens under tests/__snapshots__/test_golden_embeds/ (11 .json) + tests/__snapshots__/test_golden_custom_ids/ (1 .raw)"
affects: [21-03, 21-04, 21-05, 27-discord-adapter]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Gateway-free REAL-render drive: lookup_weather(name, config, client=_FakeClient(fixtures)) → dispatch_reply(spec) → render_embed — pins production render of recorded data, not a hand-built embed"
    - "Forecast handlers driven with now=FROZEN (the documented test seam) to pin the day-window selection deterministically"
    - "Oracle self-proof = pytest.raises(AssertionError) over a perturbed REAL render (NOT xfail — inverted-reading, D-12-rejected)"

key-files:
  created:
    - tests/test_golden_embeds.py
    - tests/test_golden_custom_ids.py
    - tests/test_oracle_selfproof.py
    - tests/__snapshots__/test_golden_embeds/ (11 .json goldens)
    - "tests/__snapshots__/test_golden_custom_ids/test_all_custom_ids_byte_golden[all_custom_ids].raw"
  modified: []

key-decisions:
  - "status golden uses the daemon_state=None reply (the stable 'unavailable' CommandReply) — deterministic with no scheduler/heartbeat state, and it doubles as the 📍-off (location=None) cell (D-10)"
  - "alerts driven with onecall_imperial_alert.json paired with onecall_metric_clear.json — alerts read off raw_onecall_imp, so the metric half does not affect the alerts output; the dual fetch lookup_weather requires a metric payload regardless"
  - "JSONSnapshotExtension sorts TOP-LEVEL keys alphabetically (color/description/fields/title) but preserves the fields LIST order — the reorder-detection contract lives on the fields array, proven by the oracle self-proof"

requirements-completed: []  # BHV-02 partially satisfied (embeds + custom_ids surfaces); held open until 21-03/04/05 pin the remaining surfaces

# Metrics
duration: ~20min
completed: 2026-06-27
status: complete
---

# Phase 21 Plan 02: Interactive Render-Surface Goldens Summary

**Pinned the `interactive`-package render surfaces as byte-exact committed goldens — 11 full Discord embeds (one per command × 📍/Updated states, frozen clock), the panel `custom_id` byte strings (inline marker + full ordered raw-bytes set), and a standing two-test oracle self-proof that a field reorder / custom_id byte-flip each FAIL — all driven gateway-free through the REAL production render path, zero source change, zero regression (671 passed).**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-27
- **Tasks:** 3 executed (all `type="auto"`; Tasks 1 & 2 TDD: RED → `--snapshot-update` → zero-flake confirm)
- **Files created:** 3 test modules + 12 committed golden artifacts

## Accomplishments

- **Task 1 — embed goldens (`c38dda5`):** 11 named JSON-snapshot cases. Each builds a REAL `LookupResult` from a recorded `onecall_*` fixture via the shipped read-only `lookup_weather` core (injected fixture-returning client — the `test_cli.py` `_FakeClient` idiom), runs the REAL registry handler through the shared `dispatch_reply` ladder, and renders via `render_embed`. So the golden pins the actual production render of actual recorded data. 📍-on covered once (every weather/forecast case via `location="home"`); 📍-off once (`status` via `location=None`). Every render wrapped in `time_machine.travel(FROZEN, tick=False)` → the `Updated <t:1781960400:t> (<t:1781960400:R>)` stamp is a frozen literal with the `:t`/`:R` format string KEPT (over-scrubbing trap avoided, D-11).
- **Task 2 — custom_id pins (`c5cd269`):** inline `view.children[0].custom_id == "wb:loc:select"` (D-03) + a raw-bytes `SingleFileSnapshotExtension` golden of the full newline-joined ordered id set (D-02). Built gateway-free via the `test_panel.py` `_make_panel`/`_FakeHolder`/`_SpyCache` stand-ins. The golden carries every `wb:cmd:*` / `wb:fc:*` id verbatim, in child order.
- **Task 3 — oracle self-proof (`bf1ffec`):** two STANDING meta-tests. `test_field_reorder_is_caught` reverses the `fields` list of a REAL `build_inbound_embed → embed_to_golden` projection and asserts the order-preserving compare raises `AssertionError`. `test_custom_id_byteflip_is_caught` flips one byte of a REAL panel `custom_id` and asserts the raw-bytes compare raises. Both driven off real output (not hand literals), so they also trip if the render/panel is ever loosened. No `xfail` (D-12 inverted-reading rejection).
- **BHV-01 held:** full suite **671 passed** (656 from Wave 0 + 15 new), zero regression. `git diff --name-only weatherbot/` is **empty** (zero production-source change). `ruff check`/`format` clean on all three new files.

## Task Commits

1. **Task 1: Embed goldens** — `c38dda5` (test)
2. **Task 2: custom_id byte pins** — `c5cd269` (test)
3. **Task 3: Oracle self-proof** — `bf1ffec` (test)

## Acceptance Criteria — all met

| Criterion | Result |
|-----------|--------|
| `uv run pytest tests/test_golden_embeds.py -q` passes, zero `--snapshot-update` on 2nd run | ✅ 11 passed (zero-flake confirmed) |
| `grep -rl ':R>' tests/__snapshots__/test_golden_embeds/` non-empty | ✅ all 10 location-bearing goldens carry the `:R>` format (status carries the stamp too) |
| `grep -rEi 'appid\|webhook\|[A-Za-z0-9_-]{30,}' tests/__snapshots__/test_golden_embeds/` no hit (V7) | ✅ NO SECRET HITS |
| `uv run pytest tests/test_golden_custom_ids.py -q` passes, 2nd run no update | ✅ 2 passed (zero-flake) |
| `grep -rc 'wb:cmd:weather' tests/__snapshots__/test_golden_custom_ids/` ≥ 1 | ✅ 1 |
| `uv run pytest tests/test_oracle_selfproof.py -q` passes | ✅ 2 passed |
| `grep -c 'pytest.raises(AssertionError)' tests/test_oracle_selfproof.py` ≥ 2 | ✅ 5 |
| `grep -c 'xfail' tests/test_oracle_selfproof.py` == 0 | ✅ 0 |

## Decisions Made

- **`status` golden uses the `daemon_state=None` reply** — the stable "Status unavailable — no daemon state…" `CommandReply`, deterministic with no scheduler/heartbeat dependency, which simultaneously serves as the 📍-OFF (`location=None`) cell of D-10 (the description carries only the frozen `Updated` stamp, no 📍 line).
- **`alerts` driven with `onecall_imperial_alert.json` + `onecall_metric_clear.json`** — `alerts` reads off `raw_onecall_imp`, so the metric half is irrelevant to its output, but the dual-fetch `lookup_weather` requires a metric payload regardless. The golden pins the real "Heat Advisory" event + its location-local window.
- **JSONSnapshotExtension sorts top-level keys alphabetically** (`color`/`description`/`fields`/`title`) but PRESERVES the `fields` list order. The load-bearing reorder-detection contract lives on the `fields` array — explicitly proven by `test_field_reorder_is_caught` (Task 3), so the alphabetized top-level key order does not weaken the field-order pin.

## Deviations from Plan

**1. [Rule 3 - Blocking] Removed the literal token `xfail` from a docstring to satisfy the strict acceptance grep.**
- **Found during:** Task 3.
- **Issue:** The plan's acceptance criterion is `grep -c 'xfail' tests/test_oracle_selfproof.py == 0`. My first draft explained the design choice with the phrase "Deliberately NOT `xfail(strict=True)`" in the module docstring — a documentation reference to the D-12-rejected approach, NOT an actual marker. But the strict grep counts ANY occurrence of the substring, so it reported `1` and would have failed acceptance.
- **Fix:** Reworded the docstring to "Deliberately NOT an expected-failure marker (that reads inverted…)" — preserving the rationale without the literal token. The test behavior is unchanged.
- **Files modified:** tests/test_oracle_selfproof.py (docstring only).
- **Verification:** `grep -c 'xfail' tests/test_oracle_selfproof.py` → `0`; `grep -c 'pytest.raises(AssertionError)'` → `5`; `2 passed`.
- **Committed in:** `bf1ffec` (Task 3 commit — the reword happened before the commit).

**Total deviations:** 1 auto-fixed (1 blocking). No scope creep — the surface is exactly as specified.

## Known Stubs

None. Every golden is driven through the real production render of recorded data; no placeholder/empty-data path exists in these tests.

## Threat Flags

None. Purely additive test infrastructure — no new network endpoint, auth path, or schema change. The only trust-boundary concern (T-21-02: secrets in committed goldens) was mitigated: the V7 secret-scan grep returns no hit, and the embeds snapshot only rendered fields (never the request URL carrying `appid`).

## Issues Encountered

None beyond the single deviation above. The gateway-free REAL-render drive (`lookup_weather` + `dispatch_reply` + `render_embed`) was spiked before writing the test file and worked first try; the FROZEN epoch `1781960400` matched Wave-0 exactly.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Plans 21-03/04/05 unblocked.** The shared `embed_to_golden` / `json_snapshot` / `bytes_snapshot` harness is proven against the real `interactive` render path, and the oracle self-proof now stands guard over every golden's comparison teeth.
- **BHV-02 partially satisfied** (embed + custom_id surfaces pinned). The schedule/DB/CLI surfaces (21-03), exception-identity pins (21-04), and the one-time branch-coverage audit (21-05) remain to complete the characterization harness.

## Self-Check: PASSED

- Created files verified on disk: `tests/test_golden_embeds.py`, `tests/test_golden_custom_ids.py`, `tests/test_oracle_selfproof.py`, 11 embed `.json` goldens, 1 custom_id `.raw` golden, this SUMMARY.
- Commits verified in git log: `c38dda5` (Task 1), `c5cd269` (Task 2), `bf1ffec` (Task 3).
- Full suite: 671 passed; `git diff --name-only weatherbot/` empty.

---
*Phase: 21-characterization-golden-test-harness*
*Completed: 2026-06-27*
