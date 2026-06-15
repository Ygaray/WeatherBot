# Security Audit — Phase 7: CLI weather location one-shot

**Phase:** 7 — CLI weather location one-shot
**ASVS Level:** 1
**block_on:** high
**Verdict:** SECURED — 9/9 threats closed
**Register origin:** authored at plan time (all three 07-0N-PLAN.md carry parseable `<threat_model>` blocks). Verification confirms each declared mitigation exists in implemented code; no blind scan performed.

---

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-07-SC | Tampering | accept | CLOSED | `pyproject.toml:16-18` build-backend = `hatchling.build` (PyPA canonical). Dependency set `pyproject.toml:6-14` unchanged — no new/risky deps added by this phase. Accepted-risk premise holds. |
| T-07-PKG | Elevation | mitigate | CLOSED | `pyproject.toml:20-21` — exactly ONE `[project.scripts]` entry: `weatherbot = "weatherbot.cli:main"` (grep count = 1). No broadening of exposed surface; no new dependency. |
| T-07-01 | Tampering/Injection | mitigate | CLOSED | location is DATA only: `command.py:50-70` parses via `strip`/`casefold`/slice only (no eval/format/shell); `loader.py:40-64` `resolve_location` matches by casefold-equality against configured names; `templates/renderer.py:75-87` `render` is whitelist regex substitution — explicitly "no `str.format`; no `eval`". grep for `eval(`/`exec(`/`os.system`/`subprocess`/`.format(` across cli + interactive + client + loader = none. No geocode path reachable from `weather` (`cli.py:326-342` `_cmd_weather` → `run_weather` → `lookup_weather`; `client.py:67` geocode used only by `do_geocode`). |
| T-07-02 | Information Disclosure | mitigate | CLOSED | `run_weather` except arms are outcome-only: `cli.py:315` logs `status=exc.response.status_code`; `cli.py:318` logs `error=type(exc).__name__`. No `appid`/URL/`exc.request.url` logged. `UnknownLocationError` message (`lookup.py:54-60`) carries only requested + valid names. httpx URL-leak suppressed at `client.py:39` (`httpx` logger → WARNING). |
| T-07-03 | DoS (self-inflicted) | mitigate | CLOSED | `run_weather` retry bound at `cli.py:286-296`: `stop_after_attempt(_MANUAL_MAX_ATTEMPTS)` (=3, `cli.py:179`) + `wait_exponential(multiplier=1, max=10)`; retry arm is `retry_if_exception(is_transient)` only. `retry.py:71` PERMANENT = {400,401,403,404}; `is_transient` (`retry.py:80-91`) returns False for 401/403 → reraised on attempt 1. Confirmed by `test_cli.py:701` (401 → 1 attempt) and `test_cli.py:677` (persistent 429 → ≤3 attempts). |
| T-07-04 | Elevation | accept | CLOSED | `weather` path is strictly read-only: `cli.py:253-323` `run_weather` → `lookup_weather`, which `lookup.py:13-14,102` writes nothing to the store (no db path, no store import). No send/persist/daemon reachable from the `weather` subcommand. Clean-break subcommands add no new privileged capability. Accepted-risk premise holds. |
| T-07-05 | Information Disclosure | mitigate | CLOSED | Regression guard present: `test_cli.py:677-698` (`test_weather_fetch_failure_exhausted_transient_exits_3`) asserts `appid`/`api_key`/`https://` absent from stdout+stderr on the failure path; `test_cli.py:701-712` repeats the secret-hygiene assertion on the 401 auth path. |
| T-07-06 | Tampering | accept | CLOSED | `deploy/weatherbot.service:29` ExecStart = `/usr/bin/uv run weatherbot run` (command string migrated `--run`→`run`). Unit privileges unchanged: `User=<USER>` non-root (`:36`), `EnvironmentFile=<REPO>/.env` only (`:34`), no inline `Environment=KEY=`. Migration documented in `deploy/README.md:88-108`. Accepted-risk premise holds. |
| T-07-07 | Repudiation/regression | mitigate | CLOSED | Full suite green after clean break: `uv run pytest -q` → **215 passed** (≥206 required). |

---

## Unregistered Flags

None. No `## Threat Flags` section is present in any of `07-01-SUMMARY.md`, `07-02-SUMMARY.md`, `07-03-SUMMARY.md`; no new unmapped attack surface was declared during implementation.

---

## Accepted Risks Log

- **T-07-SC** (Tampering — hatchling build backend): accepted. hatchling is the PyPA canonical build backend; phase introduces no new/`[SUS]`/`[ASSUMED]` dependencies.
- **T-07-04** (Elevation — subcommand surface): accepted. Clean break removes flags and adds no privileged capability; `weather` is read-only.
- **T-07-06** (Tampering — deploy ExecStart string): accepted. Only the command string changed (`--run`→`run`); no unit privilege/user/EnvironmentFile broadening. Host redeploy is a manual operator step.

---

## Notes

- Implementation files were treated as READ-ONLY; nothing in the implementation was modified.
- T-07-01: although the user-supplied location ultimately becomes the `{location}` render value, `render` substitutes it as an output value via a whitelist regex (not as a format/template string), so the user string cannot itself trigger token interpolation or code execution.
