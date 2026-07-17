---
phase: 30
slug: secret-hygiene
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-09
---

# Phase 30 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `30-RESEARCH.md` § Validation Architecture (verified against the live repo runtime).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (+ pytest-cov 7.1.0, syrupy 5.3.4) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `addopts="-ra"`) |
| **Quick run command** | `uv run pytest tests/test_redact_hygiene.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~10 seconds (targeted file); full suite < 60s |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_redact_hygiene.py tests/test_client.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work-agentic` (Gate-1):** Full suite must be green
- **Max feedback latency:** ~15 seconds
- **Note:** pre-existing syrupy "N snapshots failed" line can print at exit 0 — trust the exit code, not the snapshot line (see `[[pytest-snapshot-report-quirk]]`).

---

## Per-Task Verification Map

Task IDs are assigned by the planner; rows below bind each HARD-SEC-01 behavior to its automated proof.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | 01 | 1 | HARD-SEC-01 | T-30-01 | onecall 401 → key absent from `str(exc)` + traceback; `.response.status_code` still readable | unit | `uv run pytest tests/test_redact_hygiene.py::test_onecall_failure_redacts_key_and_keeps_status -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | HARD-SEC-01 | T-30-01 | geocode 401 → key absent; `.response.status_code` readable | unit | `uv run pytest tests/test_redact_hygiene.py::test_geocode_failure_redacts_key -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | HARD-SEC-01 | T-30-01 | Discord `on_message` failure → key absent from captured stderr (`capsys.err`) | integration | `uv run pytest tests/test_redact_hygiene.py::test_discord_on_message_does_not_dump_key -x` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | HARD-SEC-01 | T-30-01 | `redact_appid` boundary correctness (keeps endpoint/status/params, handles URL-encoded) | unit | `uv run pytest tests/test_redact_hygiene.py::test_redact_helper_boundaries -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_redact_hygiene.py` — the 4 tests above (covers HARD-SEC-01 across onecall + geocode + Discord end-to-end + helper boundaries).
- [ ] `weatherbot/_redact.py` must exist before its tests (implementation task, not a test task).
- [ ] Confirm the repo's existing async-test mechanism for the `on_message` coroutine test — reuse `tests/test_bot.py`'s pattern rather than assuming `@pytest.mark.asyncio`.
- [ ] May reuse `tests/test_client.py`'s `_install_mock` helper (extract to `conftest.py` only if cross-file import is awkward).

*No new framework install needed — existing pytest infra covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live daemon picks up redaction | HARD-SEC-01 | Requires restarting the production systemd service on host `yahir-mint` (editable install) | Deferred Gate-2 ops item: `sudo systemctl restart weatherbot` on `yahir-mint`, then trigger a failing `!weather <loc>` and confirm journald shows no `appid` value. See `[[weatherbot-live-systemd-service]]`. |
| Key rotation (if already leaked to on-disk logs) | HARD-SEC-01 | Human-gated security decision (out of code scope) | If historical logs already captured the key, rotate the OpenWeather key. Flag for the operator; not a phase code task. |

*All in-code phase behaviors have automated verification (capsys-based). Only the live-daemon rollout + optional key rotation are manual Gate-2 obligations.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
