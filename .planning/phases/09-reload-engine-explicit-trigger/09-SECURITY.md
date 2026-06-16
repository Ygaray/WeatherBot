---
phase: 09
slug: reload-engine-explicit-trigger
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-16
---

# Phase 09 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register authored at plan time across plans 09-01..09-05; verified retroactively
> against the implementation by gsd-security-auditor (ASVS L1, block_on=high).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| operator-edited `config.toml` + template files → `validate_config_and_templates` | Untrusted, hand-edited input crosses into the config layer; the validator is the gate that rejects malformed input before it can reach the live holder. | TOML config structure, template token strings (non-secret) |
| `weatherbot reload` (short-lived process) → running daemon | A separate UID-local process discovers the daemon PID and sends SIGHUP — the new cross-process control path; PID recycling could redirect the signal. | PID (int), OS signal |
| SIGHUP (OS signal) → daemon reload path | A cross-process signal triggers a config re-read + live job mutation; must not run re-entrantly in the handler or tear live state. | Signal delivery + in-process config/job state |
| reloaded config → live `ConfigHolder` + APScheduler job set | A bad or mid-failing reload could leave torn live state (half-old/half-new config or jobs). | Config object, scheduler job table |
| reloaded config → sent-log exactly-once key | A reload can change a location's display name/tz; the key must stay anchored to a STABLE id so a reload cannot reset "already sent today". | sent_log key `(location_id, send_time, local_date)` |
| reload path → systemd READY / `.env` secrets | Reload must NEVER flip the health gate or re-read secrets (restart boundary). | systemd notify socket, secret material (must NOT cross) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-09-01 | Tampering | Hollow/stubbed test scaffold hiding exactly-once break | mitigate | Wave-0 tests fail RED on real ImportError; SC#4 test asserts on real `claim_slot`/`sent_log`, not a mock. Verified: 253 tests pass. | closed |
| T-09-02 | Repudiation / Info-Disclosure | SC#4 shipping untested; secrets entering validated surface | mitigate | Named load-bearing test exists; `validate_config_and_templates` builds `Config` only, never `Settings`/`.env` (`loader.py:99-139`). | closed |
| T-09-03 | Tampering | Malformed/partial config reaching the live holder | mitigate | Validator raises on bad TOML / schema / dup name+id / unknown token BEFORE any swap; reload PHASE 1 keeps old on raise (`loader.py:99-139`, `daemon.py:565-576`). | closed |
| T-09-04 | Tampering | Template-token injection via edited template | mitigate | Reuses `validate_template` allow-list (no `str.format`/eval; unknown tokens rejected at validate, literal at render) (`loader.py:123,137`). | closed |
| T-09-04b | Access Control | Non-owner triggering a reload | accept | `os.kill` is OS-enforced to the same UID; single-user personal daemon — no extra auth surface warranted at ASVS L1. | closed |
| T-09-05 | Tampering | id-default changing the sent-log key (first-day duplicate) | mitigate | `Location.id` defaults to the RAW name verbatim (byte-identical rows); casefold used only for uniqueness check, never the stored value (`models.py:109-118`). | closed |
| T-09-06 | Spoofing / Tampering | SIGHUP delivered to a recycled/unrelated PID | mitigate | `is_weatherbot_pid` reads `/proc/<pid>/cmdline` and matches **program identity** (`_argv_is_weatherbot`: argv0 basename `== "weatherbot"` or `python -m weatherbot`) BEFORE `os.kill`; substring match removed (CR-02 fix). `os.kill` itself guarded against ProcessLookup/PermissionError (CR-01). (`pidfile.py:100-119`, `cli.py:496-514`). | closed |
| T-09-07 | Tampering | Torn/partial PID-file read mid-write | mitigate | `write_pid_atomic` uses `tempfile.mkstemp` + `os.replace` (atomic on POSIX) — a reader never observes a partial PID file (`pidfile.py:34-59`). | closed |
| T-09-08 | Information Disclosure | check-config / reload / reload-outcome logs leaking secrets | mitigate | Outcome-only logging: pass/fail, reason, pid, diff counts — never a key or webhook URL; check-config never constructs `Settings` (`daemon.py:574-627`, `cli.py`). | closed |
| T-09-09 | Tampering | Exactly-once break → duplicate/skipped briefing on a reloaded NAME or TZ change (Pitfall #8, HIGHEST RISK) | mitigate | Key's first component is the STABLE `location.id`; reload never deletes `sent_log` rows; load-bearing test asserts an already-sent slot's re-fire loses on name/tz change. | closed |
| T-09-10 | Tampering | Claim/check desync (claim under id, released/checked under name) | mitigate | All 5 callsites (claim / release / record_alert / resolve_alert + catchup `was_sent`) moved to `id` in lockstep; name-keyed store callsites = 0 (`daemon.py`, `catchup.py:170`). | closed |
| T-09-11 | Tampering | Gratuitous SQLite schema migration on live sent_log | accept (avoid) | Column stays `location_name`; only the VALUE changes — `store.py` byte-unchanged (no `_SCHEMA` edit, no `ALTER TABLE`); git-confirmed untouched. | closed |
| T-09-12 | Tampering / DoS | Malformed/partial config applied → torn live state | mitigate | Two-phase validate-then-commit; PHASE 2 rolls back to `old_cfg` + rebuilt jobs on any reconcile throw (`daemon.py:582-616`). | closed |
| T-09-13 | Tampering | Job double-fire/drop on reload | mitigate | Diff-reconcile on the stable id with `replace_existing`/`remove_job`, never `remove_all_jobs()`; `__heartbeat__` excluded (`daemon.py:471-495`). | closed |
| T-09-14 | Elevation / DoS | Reload running re-entrantly in the SIGHUP handler | mitigate | `_handle_hup` only sets a `threading.Event`; the reload runs on the main thread via the poll loop (`daemon.py:809-811,961-982`). | closed |
| T-09-15 | Tampering / Info-Disclosure | Reload re-reading `.env` / flipping the systemd READY gate | mitigate | `_do_reload` constructs no `Settings` and never calls the notifier/READY (grep=0 in engine body). | closed |
| T-09-SC | Tampering (supply chain) | npm/pip/cargo installs | accept | Zero packages installed; stdlib `os`/`signal`/`tempfile`/`threading` + pinned APScheduler/pydantic only; `uv.lock` unchanged. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-09-01 | T-09-04b | `os.kill` is OS-enforced to the same UID; single-user personal daemon — no application-level reload auth warranted at ASVS L1. | Yahir | 2026-06-16 |
| AR-09-02 | T-09-11 | Keeping the `location_name` column and changing only the stored value avoids a live SQLite migration; zero migration risk is preferred over schema purity. | Yahir | 2026-06-16 |
| AR-09-03 | T-09-SC | No new third-party dependency introduced; supply-chain surface unchanged from v1.0. | Yahir | 2026-06-16 |

---

## Residual Advisories (non-blocking, not register threats)

Surfaced by code review / verification this phase; none High-severity; target host is Linux/systemd.

| Ref | Issue | Note |
|-----|-------|------|
| WR-04 | `/proc`-absent guard fails OPEN on non-Linux (`pidfile.py` `_read_proc_cmdline` returns the `b"weatherbot"` sentinel) | Only affects non-Linux hosts; production host is Linux. Consider fail-closed when Phase 10/11 touch this path. |
| WR-02 | Rollback `_restore_jobs` re-invokes the same `_register_jobs` that just failed; can leave a half-rebuilt live job set while only logging | Escalate (re-raise/critical-log) on restore failure so the operator knows the schedule is degraded. |
| IN-04 | `test_reconcile_failure_rolls_back` asserts only on `holder.current()`, not a genuinely restored job set | Add a variant that mutates live jobs before throwing to exercise the restore path. |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-16 | 17 | 17 | 0 | gsd-security-auditor (verify mode; ASVS L1, block_on=high) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-16
