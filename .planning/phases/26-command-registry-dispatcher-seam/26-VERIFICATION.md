---
phase: 26-command-registry-dispatcher-seam
verified: 2026-06-28T00:00:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 26: Command Registry + Dispatcher Seam Verification Report

**Phase Goal:** Move the self-describing command registry + the shared `dispatch_spec` dispatcher into the module `yahir_reusable_bot` as a generic registration mechanism — commands registered by the app at the single composition root; CLI + Discord + auto-`help` all derive from ONE registry; command-set drift structurally impossible; the module owns the registry/dispatch plumbing + help-derivation; WeatherBot owns the command set + handlers; no weather command name/handler lives in the module; behavior byte-identical (Phase-21 CLI + `help` goldens + anti-drift + suite are the oracle).
**Verified:** 2026-06-28
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| - | ----- | ------ | -------- |
| 1 | Module owns the generic mechanism (CommandRegistry/CommandSpec/build_registry/match_command/dispatch shell), names no weather noun | ✓ VERIFIED | `yahir_reusable_bot/registry/{spec,registry,match,dispatch,__init__}.py` all exist; AST name-scan litmus (`test_litmus_clean`) GREEN over the package; the generic `CommandSpec` carries only name/group/summary/bind/needs_flags — no `takes_location`, no `handler`, no weather noun in any def/class/arg/annotation name |
| 2 | (D-03) Byte-identical re-export: app `registry.py` exposes COMMANDS/BY_NAME/COMMANDS_BY_KEYWORD_LEN_DESC/render_help/CommandSpec; oracle passes unmodified; parameterized `render_help(COMMANDS+(extra,))` works | ✓ VERIFIED | `weatherbot/interactive/registry.py` builds `_registry = build_registry(_wire_handlers(_SPECS))` and re-exports all 4 globals under exact names; `test_registry.py` + `test_command_views.py` pass (28 in the oracle bundle); behavioral spot-check confirms dual-signature `render_help` returns byte-identical output with no TypeError on the parameterized form |
| 3 | Both coupling sites de-weathered: dispatcher uses `spec.bind(ctx)` + neutral `needs_flags` (not `group=="Forecast"`) | ✓ VERIFIED | `dispatch.py:45` `dispatch_reply` collapses to `return spec.bind(ctx)`; `dispatch.py:77` reads `needs = spec.needs_flags`; no `Forecast`/threshold/command-name read in module dispatcher code; arity spot-check confirms 2-arg (plain) / 3-arg (needs_flags) cache call contract `[2, 3]` |
| 4 | (D-04) Discord text path resolves via module `match_command`; forecast grammar stays app-side | ✓ VERIFIED | `command.py:25` imports `match_command`; `parse_command` (L110-111) delegates `match_command(text, registry.COMMANDS_BY_KEYWORD_LEN_DESC)` and re-wraps; `parse_forecast_flags`/`forecast_cache_suffix`/`ForecastFlags`/`_day_token` stay in `command.py` (litmus-tripping, app-side) |
| 5 | Positive injection-registry assertion exists and is biting (command set app-supplied, not baked) | ✓ VERIFIED | `test_injection_registry.py::test_command_set_is_app_supplied_no_module_default_commands` asserts `build_registry` + `CommandRegistry.__init__` REQUIRE `specs`, and no module public symbol names a weather command; paired with biting self-proofs (`_BakedRegistry`, `weekday_forecast`) — 18 passed |
| 6 | (PKG-01) Module imports zero app code (grimp gate + isolated-import smoke) | ✓ VERIFIED | `test_import_hygiene.py` grimp/isolated-import/litmus gates GREEN (9 passed for the gate selection); `walk_packages` import-smoke auto-scales over the registry subpackage |
| 7 | (BHV-01/BHV-02) Full suite byte-identical green; no golden re-baselined | ✓ VERIFIED | `uv run pytest -q` → **778 passed, exit 0**; `git diff 3415b79^..5b94da5` touched ZERO `.ambr`/golden/snapshot files; the "2 snapshots failed" summary line is a pre-existing harness quirk (present at baseline ebb5999, does not affect exit code) |

**Score:** 7/7 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `yahir_reusable_bot/registry/spec.py` | Generic frozen CommandSpec + DispatchContext | ✓ VERIFIED | `CommandSpec` = frozen 5-field (name/group/summary/bind/needs_flags); `DispatchContext` frozen 4-field; no weather noun |
| `yahir_reusable_bot/registry/registry.py` | CommandRegistry + build_registry, 3 frozen views + dual-sig render_help | ✓ VERIFIED | All 3 views computed once in `__init__`; `render_help(commands=None)` optional override; `specs` required |
| `yahir_reusable_bot/registry/match.py` | match_command free function | ✓ VERIFIED | Longest-first + word-boundary guard + strip/casefold/slice-only security contract preserved verbatim |
| `yahir_reusable_bot/registry/dispatch.py` | Generic dispatch shell (bind + needs_flags) | ✓ VERIFIED | `dispatch_reply` one-line `spec.bind(ctx)`; `dispatch_spec` off-loop, needs_flags-gated via injected hooks, exceptions bubble |
| `yahir_reusable_bot/registry/__init__.py` | Barrel export | ✓ VERIFIED | Re-exports full surface + `__all__` |
| `weatherbot/interactive/registry.py` | Thin re-exporting singleton; keeps takes_location+handler, adds bind+needs_flags | ✓ VERIFIED | Builds via `build_registry`; `needs_flags=True` on exactly the 2 forecast specs; bind closures read config LIVE per-tap (hot-reload contract) |
| `weatherbot/interactive/dispatch.py` | Thin app shim injecting forecast hooks | ✓ VERIFIED | Delegates to module dispatcher with `parse_flags=parse_forecast_flags`, `cache_suffix=forecast_cache_suffix`; signature byte-identical |
| `tests/test_injection_registry.py` | Positive command-injection assertion | ✓ VERIFIED | New biting assertion + self-proofs |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `weatherbot/interactive/registry.py` | `yahir_reusable_bot/registry/registry.py` | `build_registry(_wire_handlers(_SPECS))` | ✓ WIRED |
| `weatherbot/interactive/command.py` | `yahir_reusable_bot/registry/match.py` | `match_command(text, registry.COMMANDS_BY_KEYWORD_LEN_DESC)` | ✓ WIRED |
| `weatherbot/interactive/dispatch.py` | `yahir_reusable_bot/registry/dispatch.py` | delegates to module `dispatch_spec`/`dispatch_reply` with hooks injected | ✓ WIRED |
| `registry.py bind closures` | `weatherbot/interactive/commands/*` | `lambda ctx: _h(name)(ctx.result, ctx.config.X)` live per-tap | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Parameterized `render_help(COMMANDS+(extra,))` (oracle:160 form) | `python -c "render_help(COMMANDS+(extra,))"` | renders extra, no TypeError, no-arg ⊆ param | ✓ PASS |
| dispatch_spec 2-arg/3-arg cache arity contract | `python -c` arity probe | `[2, 3]` (plain=2, needs_flags=3) | ✓ PASS |
| Full suite byte-identical | `uv run pytest -q` | 778 passed, exit 0 | ✓ PASS |
| Gate tests | `pytest test_import_hygiene.py test_injection_registry.py` | 18 passed | ✓ PASS |
| Oracle bundle | `pytest test_registry test_command_views test_dispatch test_cli` | 100 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| SEAM-06 | 26-01, 26-02 | Registry + shared dispatcher in module; commands app-registered; CLI/Discord/help derive from one registry, drift structurally impossible | ✓ SATISFIED | All 3 SEAM-06 criteria verified: (1) mechanism in module + app registers set; (2) single dispatch path + positive injection assertion; (3) litmus clean over registry seam |
| PKG-01 (cross-cutting) | — | Module subpackage imports zero app code (grimp/isolated-import gate) | ✓ SATISFIED | `test_import_hygiene.py` gates green over registry package |
| APP-02 (cross-cutting) | — | Litmus: no weather term in module package | ✓ SATISFIED | AST name-scan litmus green; coverage-gap assertion now names registry files |
| BHV-01 (cross-cutting) | — | Full suite green at boundary, no weakened assertions | ✓ SATISFIED | 778 passed, exit 0; no golden re-baselined |
| BHV-02 (cross-cutting) | — | Golden/characterization tests byte-identical | ✓ SATISFIED | Zero `.ambr`/golden/snapshot files modified by phase 26 |

All requirement IDs from PLAN frontmatter (SEAM-06) and the cross-cutting set (PKG-01/APP-02/BHV-01/BHV-02) are accounted for and SATISFIED.

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| (none) | TBD/FIXME/XXX | — | NONE — no debt markers in any phase-26 file |
| (none) | TODO/HACK/PLACEHOLDER | — | NONE |

### Notable Observations (Info — not phase-26 gaps)

1. **Pre-existing baseline flake (ℹ️ INFO):** At baseline commit `ebb5999`, a full-suite run in a clean worktree shows `1 failed, 776 passed` — the failure is `tests/test_golden_coverage_fill.py::test_load_settings_no_env_file_uses_default`, an env/CWD-sensitive settings test UNRELATED to the command registry. It was NOT modified by phase 26, passes in isolation at HEAD, and the full HEAD run is `778 passed, exit 0`. This is a pre-existing environmental/test-ordering flake, not a phase-26 regression, and does not affect SEAM-06.

2. **"2 snapshots failed" summary line (ℹ️ INFO):** The syrupy snapshot summary prints "2 snapshots failed. 27 snapshots passed." at BOTH baseline ebb5999 and phase-26 HEAD — a pre-existing harness quirk that does not affect the exit code (0). No `.ambr`/golden file was modified by phase 26 (verified via `git diff --name-only`). The authoritative signal — test pass count (778) + exit 0 — is clean.

### Gaps Summary

No gaps. This behavior-preserving relocation achieves the phase goal in full: the generic registry/dispatch mechanism lives in `yahir_reusable_bot/registry/` naming no weather noun (AST litmus clean), the app re-exports byte-for-byte and registers its own command set at the single root, both dispatcher coupling sites are de-weathered (`spec.bind(ctx)` + neutral `needs_flags` + injected hooks), the parser delegates to `match_command`, a biting positive injection assertion proves the command set is app-supplied, and the full ~778-test byte-identical oracle is GREEN (exit 0) with zero golden re-baselined.

---

_Verified: 2026-06-28_
_Verifier: Claude (gsd-verifier)_
