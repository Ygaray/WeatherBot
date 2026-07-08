# Phase 29: Startup Validation & Honest Alerting - Research

**Researched:** 2026-07-07
**Domain:** Python always-on daemon startup lifecycle — offline config/template validation, self-check classification, systemd supervision, cross-repo (hub) extension-point reuse
**Confidence:** HIGH (all findings grounded in actual `file:line`; systemd interaction verified against `systemd.service(5)`)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** On a **permanent** config/template/empty-locations error, the daemon **alerts then exits non-zero** — no warn-loop, no inert stay-alive. Introduce a distinct fatal reason (e.g. `CONFIG_INVALID`) separate from `NETWORK_NOT_READY` / `AUTH_FAILED`.
- **D-02:** Stamp the durable health row with the fatal reason **before** exiting, so a later `!status` (after a systemd restart) reads the fatal reason from the DB.
- **D-03:** `AUTH_FAILED` (401/403) behavior **unchanged** — keeps re-probing (one 401/403 cannot distinguish a permanently-bad key from a still-propagating one, ~2h activation, D-06). ONLY config/template/empty-locations become fatal.
- **D-04:** Fatal Discord alert is **best-effort, once per process boot**. Bound restart churn at the **systemd layer**, not with new app-side persistence.
- **D-05:** REQUIRES `deploy/weatherbot.service` change: `Restart=always` → `Restart=on-failure` + `StartLimitIntervalSec` + `StartLimitBurst` in `[Unit]` so a fatal-exit config error trips the start-limit and parks the unit `failed`. **Keep `TimeoutStartSec=infinity`** (line 27) — the transient slow-key re-probe stays alive/never exits. Fatal path exits; transient path does not.
- **D-06:** Unit change is in-repo but live effect needs redeploy + `systemctl daemon-reload` on `yahir-mint` → **deferred Gate-2 obligation**.
- **D-07:** `run()` calls the full offline `validate_config_and_templates(args.config)` **before** `run_daemon` — the same validator `check-config`/reload use, zero network, fail-fast. **PRIMARY** fatal mechanism, fully app-side (runs before the ReadyGate).
- **D-08:** On boot-gate failure, build the channel best-effort from `settings`, fire the fatal operator alert (D-01/D-04), then exit non-zero. Threads STARTUP-01 detection into STARTUP-02 fatal handling — one code path.
- **D-09:** The live readiness loop is the **hub's** `ReadyGate.run(stop)` — it has **no fatal path** (every non-ok re-probes forever; only branches log level on severity). Changing it is a human-gated hub tag-cut → out of scope to ship autonomously here.
- **D-10 (A + hub handoff):** Ship app-side fatal-stop now AND log the hub enhancement for later:
  - **App-side (Phase 29):** fix `selfcheck.py` classification to return the fatal reason at CRITICAL severity, AND make the app-injected `on_fail` hook, on a fatal result, **set the `stop` Event + a fatal marker + fire the alert**. After `ready_gate.run()` returns `False`, the composition root distinguishes fatal (marker set → exit non-zero) from clean SIGTERM (marker unset → exit 0). Uses the hub's **existing** extension points (`on_fail` hook + `stop` Event) → **no hub change**.
  - **Hub handoff (deferred, human-gated):** first-class "fatal outcome" in `ReadyGate.run` → `.planning/HUB-FINDINGS-HANDOFF.md`.
- **D-11:** Fix **F90** — `_announce_schedule` (`daemon.py:1042`) must iterate forecast slots too, so the boot schedule log shows every scheduled job (briefing + forecast) with `next_run_time`; a disabled/misconfigured forecast slot must be visible.
- **D-12:** Fix **F07** — move the one-time Discord online-ping to **after** `notifier.ready()` (`READY=1`) so a slow/hung webhook can't block systemd readiness past `TimeoutStartSec`.
- **D-13:** Fold **F89** — prune `_forecast_failure_streaks` (`daemon.py:392`) dead entries on config reload.

### Claude's Discretion

- Exact fatal reason constant name (`CONFIG_INVALID` vs similar).
- Concrete `StartLimitIntervalSec` / `StartLimitBurst` values.
- Fatal-marker plumbing shape.
- Whether `wait_ready_gate`/`gate_until_healthy` (`daemon.py:1108-1156`) is dead app-side code superseded by `ready_gate.run()` (line 1465): confirm during planning; if dead, removing it is in-scope cleanup (same file, already open).

### Deferred Ideas (OUT OF SCOPE)

- **Hub `ReadyGate` first-class fatal outcome** — human-gated hub tag cut; log to `.planning/HUB-FINDINGS-HANDOFF.md`; NOT built in Phase 29.
- **Gate-2 (live host) obligation** — the `deploy/weatherbot.service` restart-policy change (D-05) only takes effect after redeploy + `daemon-reload` on `yahir-mint`; batched to milestone-close human UAT.
- Other v2.1 findings stay in Phases 30–35 (except F89, folded per D-13).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-STARTUP-01 | `run` boot runs the same `assert_unique_names` + template validation `check-config`/reload enforce; a duplicate id or typo'd template fails loudly at boot instead of booting green (F05, `cli.py:986`). | §"The Shared Offline Validator" — `validate_config_and_templates(path)` already exists (`config/loader.py:99`); `run()` at `cli.py:986` currently uses the thinner `_load_config_reporting`→`load_config` (schema-only). Fix = call the full validator in `run()` before `run_daemon`, catch the SAME 4-exception set `check-config` catches (`cli.py:968-973`), and on failure route into the fatal path (HARD-STARTUP-02). |
| HARD-STARTUP-02 | Permanent config/template errors classified fatal (not `NETWORK_NOT_READY`) so the daemon surfaces/alerts instead of warn-looping forever (F06, `selfcheck.py:116`). | §"Self-check Classification" — add fatal reason `CONFIG_INVALID`, split the `selfcheck.py:116` catch-all so config/template/empty-locations map to it, and map it to `Severity.CRITICAL` in `to_health_result`. §"Fatal-stop via existing hub extension points" — `on_fail` hook detects the fatal `HealthResult`, sets `stop` + fatal marker + fires the alert. |
| HARD-STARTUP-03 | Config→runtime startup ordering/logging divergences corrected (F90 announce-omits-forecast, F07 ping-before-READY). | §"F90 Schedule Announcement", §"F07 Online-Ping Ordering", §"F89 Streak-Dict Pruning". |
</phase_requirements>

## Summary

This is a **well-specified backend/daemon phase**: CONTEXT.md locks the WHAT and most of the HOW across 13 decisions. Research confirms every referenced code site and closes the three discretion gaps (fatal reason name, systemd values, marker plumbing).

The pivotal architectural insight — already implied by D-07 — is that there are **two independent fatal-detection layers, and the offline validator is the primary one**. `validate_config_and_templates` (`config/loader.py:99`) runs *before* the ReadyGate and *before* any network, so **every realistic permanent-config case is caught there**, entirely app-side, with zero hub involvement (HARD-STARTUP-01). The `selfcheck.py` classification fix (HARD-STARTUP-02) is the **defense-in-depth second layer**: it only matters for a config/template error that somehow slips past the boot validator (e.g. an empty-locations edge, or a template file deleted between boot-validate and first probe). Both layers converge on **one fatal code path**: alert (best-effort, once) → stamp health → exit non-zero. systemd's `Restart=on-failure` + start-limit converts the non-zero exit into a loud, parked `failed` unit instead of an infinite crash-loop.

The `on_fail`/`stop`-Event overload (D-10 app-side) is confirmed to need **NO hub change**: `ReadyGate.run(stop)` (`ready_gate.py:72`) already fires `on_fail(result)` on every failing probe and already returns `False` when `stop` is set. The app injects a marker into that hook and reads it after `run()` returns.

**Primary recommendation:** Land the offline boot-validator in `run()` (`cli.py:986`) as the primary fatal gate wired into a single `_fatal_config_exit(settings, reason, detail)` helper that alerts→stamps→returns non-zero; add `CONFIG_INVALID` (→ `Severity.CRITICAL`) as the defense-in-depth selfcheck classification feeding the same helper via the `on_fail` hook + fatal marker; change `deploy/weatherbot.service` to `Restart=on-failure` + `StartLimitIntervalSec=300` / `StartLimitBurst=5` in `[Unit]` (keep `TimeoutStartSec=infinity`); and land the three STARTUP-03 corrections (F90 announce forecast slots, F07 ping-after-READY, F89 prune streaks on reload). Confirm and remove dead `gate_until_healthy` (`daemon.py:1108`).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Offline config/template validation | App (`config/loader.py`) | — | `validate_config_and_templates` is app-owned domain logic (weather templates, location schema); zero network, no hub. PRIMARY fatal gate (D-07). |
| Self-check outcome classification | App (`ops/selfcheck.py`) | — | App owns classification; hub stays weather-noun-free. Reason→`Severity` map is the boundary seam. |
| Re-probe loop / `READY=1` emit | Hub (`ReadyGate.run`) | — | Reusable lifecycle mechanism. Phase 29 uses it **unchanged** via existing hooks (D-09). |
| Fatal detection → alert → exit | App (composition root + `on_fail` hook) | Hub (`stop` Event + `on_fail` hook as passthrough carriers) | App overloads the hub's existing extension points; no hub change (D-10). |
| Restart-churn bounding | OS / systemd (`weatherbot.service`) | — | D-04/D-05 chose OS-layer bounding over app-side persistence. |
| Boot schedule announcement (F90) | App (`daemon.py:_announce_schedule`) | — | App-owned observability over app job model (briefing + forecast slots). |
| Online-ping ordering (F07) | App (`wiring.py:_on_online`) | Hub (`ReadyGate` calls `_on_online` then `notifier.ready()`) | The ordering bug is in the app hook body; the fix moves the ping out of the pre-READY hook. |
| Streak-dict pruning (F89) | App (`daemon.py` + `wiring.py:_on_applied`) | — | App-owned in-process state; pruned on the app's reload-applied hook. |

## Standard Stack

No new packages. Phase 29 is pure app-side + systemd-unit editing over the **already-installed** stack. Confirmed present in `pyproject.toml`:

| Library | Version (installed) | Purpose in this phase | Why Standard |
|---------|---------|---------|--------------|
| APScheduler | 3.11.x | `scheduler.get_jobs()` / `next_run_time` in `_announce_schedule` | Already the scheduler spine (`daemon.py`). |
| structlog | 26.x | Outcome-only fatal/critical logging (`_log.critical`) | Established logging pattern; never echoes secrets (T-04-01). |
| pydantic | 2.13.x | `ValidationError` is one of the 4 caught boot-validate exceptions | Already the config-model validator. |
| yahir_reusable_bot | tag `v0.1.1` (pinned) | `ReadyGate`, `HealthResult`, `Severity`, `ReloadEngine` — **consumed unchanged** | The hub; Phase 29 touches NONE of its source (D-09/D-10). |
| pytest | 9.0.3 | Unit + subprocess integration tests | `[tool.pytest.ini_options] testpaths=["tests"]`. |

**Installation:** none — `uv sync --frozen` already provisions everything. No `uv add` in this phase.

## Package Legitimacy Audit

> Not applicable — Phase 29 installs **no external packages**. All code sits on the already-pinned dependency set (`pyproject.toml` + `uv.lock`, hub at tag `v0.1.1`). No registry lookups performed; no new supply-chain surface introduced.

## Architecture Patterns

### System Architecture Diagram — the two fatal layers + one exit path

```
weatherbot run  (cli.py:986)
   │
   ├─ (1) load_settings()                         [existing]
   │
   ├─ (2) validate_config_and_templates(config)   ★ NEW: PRIMARY offline fatal gate (D-07, HARD-STARTUP-01)
   │        │  raises → FileNotFoundError | TOMLDecodeError | ValidationError | ValueError
   │        │
   │        └── on raise ──► _fatal_config_exit(settings, CONFIG_INVALID, detail)  ─────┐
   │                             ├─ best-effort build channel from settings            │
   │                             ├─ channel.send(fatal alert)   (best-effort, once)    │  ONE
   │                             ├─ stamp_health(db, reason=CONFIG_INVALID, detail)     │  FATAL
   │                             └─ return non-zero (e.g. 1)                            │  PATH
   │                                                                                    │
   └─ (2 passes) ─► run_daemon(config, settings, db_path, config_path)                  │
          │                                                                             │
          │  build_runtime → ReadyGate(_health_check, notifier,                         │
          │                            on_fail=_on_fail, on_online=_on_online)          │
          │                                                                             │
          └─ ready_gate.run(stop)         [HUB, unchanged — ready_gate.py:72]           │
                │  loop: result = _health_check()  (→ run_self_check → to_health_result)│
                │     result.ok  ──► on_online → scheduler.start → notifier.ready()      │
                │                                  → (F07 fix) online ping AFTER ready() │
                │     not ok:                                                            │
                │       on_fail(result)   [APP hook, wiring.py:280]                      │
                │         ├─ stamp_health(reason, detail)          [existing]            │
                │         └─ ★ if result.severity == CRITICAL and reason == CONFIG_INVALID:
                │              set fatal_marker ; stop.set() ; _fatal_config_exit(...) ──┤ (2nd layer,
                │       severity==WARNING → re-probe (AUTH_FAILED / NETWORK_NOT_READY)   │  defense-in-depth)
                │                                                                        │
                └─ returns False (stop set)                                             │
                     │                                                                  │
   run_daemon: after run() returns False ──► ★ if fatal_marker: return non-zero ◄───────┘
                                             else (clean SIGTERM): return 0  [existing 1466]
```

**Read the diagram:** the ★ items are the Phase-29 additions. Layer (2) — the offline validator — is where **every realistic case lands**. The `on_fail` layer is the belt-and-suspenders path for a config/template fault that only surfaces at probe time.

### Pattern 1: Reuse the exact `check-config` catch set for the boot validator (HARD-STARTUP-01)

**What:** `run()` must catch the SAME four exceptions `check-config` already catches so "a config `run` accepts == a config `check-config` accepts."
**When:** wrapping `validate_config_and_templates(args.config)` in `run()`.
**Example (the canonical catch set, lifted from `cli.py:966-975`):**
```python
# Source: weatherbot/cli.py:966-977 (check-config path) + config/loader.py:99-120 docstring
from weatherbot.config.loader import validate_config_and_templates
try:
    config = validate_config_and_templates(args.config)
except (
    FileNotFoundError,        # missing config OR missing template file
    tomllib.TOMLDecodeError,  # malformed TOML
    ValidationError,          # pydantic: missing/invalid field
    ValueError,               # duplicate name/id OR unknown template {token}
) as exc:
    # single fatal path (D-08): alert (best-effort, once) → stamp → exit non-zero
    return _fatal_config_exit(settings, reason=CONFIG_INVALID, detail=type(exc).__name__)
```
[VERIFIED: weatherbot/cli.py:966-977, weatherbot/config/loader.py:99-120] — the validator already exists and already propagates exactly these four; `check-config` (via `ReloadEngine.check` → `validate`) catches exactly these four. `run()` today only calls `_load_config_reporting` → `load_config` (schema-only; NO `assert_unique_names`, NO template-token check).

### Pattern 2: `CONFIG_INVALID` fatal reason + CRITICAL severity map (HARD-STARTUP-02)

**What:** a new reason constant alongside `PASS`/`NETWORK_NOT_READY`/`AUTH_FAILED` (`selfcheck.py:44-46`), mapped to `Severity.CRITICAL`, and produced by classifying the permanent-error branch that today falls into the `except Exception` catch-all (`selfcheck.py:116`).
**When:** in `run_self_check` and `to_health_result`.
**Example:**
```python
# Source: weatherbot/ops/selfcheck.py:44-46 (add), :116-122 (split), :127-145 (map)
CONFIG_INVALID = "config_invalid"   # NEW — permanent, fatal (D-01)

# In run_self_check, BEFORE the network probe, the config/template/empty-locations
# checks (lines 80-91) already run. Wrap THOSE in a branch that returns CONFIG_INVALID
# rather than letting a later broad `except Exception` mislabel them NETWORK_NOT_READY:
try:
    if not config.locations:
        raise ValueError("No locations configured in config.toml")
    validate_template(load_template(config.template))
    assert_unique_names(config)
    for loc in config.locations:
        resolve_location(config, loc.name)
except (ValueError, FileNotFoundError) as exc:   # permanent config/template/empty-loc
    return CheckResult(ok=False, reason=CONFIG_INVALID, detail=type(exc).__name__)
# ... network probe below stays NETWORK_NOT_READY / AUTH_FAILED as today ...

# to_health_result: fatal + auth both map CRITICAL; only network is WARNING.
severity = (
    Severity.CRITICAL
    if result.reason in (AUTH_FAILED, CONFIG_INVALID)
    else Severity.WARNING
)
```
[VERIFIED: weatherbot/ops/selfcheck.py:44-46, 80-124, 127-145] — the pre-probe config checks already exist at 80-91; they currently share the single broad `except Exception` at 116 that returns `NETWORK_NOT_READY`. `to_health_result` at 139 today is `CRITICAL iff AUTH_FAILED else WARNING`.

> **Note on `detail`:** keep it outcome-only — a status code or exception class name, NEVER the exception message (which could echo a path or, in adjacent flows, a secret). Existing contract at `selfcheck.py:16-17, 55-56` (T-04-01). Use `type(exc).__name__`, not `str(exc)`.

### Pattern 3: Fatal-stop via existing hub extension points — NO hub change (D-10)

**What:** the app's injected `on_fail` hook (`wiring.py:280`) already receives every failing `HealthResult`. On a `CONFIG_INVALID`/CRITICAL result it sets a fatal marker + `stop.set()` + fires the alert. `ReadyGate.run` then breaks (its `stop.is_set()` guard / `stop.wait` return) and returns `False`. The composition root reads the marker after `run()` returns.
**When:** only reachable if a config/template error slips past the boot validator (defense-in-depth).
**Example (marker plumbing — recommended shape):**
```python
# Source: hub ready_gate.py:72-119 (run loop, on_fail fires per failing probe, returns
# False when stop set) — UNCHANGED. App side in wiring.py / daemon.py:

# Recommended marker: a tiny mutable carrier the hook writes and the root reads.
# A one-field dataclass or a threading.Event both work; an Event double-serves as a
# boolean AND is the natural "fatal happened" flag. Prefer a dedicated
# `fatal = threading.Event()` (do NOT reuse `stop` as the fatal signal — `stop` is also
# set by a clean SIGTERM, so overloading it loses the fatal/clean distinction D-10 needs).

def _on_fail(result) -> None:
    daemon.stamp_health(db_path, reason=result.reason, detail=result.detail)
    if result.severity >= Severity.CRITICAL and result.reason == daemon.CONFIG_INVALID:
        fatal.set()                       # ★ fatal marker (separate from stop)
        _fatal_config_exit_alert(...)     # ★ best-effort, once (D-04)
        stop.set()                        # ★ break the hub re-probe loop
    elif result.reason == daemon.AUTH_FAILED:
        daemon._log.critical("startup self-check auth failure", ...)   # existing
    else:
        daemon._log.warning("startup self-check not ready", ...)        # existing

# In run_daemon, replace the bare `return 0` at the gate-stop branch (daemon.py:1465-1466):
if not ready_gate.run(stop):
    if fatal.is_set():          # ★ fatal → non-zero (systemd on-failure restarts → start-limit)
        return 1
    return 0                    # clean SIGTERM (marker unset) → success, no restart
```
[VERIFIED: yahir_reusable_bot/lifecycle/ready_gate.py:72-119, weatherbot/scheduler/wiring.py:280-321, weatherbot/scheduler/daemon.py:1465-1466] — `on_fail` fires on every failing probe (ready_gate.py:101); `run` returns `False` on stop (ready_gate.py:119); the composition root already branches on `run()`'s return at 1465. `fatal` must be threaded from `build_runtime`/`RuntimeParts` back to `run_daemon` alongside `stop` (both live on `parts`).

**Marker plumbing decision (discretion resolved):** thread a dedicated `fatal: threading.Event` through `RuntimeParts` (wiring.py:323-337) next to the existing `stop`. Rationale: (a) `threading.Event` is already the idiom for `stop`; (b) it is cheap, thread-safe, and needs no new type; (c) keeping it **separate from `stop`** preserves the fatal-vs-clean-SIGTERM distinction that D-10's exit-code logic depends on — reusing `stop` would collapse the two. The hub half of D-10 (a first-class fatal return) later replaces this overload; until then the separate Event is the minimal, reversible hack.

### Pattern 4: F90 — announce forecast slots too, INCLUDING disabled ones

**What:** `_announce_schedule` (`daemon.py:1042`) iterates only `location.schedule` (briefing slots), and even `continue`s past disabled briefing slots. F90's point: a **disabled/misconfigured forecast slot must be VISIBLE** at boot. So the fix should log forecast slots AND surface disabled ones (with a `next_run_time=None`/`enabled=False` note) rather than silently skipping — that is the observability the finding demands.
**Example:**
```python
# Source: weatherbot/scheduler/daemon.py:1044-1063 (briefing loop) + :556-571 (_forecast_job_id)
for location in config.locations:
    tz = ZoneInfo(location.timezone)
    # briefing slots — existing loop (keep), but log disabled ones instead of `continue`
    for slot in location.schedule:
        job = by_id.get(f"{location.name}|{slot.time}|{slot.days}")
        next_run = _next_or_none(job, tz)
        _log.info("scheduled slot", location=location.name, kind="briefing",
                  time=slot.time, days=slot.days, enabled=slot.enabled,
                  next_run_time=str(next_run))
    # ★ NEW: forecast slots — same treatment, keyed by the SINGLE source _forecast_job_id
    for fc in location.forecast:
        job = by_id.get(daemon._forecast_job_id(location, fc))
        next_run = _next_or_none(job, tz)
        _log.info("scheduled slot", location=location.name, kind=f"forecast:{fc.kind}",
                  variant=fc.variant, time=fc.time, days=fc.days, enabled=fc.enabled,
                  next_run_time=str(next_run))
```
[VERIFIED: daemon.py:1042-1063 announce loop, daemon.py:556-571 `_forecast_job_id`, config/models.py:88-116 `ForecastSchedule` fields `kind/variant/time/days/enabled`] — a disabled slot has NO registered job (`_desired_job_ids` filters `if fc.enabled`, daemon.py:707-712), so `by_id.get(...)` returns `None` → `next_run_time=None` — which is exactly the visible "this slot is off" signal F90 wants. Use the SHARED `_forecast_job_id` so announce and register never drift.

### Pattern 5: F07 — move the online ping AFTER `notifier.ready()`

**What:** the one-time Discord ping currently lives INSIDE `_on_online` (`wiring.py:305-313`), which `ReadyGate.run` invokes BEFORE `notifier.ready()` (ready_gate.py:96-98). A slow/hung webhook therefore delays `READY=1` and, past `TimeoutStartSec`, systemd could kill startup. `TimeoutStartSec=infinity` currently masks this, but the ordering is still wrong (and D-05 keeps `infinity` only for the transient path).
**Constraint:** `ReadyGate` (hub) owns the `on_online`-then-`ready()` order and is unchanged (D-09). So the app must move the ping to fire AFTER `run()` has emitted READY — i.e. out of `_on_online` and into the composition root immediately after `ready_gate.run(stop)` returns `True` (before/around the "daemon started" log at daemon.py:1468).
**Example:**
```python
# Source: hub ready_gate.py:96-98 (on_online BEFORE notifier.ready()), wiring.py:300-313,
#         daemon.py:1465-1468 (post-gate, READY already emitted)
# _on_online KEEPS: scheduler.start(), stamp_health("online"), stamp_tick(), online log.
# ★ REMOVE the channel.send(...) online ping from _on_online.
# ★ ADD it in run_daemon AFTER the gate returns True (READY=1 already sent by the hub):
if not ready_gate.run(stop):
    if fatal.is_set(): return 1
    return 0
_log.info("daemon started", jobs=len(scheduler.get_jobs()))
if channel is not None:                       # ★ online ping now strictly AFTER READY=1
    _post_online_ping(channel)                # best-effort; a hang here no longer gates READY
```
[VERIFIED: yahir_reusable_bot/lifecycle/ready_gate.py:96-98 (`_best_effort_hook(on_online...)` then `notifier.ready()`), weatherbot/scheduler/wiring.py:300-313, weatherbot/scheduler/daemon.py:1465-1468] — moving only the ping preserves the golden-sensitive `scheduler.start()`-before-`READY` invariant (that stays in `_on_online`); only the non-critical ping relocates past READY.

### Pattern 6: F89 — prune `_forecast_failure_streaks` on reload

**What:** `_forecast_failure_streaks` (`daemon.py:392`) is keyed by `_forecast_job_id` (NOT bare `location.name` — the finding text says name but the code at :412-414 keys by `_forecast_job_id(location, fc)`). It is popped only by `_note_forecast_success` (:440), which never fires for a removed/renamed slot → dead entries leak across reloads.
**When:** on every applied reload — the natural seam is `_on_applied` (`wiring.py:209`), which already runs committed-success side effects (post outcome, invalidate cache, re-derive watch dirs).
**Example:**
```python
# Source: daemon.py:392,412-414,440 (dict + keying), daemon.py:695-713 (_desired_job_ids),
#         wiring.py:209-228 (_on_applied committed-success hook)
def _prune_forecast_streaks(holder) -> None:
    """Drop streak entries for forecast job-ids no longer desired (F89)."""
    live_ids = daemon._desired_job_ids(holder)          # briefing|forecast ids for current cfg
    for dead in set(daemon._forecast_failure_streaks) - live_ids:
        daemon._forecast_failure_streaks.pop(dead, None)

# call inside _on_applied (wiring.py), best-effort like its siblings:
try:
    _prune_forecast_streaks(holder)
except Exception:  # noqa: BLE001 — best-effort; reload already committed
    daemon._log.warning("forecast streak prune failed; reload unaffected")
```
[VERIFIED: daemon.py:392,412-414,440 (dict keyed by `_forecast_job_id`), daemon.py:695-713 (`_desired_job_ids` produces `briefing_ids | forecast_ids`), wiring.py:209-228 (`_on_applied`)] — `_desired_job_ids` is the authoritative "what should exist now" set; intersecting the streak keys against it drops exactly the renamed/removed slots. `_forecast_job_id` is the single source both use, so keys match byte-for-byte.

> **Keying caveat for the planner:** `_desired_job_ids` returns briefing IDs (`name|time|days`) *and* forecast IDs (`name|fc|kind|variant|time|days`). The streak dict only ever holds forecast IDs. Set-difference `streak_keys - desired_ids` is safe (briefing IDs never appear in the streak dict, so they can't cause a spurious retention), but a reviewer may prefer restricting `live_ids` to the forecast subset for clarity — either is correct.

### Anti-Patterns to Avoid

- **Reusing `stop` as the fatal marker.** `stop` is set by both a clean SIGTERM and the fatal path; overloading it destroys the exit-code distinction D-10 requires. Use a separate `fatal` Event.
- **Echoing `str(exc)` in the fatal `detail`/alert.** Config errors can contain file paths; keep `detail=type(exc).__name__` (T-04-01 clean-failure contract, selfcheck.py:16-17).
- **`time.sleep` anywhere in the new wait/exit paths.** All waits must stay `stop.wait(...)` so `systemctl stop` breaks promptly (Pitfall 2, enforced across daemon.py/ready_gate.py).
- **Making `AUTH_FAILED` fatal.** Explicitly forbidden (D-03) — one 401/403 can't distinguish a bad key from a propagating one.
- **Editing hub source** (`ready_gate.py`, `reload.py`, `health.py`). Out of scope (D-09); the first-class fatal outcome is a deferred, human-gated hub tag → `HUB-FINDINGS-HANDOFF.md`.
- **`continue`-skipping disabled forecast slots in the announce log.** That reproduces F90 for forecasts — log them with `enabled=False`/`next_run_time=None` so they're visible.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Offline config+template validation in `run()` | A second bespoke validator | `validate_config_and_templates(path)` (loader.py:99) | It IS the shared validator `check-config`/reload use; a second copy would drift (the exact bug class F05 represents). |
| The re-probe loop / READY emit | A new app gate | Hub `ReadyGate.run(stop)` (unchanged) | Already the live path; `gate_until_healthy` (daemon.py:1108) is the DEAD hand-rolled copy — remove it. |
| Restart-churn / alert-spam bounding | App-side DB cooldown (`record_alert`) | systemd `Restart=on-failure` + `StartLimit*` | D-04/D-05 chose OS-layer bounding; the alert spine exists but is deliberately NOT used here. |
| Fatal signalling from probe loop | New hub callback | Existing `on_fail` hook + a `threading.Event` marker | The hook already carries the `HealthResult`; the app only adds a marker read. No hub change. |
| Forecast job-id derivation in announce/prune | A recomputed id string | `_forecast_job_id(location, fc)` (daemon.py:556) | Single source of truth shared by register/desired — recomputing invites drift. |

**Key insight:** almost everything this phase needs already exists as a shared, tested primitive; the defects are *omissions of reuse* (F05 skips the validator, `gate_until_healthy` is a dead duplicate of `ReadyGate`, F90 forgot forecast slots). The correct fix is consistently "call the existing thing," not "write a new thing."

## Runtime State Inventory

> Phase 29 edits code + one systemd unit — not a rename/migration. But because it changes durable-health semantics and a systemd unit, this table is included for the non-code state it touches.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `health` single-row table (`weather/store.py:468 stamp_health`) — Phase 29 writes a NEW reason value `CONFIG_INVALID` into the existing `reason` column (D-02). No schema change (reason is a free-text string column). | Code edit only — add the constant + stamp it on the fatal path. No migration; existing rows/readers tolerate a new string value. |
| Live service config | `deploy/weatherbot.service` on host `yahir-mint` (live editable-installed daemon). The `Restart=`/`StartLimit*` change lives in the repo file but the RUNNING unit is the installed copy. | In-repo edit now; live effect = redeploy + `systemctl daemon-reload` → **deferred Gate-2 obligation** (D-06). Do NOT ship autonomously. |
| OS-registered state | The systemd unit itself is the only OS registration. `StartLimitIntervalSec`/`StartLimitBurst` change how systemd's start-limit counter parks the unit. | Covered by the Gate-2 redeploy above. |
| Secrets/env vars | None renamed/changed. `OPENWEATHER_API_KEY` / `DISCORD_WEBHOOK_URL` read via `.env`/`EnvironmentFile` unchanged. The fatal alert path builds a channel from `settings` (best-effort) — reads the same secret, adds nothing. | None. |
| Build artifacts | None. No package rename, no `pyproject` change, no egg-info. Hub stays pinned at `v0.1.1`. | None. |

**Nothing found in "Secrets/env vars" and "Build artifacts":** verified — no rename, no dependency change, hub untouched.

## Common Pitfalls

### Pitfall 1: `Restart=on-failure` treats a bare SIGTERM as a failure — but a *requested* stop is exempt
**What goes wrong:** naively, `Restart=on-failure` restarts on any signal-kill including SIGTERM (exit 143), which could make a clean `systemctl stop` restart-loop.
**Why it happens:** the default "clean" set for `on-failure` is exit 0 + SIGHUP/SIGINT/SIGTERM/SIGPIPE, AND — critically — **systemd exempts any death caused by systemd's own operation (a requested stop/restart) from restart logic entirely.**
**How to avoid:** rely on the requested-stop exemption. A clean `systemctl stop` → SIGTERM → daemon returns 0 (marker unset) → NOT restarted, start-limit NOT tripped. A fatal config error → the daemon *itself* returns **non-zero** (marker set) → `on-failure` restarts → same error → start-limit trips → unit parks `failed`. The two are distinguished by the daemon's own exit code, which is exactly why the fatal path MUST `return 1` (not just `stop.set()`).
[CITED: man7.org/linux/man-pages/man5/systemd.service.5 — "When the death of the process is a result of systemd operation (e.g. service stop or restart), the service will not be restarted."]

### Pitfall 2: `TimeoutStartSec=infinity` vs `Restart=on-failure` — they do NOT conflict
**What goes wrong:** fear that changing `Restart=always`→`on-failure` while keeping `TimeoutStartSec=infinity` breaks something.
**Why it happens:** conflating "start timeout" (how long systemd waits for `READY=1`) with "restart policy" (what happens when the process EXITS).
**How to avoid:** they're orthogonal. The transient slow-key path **never exits** — it re-probes forever inside `ReadyGate.run`, so `Restart=on-failure` never fires for it, and `TimeoutStartSec=infinity` keeps systemd from killing the still-not-READY process. The fatal path **exits non-zero** — `on-failure` fires, start-limit trips. Keep `TimeoutStartSec=infinity` (line 27); it only governs the never-exiting transient path.

### Pitfall 3: `StartLimitIntervalSec`/`StartLimitBurst` must be in `[Unit]`, not `[Service]`
**What goes wrong:** placing them in `[Service]` yields `Unknown lvalue 'StartLimitIntervalSec' in section 'Service'` and the directive is silently ignored → no start-limit → infinite crash-loop persists.
**Why it happens:** start-rate-limiting is a *unit*-level concept; it moved to `[Unit]` in modern systemd.
**How to avoid:** put both in `[Unit]` (where `Wants=`/`After=` already are, weatherbot.service:13-18). `Restart=` and `RestartSec=`/`TimeoutStartSec=` stay in `[Service]`.
[CITED: support.hashicorp.com "Unknown lvalue StartLimitIntervalSec in section Service"; freedesktop.org systemd.unit(5)]

### Pitfall 4: The offline validator catches config errors; the selfcheck fix is defense-in-depth, not the primary gate
**What goes wrong:** planning the selfcheck classification (HARD-STARTUP-02) as THE fix and under-implementing the boot validator (HARD-STARTUP-01).
**Why it happens:** F06 is described vividly (warn-loop forever), so it feels central.
**How to avoid:** remember ordering — `validate_config_and_templates` runs BEFORE `run_daemon`/`ReadyGate` (D-07), so it catches every realistic permanent-config case first. Both success criteria 1 and 2 route through the SAME `_fatal_config_exit` helper (D-08). Test BOTH layers, but treat the boot validator as primary.

### Pitfall 5: `emit_online` is ALSO dead — but it belongs to F16/Phase 35, not Phase 29
**What goes wrong:** while removing dead `gate_until_healthy`, also deleting `emit_online` and `_do_reload` (they're dead too — F16 groups all three).
**Why it happens:** they're in the same file, obviously dead post-refactor.
**How to avoid:** CONTEXT.md's discretion item scopes ONLY `gate_until_healthy`/`wait_ready_gate` to Phase 29 ("same file, already open"). `emit_online` + `_do_reload` are formally **F16 → Phase 35 (Cleanup Sweep)**. Recommend the planner remove `gate_until_healthy` here (it's the direct dead twin of the `ReadyGate` this phase reasons about) and leave `emit_online`/`_do_reload` for Phase 35 — OR consciously fold all three and note it, to avoid a half-cleanup. Do NOT silently expand scope. (`wait_ready_gate` does not exist in the code — only `gate_until_healthy` at daemon.py:1108; the CONTEXT name is an alias.)

## Code Examples

See Patterns 1–6 above — each carries a verified `Source:` line-cite and the concrete edit shape. The three discretion answers are consolidated here:

### Discretion answer 1 — fatal reason constant name: `CONFIG_INVALID`
```python
# weatherbot/ops/selfcheck.py:44-46 — add alongside the existing trio
CONFIG_INVALID = "config_invalid"
```
Rationale: matches CONTEXT.md's own suggested name (D-01), mirrors the existing lowercase-string convention (`PASS="online"`, `NETWORK_NOT_READY="network_not_ready"`, `AUTH_FAILED="auth_failed"`), and reads clearly in a stamped health row / `!status` output. Export it from `weatherbot.ops` (the `__init__` already re-exports `AUTH_FAILED`/`NETWORK_NOT_READY`/`PASS`, per test_ops_selfcheck.py:16-22) and alias it onto the `daemon` module namespace like `AUTH_FAILED` is (daemon.py imports it) so `wiring.py:_on_fail` can compare `result.reason == daemon.CONFIG_INVALID`.

### Discretion answer 2 — systemd start-limit values: `StartLimitIntervalSec=300`, `StartLimitBurst=5`
```ini
# deploy/weatherbot.service — [Unit] section (with Wants=/After=)
StartLimitIntervalSec=300
StartLimitBurst=5
# [Service] section
Restart=on-failure
RestartSec=5          # keep existing 5s backoff
# TimeoutStartSec=infinity  ← KEEP (line 27) — transient path never exits
```
Rationale: 5 fatal-exit restarts within a 300s (5-min) window parks the unit `failed`. With `RestartSec=5`, five restarts take ~25s of process time + startup, comfortably inside 300s, so a genuinely-fatal config error trips the limit in well under a minute and stops churning + spamming Discord (D-04 "once per boot" × 5 boots = at most 5 alerts, then silence with a loud `failed` unit). The window is generous enough that an unrelated transient restart weeks apart never accumulates toward the limit. These are conventional production values (RedHat/systemd guidance commonly cites burst 3–5 over 30–300s); 5/300 leans slightly permissive to avoid false-parking on a legitimately flaky boot network while still hard-stopping a config crash-loop. The planner may tune to 3/120 if a tighter park is preferred — behavior is identical, only the threshold differs.

### Discretion answer 3 — fatal-marker plumbing: dedicated `threading.Event` on `RuntimeParts`
See Pattern 3. Thread `fatal: threading.Event` from `build_runtime` through `RuntimeParts` (wiring.py:323-337) alongside `stop`; the `on_fail` hook sets it; `run_daemon` reads `fatal.is_set()` after `ready_gate.run(stop)` returns `False`. Kept separate from `stop` to preserve the fatal-vs-clean-SIGTERM distinction.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| App-owned `gate_until_healthy` startup gate (daemon.py:1108) | Hub `ReadyGate.run(stop)` (ready_gate.py) | v2.0 (Phases 25/28) | The app copy is now DEAD — remove it (in-scope cleanup). |
| App-owned `emit_online` online path | Inlined into `wiring.py:_on_online` | v2.0 | `emit_online` dead (F16/Phase 35). |
| `StartLimitIntervalSec` in `[Service]` (pre-systemd 229) | In `[Unit]` | systemd 229 (2016) | Must use `[Unit]` on the modern host; `[Service]` is silently ignored. |
| `Restart=always` (always restart, even config crash) | `Restart=on-failure` + start-limit | Phase 29 | A fatal config exit now parks `failed` instead of infinite 5s crash-loop. |

**Deprecated/outdated:**
- `gate_until_healthy` / `emit_online` / `_do_reload` in `daemon.py` — dead post-v2.0 (F16). Phase 29 removes `gate_until_healthy`; the other two are Phase 35.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `StartLimitIntervalSec=300`/`StartLimitBurst=5` are appropriate for this single-user Pi/host workload. | Discretion answer 2 | Low — these are conventional; only the park threshold shifts. Tunable without code change. Verify live at Gate-2 redeploy. |
| A2 | The live `yahir-mint` host runs a modern-enough systemd (≥229) that honors `StartLimit*` in `[Unit]`. | Pitfall 3 | Low — any current Mint/Debian/Ubuntu is ≫229. Confirm with `systemctl --version` at Gate-2. |
| A3 | Restricting the streak-prune `live_ids` to the full `_desired_job_ids` set (not just the forecast subset) is safe because the streak dict only ever holds forecast IDs. | Pattern 6 | Low — verified by code inspection (streaks written only in `_note_forecast_failure`, keyed by `_forecast_job_id`). |
| A4 | No test currently asserts `run()` uses the *thin* `load_config` path in a way that a switch to `validate_config_and_templates` would break. | HARD-STARTUP-01 | Low-Med — planner should grep `test_cli.py`/`test_golden_cli.py` for `run` config-load assertions before switching; a golden test pinning the old thin behavior would need updating with the fix. |

## Open Questions

1. **Should the fatal Discord alert reuse the exact `channel.send` best-effort idiom, or a dedicated formatter?**
   - What we know: `_on_applied`/`_on_online`/`_note_forecast_failure` all use `channel.send(str)` wrapped in try/except (wiring.py:213-217, daemon.py:427-435). The channel is built from `settings` at the composition root.
   - What's unclear: on the **boot-validator** fatal path (before `run_daemon`), the channel isn't built yet — D-08 says "build the channel best-effort from `settings`." The exact builder is `build_channel`/similar in `cli.py`/`send_now`.
   - Recommendation: extract a tiny `_fatal_config_exit(settings, reason, detail) -> int` in `cli.py` (or `ops`) that best-effort-builds the channel, sends one alert, stamps health, returns non-zero. Both the boot-validate path and the `on_fail` path call it (single fatal path, D-08). Planner locates the channel builder (grep `def build_channel`/`DiscordChannel(` in cli.py/send_now).

2. **`emit_online`/`_do_reload` dead-code: fold into Phase 29 or leave for Phase 35?**
   - What we know: F16 groups all three as dead; CONTEXT scopes only `gate_until_healthy` here.
   - Recommendation: remove `gate_until_healthy` (direct twin of this phase's `ReadyGate` subject); leave `emit_online`/`_do_reload` for Phase 35 unless the planner explicitly widens scope and notes it. Avoid silent scope creep.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | all | ✓ | 3.12+ | — |
| pytest | tests | ✓ | 9.0.3 | — |
| yahir_reusable_bot (hub) | ReadyGate/HealthResult/Severity | ✓ (pinned) | tag v0.1.1 | — |
| systemd | live restart-policy effect | ✓ (target host) | ≥229 assumed (A2) | The unit edit is inert until Gate-2 redeploy; tests validate the file's directives statically, not a live daemon. |

**Missing dependencies with no fallback:** none. All work runs on the installed dev stack; the systemd behavior is a **deferred Gate-2** live verification (D-06), not a dev-time blocker.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (+ pytest-cov 7.1.0) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`, `testpaths=["tests"]` |
| Quick run command | `uv run pytest tests/test_ops_selfcheck.py tests/test_cli.py -x -q` |
| Full suite command | `uv run pytest -q` |

> Suite note (from project memory): the syrupy snapshot harness prints "N snapshots failed" but exits 0 on pre-existing noise — trust the exit code + any `.ambr` diff, not the printed line.

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| HARD-STARTUP-01 | `run()` rejects a config with a duplicate id/name at boot (loudly, non-zero) | unit (invoke `run`/`main` with a bad `--config`, assert exit≠0 + no scheduler start) | `uv run pytest tests/test_cli.py -k "run_boot_validate" -x` | ❌ Wave 0 |
| HARD-STARTUP-01 | `run()` rejects a typo'd template token / missing template file at boot | unit (bad template fixture → assert `validate_config_and_templates` raises → fatal exit) | `uv run pytest tests/test_cli.py -k "run_boot_template" -x` | ❌ Wave 0 |
| HARD-STARTUP-01 | Parity: a config `check-config` accepts, `run` accepts; one it rejects, `run` rejects | property/parametrized (feed the SAME configs to both paths, assert identical accept/reject) | `uv run pytest tests/test_cli.py -k "check_run_parity" -x` | ❌ Wave 0 |
| HARD-STARTUP-02 | `run_self_check` classifies a config/template/empty-loc error as `CONFIG_INVALID` (not `NETWORK_NOT_READY`) | unit (extend test_ops_selfcheck.py `_RaisingClient`/bad-config fixtures) | `uv run pytest tests/test_ops_selfcheck.py -k "config_invalid" -x` | ⚠️ file exists; add cases |
| HARD-STARTUP-02 | `to_health_result` maps `CONFIG_INVALID` → `Severity.CRITICAL`; `AUTH_FAILED` still CRITICAL; `NETWORK_NOT_READY` still WARNING | unit | `uv run pytest tests/test_ops_selfcheck.py -k "severity" -x` | ⚠️ add cases |
| HARD-STARTUP-02 | `AUTH_FAILED` remains NON-fatal (re-probes; marker NOT set) — regression guard for D-03 | unit | `uv run pytest tests/test_scheduler.py -k "auth_not_fatal" -x` | ❌ Wave 0 |
| HARD-STARTUP-02 | `on_fail` on a CONFIG_INVALID result sets `fatal` + `stop`, and `run_daemon` returns non-zero | unit (inject a fatal `_health_check`, drive `run_daemon` with a stub scheduler, assert return≠0) | `uv run pytest tests/test_scheduler.py -k "fatal_exit_code" -x` | ❌ Wave 0 |
| HARD-STARTUP-02 | Clean SIGTERM (stop set, marker unset) → `run_daemon` returns 0 | unit (existing gate-stop test pattern, assert exit 0) | `uv run pytest tests/test_scheduler.py -k "clean_shutdown" -x` | ⚠️ near-existing (test_scheduler.py:636-655) |
| HARD-STARTUP-03 (F90) | `_announce_schedule` logs forecast slots incl. disabled ones with `next_run_time` | unit (capture structlog; assert a `kind="forecast:*"` line per slot) | `uv run pytest tests/test_scheduler.py -k "announce_forecast" -x` | ❌ Wave 0 |
| HARD-STARTUP-03 (F07) | Online ping fires strictly AFTER `notifier.ready()` (order recorded) | unit (record global order across `notifier.ready()` and `channel.send`, like test_scheduler.py:1035) | `uv run pytest tests/test_scheduler.py -k "ping_after_ready" -x` | ⚠️ pattern exists (1015-1045) |
| HARD-STARTUP-03 (F89) | A reload removing/renaming a forecast slot prunes its streak entry | unit (seed streak dict, apply reload, assert dead key gone, live key kept) | `uv run pytest tests/test_reload.py -k "streak_prune" -x` | ❌ Wave 0 (test_reload.py exists) |

### The hard-to-test criteria — how to actually validate them

- **Fatal-exit-code behavior (SC-2 core):** best validated at **two altitudes**. (a) *Unit:* drive `run_daemon` with a stubbed `ready_gate`/`_health_check` that returns a fatal `HealthResult`, assert `run_daemon` returns non-zero and `scheduler.start` was never called. (b) *Subprocess/integration:* a `subprocess`-launched `weatherbot run --config <bad.toml>` asserting the **process exit code** is non-zero and the boot log carries the CRITICAL line — this is the only test that proves the exit code truly propagates `run_daemon → main → sys.exit`. Recommend ONE subprocess test for the end-to-end exit-code contract; unit tests for the branch logic.
- **selfcheck permanent-vs-transient classification (SC-2):** pure unit — extend `test_ops_selfcheck.py` with (i) a bad-template config → `CONFIG_INVALID`, (ii) empty-locations → `CONFIG_INVALID`, (iii) a `_RaisingClient(httpx.ConnectError)` → still `NETWORK_NOT_READY`, (iv) a 401 → still `AUTH_FAILED`. A **parametrized** matrix over (config-error, transient, auth) is the natural shape and doubles as the D-03 regression guard.
- **Boot-gate rejecting a bad config (SC-1):** unit + the parity property test (same configs → identical accept/reject for `check-config` and `run`). The parity test is the strongest guard against F05 ever regressing.
- **systemd restart-policy (SC-2 at the OS layer):** NOT unit-testable in CI. Validate statically — a test (or a `deploy/` lint) asserting `weatherbot.service` contains `Restart=on-failure`, `StartLimit*` in `[Unit]`, and STILL `TimeoutStartSec=infinity`. The LIVE crash-loop-parks-`failed` behavior is a **deferred Gate-2** obligation on `yahir-mint` (D-06), recorded, not run in CI.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_ops_selfcheck.py tests/test_cli.py tests/test_scheduler.py -x -q`
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_cli.py` — boot-validate cases: duplicate id/name, typo'd template, missing template file, and the `check-config`↔`run` **parity** property test (covers HARD-STARTUP-01).
- [ ] `tests/test_ops_selfcheck.py` — add `CONFIG_INVALID` classification + severity-map cases (extend existing file).
- [ ] `tests/test_scheduler.py` — fatal-exit-code branch, clean-SIGTERM-returns-0, `AUTH_FAILED`-not-fatal regression, `announce_forecast`, `ping_after_ready`.
- [ ] `tests/test_reload.py` — streak-prune-on-reload (F89).
- [ ] One **subprocess** integration test — `weatherbot run --config <bad>` asserts a non-zero **process** exit code (the only true end-to-end exit-code proof).
- [ ] A static `deploy/weatherbot.service` directive test (Restart/StartLimit/Timeout assertions).

## Security Domain

> `security_enforcement: true` (config.json:42). This phase is daemon-lifecycle hardening with no new external input surface, but two ASVS categories apply.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Config/template validation IS the phase — `validate_config_and_templates` (pydantic schema + unique-name + token allow-list) is the fail-loud boundary. |
| V7 Error Handling & Logging | yes | Fatal `detail`/alert must be outcome-only (`type(exc).__name__`), never `str(exc)` (which can carry paths) and never a secret (T-04-01). Overlaps Phase 30 (Secret Hygiene) — do not regress it here. |
| V6 Cryptography | no | No crypto in this phase. |
| V2/V3/V4 Auth/Session/Access | no | No auth surface changed; `AUTH_FAILED` handling is deliberately UNCHANGED (D-03). |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Config error message leaks a filesystem path / secret into the Discord alert or log | Information Disclosure | `detail=type(exc).__name__`; reuse the existing outcome-only `CheckResult.detail` contract (selfcheck.py:16-17, 55-56). |
| A hung fatal-alert `channel.send` blocks shutdown/exit | Denial of Service | best-effort try/except around the send (existing idiom); never let the alert mask/delay the non-zero exit. |
| Fatal path masks a clean SIGTERM (wrong exit code → spurious restart) | Tampering (of lifecycle state) | separate `fatal` Event from `stop`; exit 0 on clean stop, non-zero only when `fatal.is_set()`. |

## Sources

### Primary (HIGH confidence) — actual codebase (line-cited)
- `weatherbot/config/loader.py:18-27, 67-96, 99-168` — `load_config`, `assert_unique_names`, `validate_config_and_templates` (the shared offline validator + its 4-exception contract).
- `weatherbot/cli.py:569-587 (_load_config_reporting), 945-977 (check-config catch set), 984-1006 (run path)` — the F05 gap: `run` uses the thin loader.
- `weatherbot/ops/selfcheck.py:44-46, 63-124, 127-145` — reason constants, `run_self_check` catch-all (F06), `to_health_result` severity map.
- `../Reusable/YahirReusableBot/yahir_reusable_bot/lifecycle/ready_gate.py:47-119` — `ReadyGate.run(stop)`, `on_fail`/`on_online` hooks, `stop`-set → returns `False` (no fatal path; D-09).
- `../Reusable/YahirReusableBot/yahir_reusable_bot/config/reload.py:110-213` — `ReloadEngine.check`/`reload`/`_reconcile`/`request_reload`/`_on_applied` seam.
- `weatherbot/scheduler/wiring.py:195-337` — `_on_applied`, `_health_check`, `_on_fail`, `_on_online`, `ReadyGate` construction, `RuntimeParts`.
- `weatherbot/scheduler/daemon.py:380-440 (streaks/F89), 556-571 (_forecast_job_id), 695-713 (_desired_job_ids), 1030-1063 (_announce_schedule/F90), 1108-1156 (dead gate_until_healthy), 1354-1466/1560-1598 (run_daemon composition root + return path)` — every STARTUP-03 site + the exit-code seam.
- `weatherbot/weather/store.py:436-468` — `stamp_tick`/`stamp_health` (durable health row, D-02).
- `deploy/weatherbot.service:13-52` — `[Unit]`/`[Service]` placement, `TimeoutStartSec=infinity` (keep), `Restart=always`/`RestartSec=5` (change).
- `.planning/WHOLE-PROJECT-REVIEW.md:38-39, 61-98, 389-393, 406-409` — F05/F06/F07/F89/F90/F16 finding detail (F16 confirms `gate_until_healthy`+`emit_online`+`_do_reload` dead).
- `.planning/REQUIREMENTS.md:14-19` — HARD-STARTUP-01/02/03 text.

### Secondary (MEDIUM confidence) — systemd behavior, verified against man page
- man7.org systemd.service(5) — `Restart=on-failure` triggers on non-zero exit OR signal; a **requested** stop (systemctl stop/restart) is exempt from restart; `SuccessExitStatus`/`RestartPreventExitStatus` roles.
- freedesktop.org systemd.unit(5) + HashiCorp support note — `StartLimitIntervalSec`/`StartLimitBurst` belong in `[Unit]`; `[Service]` placement is silently ignored ("Unknown lvalue").
- RedHat "self-healing services with systemd" + oneuptime/itsfoss guides — conventional start-limit values (burst 3–5 over 30–300s); a restarted service enters `failed` only after the start limit is reached.

### Tertiary (LOW confidence)
- None — all systemd claims cross-checked against the official man pages; all code claims line-cited.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all primitives already installed + line-cited.
- Architecture (two-layer fatal path, on_fail/stop overload, no-hub-change): HIGH — verified against actual `ready_gate.py` + `wiring.py` + `run_daemon` control flow.
- systemd interaction (D-05): HIGH — the requested-stop exemption + `[Unit]` placement + `on-failure`-vs-`infinity` orthogonality all confirmed against `systemd.service(5)`/`systemd.unit(5)`.
- Discretion answers (name/values/marker): HIGH on shape, MEDIUM on the exact numeric values (A1/A2 — tunable, Gate-2-verifiable).
- Pitfalls: HIGH — grounded in code + man-page behavior.

**Research date:** 2026-07-07
**Valid until:** 2026-08-06 (stable domain; re-verify only if the hub tag moves off `v0.1.1` or the live host's systemd is unusually old).

## Sources

- [systemd.service(5) — man7.org](https://www.man7.org/linux/man-pages/man5/systemd.service.5.html)
- [systemd.unit(5) — freedesktop.org](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html)
- [Unknown lvalue 'StartLimitIntervalSec' in section 'Service' — HashiCorp](https://support.hashicorp.com/hc/en-us/articles/4406120244755-Unknown-lvalue-StartLimitIntervalSec-in-section-Service)
- [Set up self-healing services with systemd — Red Hat](https://www.redhat.com/en/blog/systemd-automate-recovery)
