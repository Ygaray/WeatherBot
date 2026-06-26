---
phase: 18-persistence-summon-lifecycle-restart-durability
verified: 2026-06-26T00:00:00Z
status: human_needed
score: 11/11 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification: # Deferred Gate-2 (milestone-close) live-restart UAT on host yahir-mint — mechanism unit-verified in source + tests; live re-bind/reconcile only observable against a live gateway
  - test: "Deploy panel.py/bot.py + add [bot] panel_channel_id to config.toml; sudo systemctl restart weatherbot; tap every button + the dropdown on the already-pinned panel."
    expected: "Every component routes to its callback — no 'interaction failed'. (SC#1 — persistent-view re-bind by custom_id across a real process restart.)"
    why_human: "add_view re-bind is only observable against a live Discord gateway client after a real daemon restart; the gateway-free unit suite proves is_persistent()==True + setup_hook registration but cannot exercise the live click route."
  - test: "Select a non-default location on the panel; sudo systemctl restart weatherbot; tap a location-taking button."
    expected: "The tap uses locations[0] (the documented default-on-restart selection). (SC#3.)"
    why_human: "Default-on-restart selected-location state is only observable across a real process restart with live gateway interaction."
  - test: "After the restart, run !panel again in the panel channel."
    expected: "Exactly one pinned panel remains; any stray bot-owned panels are removed. (SC#2 live reconcile.)"
    why_human: "Idempotent reconcile against the live pinned state on the production host; unit tests prove the find-or-create-one/delete-extras logic but not the live channel outcome."
---

# Phase 18: Persistence + Summon/Lifecycle (Restart Durability) Verification Report

**Phase Goal:** The pinned panel keeps working after a bot restart/deploy — `PanelView` registered as a persistent view (`timeout=None` + static `custom_id`s + `add_view` in `setup_hook`, not `on_ready`); an idempotent `!panel` summon finds-or-creates exactly one panel, pins it, cleans up strays; required channel permissions checked with a CRITICAL log if missing. Resolves the persist-vs-recreate design decision; verified by a live `systemctl restart` UAT on host `yahir-mint`.
**Verified:** 2026-06-26
**Status:** human_needed (all mechanisms VERIFIED in code + tests; 3 live cross-restart items deferred to Gate-2 milestone-close per project two-gate UAT policy)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | `[bot]` table requires both `operator_id` and `panel_channel_id`; unknown key still fails loud (`extra=forbid`) | ✓ VERIFIED | `models.py:384-387` — `model_config=ConfigDict(extra="forbid", frozen=True)`, `panel_channel_id: int` (required). Tests in test_models/test_config pass (138 targeted green). |
| 2 | `panel_channel_id` threads config → daemon → BotThread → build_client | ✓ VERIFIED | `daemon.py:1594-1601` passes `panel_channel_id=config.bot.panel_channel_id`; `bot.py:489` (build_client), `bot.py:574,582` (BotThread forwards it). `test_bot_thread_forwards_panel_channel_id`, `test_build_client_accepts_panel_channel_id` pass. |
| 3 | PanelView registered via `add_view` in `setup_hook` (NOT `on_ready`); re-binds by custom_id after restart | ✓ VERIFIED | `bot.py:521-538` `@client.event async def setup_hook()` → `client.add_view(PanelView(...))`, deferred import. `test_setup_hook_registers_panel_view_once` (exactly one) + `test_on_ready_does_not_register_view` (zero) pass. |
| 4 | Fresh PanelView `is_persistent() == True` (timeout=None + static custom_ids) | ✓ VERIFIED | `panel.py:204` `super().__init__(timeout=None)`; static `wb:` custom_ids. `test_freshly_built_view_is_persistent_and_defaults_location` passes. |
| 5 | `_is_owned_panel` matches only author==bot AND a `wb:` child custom_id; defensive getattr walk | ✓ VERIFIED | `panel.py:108-133` marker-strict, defensive `getattr` walk. `test_is_owned_panel_matches_*`, `test_is_owned_panel_rejects_*`, `test_is_owned_panel_does_not_raise_on_childless_row` pass. |
| 6 | `!panel` with no valid panel posts+pins a fresh one — exactly one bot-owned panel results | ✓ VERIFIED | `bot.py:321-326` create path. `test_panel_create_posts_and_pins_when_no_match` (send+pin called, created copy) passes. |
| 7 | `!panel` with ≥1 valid panel reuses first in place (edit) + deletes extras — exactly one remains (SC#2) | ✓ VERIFIED | `bot.py:329-338` edit-first + delete-strays. `test_panel_reuse_edits_in_place_single_match` + `test_panel_strays_deleted_keeps_exactly_one` (edit p1, delete p2/p3, no unpin, count copy) pass. |
| 8 | Missing any D-10 perm → posts/pins NOTHING, CRITICAL log naming missing perm(s), tells operator (SC#4) | ✓ VERIFIED | `bot.py:291-302` eager preflight, refuse-before-write. `test_panel_perms_missing_pin_refuses_with_named_perm` passes. |
| 9 | `discord.Forbidden` on any write after passing preflight → caught, CRITICAL, no bubble (TOCTOU backstop) | ✓ VERIFIED | `bot.py:339-347` per-write `except discord.Forbidden` → CRITICAL → return. `test_panel_forbidden_write_is_caught_and_logged` passes. |
| 10 | Unset/inaccessible `panel_channel_id` → clear message naming `[bot] panel_channel_id` + restart, no crash (D-04) | ✓ VERIFIED | `bot.py:276-289` `guild.get_channel(...) is None` → log + `_PANEL_CHANNEL_UNCONFIGURED` + return (never `.pins()` on None). `test_panel_channel_missing_aborts_without_crash` passes. |
| 11 | `!panel` is operator-gated in on_message and does NOT route through dispatch_spec/registry (D-07) | ✓ VERIFIED | `bot.py:403-419` guard ladder (drop bots, drop non-operator, require `!`) then `if content.strip() == "!panel"` dispatched to `_handle_panel_summon` BEFORE the registry parse. |

**Score:** 11/11 truths verified (0 present, behavior-unverified). Every behavior-dependent truth (state transition / cancellation / cleanup invariant) is backed by a passing named behavioral test.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `weatherbot/config/models.py` | `BotConfig.panel_channel_id: int` | ✓ VERIFIED | Line 387; required int, extra=forbid/frozen unchanged. |
| `weatherbot/interactive/panel.py` | `_PANEL_MARKER` + `_is_owned_panel` | ✓ VERIFIED | Lines 108, 111-133; marker-strict + defensive walk. |
| `weatherbot/interactive/bot.py` | `setup_hook add_view` + `panel_channel_id` threading + `!panel` summon branch | ✓ VERIFIED | setup_hook 521-538; build_client/BotThread params; `_handle_panel_summon` 240-347; `!panel` branch 419-432. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `daemon.py` | `bot.py` | `BotThread(..., panel_channel_id=config.bot.panel_channel_id)` → `build_client(..., panel_channel_id=...)` | ✓ WIRED | daemon.py:1598; bot.py:582 forwards into build_client. |
| `bot.py setup_hook` | `panel.py PanelView` | `client.add_view(PanelView(...))` with deferred import | ✓ WIRED | bot.py:528-538; breaks the panel.py→bot.py render_embed cycle. |
| `bot.py on_message` | `panel.py _is_owned_panel` | `[m async for m in channel.pins() if _is_owned_panel(m, me)]` | ✓ WIRED | bot.py:320; deferred import at 270. |
| `bot.py !panel branch` | discord channel writes | `channel.permissions_for(guild.me)` preflight + per-write `try/except discord.Forbidden` | ✓ WIRED | bot.py:293-294 preflight; 317-347 write block + Forbidden catch. |

### Behavioral Spot-Checks (Gate 1 — gateway-free unit suite)

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Targeted phase files green | `pytest tests/test_bot.py tests/test_panel.py tests/test_config.py tests/test_models.py -q` | 138 passed | ✓ PASS |
| Behavior-dependent named tests | 9 named tests (setup_hook, channel-missing, perms, forbidden, create, reuse, strays, marker-skip, is_persistent) | 9 passed | ✓ PASS |
| Full suite (no regression) | `pytest -q` | 622 passed | ✓ PASS |
| Source lint | `ruff check weatherbot` | All checks passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| PANEL-09 | 18-01 | Pinned panel buttons keep working after restart (persistent views) | ✓ SATISFIED | setup_hook add_view (truth 3), is_persistent True (truth 4); cross-restart live tap = deferred Gate-2 SC#1. REQUIREMENTS.md:26 marked Complete, mapped to Phase 18. |
| PANEL-01 | 18-02 | Idempotent pinned control-panel summon — exactly one, strays cleaned | ✓ SATISFIED | create/reuse/delete-extras (truths 6,7), perms+abort+Forbidden (truths 8-10). REQUIREMENTS.md:15 marked Complete, mapped to Phase 18. |

Both phase requirement IDs (PANEL-01, PANEL-09) appear in PLAN frontmatter AND in REQUIREMENTS.md mapped to Phase 18. No orphaned requirements.

### Prohibitions (must-NOT) — all honored

| Prohibition | Status | Evidence |
| ----------- | ------ | -------- |
| MUST NOT register add_view in on_ready | ✓ HELD | Registration only in setup_hook; `test_on_ready_does_not_register_view` asserts on_ready calls add_view zero times. |
| MUST NOT import PanelView at module top (cycle) | ✓ HELD | Deferred imports at bot.py:528 (setup_hook) and 270 (summon helper). |
| MUST NOT add new persisted state (no JSON/SQLite) — D-02 | ✓ HELD | No .json/.sqlite/.db files in phase commits; design resolved as recreate/scan, not persist message_id. |
| MUST NOT add a new dependency / bump discord.py / add an intent | ✓ HELD | pyproject.toml/uv.lock untouched in all 5 feat commits. |
| MUST NOT check manage_messages for pin (use pin_messages) — D-10 | ✓ HELD | `_REQUIRED_PANEL_PERMS` uses `pin_messages` (bot.py:83); the only two `manage_messages` hits are warning comments (74-76). |
| MUST NOT `await channel.pins()` (use async for) — D-03 | ✓ HELD | bot.py:320 `[m async for m in channel.pins() ...]`. |
| MUST NOT unpin-only a stray — delete() it — D-06 | ✓ HELD | bot.py:334 `await extra.delete()`; `test_panel_strays_deleted_keeps_exactly_one` asserts `.pin` not awaited on strays. |
| MUST NOT identify a panel by author alone — D-05 | ✓ HELD | `_is_owned_panel` requires author==bot AND wb: child; `test_panel_bot_pin_without_marker_is_never_touched` passes. |
| MUST NOT route !panel through dispatch_spec — D-07 | ✓ HELD | Branch dispatched before registry parse (bot.py:419). |
| MUST NOT post a panel before preflight passes (no orphan) — SC#4 | ✓ HELD | Preflight refuse-before-write at bot.py:295-302. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none in phase-18 source) | — | — | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER in any modified source file. |

A `ruff format` drift exists at `models.py:149` (`_variant_valid` f-string), but it is Phase-13 code OUTSIDE the lines this phase touched — pre-existing, logged in `deferred-items.md`, not a Phase-18 gap.

### Design Decision Resolution

The phase's open design decision — persist `message_id`/selected-location durably vs. recreate-on-restart — is RESOLVED as **recreate / find-by-scan with no new persisted state**: PanelView re-binds by static `custom_id` via `add_view` (no stored message_id needed), `!panel` re-finds its panel by scanning pins (`_is_owned_panel`), and selected-location defaults to `locations[0]` on restart (D-08). No JSON/SQLite added (D-02 held).

### Human Verification Required (Deferred Gate-2, milestone-close — host `yahir-mint`)

Per the project two-gate UAT policy, these 3 live cross-restart items are deferred milestone-close obligations, NOT per-phase blockers. Each mechanism is unit-verified in source + tests; only the live gateway re-bind/reconcile observation remains:

1. **Persistent-view re-bind (SC#1)** — restart the daemon, tap every button + dropdown on the pinned panel; expect no "interaction failed".
2. **Default-on-restart location (SC#3)** — select a non-default location, restart, tap a location-taking button; expect `locations[0]`.
3. **Live idempotent reconcile (SC#2)** — re-run `!panel` after restart; expect exactly one pinned panel, strays removed.

### Gaps Summary

No gaps. All 11 must-have truths, all 3 artifacts, all 4 key links, all 10 prohibitions, and both requirement IDs verify against the codebase with passing behavioral tests (622-test full suite green, 0 regressions; code review found 0 BLOCKER/critical defects). The phase goal's mechanisms are fully implemented and unit-proven. Overall status is `human_needed` solely because three success criteria (SC#1, SC#3, and the live SC#2 reconcile) assert cross-process-restart runtime behavior against a live Discord gateway, which the gateway-free unit suite cannot exercise — these are correctly scoped as deferred Gate-2 obligations per the project's two-gate UAT policy, not as failures.

---

_Verified: 2026-06-26_
_Verifier: Claude (gsd-verifier)_
