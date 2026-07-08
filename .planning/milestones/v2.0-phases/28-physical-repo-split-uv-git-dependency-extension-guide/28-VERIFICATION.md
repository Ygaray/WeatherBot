---
phase: 28-physical-repo-split-uv-git-dependency-extension-guide
verified: 2026-06-29T00:00:00Z
status: passed
score: 11/11 must-haves verified (autonomous Gate-1)
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: n/a
human_verification:

  - test: "Live yahir-mint restart against the pinned module sha (deferred Gate-2 / SC#3)"
    expected: "After a fetchable YahirReusableBot remote replaces the file:// URL, on yahir-mint: git pull + uv sync --frozen + sudo systemctl restart weatherbot; journalctl shows the once-per-boot 'module provenance' line with module_sha=138a907d57ac1d1d8499399b019f1509e43d02f1 (== PROMOTION-LEDGER v0.1.0 row) and editable=False"
    why_human: "Secure-host action (sudo systemctl restart on yahir-mint) the tooling cannot synthesize; per project Two-Gate UAT policy this is a deferred milestone-close obligation, NOT a phase blocker. Mechanism + data-level sha cross-check ARE proven in Gate-1."

  - test: "Live Discord panel tap-through against the pinned module (deferred Gate-2 / SC#3)"
    expected: "Tap every button/dropdown on the already-pinned live panel — each routes (no 'interaction failed'), the custom_id contract + persistent-view re-bind survived the split byte-identically, correct default location selected"
    why_human: "Live Discord gateway interaction cannot be synthesized by tooling. The custom_id wire-contract golden (4 byte-identical snapshots) + persistent-view re-bind mechanism ARE proven in Gate-1; only the live human tap-through defers."
---

# Phase 28: Physical Repo Split + uv Git Dependency + EXTENSION-GUIDE Verification Report

**Phase Goal:** Physically split the module to its own repo `YahirReusableBot` (import root `yahir_reusable_bot`, no console script) via a clean import of the boundary, and re-point WeatherBot at it through a uv git dependency (tag-pinned + editable override + reproducible `uv.lock` + `uv build --no-sources` leak gate). The `weatherbot` console entry stays app-side crossing through stable public names. Ship the EXTENSION-GUIDE; initialize the module as its own GSD project; stand up the commit→push→repin→deploy ritual + startup-version-log + promotion ledger. Clean-venv install + live `yahir-mint` restart UAT confirm the deployed bot runs against the pinned module.

**Verified:** 2026-06-29
**Status:** human_needed (autonomous Gate-1 fully PASS; live yahir-mint Gate-2 deferred per Two-Gate UAT policy — not a phase blocker)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | YahirReusableBot repo exists — fresh git init, single clean import commit tagged v0.1.0 | ✓ VERIFIED | `git -C ../YahirReusableBot log`: single commit `138a907`; `git tag` → `v0.1.0`; `rev-parse v0.1.0` = `138a907d57ac1d1d8499399b019f1509e43d02f1` |
| 2 | Module import root `yahir_reusable_bot`, NO console script | ✓ VERIFIED | `yahir_reusable_bot/` present; module `pyproject.toml` has NO `[project.scripts]` (only a comment documenting its absence) |
| 3 | Module imports zero app code; no `weatherbot.*` prose | ✓ VERIFIED | `grep -rn weatherbot ../YahirReusableBot/yahir_reusable_bot/` → empty; module import-hygiene suite (single-package grimp build) `8 passed`, exit 0 |
| 4 | Module deps = discord.py==2.7.1 (exact) + httpx + structlog + tenacity | ✓ VERIFIED | module `pyproject.toml` lines 6-14: exact `discord.py==2.7.1` pin + the three ranges |
| 5 | EXTENSION-GUIDE documents all six plug points with implemented-vs-deferred status | ✓ VERIFIED | `../YahirReusableBot/EXTENSION-GUIDE.md`: Channel(partial), JobStore(partial+serialization contract), config-schema/health-check/command-reg/SelectedContext(implemented) |
| 6 | Module initialized as its own GSD project recording durable-JobStore + 2nd Channel deferred | ✓ VERIFIED | `../YahirReusableBot/.planning/` has PROJECT/ROADMAP/REQUIREMENTS; REQUIREMENTS records EXT-01 (durable JobStore) + EXT-02 (2nd Channel) as deferred |
| 7 | WeatherBot depends on yahir-reusable-bot via `[tool.uv.sources]` git tag pin; uv.lock froze the sha | ✓ VERIFIED | app `pyproject.toml` line 35: `git = "file://.../YahirReusableBot", tag = "v0.1.0"`; `uv.lock` line 1324: `...?tag=v0.1.0#138a907d...` |
| 8 | discord.py==2.7.1 removed from app deps (inherited transitively); in-tree module removed | ✓ VERIFIED | app `pyproject.toml`: no `discord.py==2.7.1` line; in-tree `yahir_reusable_bot/` removed; `uv.lock` line 401: `discord-py 2.7.1` resolved transitively |
| 9 | App wheel collapses to `["weatherbot"]`; coverage source drops yahir_reusable_bot (Pitfall 5) | ✓ VERIFIED | `packages = ["weatherbot"]`; coverage `source` lists only `weatherbot/*` move-path pkgs; `uv build --no-sources` wheel = 46 weatherbot entries, 0 yahir_reusable_bot |
| 10 | Startup-version-log: `_module_provenance()` reads PEP 610 direct_url.json (vcs_info.commit_id) via importlib.metadata; editable tripwire | ✓ VERIFIED | `weatherbot/cli.py:75-114` reader + line 995 once-per-boot `_log.info("module provenance", ...)`; `test_module_provenance.py` `3 passed`; live reader output: sha=138a907d, editable=False |
| 11 | Repin ritual + promotion ledger stood up; Gate-1 self-UAT records 5/5 PASS | ✓ VERIFIED | `deploy/REPIN-RITUAL.md` (uv lock --upgrade-package + systemctl restart + never-commit-path-source rule); `deploy/PROMOTION-LEDGER.md` seeded `v0.1.0 \| 138a907d`; `28-SELF-UAT.md` 5/5 PASS |

**Score:** 11/11 truths verified (0 present, behavior-unverified)

SC#3 (live yahir-mint restart + panel tap-through) is the deferred Gate-2 milestone obligation — its mechanism + data-level checks are PROVEN above (truths 10, 3, suite custom_id golden); only the physical secure-host restart + live Discord interaction route to Human Verification. Per the project Two-Gate UAT policy and the verification guidance, this does NOT make the phase gaps_found.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `../YahirReusableBot/pyproject.toml` | name=yahir-reusable-bot, no console script, discord.py==2.7.1 | ✓ VERIFIED | All present; `packages=["yahir_reusable_bot"]` |
| `../YahirReusableBot/tests/test_import_hygiene.py` | Re-scoped single-package gate, green standalone | ✓ VERIFIED | `8 passed`, exit 0 |
| `../YahirReusableBot/EXTENSION-GUIDE.md` | Six plug points, implemented-vs-deferred, JobStore serialization contract | ✓ VERIFIED | All six + durable-JobStore contract documented |
| `../YahirReusableBot/.planning/` | Module GSD project recording deferred extension points | ✓ VERIFIED | PROJECT/ROADMAP/REQUIREMENTS; EXT-01/EXT-02 deferred |
| `pyproject.toml` (app) | git pin, collapsed wheel, discord.py removed, coverage fixed | ✓ VERIFIED | All four edits present |
| `uv.lock` (app) | Resolved module sha + discord.py 2.7.1 transitive | ✓ VERIFIED | sha 138a907d frozen; discord-py 2.7.1 |
| `weatherbot/cli.py` | `_module_provenance()` + startup-version-log line | ✓ VERIFIED | reader + once-per-boot log line wired in `run` path |
| `tests/test_module_provenance.py` | Reader proven against git/editable/missing shapes | ✓ VERIFIED | `3 passed` |
| `deploy/REPIN-RITUAL.md` | commit→push→repin→deploy ritual | ✓ VERIFIED | `uv lock --upgrade-package` + immutable-tag + never-commit-path-source |
| `deploy/PROMOTION-LEDGER.md` | Append-only sha-promotion record seeded v0.1.0 | ✓ VERIFIED | seeded `2026-06-29 \| v0.1.0 \| 138a907d` |
| `28-SELF-UAT.md` | Gate-1 per-criterion log | ✓ VERIFIED | 5/5 PASS + deferred Gate-2 section |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| module pyproject | yahir_reusable_bot/ | `packages = ["yahir_reusable_bot"]` | ✓ WIRED | wheel built contains only the module pkg |
| app pyproject | ../YahirReusableBot (v0.1.0) | `[tool.uv.sources] tag = "v0.1.0"` | ✓ WIRED | line 35 |
| uv.lock | resolved sha | tag → 138a907d frozen | ✓ WIRED | line 1324 |
| cli.py | installed dist-info | `Distribution.from_name(...).read_text("direct_url.json")` | ✓ WIRED | reader returns sha 138a907d from live install |
| REPIN-RITUAL.md | PROMOTION-LEDGER.md | ritual final step appends a ledger row | ✓ WIRED | ritual step D references ledger |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Module import-hygiene suite green standalone | `uv run pytest tests/test_import_hygiene.py -q` (in module repo) | `8 passed`, exit 0 | ✓ PASS |
| Provenance reader proven against both install shapes | `uv run pytest tests/test_module_provenance.py -q` | `3 passed`, exit 0 | ✓ PASS |
| Full suite + Phase-21 goldens byte-identical vs pinned module (SC#1) | `uv run pytest -q` | `776 passed`, exit 0; `git status --short '*.ambr'` empty | ✓ PASS |
| Console script resolves through public names (SC#2) | `uv run weatherbot --help` | exit 0; full command set listed | ✓ PASS |
| Leak gate — no path source in deploy artifact (SC#2) | `uv build --no-sources` | exit 0; built clean | ✓ PASS |
| App wheel contains only weatherbot/ (Pitfall 7) | `python -m zipfile -l *.whl` | 46 weatherbot, 0 yahir_reusable_bot | ✓ PASS |
| Deployed-sha data-level cross-check (SC#3 mechanism) | read installed direct_url.json + `_module_provenance()` | commit_id=138a907d == uv.lock sha == reader output; editable=False | ✓ PASS |

Note: the "2 snapshots failed / 27 passed" print on the full suite is the documented pre-existing syrupy report quirk (project `pytest-snapshot-report` memory) — exit code is 0 and `git status --short '*.ambr'` is empty (no golden diff), confirming byte-identical goldens.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| PKG-02 | 28-01/02/03/04 | Module extracted to own repo (no console script); WeatherBot depends via uv git dep (tag-pinned + editable override + reproducible lock + `--no-sources` leak gate); clean-venv install + live restart UAT | ✓ SATISFIED (autonomous portion); live restart deferred to Gate-2 | Repo+v0.1.0 tag, git pin in pyproject/lock, leak gate green, clean-venv install proven; live yahir-mint restart = deferred Gate-2 (human) |
| DOCS-01 | 28-01/04 | EXTENSION-GUIDE documents each plug point implemented-vs-deferred; module initialized as own GSD project recording durable-JobStore + 2nd Channel deferred | ✓ SATISFIED | EXTENSION-GUIDE (six plug points), module `.planning/` GSD project, EXT-01/EXT-02 recorded deferred |

Both PLAN-declared requirement IDs accounted for. REQUIREMENTS.md line 102 already marks DOCS-01 Complete; PKG-02 (line 101) is "In Progress" pending the live UAT — consistent with the deferred Gate-2 status. No orphaned requirements for Phase 28.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | No TBD/FIXME/XXX debt markers in any phase-modified file (app or module repo) | — | clean |

### Human Verification Required (Deferred Gate-2 — milestone-close, NOT a phase blocker)

#### 1. Live yahir-mint restart against the pinned module sha

**Test:** After creating a fetchable `YahirReusableBot` remote and swapping the `file://` URL: on `yahir-mint` run `git pull && uv sync --frozen && sudo systemctl restart weatherbot`, then `journalctl -u weatherbot -n 30 --no-pager`.
**Expected:** the once-per-boot `module provenance` line shows `module_sha=138a907d57ac1d1d8499399b019f1509e43d02f1` (== PROMOTION-LEDGER v0.1.0 row) and `editable=False`.
**Why human:** secure-host `sudo systemctl restart` action the tooling cannot synthesize. Mechanism + data-level sha cross-check already PASS in Gate-1.

#### 2. Live Discord panel tap-through

**Test:** Tap every button/dropdown on the already-pinned live Discord panel.
**Expected:** each routes (no "interaction failed"), correct default location, custom_id contract + persistent-view re-bind intact.
**Why human:** live Discord gateway interaction cannot be synthesized. The custom_id wire-contract golden (4 byte-identical snapshots) + persistent-view re-bind mechanism already PASS in Gate-1.

**Outstanding prerequisite (standing Gate-2 blocker, already recorded in STATE.md line 121):** a fetchable `YahirReusableBot` remote must replace the committed `file://` URL before the host can `git`-resolve the pin, then `uv lock --upgrade-package yahir-reusable-bot` re-resolves the same `v0.1.0` tag → same sha.

### Gaps Summary

No gaps. All 11 autonomous must-have truths VERIFIED with live codebase evidence across both repos. The module repo (`/home/yahir/Projects/YahirReusableBot`) exists as a fresh git init, clean import commit tagged `v0.1.0` @ `138a907d`, with the correct import root, no console script, exact discord.py pin, green import-hygiene suite, complete EXTENSION-GUIDE, and its own GSD project. WeatherBot is re-pointed via a `[tool.uv.sources]` git tag pin with a reproducible `uv.lock`, collapsed wheel, removed in-tree module, transitive discord.py 2.7.1, a wired startup-version-log provenance reader, and the repin ritual + promotion ledger process artifacts. The full 776-test suite + Phase-21 goldens pass byte-identical against the pinned module; the `uv build --no-sources` leak gate is clean; and the deployed-sha is proven at the data level (direct_url.json == uv.lock == provenance reader).

The only outstanding item is the live `yahir-mint` restart + Discord panel tap-through (SC#3), which is — per the project's Two-Gate UAT policy and the phase's explicit design — a **deferred Gate-2 milestone-close obligation**, not a phase blocker. Its mechanism and data-level checks are fully proven in the autonomous Gate-1; only the physical secure-host restart and live Discord interaction defer, gated additionally on creating a fetchable remote. Status is therefore `human_needed` (not `passed`, not `gaps_found`).

---

_Verified: 2026-06-29_
_Verifier: Claude (gsd-verifier)_
