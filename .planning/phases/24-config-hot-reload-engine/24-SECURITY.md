---
phase: 24
slug: config-hot-reload-engine
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-07
---

# Phase 24 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Verified by gsd-security-auditor against the extracted (v2.0) two-tree layout: app-side code in
> `weatherbot/`, reusable-module code in `../Reusable/YahirReusableBot/yahir_reusable_bot/config/`.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| operator-edited `config.toml` → `run_daemon` → `reload_engine.service_pending()` → injected `validate_config_and_templates` | The only untrusted input: a local operator's config edit, re-read from disk and validated (pydantic `extra="forbid"` + field validators + template allow-list) BEFORE any swap. The module never parses/validates it itself — validation is injected. | untrusted config text (non-secret structure only) |
| local SIGHUP handler / watchfiles observer thread → main poll loop | An off-thread reload trigger (signal handler or file-watch observer) crosses into the daemon; only a `threading.Event` is flag-set off-thread — reload work runs solely on the main poll thread (D-05). | reload-request signal (no data) |
| `.env` / secrets file → watch filter → (rejected) | A secret-file edit in a watched directory; the app-side `_make_watch_filter` allow-list is the hard secrets boundary — a `.env` edit produces ZERO reloads. | secrets (must never cross into a reload) |
| self-UAT evidence → phase-completion decision | The Gate-1 log is the record Gate-2 human UAT verifies against; a fabricated PASS would let a real regression ship — hence byte-level/data-level evidence is mandatory. | verification evidence |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-24-01 | Denial of Service | `ReloadEngine.reload` PHASE-1 validate | high | mitigate | A validator raise fires best-effort `on_rejected` then re-raises, leaving holder+jobs UNTOUCHED (keep-old). `reload.py:131-139` (module); pinned by `tests/test_reload.py::test_invalid_reload_keeps_old` (PASS). | closed |
| T-24-02 | Tampering | `ReloadEngine.reload` PHASE-2 reconcile | high | mitigate | All-or-nothing: a reconcile throw does `holder.replace(old)` + injected `restore(old)` then re-raises — a half-applied job set can never persist. `reload.py:144-158` (module); pinned by `tests/test_reload.py::test_reconcile_failure_rolls_back` (PASS). | closed |
| T-24-03 | Elevation of Privilege (re-entrancy) | `request_reload` / `service_pending` / SIGHUP | high | mitigate | Off-thread triggers only `Event.set()`; reload runs solely on the main poll thread via `service_pending()`. Module `request_reload()` = `reload.py:198-200` (set-only); app SIGHUP handler flag-sets at `daemon.py:1424`. Pinned by `tests/test_reload.py::test_sighup_triggers_reload` (PASS). | closed |
| T-24-04 | Information Disclosure | `ConfigHolder[T]` | medium | accept | Holder carries the app config object ONLY; the secrets object / `.env` never enters it (secrets live behind the restart boundary). Invariant preserved & documented in `holder.py:28-29` (module). No new disclosure surface from the generalization. See Accepted Risks Log R-24-01. | closed |
| T-24-05 | Denial of Service | `run_daemon` main poll loop | high | mitigate | Poll loop wraps `service_pending` in `try/except Exception: _log.exception(...)` so a bad edit + SIGHUP can never crash the always-on daemon. `daemon.py:1550-1561`; pinned by `tests/test_filewatch.py::test_invalid_save_keeps_old_config` (PASS). | closed |
| T-24-06 | Information Disclosure | `_make_watch_filter` / `.env` edits | high | mitigate | The app-side watch filter allow-lists only `config.toml` + referenced template basenames; a `.env` edit matches nothing → ZERO reloads; the holder never receives secrets. `daemon.py:1242-1263`; pinned by `tests/test_filewatch.py::test_env_save_never_reloads` (PASS). | closed |
| T-24-07 | Tampering | `excluded_ids` wiring | high | mitigate | App supplies `excluded_ids=frozenset({"__heartbeat__","__uvmonitor__"})` (`wiring.py:254`); the module subtracts it from live BEFORE diffing (`reload.py:176`) and names no app job id — so a reload never tears down the liveness/monitor jobs. Pinned by `tests/test_reload.py::test_reconcile_diff` + `tests/test_reload_engine.py::test_reload_excluded_id_never_removed_even_when_not_desired` (PASS). | closed |
| T-24-08 | Tampering | job-id collision via config | medium | accept | The `_no_pipe_in_identity` field_validator stays inside the concrete `Config` (`weatherbot/config/models.py:209-224`), unaffected by the extraction — a `|` in a location name/id still raises at validation. Pinned by `tests/test_config.py::test_pipe_in_location_name_fails_loud` (PASS). See Accepted Risks Log R-24-02. | closed |
| T-24-09 | Repudiation | self-UAT log | medium | mitigate | Each verdict in `24-SELF-UAT.md` cites the exact command + captured output (byte-level golden + `sent_log` DB-row evidence), so the Gate-1 record is auditable at Gate-2 close — a PASS cannot be a bare assertion. Log present with per-command PASS evidence for all five reload paths. | closed |
| T-24-10 | Denial of Service | bad-edit-keep-old drive (self-UAT path 4) | high | mitigate | The self-UAT drives 4 malformed-config kinds and proves the daemon does not crash + old config stays live + `⛔ rejected` post fires before the re-raise (the same DoS mitigation Plan 02 wires, verified end-to-end). `24-SELF-UAT.md` Path 4; underlying test `tests/test_reload.py::test_invalid_reload_keeps_old` (PASS). | closed |
| T-24-SC | Tampering | npm/pip/cargo installs | low | accept | No package installs this phase — pure in-repo relocation; RESEARCH.md Package Legitimacy Gate = N/A. Verified: `tech-stack.added: []` in all three plan summaries; module `config/` imports no new third-party dep (pydantic-free confirmed). See Accepted Risks Log R-24-03. | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-24-01 | T-24-04 | The `ConfigHolder[T]` generalization holds the app config reference ONLY; secrets (API key, webhook URL) live on the `Settings`/`.env` object behind the restart boundary and never enter the holder. Documented invariant preserved byte-for-byte from the analog (`holder.py:28-29`). No new information-disclosure surface introduced by the extraction. Medium severity, ASVS-L1 accept with rationale. | gsd-security-auditor | 2026-07-07 |
| R-24-02 | T-24-08 | Job-id collision via a `|` in a location name is fail-loud-at-load by the app-side `_no_pipe_in_identity` validator, which stays inside the concrete pydantic `Config` and is unaffected by the module extraction. No new tampering surface added by Phase 24; validator + test both present and green. Medium severity, ASVS-L1 accept with rationale. | gsd-security-auditor | 2026-07-07 |
| R-24-03 | T-24-SC | Supply-chain: zero package installs this phase — a pure in-repo/in-hub relocation of existing code. No new dependency enters the lockfile; the module `config/` package is confirmed pydantic-free and third-party-clean. Low severity, ASVS-L1 accept. | gsd-security-auditor | 2026-07-07 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-07 | 11 | 11 | 0 | gsd-security-auditor |

---

## Unregistered Flags

None. All three plan SUMMARYs' `## Threat Flags` sections read "None — no new security surface." No new attack surface appeared during implementation with an unmapped threat.

---

## Verification Notes (post-extraction path resolution)

The plans' cited paths were authored PRE-extraction (`yahir_reusable_bot/config/*` relative). Under the
v2.0 physical split the module code now lives in the sibling hub repo and the app wiring stayed here:

- **Module (hub repo `../Reusable/YahirReusableBot/`):** `yahir_reusable_bot/config/holder.py`,
  `yahir_reusable_bot/config/reload.py` — verified pydantic-free and weather-noun-free
  (`test_import_hygiene.py::test_config_module_never_imports_pydantic` + `::test_litmus_clean` both PASS).
- **App wiring (this repo):** the `ReloadEngine` construction (`excluded_ids`, `on_rejected`,
  `on_applied`, `validate`) moved from inline `daemon.py` into `weatherbot/scheduler/wiring.py`
  (`build_runtime`) during the LATER Phase 25 composition-root pass. The mitigations are traced there
  (`wiring.py:230-261`) plus the poll-loop/SIGHUP/watch-filter in `daemon.py`. The holder shim
  (`weatherbot/config/holder.py`) re-exports the module class; the `_no_pipe_in_identity` validator
  remains in `weatherbot/config/models.py`.
- **Tests:** `test_import_hygiene.py` (litmus + pydantic gate) lives in the hub; the direct engine /
  generic-holder tests (`test_reload_engine.py`, `test_config_holder_generic.py`) and all app-side
  keep-old / SIGHUP / .env-filter / pipe-validator tests live in this repo. All named tests were
  re-run during this audit and PASS.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-07
