---
phase: 12-command-registry-read-only-command-surface
reviewed: 2026-06-19T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - weatherbot/interactive/registry.py
  - weatherbot/interactive/command.py
  - weatherbot/interactive/bot.py
  - weatherbot/interactive/state.py
  - weatherbot/interactive/commands/info.py
  - weatherbot/interactive/commands/status.py
  - weatherbot/interactive/commands/weather_views.py
  - weatherbot/cli.py
  - weatherbot/config/models.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/weather/client.py
  - weatherbot/weather/store.py
findings:
  critical: 0
  warning: 7
  info: 6
  total: 13
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-06-19
**Depth:** standard
**Files Reviewed:** 11 (+ 12 test files cross-referenced; cache.py read for context)
**Status:** issues_found

## Summary

Phase 12 adds the self-describing command registry, the pure registry-driven
parser (`parse_command`), seven read-only command handlers, the read-only
`DaemonState` accessor, and the bot/CLI dispatch wiring on top of the One Call
`exclude` widening (`minutely`-only). The full 80-test slice for this phase
passes.

The headline security/correctness concerns held up under adversarial tracing:

- **Parser purity / word-boundary safety:** `parse_command` uses only
  `strip`/`casefold`/slicing — no `format`/`eval`/`exec`/shell. The
  word-boundary guard (`rest[0].isspace()`) was probed against the full
  registry (`sunny`/`helper`/`statusbar`/`next-cloudyx`/`alerts!!!`) and
  correctly classifies all of them `NOT_A_COMMAND`. Longest-keyword-first
  ordering is real.
- **Failure-isolation envelope (CMD-16):** the whole registry dispatch lives
  inside ONE non-propagating `try/except` in `on_message`; a raising handler,
  a raising fetch, AND a raising error-reply are all swallowed. `BotThread._run`
  independently swallows `LoginFailure`/any crash and flips `_failed`.
- **Read-only / zero-store-write discipline:** the handler package imports
  nothing from `weather.store` except the read-only `read_heartbeat` (in
  `status`), and the zero-store-writes spy test enforces it.
- **Store SQLi:** every store statement is parameterized `?`; `read_heartbeat`
  is genuinely read-only.

The findings below are robustness gaps, not shipped-broken behavior. The
recurring theme: several handlers index raw One Call dict fields
(`h["dt"]`, `d["dt"]`, `cur["sunrise"]`) that are *assumed* present after a
`None`-guard on a *sibling* field — on the Discord surface a `KeyError` is
absorbed by the envelope (operator sees a generic error), but on the **CLI**
surface (`_run_registry_command`) those same `KeyError`s are NOT caught and
crash with a traceback (only `UnknownLocationError`/httpx errors are handled).

## Warnings

### WR-01: `next_cloudy` indexes `h["dt"]` / `d["dt"]` after guarding only `clouds` — uncaught `KeyError` crashes the CLI

**File:** `weatherbot/interactive/commands/weather_views.py:188-208`
**Issue:** The hourly loop guards on `clouds` (`if clouds is None or clouds < threshold: continue`) then unconditionally reads `h["dt"]` (line 192). The daily loop does the same with `d["dt"]` (line 208). A One Call bucket that carries `clouds` but is missing `dt` (or a malformed/partial payload) raises `KeyError`. On Discord this is swallowed by the `on_message` envelope, but the CLI dispatcher (`cli.py:_run_registry_command`) only catches `UnknownLocationError`/httpx errors — a `KeyError` there propagates as a raw traceback (violates the CONF-05/"never a raw traceback" posture the rest of the CLI honors). The module's own docstring touts defensive `or []`/`a or {}` guards elsewhere, so this is an inconsistency, not a deliberate choice.
**Fix:** Use `.get("dt")` and skip the bucket when absent, mirroring the `clouds` guard:
```python
for h in raw.get("hourly") or []:
    clouds = h.get("clouds")
    dt_ts = h.get("dt")
    if clouds is None or dt_ts is None or clouds < threshold:
        continue
    when = _epoch_local(dt_ts, tz)
    ...
# and likewise d.get("dt") in the daily loop
```

### WR-02: `next_cloudy` "no cloudy day" message reports the wrong window count when `hourly` is the only data

**File:** `weatherbot/interactive/commands/weather_views.py:217-221`
**Issue:** `days = len(daily) or 8` is computed from `daily` only. When the payload has a populated `hourly[]` but an empty/missing `daily[]` (the exact case the hybrid lookahead exists to bridge), `len(daily)` is 0, so the fallback claims `"No cloudy day in the next 8 days."` even though no 8-day daily data was actually scanned. The message asserts a forecast horizon the function never inspected — misleading the operator about coverage.
**Fix:** Report the count actually scanned, or make the wording honest about the hybrid scan, e.g. base it on the real daily length without the magic `or 8`, or phrase it `"No cloudy day in the forecast window."` (matching the registry summary) when daily is empty.

### WR-03: `sun` reads `cur["sunrise"]`/`cur["sunset"]` by subscript after a truthiness-style guard

**File:** `weatherbot/interactive/commands/weather_views.py:144-147`
**Issue:** `if cur.get("sunrise") is not None: lines.append((..., _epoch_local(cur["sunrise"], tz)...))`. This is safe today because the same key is re-read, but it double-reads a dict that could in principle differ and is a fragile pattern. More importantly it sets the precedent the rest of the file (WR-01) violates. Low risk on its own; flagged for consistency since the codebase elsewhere binds the value once.
**Fix:** Bind once: `sr = cur.get("sunrise"); if sr is not None: lines.append(("Sunrise", _epoch_local(sr, tz).strftime("%H:%M")))`.

### WR-04: `status` handler will crash if dispatched with `daemon_state=None`

**File:** `weatherbot/interactive/bot.py:188-192` + `weatherbot/interactive/commands/status.py:53-77`
**Issue:** `build_on_message` accepts `daemon_state: DaemonState | None = None` (and several tests/`build_client` callers pass `None`/omit it). When an operator types `!status` with `daemon_state=None`, the bot dispatches `spec.handler(None)`, and `status(None)` immediately calls `None.next_fires()` → `AttributeError`. The `on_message` envelope absorbs it into the generic "something went wrong" reply, so it is non-crashing, but `!status` is then permanently broken (no useful message) for any bot constructed without state. Production daemon wiring always supplies it (`daemon.py:1227`), so this is a latent gap rather than a live bug, but the public `build_on_message`/`build_client` signature invites the broken configuration.
**Fix:** Guard the status branch: if `daemon_state is None`, reply with a clear "status unavailable (no daemon state)" `CommandReply` instead of dispatching into a `None`. Alternatively make `status` tolerate `None` and report "daemon state unavailable".

### WR-05: CLI registry dispatch lacks the failure-isolation envelope the Discord surface has

**File:** `weatherbot/cli.py:556-604`
**Issue:** `_run_registry_command` catches only `UnknownLocationError` and the httpx transport errors around `lookup_weather`. The handler invocation itself (`spec.handler(result)`, `spec.handler(config)`, `_cli_daemon_state(config)` → `read_heartbeat`) runs with NO try/except. Any handler bug or malformed-payload `KeyError` (see WR-01) surfaces as a raw traceback to the terminal, breaking the CLI's documented "report loudly but cleanly, never a raw Python traceback" contract (CONF-05/SC-05) that `_load_config_reporting` and `run_weather` carefully uphold. The two surfaces have asymmetric robustness for the same registry handlers.
**Fix:** Wrap the handler dispatch + render in a try/except that logs outcome-only and returns a non-zero exit (e.g. 3) with a clean message, mirroring the Discord envelope's intent on the CLI side.

### WR-06: `render_embed` adds fields with no Discord field-count / value-length bound

**File:** `weatherbot/interactive/bot.py:78-86`
**Issue:** `render_embed` iterates `reply.lines` and calls `add_field` for each with no cap. `alerts` builds one field per active alert (`weather_views.py:111-127`) with the event name as the field NAME (untruncated) and a `when — desc` value (desc capped at 200, but `when` + event name are not). Discord rejects an embed with >25 fields or any field value/name over its limits (1024 value / 256 name), and the gateway send would raise `HTTPException`. With many simultaneous alerts this produces a failed send → the envelope's generic error reply, so the operator gets nothing useful during exactly the high-alert moment the command exists for. The alert `event` string is provider-controlled text placed directly into a field name.
**Fix:** Cap the number of fields rendered (e.g. first 24 + a "+N more" field), and truncate field names/values to Discord's limits in `render_embed` (or in the `alerts` handler before building the reply).

### WR-07: `alerts` time window shows day-of-week + time only — ambiguous across week boundaries

**File:** `weatherbot/interactive/commands/weather_views.py:119-121`
**Issue:** `strftime("%a %H:%M")` renders an alert window as e.g. `"Mon 14:00 → Wed 02:00"`. One Call alerts can have multi-day spans and `start`/`end` up to a week out; `%a` alone (no date) is ambiguous and can read as a window in the past. For a safety-relevant feature (weather alerts) the operator can misjudge whether an advisory is active now or days away.
**Fix:** Include the date in the window format (e.g. `"%a %b %d %H:%M"`), matching the daily `next-cloudy` format which already uses `"%a %b %d"`.

## Info

### IN-01: `parse_command` matches `spec.name` against a casefolded string but never folds `spec.name`

**File:** `weatherbot/interactive/command.py:103-104`
**Issue:** `folded.startswith(spec.name)` relies on every registry name being lowercase. It is today, but a future mixed-case command name would silently never match (no test guards this).
**Fix:** Fold the spec name too (`folded.startswith(spec.name.casefold())`) or assert lowercase names in the registry, so the case-insensitive contract is name-agnostic.

### IN-02: Duplicated next-fire logic between `state.py:_next_fire` and `daemon.py:_announce_schedule`

**File:** `weatherbot/interactive/state.py:26-38` and `weatherbot/scheduler/daemon.py:730-736`
**Issue:** `_next_fire` "mirrors `_announce_schedule` verbatim" (per its own docstring) — the running-value-first/trigger-fallback logic is copied. The job-id format `f"{name}|{time}|{days}"` is also independently re-derived in three places (`_register_jobs`, `_desired_job_ids`, `_announce_schedule`, `state.next_fires`). Drift between any of them silently breaks `status` next-send reporting.
**Fix:** Extract the next-fire helper and the job-id builder into one shared function the daemon and `DaemonState` both call.

### IN-03: `wind` direction uses `int(deg)` which truncates toward zero for floats

**File:** `weatherbot/interactive/commands/weather_views.py:170`
**Issue:** `f"{compass(deg)} ({int(deg)}°)"` — `int(199.8)` displays `199°`. Cosmetic, but `round(deg)` would be more accurate for a degree readout. (`compass` itself rounds correctly via the `+11.25` offset.)
**Fix:** Use `round(deg)` for the displayed degree value.

### IN-04: `_fmt_epoch`/`_fmt_uptime` accept untyped params and silently coerce

**File:** `weatherbot/interactive/commands/status.py:22-43`
**Issue:** `_fmt_uptime(delta)` is untyped and assumes `.total_seconds()`; `_fmt_epoch` assumes a UTC epoch int. These are internal helpers fed by `DaemonState`, so risk is low, but the untyped `delta` parameter loses the `timedelta` contract.
**Fix:** Add type hints (`delta: timedelta`) for clarity and lint coverage.

### IN-05: `DaemonState.scheduler`/`db_path` typed as bare `object`

**File:** `weatherbot/interactive/state.py:51,53`
**Issue:** `scheduler: object` and `db_path: object` defeat type checking at the one boundary (`get_jobs()`, `read_heartbeat(db_path)`) where a wrong type would fail at status-call time rather than construction. The CLI passes a hand-rolled `_NoJobsScheduler`, so a structural/Protocol type would document the contract.
**Fix:** Use a `Protocol` for the scheduler (just `get_jobs()`) and `str | Path` for `db_path`.

### IN-06: `next_cloudy` daily fallback ignores `_is_daytime`, unlike the hourly branch

**File:** `weatherbot/interactive/commands/weather_views.py:202-215`
**Issue:** The hourly branch filters to daytime buckets via `_is_daytime`, but the daily branch reports any day at/above threshold regardless of the daytime weighting the docstring implies ("daytime-weighted daily clouds"). `daily[].clouds` is a whole-day value, so this is defensible, but the comment overstates what the code does (no daytime weighting is applied to the daily value).
**Fix:** Align the comment with the behavior, or document that daily clouds are taken as-is.

---

_Reviewed: 2026-06-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
