---
phase: quick-260626-uqp
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - weatherbot/interactive/bot.py
  - tests/test_bot.py
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
autonomous: true
requirements: [PANEL-01]

must_haves:
  truths:
    - "!panel always posts a FRESH panel as the newest message in the channel (appears at the bottom), then pins it"
    - "All prior bot-owned panels (the previously-pinned one + any strays) are DELETED after the fresh one is posted+pinned"
    - "Net result is exactly one pinned panel — moved to the channel bottom on every summon"
    - "No zero-panel window: the fresh panel is created+pinned BEFORE any old panel is deleted (create-before-delete, SC#4 no-orphan)"
    - "Every Phase-18 prohibition still holds: channel-abort (D-04), perm preflight incl. pin_messages (D-09/D-10), Forbidden TOCTOU backstop (D-09), marker-strict ownership (D-05), async-for pins (D-03), DELETE-not-unpin strays (D-06), operator-gate + no-dispatch_spec routing (D-07)"
  artifacts:
    - path: "weatherbot/interactive/bot.py"
      provides: "_handle_panel_summon step-3 always-recreate-at-bottom logic + _PANEL_RESUMMONED copy constant"
      contains: "_PANEL_RESUMMONED"
    - path: "tests/test_bot.py"
      provides: "Updated panel-summon tests for re-summon-to-bottom behavior"
  key_links:
    - from: "weatherbot/interactive/bot.py _handle_panel_summon"
      to: "channel.send + msg.pin + old.delete"
      via: "create-before-delete: send(embed,view) then pin() then delete all prior matches"
      pattern: "channel\\.send.*view=_build_view"
---

<objective>
Change `!panel` (PANEL-01) summon behavior from idempotent reuse-in-place to re-summon-to-bottom. Today `_handle_panel_summon` EDITS the existing pinned panel in place (`matches[0].edit(...)`), so on mobile the panel stays buried up-channel. After this change, `!panel` posts a FRESH panel as the newest message (bottom of channel), pins it, then deletes ALL prior bot-owned panels — keeping the "exactly one panel, strays cleaned" invariant while repositioning to the bottom every summon.

Purpose: The product owner wants the panel re-summoned to the channel bottom so it is reachable on mobile.
Output: Updated `_handle_panel_summon` step-3 block + copy constants, updated panel-summon tests, and planning-doc supersession notes.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@weatherbot/interactive/bot.py
@tests/test_bot.py
@tests/conftest.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Rewrite _handle_panel_summon step-3 to always-recreate-at-bottom + update copy constants</name>
  <files>weatherbot/interactive/bot.py</files>
  <action>
In `_handle_panel_summon` (bot.py), replace ONLY the step-3 find-or-reuse-in-place block (the `try:` block at lines ~367-388, from the `matches = [...]` comprehension through the `_PANEL_REUSED` else-branch — NOT the `except discord.Forbidden` handler that follows). The channel resolve (step 1), permission preflight (step 2), `_build_view`/`idle_embed` setup, and the `except discord.Forbidden` backstop all stay EXACTLY as-is.

New step-3 body inside the SAME `try:` (the Forbidden backstop must still wrap all writes):
1. Scan owned panels FIRST (unchanged D-03 async-for): `matches = [m async for m in channel.pins() if _is_owned_panel(m, me)]`.
2. Create-before-delete (no-orphan ordering, SC#4): post the fresh panel and pin it FIRST — `msg = await channel.send(embed=idle_embed, view=_build_view())` then `await msg.pin()` — so there is never a zero-panel window even if a later write fails.
3. THEN delete ALL prior owned panels in `matches` (the previously-pinned one + any strays): `for old in matches: await old.delete()`. Deleting the old pinned message also clears its pin, so net pins return to exactly one. Use DELETE, never unpin-only (D-06).
4. Send the operator a confirmation: when `matches` was empty use the existing `_PANEL_CREATED`; when there WERE prior panels send the re-summon copy. If more than one prior panel was cleaned, reflect the stray count.

Copy-constant changes (the panel copy block, ~lines 110-136):
- ADD a new constant `_PANEL_RESUMMONED = "Panel re-summoned — moved to the bottom of the channel."` (plain-text, emoji-free, identity-free, secret-free per the 18-UI-SPEC Copywriting Contract).
- REMOVE the now-unused `_PANEL_REUSED` constant (reuse-in-place is gone).
- Keep `_PANEL_CREATED` (still used for the no-prior case). Keep `_panel_strays_cleaned_copy(n)`; reuse it for the >1-prior case so the operator sees a non-secret count.

Confirmation-copy logic (suggested): if `not matches` → `_PANEL_CREATED`; elif `len(matches) > 1` → `_panel_strays_cleaned_copy(len(matches) - 1)` (one is the kept fresh panel, the rest were cleaned); else → `_PANEL_RESUMMONED`.

Update the `_handle_panel_summon` docstring step-3 line and the step-3 inline comment to describe always-recreate-at-bottom (drop the "reuse the survivor in place" wording). Do NOT change the docstring's steps 1-2 or the Forbidden-backstop comment.

PROHIBITIONS (do NOT regress — Phase-18 load-bearing): keep step-1 channel resolve/abort (D-04, `_PANEL_CHANNEL_UNCONFIGURED`); keep step-2 eager `permissions_for` preflight incl. `pin_messages` and refuse-before-write (D-09/D-10, SC#4); keep the outer per-write `except discord.Forbidden` TOCTOU backstop (D-09) wrapping ALL the new writes; keep `_is_owned_panel` marker-strict ownership (D-05); keep async-for `channel.pins()` (never `await channel.pins()`, D-03); keep DELETE-not-unpin (D-06). Do NOT touch PanelView, `_render_view`, the clone-routing fix, `dispatch_spec`, the registry, the scheduler/briefing spine, or `add_view` registration. The fresh panel must use `_build_view()` (the real PanelView) so it routes and static custom_ids keep add_view coverage post-restart.

Comment-text discipline: do NOT write the literal string `_PANEL_REUSED` into any comment or docstring after removing the constant (the grep gate in verify negative-greps for it).
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot &amp;&amp; grep -q "_PANEL_RESUMMONED" weatherbot/interactive/bot.py &amp;&amp; test "$(grep -v '^[[:space:]]*#' weatherbot/interactive/bot.py | grep -c '_PANEL_REUSED')" = "0" &amp;&amp; uv run ruff check weatherbot/interactive/bot.py &amp;&amp; uv run python -c "import weatherbot.interactive.bot"</automated>
  </verify>
  <done>`_PANEL_RESUMMONED` constant exists; `_PANEL_REUSED` is fully removed (0 non-comment references); module imports clean; ruff passes. The step-3 block posts+pins a fresh panel before deleting any prior owned panel, all inside the existing Forbidden try/except.</done>
</task>

<task type="auto">
  <name>Task 2: Update panel-summon tests to re-summon-to-bottom behavior</name>
  <files>tests/test_bot.py</files>
  <action>
Update the `!panel` summon tests (the block starting at the "!panel summon (Plan 18-02 — PANEL-01)" header, ~line 1159) to the new recreate-at-bottom behavior. The Wave-0 fakes already support every seam needed: `channel.send` is an `AsyncMock` whose `.return_value.pin` auto-chains (the fresh post + its pin), and each `fake_pinned_message` exposes `.delete` / `.edit` AsyncMocks.

1. `test_panel_reuse_edits_in_place_single_match` → RENAME to `test_panel_resummon_posts_fresh_and_deletes_old` and rewrite: with exactly ONE existing owned panel, assert `channel.send` is awaited once WITH a `view=` kwarg (fresh post), `channel.send.return_value.pin` is awaited once (the fresh panel is pinned), and the old matched panel's `.delete` is awaited once. Assert the old panel is NOT edited in place: `panel.edit.assert_not_awaited()`. Update the success-copy assertion to `bot._PANEL_RESUMMONED`. Update the docstring to describe re-summon-to-bottom.

2. `test_panel_strays_deleted_keeps_exactly_one` → rewrite so ALL three prior owned panels (p1, p2, p3 — including the formerly-reused survivor) are DELETED and exactly one fresh panel remains: assert `channel.send` awaited once + `channel.send.return_value.pin` awaited once, and `p1.delete` / `p2.delete` / `p3.delete` each awaited once. Assert no in-place edit on any: `p1.edit.assert_not_awaited()`. The strays-cleaned copy now reflects 2 cleaned beyond the kept fresh panel (3 prior panels deleted, 1 fresh kept) → assert `bot._panel_strays_cleaned_copy(2)`. Confirm `p2.pin.assert_not_awaited()` (only the fresh `channel.send.return_value` is pinned).

3. `test_panel_create_posts_and_pins_when_no_match` → UNCHANGED behavior (no prior → post+pin fresh, `_PANEL_CREATED`); keep it green (only verify it still passes; no rewrite needed).

4. `test_panel_bot_pin_without_marker_is_never_touched` → still valid (unmarked bot pin never matched → falls through to fresh post + `_PANEL_CREATED`); keep green, no change to its assertions.

5. `test_panel_forbidden_write_is_caught_and_logged` → UNCHANGED (the fresh `channel.send` raising 403 is swallowed by the Forbidden backstop on the new write path); keep green.

6. Keep the perms-missing / channel-missing / wrong-type / guild-me-none tests UNCHANGED (those paths are untouched).

7. ADD a create-before-delete ordering test, e.g. `test_panel_resummon_creates_before_deleting_old`: with one existing owned panel, attach a shared `call_order` list — wrap `channel.send` / `channel.send.return_value.pin` / the old panel's `.delete` so each appends a marker when awaited (via `side_effect`), then assert the fresh `send` (and its `pin`) were awaited BEFORE the old `delete` (so there is never a zero-panel window). If wiring ordered side-effects is awkward with the existing fakes, instead assert the weaker-but-sufficient invariant that the fresh `channel.send` + `pin` are both awaited AND the old `.delete` is awaited (recreate-before-delete is structurally guaranteed by source order — already covered by Task 1's sequencing), and note that in the test docstring.

Remove any leftover references to `bot._PANEL_REUSED` in the test module (it no longer exists).
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot &amp;&amp; ! grep -q "_PANEL_REUSED" tests/test_bot.py &amp;&amp; uv run pytest tests/test_bot.py -k "panel" -q</automated>
  </verify>
  <done>No `_PANEL_REUSED` references remain in tests; all panel-summon tests pass under the new recreate-at-bottom behavior, including the create-before-delete ordering assertion and the unchanged perms/forbidden/channel-missing tests.</done>
</task>

<task type="auto">
  <name>Task 3: Update REQUIREMENTS.md PANEL-01 wording + annotate ROADMAP Phase 18 (supersession notes)</name>
  <files>.planning/REQUIREMENTS.md, .planning/ROADMAP.md</files>
  <action>
Update planning docs to reflect the behavior change WITHOUT rewriting history. PANEL-01 stays SATISFIED / Complete, still mapped to Phase 18.

REQUIREMENTS.md:
- Update the PANEL-01 line (~line 15) wording from "summon is idempotent — exactly one panel, stray panels cleaned up" to reflect that `!panel` now re-summons a FRESH panel to the channel bottom (still exactly one panel; the old panel + any strays are cleaned up). Suggested: "Operator can summon a pinned control-panel message (location dropdown + command-button grid); each `!panel` re-summons a fresh panel to the channel bottom — still exactly one panel, old/stray panels cleaned up."
- Add a brief one-line supersession note near the PANEL-01 entry (or as a trailing parenthetical): the Phase-18 reuse-in-place behavior was changed to re-summon-to-bottom at v1.3 Gate-2 (quick task 260626-uqp, 2026-06-26).
- Leave the status table (`PANEL-01 | Phase 18 | Complete`) and the phase mapping line unchanged.

ROADMAP.md:
- Briefly annotate the Phase 18 entry (line 72 summary bullet and/or the 18-02-PLAN.md line ~151) to note the reuse-in-place summon was superseded by re-summon-to-bottom at v1.3 Gate-2 (quick task 260626-uqp). Do NOT rewrite the historical plan descriptions — append a short "(superseded: re-summon-to-bottom, 260626-uqp)" style annotation.

Use scoped Edits only — do NOT rewrite either file wholesale.
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot &amp;&amp; grep -q "260626-uqp" .planning/REQUIREMENTS.md &amp;&amp; grep -q "260626-uqp" .planning/ROADMAP.md &amp;&amp; grep -qi "bottom" .planning/REQUIREMENTS.md</automated>
  </verify>
  <done>REQUIREMENTS.md PANEL-01 wording reflects re-summon-to-bottom (still exactly one, old/strays cleaned) with a 260626-uqp supersession note; ROADMAP Phase 18 carries a short supersession annotation; PANEL-01 stays Complete / Phase 18. History not rewritten.</done>
</task>

</tasks>

<verification>
Full-suite green + lint clean (the v1.3 baseline is 651 passed):

```
cd /home/yahir/Projects/WeatherBot
uv run pytest -q
uv run ruff check weatherbot tests
uv run ruff format --check weatherbot tests
```

All three must pass with no regression in test count.
</verification>

<success_criteria>
- `!panel` posts a FRESH panel as the newest channel message, pins it, then deletes ALL prior bot-owned panels → net exactly one panel at the channel bottom (PANEL-01).
- Create-before-delete ordering preserved: fresh panel is posted+pinned before any old delete (no zero-panel window, SC#4).
- Every Phase-18 prohibition intact: channel-abort (D-04), perm preflight incl. pin_messages (D-09/D-10), Forbidden TOCTOU backstop (D-09), marker-strict ownership (D-05), async-for pins (D-03), DELETE-not-unpin (D-06), operator-gate + no-dispatch_spec routing (D-07).
- `_PANEL_REUSED` fully removed; `_PANEL_RESUMMONED` added. No untouched module/state machine (PanelView, _render_view, clone-routing, dispatch_spec, registry, scheduler, add_view).
- Full suite green (≥651 passed) + ruff check/format clean.
- REQUIREMENTS.md + ROADMAP.md carry the supersession notes; PANEL-01 stays Complete.
</success_criteria>

<output>
Create `.planning/quick/260626-uqp-panel-re-summons-a-fresh-panel-at-channe/260626-uqp-SUMMARY.md` when done.
</output>