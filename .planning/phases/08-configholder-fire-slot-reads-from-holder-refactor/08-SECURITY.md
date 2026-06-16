# SECURITY.md — Phase 08: ConfigHolder + fire_slot Reads-From-Holder Refactor

**Audited:** 2026-06-15
**ASVS Level:** 1
**block_on:** high
**Verdict:** SECURED — 11/11 threats closed (8 mitigate, 3 accept), 0 open.

This phase is a pure in-process refactor: it introduces a `ConfigHolder` (one live
immutable `Config` reference with lock-free read / locked swap), freezes all five
config models, and rewires `fire_slot` + the three daemon readers to resolve config
from the holder at fire time. No external input, network, auth, or persisted-state
surface was added. Verification is by grep/code-evidence against the
implementation, plus the full 226-test suite passing as the regression proof for the
unhashability concern.

---

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-08-01 | Tampering | mitigate | CLOSED | `tests/test_config_holder.py:89` `test_concurrent_read_swap_safe` — 8 reader threads loop `holder.current()` (line 109) while a writer alternates `holder.replace()` (line 118) for 5000 iterations; torn/None reads collected into a shared error list and asserted empty. Exercises `current()`/`replace()` concurrently as required. |
| T-08-02 | Information Disclosure | mitigate | CLOSED | `weatherbot/config/holder.py` stores a `Config` reference ONLY (`self._config`, line 47). Grep for `settings`/`appid`/`webhook_url`/`.env`/`api_key` returns no code — the single hit (line 25) is a docstring stating secrets never enter. In `daemon.py`, `settings=` is threaded SEPARATELY into `fire_slot`/`send_now` and never enters the holder. |
| T-08-03 | Tampering | mitigate | CLOSED | `weatherbot/config/models.py` — `frozen=True` present on all 5 models' `ConfigDict(extra="forbid", frozen=True)` (lines 45, 93, 126, 154, 219; `grep -c` = 5). No v1 `class Config:`/`allow_mutation` idiom. Guard proven by `tests/test_models.py:272` `test_frozen_rejects_mutation`, parametrized over Schedule/Location/WebhookIdentity/Reliability/Config, asserting `pydantic.ValidationError` (line 279) — never `FrozenInstanceError`. |
| T-08-04 | Tampering | mitigate | CLOSED | No `lru_cache`/`hash(config)`/`set(config)`/`frozenset`/config-as-dict-key introduced anywhere in `weatherbot/config/`, `daemon.py`, or `cli.py` (grep empty). Full suite green (`226 passed`) is the regression proof that no config-hashing path crashed under newly-unhashable frozen list-bearing models. |
| T-08-05 | Tampering | mitigate | CLOSED | `weatherbot/config/holder.py` — `current()` (line 50-57) is a lock-free single `LOAD_ATTR` (`return self._config`) vs the single `STORE_ATTR` in `replace()` under the GIL; reader sees old or new whole snapshot. Proven by `test_concurrent_read_swap_safe`. |
| T-08-06 | Tampering | mitigate | CLOSED | `weatherbot/config/holder.py:65` `replace()` body is `with self._lock: self._config = new_config`; `self._lock = threading.Lock()` (line 48) serializes writers. |
| T-08-07 | Tampering | accept (deferred to Phase 9 / CFG-04) | CLOSED | See Accepted Risks log below. `replace()` intentionally does no validation (holder.py docstring lines 18-24). Verified the ONLY production `.replace(` matches are `datetime.replace(tzinfo=...)` in `catchup.py` — there is NO production `ConfigHolder.replace()` caller in Phase 8; only tests drive it, always with an already-loaded frozen `Config`. |
| T-08-08 | Tampering | mitigate | CLOSED | `weatherbot/scheduler/daemon.py` — `fire_slot` resolves `snapshot` ONCE (lines 148-153) and threads the SAME object through the reliability budget read (`snapshot.reliability.*`, lines 200-202) AND `send_now(config=snapshot)` (line 211). A mid-fire `replace()` between reads is structurally impossible. Proven by `test_inflight_job_keeps_snapshot` (`tests/test_config_holder.py:143`). |
| T-08-09 | Tampering | mitigate | CLOSED | `weatherbot/scheduler/daemon.py:385` `add_job(kwargs={"holder": holder, ...})` replaces the old `{"config": config}` (grep for `"config": config` is empty). An unchanged job re-reads `holder.current()` each fire. Proven by `test_unchanged_job_renders_after_replace` (`tests/test_config_holder.py:185`). |
| T-08-10 | Tampering | mitigate | CLOSED | `weatherbot/scheduler/daemon.py:396` `id=f"{location.name}|{slot.time}|{slot.days}"` left byte-identical (grep count = 1, single occurrence). Phase 9 exactly-once job-diff key undisturbed. |
| T-08-SC | Tampering | accept | CLOSED | See Accepted Risks log below. Zero packages installed; last `uv.lock` change is Phase 07 (`ee4cd02`), none in Phase 08; all four 08-* SUMMARYs declare `tech-stack.added: []`. Stdlib `threading` only. |

---

## Accepted Risks Log

| Threat ID | Category | Rationale | Owner / Follow-up |
|-----------|----------|-----------|-------------------|
| T-08-07 | Tampering — unvalidated config via `replace()` | `replace()` deliberately performs no validate-before-swap in Phase 8 (D-04). In Phase 8 it is only ever fed an already-loaded, schema/IANA/units-validated, frozen `Config` (tests only; no production caller exists yet — confirmed by grep). The lock in `replace()` is the seam where Phase 9 will hang the atomic validate-then-swap. | Phase 9 / CFG-04 owns validate-before-swap. |
| T-08-SC | Tampering — supply chain (npm/pip/cargo installs) | No dependencies added in Phase 08. `uv.lock` unchanged since Phase 07; all phase SUMMARYs report `added: []`; the refactor uses only stdlib `threading` and the already-pinned pydantic 2.13.4 `frozen=True` flag. | None — no action required. |

---

## Unregistered Flags

None. The four 08-* SUMMARY files each carry a "Threat Surface Scan" / "Threat
Mitigations Applied" note, and every flag raised there maps to an existing threat ID
in the register (T-08-01 through T-08-10, T-08-SC). No new unmapped attack surface
appeared during implementation. Consistent with the phase being a no-new-surface
in-process refactor.

---

## Auditor Notes

- Implementation files were NOT modified (read-only audit).
- The grep for secrets in `holder.py` yielded one hit — a docstring line affirming
  secrets never enter — not a code path; treated as confirming-by-absence.
- The full suite (`226 passed`) doubles as the falsifiable spec: T-08-01/05/06 are
  guarded by `test_concurrent_read_swap_safe`, T-08-03 by `test_frozen_rejects_mutation`,
  T-08-08 by `test_inflight_job_keeps_snapshot`, T-08-09 by
  `test_unchanged_job_renders_after_replace`, all green.
