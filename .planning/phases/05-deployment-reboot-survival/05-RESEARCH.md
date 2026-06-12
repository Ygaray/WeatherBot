# Phase 5: Deployment & Reboot Survival - Research

**Researched:** 2026-06-11
**Domain:** systemd process supervision + startup self-check gate + sd_notify readiness, for a personal always-on Python (3.12+) daemon on a Pi/server
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Ship a **systemd unit** (`.service` with `Restart=always` + `EnvironmentFile=` for `.env` secrets) running `weatherbot --run`. Docker/compose is **NOT** shipped this phase.
- **D-02:** The unit declares **`After=network-online.target`** + **`Wants=network-online.target`** so on reboot the daemon waits for the network.
- **D-03:** The daemon **runs the self-check itself at startup** (does NOT rely on an operator running `--check`). Reuse the existing `do_check` logic (config + template validation + ONE OpenWeather reachability probe whose 401/403 distinguishes "subscription not active / not yet propagated" from a generic error). Runs **before** the online signal.
- **D-04 (stay-up, never crash-loop):** On a self-check failure the daemon **stays alive and re-probes internally** — does NOT exit-and-let-the-supervisor-restart. Holds for BOTH transient/not-ready failures (network-not-up, key still propagating) AND a genuine permanent auth failure (confirmed 401/403): on the latter, log CRITICAL + write a durable health/alert row and **keep re-probing** (a dead process can't answer a future inbound-`status` query). Re-probe interval is **Claude's discretion** (~60–300s; may promote to config later).
- **D-05 (all three signals, fired once after first successful self-check):** online signal = (1) structured log + durable DB stamp, (2) systemd `sd_notify` `READY=1` (unit is **`Type=notify`**), (3) one-time Discord "online" webhook ping. Fires **exactly once per process start, only AFTER the self-check first passes**; if the startup probe initially fails, the online signal (incl. `READY=1`) is **DEFERRED** until the internal re-probe first succeeds.
- **D-06 (reboot network-readiness):** Startup probe failures are **classified**: connection/timeout/DNS (and not-yet-active key) → transient "not ready" → re-probe/wait; distinct from a confirmed 401/403 bad key. Combined with `After=network-online.target`, a real Pi reboot is robust, not a false "bad key" failure.
- **D-07 (Discord ping anti-spam):** The online ping posts **exactly once per process start** when a freshly-started process passes its self-check. Internal re-probe recoveries do **NOT** re-post. A supervisor crash-loop posts per *new* process start (accepted as an honest "I restarted" signal).
- **D-08 (queryable health/status state):** Make the daemon's current health/error state durable + queryable — a health/status row in `data/weatherbot.db` reflecting last self-check result + current reason (`online`, `network_not_ready`, `auth_failed`, `key_propagating`), reusing the `alerts`/`heartbeat` `INSERT OR IGNORE` / single-row-upsert pattern. **In scope:** writing/maintaining the row. **Out of scope:** the inbound command that reads it (deferred).

### Claude's Discretion
- Self-check re-probe interval (sensible default, may promote to config).
- Exact systemd unit filename, `User=`/`WorkingDirectory=`/`RestartSec=` values, install snippet.
- Exact health/status row table/column names + the online-event key — follow `store.py` conventions.
- The precise transient-vs-permanent probe classification — reuse Phase 4's `is_transient`/`is_auth_failure`.
- Whether the online DB stamp reuses `heartbeat` or adds a dedicated `online`/`status` row (likely the D-08 health row).

### Deferred Ideas (OUT OF SCOPE)
- **Inbound Discord `status` command** (needs a Discord gateway bot + token — do NOT research discord.py gateway bots). Phase 5 lays the seam (D-08) but does NOT build the reader.
- **Docker / container deployment** (systemd chosen, D-01).
- **Promoting the re-probe interval to config** (carried as a discretion default).
- **Routing the online/health log event to journald→email / external monitoring** (the future monitoring bot's job).
- SMS/Telegram channels, weather-pattern analysis (v2).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS-01 | The bot runs as a long-running supervised process that survives crashes and host reboot (systemd `Restart=always`), restarting automatically. | `## Standard Stack` (systemd unit), `## Code Examples` (the unit file), `## Common Pitfalls` (Restart loop / WantedBy enable). The daemon already does NOT self-daemonize and already shuts down cleanly on SIGTERM (`run_daemon`, `daemon.py:439–511`) — systemd just supervises it. |
| OPS-02 | On startup the bot self-checks (config valid + OpenWeather key reachable, distinguishing key-not-yet-active from genuine auth error) and emits an "online" signal so a silent death is detectable. | `do_check` already implements the probe + 401/403 distinction (`cli.py:314–394`). Research covers: extracting `do_check` into a reusable engine, classifying its failure (reuse `is_transient`/`is_auth_failure`, `reliability/retry.py:80–99`), the interruptible re-probe loop wired around `scheduler.start()`, the three online signals (log+DB stamp, `sd_notify READY=1`, one-time Discord ping), and the durable health/status row (D-08). |
</phase_requirements>

## Summary

Phase 5 is almost entirely **integration and ops wiring**, not new library territory. The daemon (`run_daemon`, `weatherbot/scheduler/daemon.py:439–511`) is already a clean foreground process with a SIGTERM-clean shutdown via a `threading.Event` (`stop`), and it explicitly does *not* self-daemonize — it was built waiting for exactly this phase. The self-check engine (`do_check`, `weatherbot/cli.py:314–394`) already validates config + template, resolves locations, and makes ONE OpenWeather probe whose 401/403 message distinguishes "subscription not active / not yet propagated" (Pitfall 1) from a generic error. The failure classifiers `is_transient` / `is_auth_failure` (`weatherbot/reliability/retry.py:80–99`) already exist. The durable-state primitives (single-row `heartbeat`, `INSERT OR IGNORE` `alerts`) in `weatherbot/weather/store.py` are the exact template for the D-08 health row.

The only genuinely external surface is **systemd**: a `Type=notify` `Restart=always` unit, and the `sd_notify(READY=1)` readiness handshake. Verified against the host's own systemd (255) man pages and freedesktop/systemd.io docs: `READY=1` is sent as a single `AF_UNIX`/`SOCK_DGRAM` datagram to the path in `$NOTIFY_SOCKET` (with the leading `@` → `\0` abstract-socket fixup), which is a ~10-line pure-stdlib function — **no new dependency is warranted** given the project's minimal-dep posture (the `sdnotify` PyPI package is the same ~10 lines). Under `Type=notify`, systemd holds the unit in "activating (start)" until `READY=1` arrives or `TimeoutStartSec` (default `DefaultTimeoutStartSec`, typically 90s) elapses — which is the **one real pitfall**: the deferred-online design (D-05) means `READY=1` may not arrive for *minutes* while the re-probe loop waits, so the unit MUST either raise `TimeoutStartSec=infinity` or have the daemon send `EXTEND_TIMEOUT_USEC=` / fall back to `Type=exec`. The recommendation below resolves this explicitly.

A second verified, design-validating finding: `network-online.target` **does not guarantee DNS or internet reachability** — only that a wait-online service reported local link/IP connectivity "has been reached" (it may already be gone again). This is precisely *why* D-04's stay-alive re-probe loop is mandatory rather than optional: even with `After=network-online.target`, the first OpenWeather probe on a fresh Pi boot can legitimately hit a transient DNS/connection error, which must be classified "not ready" and retried — not treated as a fatal bad key.

**Primary recommendation:** Add no new dependencies. Extract `do_check`'s validate+probe into a reusable engine that returns a classified result; wire a SIGTERM-interruptible re-probe loop into `run_daemon` *before* `scheduler.start()` using the existing `stop` Event; on first pass, fire all three online signals once and send `READY=1` via a ~10-line stdlib `sd_notify` helper (no-op when `NOTIFY_SOCKET` is unset); maintain a single-row `health` table (D-08) on every probe outcome. Ship a `Type=notify`, `Restart=always`, `EnvironmentFile=`, `After=/Wants=network-online.target` unit, and use `TimeoutStartSec=infinity` (simplest correct choice given the deferred-online gate).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Process liveness / auto-restart / reboot survival (OPS-01) | OS supervisor (systemd) | — | The daemon explicitly does NOT self-daemonize; systemd owns process liveness (CLAUDE.md "systemd only to keep the *process* alive, not to schedule"). |
| Network-readiness ordering on boot | OS supervisor (systemd unit ordering) | App (re-probe loop) | `After=network-online.target` gets the daemon close; the app's re-probe loop covers the residual DNS/transient gap the target does not guarantee. |
| Startup self-check (config+template+probe) (OPS-02) | App (daemon, reusing `do_check`) | — | Must run in-process before announcing online (D-03); systemd cannot validate OpenWeather reachability. |
| Failure classification (transient vs auth vs propagating) | App (`reliability/retry.py` classifiers) | — | Pure domain logic over `httpx` exceptions; reuse Phase 4's `is_transient`/`is_auth_failure`. |
| Readiness handshake (`READY=1`) | App → OS supervisor (sd_notify over `$NOTIFY_SOCKET`) | — | Only the app knows when the self-check passed; systemd reflects it in `systemctl status`. |
| Durable health/status state (D-08) | App (SQLite `store.py`) | — | A queryable row for the future inbound-`status` reader; same store as `alerts`/`heartbeat`. |
| Human-facing "online" notice | App (existing Discord webhook channel) | — | Reuse the existing `Channel.send`; no new mechanism. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| systemd (host) | 247+ (host has **255**) | Process supervisor: `Restart=always`, reboot survival, `Type=notify` readiness, `EnvironmentFile=` secrets | CLAUDE.md's chosen "lightest reliable" supervisor for a Pi/server. The host running this repo is systemd 255 — all directives below are confirmed present. [VERIFIED: local man pages, `systemctl --version` = systemd 255] |
| Python stdlib `socket` | built-in (3.12+) | Send `READY=1` to `$NOTIFY_SOCKET` (AF_UNIX/SOCK_DGRAM datagram) | The sd_notify wire protocol is a single datagram; stdlib covers it in ~10 lines. No dependency needed (matches STACK.md minimal-dep posture). [VERIFIED: systemd sd_notify docs + Arch/man7 sd_notify(3)] |
| Python stdlib `os` | built-in | Read `NOTIFY_SOCKET` env var (graceful no-op when unset) | Standard way to detect "running under systemd vs interactively/in tests". [VERIFIED] |

**No new runtime dependency is required for this phase.** Everything else (apscheduler, httpx, tenacity, discord-webhook, structlog, pydantic) is already in `pyproject.toml` and reused unchanged.

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `sdnotify` (PyPI) | 0.3.x | Thin wrapper around the same `$NOTIFY_SOCKET` datagram | **Do NOT add.** Listed only as the alternative the project deliberately rejects — it is ~10 lines of the same stdlib code, and adds a dependency for no behavioral gain. [ASSUMED — not installed/verified; pip unavailable in this env] |
| `systemd-python` (PyPI) | 235 | libsystemd CFFI bindings incl. `daemon.notify()` | **Do NOT add.** Requires `libsystemd-dev` headers + C compile at install — heavy and Pi-hostile for one datagram. [ASSUMED — not verified] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `Type=notify` + stdlib `sd_notify` | `Type=exec` (no readiness handshake) | `Type=exec` is simpler (systemd considers the unit started once `execve` succeeds) but loses the D-05 "systemctl status reflects genuine readiness, not just process-spawned" property. Keep `Type=notify` per D-05; only fall back to `Type=exec` if the `TimeoutStartSec` interaction proves troublesome (see Pitfall 2). |
| `TimeoutStartSec=infinity` | Daemon sends periodic `EXTEND_TIMEOUT_USEC=` during the re-probe loop | `EXTEND_TIMEOUT_USEC=` is more "correct" (keeps a real start timeout for genuine hangs) but adds a recurring notify call inside the loop. For a personal bot whose only legitimate slow-start cause is "key still propagating (up to ~2h)", `infinity` is simpler and matches the user's explicit never-crash-loop intent (D-04). |
| stdlib `sd_notify` helper | `sdnotify` / `systemd-python` PyPI | See Supporting table — both add a dependency for the same ~10 lines; rejected per minimal-dep posture. |
| systemd unit | Docker `restart: always` | Explicitly out of scope (D-01); systemd chosen for the Pi/personal host. |

**Installation:** None. (No `uv add`. If a future phase wanted the wrapper: `uv add sdnotify` — but this phase ships zero new deps.)

**Version verification:** Host systemd version confirmed via `systemctl --version` → `systemd 255 (255.4-1ubuntu8.15)`. The directives used (`Type=notify`, `Restart=always`, `RestartSec=`, `TimeoutStartSec=`, `EnvironmentFile=`, `WatchdogSec=`, `After=/Wants=network-online.target`) are all present in the host's `systemd.service(5)` man page. `RestartSec` default is **100ms** [VERIFIED: local `systemd.service.5` man page].

## Package Legitimacy Audit

> This phase installs **no external packages**. All code is pure stdlib (`socket`, `os`) plus already-installed, already-audited dependencies. The two PyPI wrappers below are documented only as *rejected* alternatives — they are NOT recommended for install.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `sdnotify` | PyPI | mature (~2015+) | moderate | github.com/bb4242/sdnotify | not run (pip unavailable) | NOT installed — rejected alternative ([ASSUMED]) |
| `systemd-python` | PyPI | mature | high | github.com/systemd/python-systemd | not run | NOT installed — rejected alternative ([ASSUMED]) |

**Packages removed due to slopcheck [SLOP] verdict:** none (none installed).
**Packages flagged as suspicious [SUS]:** none.

*slopcheck and pip were unavailable in the research environment. This carries **zero risk** because the phase recommends installing nothing — the two packages above are explicitly rejected, not adopted. If a future maintainer overrides this and adds `sdnotify`/`systemd-python`, the planner MUST gate that install behind a `checkpoint:human-verify` task and re-run the legitimacy gate.*

## Architecture Patterns

### System Architecture Diagram

```
                          HOST REBOOT / CRASH
                                  │
                                  ▼
          ┌──────────────────────────────────────────────┐
          │ systemd  (weatherbot.service)                 │
          │   Restart=always  RestartSec=5s               │
          │   Type=notify     TimeoutStartSec=infinity    │
          │   EnvironmentFile=.env  (OPENWEATHER_API_KEY, │
          │                          DISCORD_WEBHOOK_URL)  │
          │   After=/Wants=network-online.target          │
          └───────────────┬──────────────────────────────┘
              waits for    │  (link/IP up — NOT DNS/internet guaranteed)
       network-online.target  ExecStart=… weatherbot --run
                                  │
                                  ▼
   ┌──────────────────────── run_daemon (foreground) ─────────────────────────┐
   │                                                                            │
   │  1. register cron jobs + heartbeat IntervalTrigger                         │
   │  2. announce schedule                                                      │
   │                                                                            │
   │  3. ── STARTUP SELF-CHECK GATE (NEW, D-03) ──────────────────────┐         │
   │     run_self_check()  ──►  validate config+template, resolve     │         │
   │       │                    locations, ONE OpenWeather probe      │         │
   │       │                                                          │         │
   │       ├─ PASS ──────────────────────────► emit online ONCE (D-05)│         │
   │       │                                   • structured log + DB   │        │
   │       │                                     stamp (health row=    │        │
   │       │                                     'online')             │        │
   │       │                                   • sd_notify READY=1      │        │
   │       │                                   • Discord one-time ping  │        │
   │       │                                                            │        │
   │       └─ FAIL ── classify(exc) ──┐                                 │        │
   │            (is_auth_failure /     │  write health row reason:      │        │
   │             is_transient /        │   network_not_ready |          │        │
   │             401-but-new-key)      │   key_propagating |            │        │
   │                                   │   auth_failed (+CRITICAL log)  │        │
   │                                   ▼                                │        │
   │            RE-PROBE LOOP: stop.wait(interval) then re-run          │        │
   │            self-check.  stop.set() (SIGTERM) breaks out CLEANLY.   │        │
   │            On FIRST pass → emit online ONCE (deferred), then exit  │        │
   │            the loop.  NEVER sys.exit on failure (D-04).            │        │
   │     ─────────────────────────────────────────────────────────────┘        │
   │                                                                            │
   │  4. scheduler.start()  →  stamp_tick  →  block on stop.wait()              │
   │       SIGTERM handler sets stop → scheduler.shutdown(wait=False)           │
   └────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                   data/weatherbot.db  (health row = read-seam for
                   the FUTURE inbound-`status` command, D-08)
```

### Recommended Project Structure
```
deploy/
└── weatherbot.service          # NEW — the systemd unit (template + install notes)

weatherbot/
├── scheduler/
│   └── daemon.py               # MODIFY — wire self-check gate + re-probe loop + online signal into run_daemon
├── ops/                        # NEW (optional) — small, focused ops helpers
│   ├── __init__.py
│   ├── sdnotify.py             # NEW — ~10-line stdlib READY=1 / WATCHDOG=1 (no-op if NOTIFY_SOCKET unset)
│   └── selfcheck.py            # NEW (optional) — extracted reusable self-check engine + classified result
├── cli.py                      # MODIFY — refactor do_check to call the shared self-check engine
└── weather/
    └── store.py                # MODIFY — add single-row `health` table + stamp_health()/read_health()
```
*Placement of `selfcheck`/the online-signal helper is the planner's call — it may live in `scheduler/` or a new `ops/`. The only hard constraint: avoid re-introducing the cli↔daemon import cycle (`run_daemon` is already imported lazily inside `cli.main`'s `--run` branch, `cli.py:494`).*

### Pattern 1: Extract the self-check into a reusable, *classified* engine
**What:** `do_check` (`cli.py:314–394`) currently does validate→probe→print-budget→return-int (0/1). The daemon needs the same validate+probe but a **classified outcome** (pass | network_not_ready | key_propagating | auth_failed), not just exit code, so the re-probe loop and the health row can branch.
**When to use:** D-03 (startup gate) + D-04 (re-probe) + D-06 (classification).
**Example:**
```python
# Source: derived from weatherbot/cli.py:314-394 + reliability/retry.py:80-99
from dataclasses import dataclass
from weatherbot.reliability import is_auth_failure, is_transient
import httpx

PASS = "online"
NETWORK_NOT_READY = "network_not_ready"
KEY_PROPAGATING = "key_propagating"
AUTH_FAILED = "auth_failed"

@dataclass
class CheckResult:
    ok: bool
    reason: str          # one of the constants above
    detail: str = ""     # outcome-only, NEVER a secret (T-04-01)

def run_self_check(*, config, settings=None, client=None) -> CheckResult:
    """Validate config+template, resolve locations, ONE probe. Classify the failure.
    Reuses do_check's exact validation/probe steps; differs only in returning a
    CheckResult instead of printing + exit code."""
    try:
        # (1) config already validated at load; (2) template; (4) unique names + resolve
        # ... reuse do_check steps (validate_template / assert_unique_names / resolve_location)
        if client is None:
            client = build_client(settings)
        client.fetch_onecall(config.locations[0], "imperial")     # (3) ONE probe
    except httpx.HTTPStatusError as exc:
        if is_auth_failure(exc):                                  # 401/403
            # A 401/403 on a *new* key is "still propagating" (Pitfall 1/8), not a
            # confirmed bad key — but we cannot distinguish them from one response.
            # Per D-06: treat 401/403 as auth_failed; the re-probe loop keeps trying
            # so a genuinely-propagating key recovers on a later attempt anyway.
            return CheckResult(ok=False, reason=AUTH_FAILED, detail=f"{exc.response.status_code}")
        return CheckResult(ok=False, reason=NETWORK_NOT_READY, detail="http_status")
    except Exception as exc:                                      # noqa: BLE001
        if is_transient(exc):                                     # timeout/connect/read/5xx/429
            return CheckResult(ok=False, reason=NETWORK_NOT_READY, detail=type(exc).__name__)
        return CheckResult(ok=False, reason=NETWORK_NOT_READY, detail=type(exc).__name__)
    return CheckResult(ok=True, reason=PASS)
```
**Note on the 401/403 vs key-propagating split (D-06):** A *single* 401/403 response is genuinely ambiguous between "permanently bad key" and "new key still propagating" — OpenWeather returns the same status for both (Pitfall 8, up to ~2h activation). The honest design (and the user's D-04 intent) is: **classify 401/403 as `auth_failed`, log CRITICAL, write the health row — but STILL keep re-probing.** If it was merely propagating, a later re-probe passes and flips the row to `online`; if it is genuinely bad, the row stays `auth_failed` for the future `status` reader to surface. `do_check`'s existing message already says "may not be active or not yet propagated — wait a few hours and retry" — reuse that wording. `key_propagating` as a *distinct* reason is optional sugar; the planner may collapse it into `auth_failed` since one probe cannot tell them apart. `[VERIFIED: cli.py:355-366, reliability/retry.py:94-99]`

### Pattern 2: SIGTERM-interruptible re-probe loop, reusing the existing `stop` Event
**What:** The re-probe loop must block between attempts but abandon instantly on SIGTERM/stop, exactly like the existing two-burst retry (`build_retrying` wires `sleep=stop_event.wait`, `retry.py:231`) and the existing `stop.wait()` at `daemon.py:505`.
**When to use:** D-04 stay-alive loop; must run *before* `scheduler.start()` so the online signal precedes job firing.
**Example:**
```python
# Source: derived from daemon.py:459 (stop = threading.Event()) + retry.py:231 pattern
RE_PROBE_INTERVAL_S = 120   # Claude's discretion (D-04); 60–300s sensible. May promote to config.

def gate_until_healthy(stop, *, config, settings, db_path, channel, notifier) -> bool:
    """Run the self-check; on failure stay alive and re-probe until pass or stop.
    Returns True once healthy, False if stop was set first (clean shutdown). NEVER exits."""
    while not stop.is_set():
        result = run_self_check(config=config, settings=settings)
        stamp_health(db_path, reason=result.reason, detail=result.detail)   # D-08, every outcome
        if result.ok:
            return True
        if result.reason == AUTH_FAILED:
            _log.critical("startup self-check auth failure", reason=result.reason, detail=result.detail)
        else:
            _log.warning("startup self-check not ready", reason=result.reason, detail=result.detail)
        # stop.wait(timeout) returns True if stop was set during the wait → clean exit.
        if stop.wait(RE_PROBE_INTERVAL_S):
            break
    return False
```
**Wiring point in `run_daemon`:** after `_announce_schedule` / before `scheduler.start()` (`daemon.py:483→492`). If `gate_until_healthy` returns `True`, call the once-only `emit_online(...)`; if it returns `False` (stop set during the loop), fall straight through to the existing `finally: scheduler.shutdown(...)` — do NOT start the scheduler, do NOT emit online. **Important:** the SIGTERM handler currently installed at `daemon.py:503` is registered *after* `scheduler.start()`. The re-probe loop runs *before* that — so the signal handler (`signal.signal(SIGTERM, _handle)`) must be **registered earlier**, before `gate_until_healthy`, so a `systemctl stop` during the re-probe loop is honored. This is a load-bearing ordering change. `[VERIFIED: daemon.py:500-505]`

### Pattern 3: One-time online signal (fire exactly once per process)
**What:** All three online signals (log+DB stamp, `READY=1`, Discord ping) fire exactly once, the first time the self-check passes (D-05/D-07). Recoveries from a *later* re-probe do not re-fire (the loop returns immediately on first pass, so this is naturally satisfied — there is no "later recovery" within one `run_daemon` call once it has passed once).
**Example:**
```python
# Source: reuses store.stamp_tick/stamp_success pattern + existing Channel.send (discord.py:50)
def emit_online(*, db_path, channel, notifier, jobs: int) -> None:
    stamp_health(db_path, reason="online")          # 1a. durable DB row (D-08 / D-05)
    stamp_tick(db_path)                              # 1b. reuse existing liveness tick (daemon.py:497)
    _log.info("weatherbot online", jobs=jobs)        # 1c. structured log event (machine-detectable)
    notifier.ready()                                 # 2.  sd_notify READY=1 (no-op if NOTIFY_SOCKET unset)
    if channel is not None:                          # 3.  one-time human-facing Discord ping (D-07)
        channel.send("✅ WeatherBot online — startup self-check passed.")
```
The Discord ping reuses the **existing** `Channel.send(text)` (`discord.py:50`) — no new mechanism (D-05/D-07). It is a best-effort fire-and-forget: a non-ok `DeliveryResult` from the ping should be logged but must NOT block startup or re-fire (the daemon is online regardless of whether the human notice landed). `[VERIFIED: discord.py:50-52]`

### Pattern 4: Pure-stdlib `sd_notify` (no dependency)
**What:** Send `READY=1` (and optionally `WATCHDOG=1`) as a single AF_UNIX/SOCK_DGRAM datagram to `$NOTIFY_SOCKET`, with the abstract-socket `@`→`\0` fixup. No-op when `NOTIFY_SOCKET` is unset (running interactively or in tests).
**Example:** see `## Code Examples` below.

### Anti-Patterns to Avoid
- **`sys.exit()` / raising on a failed self-check.** Violates D-04 — a crash-looping process can't answer a future `status` query, and under `Restart=always` it would hammer restart. STAY ALIVE and re-probe.
- **Blocking `time.sleep()` in the re-probe loop.** Makes SIGTERM laggy/ignored — `systemctl stop` would wait the full interval. Use `stop.wait(interval)` (the project's established interruptible-sleep idiom, `retry.py:231`).
- **`Type=notify` without ever sending `READY=1`, with a finite `TimeoutStartSec`.** systemd marks the start *failed* at the timeout and (with `Restart=always`) restarts — a crash-loop disguised as a timeout. Either `READY=1` reliably arrives within the timeout, or set `TimeoutStartSec=infinity` (recommended here, since the deferred-online gate can legitimately take minutes-to-hours).
- **Adding `sdnotify` / `systemd-python`.** Dependency for ~10 stdlib lines; rejected per minimal-dep posture.
- **Putting the API key / webhook URL in the unit file or any health-row column.** Secrets come from `.env` via `EnvironmentFile=` only (CONF-02 / Pitfall 7); the health row carries reason/timestamp only (T-04-01).
- **Re-posting the Discord "online" ping on every re-probe recovery.** D-07: once per process start only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Process auto-restart / reboot survival | A bash `while true` wrapper, `nohup`, cron `@reboot` | systemd `Restart=always` + `WantedBy=multi-user.target` | The project explicitly chose an in-process scheduler + systemd-only-for-liveness (CLAUDE.md). Hand-rolled supervision misses reboot, backoff, and journald integration. |
| Readiness signaling | A PID file + polling, a "started" sentinel file | `Type=notify` + `sd_notify(READY=1)` | systemd has a first-class readiness protocol; a sentinel file races and isn't visible in `systemctl status`. |
| Failure classification (transient vs auth) | New `if exc.status in (...)` logic | `reliability/retry.py` `is_transient` / `is_auth_failure` | Already built, tested, and reason-tagged in Phase 4 (RELY-01/02). Re-deriving risks drift. |
| Durable single-row state | A new ad-hoc JSON file | `store.py` single-row-upsert pattern (`heartbeat`) + `INSERT OR IGNORE` | The DB is already the durable-state home; a JSON file isn't queryable by the future `status` reader (D-08). |
| Interruptible sleep | `time.sleep()` + signal flag polling | `threading.Event.wait(timeout)` | The codebase already standardizes on `stop.wait` for interruptible pauses (`retry.py:231`, `daemon.py:505`). |
| Loading `.env` for the service | `python-dotenv` call inside the daemon for the systemd path | systemd `EnvironmentFile=.env` | The app already reads secrets from the environment via pydantic-settings; `EnvironmentFile=` populates that environment. (See Pitfall 3 for the `.env` format caveat.) |

**Key insight:** This phase is "wire the existing pieces to systemd," not "build new machinery." Every domain primitive it needs already exists in the repo; the only new code is a ~10-line stdlib sd_notify helper, a small classified-result wrapper around `do_check`, a single-row `health` table, and the loop/ordering changes in `run_daemon`.

## Runtime State Inventory

> This phase is **additive** (new unit file, new code paths, additive SQLite table) — it does not rename or migrate anything. Inventory included because it touches deployment/runtime registration.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **New** single-row `health` table in `data/weatherbot.db` (D-08). Additive `CREATE TABLE IF NOT EXISTS` like `heartbeat` — no migration, no backfill. Existing `sent_log`/`alerts`/`heartbeat`/`weather_onecall` rows untouched. | Code: add table to `_SCHEMA` + `stamp_health`/`read_health` helpers. No data migration. |
| Live service config | **New** OS-registered systemd unit `weatherbot.service`. This is the one *new* runtime registration this phase creates (it does not yet exist). On install it must be `systemctl daemon-reload`'d + `enable`'d (for reboot) + `start`'d. | Install step: copy unit, `daemon-reload`, `enable --now`. Document in deploy notes. |
| OS-registered state | None pre-existing. The new `weatherbot.service` IS the registration. Host already has `NetworkManager-wait-online.service` **enabled** (verified) → `network-online.target` will actually wait. | Verify the wait-online service is enabled on the *target* host (it is on this host). |
| Secrets/env vars | `OPENWEATHER_API_KEY`, `DISCORD_WEBHOOK_URL` already read from `.env` via pydantic-settings (CONF-02). systemd `EnvironmentFile=` must point at the same `.env`. **No new secret introduced.** `NOTIFY_SOCKET` is injected *by systemd* (not a user secret) and read read-only. | Code: read `NOTIFY_SOCKET` (no-op if unset). Unit: `EnvironmentFile=<path>/.env`. Mind `.env` format (Pitfall 3). |
| Build artifacts / installed packages | None. No new package installed (zero new deps). `weatherbot --run` is already the console entry / module invocation used today (`cli.py:483-496`). | Confirm the `ExecStart` invocation matches how the project is actually run (uv-run vs venv python vs console script — see Pitfall 5). |

## Common Pitfalls

### Pitfall 1: `Type=notify` startup hang / false-failure when `READY=1` is deferred
**What goes wrong:** Under `Type=notify`, systemd holds the unit in `activating (start)` until it receives `READY=1`. The first receipt must occur before `TimeoutStartSec` (default = `DefaultTimeoutStartSec`, commonly **90s**). The D-05 design **defers** `READY=1` until the self-check first passes — which, on a propagating key (Pitfall 8: up to ~2h) or a slow-network boot, can far exceed 90s. systemd then marks the start **failed**, and with `Restart=always` restarts the process → an effective crash-loop, defeating D-04's "stay alive" intent.
**Why it happens:** The deferred-readiness design is fundamentally at odds with a finite start timeout.
**How to avoid (recommendation):** Set **`TimeoutStartSec=infinity`** on the unit. This is the simplest correct choice given that the *only* legitimate slow-start causes here are exactly the ones D-04 says to wait through. (Alternative: keep a finite timeout and have the re-probe loop send `EXTEND_TIMEOUT_USEC=<usec>` each iteration via the same notify socket — more "correct" but more code; not recommended for a personal bot.)
**Warning signs:** `systemctl status weatherbot` shows repeated `Failed with result 'timeout'` then restart; `journalctl` shows the self-check still looping. `[VERIFIED: local systemd.service.5 — TimeoutStartSec defaults to DefaultTimeoutStartSec, EXTEND_TIMEOUT_USEC extends it]`

### Pitfall 2: SIGTERM handler registered *after* the re-probe loop → `systemctl stop` ignored during the loop
**What goes wrong:** Today the SIGTERM handler is installed at `daemon.py:503`, *after* `scheduler.start()`. If the new re-probe loop runs before that (it must, per D-03/D-05 ordering), a `systemctl stop` (or `systemctl restart` for a redeploy) during the loop has no handler → default SIGTERM behavior may not cleanly set `stop`, and systemd escalates to SIGKILL after `TimeoutStopSec`.
**Why it happens:** Ordering: the loop is new code inserted before the existing handler registration.
**How to avoid:** Register the SIGTERM handler **before** entering `gate_until_healthy`, and have the loop block on `stop.wait(interval)` so the handler's `stop.set()` breaks it immediately. Then the existing `finally: scheduler.shutdown(wait=False)` runs.
**Warning signs:** `systemctl stop` hangs ~90s (the `TimeoutStopSec` default) then logs `Killed`. `[VERIFIED: daemon.py:500-505]`

### Pitfall 3: `EnvironmentFile=` vs `python-dotenv` / pydantic-settings `.env` parsing differ
**What goes wrong:** systemd's `EnvironmentFile=` parser is **not** a shell and **not** python-dotenv. Notably: it does NOT do shell-style quote-stripping the same way, does NOT support `export `, does NOT expand `$VAR` or `~`, and treats quotes more literally in older systemd (modern systemd does strip matching outer single/double quotes). A `.env` written for python-dotenv with `export FOO="bar"` or inline comments after a value can be parsed differently, so the daemon sees a subtly-wrong `OPENWEATHER_API_KEY` (→ a 401 that looks like Pitfall 8) or `DISCORD_WEBHOOK_URL`.
**Why it happens:** The project's `.env` is currently consumed by pydantic-settings (python-dotenv semantics); reusing the *same file* via `EnvironmentFile=` assumes identical parsing.
**How to avoid:** Keep the `.env` to the lowest-common-denominator form: `KEY=value`, one per line, no `export`, no inline `# comment` after a value, no shell expansion. Validate by `systemctl show -p Environment weatherbot` (or a throwaway `systemd-run --property=EnvironmentFile=...`) after install. Document this format constraint in the deploy notes. `[VERIFIED: systemd EnvironmentFile semantics — systemd.exec(5); MEDIUM — exact quote behavior varies by systemd version, host is 255]`

### Pitfall 4: `network-online.target` does not guarantee DNS / internet — the first probe can still fail
**What goes wrong:** Developers assume `After=network-online.target` means "the OpenWeather probe will succeed." It only means a wait-online service reported local link/IP connectivity *has been reached* — **not** that DNS resolves or the internet is reachable (and it may already be gone again). On a Pi just after boot, the first probe can hit a transient DNS/connection error.
**Why it happens:** Misreading the target's guarantee.
**How to avoid:** This is exactly why D-04's re-probe loop is mandatory: classify the first probe's connection/timeout/DNS failure as `network_not_ready` (via `is_transient`) and re-probe — do NOT treat it as a fatal bad key. Also ensure the *target host* has the correct wait-online service enabled (`NetworkManager-wait-online.service` OR `systemd-networkd-wait-online.service`, not both) — without it, `network-online.target` waits for nothing. (This host: `NetworkManager-wait-online` **enabled**, `systemd-networkd-wait-online` disabled — correct.)
**Warning signs:** First-boot journal shows a single `network_not_ready` probe failure that self-resolves on the next re-probe — this is **expected and healthy**, not a bug. `[VERIFIED: systemd.io/NETWORK_ONLINE/ + host systemctl is-enabled]`

### Pitfall 5: `ExecStart=` doesn't match how the project actually runs (uv / venv / console script)
**What goes wrong:** `weatherbot --run` works in the dev shell because the venv is active / `uv run` resolves it. systemd runs with a minimal environment and no active venv, so a bare `ExecStart=weatherbot --run` may not find the interpreter or the package.
**Why it happens:** systemd does not inherit the developer's shell PATH/venv.
**How to avoid:** Use an absolute, environment-independent `ExecStart`. Two robust options for a uv project: (a) `ExecStart=/usr/bin/uv run weatherbot --run` with `WorkingDirectory=<repo>` (uv resolves the project venv), or (b) the explicit venv interpreter: `ExecStart=<repo>/.venv/bin/python -m weatherbot --run` (no venv activation needed). Set `WorkingDirectory=` to the repo so the default `config.toml` / `data/` paths resolve (the daemon uses `data/weatherbot.db` relative path, `cli.py:62`). Confirm the actual run mechanism before pinning the line — Claude's discretion per CONTEXT, but it MUST be absolute. `[VERIFIED: cli.py:62 relative DEFAULT_DB_PATH; CLAUDE.md uv stack]`

### Pitfall 6: `WatchdogSec` left on without sending `WATCHDOG=1` → systemd kills a healthy bot
**What goes wrong:** If the unit sets `WatchdogSec=` but the daemon never sends `WATCHDOG=1` keep-alives, systemd considers it hung and kills+restarts it on the interval — a self-inflicted crash-loop.
**Why it happens:** Copy-pasting a "production" unit that includes `WatchdogSec`.
**How to avoid:** **Defer the watchdog** (CONTEXT flags it as likely-deferred). Do NOT set `WatchdogSec=` in this phase. If wanted later, it's cheap: the same stdlib notifier sends `WATCHDOG=1` from inside the existing `stop.wait` block on a sub-`WatchdogSec` interval, and the unit adds `WatchdogSec=`. Note it as a one-line future enhancement, not Phase 5 scope. `[VERIFIED: sd_notify WATCHDOG=1 + systemd.service WatchdogSec]`

## Code Examples

### The systemd unit (`deploy/weatherbot.service`)
```ini
# Source: synthesized from host systemd.service(5) [systemd 255] + systemd.io/NETWORK_ONLINE
# Replace <REPO>, <USER>, and the ExecStart per Pitfall 5 (confirm uv vs venv path).
[Unit]
Description=WeatherBot — personal morning weather briefing daemon
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
NotifyAccess=main
# Deferred-online gate (D-05) can legitimately take minutes-to-hours (key propagation,
# slow boot network) — do NOT let a finite start timeout turn that into a crash-loop (Pitfall 1).
TimeoutStartSec=infinity
ExecStart=/usr/bin/uv run weatherbot --run
WorkingDirectory=<REPO>
EnvironmentFile=<REPO>/.env
User=<USER>
Restart=always
RestartSec=5
# (No WatchdogSec in v1 — deferred, Pitfall 6.)

[Install]
WantedBy=multi-user.target
```
Install (deploy notes):
```bash
sudo cp deploy/weatherbot.service /etc/systemd/system/weatherbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now weatherbot.service     # enable = survive reboot (OPS-01)
systemctl status weatherbot                         # should reach "active (running)" only AFTER READY=1
journalctl -u weatherbot -f                          # watch the self-check / online log
```

### The pure-stdlib sd_notify helper (`weatherbot/ops/sdnotify.py`)
```python
# Source: systemd sd_notify(3) protocol — man7.org/Arch sd_notify.3 + systemd docs.
# Sends a single AF_UNIX/SOCK_DGRAM datagram to $NOTIFY_SOCKET. No dependency.
from __future__ import annotations
import os
import socket


class SystemdNotifier:
    """READY=1 / WATCHDOG=1 to systemd. A no-op when not run under systemd
    (NOTIFY_SOCKET unset) — so the daemon runs identically interactively and in tests."""

    def __init__(self) -> None:
        addr = os.environ.get("NOTIFY_SOCKET")
        # Abstract-namespace socket: leading '@' must become a NUL byte.
        if addr and addr.startswith("@"):
            addr = "\0" + addr[1:]
        self._addr = addr or None

    def _send(self, msg: str) -> None:
        if self._addr is None:
            return  # not under systemd -> silently do nothing
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.sendto(msg.encode("utf-8"), self._addr)
        except OSError:
            # Never let a notify failure crash the daemon; readiness is best-effort signaling.
            pass

    def ready(self) -> None:
        self._send("READY=1")

    def watchdog(self) -> None:           # deferred (Pitfall 6) — present but unused in v1
        self._send("WATCHDOG=1")
```
Key protocol facts (all [VERIFIED: man7.org sd_notify.3 / systemd sd_notify docs]): the payload is newline-separated `KEY=value`; `READY=1` transitions the unit `activating → active`; `$NOTIFY_SOCKET` is an `AF_UNIX` path; a leading `@` denotes an abstract socket and must be replaced with `\0`; the socket type is `SOCK_DGRAM`; when `NOTIFY_SOCKET` is unset the program must treat notification as a no-op.

### The D-08 health row (additive to `store.py` `_SCHEMA`)
```python
# Source: copies the single-row heartbeat pattern in store.py:129-135 (CHECK id=1 + INSERT OR IGNORE seed).
# Append to _SCHEMA:
"""
CREATE TABLE IF NOT EXISTS health (
    id            INTEGER PRIMARY KEY CHECK (id = 1),   -- single status row (D-08)
    reason        TEXT,                                  -- online | network_not_ready | auth_failed | key_propagating
    detail        TEXT,                                  -- outcome-only, NEVER a secret (T-04-01)
    updated_at_utc INTEGER
);
INSERT OR IGNORE INTO health (id, reason, detail, updated_at_utc) VALUES (1, NULL, NULL, NULL);
"""

# New helper, mirroring stamp_tick/stamp_success (store.py:383-412):
def stamp_health(db_path, reason: str, detail: str = "") -> None:
    """Upsert the single health row with the latest self-check outcome (D-08).
    Parameterized only (SQLi-safe, T-03-01); detail is outcome-only, never a secret."""
    now = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "UPDATE health SET reason=?, detail=?, updated_at_utc=? WHERE id=1",
            (reason, detail, now),
        )
        conn.commit()
```
A `read_health(db_path)` is **not** required this phase (the inbound `status` reader is deferred, D-08) but a trivial `SELECT reason, detail, updated_at_utc FROM health WHERE id=1` is the future seam.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `Type=forking` + PID file for daemons | `Type=notify` (or `Type=exec`) — the app signals readiness directly | systemd era (stable for years) | Cleaner readiness; the daemon must NOT self-fork (it already doesn't — `daemon.py:453`). |
| Hand-rolled `nohup`/`screen`/`@reboot` cron supervision | systemd `Restart=always` + `WantedBy=multi-user.target` | Long-standing | Reboot survival + backoff + journald for free. |
| `sdnotify`/`systemd-python` to send `READY=1` | ~10-line stdlib `socket` datagram | Always possible; now common guidance | Zero dependency; the wire protocol is trivial and stable. |

**Deprecated/outdated:** None relevant. systemd directives used here are stable across 247→255 (host is 255). `Type=notify-reload` (systemd 253+) is NOT needed (no live config reload this phase — ENH-V2-01 deferred).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The target deploy host runs systemd ≥ 247 and has the correct wait-online service enabled. | Standard Stack / Pitfall 4 | If the host lacks a wait-online service, `network-online.target` waits for nothing → first probe fails more often (mitigated by the re-probe loop anyway). The *research host* is systemd 255 with `NetworkManager-wait-online` enabled. |
| A2 | `sdnotify` (PyPI) and `systemd-python` are real packages but deliberately NOT installed. | Package Legitimacy Audit | None — they are rejected, not adopted. slopcheck/pip were unavailable; tagged [ASSUMED]. |
| A3 | The project is invoked via `uv run weatherbot` (or `.venv/bin/python -m weatherbot`); `weatherbot --run` is the daemon entry. | Pitfall 5 | If the real entry differs, the `ExecStart` line needs adjustment — flagged as a planner verification step. Confirmed `--run` branch exists at `cli.py:483-496`. |
| A4 | Exact `EnvironmentFile=` quote/parse behavior vs python-dotenv. | Pitfall 3 | A subtly-mis-parsed secret would surface as a 401 (looks like Pitfall 8). Mitigation: lowest-common-denominator `.env` format + post-install `systemctl show -p Environment` check. MEDIUM confidence on exact quoting. |

## Open Questions (RESOLVED)

1. **uv-run vs explicit venv interpreter in `ExecStart` (Pitfall 5 / A3).**
   - What we know: project is a uv project (CLAUDE.md); `weatherbot --run` is the daemon entry (`cli.py:483`).
   - What's unclear: whether a console script `weatherbot` is installed on PATH, or whether `python -m weatherbot` is the canonical invocation, on the target host.
   - Recommendation: planner adds a task to confirm the actual invocation, then pin an **absolute** `ExecStart` (prefer `/usr/bin/uv run weatherbot --run` with `WorkingDirectory=<repo>`, or `<repo>/.venv/bin/python -m weatherbot --run`).

2. **Should `key_propagating` be a distinct health reason, or folded into `auth_failed`?**
   - What we know: one 401/403 cannot distinguish a propagating new key from a permanently bad one (Pitfall 8).
   - What's unclear: product preference for the future `status` reader's vocabulary.
   - Recommendation: fold 401/403 into `auth_failed` (with the existing "may not be active or not yet propagated — wait" wording) and keep re-probing; treat `key_propagating` as optional sugar the planner may omit. Either is D-06-compliant.

3. **Re-probe interval default (D-04, Claude's discretion).**
   - What we know: 60–300s is the stated sensible band; same posture as Phase 4's discretion defaults.
   - Recommendation: 120s. Frequent enough that a propagating key / restored network recovers within ~2 min of becoming good; gentle enough it never approaches the OpenWeather 60/min limit. Document as a module constant, promotable to config later.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| systemd | OPS-01 supervision, `Type=notify`, `EnvironmentFile=` | ✓ (research host) | 255 (255.4-1ubuntu8.15) | None needed — chosen supervisor (D-01). On the *target* Pi, confirm systemd present (standard on Raspberry Pi OS / Ubuntu). |
| `NetworkManager-wait-online.service` | D-02 `network-online.target` actually waits | ✓ enabled (research host) | — | If target uses systemd-networkd instead, enable `systemd-networkd-wait-online.service` instead. Re-probe loop covers the gap regardless. |
| Python `socket`/`os` (stdlib) | sd_notify helper (D-05) | ✓ | 3.12+ | None needed (stdlib). |
| `uv` | `ExecStart=uv run …` (one ExecStart option) | assumed on target (CLAUDE.md stack) | 0.11.x | Use the explicit `.venv/bin/python -m weatherbot` ExecStart instead — no uv at runtime needed. |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** `uv`-at-runtime (fallback: explicit venv interpreter in `ExecStart`).

## Validation Architecture

> `nyquist_validation` config key not located (no `.planning/config.json` present in repo root scan); per the rule "absent = enabled", this section is included. The project already uses pytest (`pyproject.toml [tool.pytest.ini_options]`, `tests/`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x (+ `time-machine` for time control; both in `[dependency-groups].dev`) |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`) |
| Quick run command | `uv run pytest tests/test_daemon.py -x` (and the new `tests/test_ops_selfcheck.py` / `tests/test_sdnotify.py`) |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-02 | Self-check classifies a transient probe error as `network_not_ready` | unit | `uv run pytest tests/test_ops_selfcheck.py -k transient -x` | ❌ Wave 0 |
| OPS-02 | Self-check classifies a 401/403 as `auth_failed` | unit | `uv run pytest tests/test_ops_selfcheck.py -k auth -x` | ❌ Wave 0 |
| OPS-02 | Re-probe loop stays alive on failure and exits cleanly when `stop` is set | unit | `uv run pytest tests/test_daemon.py -k gate_stop -x` | ❌ Wave 0 (extend existing `test_daemon.py`) |
| OPS-02 | Online signal fires exactly once (log+stamp+ready+ping) on first pass; not re-fired | unit | `uv run pytest tests/test_daemon.py -k online_once -x` | ❌ Wave 0 |
| OPS-02 | `sd_notify` is a no-op when `NOTIFY_SOCKET` unset; sends `READY=1` when set (fake AF_UNIX socket) | unit | `uv run pytest tests/test_sdnotify.py -x` | ❌ Wave 0 |
| OPS-02 | `stamp_health` upserts the single `health` row with reason/detail (no secret) | unit | `uv run pytest tests/test_store.py -k health -x` | ❌ Wave 0 (extend existing store tests) |
| OPS-01 | systemd unit correctness (`Type=notify`, `Restart=always`, `After=/Wants=network-online.target`, no secrets) | manual + lint | `systemd-analyze verify deploy/weatherbot.service`; reboot UAT | manual-only (justified: real reboot survival can only be confirmed on the host) |

### Sampling Rate
- **Per task commit:** the matching quick-run command above.
- **Per wave merge:** `uv run pytest`.
- **Phase gate:** full suite green + `systemd-analyze verify deploy/weatherbot.service` clean + a real host reboot UAT (OPS-01 SC#1) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_ops_selfcheck.py` — classified self-check (transient / auth / pass), mocking the injected client to raise `httpx` errors / return ok. Covers OPS-02.
- [ ] `tests/test_sdnotify.py` — bind a throwaway `AF_UNIX`/`SOCK_DGRAM` socket, set `NOTIFY_SOCKET`, assert `READY=1` received; assert no-op + no error when unset. Covers OPS-02.
- [ ] Extend `tests/test_daemon.py` — re-probe loop stays alive + breaks on `stop.set()`; online-signal-once; SIGTERM-during-gate clean shutdown.
- [ ] Extend the store tests — `stamp_health` single-row upsert.
- [ ] `systemd-analyze verify deploy/weatherbot.service` as a non-pytest lint gate (the unit can't be unit-tested in CI but can be statically verified).
- *(No new framework install needed — pytest + time-machine already present.)*

## Security Domain

> `security_enforcement` config not located; per "absent = enabled", included. This phase introduces a systemd unit + a Discord "online" post + a DB health row — all touch secret-hygiene and input/least-privilege.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface added (single-user bot). |
| V3 Session Management | no | No sessions. |
| V4 Access Control | yes | systemd least-privilege: run as a non-root `User=`; `.env` and the unit must not be world-readable (`chmod 600` the `.env`, Pitfall 7). Optionally harden later with `ProtectSystem=`/`NoNewPrivileges=` (note only; not required for SC). |
| V5 Input Validation | yes | The OpenWeather probe response (and any `Retry-After`) is untrusted — already handled by Phase 4 classifiers; the health-row `detail` is outcome-only and parameterized (SQLi-safe). The Discord "online" text is a fixed literal (no user/template interpolation → no markdown-injection vector). |
| V6 Cryptography | no | No new crypto; secrets stay in `.env` (never hand-rolled storage). |

### Known Threat Patterns for systemd + Python daemon + Discord webhook

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret (`appid`/webhook URL) leaked into the unit file, journald log, or health-row column | Information Disclosure | `EnvironmentFile=.env` only (never inline `Environment=KEY=...` with the secret); outcome-only logging (T-04-01, already enforced); health row carries reason/detail (class names/status) only. `chmod 600 .env`. |
| `network-online.target` misread as "internet up" → false fatal on first probe | Denial of Service (self-inflicted) | Re-probe loop classifies transient/DNS as `network_not_ready` and waits (Pitfall 4). |
| `Type=notify` start-timeout → restart crash-loop | Denial of Service (self-inflicted) | `TimeoutStartSec=infinity` (Pitfall 1). |
| `WatchdogSec` without `WATCHDOG=1` → systemd kills a healthy bot | Denial of Service (self-inflicted) | Do not set `WatchdogSec` in v1 (Pitfall 6). |
| Discord "online" ping text carrying injectable markdown / mentions | Tampering | Fixed literal string, no `@everyone`/user interpolation (Pitfalls.md Discord row). |
| Running the daemon as root | Elevation of Privilege | `User=<non-root>` in the unit (V4). |

## Sources

### Primary (HIGH confidence)
- Local `systemd.service(5)` man page (host systemd **255**) — `Type=notify` semantics, `TimeoutStartSec` default + `EXTEND_TIMEOUT_USEC=`, `RestartSec=` default 100ms, `Restart=`. [VERIFIED via `zcat /usr/share/man/man5/systemd.service.5.gz`]
- Host `systemctl --version` → `systemd 255 (255.4-1ubuntu8.15)`; `systemctl is-enabled NetworkManager-wait-online.service` → enabled. [VERIFIED]
- https://systemd.io/NETWORK_ONLINE/ — `network-online.target` guarantees link/IP "has been reached", NOT DNS/internet; requires `Wants=`+`After=` together; the right wait-online service must be enabled.
- https://man7.org/linux/man-pages/man3/sd_notify.3.html + https://man.archlinux.org/man/sd_notify.3.en — `READY=1`, `$NOTIFY_SOCKET` AF_UNIX, abstract-socket `@`→`\0`, `SOCK_DGRAM`, no-op when unset, `WATCHDOG=1`.
- Codebase (read this session): `weatherbot/scheduler/daemon.py:439-511`, `weatherbot/cli.py:314-394` & `:483-496`, `weatherbot/weather/store.py` (`_SCHEMA`, single-row `heartbeat`, `stamp_tick`/`stamp_success`), `weatherbot/reliability/retry.py:80-99`, `weatherbot/channels/discord.py:50`, `pyproject.toml`. [VERIFIED]

### Secondary (MEDIUM confidence)
- https://oneuptime.com/blog/post/2026-03-02-how-to-use-systemd-type-notify-for-ready-signaling-on-ubuntu/view — Type=notify ready-signaling walkthrough (corroborates the man-page facts).
- systemd `EnvironmentFile=` parse semantics (systemd.exec(5)) — quote/`export`/comment handling differs from python-dotenv (exact quoting varies by version; host is 255). [MEDIUM]

### Tertiary (LOW confidence)
- `sdnotify` / `systemd-python` PyPI package existence — [ASSUMED], not installed/verified (pip unavailable); used only as rejected alternatives.

## Metadata

**Confidence breakdown:**
- Standard stack (systemd directives, stdlib sd_notify, zero new deps): HIGH — verified against the host's own systemd 255 man pages + freedesktop/man7 protocol docs.
- Architecture (where the gate/loop/online-signal wire into `run_daemon`, classifier reuse, health row): HIGH — read the exact functions/lines; all primitives already exist in the repo.
- Pitfalls (Type=notify timeout, SIGTERM ordering, network-online guarantee, EnvironmentFile parsing): HIGH except the EnvironmentFile quote-exactness (MEDIUM).

**Research date:** 2026-06-11
**Valid until:** ~2026-09-11 (systemd directives are stable; re-verify only if the target host's systemd is < 247 or uses a non-standard network stack).
