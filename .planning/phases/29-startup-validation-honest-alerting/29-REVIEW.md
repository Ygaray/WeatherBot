---
status: issues
phase: 29
findings:
  critical: 0
  blocker: 0
  warning: 1
  info: 1
---

# Phase 29: Code Review Report

**Reviewed:** 2026-07-07T00:00:00Z
**Depth:** deep (cross-file: cli → daemon → wiring → hub ReadyGate; selfcheck classification; channel factory)
**Files Reviewed:** 6 source (`weatherbot/cli.py`, `weatherbot/ops/selfcheck.py`, `weatherbot/ops/__init__.py`, `weatherbot/scheduler/daemon.py`, `weatherbot/scheduler/wiring.py`, `deploy/weatherbot.service`) + 6 test files cross-checked
**Status:** issues_found

## Summary

The correctness-critical machinery of Phase 29 is **sound**. I traced every high-risk area
called out in the review brief and found no Critical/blocker defect:

- **Fatal-marker logic (D-10):** `fatal` is a dedicated `threading.Event`, set ONLY inside the
  `_on_fail` branch guarded by `result.reason == daemon.CONFIG_INVALID and result.severity >=
  CRITICAL`. `AUTH_FAILED` (also CRITICAL severity) is excluded by the explicit `reason ==
  CONFIG_INVALID` check and falls through to the re-probe branch → **D-03 preserved**. A clean
  SIGTERM sets only `stop` (via `_handle`), never `fatal`. No path sets `fatal` on a clean
  shutdown; no fatal path fails to set it. `run_daemon` returns `1 if parts.fatal.is_set() else 0`.
- **Exit-code propagation:** `run_daemon → main` return reaches `sys.exit` via both
  `weatherbot/__main__.py:14` (`sys.exit(main())`) and the `[project.scripts]` console-script
  wrapper. HARD-STARTUP-02 holds.
- **F05 parity:** `run()` catches the exact 4-exception set (`FileNotFoundError`,
  `tomllib.TOMLDecodeError`, `ValidationError`, `ValueError`) that `check-config` catches, via the
  same `validate_config_and_templates` validator.
- **F07:** the online ping is relocated out of `_on_online` into `run_daemon` strictly after
  `ready_gate.run(stop)` returns `True` (post-READY), wrapped best-effort. `scheduler.start()`
  stays in `_on_online` → the start-before-READY invariant is intact.
- **F90:** `_announce_schedule` now iterates `location.forecast` (a `default_factory=list` field —
  safe on empty) and logs disabled slots with `next_run_time=None`. No throw.
- **F89:** `_prune_forecast_streaks` keys on `_desired_job_ids` (which uses `_forecast_job_id`,
  byte-matching the streak dict keys) — live slots retained, removed/renamed pruned. Correct.
- **Dead-code removal:** `gate_until_healthy`/`wait_ready_gate` fully removed with zero remaining
  callers; `emit_online`/`_do_reload` correctly left for Phase 35.
- **No hub edits**, no `time.sleep` introduced, interruptible `stop.wait(...)` preserved.
- Full phase test suite: **156 passed**.

Three Warnings and one Info were raised. WR-01 was the notable one: the **primary** boot-validate
fatal path silently never delivered the Discord operator alert, which negated half of the phase's
explicit "honest alerting" value on the very path D-07 says catches every realistic case.

**Update (2026-07-08):** WR-01 (commit `a818057`) and WR-03 (commit `be83b1b`) are RESOLVED, each
with a regression test; full suite green (806 passed, exit 0). WR-02 is a deliberate WON'T FIX
(check-config↔run parity; local operator log; no credential in the config-validation exception) —
1 Warning remains open by design. IN-01 (stale xfail prose) left as-is (optional, harmless shim).

## Warnings

### WR-01: Primary boot-validate fatal path never delivers the Discord alert (config=None crashes channel build)

**Status:** RESOLVED — commit `a818057`. `_build_discord` now tolerates
`config is None`, falling back to a default `"WeatherBot"` username / `None` avatar
while the webhook URL still comes from `settings`; `build_channel`'s and
`_build_discord`'s `config` hint widened to `Config | None`. `build_channel(None,
settings)` no longer raises. Test gap closed: factory-level guard in
`tests/test_channel.py` (`test_build_channel_none_config_uses_settings_and_default_identity`)
plus a cli-level test (`test_fatal_config_exit_sends_via_real_build_channel`) that
drives the REAL `build_channel` through `_fatal_config_exit` so the alert send is
actually exercised (not stubbed).

**File:** `weatherbot/cli.py:611` (inside `_fatal_config_exit`) → `weatherbot/channels/factory.py:22`
**Issue:**
`_fatal_config_exit` builds the alert channel with `build_channel(None, settings)` — passing
`config=None`. That routes to `_build_discord(config, settings)` (`factory.py:22`), whose body is:

```python
return DiscordWebhookChannel(
    settings.discord_webhook_url,
    config.webhook.username,   # config is None → AttributeError
    config.webhook.avatar_url,
)
```

`None.webhook` raises `AttributeError` *before* the channel is ever constructed, so the alert send
never happens. The broad `except Exception` in `_fatal_config_exit` swallows it and logs
`"fatal alert send failed (best-effort)"`. Net effect: on the **primary** fatal detection layer
(D-07 — the offline boot validator, which the research says catches "every realistic
permanent-config case"), the operator **never receives a Discord alert**. This defeats half of the
phase's stated user-visible value (CONTEXT.md §specifics: "the human actually hears about it on
Discord AND the OS layer shows a failed unit — not one or the other. Both channels on a fatal.").
The exit code + systemd `failed` unit still surface it at the OS layer, so this is not a crash or
data loss — but it silently drops the Discord half of the locked D-08 requirement on the dominant
path.

The unit tests do not catch this because every `_fatal_config_exit` test monkeypatches
`build_channel` (to throw or return a stub) — the real `build_channel(None, settings)` factory path
is never exercised.

Note the defense-in-depth `_on_fail` path in `wiring.py:315` does NOT have this bug: it reuses the
already-built `channel` (constructed from the real `config`), so its alert sends correctly. Only the
`cli.py` boot-validate path is affected — and that is the primary one.

**Fix:** Give `_build_discord` a config-optional path, or build the channel in `_fatal_config_exit`
without the config-derived identity. Simplest:

```python
# weatherbot/channels/factory.py
def _build_discord(config, settings):
    username = config.webhook.username if config is not None else None
    avatar = config.webhook.avatar_url if config is not None else None
    return DiscordWebhookChannel(settings.discord_webhook_url, username, avatar)
```

(`DiscordWebhookChannel.__init__` already accepts `avatar_url: str | None`; confirm/allow a `None`
username, or fall back to a literal like `"WeatherBot"`.) Then add a test that drives
`_fatal_config_exit` through the **real** `build_channel` with `config=None` and a fake
webhook-capable `settings`, asserting `channel.send` is actually invoked.

### WR-02: `str(exc)` logged on the boot-validate failure line violates the outcome-only clean-failure contract

**Status:** OPEN — WON'T FIX (deliberate disposition). Left as-is: this is intentional
parity with `check-config`'s own `error=str(exc)` logging (`cli.py:1013`), it is the
LOCAL operator log (actionable — it tells the operator which config field is bad), and
the actual secrets (OpenWeather API key, Discord webhook URL) live in `.env`/`settings`,
NOT in the config-validation exception — so this is at most config-content disclosure in
a local operator log, not a credential leak. Changing only `run` would break the intended
`check-config` ↔ `run` parity. Counts as the 1 remaining open Warning (`findings.warning: 1`).

**File:** `weatherbot/cli.py:1036`
**Issue:**
```python
_log.error("run boot-validate failed", path=str(args.config), error=str(exc))
```
Every other new code path in this phase is scrupulously outcome-only (`detail=type(exc).__name__`),
and the `_fatal_config_exit` docstring + Pattern 2 in RESEARCH.md explicitly forbid `str(exc)`
because "a config error can embed a filesystem path or config value" (T-04-01 / T-29-10). This one
log line logs the full `str(exc)` of a pydantic/loader validation error, which can echo config-file
content (a location name, a template token, an offending value, a resolved path) into the logs.

The OpenWeather key and Discord webhook are read from `.env`/`settings` (not from the validated
`config.toml`), so this is **config-content disclosure, not a credential leak** — hence Warning, not
Critical. But it is a direct regression of the clean-failure contract the phase is otherwise careful
to honor, and Phase 30 (Secret Hygiene) is explicitly told "do not regress it here" (RESEARCH.md
§Security Domain, V7).

**Fix:**
```python
_log.error(
    "run boot-validate failed",
    path=str(args.config),
    error=type(exc).__name__,   # outcome-only; never str(exc)
)
```

### WR-03: Narrowed self-check catch lets non-(ValueError/FileNotFoundError) config errors escape and crash the ReadyGate loop

**Status:** RESOLVED — commit `be83b1b`. The pre-probe catch widened from
`(ValueError, FileNotFoundError)` to `(ValueError, OSError)` at `selfcheck.py:101`
(`FileNotFoundError ⊂ OSError`; strictly broadens to also catch
`IsADirectoryError`/`PermissionError` → `CONFIG_INVALID`). The block is offline (the
probe lives in the separate try below), so broadening cannot swallow a
transient/network error; `detail` stays `type(exc).__name__` (secret-safe).
Regression added in `tests/test_ops_selfcheck.py`
(`test_config_invalid_on_template_oserror`, parametrized over
`PermissionError`/`IsADirectoryError`): `run_self_check` returns
`CheckResult(reason=CONFIG_INVALID)` without raising, probe never reached. The D-03
guards (transient → `NETWORK_NOT_READY`, 401 → `AUTH_FAILED`) stay green.

**File:** `weatherbot/ops/selfcheck.py:101`
**Issue:**
The pre-probe config block now catches only `(ValueError, FileNotFoundError)`:

```python
try:
    if not config.locations: ...
    validate_template(load_template(config.template))
    assert_unique_names(config)
    for loc in config.locations:
        resolve_location(config, loc.name)
except (ValueError, FileNotFoundError) as exc:
    return CheckResult(ok=False, reason=CONFIG_INVALID, detail=type(exc).__name__)
```

`load_template` (`templates/renderer.py:202`) does `Path(...).read_text()`, which can raise
`IsADirectoryError` or `PermissionError` — both subclasses of `OSError`, **not** caught here. Prior
to this change, the single broad `except Exception` swallowed any such error into
`NETWORK_NOT_READY` (stay-alive). Now these escape `run_self_check` entirely, propagate through
`_health_check` into the hub's `ReadyGate.run`, whose `result = self._health_check()`
(`ready_gate.py:90`) is **not** wrapped in try/except — so the exception unwinds out of
`run_daemon` and crashes the daemon with a traceback (uncaught → non-zero exit via `sys.exit`).

Reachability is narrow: in `run` mode the boot validator (`validate_config_and_templates`) runs
first and, though it catches only the same 4 exceptions, would surface most cases at boot. The
probe-time layer is only hit if a template path becomes a directory / loses read permission
*between* boot-validate and a later probe. But this is the defense-in-depth layer whose whole point
(D-04) is to *never* die on a probe — and this narrowing reintroduces a die-on-probe crash path
(traceback, not a classified stamp).

**Fix:** widen the pre-probe catch to also classify these as `CONFIG_INVALID` (they are permanent
operator errors, not transient), keeping the outcome-only detail:

```python
except (ValueError, FileNotFoundError, OSError) as exc:  # OSError covers IsADirectory/Permission
    return CheckResult(ok=False, reason=CONFIG_INVALID, detail=type(exc).__name__)
```

(`FileNotFoundError` is itself an `OSError` subclass, so it can be folded in — keep it listed for
readability or drop it as redundant.) Add a regression case in `test_ops_selfcheck.py` with a
template path that is a directory.

## Info

### IN-01: Stale "xfail" prose in the Phase 29 test scaffolding comment

**File:** `tests/test_scheduler.py:2193` (block comment) and similar prose at `tests/test_cli.py`,
`tests/test_service_unit.py`
**Issue:** The comment header states the impl-dependent cases "are `xfail(strict=False)` until then
— RED here is SUCCESS", but the tests carry no `@pytest.mark.xfail` decorator (they are live and
passing now that the impl landed). The prose is misleading to a future reader who greps for the
supposed xfail markers.
**Fix:** Update the block comment to reflect that these are now live, de-scaffolded guards (or delete
the RED/xfail narration).

---

_Reviewed: 2026-07-07T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
