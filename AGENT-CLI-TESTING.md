---
status: needs-confirmation
platform: cli
workflow.uat_driver_playbook: AGENT-CLI-TESTING.md
generated_by: gsd-verify-work-agentic (headless bootstrap, phase 29)
generated_at: 2026-07-08
---

# WeatherBot — Agent CLI UAT Driver Playbook

WeatherBot is a long-running Python CLI weather-briefing daemon, NOT a UI app. There is no
browser/device. You "drive" it by invoking the CLI as a subprocess and inspecting **exit codes,
structured logs, and the durable single-row SQLite health table**.

> **status: needs-confirmation** — auto-drafted headlessly during the phase-29 run. The owner
> should confirm the isolation + drive mechanics at the next human touchpoint.

## D1 — Target + preflight
- **Target:** the `weatherbot` CLI (`python -m weatherbot <cmd> --config <path>`), run as a subprocess.
- **Preflight:** the project venv resolves (`uv run python -c "import weatherbot"` → `IMPORT OK`).
  A failed import / missing venv is **INFRA**, not a behavior FAIL.
- **⚠ SAFETY — a LIVE production daemon runs on host `yahir-mint`.** NEVER `systemctl` /
  `daemon-reload` / touch the live unit. Only local test invocations.

## D2 — Build / install / launch
- No compile step (Python). "Build identity" = `git rev-parse --short HEAD` + confirm the working
  tree has no *production-code* modifications (`git status --porcelain` shows only `.planning/`).
- Rung-0 "compile" = importability: `uv run python -c "import weatherbot.cli, weatherbot.ops.selfcheck, weatherbot.scheduler.daemon, weatherbot.channels.factory; print('IMPORT OK')"`.
- Bring-up = run the subprocess (see D3). Do it with the venv python directly so cwd can be an
  isolated tempdir: `PY=/home/yahir/Projects/WeatherBot/.venv/bin/python3`.

## D3 — Act (drive the CLI)
- `check-config` (offline, safe, exits immediately): `( cd $TMP && $PY -m weatherbot check-config --config <toml> )`.
- `run` (the daemon) — **only ever drive `run` on a KNOWN-BAD config**, because the fatal
  boot-validate path exits immediately (RC=1). Driving `run` on a GOOD config would block forever
  AND hit the real OpenWeather API + send a real Discord online ping — do NOT do that here; verify
  the good-config startup path by mechanism+result (tests + source) instead.
- Always wrap `run` in `timeout 20` — a non-124 exit proves it terminated rather than warn-looping.

## D4 — Observe (four layers)
- (a/b) No UI tree / screenshot layer (headless CLI) — N/A.
- (c) **Logs:** structlog writes to stderr; capture with `2> run.log`. Loud fatal lines:
  `run boot-validate failed` (error), `boot fatal: config/template invalid` (critical). A green boot
  would instead log `module provenance` + `daemon started` + `scheduled slot` — their ABSENCE proves
  the scheduler never started.
- (d) **Data / byte-level:** the durable health row —
  `$PY -c "from weatherbot.weather.store import read_health; print(read_health('$TMP/data/weatherbot.db'))"`.

## D5 — Fixture / isolation integrity (CRITICAL)
- The health DB path is `DEFAULT_DB_PATH = Path("data")/"weatherbot.db"` — **relative to cwd**
  (`weatherbot/cli.py:67`). Therefore **running from an isolated tempdir fully isolates all side
  effects**: the fatal exit writes `$TMP/data/weatherbot.db`, never the live production DB.
- Copy `templates/` into `$TMP` so cwd-relative template loading resolves.
- Set `DISCORD_WEBHOOK_URL=https://discord.invalid/webhook` so the best-effort fatal alert *attempts*
  a send (exercising the WR-01 path) but harmlessly fails — no real Discord spam.
- Restore = delete `$TMP` (nothing outside it is touched).

## D6 — Ladder commands
| Rung | Command |
|------|---------|
| 0 compile | `uv run python -c "import weatherbot.cli, ...; print('IMPORT OK')"` |
| 1 unit | `uv run pytest tests/ -q -k "<names>"` |
| 3 headless data/log | drive `run`/`check-config` in `$TMP`; capture RC + `run.log`; `read_health($TMP/data/weatherbot.db)` |
| 4/5 UI | N/A (headless CLI) |

## D7 — Gotchas
- `uv run` resolves the project by walking up from cwd; running it from an unrelated `/tmp` subdir
  won't find the project. Use the venv python **directly** (`$PY`) with cwd=`$TMP`.
- A duplicate-**name** config trips the name check before the id check (both raise `ValueError`) — to
  target the id path specifically, give unique names but a colliding id.
- `detail` in the health row is `type(exc).__name__` (outcome-only) — different bad configs yield
  different detail (`ValueError` vs `FileNotFoundError`); that variance is the proof it's real, not a
  hardcoded constant.
