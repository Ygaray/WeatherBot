---
phase: 29-startup-validation-honest-alerting
gate: 1
status: partial
result: has_partial
source: gsd-verify-work-agentic
device: CLI subprocess (isolated tempdir + isolated health DB)
apk: n/a (Python CLI) — build identity git short-sha e692a72
run: 2026-07-08
---

# Phase 29 — Startup Validation & Honest Alerting — Gate-1 Self-UAT

**Platform / driver:** CLI (`AGENT-CLI-TESTING.md`, auto-bootstrapped headlessly this run).
**Build identity:** git `e692a72`; working tree clean of production code (only `.planning/` docs modified).
**Target:** `python -m weatherbot <cmd> --config <toml>` as a subprocess.
**Isolation:** ran from a temp cwd `$TMP` (`/tmp/wb-uat-29.*`) so the cwd-relative health DB
(`DEFAULT_DB_PATH = Path("data")/"weatherbot.db"`, `cli.py:67`) landed at `$TMP/data/weatherbot.db` —
the LIVE production DB on `yahir-mint` was never touched. `DISCORD_WEBHOOK_URL=https://discord.invalid/webhook`
so the best-effort fatal alert attempted a send and harmlessly failed. `run` was driven ONLY on
KNOWN-BAD configs (they fatal-exit immediately); the GOOD-config live daemon drive was intentionally
skipped for side-effect safety (real API + real Discord ping) and covered by mechanism+result instead.

**Verdict:** SC1 PASS, SC2 PASS, SC3 PARTIAL (mechanism+result verified; live drive safely deferred).
No behavior FAIL. One deferred Gate-2 obligation (live systemd redeploy) registered.

---

### 1. SC1 (HARD-STARTUP-01) — bad config fails `run` loudly at boot; F05 parity with check-config
result: passed

**Highest ladder rung:** 3 (headless data/log — real subprocess exit codes + logs).

**What was tested:** that a permanent config fault (a) makes `weatherbot run` exit non-zero at boot,
(b) logs a loud error/CRITICAL line naming the failure (not a green "scheduler started"), (c) never
starts the scheduler, and (d) is rejected identically by `check-config` (F05 parity), while a GOOD
config passes `check-config` (accept side).

**Exact commands (from `$TMP`, `PY=/home/yahir/Projects/WeatherBot/.venv/bin/python3`):**
```
# accept side
DISCORD_WEBHOOK_URL=https://discord.invalid/webhook $PY -m weatherbot check-config --config good.toml   # -> EXIT 0
# reject side (F05 parity)
... check-config --config bad-dupid.toml            # -> EXIT 1
... check-config --config bad-missing-template.toml  # -> EXIT 1
# the daemon boot-validate gate (timeout guards against a warn-loop hang)
DISCORD_WEBHOOK_URL=https://discord.invalid/webhook timeout 20 $PY -m weatherbot run --config bad-dupid.toml           # -> EXIT 1
DISCORD_WEBHOOK_URL=https://discord.invalid/webhook timeout 20 $PY -m weatherbot run --config bad-missing-template.toml # -> EXIT 1
```

**Evidence:**
- **Accept:** `check-config passed  path=good.toml` → `EXIT=0`.
- **Reject (check-config):** `check-config failed  error="Duplicate location name 'home' ..."` → `EXIT=1`;
  and `check-config failed  error="[Errno 2] No such file or directory: .../does-not-exist.txt"` → `EXIT=1`.
- **Reject (run boot-validate):** RC **= 1** (NOT 124 = timeout → it exited, did not warn-loop/hang). Log:
  `[error] run boot-validate failed  error="Duplicate location name 'home' ..."  path=bad-dupid.toml`
  then `[critical] boot fatal: config/template invalid  detail=ValueError reason=config_invalid`.
- **Scheduler never started:** the bad-config run logs contained NO `module provenance`, `daemon started`,
  or `scheduled slot` line — the green-boot path was never reached.
- **F05 parity source:** the `run` catch tuple `cli.py:1032-1037` is byte-identical to check-config's
  `cli.py:1007-1011`, both calling the SAME `validate_config_and_templates` (`config/loader.py:99`).
- **Falsification:** two distinct fault classes (dup-name → `ValueError`; missing template → `FileNotFoundError`)
  were both rejected, and a valid config was accepted — the check is a real gate, not a blanket reject.

---

### 2. SC2 (HARD-STARTUP-02) — permanent error is FATAL (alerts + stops), not a forever warn-loop
result: passed

**Highest ladder rung:** 3 (headless data/log — durable SQLite health row + logs). Non-fatal-guard: rung 1.

**What was tested:** from the SAME bad-config `run` — (a) the durable health row is stamped
`config_invalid` (D-02, survives for a later `!status`); (b) the process EXITED (returned, did not
warn-loop); (c) the fatal Discord alert was ATTEMPTED best-effort (WR-01, `build_channel(None, settings)`).
Plus D-03 mechanism: `AUTH_FAILED` stays NON-fatal.

**Exact commands:**
```
$PY -c "from weatherbot.weather.store import read_health; print(read_health('$TMP/data/weatherbot.db'))"
uv run pytest tests/ -q -k "auth_not_fatal or auth_failed"
```

**Evidence:**
- **(a) Data-level, health row:** `{'reason': 'config_invalid', 'detail': 'ValueError', 'updated_at_utc': 1783491212}`.
  `weatherbot.ops.CONFIG_INVALID == 'config_invalid'` matches the stamped reason. `detail` is outcome-only
  (`type(exc).__name__`) — NO secret/path/`str(exc)`. Falsified as real: the missing-template run stamped
  `detail='FileNotFoundError'` (detail tracks the actual exception class, not a hardcoded string).
- **(b) Exited, no warn-loop:** RC=1 under `timeout 20` (124 would signal a hang); process returned immediately.
- **(c) Fatal alert attempted (WR-01):** log line `[warning] fatal alert send failed (best-effort)  reason=config_invalid`
  — proves `_fatal_config_exit` reached `build_channel(None, settings)` + `channel.send(...)` (`cli.py:611`) and the
  swallowed send failure did NOT crash the fatal path or block the non-zero exit.
- **(D-03) AUTH_FAILED non-fatal:** `6 passed` (`test_auth_not_fatal` + auth-failed suite). Source: the fatal
  branch `wiring.py:313` is guarded on `result.reason == daemon.CONFIG_INVALID`; `AUTH_FAILED` falls to the
  `elif` at `wiring.py:332` (log only, re-probes) — a real 401 is not safely drivable, so mechanism-verified.

---

### 3. SC3 (HARD-STARTUP-03) — startup ordering/logging corrected (forecast slot can't be silently omitted)
result: partial

**Highest ladder rung:** 1 (unit/behavioral tests) + source inspection. Live daemon drive intentionally SKIPPED (unsafe).

**What was tested (mechanism + result, per two-gate policy):** driving the GOOD-config daemon live is
unsafe (real API + real Discord ping), so F90/F07/F89 were verified by named behavioral tests + source paths.

**Exact commands:**
```
uv run pytest tests/ -q -k "announce_forecast or ping_after_ready or streak_prune"   # -> 3 passed
uv run pytest tests/ --collect-only -q -k "..."   # confirmed exact test ids
```

**Evidence:**
- `tests/test_scheduler.py::test_announce_forecast`, `::test_ping_after_ready`, `tests/test_reload.py::test_streak_prune`
  all **PASS** (3 passed, 803 deselected).
- **F90 (`daemon.py:1100-1110`):** the forecast-slot loop announces EVERY slot incl. disabled (job miss →
  `next_run_time=None`) — no continue-skip; a paused forecast slot is logged, never silently omitted.
- **F07 (`daemon.py:1496-1507`):** the online ping fires STRICTLY after `ready_gate.run(stop)` returns True
  (`daemon.py:1478`), and the fatal exit-code gate (`daemon.py:1486`) precedes it — moved OUT of `_on_online`
  (`wiring.py:352-356`). `test_ping_after_ready` asserts ping index > ready index.
- **F89 (`daemon.py:447-461`):** `_prune_forecast_streaks` pops dead job-ids, retains live ones; wired
  best-effort from `wiring.py:243`.
- **Why PARTIAL (not FAIL):** mechanism (source paths) + result (green behavioral tests) are both verified;
  ONLY the physical "watch it on the live daemon" step is deferred for side-effect safety. Per project two-gate
  policy this is a `partial`, not skipped, not a phase blocker.

---

## Deferred to Gate-2 (milestone close)
- **Live `deploy/weatherbot.service` restart-policy effect (D-05/D-06):** a fatal config-exit trips the
  systemd start-limit → unit parks `failed`. Requires a redeploy + `systemctl daemon-reload` on `yahir-mint`.
  In-repo unit edit is verified by static tests (`test_service_unit.py`, 3 passed); the LIVE effect is a
  deferred milestone-close obligation. Registered in `.planning/HUMAN-UAT-PENDING.md`. PARTIAL, not a blocker.

## Outcome
Gate-1 SATISFIED (no behavior FAIL). SC1 PASS, SC2 PASS on the real running CLI at rung 3 (exit codes +
durable health row + logs); SC3 PARTIAL (mechanism+result). The one deferred item is a Gate-2 obligation.
Phase 29 proceeds.
