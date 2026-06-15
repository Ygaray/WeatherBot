---
phase: 7
slug: cli-weather-location-one-shot
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-15
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
| 07-01-01 | 01 | 1 | CMD-01 (D-03) | T-07-SC / T-07-PKG | hatchling = canonical PyPA backend; only one entry point exposed; no new dep | smoke | `uv sync && uv run weatherbot --help` (exit 0; `.venv/bin/weatherbot` exists) | ✅ existing (uv/pytest infra) | ⬜ pending |
| 07-02-01 | 02 | 1 | CMD-01 / CMD-03 / CMD-04 / CMD-05 | T-07-01 / T-07-02 / T-07-03 | UnknownLocationError caught first (no network on unknown path); outcome-only error logging (no appid/URL); is_transient-only retry never retries 401/403 | unit (tdd) | `uv run pytest tests/test_cli.py -k weather -x -q` then `uv run python -c "from weatherbot.cli import run_weather, _cmd_weather"` | ❌ W0 (weather tests authored in 07-03-02) | ⬜ pending |
| 07-02-02 | 02 | 1 | CMD-01 / CMD-03 / D-07 / D-09 | T-07-04 | clean-break subcommand surface adds no new privilege; quiet-by-default scoped to `weather` only | smoke | `uv run python -c "from weatherbot.cli import main; assert main(['weather','x']) in (0,1,2,3)"` && `uv run weatherbot --help 2>&1 \| grep -E "weather\|run\|check\|send-now\|geocode"` | ✅ existing infra (full matrix in 07-03-02) | ⬜ pending |
| 07-03-01 | 03 | 2 | CMD-01 / CMD-03 / CMD-04 / CMD-05 (migration regression) | T-07-07 | clean break drops no behavior — migrated handlers keep original exit codes | unit (rewrite) | `test -z "$(grep -rn 'main(\["--' tests/)"` && `uv run pytest tests/test_cli.py tests/test_scheduler.py -q` | ✅ existing (rewritten callsites) | ⬜ pending |
| 07-03-02 | 03 | 2 | CMD-01 / CMD-03 / CMD-04 / CMD-05 (+ D-05/D-08/D-09) | T-07-05 | error test asserts no `appid`/webhook URL in stderr/logs (T-04-01 regression guard) | unit | `uv run pytest tests/test_cli.py -k weather -q` (exit-code matrix 0/1/2/3, stdout-vs-stderr split, byte-equality vs v1 template, unknown-path no-network, quiet-vs-`-v`) | ❌ W0 (new tests created by this task) | ⬜ pending |
| 07-03-03 | 03 | 2 | CMD-01 (D-02) | T-07-06 | only the ExecStart command string changes; no broadening of unit privileges/user/EnvironmentFile | smoke | `test -z "$(grep -rn 'weatherbot --run\|m weatherbot --run' deploy/)"` && `grep -rn 'weatherbot run' deploy/weatherbot.service deploy/README.md` | ✅ existing deploy artifacts | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

The real Wave 0 gaps from RESEARCH § "Wave 0 Gaps" / § "Phase Requirements → Test Map" — all live inside the EXISTING `tests/test_cli.py` and reuse established seams; no new framework, no new fixtures, no new conftest:

- [ ] New `weather`-subcommand tests in `tests/test_cli.py` (exit 0 configured / 0 default / 1 unknown-lists-valid-names / 2 bad-config / 3 exhausted-transient AND first-attempt 401, stdout-vs-stderr split, byte-equality vs v1 template, quiet-vs-`-v`) — covers CMD-01/03/04/05 + D-05/D-08/D-09. **Authored in task 07-03-02** (the exit matrix cannot run until then; 07-02's tasks verify import/parse + `--help` surface only).
- [ ] Rewrite existing `main(["--check"/"--send-now", …])` calls in `tests/test_cli.py` (L295/308/314/322) and `tests/test_scheduler.py` (L619 `--run`) to subcommand form — covers the migration regression bar (Pitfall 2). **Done in task 07-03-01.**
- [ ] Smoke check that `[build-system]`+`[project.scripts]` produce a resolvable `weatherbot` script (`uv run weatherbot --help`) — covers D-03 (Pitfall 1). **Done in task 07-01-01.**

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

> Note on `wave_0_complete: false` — the new `weather` exit-matrix tests (the principal Wave 0 gap) are AUTHORED during execution in task 07-03-02; they do not yet exist on disk at planning time. The flag flips to `true` once 07-03-01/02 land. Existing pytest infra + fixtures + seams require no setup.
