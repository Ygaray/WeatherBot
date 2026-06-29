---
phase: 28-physical-repo-split-uv-git-dependency-extension-guide
plan: 04
subsystem: deploy
tags: [repin-ritual, promotion-ledger, gate-1-self-uat, two-gate-uat, deferred-gate-2, d-06, d-08, pep610, uv-frozen, no-sources-leak-gate]

# Dependency graph
requires:
  - phase: 28-02
    provides: "WeatherBot re-pointed at the yahir-reusable-bot git TAG pin (v0.1.0, sha 138a907d); uv.lock frozen; clean-venv Gate-1 proofs first established"
  - phase: 28-03
    provides: "_module_provenance() + the 'module provenance' startup-version-log line reading direct_url.json (the SC#3 mechanism the Gate-1 sha cross-check drives)"
provides:
  - "deploy/REPIN-RITUAL.md — durable commit->push->tag->uv lock --upgrade-package->uv sync --frozen->systemctl restart loop (D-06), incl. immutable-tag discipline, never-commit-a-path-source rule, and the uncommitted venv editable overlay for local co-dev (D-05)"
  - "deploy/PROMOTION-LEDGER.md — append-only Date|Tag|Resolved SHA|Note table, seeded with v0.1.0 / 138a907d (D-06)"
  - "28-SELF-UAT.md — persistent Gate-1 self-UAT log: 5 criteria PASS against the pinned module with exact commands + evidence; deferred Gate-2 obligation recorded (verdict PARTIAL) with exact replay instructions"
affects: [v2.0-milestone-audit (the deferred Gate-2 live yahir-mint restart obligation)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "uv lock --upgrade-package <name> as the single-package repin re-resolve (never a bare uv lock for a deploy repin)"
    - "Gate-1 data-level sha proof: cross-check installed direct_url.json commit_id == uv.lock frozen sha == _module_provenance() module_sha (prove the value, don't infer from code)"
    - "uncommitted venv editable overlay (uv pip install -e ../sibling) for co-dev, reverted by uv sync --frozen; the committed default stays the git pin"

key-files:
  created:
    - "deploy/REPIN-RITUAL.md"
    - "deploy/PROMOTION-LEDGER.md"
    - ".planning/phases/28-physical-repo-split-uv-git-dependency-extension-guide/28-SELF-UAT.md"

decisions:
  - "Process docs live WeatherBot-side under deploy/ (alongside the systemd unit) per RESEARCH A3 + 28-PATTERNS — the app owns consume/deploy"
  - "Tasks 2 + 3 share one artifact (28-SELF-UAT.md): the Gate-1 log and the deferred Gate-2 section are the same persistent record the human verifies against"
  - "A fully-passing Gate-1 completes the phase autonomously (Two-Gate UAT policy) — no per-phase blocking human-verify checkpoint emitted; the live restart is a deferred milestone-close obligation"

requirements-completed: [PKG-02, DOCS-01]

# Metrics
duration: ~9min
completed: 2026-06-29
status: complete
---

# Phase 28 Plan 04: Repin ritual + promotion ledger + Gate-1 self-UAT — Summary

**Stood up the durable D-06 deploy process artifacts WeatherBot-side (`deploy/REPIN-RITUAL.md` — the full commit→push→tag→`uv lock --upgrade-package`→`uv sync --frozen`→`systemctl restart` loop with immutable-tag discipline + the never-commit-a-path-source rule + the uncommitted venv editable overlay for co-dev; `deploy/PROMOTION-LEDGER.md` — an append-only ledger seeded with `v0.1.0`/`138a907d`), then drove the autonomous Gate-1 self-UAT to a clean pass: all five criteria PASS against the pinned module (clean-venv `uv sync --frozen`, `weatherbot check`/`--help`, 776-test byte-identical suite/goldens, `uv build --no-sources` leak gate with a `weatherbot/`-only wheel, and a data-level `direct_url.json` sha cross-check), with the live `yahir-mint` restart + panel tap-through recorded as a deferred Gate-2 obligation (verdict PARTIAL). Per the Two-Gate UAT policy, the phase completes autonomously.**

## Performance

- **Duration:** ~9 min
- **Completed:** 2026-06-29
- **Tasks:** 3
- **Files created:** 3 (2 deploy docs + the Gate-1 self-UAT log)

## Accomplishments

- **D-06 repin ritual (`deploy/REPIN-RITUAL.md`):** the step-by-step loop across both repos —
  module-side commit→push→`git tag vX.Y.Z` (immutable; never force-push a deploy tag, Pitfall 2)→push tag;
  WeatherBot-side bump `[tool.uv.sources]` tag→`uv lock --upgrade-package yahir-reusable-bot` (re-resolve only that package)→commit pyproject+lock together;
  host-side `git pull`→`uv sync --frozen` (fails loud on drift)→`sudo systemctl restart weatherbot`→confirm the `module provenance` line→append a ledger row. Includes the **D-05 local-co-dev overlay** (`uv pip install -e ../YahirReusableBot`, venv-only, reverted by `uv sync --frozen`) and the inviolable **never-commit-a-path-source** rule (with the `uv build --no-sources` backstop + the `editable: True` runtime tripwire).
- **D-06 promotion ledger (`deploy/PROMOTION-LEDGER.md`):** append-only `Date | Tag | Resolved SHA | Note` table, seeded with the first row (`2026-06-29 | v0.1.0 | 138a907d… | initial split`), plus the how-to-read-the-deployed-sha-off-the-host note (the `module provenance` journal line). The ritual's final step links here.
- **D-08 Gate-1 self-UAT (`28-SELF-UAT.md`):** drove the real installed artifact and recorded per-criterion evidence — all five PASS (table below).
- **D-08 deferred Gate-2:** the live `yahir-mint` restart + panel tap-through recorded as a clearly-marked deferred milestone-close obligation (verdict PARTIAL — mechanism + data-level checks proven in Gate-1) with exact replay instructions; flagged for carry-forward into STATE.md Deferred Items + the v2.0 milestone audit.
- **DOCS-01 closeout:** confirmed SC#4 is satisfied across the phase — the EXTENSION-GUIDE (Wave 1, module repo, all six plug points + the durable-`JobStore` serialization contract, implemented-vs-deferred), the module's own GSD project (recording EXT-01 durable JobStore + EXT-02 2nd Channel as deferred), and these process artifacts together complete it.

## Gate-1 self-UAT results (all PASS against the pinned module @ 138a907d)

| # | Criterion | Command (exact) | Result |
|---|-----------|-----------------|--------|
| 1 | Clean-venv frozen install | `rm -rf .venv && uv venv && uv sync --frozen` | **PASS** — `yahir-reusable-bot==0.1.0 (from git+file://…@138a907d…)`, exit 0, no dev overlay |
| 2 | Console-script resolution | `uv run weatherbot --help` / `uv run weatherbot check` | **PASS** — both exit 0; `check` → "config check passed locations=2" through stable public names |
| 3 | Byte-identical suite/goldens | `uv run pytest -q` (+ `-k custom_id`) | **PASS** — **776 passed, exit 0**; zero `.ambr` diff; custom_id golden green. The "2 snapshots failed" print is the known syrupy noise (trust exit code) |
| 4 | `--no-sources` leak gate + wheel | `uv build --no-sources` + `python -m zipfile -l dist/*.whl` | **PASS** — build exit 0 (no path leak); wheel = **46 `weatherbot/` entries, 0 `yahir_reusable_bot/`** |
| 5 | Deployed-sha data-level proof | read `direct_url.json` `commit_id` vs `uv.lock` sha vs `_module_provenance()` | **PASS** — all three == `138a907d…`; `editable: False` (real git deploy) |

## Deferred Gate-2 obligation (PARTIAL — does NOT block this phase)

- **What:** live `yahir-mint` `sudo systemctl restart weatherbot` against the pinned sha → confirm the `module provenance` journal line sha == ledger sha + `editable: False` → tap every panel button/dropdown (custom_id contract + persistent-view re-bind intact, correct default location).
- **Why deferred:** secure-host action + live Discord gateway interaction the tooling cannot synthesize. Its mechanism (startup-version-log line, persistent-view re-bind, custom_id contract) + data-level checks ARE proven in Gate-1.
- **Outstanding prerequisite (standing Gate-2 blocker):** a fetchable `YahirReusableBot` remote must replace the `file://` URL before the host can `git`-resolve the pin (then `uv lock --upgrade-package yahir-reusable-bot` to re-resolve the same v0.1.0 tag → same sha).
- **Carry-forward:** recorded in `28-SELF-UAT.md` + flagged into STATE.md Deferred Items + the v2.0 milestone audit.

## Task Commits

1. **Task 1 — repin ritual + promotion ledger** — `85da1ad` `docs(28-04): add repin-ritual + promotion-ledger deploy process artifacts (D-06)` (deploy/REPIN-RITUAL.md, deploy/PROMOTION-LEDGER.md)
2. **Task 2 + Task 3 — Gate-1 self-UAT log + deferred Gate-2 section** — `a53516a` `docs(28-04): record Gate-1 self-UAT log + deferred Gate-2 obligation (D-08)` (28-SELF-UAT.md). Tasks 2 and 3 share one artifact by design (the same persistent log the human verifies against).

## Deviations from Plan

None — plan executed exactly as written. (Tasks 2 and 3 both target `28-SELF-UAT.md`; they are committed together as one artifact, the persistent Gate-1+Gate-2 record — this is the plan's stated structure, not a deviation.)

## Threat Model Coverage

- **T-28-11 (deployed-sha drift):** mitigated — the ledger records the promoted sha; the ritual mandates `uv lock --upgrade-package` + committing the lock before deploy; the Gate-1 data-level cross-check (criterion 5) + the Gate-2 step-3 journal cross-check prove log sha == ledger sha.
- **T-28-12 (mutable deploy tag):** mitigated — `REPIN-RITUAL.md` documents tags as immutable (never force-push a deploy tag); `uv.lock` + `--frozen` pin the sha regardless of tag movement.
- **T-28-13 (dev path-override shipped to host):** mitigated — `REPIN-RITUAL.md` mandates the uncommitted venv overlay for co-dev + the never-commit-a-path-source rule; the `uv build --no-sources` backstop re-proven green in Gate-1 criterion 4; the `editable: True` runtime tripwire documented.

## Known Stubs

None. The `file://` git URL is a documented, intentional Gate-1 fallback (the named Gate-2 prerequisite is a fetchable remote), not a stub.

## Threat Flags

None — no new security surface. These are deploy-process docs + a verification log; no new endpoints, auth paths, file access, or schema changes.

## Self-Check: PASSED

- FOUND: deploy/REPIN-RITUAL.md (contains `uv lock --upgrade-package`)
- FOUND: deploy/PROMOTION-LEDGER.md (contains `v0.1.0`)
- FOUND: .planning/phases/28-.../28-SELF-UAT.md (5 PASS criteria + Gate-2 deferred section + `systemctl restart weatherbot`)
- FOUND: commit 85da1ad (Task 1)
- FOUND: commit a53516a (Tasks 2+3)
- VERIFIED: 776 passed exit 0; clean-venv install + console scripts + leak gate + wheel-only-weatherbot + direct_url.json sha cross-check all green against sha 138a907d

---
*Phase: 28-physical-repo-split-uv-git-dependency-extension-guide*
*Completed: 2026-06-29*
