---
phase: quick-260617-fua
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - weatherbot/scheduler/daemon.py
  - tests/test_reload.py
  - deploy/README.md
  - .planning/phases/11-discord-inbound-gateway-bot/11-CONTEXT.md
autonomous: true
requirements: [CR-01]
must_haves:
  truths:
    - "After a successful config reload, the bot's ForecastCache is cleared so the next !weather refetches against the new config (CR-01 closed)."
    - "A cache.invalidate() error never aborts an otherwise-successful reload (best-effort)."
    - "A daemon-level integration test proves reload triggers a refetch (distinct from the isolated invalidate unit test)."
    - "deploy/README.md and the Phase 11 CONTEXT deferral note state cache invalidation on reload is now wired (no longer deferred)."
  artifacts:
    - path: "weatherbot/scheduler/daemon.py"
      provides: "_do_reload accepts cache= and invalidates it best-effort after a successful swap; run_daemon threads cache into the _do_reload call"
      contains: "cache.invalidate"
    - path: "tests/test_reload.py"
      provides: "daemon-level integration test: reload with a changed location → next cache.lookup refetches"
      contains: "invalidate"
  key_links:
    - from: "weatherbot/scheduler/daemon.py run_daemon poll-loop _do_reload call"
      to: "_do_reload cache= param"
      via: "keyword arg cache=cache"
      pattern: "cache=cache"
    - from: "_do_reload success path (after reconcile commit)"
      to: "ForecastCache.invalidate"
      via: "best-effort call guarded by try/except"
      pattern: "cache\\.invalidate\\(\\)"
---

<objective>
Wire `ForecastCache.invalidate()` into the daemon reload path, closing code-review
finding CR-01 and reversing the Phase 11 Q2/D-12 deferral. The cache is constructed
in `run_daemon` and currently handed only to `BotThread`; the reload engine
(`_do_reload`) has no reference to it, so after a config edit + reload the bot serves
a pre-reload forecast for up to the full TTL (~10 min, D-12) on the next `!weather`.

Thread the cache into `_do_reload` and call `cache.invalidate()` in the SUCCESS branch
only — after `holder.replace` + `_reconcile_jobs` have committed — so a stale forecast
is never served against a freshly reloaded config. The call is best-effort: an
invalidation error must never abort an otherwise-successful reload.

Purpose: Close CR-01 (stale-forecast-after-reload BLOCKER) and make the documented
Pattern-4 reload hook actually fire in production.
Output: Updated `_do_reload`/`run_daemon`, a new daemon-level integration test, and
doc/deferral-note corrections in deploy/README.md and 11-CONTEXT.md.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
</execution_context>

<context>
@.planning/STATE.md
@weatherbot/scheduler/daemon.py
@weatherbot/interactive/cache.py
@tests/test_reload.py
@tests/test_cache.py
@deploy/README.md
@.planning/phases/11-discord-inbound-gateway-bot/11-REVIEW.md
@.planning/phases/11-discord-inbound-gateway-bot/11-CONTEXT.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Thread the cache into _do_reload and invalidate best-effort after a successful swap</name>
  <files>weatherbot/scheduler/daemon.py</files>
  <read_first>
    - weatherbot/scheduler/daemon.py lines 549-679 (the `_do_reload` signature + the
      two-phase body: PHASE 1 validate-or-keep-old, PHASE 2 atomic swap + reconcile +
      rollback, then the success log/post block at ~647-668 and the watch-dir re-derive
      at ~670-679).
    - weatherbot/scheduler/daemon.py lines 1031-1045 (`run_daemon` constructs the
      `ForecastCache` as `cache`, only when `settings is not None`).
    - weatherbot/scheduler/daemon.py lines 1202-1230 (the main poll-loop reload servicing
      block that calls `_do_reload(...)`).
    - weatherbot/interactive/cache.py lines 110-114 (`invalidate()` clears every entry
      under the lock — the Pattern-4 hook).
  </read_first>
  <action>
    Two edits in weatherbot/scheduler/daemon.py, resolving CR-01:

    (1) Add a `cache=None` keyword-only parameter to `_do_reload` (place it alongside the
    existing keyword-only params such as `client`/`channel`/`stop_event`/`watch_dirs_ref`;
    default None so every existing caller and test that omits it stays valid). Type it as
    the same optional-ForecastCache shape the daemon already uses (an untyped/`None`
    default is fine — no new import required at runtime; if a type hint is added, keep it
    behind the existing `TYPE_CHECKING` guard, importing `ForecastCache` from
    `weatherbot.interactive` there only).

    Inside `_do_reload`, invalidate the cache in the SUCCESS branch ONLY — after
    `holder.replace(new_cfg)` AND `_reconcile_jobs(...)` have committed (i.e. after the
    success `summary` log/post block, around line 668, in the same region as the CFG-07
    "✅ config reloaded" post and BEFORE/AFTER the watch-dir re-derive — either side is
    fine, but it MUST be in the committed-success path, never the PHASE-1 reject `except`
    and never the PHASE-2 rollback `except`). Guard it best-effort, mirroring the existing
    emit_online / CFG-07 post idiom: `if cache is not None:` then a `try: cache.invalidate()
    except Exception:` that logs a warning and swallows — so a cache error can NEVER abort
    an already-committed reload. Reuse the project's `_log` structlog logger for the warning
    (outcome-only; no secret). This implements CR-01's "Pattern 4: never serve a pre-reload
    forecast".

    (2) In `run_daemon`'s poll-loop `_do_reload(...)` call (the block around lines
    1213-1224), pass `cache=cache` as a new keyword argument. `cache` is already in scope
    (constructed at ~1041-1045; it is `None` when `settings is None`, which the best-effort
    `if cache is not None` guard in `_do_reload` already tolerates). Do NOT change the cache
    construction, the BotThread wiring, or any other reload semantics.

    Do not touch the PHASE-1 reject path, the rollback path, the reconcile logic, the
    CFG-07 posts, or the watch-dir re-derive behavior — invalidation is purely additive in
    the success branch.
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot && grep -n "cache=cache" weatherbot/scheduler/daemon.py && grep -n "cache.invalidate" weatherbot/scheduler/daemon.py && uv run python -c "import weatherbot.scheduler.daemon"</automated>
  </verify>
  <done>
    `_do_reload` has a `cache=None` keyword-only param and calls `cache.invalidate()`
    best-effort (try/except, swallowed) in the committed-success branch only;
    `run_daemon`'s poll-loop call passes `cache=cache`. The module imports cleanly and the
    existing reload tests (which omit `cache=`) still pass.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add a daemon-level integration test proving reload refetches the cache</name>
  <files>tests/test_reload.py</files>
  <read_first>
    - tests/test_reload.py lines 75-204 (the local `_loc`/`_cfg`/`_slot` builders, the
      `_RecordingChannel`, and the `holder_scheduler`/`load_fixture` usage pattern in
      `test_already_sent_slot_not_refired_after_tz_name_change`).
    - tests/test_reload.py lines 441-456 (`test_reload_applies_new_schedule` — the simplest
      `_do_reload(new, holder=..., scheduler=..., db_path=...)` success-path call shape).
    - tests/test_cache.py lines 75-184 (how `ForecastCache` is built with `settings=None`
      and how `lookup_weather` is monkeypatched with a counting spy via the cache module;
      `test_invalidate_clears_cache` is the ISOLATED unit test this integration test must be
      distinct from).
    - weatherbot/interactive/cache.py lines 82-114 (`lookup(name, config)` keys on
      `resolve_location(config, name).id`; `invalidate()` clears under the lock).
    - tests/conftest.py lines 157-183 (`holder_scheduler` returns `(holder, scheduler,
      db_path)` from an unstarted BackgroundScheduler).
  </read_first>
  <behavior>
    - Build a real `ForecastCache(settings=None)` and monkeypatch the cache module's
      `lookup_weather` with a counting spy (mirror test_cache.py: `monkeypatch.setattr(
      cache_mod, "lookup_weather", lambda name, *, config, **k: fetches.append(name) or
      object(), raising=False)`).
    - Prime the cache: call `cache.lookup("home", old_cfg)` once → spy count == 1.
    - Drive a real `_do_reload(new_cfg, holder=..., scheduler=..., db_path=..., cache=cache)`
      with a CHANGED location (e.g. new lat/lon and/or template on the SAME stable id so the
      cache key survives — the exact CR-01 stale-key scenario) so the success branch commits
      and invalidates.
    - After the reload, call `cache.lookup("home", new_cfg)` again → spy count == 2,
      proving the reload-invalidation forced a refetch (NOT served from the pre-reload entry).
    - The test must use the REAL `_do_reload` cache wiring from Task 1 (distinct from
      `test_invalidate_clears_cache`, which calls `cache.invalidate()` directly).
  </behavior>
  <action>
    Add one new test function to tests/test_reload.py (e.g.
    `test_reload_invalidates_forecast_cache_so_next_lookup_refetches`). Reuse the existing
    deferred `_do_reload` helper at the top of the file and the local `_loc`/`_cfg`/`_slot`
    builders and the `holder_scheduler` fixture — do NOT add new fixtures. Import the cache
    module the same way test_cache.py does (`from weatherbot.interactive import cache as
    cache_mod`, or a small local deferred helper) and build `ForecastCache(settings=None)`.
    Monkeypatch `cache_mod.lookup_weather` with a counting spy so no real OpenWeather call is
    made. The reload's `new_cfg` keeps the SAME stable `id` for "home" but changes a field
    (lat/lon) so the cache key is identical across the edit — exactly the stale-read CR-01
    describes; the assertion (`len(fetches) == 2` after the post-reload lookup) proves the
    reload cleared the entry. Add a docstring naming CR-01 and stating this is the
    daemon-level integration proof distinct from the isolated `test_invalidate_clears_cache`.
    Run `lookup` synchronously in-test (the off-loop `run_in_executor` dispatch is the bot's
    concern; `lookup` itself is plain blocking code, per cache.py's contract).
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot && uv run pytest tests/test_reload.py -k "invalidat or refetch" -x -q && uv run pytest tests/test_reload.py tests/test_cache.py -q</automated>
  </verify>
  <done>
    A new daemon-level test in tests/test_reload.py drives the real `_do_reload(...,
    cache=cache)` with a changed location and asserts the next `cache.lookup` refetches
    (spy count goes 1 → 2). The full tests/test_reload.py and tests/test_cache.py suites
    pass. The test is distinct from the isolated `test_invalidate_clears_cache`.
  </done>
</task>

<task type="auto">
  <name>Task 3: Update the deploy README and Phase 11 deferral note to reflect cache invalidation is now wired</name>
  <files>deploy/README.md, .planning/phases/11-discord-inbound-gateway-bot/11-CONTEXT.md</files>
  <read_first>
    - deploy/README.md lines 203-227 (the "Reload behavior (inbound bot — known v1
      limitations)" section: first bullet = stale-forecast-up-to-TTL, second bullet =
      operator_id requires restart).
    - .planning/phases/11-discord-inbound-gateway-bot/11-CONTEXT.md lines 113-120 (D-12,
      whose parenthetical says "Planner to confirm exact placement/invalidation") and lines
      286-288 (the Deferred-section bullet "Wiring the scheduled briefing path to actually
      read the shared cache").
    - weatherbot/scheduler/daemon.py lines 1031-1045 (the in-code comment at ~1037 that
      currently reads "The scheduler-read seam stays UNWIRED (Q2/D-12)").
  </read_first>
  <action>
    Documentation-only edits reflecting that CR-01 is now closed (cache invalidation on
    reload is WIRED). Scope strictly to the FORECAST-CACHE staleness — do NOT remove or
    soften the separate `operator_id`-requires-restart limitation (that is WR-01, out of
    scope here and still a real v1 limitation).

    (1) deploy/README.md "Reload behavior" section: rewrite the FIRST bullet (the
    "Stale forecast for up to the cache TTL" / "intentional v1 deferral" bullet) to state
    that a successful reload now INVALIDATES the bot's `ForecastCache`, so the next
    `!weather <loc>` after a reload refetches against the new config (no stale-forecast
    window). Keep the section heading honest: since one limitation (operator_id) remains,
    leave the section but make clear the forecast-cache staleness is RESOLVED, not deferred.
    Adjust the closing "If you change either of these, restart…" line so it no longer
    implies the forecast-cache case needs a restart (only the operator_id case does).

    (2) 11-CONTEXT.md: in the D-12 entry (~line 119), replace the "(Planner to confirm exact
    placement/invalidation…)" parenthetical with a note that invalidation IS now wired —
    `_do_reload` calls `cache.invalidate()` best-effort after a successful swap (CR-01
    closed, quick task 260617-fua). In the Deferred-section bullet at ~line 286-288, mark
    that the BOT cache is now invalidated on reload (CR-01 resolved); if the bullet's
    broader point was about the SCHEDULED path reading the shared cache, keep that part as
    still-deferred but clearly separate it from the now-wired bot-cache invalidation. Do not
    rewrite unrelated decisions.

    (3) weatherbot/scheduler/daemon.py: update the stale in-code comment near line 1037 that
    says the cache "scheduler-read seam stays UNWIRED (Q2/D-12) — this cache is for the bot
    only for now" so it reflects that the cache is now invalidated on reload via `_do_reload`
    (CR-01), while noting the SCHEDULED-path READ seam remains unwired. (This is a comment
    edit only — no behavior change.)
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot && grep -n "invalidat" deploy/README.md && grep -n "CR-01\|invalidat" .planning/phases/11-discord-inbound-gateway-bot/11-CONTEXT.md && grep -n "invalidat" weatherbot/scheduler/daemon.py | grep -v "def invalidate"</automated>
  </verify>
  <done>
    deploy/README.md no longer frames the post-reload forecast-cache staleness as a v1
    deferral (it states invalidation is wired); the operator_id-restart limitation is
    untouched. 11-CONTEXT.md's D-12 and Deferred notes reflect that bot-cache invalidation on
    reload is now wired (CR-01 closed). The daemon's in-code "UNWIRED" comment is corrected.
  </done>
</task>

</tasks>

<verification>
- `grep -n "cache=cache" weatherbot/scheduler/daemon.py` and `grep -n "cache.invalidate"
  weatherbot/scheduler/daemon.py` both return a line (the wiring is present in run_daemon
  and the invalidate call is in `_do_reload`).
- `uv run pytest tests/test_reload.py tests/test_cache.py -q` passes, including the new
  daemon-level integration test.
- `uv run pytest -q` (full suite) stays green — no existing reload/cache/bot test regressed
  by the additive `cache=None` parameter.
- deploy/README.md and 11-CONTEXT.md no longer describe forecast-cache-on-reload as a
  deferral.
</verification>

<success_criteria>
- CR-01 closed: a successful config reload invalidates the bot's `ForecastCache`, so the
  next `!weather` refetches against the reloaded config (no stale forecast within the TTL).
- Invalidation is best-effort: a `cache.invalidate()` exception is logged and swallowed and
  never aborts the already-committed reload.
- Invalidation happens ONLY in the committed-success branch (after `holder.replace` +
  `_reconcile_jobs`), never on the validation-reject or rollback paths.
- A daemon-level integration test (distinct from the isolated `test_invalidate_clears_cache`)
  proves reload-with-a-changed-location forces the next `cache.lookup` to refetch.
- deploy/README.md "Reload behavior", the Phase 11 D-12/Deferred CONTEXT notes, and the
  daemon's in-code comment all reflect that cache invalidation on reload is now wired.
</success_criteria>

<output>
Create `.planning/quick/260617-fua-wire-forecastcache-invalidate-into-the-d/260617-fua-SUMMARY.md` when done.
</output>
