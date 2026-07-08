# Phase 27 — Gate-1 Self-UAT Log (Plan 27-03, Wave 4)

> **Two-Gate UAT policy (CLAUDE.md):** Gate-1 is the autonomous agent self-UAT that gates this
> phase/PR. Gate-2 (the live `yahir-mint` `systemctl restart` panel re-bind) is the deferred,
> milestone-close human obligation tracked for **Phase 28** — it does NOT block this phase.
>
> **Date:** 2026-06-29 · **Suite baseline after this plan:** 783 passed, exit 0 (was 778 at
> 27-04; +5 new gate tests). **Discipline:** byte-identical extraction — any non-empty golden
> diff is a regression to investigate, never a re-baseline (D-06 / Phase-21 oracle).

---

## Verdict Summary

| Criterion | What it proves | Verdict |
|-----------|----------------|---------|
| **SC#1** — litmus tree-coverage requires the adapter | a future relocation can't silently drop `discord/` from litmus coverage | ✅ PASS |
| **SC#2** — no surviving render-cycle import | `render_embed`↔`PanelView` cycle is dead (resolved by ownership) | ✅ PASS |
| **SC#3** — marker parameterized + frozen custom_ids | `PanelKit(marker="X:")` → `X:cmd:<name>`; module bakes no `wb:` | ✅ PASS |
| **SC#4** — full byte-identical oracle | full suite + every golden green, zero `.ambr` re-baseline | ✅ PASS |
| **PKG-01** — core↔adapter isolation | no `yahir_reusable_bot/discord/**` imports `weatherbot.*` | ✅ PASS |
| **APP-02** — positive injection | render/contributors/marker are required no-default params wired at one root | ✅ PASS |
| **BHV-01** — suite green | `uv run pytest -q` exit 0 | ✅ PASS |
| **BHV-02** — goldens byte-identical | custom_id byte snapshot + embed + panel/clone goldens zero-diff | ✅ PASS |
| **Live restart re-bind** (Gate-2) | the pinned panel still routes on the live host after restart | ⚠️ PARTIAL — deferred to Phase 28 |

---

## SC#1 — Litmus tree-coverage requires the Discord adapter (coverage-gap guard)

- **Tested:** `test_litmus_clean` now asserts `{panelkit.py, gateway.py, selection.py}` are in the
  scanned `yahir_reusable_bot/discord/` tree (mirrors the lifecycle/registry coverage-gap guards),
  so a future relocation cannot silently drop the adapter from litmus coverage. The D-13 litmus
  term set is UNCHANGED (`weather|forecast|location|openweather|\buv\b|briefing`).
- **Command:** `uv run pytest tests/test_import_hygiene.py -q`
- **Evidence:** `11 passed` (was 9 — +2 Phase-27 tests). D-13 term set verified unchanged:
  `grep -n 'weather|forecast|location|openweather' tests/test_import_hygiene.py` → the same two
  locked lines (docstring L7 + `_LITMUS` L61).
- **Verdict:** **PASS**

## SC#2 — No surviving render-cycle import (cycle resolved by ownership)

- **Tested:** The two former cycle endpoints — `weatherbot/interactive/bot.py` and `panel.py` —
  carry NO deferred `import PanelView` / `import render_embed` edge. The render-cycle was resolved
  by OWNERSHIP: `render_embed` stays app-side and is INJECTED into the module `PanelKit` as
  `render` via the `_render_bridge` closure at the composition root; the panel view relocated to
  the module. New gate `test_no_deferred_cycle_import_survives_in_app_interactive` (forbidden
  tokens built from parts so the guard's own source stays grep-clean) + the grimp gate
  `test_discord_adapter_imports_zero_app_code` are the authoritative oracles.
- **Commands:**
  - `grep -n 'import render_embed\|import PanelView' weatherbot/interactive/bot.py weatherbot/interactive/panel.py`
  - `grep -rn 'class PanelView\|PanelView(' weatherbot/`
  - `uv run pytest tests/test_import_hygiene.py -q`
- **Evidence:**
  - bot.py + panel.py: **both cycle endpoints clean** (grep returns nothing).
  - `PanelView` no longer exists app-side at all (no class/construction) — relocated to module `PanelKit`.
  - `test_import_hygiene.py` 11/11 green (grimp + isolation + no-deferred-import all pass).
  - **Nuance (not a defect):** the broad pattern `grep -rn 'import render_embed' weatherbot/` returns
    ONE hit — `weatherbot/interactive/__init__.py:12: from .bot import render_embed`. This is the
    package **barrel re-exporting its own app-owned symbol** from its sibling `bot.py` module
    (present since before Phase 27, documented in 27-02). It is structurally incapable of forming
    the `render_embed↔PanelView` cycle — there is no `PanelView` for it to point back to. SC#2 is
    about the cycle *endpoints* (bot.py/panel.py), which are proven clean; this same-package barrel
    re-export is the legitimate app-side ownership surface, not a cycle edge.
- **Verdict:** **PASS** (cycle dead; the single grep hit is a benign same-package re-export)

## SC#3 — Marker parameterized + frozen custom_ids

- **Tested:** New `tests/test_panelkit_marker.py::test_panelkit_marker_parameterized` constructs a
  fully-generic `PanelKit(marker="X:")` (tiny fake registry, empty contributors, trivial
  render/dispatch — zero app code) and asserts every module command button carries `X:cmd:<name>`;
  a second panel with `marker="reminder:"` yields `reminder:cmd:<name>` (proving the namespace is
  parameterized, not coincidental). Plus the source assertion: `panelkit.py` bakes NO `wb:` literal.
  The positive injection test (`test_panel_cosmetics_and_render_and_marker_are_app_supplied`)
  independently asserts the same no-`wb:` property + that marker is a required param.
- **Commands:** `uv run pytest tests/test_panelkit_marker.py tests/test_injection_registry.py -q`
- **Evidence:** marker test `2 passed`; injection `10 passed`. The frozen WeatherBot `wb:…` byte
  strings are pinned separately by `test_golden_custom_ids.py` (see SC#4) — zero diff.
- **Verdict:** **PASS**

## SC#4 / BHV-01 / BHV-02 — Full byte-identical oracle

- **Tested:** Full suite (BHV-01) + the explicit golden oracle: the ordered `custom_id` byte
  snapshot, the embed goldens, and the Phase-21 panel/clone-render goldens (BHV-02). No `.ambr`
  re-baseline permitted.
- **Commands:**
  - `uv run pytest -q`
  - `uv run pytest tests/test_golden_custom_ids.py tests/test_golden_embeds.py tests/test_panel.py tests/test_bot.py -q`
  - `git status --short` (confirm zero `.ambr`/snapshot/golden file change)
- **Evidence:**
  - Full suite: **783 passed, exit 0** in ~42s (was 778 at 27-04; the +5 are this plan's new gate
    tests). The printed "2 snapshots failed. 27 snapshots passed." is the **documented syrupy
    oracle-self-proof perturbation quirk** (MEMORY: pytest-snapshot-report-quirk) — exit 0 + no
    `.ambr` diff confirm it is noise, not a golden diff.
  - Explicit goldens: **88 passed, 12 snapshots passed**, zero diff.
  - `git status --short`: NO `.ambr`/snapshot/golden/fixture file is dirty (the only untracked path
    is the pre-existing, unrelated `.planning/.../21-PATTERNS.md`). **Zero re-baseline.**
- **Verdict:** **PASS** (suite green, every golden byte-identical, no re-baseline)

## PKG-01 — Core↔adapter import isolation

- **Tested:** `test_discord_adapter_imports_zero_app_code` — the explicit grimp gate naming the
  `yahir_reusable_bot.discord` package asserts NO adapter module imports `weatherbot.*` (the broad
  `test_module_imports_zero_app_code` also covers it via `startswith(MODULE)`; this pins the intent
  on the adapter, the layer most at risk of reaching back for `render_embed`/the app panel).
- **Command:** `uv run pytest tests/test_import_hygiene.py -q`
- **Evidence:** 11/11 green; the adapter-scoped grimp scan finds zero `discord/`→`weatherbot` edge.
- **Verdict:** **PASS**

## APP-02 — Positive injection (render/contributors/marker)

- **Tested:** `test_panel_cosmetics_and_render_and_marker_are_app_supplied` — `render`,
  `contributors`, `marker` are REQUIRED no-default `PanelKit.__init__` params (each paired with a
  biting self-proof against a baked-default stub); the module source bakes no `wb:` literal; and
  all three are wired at the single composition root `wiring.build_inbound_bot`. The realigned
  leak-point-1/4 stubs (`SelectedContext` seam app-side; `render_embed` app-side via `_render_bridge`)
  pass against the relocated shape; the stale `render_embed in panel_src` assertion was removed.
- **Command:** `uv run pytest tests/test_injection_registry.py -q`
- **Evidence:** `10 passed`. `grep -n '"render_embed" in panel_src' tests/test_injection_registry.py`
  → nothing (stale assertion gone).
- **Verdict:** **PASS**

---

## Deferred Gate-2 obligation (Phase 28) — PARTIAL

- **Behavior:** Live `yahir-mint` `sudo systemctl restart weatherbot` → the already-pinned Discord
  panel's every button/dropdown still routes (custom_id wire-contract + persistent-view re-bind),
  correct default location, against the pinned module sha.
- **Why PARTIAL (mechanism verified, physical run deferred):**
  - **Mechanism verified (Gate-1 stand-in):** the byte-frozen `custom_id` snapshot
    (`test_golden_custom_ids.py`) pins the exact `wb:loc:select` / `wb:cmd:*` / `wb:fc:*` wire
    strings the live panel routes by — zero diff this plan. The persistent-view registration path
    (`setup_hook` → `client.add_view(panelkit)`) and the marker-bound ownership predicate are
    covered green by `test_bot.py` / `test_panel.py`. The relocation is byte-identical, so the live
    custom_id contract is unchanged by construction.
  - **Physical run deferred:** the actual `systemctl restart` on the live host + a real button tap
    round-trip is a human/host action this autonomous agent cannot drive — it is the Phase-28
    milestone-close obligation per VALIDATION.md + the STATE.md pending-todo.
- **Verdict:** **PARTIAL** — not skipped, not a phase blocker; tracked as the single deferred
  Gate-2 item for Phase 28.

---

## Threat-register discharge (this plan's mitigations)

| Threat | Mitigation status |
|--------|-------------------|
| **T-27-09** (silently re-baselined golden) | HELD — `git status` shows zero `.ambr`/golden file change; the syrupy "2 snapshots failed" quirk is handled by trusting exit 0 + the empty `.ambr` diff (no investigation needed, no re-baseline). |
| **T-27-10** (reintroduced cycle import escaping the gate) | HELD — `test_no_deferred_cycle_import_survives_in_app_interactive` (bot.py/panel.py) + the grimp adapter gate redden on any reintroduced edge; both green. |
| **T-27-11** (unverified completion claim) | HELD — this log records exact commands + evidence per criterion; the live restart is explicitly the deferred Phase-28 Gate-2 item. |
| **T-27-SC** (uv/pip installs) | ACCEPT — test-only plan, no package install, no new dependency entered the tree. |
