---
phase: 28-physical-repo-split-uv-git-dependency-extension-guide
plan: 03
subsystem: cli
tags: [provenance, pep610, direct_url, importlib-metadata, structlog, startup-log, deploy-audit, d-06]

# Dependency graph
requires:
  - phase: 28-01
    provides: "EMPIRICALLY CONFIRMED direct_url.json contract (vcs_info.commit_id + requested_revision; dir_info.editable on editable installs only)"
  - phase: 28-02
    provides: "WeatherBot re-pointed at the yahir-reusable-bot git TAG pin (v0.1.0, sha 138a907d), so an installed dist-info with a direct_url.json exists to read"
provides:
  - "_module_provenance() in weatherbot/cli.py — reads the installed module's PEP 610 direct_url.json and returns {module_version, module_sha, module_ref, editable}"
  - "A once-per-boot 'module provenance' startup-version-log line in the daemon run path (the SC#3 line the live host verifies)"
  - "tests/test_module_provenance.py — self-disciplined proof against git/editable/missing direct_url.json shapes"
affects: [28-04 (promotion ledger — the startup sha is checked against the ledger; live-host display is the deferred Gate-2 confirmation)]

# Tech tracking
tech-stack:
  added: []
  patterns: ["PEP 610 direct_url.json as the runtime deployed-sha source (read via stdlib importlib.metadata, no new dep)", "editable-flag as a free dev-tree-vs-deploy tripwire", "provenance read guarded so it never crashes startup"]

key-files:
  created:
    - "tests/test_module_provenance.py"
  modified:
    - "weatherbot/cli.py (imports: json + importlib.metadata Distribution/PackageNotFoundError/version; _MODULE_DIST const; _module_provenance() helper; startup-version-log line in the run path)"

key-decisions:
  - "Used the confirmed 28-01 field names verbatim (vcs_info.commit_id / vcs_info.requested_revision) — no assumption"
  - "Guarded BOTH the dist lookup (PackageNotFoundError) and the version() call, plus the absent/empty direct_url.json, so a provenance read can never crash daemon startup (T-28-10)"
  - "Inserted the line in the cli.py run-command path (after _configure_logging ran, before daemon launch) rather than wiring.py:304 — same once-per-boot READY moment, but keeps the provenance read at the app composition root where the module dist name is already a cli.py concern"

requirements-completed: [PKG-02]

# Metrics
duration: ~8min
completed: 2026-06-29
status: complete
---

# Phase 28 Plan 03: Startup-version-log provenance reader (D-06) — Summary

**Wired `_module_provenance()` into `weatherbot/cli.py` — it reads the installed `yahir-reusable-bot` module's PEP 610 `direct_url.json` via stdlib `importlib.metadata` and emits a once-per-boot `module provenance` structlog line reporting the deployed `module_version` / `module_sha` / `module_ref` / `editable`. Proven by a self-disciplined unit test against the git-install, editable-install, and missing-record shapes; full suite green (776 passed, exit 0).**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-06-29T17:38:11Z
- **Tasks:** 2
- **Files created/modified:** 2 (1 created, 1 modified)

## The startup-version-log line (record for 28-04 / Gate-2)

- **Event key:** `"module provenance"` (structlog `_log.info`, `_log = structlog.get_logger(__name__)`).
- **Exact provenance dict keys logged:** `module_version`, `module_sha`, `module_ref`, `editable`.
- **Insertion point:** `weatherbot/cli.py`, inside `if args.command == "run":` (after `load_settings()`, before the daemon import + `daemon.run_daemon(...)`). `_configure_logging(level)` has already run (main:870), so the line is correctly formatted; it fires exactly once per boot.
- **Live value against the real install (driven this session):**
  ```json
  {
    "module_version": "0.1.0",
    "module_sha": "138a907d57ac1d1d8499399b019f1509e43d02f1",
    "module_ref": "v0.1.0",
    "editable": "False"
  }
  ```
  The sha matches the v0.1.0 git pin frozen by 28-02 (`138a907d`), and `editable: False` confirms a real git deploy (not a dev-tree overlay).
- **Deferred Gate-2 (28-04):** the *live-host* display of this line on `yahir-mint` — `sudo systemctl restart weatherbot` then confirm the journal shows the pinned sha — is the deferred Gate-2 confirmation of SC#3. NOT touched this session (no `systemctl`, no live host).

## Accomplishments

- **`_module_provenance()`** (`weatherbot/cli.py`): `Distribution.from_name("yahir-reusable-bot").read_text("direct_url.json")` → `json.loads` → returns `module_version` (from `importlib.metadata.version`), `module_sha` (`vcs_info.commit_id`), `module_ref` (`vcs_info.requested_revision`), `editable` (`str(dir_info.editable)`). Stdlib only — no new dependency.
- **Startup-safety guard (T-28-10):** wraps the dist lookup in `PackageNotFoundError`, treats an absent/empty `direct_url.json` as `{}` (empty sha/ref), and guards `version()` too — a provenance read can never crash startup.
- **Secret hygiene (T-04-01 / T-28-08):** the line logs ONLY version/sha/ref/editable; verified by reading the emitted log line (no webhook URL, no `appid`, no token).
- **Editable tripwire (T-28-09):** an editable install (`dir_info.editable=true`, no `vcs_info`) surfaces `editable == "True"` with an empty sha — visibly distinguishing a dev overlay from a pinned deploy.
- **Self-disciplined unit test** (`tests/test_module_provenance.py`, 3 tests): git-install shape (asserts the embedded sha + tag, `editable == "False"`), editable-install shape (`editable == "True"`, empty sha), missing-record (`read_text -> None` → empty sha/ref, no raise). Mocks `Distribution.from_name` + `version` so it never depends on a live install.

## TDD Gate Compliance

Both tasks executed TDD. RED confirmed: the 3 provenance tests failed first (`_module_provenance`/`Distribution`/`version` absent from `cli.py`). GREEN: implementation added, all 3 pass. Gate commits in git log:
- `test(28-03): ...` — `40d3ff9` (RED test, committed after the impl since the test imports `cli._module_provenance`)
- `feat(28-03): ...` — `7c29a70` (GREEN implementation)

## Verification

- `uv run pytest tests/test_module_provenance.py -q` → **3 passed**.
- `uv run pytest` (full suite) → **776 passed, exit 0** (773 baseline + 3 new). The "2 snapshots failed" line is the known syrupy report-noise quirk (exit 0, no `.ambr` diff) — trusted per the pytest-snapshot-report memory.
- No `.ambr` / golden diffs (`git status` clean of snapshots) — byte-identical oracle holds.
- `uv run ruff check weatherbot/cli.py tests/test_module_provenance.py` → All checks passed.
- Drove `cli.main(["run"])` with a stubbed daemon → the `module provenance` line fires once and carries no secret.
- Drove `_module_provenance()` against the REAL installed module → returns the deployed sha `138a907d...`, ref `v0.1.0`, `editable: False`.

## Task Commits

1. **Task 1 — `_module_provenance()` + startup-version-log line** (`weatherbot/cli.py`): `7c29a70` `feat(28-03): startup-version-log + _module_provenance() reading direct_url.json (D-06)`.
2. **Task 2 — self-disciplined unit test** (`tests/test_module_provenance.py`): `40d3ff9` `test(28-03): prove _module_provenance() against git/editable/missing direct_url.json shapes`.

## Files Created/Modified

- **`weatherbot/cli.py`** (modified): added `json` + `from importlib.metadata import Distribution, PackageNotFoundError, version` imports; `_MODULE_DIST = "yahir-reusable-bot"` const; `_module_provenance()` helper; `_log.info("module provenance", **_module_provenance())` in the `run` path.
- **`tests/test_module_provenance.py`** (created): 3 tests covering git-install, editable-install, and missing-record shapes.

## Decisions Made

- **Confirmed field names used verbatim** — `vcs_info.commit_id` (deployed sha) and `vcs_info.requested_revision` (tag), per the 28-01 spike; no assumption.
- **Guarded the lookup at two points** — `Distribution.from_name` AND `version()` both wrapped in `PackageNotFoundError`, plus the absent/empty `direct_url.json` path, so the provenance read is total (never raises) regardless of install shape.
- **Insertion at the cli.py run path, not wiring.py:304** — same once-per-boot READY moment; chosen because the module dist name and `direct_url.json` read are an app-composition-root concern (cli.py), keeping the module itself free of any self-provenance code.

## Deviations from Plan

None — plan executed as written. (Minor: the plan's example sketch did not show the `PackageNotFoundError` guard on the dist lookup; I added it as Rule-2 correctness — "a provenance read must not crash startup" is the plan's own stated behavior, and a missing dist is the same failure class as a missing `direct_url.json`.)

## Known Stubs

None.

## Threat Flags

None — no new security surface beyond the threat_model already enumerated (T-28-08/09/10, all mitigated and verified above).

## Next Phase Readiness

- **28-04** can build the promotion ledger and check the startup `module provenance` sha against the recorded promotion entry. The live-host display of this line (`yahir-mint` restart → journal shows sha `138a907d`) remains the deferred Gate-2 confirmation of SC#3 — **still gated on a fetchable remote** for `YahirReusableBot` (currently `file://` only, per 28-01/28-02).

## Self-Check: PASSED

- FOUND: weatherbot/cli.py (_module_provenance + startup-version-log line)
- FOUND: tests/test_module_provenance.py
- FOUND: commit 7c29a70 (feat — implementation)
- FOUND: commit 40d3ff9 (test — provenance unit test)

---
*Phase: 28-physical-repo-split-uv-git-dependency-extension-guide*
*Completed: 2026-06-29*
