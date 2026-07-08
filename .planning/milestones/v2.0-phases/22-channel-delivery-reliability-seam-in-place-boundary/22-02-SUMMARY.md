---
phase: 22-channel-delivery-reliability-seam-in-place-boundary
plan: 02
subsystem: channels
tags: [channel-seam, relocation, import-hygiene, shim, byte-identical, grimp, ast-litmus]

# Dependency graph
requires:
  - phase: 22-channel-delivery-reliability-seam-in-place-boundary
    plan: 01
    provides: yahir_reusable_bot/ skeleton (channels/ subpackage) + three standing import-hygiene gates (grimp graph, isolated-import smoke, AST litmus) + Phase-21 738-test byte-identical oracle
provides:
  - "yahir_reusable_bot/channels/base.py — the ONE true text-only Channel ABC (send(text) -> DeliveryResult) + DeliveryResult, zero weather coupling (D-03)"
  - "yahir_reusable_bot/channels/__init__.py — subset export of Channel/DeliveryResult (DiscordWebhookChannel + build_channel stay app-side, D-04)"
  - "weatherbot/channels/base.py — app-side shim: re-exports module Channel/DeliveryResult, re-homes the briefing-capable Channel subclass with the send_briefing default + app-side Forecast import"
  - "channels seam of the grimp import-hygiene gate is now green (zero yahir_reusable_bot.channels.* -> weatherbot.* edges)"
affects: [22-03, 23, 24, 25, 26, 27, 28]

# Tech tracking
tech-stack:
  added: []
  patterns: [re-export shim keeps importers byte-identical, app-side briefing-capable subclass IS-A the one true module Channel (single-class invariant), TYPE_CHECKING Forecast import lives app-side to avoid a module->app edge]

key-files:
  created:
    - yahir_reusable_bot/channels/base.py
    - .planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-02-SELFUAT.md
  modified:
    - yahir_reusable_bot/channels/__init__.py
    - weatherbot/channels/base.py

key-decisions:
  - "Adopted RESEARCH Pattern 2 shape (a): weatherbot/channels/base.py exports a briefing-capable Channel SUBCLASS of the module's text-only Channel, so isinstance(ch, Channel) tests the one true class AND a non-Discord channel still inherits the send_briefing default (forced by test_channel.py:119)"
  - "Kept weatherbot/channels/base.py as a thin re-export shim (not deleted) so the five direct weatherbot.channels.base importers (cli.py:57, daemon.py:82, uvmonitor.py:44 under TYPE_CHECKING; test_config_holder.py:27, test_reliability.py:35) resolve byte-identically with zero edits"
  - "Forecast TYPE_CHECKING import re-homed APP-side in the shim so it does NOT re-introduce a module->app import edge (D-03 / T-22-04)"

requirements-completed: [SEAM-01]

# Metrics
duration: 4min
completed: 2026-06-27
status: complete
---

# Phase 22 Plan 02: Channel Seam Relocation (text-only Channel into the reusable module) Summary

**Moved the clean, text-only `Channel` ABC + `DeliveryResult` into `yahir_reusable_bot.channels` (dropping `send_briefing` and the `Forecast` import — the single change that satisfies the litmus and grimp gates at once), and re-homed the app-side `send_briefing` default behind a thin re-export shim so `weatherbot.channels` stays byte-identical for every importer — full 738-test oracle green, zero golden diff.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-27T23:32:27Z
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- Created `yahir_reusable_bot/channels/base.py` as the ONE true `Channel` (`send(text) -> DeliveryResult` only) + `DeliveryResult`, copied verbatim from the app source minus exactly two blocks: the `send_briefing` method (D-03 — kills the litmus signature hit) and the `if TYPE_CHECKING: from weatherbot.weather.models import Forecast` block (kills the only module→app grimp edge). Module source now contains neither `Forecast` nor `weatherbot`.
- Updated `yahir_reusable_bot/channels/__init__.py` to the SUBSET export `__all__ == ["Channel", "DeliveryResult"]` — `DiscordWebhookChannel` + `build_channel` intentionally stay app-side (D-04, Phase-27 home).
- Rewrote `weatherbot/channels/base.py` as a thin app-side shim: it re-exports the module `Channel`/`DeliveryResult` and exports a briefing-capable `Channel` **subclass** that re-adds the default `send_briefing(text, forecast) -> send(text)` plus the app-side `Forecast` annotation import. Because this app `Channel` IS-A the module `Channel`, there is still exactly ONE abstract `Channel` underneath (Pitfall 3).
- Confirmed the five direct `weatherbot.channels.base` importers and `weatherbot/channels/{__init__,discord,factory}.py` resolve through the shim with **zero source edits** — verified by the green focused suite, not assumed.
- Full oracle suite **738 passed** (exit 0) with **zero golden snapshot diff** (`git status --porcelain tests/__snapshots__/` empty). The channels seam of the grimp/litmus/isolated-import gate is now green.

## Task Commits

Each task was committed atomically:

1. **Task 1: Move Channel + DeliveryResult into the module (minus send_briefing + Forecast)** — `4ab8374` (feat)
2. **Task 2: Shim weatherbot.channels.base, re-home send_briefing app-side** — `c549083` (feat)
3. **Task 3: Self-UAT — full oracle suite byte-identical green, record Phase-27 hand-off** — `67d1cda` (test)

## Files Created/Modified
- `yahir_reusable_bot/channels/base.py` (created) — the one true text-only `Channel` ABC + `DeliveryResult` (zero weather coupling, D-03)
- `yahir_reusable_bot/channels/__init__.py` (modified) — subset export `["Channel", "DeliveryResult"]` (D-04)
- `weatherbot/channels/base.py` (modified) — app-side re-export shim + briefing-capable `Channel` subclass re-homing `send_briefing` + the app-side `Forecast` TYPE_CHECKING import
- `.planning/.../22-02-SELFUAT.md` (created) — Gate-1 self-UAT log + D-05 Phase-27 hand-off + deferred Gate-2 host obligation

## Decisions Made
- **RESEARCH Pattern 2 shape (a), not (b).** `test_channel.py:119` (`test_base_send_briefing_defaults_to_send_text`) subclasses the re-exported `Channel` and calls `.send_briefing(...)`, so a non-Discord channel MUST inherit a `send_briefing` default. Shape (a) — an app-side briefing-capable `Channel` base — is the only choice that satisfies this AND keeps the module `Channel` clean. Shape (b) (send_briefing only on `DiscordWebhookChannel`) would fail that test.
- **`weatherbot/channels/base.py` kept as a shim, not deleted.** Five direct `weatherbot.channels.base` importers exist; keeping the module importable (and re-exporting `Channel`/`DeliveryResult` from it) means zero call-site churn, which is what keeps the 738-test suite byte-identical.
- **`Forecast` import lives app-side.** Re-homing it into the app shim (under `TYPE_CHECKING`) preserves the `send_briefing` annotation without re-introducing the module→app edge the grimp gate exists to catch (D-03 / T-22-04).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Shim docstring tripped `test_base_module_has_no_embed_reference`**
- **Found during:** Task 2 (focused verify)
- **Issue:** `test_channel.py:140` asserts the literal string `DiscordEmbed` is absent from `weatherbot/channels/base.py` source. My first shim docstring spelled out "carries no ``DiscordEmbed`` reference" — the literal token tripped the substring assertion even though the shim has no actual embed code.
- **Fix:** Reworded the docstring to "carries no embed reference" (no literal `DiscordEmbed` token). Behavior unchanged; the shim still has zero embed logic.
- **Files modified:** weatherbot/channels/base.py
- **Verification:** `test_base_module_has_no_embed_reference` and the full focused suite (25 passed) green afterward.
- **Committed in:** `c549083` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug). No scope creep — the seam shape and the move are exactly as planned.

## Issues Encountered
- **Pre-existing cosmetic "2 snapshots failed" syrupy line.** `uv run pytest` prints `2 snapshots failed. 27 snapshots passed.` while reporting `738 passed` and exiting 0. This is syrupy's unused-snapshot accounting (same line on the 738 baseline, documented in 22-01-SUMMARY), not a test failure and not a golden diff — `git status --porcelain tests/__snapshots__/` is empty.
- **Plan's `(! grep .)` snapshot-gate one-liner is inverted** (same as noted in 22-01). The substantive criterion — empty `git status --porcelain tests/__snapshots__/` — is definitively met (verified via `od -c` empty + `wc -l` = 0). Documented, not a real failure.

## Known Stubs
None introduced by this plan. The two-home channel split below is intentional and named, not a stub.

## Phase-27 Hand-off (D-05) — temporary two-home split, BY DESIGN
The clean text-only `Channel` + `DeliveryResult` now live in `yahir_reusable_bot.channels`. The concrete `DiscordWebhookChannel` + its embed-building `send_briefing` override, plus the `build_channel` factory and the app-side `send_briefing` default, **intentionally remain app-side** (`weatherbot/channels/`). Relocating the concrete Discord channel + embed is Phase 27's named obligation — this two-home split is by design, NOT an incomplete extraction. The grimp/litmus/isolated-import gates stand guard against any silent module→app drift in the interim.

## Threat Flags
None. No new network endpoint, auth path, or trust-boundary surface introduced — this is a pure relocation. The webhook credential stays in the unmoved app-side `DiscordWebhookChannel._url` (T-22-05); the module `Channel`/`DeliveryResult` surface never references it.

## Next Phase Readiness
- The channel seam is byte-identical and gate-green; Plan 22-03 (reliability seam) can land the retry engine + `AlertSink` port into `yahir_reusable_bot/` with the same standing-gate validation.
- No blockers. Exactly one `Channel` class exists; `isinstance(ch, Channel)` is the loud regression guard against any future dual-definition.

## Self-Check: PASSED

All created/modified files exist on disk (`yahir_reusable_bot/channels/base.py`, `yahir_reusable_bot/channels/__init__.py`, `weatherbot/channels/base.py`, `22-02-SELFUAT.md`) and all three task commits (`4ab8374`, `c549083`, `67d1cda`) are present in git history.

---
*Phase: 22-channel-delivery-reliability-seam-in-place-boundary*
*Completed: 2026-06-27*
