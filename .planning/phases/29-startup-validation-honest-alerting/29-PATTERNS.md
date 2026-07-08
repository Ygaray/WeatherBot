# Phase 29: Startup Validation & Honest Alerting - Pattern Map

**Mapped:** 2026-07-07
**Files analyzed:** 6 source edits + 4 test files (extend/add)
**Analogs found:** 10 / 10 (this is an EDIT-in-place phase — every file's analog is itself or an adjacent sibling in the same module)

> Note to planner: This is a backend/daemon phase. There are almost **no new files** — the
> surface is EDITS to existing Python modules + one systemd unit, plus NEW test cases inside
> EXISTING test files. So the "closest analog" for each edited file is usually the *sibling
> function in the same file* (e.g. the existing `AUTH_FAILED` handling next to the new
> `CONFIG_INVALID`). Copy the established local idiom, do not invent a new shape. RESEARCH.md
> already carries verified line-cited edit shapes (Patterns 1–6); this file names the exact
> reusable scaffolding to copy from.

## File Classification

| File (edit/new) | Role | Data Flow | Closest Analog | Match Quality |
|-----------------|------|-----------|----------------|---------------|
| `weatherbot/cli.py` (`run` cmd, add `_fatal_config_exit`) | route/controller | request-response (CLI dispatch) | `check-config` branch same file `cli.py:949-977` | exact (sibling branch) |
| `weatherbot/config/loader.py` `validate_config_and_templates` | utility/validator | transform (offline validate) | REUSED read-only — no edit | n/a (consumed) |
| `weatherbot/ops/selfcheck.py` (add `CONFIG_INVALID`) | service (classifier) | transform (classify outcome) | existing `AUTH_FAILED`/`NETWORK_NOT_READY` + `to_health_result` same file | exact (sibling constants) |
| `weatherbot/scheduler/daemon.py` (F90 announce, F89 prune, exit-code branch, remove dead gate) | service (daemon lifecycle) | event-driven / batch | `_desired_job_ids`:695, `_forecast_job_id`:556, `_announce_schedule`:1030, `ready_gate.run` branch:1465 | exact (same file) |
| `weatherbot/scheduler/wiring.py` (`_on_fail` fatal marker, F07 ping move, `_on_applied` prune call) | provider (composition wiring) | event-driven (hooks) | existing `_on_fail`:280, `_on_online`:300, `_on_applied`:209 same file | exact (same file) |
| `deploy/weatherbot.service` (`Restart=on-failure` + StartLimit) | config (systemd unit) | n/a | itself `[Unit]`:13 / `[Service]`:20 sections | exact (in-file) |
| `tests/test_cli.py` (boot-validate + parity + subprocess) | test | request-response | `test_check_config_offline_pass/fail`:804-828, `main([...])` idiom | exact (sibling tests) |
| `tests/test_ops_selfcheck.py` (CONFIG_INVALID + severity) | test | transform | `_RaisingClient`:52, `test_auth_401_is_auth_failed`:98 | exact (extend file) |
| `tests/test_scheduler.py` (fatal exit, clean-SIGTERM, auth-not-fatal, announce, ping-order) | test | event-driven | `test_run_daemon_stamps_tick_at_startup`:631, `test_bot_thread_starts_strictly_after_online_signal`:1013 | exact (sibling tests) |
| `tests/test_reload.py` (streak-prune) | test | event-driven | `_cfg`:89, `_slot`:93, `holder_scheduler` fixture, `_do_reload` idiom | exact (extend file) |

## Pattern Assignments

### `weatherbot/cli.py` — `run` boot-validate + `_fatal_config_exit` (controller, request-response)

**Analog:** the `check-config` branch in the SAME file (`cli.py:949-977`) — it already calls the
shared validator and catches the exact 4-exception set. `run` (`cli.py:985-1006`) currently uses
the THIN `_load_config_reporting`→`load_config` path (schema-only). The fix makes `run` match
`check-config`'s validation depth.

**Canonical catch set to copy** (`cli.py:966-975`, the `check-config` path):
```python
try:
    _check_engine.check(args.config)
except (
    FileNotFoundError,
    tomllib.TOMLDecodeError,
    ValidationError,
    ValueError,
) as exc:
    _log.error("check-config failed", path=str(args.config), error=str(exc))
    return 1
```
For `run`, wrap `validate_config_and_templates(args.config)` in the SAME 4-tuple and route the
`except` into `_fatal_config_exit(...)` instead of a bare `return 1` (D-08 single fatal path).

**Clean-failure idiom to copy** (`_load_config_reporting`, `cli.py:569-587`): outcome-only
`_log.error(..., path=str(path))`, no traceback. NOTE the divergence the planner must respect:
`_load_config_reporting` logs `error=str(exc)`; the FATAL alert `detail` must use
`type(exc).__name__` NOT `str(exc)` (T-04-01 — config errors can carry a filesystem path). The
log line may keep `str(exc)`; the Discord alert `detail` must not.

**Current `run` dispatch to modify** (`cli.py:985-1006`):
```python
if args.command == "run":
    config = _load_config_reporting(args.config)   # ← REPLACE with full-validator gate
    if config is None:
        return 1
    settings = load_settings()
    ...
    return daemon.run_daemon(config=config, settings=settings, db_path=db_path, config_path=args.config)
```

**`_fatal_config_exit` shape (NEW helper, Open Question 1 resolution):** best-effort build channel
from `settings` → send ONE alert → stamp health → `return 1`. The channel builder is
`build_channel(config, settings)` (`weatherbot/channels`, used in `wiring.py:143-145`). The
best-effort `channel.send(...)` try/except idiom is copied from `_on_applied` (`wiring.py:213-217`).

---

### `weatherbot/ops/selfcheck.py` — `CONFIG_INVALID` reason + CRITICAL map (service, transform)

**Analog:** the existing reason trio + `to_health_result` in the SAME file.

**Reason constant block to extend** (`selfcheck.py:44-46`):
```python
PASS = "online"
NETWORK_NOT_READY = "network_not_ready"
AUTH_FAILED = "auth_failed"
# ADD: CONFIG_INVALID = "config_invalid"   (lowercase-string convention)
```

**Classification split** — today the pre-probe config checks (`selfcheck.py:80-91`:
`config.locations` guard, `validate_template`, `assert_unique_names`, `resolve_location`) share the
single broad `except Exception` at `:116` that returns `NETWORK_NOT_READY`. Wrap those pre-probe
checks in their own `except (ValueError, FileNotFoundError)` → `CONFIG_INVALID` BEFORE the network
probe (Pattern 2). Keep the `httpx.HTTPStatusError` branch (`:104-115`) and the trailing
`except Exception` (`:116-122`) exactly as-is for AUTH/NETWORK.

**Severity map to extend** (`to_health_result`, `selfcheck.py:139`):
```python
severity = Severity.CRITICAL if result.reason == AUTH_FAILED else Severity.WARNING
# CHANGE to: CRITICAL if result.reason in (AUTH_FAILED, CONFIG_INVALID) else WARNING
```

**Export:** re-export `CONFIG_INVALID` from `weatherbot.ops.__init__` (it already re-exports
`AUTH_FAILED`/`NETWORK_NOT_READY`/`PASS`, per `test_ops_selfcheck.py:16-22`) AND alias it onto the
`daemon` namespace like `AUTH_FAILED` is, so `wiring.py:_on_fail` can compare
`result.reason == daemon.CONFIG_INVALID`.

**`detail` contract** (`selfcheck.py:16-17, 55-56`): `detail=type(exc).__name__`, never `str(exc)`.

---

### `weatherbot/scheduler/wiring.py` — fatal marker + F07 ping move (provider, event-driven)

**Analog:** the three existing injected hooks in the SAME file — `_on_fail`:280, `_on_online`:300,
`_on_applied`:209. Copy each hook's local structure.

**`_on_fail` extension** (`wiring.py:280-293`): today it stamps health then branches
CRITICAL(auth)/WARNING(other). ADD a fatal branch BEFORE the auth branch:
```python
def _on_fail(result) -> None:
    daemon.stamp_health(db_path, reason=result.reason, detail=result.detail)
    if result.severity >= Severity.CRITICAL and result.reason == daemon.CONFIG_INVALID:
        fatal.set()                       # ★ dedicated Event, threaded from build_runtime
        _fatal_config_exit_alert(...)     # ★ best-effort once (D-04)
        stop.set()                        # ★ break the hub re-probe loop
    elif result.reason == daemon.AUTH_FAILED:
        daemon._log.critical("startup self-check auth failure", ...)   # existing
    else:
        daemon._log.warning("startup self-check not ready", ...)        # existing
```

**F07 ping move** (`wiring.py:300-313`): the online Discord ping currently lives INSIDE `_on_online`
(`channel.send("WeatherBot online...")` at `:305-313`), which the hub fires BEFORE
`notifier.ready()`. REMOVE the ping from `_on_online` (KEEP `scheduler.start()`, `stamp_health`,
`stamp_tick`, the online log — the golden-sensitive `scheduler.start()`-before-READY invariant).
RE-ADD the ping in `run_daemon` AFTER `ready_gate.run(stop)` returns True (Pattern 5).

**`RuntimeParts` threading** (`wiring.py:84-105`): add `fatal: threading.Event` field next to the
existing `stop: threading.Event` (`:94`). Construct it in `build_runtime` next to
`stop = daemon.threading.Event()` (`wiring.py:155`) and include it in the returned `RuntimeParts`
(`:323-337`). Keep it SEPARATE from `stop` (anti-pattern: reusing `stop` collapses the
fatal-vs-clean-SIGTERM distinction).

**`_on_applied` prune call** (`wiring.py:209-228`): add a best-effort `_prune_forecast_streaks(holder)`
call in the same committed-success try/except style as its siblings (`channel.send`,
`cache.invalidate` at `:213-224`) — each wrapped `except Exception: ... _log.warning(...)`.

---

### `weatherbot/scheduler/daemon.py` — F90 / F89 / exit-code / dead-gate removal (service)

**F90 announce** — `_announce_schedule` (`daemon.py:1030-1063`): today iterates only
`location.schedule` (briefing) and `continue`s past disabled slots (`:1047-1048`). ADD a parallel
loop over `location.forecast` keyed by the SHARED `_forecast_job_id(location, fc)` (`daemon.py:556-571`)
and STOP skipping disabled slots — log them with `enabled=False`/`next_run_time=None` so a disabled
forecast slot is visible (Pattern 4). Copy the existing `_log.info("scheduled slot", ...)` call
shape; add `kind=` to distinguish briefing vs forecast.

**F89 prune** — `_forecast_failure_streaks` dict (`daemon.py:392`), keyed by `_forecast_job_id`
(written in `_note_forecast_failure`:412-414, popped only in `_note_forecast_success`:440). The
authoritative live-id set is `_desired_job_ids(holder)` (`daemon.py:695-713`, returns
`briefing_ids | forecast_ids`). Prune = `set(_forecast_failure_streaks) - live_ids` (Pattern 6).
Set-difference is safe because the streak dict only ever holds forecast ids.

**Exit-code branch** — the gate-stop return (`daemon.py:1465-1466`):
```python
if not ready_gate.run(stop):
    return 0                    # ← today: always 0
```
Change to read the fatal marker:
```python
if not ready_gate.run(stop):
    return 1 if parts.fatal.is_set() else 0
```
`fatal` arrives via `parts` (unpacked like `stop = parts.stop` at `daemon.py:1397-1407`).

**Dead-code removal** — `gate_until_healthy` (`daemon.py:1108-1156`) is the DEAD hand-rolled twin of
the hub `ReadyGate.run` this phase reasons about (F16/State-of-the-Art). Remove it. NOTE (Pitfall 5):
`emit_online` (`daemon.py:1159`) + `_do_reload` are ALSO dead but are formally F16→Phase 35 — do NOT
remove them here unless consciously widening scope and noting it. `wait_ready_gate` does not exist
(the CONTEXT name is an alias for `gate_until_healthy`).

**Online ping re-add site** (F07 second half) — after `daemon.py:1468` (`_log.info("daemon started"...)`),
add the best-effort online ping guarded on `channel is not None` (Pattern 5).

---

### `deploy/weatherbot.service` — restart policy (config)

**Analog:** the file's own `[Unit]` (`:13`) and `[Service]` (`:20`) sections.

**`[Unit]` section** — ADD (Pitfall 3: MUST be in `[Unit]`, not `[Service]`):
```ini
StartLimitIntervalSec=300
StartLimitBurst=5
```
**`[Service]` section** — CHANGE `Restart=always` (`:45`) → `Restart=on-failure`; KEEP
`RestartSec=5` (`:46`) and KEEP `TimeoutStartSec=infinity` (`:27` — governs the never-exiting
transient path, orthogonal to restart policy, Pitfall 2).

> Gate-2 (D-06): the live effect needs redeploy + `systemctl daemon-reload` on `yahir-mint` —
> deferred to milestone-close human UAT, NOT shipped autonomously.

---

## Test Pattern Assignments

### `tests/test_cli.py` — boot-validate, parity, subprocess (test)

**Analogs:** `test_check_config_offline_pass`/`_fail` (`:804-828`) and the `main([...])` boundary
tests (`:305-332`). All CLI tests drive `main([...])` and assert the returned int exit code —
copy that idiom (NOT `subprocess`, except the ONE end-to-end exit-code test).

**Config-file fixture to copy:** `_good_config_file(tmp_path)` (`:786-801`) writes a minimal valid
`config.toml` and returns the path; the bad-template variant in `test_check_config_offline_fail`
(`:817-826`) shows the `template = "__does_not_exist__.txt"` typo. Build the duplicate-id/name and
missing-template fixtures the same way.

**Parity test** (HARD-STARTUP-01 strongest guard): parametrize over the SAME configs and assert
`main(["check-config", "--config", str(c)])` and the `run` boot-validate return identical
accept/reject. Reuse `_good_config_file` + the bad variants.

**Subprocess exit-code test** (the ONE true end-to-end proof): launch
`weatherbot run --config <bad.toml>` via `subprocess` and assert non-zero PROCESS exit code — no
existing analog, this is genuinely new (call out in plan). All OTHER exit-code logic uses
in-process `main([...])`/`run_daemon` stubs.

---

### `tests/test_ops_selfcheck.py` — CONFIG_INVALID classification + severity (test)

**Analogs (extend this file):** `_config()` (`:25-37`), `_OkClient` (`:40`), `_RaisingClient`
(`:52-61`), `_http_status_error` (`:64-67`), and the per-reason test shape
`test_auth_401_is_auth_failed` (`:98-103`) / `test_transient_connect_error...` (`:81-86`).

**New cases (Pattern 2, parametrized matrix is the natural shape):**
- bad-template config (`_config(template="__does_not_exist__.txt")`) → `CONFIG_INVALID`
- empty-locations config → `CONFIG_INVALID`
- `_RaisingClient(httpx.ConnectError)` → still `NETWORK_NOT_READY` (D-03 guard)
- `_RaisingClient(_http_status_error(401))` → still `AUTH_FAILED` (D-03 guard)
- `to_health_result` severity map: `CONFIG_INVALID`→CRITICAL, `AUTH_FAILED`→CRITICAL,
  `NETWORK_NOT_READY`→WARNING

Import `CONFIG_INVALID` from `weatherbot.ops` alongside the existing `AUTH_FAILED`/... imports (`:16-22`).

---

### `tests/test_scheduler.py` — fatal-exit, clean-SIGTERM, auth-not-fatal, announce, ping-order (test)

**Clean-SIGTERM / gate-stop analog:** `test_run_daemon_stamps_tick_at_startup` (`:631-`) — shows
the full stub kit: `monkeypatch.setattr(daemon_mod, "run_self_check", lambda *, config, settings:
CheckResult(ok=True, reason=PASS))`, a `_FakeScheduler` (`:664`), and a config with no enabled
slots. For the fatal branch, return a fatal `CheckResult(ok=False, reason=CONFIG_INVALID)` health
result and assert `run_daemon` returns non-zero + `scheduler.start` never called. For clean-SIGTERM
assert return 0 with the marker unset.

**Ordering-recording analog (F07 `ping_after_ready`):**
`test_bot_thread_starts_strictly_after_online_signal` (`:1013-1045`) is the exact template — it
builds an `order: list[str]`, monkeypatches `SystemdNotifier.ready` to
`lambda self: order.append("ready")` (`:1037-1039`), stubs `build_channel`
(`:1042-1045`), and asserts recorded order. Copy this to record `channel.send` vs `ready()` and
assert the ping appears AFTER `"ready"`. Reuse `_StartObservableScheduler` and
`_NeverSetImmediateWait` (the `threading.Event` stub that lets the gate probe once).

**`auth_not_fatal` (D-03 regression):** drive the gate with a `CheckResult(ok=False,
reason=AUTH_FAILED)` health result, assert the fatal marker is NOT set (re-probes, does not exit
non-zero). Same stub kit as above.

**`announce_forecast` (F90):** capture structlog (the suite already captures daemon logs — grep the
file for the existing structlog-capture fixture) and assert a `kind="forecast:*"` line per forecast
slot, including a disabled one with `next_run_time=None`.

---

### `tests/test_reload.py` — streak-prune-on-reload (test)

**Analogs (extend this file):** `_cfg(*locations)` (`:89`), `_slot(...)` (`:93`), the
`holder_scheduler` fixture (`:143` etc. — returns `(holder, scheduler, db_path)`), and the
`_do_reload(new, holder=holder, scheduler=scheduler, db_path=db_path)` / `service_pending` idiom
(`test_reconcile_diff`:328, `test_send_time_change...`:212). `_RecordingChannel` (`:97-112`) is
available if the prune path needs a channel.

**New case:** seed `daemon._forecast_failure_streaks` with a live key + a dead (removed/renamed
forecast-slot) key, apply a reload whose new config drops that slot, assert the dead key is popped
and the live key retained. Key both entries via `daemon._forecast_job_id(location, fc)` so they
match the prune set-difference byte-for-byte.

---

## Shared Patterns

### Best-effort channel send (fire-and-forget, never re-raise)
**Source:** `wiring.py:_on_applied` (`:213-217`), `daemon._note_forecast_failure` (`:427-435`).
**Apply to:** the fatal alert (`_fatal_config_exit`), the F07 relocated online ping, the F89 prune call.
```python
try:
    channel.send(msg)
except Exception:  # noqa: BLE001 — best-effort; never re-raise
    daemon._log.warning("<action> failed; <invariant> unaffected")
```

### Outcome-only logging / `detail` hygiene (T-04-01, ASVS V7)
**Source:** `selfcheck.py:16-17, 55-56` + `_load_config_reporting` (`cli.py:569-587`).
**Apply to:** every new log line + the fatal alert `detail`. Use `type(exc).__name__`, never
`str(exc)` in the alert `detail`; never echo a secret or path.

### Interruptible wait (never `time.sleep`, Pitfall 2)
**Source:** `gate_until_healthy` (`:1152-1154`, being removed) + the main poll loop
(`daemon.py:1535` `while not stop.wait(timeout=1.0)`) + hub `ReadyGate.run`.
**Apply to:** any new wait/exit path — stay `stop.wait(...)` so `systemctl stop` breaks promptly.

### Daemon-namespace resolution for monkeypatch (test-bite invariant)
**Source:** `build_runtime` comment (`wiring.py:131-136`) + every scheduler test's
`monkeypatch.setattr(daemon_mod, "run_self_check", ...)`.
**Apply to:** reference `daemon.CONFIG_INVALID` / `daemon.stamp_health` / `daemon.threading.Event`
through the daemon module object so the daemon-suite monkeypatches bite the new fatal path too.

### Single-source forecast job-id (no drift)
**Source:** `_forecast_job_id` (`daemon.py:556-571`) — used by BOTH `_register_jobs` and
`_desired_job_ids`.
**Apply to:** F90 announce AND F89 prune must call `_forecast_job_id`, never recompute the id string.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| the ONE subprocess integration test in `tests/test_cli.py` | test | request-response | No existing `subprocess`-launched CLI test — all current CLI tests use in-process `main([...])`. This is genuinely new scaffolding (though small: `subprocess.run([sys.executable, "-m", "weatherbot", "run", "--config", bad], ...)` asserting non-zero returncode). |

Everything else has an exact in-file or sibling-module analog — this phase is overwhelmingly
"call/copy the existing thing," per RESEARCH.md's key insight (the defects are *omissions of reuse*).

## Metadata

**Analog search scope:** `weatherbot/cli.py`, `weatherbot/ops/selfcheck.py`,
`weatherbot/scheduler/{daemon,wiring}.py`, `deploy/weatherbot.service`,
`tests/test_{cli,ops_selfcheck,scheduler,reload}.py`.
**Files scanned:** 9 source/test files (targeted reads on cited ranges) + RESEARCH.md's verified
line-cites cross-checked against source.
**Pattern extraction date:** 2026-07-07
