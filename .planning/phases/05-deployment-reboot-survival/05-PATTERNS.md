# Phase 5: Deployment & Reboot Survival - Pattern Map

**Mapped:** 2026-06-11
**Files analyzed:** 9 (4 new code/config, 2 modified code, 3 new/extended tests)
**Analogs found:** 8 / 9 (only the systemd unit has no in-repo analog — synthesized from RESEARCH.md)

> **Correction to RESEARCH.md:** the research repeatedly cites `tests/test_daemon.py`. **No such file exists.** All `run_daemon` / daemon-spine tests live in **`tests/test_scheduler.py`** (see its section `# --- SCHD-05/D-07: daemon spine ---`, lines 303+, and `# --- SCHD-05/D-09: --run CLI flag ---`, lines 581+). The planner MUST extend `tests/test_scheduler.py`, NOT create `tests/test_daemon.py`. The new `tests/test_ops_selfcheck.py` and `tests/test_sdnotify.py` are genuinely new files.

> **Correction to RESEARCH.md line numbers:** `do_check` is at `weatherbot/cli.py:314–394` (verified). `run_daemon` is at `weatherbot/scheduler/daemon.py:439–511` (verified). `is_transient`/`is_auth_failure` are at `weatherbot/reliability/retry.py:80–99` (verified). The `heartbeat` single-row table is `store.py:129–135`; `stamp_tick`/`stamp_success` are `store.py:383–412` (verified). `Channel.send` is `discord.py:50–52` (verified, returns a `DeliveryResult`, does NOT raise).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `deploy/weatherbot.service` | config (systemd unit) | event-driven (process lifecycle) | *(none in repo)* | no-analog — use RESEARCH.md `## Code Examples` |
| `weatherbot/ops/__init__.py` | package init (re-export) | n/a | `weatherbot/reliability/__init__.py` | exact (package-structure) |
| `weatherbot/ops/sdnotify.py` | utility (OS IPC) | event-driven (single AF_UNIX datagram) | `weatherbot/channels/discord.py` (best-effort, never-raise side-effect) | role+flow partial; RESEARCH.md has the literal code |
| `weatherbot/ops/selfcheck.py` *(optional, planner's call)* | service (validate + classify) | request-response (one probe) | `weatherbot/cli.py::do_check` (314–394) + `reliability/retry.py` classifiers | exact (extracted from do_check) |
| `weatherbot/weather/store.py` (MODIFY: `health` table + `stamp_health`) | model / persistence | CRUD (single-row upsert) | `store.py` `heartbeat` table (129–135) + `stamp_tick`/`stamp_success` (383–412); `alerts`/`record_alert` (117–127, 324–355) | exact |
| `weatherbot/cli.py` (MODIFY: `do_check` → reusable engine) | controller / CLI | request-response | `do_check` itself (314–394) — refactor in place | exact (self) |
| `weatherbot/scheduler/daemon.py` (MODIFY: gate + re-probe loop + online signal in `run_daemon`) | service / daemon spine | event-driven (interruptible loop) | `run_daemon` (439–511) + `build_retrying`'s `sleep=stop_event.wait` (retry.py:231) | exact (self) |
| `tests/test_ops_selfcheck.py` (NEW) | test | request-response | `tests/test_store.py` alert/heartbeat tests (157–252); `tests/test_scheduler.py` fire_slot tests (369+) | role-match |
| `tests/test_sdnotify.py` (NEW) | test | event-driven | `tests/test_scheduler.py` daemon tests (584+, monkeypatch + stub pattern) | role-match |
| `tests/test_scheduler.py` (EXTEND: gate-stop, online-once) | test | event-driven | existing `test_run_daemon_stamps_tick_at_startup` (624–674) | exact |
| `tests/test_store.py` (EXTEND: `stamp_health`) | test | CRUD | existing heartbeat tests (217–252) | exact |

## Pattern Assignments

### `weatherbot/weather/store.py` — add `health` table + `stamp_health` (model, CRUD single-row)

**Analog:** the `heartbeat` single-row table + `stamp_tick`/`stamp_success`, AND the `alerts` table + `record_alert`/`resolve_alert` (for the secret-hygiene + `INSERT OR IGNORE` seed idiom). All in this same file.

**Single-row table pattern to copy** (`store.py:129–135`, append to `_SCHEMA`):
```python
CREATE TABLE IF NOT EXISTS heartbeat (
    id               INTEGER PRIMARY KEY CHECK (id = 1),  -- single liveness row (D-05)
    last_tick_utc    INTEGER,
    last_success_utc INTEGER
);
INSERT OR IGNORE INTO heartbeat (id, last_tick_utc, last_success_utc)
    VALUES (1, NULL, NULL);
```
The new `health` table is the structural twin: `id INTEGER PRIMARY KEY CHECK (id = 1)`, `reason TEXT`, `detail TEXT`, `updated_at_utc INTEGER`, seeded with `INSERT OR IGNORE ... VALUES (1, NULL, NULL, NULL)`. Append it to the `_SCHEMA` string (additive, idempotent — D-08 / "Additive SQLite schema"). RESEARCH.md `## Code Examples → The D-08 health row` has the exact DDL.

**Upsert helper pattern to copy** (`store.py:383–398`, the `stamp_tick` body — copy verbatim, swap table/columns):
```python
def stamp_tick(db_path: str | Path) -> None:
    last_tick_utc = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)                 # idempotent schema-on-connect (load-bearing)
        conn.execute(
            "UPDATE heartbeat SET last_tick_utc=? WHERE id=1",
            (last_tick_utc,),
        )
        conn.commit()
```
`stamp_health(db_path, reason, detail="")` is the same shape: compute `now = int(datetime.now(timezone.utc).timestamp())`, `conn.executescript(_SCHEMA)`, `conn.execute("UPDATE health SET reason=?, detail=?, updated_at_utc=? WHERE id=1", (reason, detail, now))`, `conn.commit()`.

**Hard constraints carried from the analogs (all already enforced in this file):**
- **Parameterized `?` only**, never f-string into SQL (T-03-01 SQLi) — every helper in this file does this; `stamp_health` must too.
- **`conn.executescript(_SCHEMA)` on connect** so the helper works against a never-initialized `db_path` (every helper does this — see `was_sent:224`, `record_alert:347`).
- **Secret hygiene (T-04-01):** the row carries reason/detail/timestamp ONLY — `detail` is outcome-only (a status code or exception class name), NEVER the key or webhook URL. See the `record_alert` docstring (324–344) and the `test_no_secret_in_alert_or_heartbeat_rows` test (`tests/test_store.py:241–252`) — the planner should add the analogous `health`-row no-secret assertion.

**`read_health` is NOT required this phase** (the inbound `status` reader is deferred, D-08). A trivial `SELECT reason, detail, updated_at_utc FROM health WHERE id=1` is the future seam if the planner wants the symmetric helper now.

---

### `weatherbot/ops/selfcheck.py` (optional) — classified self-check engine (service, request-response)

**Analog:** `weatherbot/cli.py::do_check` (314–394) for the validate+probe steps; `weatherbot/reliability/retry.py::is_transient`/`is_auth_failure` (80–99) for the classification.

**Validate+probe steps to reuse** (`cli.py:333–366`):
```python
# (1) config already validated at load; (2) template; (4) unique names + resolve
validate_template(load_template(config.template))
assert_unique_names(config)
for loc in config.locations:
    resolve_location(config, loc.name)
# (3) ONE live reachability probe — never retried here
if client is None:
    client = build_client(settings)
try:
    client.fetch_onecall(config.locations[0], "imperial")
except httpx.HTTPStatusError as exc:
    status = exc.response.status_code
    if status in (401, 403):
        raise ValueError("... may not be active or not yet propagated — wait a few hours and retry.") from exc
    raise
```
Reuse this EXACT 401/403 wording (it is the OPS-02 "distinguish key-not-yet-active from genuine auth error" deliverable).

**Classifier reuse** (`reliability/retry.py:80–99`) — import from the package, do NOT re-derive:
```python
from weatherbot.reliability import is_auth_failure, is_transient
# is_auth_failure(exc): True only for HTTPStatusError 401/403
# is_transient(exc):    True for TimeoutException/ConnectError/ReadError + HTTP 429/5xx
```

**Result-object pattern (NEW shape, no exact analog — closest is a `dataclass` + module-level reason constants, mirroring `retry.py`'s `REASON_*` constants at retry.py:75–77):**
```python
PASS = "online"; NETWORK_NOT_READY = "network_not_ready"; AUTH_FAILED = "auth_failed"
@dataclass
class CheckResult:
    ok: bool
    reason: str
    detail: str = ""    # outcome-only, NEVER a secret (T-04-01)
```
Map: 401/403 → `AUTH_FAILED` (per D-06, treat ambiguous propagating-vs-bad key as `auth_failed` and keep re-probing); transient/connection/timeout → `NETWORK_NOT_READY`; clean probe → `ok=True, reason=PASS`. RESEARCH.md `## Architecture Patterns → Pattern 1` has the full function body.

**Refactor `do_check` (cli.py) to call this engine** so `--check` and the daemon share one implementation, while `do_check` keeps its print-budget + exit-code surface (376–394). **Import-cycle caution:** `run_daemon` is imported lazily inside `cli.main`'s `--run` branch (`cli.py:494`) precisely to avoid a cli↔daemon cycle. If the engine lives in `weatherbot/ops/`, `cli.py` and `daemon.py` both import it cleanly (ops depends on neither). Prefer `weatherbot/ops/selfcheck.py` over putting it in `scheduler/` for this reason.

---

### `weatherbot/scheduler/daemon.py` — wire gate + re-probe loop + online signal into `run_daemon` (service, event-driven)

**Analog:** `run_daemon` itself (439–511) and the interruptible-sleep idiom from `build_retrying` (`retry.py:231`, `sleep=stop_event.wait`).

**Interruptible-wait primitive to reuse** — the existing `stop` Event (`daemon.py:459`) and the project's established interruptible-sleep idiom:
```python
# daemon.py:459
stop = threading.Event()
# retry.py:231 — the idiom: stop.wait(timeout) returns True if set during the wait
sleep=stop_event.wait,  # interruptible pause (D-07) — NOT a blocking stdlib sleep
# daemon.py:505 — the daemon's own blocking wait
stop.wait()
```
The re-probe loop blocks on `stop.wait(RE_PROBE_INTERVAL_S)`; a `True` return means SIGTERM/stop fired → break cleanly. NEVER `time.sleep()` (Anti-Pattern: laggy SIGTERM).

**SIGTERM handler to reuse + the load-bearing ORDERING CHANGE** (`daemon.py:500–505`):
```python
def _handle(signum, frame):  # noqa: ANN001 — signal handler signature
    stop.set()
signal.signal(signal.SIGTERM, _handle)   # CURRENTLY registered AFTER scheduler.start()
```
**The handler is currently registered at line 503, AFTER `scheduler.start()` (492).** The new re-probe loop must run BEFORE `scheduler.start()` (the online signal must precede job firing). Therefore the planner MUST move `signal.signal(signal.SIGTERM, _handle)` registration EARLIER — before entering the gate loop — so a `systemctl stop` during the re-probe loop is honored (Pitfall 2). This is a load-bearing ordering change in `run_daemon`.

**Wiring point** (`daemon.py:483 → 492`): insert the gate AFTER `_announce_schedule`/`_run_catchup`, BEFORE `scheduler.start()`. If the gate returns `True` (healthy), fire the once-only online signal then `scheduler.start()`. If it returns `False` (stop set during the loop), fall straight through to the existing `finally: scheduler.shutdown(wait=False)` (509) — do NOT start the scheduler, do NOT emit online.

**Online signal — reuse existing primitives** (`store.stamp_tick`:383, `Channel.send`:discord.py:50):
```python
stamp_health(db_path, reason="online")    # 1a. NEW durable row (D-08/D-05)
stamp_tick(db_path)                        # 1b. EXISTING — already called at daemon.py:497
_log.info("weatherbot online", jobs=jobs)  # 1c. structured log (existing _log = structlog.get_logger)
notifier.ready()                           # 2.  sd_notify READY=1 (no-op if NOTIFY_SOCKET unset)
if channel is not None:
    channel.send("WeatherBot online — startup self-check passed.")  # 3. one-time (D-07)
```
The existing `stamp_tick(db_path)` + `_log.info("daemon started", ...)` at `daemon.py:497–498` is the seam this formalizes into the online signal. `Channel.send` returns a `DeliveryResult` (never raises) — log a non-ok result but do NOT block startup or re-fire (D-07). The `channel is None` guard mirrors the existing optional-channel pattern throughout `run_daemon` (`channel: Channel | None = None`, line 445).

---

### `weatherbot/ops/sdnotify.py` — pure-stdlib READY=1 (utility, event-driven AF_UNIX datagram)

**Analog:** no exact in-repo IPC analog. Closest *behavioral* analog is `discord.py::_post` (72–117): a best-effort side-effecting call that **catches its own errors and never lets a delivery/signal failure crash the caller** (`except RequestException: ... return DeliveryResult(ok=False)`, lines 92–98). Apply the same "never raise on a transport error" posture: `except OSError: pass`.

**Code:** RESEARCH.md `## Code Examples → The pure-stdlib sd_notify helper` has the literal ~25-line `SystemdNotifier` class (verbatim-usable). Key facts: read `NOTIFY_SOCKET`, apply the abstract-socket `@`→`\0` fixup, send a `socket.AF_UNIX`/`socket.SOCK_DGRAM` datagram; **no-op when `NOTIFY_SOCKET` is unset** (so it runs identically interactively and in tests). `stdlib socket`/`os` only — zero new dependencies (confirmed against `pyproject.toml`; the `sdnotify`/`systemd-python` PyPI packages are explicitly REJECTED, RESEARCH.md `## Standard Stack → Supporting`).

---

### `weatherbot/ops/__init__.py` — package re-export (package init)

**Analog:** `weatherbot/reliability/__init__.py` (EXACT — the most recently-added focused package, Phase 4). Copy its shape: a module docstring + a flat `from .module import (...)` re-export of the public surface + an `__all__` list.
```python
"""Reliability package: ... Re-exports the public retry surface ..."""
from .retry import (REASON_AUTH_FAILED, ..., is_transient, parse_retry_after)
__all__ = ["REASON_AUTH_FAILED", ..., "parse_retry_after"]
```
For `ops`: re-export `SystemdNotifier` (and, if `selfcheck.py` lives here, `run_self_check`, `CheckResult`, and the reason constants).

---

### `deploy/weatherbot.service` — systemd unit (config, no in-repo analog)

**No analog exists in the repo** (no `deploy/` dir, no existing unit). Use RESEARCH.md `## Code Examples → The systemd unit` verbatim as the template. Load-bearing directives (all verified against host systemd 255): `Type=notify`, `NotifyAccess=main`, `TimeoutStartSec=infinity` (Pitfall 1 — the deferred-online gate can take minutes-to-hours), `Restart=always`, `RestartSec=5`, `EnvironmentFile=<REPO>/.env`, `User=<non-root>`, `WorkingDirectory=<REPO>`, `Wants=`+`After=network-online.target`, `WantedBy=multi-user.target`. **No `WatchdogSec`** (Pitfall 6 — deferred). `ExecStart` MUST be absolute (Pitfall 5: `/usr/bin/uv run weatherbot --run` OR `<REPO>/.venv/bin/python -m weatherbot --run`) — planner confirms the actual invocation first. `--run` dispatches to `run_daemon` (`cli.py:483–496`, verified).

---

### Tests

**`tests/test_store.py` (EXTEND) — `stamp_health` single-row upsert.** Analog: the existing heartbeat tests `test_heartbeat_single_row_upserts_in_place` (217–229), `test_no_secret_in_alert_or_heartbeat_rows` (241–252). Copy the `tmp_db` fixture usage + raw `sqlite3.connect(tmp_db)` row-count/SELECT assertions; add a no-secret assertion for the `health` row.

**`tests/test_ops_selfcheck.py` (NEW) — classified self-check.** Analog: `tests/test_store.py` alert tests (160–211) for assertion style + `tests/test_scheduler.py` `test_fire_slot_*` (369+) for the injected-stub-client pattern (`load_fixture` + a fake client whose `fetch_onecall` returns ok / raises `httpx.HTTPStatusError(401)` / raises `httpx.ConnectError`). Assert `CheckResult.reason` is `online` / `auth_failed` / `network_not_ready` respectively.

**`tests/test_sdnotify.py` (NEW) — READY=1 / no-op.** No in-repo analog for AF_UNIX socket testing; use the `monkeypatch` env idiom from `tests/test_scheduler.py:584+` (`monkeypatch.setattr` / env stubbing). Bind a throwaway `socket.AF_UNIX`/`SOCK_DGRAM`, set `NOTIFY_SOCKET`, assert `READY=1` is received; assert no-op + no error when `NOTIFY_SOCKET` unset.

**`tests/test_scheduler.py` (EXTEND, NOT a new `test_daemon.py`) — gate + online-once + SIGTERM-during-gate.** Analog: the existing `test_run_daemon_stamps_tick_at_startup` (624–674) — it monkeypatches the scheduler so `run_daemon` returns immediately and asserts a DB stamp; and `test_run_flag_dispatches_to_daemon` (584–624) — it stubs `run_daemon`. Copy this exact monkeypatch+stub style: pre-set `stop` so the gate exits, assert the online signal fired exactly once (DB `health` row = `online`, `notifier.ready` called once, `channel.send` called once); and set `stop` during a failing gate to assert clean shutdown without `scheduler.start()`.

## Shared Patterns

### Secret hygiene (T-04-01) — applies to ALL new files
**Source:** `store.py` docstrings (17–20, 324–344), `discord.py:11–13/45/91`, `retry.py:34–37`.
No OpenWeather key or webhook URL in any log line, DB column, the systemd unit (use `EnvironmentFile=` only — never inline `Environment=KEY=...`), or `CheckResult.detail`. `detail` carries a status code / exception class name only. The `health` row stores reason/detail/timestamp only.
```python
# discord.py:91–98 — detail carries the EXCEPTION CLASS NAME ONLY, never the URL
except RequestException as exc:
    _log.warning("discord delivery error type=%s", type(exc).__name__)
    return DeliveryResult(ok=False, detail=type(exc).__name__)
```

### Interruptible wait (NEVER blocking sleep) — applies to the re-probe loop
**Source:** `retry.py:231` (`sleep=stop_event.wait`), `daemon.py:505` (`stop.wait()`).
Block on `stop.wait(timeout)`; a `True` return = stop was set → break cleanly. `threading.Event` is the project's standard interruptible-sleep primitive. `time.sleep()` is an anti-pattern here (laggy SIGTERM → `systemctl stop` hangs to `TimeoutStopSec`).

### Idempotent schema-on-connect + parameterized SQL — applies to `stamp_health`
**Source:** every helper in `store.py` (e.g. `record_alert:347`, `stamp_tick:392`).
`conn.executescript(_SCHEMA)` first (so the helper works on a fresh `db_path`), then a parameterized `?` `UPDATE ... WHERE id=1`, then `conn.commit()`. Never f-string a value into SQL.

### Outcome-only structured logging — applies to the gate + online signal
**Source:** `daemon.py:498` (`_log.info("daemon started", jobs=...)`), `retry.py:212–222`.
`_log = structlog.get_logger(__name__)`. Log the outcome/classification (`reason`, `jobs`, `detail`) — a self-check auth failure is `_log.critical(...)` (D-04), a transient is `_log.warning(...)`, the online event is `_log.info("weatherbot online", ...)`. Never log a secret.

### Best-effort never-raise side effect — applies to `sdnotify` + the Discord online ping
**Source:** `discord.py::_post` (72–117) — catches its own transport errors, returns/continues rather than raising.
`sdnotify.ready()` wraps the datagram send in `except OSError: pass`; the online Discord ping's non-ok `DeliveryResult` is logged but does not block startup or re-fire. Readiness/notice is best-effort — the daemon is online regardless.

## No Analog Found

| File | Role | Data Flow | Reason | Planner uses instead |
|------|------|-----------|--------|----------------------|
| `deploy/weatherbot.service` | config (systemd unit) | event-driven | No `deploy/` dir or any unit file exists in the repo; this is the one genuinely-new OS-registration artifact. | RESEARCH.md `## Code Examples → The systemd unit` (verbatim template, verified against host systemd 255) + Pitfalls 1/2/3/5/6. |
| `weatherbot/ops/sdnotify.py` (logic) | utility | event-driven (AF_UNIX) | No existing OS-IPC / socket code in the repo. | RESEARCH.md `## Code Examples → sd_notify helper` (literal code); apply `discord.py`'s never-raise posture for error handling. |

## Metadata

**Analog search scope:** `weatherbot/` (all packages: `channels/`, `config/`, `reliability/`, `scheduler/`, `weather/`), `tests/`, repo root (for `deploy/`).
**Files scanned (read this session):** `weatherbot/weather/store.py` (full), `weatherbot/reliability/retry.py` (full), `weatherbot/reliability/__init__.py` (full), `weatherbot/scheduler/daemon.py:1–60 + 430–511`, `weatherbot/cli.py:300–499`, `weatherbot/channels/discord.py` (full); grepped `tests/test_scheduler.py` + `tests/test_store.py` structure.
**Pattern extraction date:** 2026-06-11
