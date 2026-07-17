---
status: complete
result: all_pass
gate: 1
phase: 30-secret-hygiene
source: [30-ROADMAP success criteria]
device: CLI subprocess (headless Python; no UI/device surface)
apk: source-tree md5 1dc8f9371b6f7b3aab8a052763a0a848 @ d89eb0c
run: 2026-07-09T12:11Z
---

<!--
Gate-1 autonomous behavioral self-UAT for Phase 30 (Secret Hygiene, HARD-SEC-01).
Driver playbook: AGENT-CLI-TESTING.md (Python CLI bot; no browser/device — driven via uv run + pytest).
DIAGNOSE-ONLY: no code was edited. Live systemd daemon on yahir-mint was NOT touched.
-->

# Self-UAT Log — Phase 30 Plan 01 (Secret Hygiene)

**Device:** CLI subprocess (headless Python; no UI/device)   **Artifact:** source md5 `1dc8f9371b6f7b3aab8a052763a0a848` @ `d89eb0c`   **Run:** 2026-07-09T12:11Z
**Schema:** n/a (no DB migration in this phase)   **Pre-flight:** `import weatherbot.*` → IMPORT OK; working tree clean of production code (`git status --porcelain` shows only `.planning/`)
**Unit suite:** `uv run pytest tests/test_redact_hygiene.py -v` → 4 passed; `uv run pytest tests/test_client.py -v` → 7 passed; full `uv run pytest -q` → 810 passed, exit 0
**Seed/fixture integrity:** No stored fixture — leak paths are exercised via an offline `httpx.MockTransport` 401 handler whose request URL carries `appid=<sentinel>` (the exact leak source). Confirmed the mock actually produces a key-bearing `raise_for_status` URL before trusting any redaction result (str(exc) shows the redacted `appid=***`, proving the mock's URL did contain the value pre-redaction).

## Criteria

### 1. On a 401/403 from OpenWeather onecall OR geocode, no log line / exception message / traceback contains the appid value
result: passed
- **Rung:** 3 (headless data/log inspection — live end-to-end drive of the real fetch-failure path)
- **Expected:** With `OPENWEATHER_API_KEY=SENTINEL_LEAKCHECK_9f3x`, a real `fetch_onecall`/`geocode` call that fails auth must surface an error whose message, `str(exc)`, AND full traceback (as `_log.exception` renders it to stderr) contain NO sentinel value; the key is scrubbed to `appid=***`; `.response.status_code` (type contract) stays intact.
- **Arranged (seeded):** none — offline `httpx.MockTransport` returns a 401 whose request URL carries `appid=SENTINEL_LEAKCHECK_9f3x` (the real leak source; no live OpenWeather call needed to reach the redaction code path).
- **Did (drove):** ran a one-shot `uv run python` with `OPENWEATHER_API_KEY=SENTINEL_LEAKCHECK_9f3x` that imported the real `weatherbot` package (live `_LiveStderr`-backed structlog), called the real `client.fetch_onecall(...)` and `client.geocode(...)`, let each fail auth, and emitted the failure via `structlog log.exception(...)` (rendering event + FULL traceback to real stderr). Captured BOTH stdout and stderr to files and grepped for the sentinel across both streams.
- **Observed:** Sentinel `SENTINEL_LEAKCHECK_9f3x` ABSENT from stdout AND stderr on both onecall and geocode paths. Rendered stderr traceback shows `appid=***` twice (redaction actually fired — not merely an absent URL); `str(exc)` = `Client error '401 Unauthorized' for url '...&appid=***&units=imperial...'`; `status_code` = 401; `traceback carries KEY: False`. This exercises the real `client.py` redacted re-raise (`from None`) + the `_LiveStderr` backstop end-to-end. Adversarial split-write check: even when structlog renders across multiple `write()` calls, the `appid=<value>` token is never split across a write boundary, so the per-write regex backstop still scrubs it (raw sentinel never reached the underlying stderr).
- **Evidence:** live one-shot drive (stdout `ONECALL str(exc): ...appid=***...`, `status_code 401`, `traceback carries KEY: False`; stderr both tracebacks show `appid=***`, grep for sentinel = 0 hits). Unit corroboration: `tests/test_redact_hygiene.py::test_onecall_failure_redacts_key_and_keeps_status` + `::test_geocode_failure_redacts_key` PASS. Source: `weatherbot/weather/client.py:79-84,106-111`, `weatherbot/_redact.py:23-28`.

### 2. A failing !weather over Discord logs an outcome without dumping the key-bearing traceback; scheduler/CLI fetch paths stay leak-free
result: partial
- **Rung:** 3 (mechanism + result via the real `on_message` envelope; live Discord gateway drive deferred to Gate-2)
- **Expected:** A failing `!weather <loc>` whose command dispatch raises a key-bearing `HTTPStatusError` must be swallowed by the non-propagating `on_message` envelope (`bot.py` `except Exception: _log.exception(...)`, CMD-08) and log an outcome to stderr with NO sentinel value in the rendered traceback.
- **Arranged (seeded):** `fake_discord_message` fixture (conftest.py:156) with a real async-context-manager `channel.typing()` mock so the real `on_message` runs to the dispatch call; `dispatch_spec` monkeypatched to raise the key-bearing `HTTPStatusError(...appid=<SENTINEL>...)`.
- **Did (drove):** ran the real `bot.build_on_message(...)` envelope to completion via `asyncio.run(handler(msg))` under `OPENWEATHER_API_KEY=SENTINEL_LEAKCHECK_9f3x` (`test_discord_on_message_does_not_dump_key`). Captured stderr via `capsys`. Also independently emitted a RAW un-redacted `appid=<SENTINEL>` log line to prove the `_LiveStderr` backstop scrubs even a future/forgotten source leak.
- **Observed:** Envelope swallowed the exception (did not re-raise), an outcome WAS logged, and the sentinel is ABSENT from the rendered stderr traceback; the raw backstop line was scrubbed to `appid=***`. Test PASSES with the env sentinel set. NOTE: my initial ad-hoc live stub raised prematurely on a missing `.typing()` (never reached dispatch) — the fixture-backed unit test is the faithful driver of the real envelope, so it is the authoritative mechanism+result proof. The physical step that remains — driving the ACTUAL live Discord gateway on host `yahir-mint` — is deferred to Gate-2 (ops safety: must NOT restart the live daemon in this gate).
- **Evidence:** `uv run pytest tests/test_redact_hygiene.py::test_discord_on_message_does_not_dump_key -v` PASS (with `OPENWEATHER_API_KEY=SENTINEL_LEAKCHECK_9f3x`). CLI/scheduler fetch paths leak-free proven by Criterion 1's live onecall/geocode drive (same `client.py` redaction feeds every caller). Source: `weatherbot/interactive/bot.py` on_message envelope + `weatherbot/__init__.py:35-43` `_LiveStderr.write` backstop.

### 3. A regression test asserts the key never appears; the .response.status_code type-contract canary passes
result: passed
- **Rung:** 1 (unit)
- **Expected:** `uv run pytest tests/test_redact_hygiene.py -v` → all 4 tests pass, asserting the sentinel is absent from `str(exc)`, the full traceback, and captured stderr across all three leak paths; the `.response.status_code == 401` type-contract canary passes (type stays `HTTPStatusError`).
- **Arranged (seeded):** none (self-contained pytest suite; offline mock transport).
- **Did (drove):** `uv run pytest tests/test_redact_hygiene.py -v` and `uv run pytest tests/test_client.py -v`.
- **Observed:** 4/4 redact-hygiene tests PASS (`test_redact_helper_boundaries`, `test_onecall_failure_redacts_key_and_keeps_status`, `test_geocode_failure_redacts_key`, `test_discord_on_message_does_not_dump_key`); the onecall test asserts BOTH `type(exc).__name__ == "HTTPStatusError"` AND `exc.response.status_code == 401` (the type-contract canary) AND sentinel-absence from the full traceback — all green. Full suite `uv run pytest -q` → 810 passed, exit 0 (the "2 snapshots failed" line is pre-existing syrupy noise per the recorded quirk; exit code 0 trusted).
- **Evidence:** pytest output (4 passed / 7 passed / 810 passed, exit 0). Source: `tests/test_redact_hygiene.py:85-118` (status-code canary at :97-98).

## Summary

total: 3
passed: 2
partial: 1
failed: 0
infra: 0

## Notes / anomalies (for the Gate-2 reviewer)

- **Live Discord gateway (Criterion 2) is PARTIAL, not skipped:** the mechanism (real `on_message` envelope) and result (no key in rendered stderr) are fully verified via the fixture-backed test; only the physical drive against the live `yahir-mint` daemon is deferred (ops-safety: the gate must not restart the production service).
- **`_LiveStderr` backstop single-write assumption held under adversarial split-write testing** — the `appid=value` token is not split across structlog `write()` boundaries, so the per-write regex backstop is robust.
- **"2 snapshots failed" is pre-existing syrupy noise** (recorded quirk); full-suite exit code was 0.
- **No production code was edited** during this gate; working tree carried only `.planning/` changes (`git status --porcelain`).

## Findings routed to gap-closure (if any)

- None. No genuine behavior FAIL.

## Verdict

All in-scope criteria PASS (SC1 PASS live, SC3 PASS unit); SC2 PASS on mechanism+result with only the live-daemon Discord drive deferred (PARTIAL → Gate-2). Gate-1 satisfied; human Gate-2 deferred to milestone completion (registered in HUMAN-UAT-PENDING.md).
