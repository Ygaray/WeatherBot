---
phase: 23
slug: scheduler-engine-occurrencestore-jobstore-seam
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-07
---

# Phase 23 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
>
> Phase 23 built the scheduler-engine / OccurrenceStore / JobStore seam during milestone v2.0
> ("The Great Decoupling"). The module-side code (`SchedulerEngine`, `OccurrenceStore`,
> `JobStore`/`MemoryJobStore`) now lives in the **hub repo**
> (`../Reusable/YahirReusableBot/yahir_reusable_bot/{scheduler,ports}/`); the consuming daemon
> stays app-side (`weatherbot/scheduler/daemon.py`). Cited PLAN paths were authored pre-extraction,
> so mitigations were verified against the post-extraction hub package path.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| host/app orchestration → module engine | `daemon.py` constructs and owns the `BackgroundScheduler` and passes already-validated `(job_id, trigger, callback, args, kwargs)` into `engine.register`. Relocation only — no new external input surface. | Job identity (plain-string id), native trigger object, opaque callback + args/kwargs (which internally hold `client`/`channel`/`stop_event` runtime handles). |
| app → SQLite `sent_log` | The `OccurrenceStore` **adapter body** (`claim_slot`/`was_sent`/`release_claim`) stays in `weatherbot/weather/store.py`, parameterized `?`-only, untouched this phase. The module ships only the structural Protocol. | Exactly-once claim keyed on `(location_name, send_time, local_date)`. |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-23-01 | Information disclosure (STRIDE-I) | `SchedulerEngine` logging / job repr (hub `scheduler/engine.py`) | medium | accept | Engine emits **zero** log calls; secrets ride inside opaque `client`/`channel` kwargs the engine never names, inspects, or logs. No new log surface (T-04-01 preserved). | closed |
| T-23-02 | Tampering / DoS (STRIDE-T) | `JobStore` serialization contract (hub `ports/jobstore.py`) | medium | mitigate | Docstring constraint 2 forbids closing a live client/socket/channel/threading primitive over `args`; the D-13 durable-store-boundary paragraph names the process-level registry relocation (build nothing). Shipped `MemoryJobStore` never serializes → no v2.0 attack surface. | closed |
| T-23-03 | Tampering (STRIDE-T) | `sent_log` exactly-once SQL (`INSERT OR IGNORE … rowcount==1`, `store.py`) | high | mitigate | `store.py` binds `VALUES (?, ?, ?, ?)` parameterized-only with a `rowcount == 1` gate; the daemon rebind never inline-formats a key into SQL (no SQL touched at all). SQLi mitigation T-03-01 preserved. | closed |
| T-23-04 | Information disclosure (STRIDE-I) | engine/daemon job registration logging (`daemon.py` + hub `engine.py`) | medium | accept | Registration logging stays outcome-only; no daemon log line emits `kwargs`/`client`/`channel`/secret tokens; the engine never logs. No new log surface (T-04-01 preserved). | closed |
| T-23-SC | Tampering — supply chain (STRIDE-T) | npm/pip/cargo installs | high | mitigate | No packages installed this phase — relocation within the frozen, already-locked stack. No phase-23 commit touches `pyproject.toml`/`uv.lock`; module files import only stdlib + already-locked `apscheduler`. | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `block_on: high` count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

**Note:** T-23-SC appears in both `23-01-PLAN.md` and `23-02-PLAN.md` with identical scope (one supply-chain threat spanning the phase); recorded once here.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-23-01 | T-23-01 | The `SchedulerEngine` (hub `scheduler/engine.py`) has no logging calls whatsoever and forwards `callback`/`args`/`kwargs` opaquely to `add_job`. Secrets exist only inside the `client`/`channel` objects carried in `kwargs`, which the engine never names, inspects, or serializes. Residual disclosure risk is confined to whatever the app itself chooses to log — unchanged from pre-extraction (T-04-01). Medium severity, below the `high` block threshold; no new module-side log surface. | Yahir (phase owner) | 2026-07-07 |
| AR-23-02 | T-23-04 | Daemon registration logging is outcome-only; grep confirms no daemon log line emits `kwargs`/`client`/`channel`/`secret`/`token`/`webhook`/`api_key`. The relocation routes the same kwargs through `engine.register` without adding a log line. Residual risk unchanged from pre-extraction (T-04-01). Medium severity, below the `high` block threshold. | Yahir (phase owner) | 2026-07-07 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-07 | 5 | 5 | 0 | gsd-security-auditor (Claude) |

*Threats Total = 5 unique IDs (T-23-SC counted once though it appears in both plan registers).*

### Verification Evidence (ASVS L1 — pattern present in cited/relocated file)

| Threat ID | Disposition | Evidence |
|-----------|-------------|----------|
| T-23-01 | accept | `../Reusable/YahirReusableBot/yahir_reusable_bot/scheduler/engine.py` — no `log`/`logger`/`print`/`structlog` call anywhere; only docstring text ("sent-log", "backlog") matched. Documented AR-23-01. |
| T-23-02 | mitigate | `../Reusable/YahirReusableBot/yahir_reusable_bot/ports/jobstore.py:36-44` (constraint 2 forbids live client/socket/channel/threading primitive over args) + `:46-56` (D-13 durable-store-boundary paragraph naming registry relocation) + `MemoryJobStore` `:61-72` "never serializes". |
| T-23-03 | mitigate | `weatherbot/weather/store.py:281-288` — `INSERT OR IGNORE INTO sent_log … VALUES (?, ?, ?, ?)` parameterized binds + `return cur.rowcount == 1`. Git: last commit touching store.py is `381fef0` (Phase 15); phase-23 commits `e7438b5`/`ed6e213` modified only `daemon.py` (store.py + catchup.py untouched). |
| T-23-04 | accept | `weatherbot/scheduler/daemon.py` — grep of all `log.*`/`logger.*` lines finds none emitting `kwargs`/`client`/`channel`/secret tokens. Documented AR-23-02. |
| T-23-SC | mitigate | Git `--stat --name-only` over all phase-23 commits (`a6c7abe f1886f0 0ec0523 e7438b5 ed6e213 01820f3`) shows no `pyproject.toml`/`uv.lock`/`requirements`/`package.json`/`Cargo` change. Module files import only stdlib (`os`, `typing`) + already-locked `apscheduler`. |

### Threat Flags (from SUMMARY `## Threat Flags`)

Neither `23-01-SUMMARY.md` nor `23-02-SUMMARY.md` contains a `## Threat Flags` section — no new attack surface was flagged during implementation. No unregistered flags.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-07
