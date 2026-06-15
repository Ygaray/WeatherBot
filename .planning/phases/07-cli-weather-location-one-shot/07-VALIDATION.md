---
phase: 7
slug: cli-weather-location-one-shot
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-15
validated: 2026-06-15
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=9.0.3 (`[dependency-groups] dev` in pyproject.toml) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| **Quick run command** | `uv run pytest tests/test_cli.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | quick ~2-5s (single offline file, injected `_FakeClient`, no network); full ~15-25s (≥206 tests, all fixture-driven/offline) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_cli.py -x`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green (≥206 tests; new `weather` tests added) AND `uv run weatherbot --help` exits 0
- **Max feedback latency:** ~5 seconds (quick command on the single CLI test file)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | CMD-01 (D-03) | T-07-SC / T-07-PKG | hatchling = canonical PyPA backend; only one entry point exposed; no new dep | smoke | `uv sync && uv run weatherbot --help` (exit 0; `.venv/bin/weatherbot` exists) | ✅ existing (uv/pytest infra) | ✅ green |
| 07-02-01 | 02 | 1 | CMD-01 / CMD-03 / CMD-04 / CMD-05 | T-07-01 / T-07-02 / T-07-03 | UnknownLocationError caught first (no network on unknown path); outcome-only error logging (no appid/URL); is_transient-only retry never retries 401/403 | unit (tdd) | `uv run pytest tests/test_cli.py -k weather -x -q` then `uv run python -c "from weatherbot.cli import run_weather, _cmd_weather"` | ✅ 9 `test_weather_*` in tests/test_cli.py | ✅ green |
| 07-02-02 | 02 | 1 | CMD-01 / CMD-03 / D-07 / D-09 | T-07-04 | clean-break subcommand surface adds no new privilege; quiet-by-default scoped to `weather` only | smoke | `uv run python -c "from weatherbot.cli import main; assert main(['weather','x']) in (0,1,2,3)"` && `uv run weatherbot --help 2>&1 \| grep -E "weather\|run\|check\|send-now\|geocode"` | ✅ existing infra (full matrix in 07-03-02) | ✅ green |
| 07-03-01 | 03 | 2 | CMD-01 / CMD-03 / CMD-04 / CMD-05 (migration regression) | T-07-07 | clean break drops no behavior — migrated handlers keep original exit codes | unit (rewrite) | `test -z "$(grep -rn 'main(\["--' tests/)"` && `uv run pytest tests/test_cli.py tests/test_scheduler.py -q` | ✅ existing (rewritten callsites) | ✅ green |
| 07-03-02 | 03 | 2 | CMD-01 / CMD-03 / CMD-04 / CMD-05 (+ D-05/D-08/D-09) | T-07-05 | error test asserts no `appid`/webhook URL in stderr/logs (T-04-01 regression guard) | unit | `uv run pytest tests/test_cli.py -k weather -q` (exit-code matrix 0/1/2/3, stdout-vs-stderr split, byte-equality vs v1 template, unknown-path no-network, quiet-vs-`-v`) | ✅ 9 `test_weather_*` in tests/test_cli.py | ✅ green |
| 07-03-03 | 03 | 2 | CMD-01 (D-02) | T-07-06 | only the ExecStart command string changes; no broadening of unit privileges/user/EnvironmentFile | smoke | `test -z "$(grep -rn 'weatherbot --run\|m weatherbot --run' deploy/)"` && `grep -rn 'weatherbot run' deploy/weatherbot.service deploy/README.md` | ✅ existing deploy artifacts | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

The real Wave 0 gaps from RESEARCH § "Wave 0 Gaps" / § "Phase Requirements → Test Map" — all live inside the EXISTING `tests/test_cli.py` and reuse established seams; no new framework, no new fixtures, no new conftest:

- [x] New `weather`-subcommand tests in `tests/test_cli.py` (exit 0 configured / 0 default / 1 unknown-lists-valid-names / 2 bad-config / 3 exhausted-transient AND first-attempt 401, stdout-vs-stderr split, byte-equality vs v1 template, quiet-vs-`-v`) — covers CMD-01/03/04/05 + D-05/D-08/D-09. **Authored in task 07-03-02** — 9 `test_weather_*` tests land in `tests/test_cli.py` (verified green).
- [x] Rewrite existing `main(["--check"/"--send-now", …])` calls in `tests/test_cli.py` and `tests/test_scheduler.py` (L619 `--run`) to subcommand form — covers the migration regression bar (Pitfall 2). **Done in task 07-03-01** — `grep -rn 'main(\["--' tests/` returns nothing (verified).
- [x] Smoke check that `[build-system]`+`[project.scripts]` produce a resolvable `weatherbot` script (`uv run weatherbot --help`) — covers D-03 (Pitfall 1). **Done in task 07-01-01** — `.venv/bin/weatherbot` exists, `--help` exits 0 (verified).

**Existing infrastructure covers the rest:** pytest + `[tool.pytest.ini_options]` already configured in `pyproject.toml`; `_FakeClient`, `_config`, `load_fixture`, `capsys`, the `weatherbot.cli.time.sleep` patch seam, and `tests/fixtures/onecall_*.json` already exist (reused, NO new fixtures). No framework install required.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live-host redeploy on `yahir-mint` (the deployed systemd unit still runs `ExecStart=… --run` and the host `.venv` lacks the new console script until re-synced) | CMD-01 / D-02 | Claude cannot mutate `/etc/systemd/system/` or restart services on the remote host; requires `sudo` + a reboot/restart on a machine outside the repo | 1. Pull the updated repo on `yahir-mint`. 2. `uv sync` so `.venv/bin/weatherbot` materializes (new console script). 3. Edit `/etc/systemd/system/weatherbot.service` so `ExecStart` uses `weatherbot run` (not `--run`). 4. `sudo systemctl daemon-reload`. 5. `sudo systemctl restart weatherbot.service`. 6. Confirm `systemctl status weatherbot.service` is `active (running)` and the next scheduled briefing fires. 7. Optionally `uv run weatherbot weather home` on the host prints a briefing and exits 0. |
| Live `weatherbot weather home` against the real OpenWeather API (needs `.env` + network) | CMD-01 | Requires real `OPENWEATHER_API_KEY` + outbound network not present in the offline exec/CI env | Run `uv run weatherbot weather home` on a host with a valid `.env`; expect a briefing on stdout, exit 0, and NO `lookup complete` INFO line (and the INFO line WITH `-v`). Authoritative coverage of this behavior is the Plan 03 offline matrix (07-03-02); this is an optional confidence check only. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (the `weather` matrix is authored in 07-03-02; 07-02 tasks gate on import/parse + `--help`, not the not-yet-written matrix)
- [x] No watch-mode flags
- [x] Feedback latency < 5s (quick command)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-15

> Note on `wave_0_complete` — flipped to `true` on 2026-06-15 after retroactive validation confirmed the principal Wave 0 gap (the `weather` exit-matrix tests, task 07-03-02) landed on disk as 9 `test_weather_*` tests and runs green. The migration rewrite (07-03-01) and console-script smoke (07-01-01) are likewise confirmed.

---

## Validation Audit 2026-06-15

Retroactive audit (State A) — VALIDATION.md was authored at planning time with all rows `⬜ pending`; this audit reconciles it against the executed, committed phase artifacts. No new tests were needed; all planned coverage exists and is green.

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

**Evidence (commands re-run during audit):**
- `uv run pytest tests/test_cli.py -k weather -q` → **9 passed** (full exit-code matrix 0/1/2/3, stdout/stderr split, byte-equality vs v1, no-network unknown path, quiet-vs-`-v`).
- `uv run pytest tests/test_cli.py tests/test_scheduler.py -q` → **57 passed** (migration regression).
- `uv run pytest` → **215 passed** (full suite; +9 over the 206 baseline).
- `grep -rn 'main(\["--' tests/` → no output (no removed-flag callsites remain).
- `uv run weatherbot --help` → exit 0; `.venv/bin/weatherbot` console script present.
- `deploy/weatherbot.service` line 29 `ExecStart=/usr/bin/uv run weatherbot run`; `deploy/README.md` examples on `run` form (residual `--run` tokens are explanatory prose only).

All 6 per-task rows → ✅ green. The 2 Manual-Only items (live-host `yahir-mint` redeploy; live OpenWeather API call) remain correctly manual — they require remote `sudo`/network outside the repo and are not automatable. Phase 7 is **Nyquist-compliant**.
