# Whole-Project Review — WeatherBot + YahirReusableBot

**Scope:** two repos — the **WeatherBot** consumer app (WB) and the shared **YahirReusableBot** hub
(HUB), which WeatherBot pins at tag `v0.1.1`. A handful of findings touch shared test/contract
surface and are tagged **BOTH**. This audit ran across **17 units** with **6 finders per unit**, a
**1-vote verification pass** over the top findings, and a **sweep pass on** to catch untriaged
defects (those carry verdict `SWEEP-NEW` and are unverified). Verified findings carry `CONFIRMED`
(reproduced) or `PLAUSIBLE` (mechanism real, trigger uncertain) with concrete evidence.

**HUB findings route upstream and are human-gated.** Anything under `yahir_reusable_bot/…` is a bug
in the shared hub. Per `ECOSYSTEM.md`, cutting a hub tag + repinning + deploying is a **human-gated**
step — surface it, do not ship it autonomously. Fix HUB defects in the hub checkout
(`../Reusable/YahirReusableBot`), then the human cuts the tag and repins WeatherBot.

After dedupe there are **116** distinct findings.

## Severity Summary

| Severity  | Count | WB | HUB | BOTH |
|-----------|------:|---:|----:|-----:|
| critical  |     2 |  2 |   0 |    0 |
| high      |    17 | 13 |   2 |    2 |
| medium    |    30 | 25 |   4 |    1 |
| low       |    58 | 40 |  10 |    8 |
| cleanup   |     9 |  8 |   1 |    0 |
| **total** | **116** | **88** | **17** | **11** |

Verdict mix: critical are both `SWEEP-NEW` (unverified — verify before acting). High is 6 `CONFIRMED`
+ 11 `SWEEP-NEW`. The bulk of `CONFIRMED` correctness bugs sit at medium.

## Fix First

The short list — the correctness defects with real user impact. Verify the two `SWEEP-NEW` criticals
first; the rest are `CONFIRMED`.

1. **F01 — `daemon.py:335` (WB, critical, SWEEP-NEW):** post-send bookkeeping runs inside the send `try`; a `database is locked` there releases the won claim → **silent duplicate briefing**. *Verify first.*
2. **F02 — `dispatch.py:119` (WB, critical, SWEEP-NEW):** bare `!weather` (no arg) never fetches → `result=None` → AttributeError → generic error. **Default-location is dead on Discord.** *Verify first.*
3. **F05 — `cli.py:986` (WB, high, CONFIRMED):** daemon `run` startup skips `assert_unique_names` + template validation → duplicate ids / typo'd templates boot green and silently drop briefings every morning.
4. **F06 — `selfcheck.py:116` (WB, high, CONFIRMED):** permanent config/template errors classified `NETWORK_NOT_READY` → daemon warn-loops forever, sends nothing, never alerts.
5. **F12 — `client.py:67/84` (WB, high, CONFIRMED):** `raise_for_status()` embeds `appid=<key>` in the exception; the Discord inbound path logs the traceback → **OpenWeather key leaks to logs.**
6. **F14 — `catchup.py:155` (WB, high, CONFIRMED):** catch-up only composes *today's* date → a late-evening slot missed across local midnight is silently lost.
7. **F15 — `uvmonitor.py:318` (WB, high, CONFIRMED):** all-clear latches on one momentary UV dip → user told "protect window over" while UV is peaking.
8. **F45 — `identity.py:149` (HUB, high, CONFIRMED):** `-m` argv match false-positives on `python -m pytest weatherbot` → `reload` can SIGHUP an unrelated recycled PID. *Routes upstream.*

---

## Critical

### F01 — `weatherbot/scheduler/daemon.py:335` · WB · SWEEP-NEW · send-atomicity/double-send
Post-send bookkeeping (`resolve_alert`/`stamp_success`) runs INSIDE the try after the briefing is already delivered; if it raises, the `except` releases the won claim and the slot re-fires → duplicate briefing.
*Scenario:* `claim_slot` wins (206), `send_now` POSTs the briefing, then `resolve_alert`/`stamp_success` open fresh sqlite connections against a DB being concurrently written by ~10 workers + heartbeat + UV monitor (no `busy_timeout` override, default rollback journal) → a `database is locked` OperationalError after the 5s timeout is realistic. Caught by the broad `except` at 345 with `claimed=True`, so `release_claim` (352) DELETEs the sent_log row. The user already got the briefing, but the slot is now re-fireable: catch-up (same local_date, within grace) or a restart sees `was_sent()==False` and delivers the SAME briefing again.

### F02 — `weatherbot/interactive/dispatch.py:119` · WB · SWEEP-NEW · integration/wrong-result-crash
A bare location-taking command (`!weather` with no arg) never fetches, so the handler receives `result=None` and crashes → generic error reply; the default-location feature is dead on the Discord surface.
*Scenario:* bare `!weather`/`!sun`/`!wind`/`!alerts`/`!uv`/`!next-cloudy` → `parse_command` arg=None, needs_flags=False. The `dispatch_spec` guard `if arg is not None or spec.needs_flags:` (76) is False, so `cache.lookup` is SKIPPED and result stays None. The bind closure then calls `weather_views.weather(None)` → `result.forecast` → AttributeError, caught by `on_message`'s envelope → generic "something went wrong". The documented default-location behavior (CLI's `run_weather` does `resolve_location(None)`) is broken over Discord. Root cause: the module has only a `needs_flags` signal, not a `takes_location` signal.

---

## High

### F05 — `weatherbot/cli.py:986` · WB · CONFIRMED · validation-gap/silently-dropped-briefing
Daemon `run` startup loads config via `load_config` only — never runs `assert_unique_names` or `validate_config_and_templates` that check-config and reload both enforce; duplicate names/ids and bad templates boot green. *(Merged: cli.py:986 dup-names + cli.py:986 template-validation + wiring.py:167 build_runtime-no-validation.)*
*Scenario:* two `[[locations]]` with different names but the SAME explicit id both register distinct jobs (job id keyed on name, 631) and both fire, but each fire claims on `location.id` (206) against `UNIQUE(location_name,send_time,local_date)`; first wins, second logs "slot skipped (already sent)" and never delivers — a silently missed briefing every morning. The same gap lets a typo'd template `{placeholder}` or missing template file boot green; at 9am `fire_slot`→`validate_template`/`load_template` raises, is swallowed, briefing silently missed daily.
*Evidence:* `_load_config_reporting`→`load_config` (loader.py:24-27) does only `tomllib.load` + `model_validate`; `build_runtime` calls `_register_jobs` directly; the validators are wired only into the ReloadEngine `validate` (reload-only) and selfcheck/check.

### F06 — `weatherbot/ops/selfcheck.py:116` · WB · CONFIRMED · selfcheck-false-classification
Permanent config/template/location errors (and empty-locations) are classified `NETWORK_NOT_READY`, so the daemon warn-loops forever, never sends, and never surfaces a hard failure. *(Merged: selfcheck.py:116 + selfcheck.py:80 empty-locations.)*
*Scenario:* a bad template placeholder, a duplicate name, an unresolvable location, or empty `[[locations]]` all fall into the bare `except Exception` (116-122) → `NETWORK_NOT_READY` → `to_health_result` maps to `Severity.WARNING` → ReadyGate re-probes every 120s forever, never emits READY=1, never starts the scheduler, never fires a briefing, never a critical alert. Reachable because daemon `run` (see F05) never validates these; the bot looks "alive but not ready" and silently sends zero briefings.

### F12 — `weatherbot/weather/client.py:67` · WB · CONFIRMED · injection/secret-leak
`raise_for_status()` raises an HTTPStatusError whose message embeds the full URL including `appid=<key>`, at both the onecall (67) and geocode (84) call sites — defeating the Pitfall-6 key-redaction claim. *(Merged: client.py:67 + client.py:84.)*
*Scenario:* on a 401/403, `str(HTTPStatusError)` = "...`appid=SECRETKEY123`&units=imperial". The mitigation (client.py:39 raising the httpx logger to WARNING) only silences INFO request logs, not the exception text. Reachable leak: Discord inbound `bot.py:492 dispatch_spec` → `lookup.py:117 fetch_onecall` (no httpx guard); an HTTPStatusError falls to `bot.py:506-507 except Exception: _log.exception(...)`, and structlog renders the full traceback (tail `appid=<key>`) to stderr — reproduced end-to-end. The scheduler/CLI fetch handlers log outcome-only and are safe; the genuine leaks are the Discord command path and the geocode CLI.

### F14 — `weatherbot/scheduler/catchup.py:155` · WB · CONFIRMED · timezone/date off-by-one
Catchup only composes TODAY's local date, so a late-evening slot missed across local midnight is never recovered.
*Scenario:* a 23:45 slot fails to fire and the daemon returns at 00:15 the next local day (30 min late, inside the 90-min GRACE). `plan_catchup` builds `naive=datetime(now_local.year,month,day,23,45)` using TODAY's date, so the recomputed instant is ~23.5h in the FUTURE and is skipped as "not due yet" (170, `scheduled > now_utc`). Yesterday's genuinely-missed 23:45 slot is never a candidate. Correct fix would also test the prior local day's instant against `now_utc - GRACE`.

### F15 — `weatherbot/scheduler/uvmonitor.py:318` · WB · CONFIRMED · wrong-condition/no-hysteresis
All-clear fires and latches on a single momentary instantaneous UV dip mid-day, permanently ending the protect window while it is still active.
*Scenario:* after a crossing is claimed, branch 3 gates only on `summary.current` (= instantaneous `current.uvi`). At solar noon a passing cloud makes one 15-min tick read UV 5.8 vs threshold 6.0 → `current < threshold and 'crossing' in prior and 'allclear' not in prior` is true → claims allclear (once/day, durable INSERT OR IGNORE) and posts "✅ UV back below 6 — protect window over." UV climbs back to 8 minutes later but allclear can never re-open. No hysteresis/window_end/persistence gate exists in branch 3.

### F45 — `yahir_reusable_bot/lifecycle/identity.py:149` · HUB · CONFIRMED · PID-recycling false positive · **ROUTES UPSTREAM**
The `-m` module match uses `proc_marker in argv[1:4]` (and assumes `-m` is argv[1]), so it both false-positives on `python -m <tool> weatherbot` and false-negatives when interpreter flags precede `-m`. *(Merged: identity.py:149 marker-as-arg + identity.py:149 flags-before-m; dead local dup is F46.)*
*Scenario:* `return b"-m" in argv[1:3] and proc_marker in argv[1:4]`. (a) FALSE POSITIVE: a recycled PID running `python -m pytest weatherbot` / `python -m http.server weatherbot` has the marker in argv[3], so both clauses are True and `weatherbot reload` delivers SIGHUP (terminate) to that unrelated process. (b) FALSE NEGATIVE: a daemon started with `python -W ignore -m weatherbot run` has argv[1:3] without `-m`, so a live daemon is reported NOT running and reload refuses to signal it. Fix: `len(argv)>=3 and argv[1]==b"-m" and argv[2]==proc_marker`.
*Evidence:* reproduced True for both decoys and the genuine `-m weatherbot run`; existing guard test only covers non-`-m` decoys.

### F03 — `weatherbot/scheduler/catchup.py:106` · WB · SWEEP-NEW · integration/recovery-ordering
Catch-up scan runs during `build_runtime` BEFORE the ReadyGate health gate, so missed slots fire before API key/network is confirmed and are never re-attempted. *(Merged with wiring.py:197 lifecycle-ordering.)*
*Scenario:* on a reboot where the OpenWeather key is still propagating (the "~2h activation" case the gate exists for) or the network is briefly down, `plan_catchup`'s `fire_slot` fetches, gets a 401/timeout, exhausts its two-burst retry, releases the claim, and fires a failure alert for EVERY missed slot — all before `ready_gate.run()` (daemon.py:1465). When the gate later passes, catch-up does not run again (it ran once at wiring.py:197), so every recoverable missed briefing is permanently lost, replaced by an alert. Also fires before the SIGTERM handler is installed (1418).
*Evidence:* ordering CONFIRMED (build_runtime 1389 → catch-up wiring.py:197 → SIGTERM handler 1418 → ready_gate 1465). The recovery-loss verdict is sweep-unverified.

### F04 — `weatherbot/scheduler/daemon.py:235` · WB · SWEEP-NEW · signal/interruptibility · **root in HUB**
`sleep=stop_event.wait` does NOT abandon the schedule on shutdown — tenacity discards `wait()`'s return, so SIGTERM drains all remaining ~16 attempts back-to-back at zero delay. *(Merged with HUB retry.py:241; the fix lands in the hub.)*
*Scenario:* on SIGTERM the daemon sets `stop` mid-retry. tenacity does `self.sleep(do)` and IGNORES the boolean return; `Event.wait` returns True immediately but tenacity proceeds to the next attempt and every subsequent pause is also zero-length, firing the full remaining burst of `send_now` attempts back-to-back during shutdown — a rapid volley of OpenWeather/Discord calls. Contradicts the D-07/Pitfall-1 "abandon instantly" guarantee. Fix: a wait wrapper that stops when the event returns True. **Routes upstream (hub retry.py:241).**

### F07 — `weatherbot/scheduler/wiring.py:305` · WB · SWEEP-NEW · lifecycle regression
One-time Discord online-ping moved to BEFORE the systemd READY=1 emit, so a slow/hung webhook delays readiness and systemd can kill the still-starting service.
*Scenario:* original `emit_online` fired `notifier.ready()` (READY=1) BEFORE `channel.send(ping)`. In the refactor the ping runs INSIDE `_on_online` (305-313) and ReadyGate calls `notifier.ready()` only AFTER `_on_online` returns. A slow/hanging Discord POST at startup now blocks READY=1; if it exceeds TimeoutStartSec systemd treats the service as failed and kills/restarts it. Fix: emit ping after `notifier.ready()`.

### F08 — `weatherbot/scheduler/daemon.py:518` · WB · SWEEP-NEW · send-failure not detected
`fire_forecast_slot` ignores the DeliveryResult from `channel.send()`, so a Discord non-2xx delivery failure counts as success and resets the failure streak.
*Scenario:* a forecast slot posts and Discord returns non-2xx (400/413/429-exhausted). `_post` maps to `DeliveryResult(ok=False)` and NEVER raises, so control falls through to `_note_forecast_success()` which resets the streak. The forecast is never delivered, yet `_note_forecast_failure` / the WR-05 dead-slot CRITICAL + operator alert never fire (they only run in the except branch). A chronically-dead forecast slot failing via ok=False stays completely silent. Sibling `fire_slot` DOES inspect `result.ok`; this path does not.

### F09 — `weatherbot/cli.py:934` · WB · SWEEP-NEW · error-handling
`load_settings()` is called unguarded in every command path; a missing/malformed env secret crashes with a raw pydantic traceback, violating the CLI's clean-failure contract.
*Scenario:* a first-run user runs any command with an incomplete `.env` (e.g. `DISCORD_BOT_TOKEN` unset — a REQUIRED Settings field geocode/weather never use). `load_settings()` raises pydantic ValidationError, NOT caught anywhere (ValidationError is only wrapped around `load_config` at 585 and check-config at 971), so the process dies with a raw stack trace. Asymmetric: config.toml typos fail cleanly, `.env` typos traceback.

### F10 — `weatherbot/weather/store.py:143` · WB · SWEEP-NEW · concurrent read/write race
"READ-ONLY" functions take a write lock every call — `_SCHEMA` runs INSERT OR IGNORE on every connect, so a status read during a daemon write can raise `database is locked`.
*Scenario:* `read_heartbeat`/`read_health`/`was_sent`/`claimed_uv_kinds` all call `conn.executescript(_SCHEMA)` on connect, and `_SCHEMA` ends with two `INSERT OR IGNORE INTO heartbeat/health`. `executescript` force-commits and the INSERTs acquire a RESERVED/write lock, so a status read fired while the daemon is mid-write can raise `sqlite3.OperationalError: database is locked` after the default 5s busy timeout — even though the docstrings claim "READ-ONLY: writes nothing".

### F107 — `tests/test_models.py:90` · BOTH · SWEEP-NEW · missing-coverage
Briefing `from_payloads` is never tested for dt-based imperial/metric daily pairing — only the forecast path is.
*Scenario:* `models.py:302-303` pairs imperial daily[0] with metric daily[0] POSITIONALLY. The forecast path has an explicit dt-pairing guard test; the daily-briefing high/low/rain/uvi has no equivalent. If a live metric fetch returns a daily[] whose index 0 is a different local day (length/ordering skew), the briefing renders a °C high paired to the wrong day's °F and every existing test passes (fixtures are pre-aligned). Relates to F11.

### F108 — `tests/test_scheduler.py:491` · BOTH · SWEEP-NEW · missing-coverage
The rename-safe `Location.id != name` path is never driven through `fire_slot` / `plan_catchup` / alert-dedup.
*Scenario:* `fire_slot` keys claim/release/record/resolve on `location.id` while logging `location.name`; `plan_catchup` keys `was_sent` on `loc.id`. `Location.id` defaults to name and EVERY scheduler/reliability/catchup test uses id==name. No test constructs a Location with an explicit id ≠ name. A regression keying any one path on `.name` would double-send or lose dedup after a rename, uncaught. Relates to F36.

### F11 — `weatherbot/weather/models.py:424` · WB · SWEEP-NEW · cross-unit data loss
`high/low_display` falls back to current temp when only the METRIC daily field is missing, discarding a valid imperial high.
*Scenario:* `high_imp`/`high_met` are read independently from imperial vs metric daily[0] (370-373). If the metric payload's daily[0].temp is partial/missing while imperial has a real max, `high_met` is None so `high_display` (424: `if high_imp is None or high_met is None`) throws away the valid imperial high and shows the current temp as today's high. The day's real high is silently lost even though it was fetched in one unit.

### F13 — `weatherbot/interactive/cache.py:119` · WB · SWEEP-NEW · cache-invalidation-race
An in-flight fetch that started before `invalidate()` re-populates the cache with a pre-reload (stale) result, surviving until TTL.
*Scenario:* tap → cache miss → `lookup_weather` runs off-loop WITHOUT the lock. While in flight, a config hot-reload commits and calls `cache.invalidate()`, clearing the dict. The in-flight fetch then completes and does `self._cache[key] = result` (119), re-inserting a result computed against the OLD config (old lat/lon/units/template). `invalidate()` has no epoch/generation guard, so the stale entry is served for up to ~10 min. Since `resolve_location` keys on `Location.id`, if the id survived the rename the stale entry masks the reloaded config entirely.

### F94 — `yahir_reusable_bot/reliability/retry.py:87` · HUB · SWEEP-NEW · transient classification · **ROUTES UPSTREAM**
`is_transient` misses common transient httpx failures (`RemoteProtocolError`, `WriteError`), so they are NOT retried.
*Scenario:* `is_transient` only matches `TimeoutException`, `ConnectError`, `ReadError`. `httpx.RemoteProtocolError` ("Server disconnected without sending a response") and `httpx.WriteError` are sibling NetworkError/ProtocolError subclasses NOT in the tuple. A server hangup mid-response — routine for OpenWeather/Discord — falls through `is_transient()==False`, so the retry predicate does not fire, the whole two-burst schedule is skipped, and `fire_slot` records `reason=internal_error` instead of retrying. Realistic network blips silently miss the briefing with the wrong alert reason. Fix: catch `httpx.TransportError` or `NetworkError`.

---

## Medium

### F17 — `weatherbot/scheduler/wiring.py:213` · WB · CONFIRMED · swallowed-error/ordering
`on_applied` calls `channel.send` before `cache.invalidate`, so a slow/blocking Discord post delays the ForecastCache invalidation the inbound bot relies on. After a committed reload that changes a location's coords, an inbound `!weather <loc>` served during the blocked send returns the OLD coordinates' forecast until `invalidate()` finally fires. *Evidence:* wiring.py:215 send before :220 invalidate; discord `_post` with `rate_limit_retry=True` can sleep-retry; cache keyed on Location.id, 600s TTL, same instance handed to the inbound bot.

### F20 — `weatherbot/scheduler/uvmonitor.py:257` · WB · CONFIRMED · never-fire gap
If UV already crossed up earlier while the bot was down and is now below threshold, no branch claims `crossing`, so all-clear can never fire — the day is silently skipped. First afternoon tick after the up-cross elapsed with current below threshold: branch 1 (current≥threshold) false, branch 2 (future crossing) false, branch 3 needs a claimed crossing. *Evidence:* reproduced `_decide` → `sent=[] claimed=set()`; no test covers this.

### F22 — `weatherbot/scheduler/wiring.py:452` · WB · CONFIRMED · stale-read/cache-invalidation
`SelectedContext` is seeded once at wiring and never reconciled on hot-reload; a renamed/removed selected location leaves a stale value the dropdown no longer shows as selected. Tapping a location-taking button without re-selecting passes the stale name to `resolve_location` → UnknownLocationError for a location the user never sees selected. *Evidence:* wiring.py:452 seed never reset in reload path; default flag uses stale value (panel.py:226).

### F25 — `weatherbot/interactive/command.py:167` · WB · CONFIRMED · zero/empty edge
Bare `+` or `-` flag token yields `_day_token('')` → ValueError, surfacing as the generic error reply instead of the actionable flag message. `!weekday-forecast home -` → `'-'.lstrip('-')==''` → `_day_token('')` raises a plain ValueError → outer `except` → "Sorry — something went wrong" instead of "use one of [...]". *Evidence:* reproduced.

### F26 — `weatherbot/interactive/command.py:172` · WB · CONFIRMED · flag-grammar footgun
A long-form `--sat`/`--mon` day flag is only ever treated as a DROP, never an ADD, because `--` matches the elif-`-` branch. `!weekday-forecast home --sat` → `add=set(), drop={'sat'}` — the day the operator asked to ADD is silently dropped, wrong forecast, no error. Since `--compact`/`--detailed` are documented equivalents of `+compact`/`+detailed`, a user extrapolating `--X == +X` gets a silent DROP. *Evidence:* reproduced.

### F29 — `weatherbot/interactive/commands/weather_views.py:233` · WB · CONFIRMED · inverted/wrong-condition
`next_cloudy` near-term loop silently drops every night-time cloudy hour, so a fully nocturnal cloudy stretch is never reported and falls through to daily days 3-8. `!next-cloudy` at threshold 60 while tonight is fully overcast (22:00-05:00): every qualifying overnight bucket fails `_is_daytime` and is skipped; daily fallback skips today/tomorrow (`daily[2:]`). *Evidence:* line 230 threshold, 233 `_is_daytime` gate, 244 `daily[2:]`; no test covers a nocturnal-only stretch.

### F30 — `weatherbot/weather/uv.py:135` · WB · CONFIRMED · timezone/day-window filter bypass
`sunrise<=ts<=sunset` compares the RAW `ts` (not `int(ts)`); a valid-but-string epoch bypasses the daytime window entirely. A numeric-string dt passes `int(ts)` at 127 (date filter works) but at 135 `sunrise <= "1720000000"` raises TypeError, caught at 137 and treated as in-range → a pre-sunrise/post-sunset bucket leaks in, inflating peak/window and yielding an early crossing_time. *Evidence:* 118 raw ts, 127 int into a local temp (no reassign), 135 compares raw; reproduced TypeError caught as "in-range".

### F39 — `yahir_reusable_bot/config/reload.py:150` · HUB · CONFIRMED · giving-up-without-alerting · **ROUTES UPSTREAM**
PHASE-2 reconcile failure rolls back and re-raises but never fires `on_rejected`, so a reconcile-time reload failure produces no rejection alert. A job id failing to (de)register during `_reconcile` rolls back + restores + logs + re-raises, but unlike PHASE-1 it never calls the reject hook, so the operator's Discord "config reload rejected" never fires. The common cause (malformed edited config) is a PHASE-1 failure and DOES alert; this is the narrower reconcile-failure path. *Evidence:* PHASE-1 fires reject hook (138) then raise; PHASE-2 (146-158) no reject hook.

### F41 — `yahir_reusable_bot/discord/gateway.py:167` · HUB · CONFIRMED · non-atomic write/resource leak · **ROUTES UPSTREAM**
`summon_panel` create-before-delete + Forbidden-only catch: `pin()` or `old.delete()` raising a non-Forbidden error leaves duplicate live pinned panels and can leave the fresh panel unpinned. *(Merged: gateway.py:166/167/171/180.)* An `old.delete()` raising NotFound/HTTPException bypasses the Forbidden catch, aborts remaining deletes, and leaves 2+ live pinned panels — and since `add_view` registers by static custom_id, taps on stale panels still route. On a channel at Discord's 50-pin cap, `msg.pin()` momentarily hits 51 and raises HTTPException, also uncaught, leaving the fresh panel unpinned. Fix: delete-then-pin (or reserve headroom) + per-item try/except catching HTTPException/NotFound. *Evidence:* verified NotFound/HTTPException are siblings of Forbidden, not subclasses.

### F44 — `yahir_reusable_bot/registry/match.py:61` · HUB · CONFIRMED · off-by-one/unicode · **ROUTES UPSTREAM**
The arg substring is sliced from the raw string using the folded keyword length, so a casefold that changes length misaligns the slice. `casefold()` is not length-preserving ('ß'→'ss'); `match_command('ßtatus arg', [spec 'sstatus'])` → `spec=None` because `stripped[7:]` cuts the 10-char raw string mid-token. UNREACHABLE on WeatherBot (all spec names lowercase ASCII) — a generic hub-matcher bug. *Evidence:* reproduced both the 'ß' and ligature cases.

### F54 — `weatherbot/cli.py:419` · WB · CONFIRMED · error-handling
`do_geocode` only catches `HTTPStatusError`; a transient timeout/connect error crashes with a raw traceback. `weatherbot geocode "..."` while OpenWeather is slow raises `httpx.TimeoutException`, not rescued anywhere → uncaught traceback, violating the CLI's "never a raw traceback" contract that sibling handlers uphold. One-shot setup command (downgraded high→medium).

### F55 — `weatherbot/cli.py:426` · WB · CONFIRMED · exit-codes
`geocode` returns exit 1 for both a successful zero-match query (428) and a hard HTTP/auth failure (424) — indistinguishable. A caller checking `$?` cannot tell "that place doesn't exist" from "your key is invalid", so setup tooling reports the wrong remediation. Contradicts the file's own exit-code convention (383-385).

### F24 — `weatherbot/interactive/panel.py:248` · WB · PLAUSIBLE · interaction race/non-atomic ack
`LocationSelect.callback` mutates the shared selection BEFORE acking, so a failed/expired `edit_message` leaves selection changed with no visible re-render. `self._selection.set(...)` (248) commits before the ack at 252; on failure `_safe_error_edit` posts the generic error but the selection silently advanced. Requires the ack to fail on a fresh 3s token — edge case; recoverable by re-selecting.

### F34 — `weatherbot/weather/models.py:536` · WB · PLAUSIBLE · null/None deref
ForecastDay feels-like high/low: `max()`/`min()` over daypart values crashes when any daypart is present-but-null, violating T-13-01 "degrade not raise". `.get('feels_like') or {}` guards only a missing whole dict; a single null member (`{'day':70,'night':None,...}`) makes `max()` raise TypeError. Bounded: both entry paths wrap it in a non-propagating envelope, so no crash — the partial-null day drops/errors that forecast reply (recoverable) instead of degrading feels-like to ''. *Evidence:* reproduced the TypeError.

### F40 — `yahir_reusable_bot/discord/gateway.py:273` · HUB · PLAUSIBLE · async misuse/unhandled disconnect · **ROUTES UPSTREAM**
No reconnect supervisor: a non-recoverable disconnect from `client.start` permanently kills the interactive bot with no retry. `_amain` runs `async with self._client: await self._client.start(token)` with no retry loop; discord.py's `reconnect=True` absorbs blips, but a non-recoverable disconnect escapes, sets `_failed=True`, ends the thread, and `is_alive()` stays False forever. The consumer calls `bot.start()` once and never polls to respawn. Bounded by failure isolation: scheduled briefings run on a separate thread. Death requires a non-recoverable disconnect (less common than "any blip").

### F109 — `tests/test_models.py:156` · BOTH · SWEEP-NEW · missing-coverage
`from_payloads` blindly takes daily[0] with no assertion it is the location-local TODAY. No test feeds a payload whose daily[0].dt is a PAST local date and asserts the high/low corresponds to the configured-tz today; a stale daily[0] would ship yesterday's high/low labelled as today's, uncaught. Relates to F35.

### F18 — `weatherbot/scheduler/wiring.py:234` · WB · SWEEP-NEW · logging divergence
`on_rejected` reload closure omits the stdlib-logger reject line the in-place path emits, so a rejected SIGHUP reload is under-reported in the journal. The in-place `_do_reload` logs both `_log.error` and `_stdlog.error`; the wiring closure (256) only posts to the channel and the ReloadEngine reject path (reload.py:134) emits only structlog — the journal "reload rejected" line disappears.

### F19 — `weatherbot/scheduler/uvmonitor.py:298` · WB · SWEEP-NEW · wrong-behavior/false-alert
`value_close` prewarn fires with no rising/future-crossing guard — both when UV never reaches threshold today (stays_below) and when UV has already peaked and is descending. *(Merged: two value_close scenarios.)* `value_close = (threshold - current) <= margin` has no `not stays_below` and no rising guard (unlike time_close), so it posts "UV nearing 6 — sunscreen soon" on a day that never crosses, or in the post-peak descent when the window is effectively over.

### F21 — `weatherbot/scheduler/uvmonitor.py:167` · WB · SWEEP-NEW · stuck-state/missed-allclear
`daily0`-date-mismatch skip also suppresses the daylight-independent all-clear, stranding the day's lifecycle. Near a tz/DST/midnight boundary daily[0] resolves to the prior day → `_daily0_matches_today` False → early return at 167 before computing prior/all-clear. If a `crossing` was claimed earlier today, WR-01 requires the all-clear to still close the day; this blocks it. Same structural gap as F58, distinct trigger.

### F23 — `weatherbot/interactive/panel.py:252` · WB · SWEEP-NEW · error-handling-asymmetry
Select/command callback re-render crashes inside `_safe_error_edit` when config was hot-reloaded to zero locations, leaving the panel stuck on the disabled cue. `edit_message(view=_build_clone_view())` raises (fail-loud on empty locations); `_safe_error_edit` ALSO calls `_build_clone_view()` → same ValueError → swallowed → only a log. Panel frozen with no user-visible recovery.

### F27 — `weatherbot/interactive/bot.py:504` · WB · SWEEP-NEW · UI-inconsistency
Inbound `!weather <loc>` replies never render the 📍 location indicator because `render_embed` is called with no `location=`, diverging from the panel which always passes it. `!weather London` suppresses the 📍 even though the user named a location, while the panel path (via `_render_bridge`) shows it — a D-07 parity drift on the location header.

### F28 — `weatherbot/interactive/commands/forecast.py:165` · WB · SWEEP-NEW · duplicated header
Forecast reply duplicates its title: `CommandReply.title` AND the rendered body's first line are both "{title} — {location}". Discord shows the embed title AND again as the first body line; the CLI `render_text` duplicates it too. Frozen into the golden snapshot. Appears twice on every forecast reply on both surfaces.

### F31 — `weatherbot/weather/uv.py:133` · WB · SWEEP-NEW · cross-file-integration
`compute_uv` trusts daily[0].sunrise/sunset without verifying daily[0]'s local date == today; the briefing consumer lacks the WR-05 guard the monitor has. Near a boundary daily[0] can be YESTERDAY, so its sunrise/sunset epochs are ~86400s in the past → every today bucket has `ts > sunset` and is filtered out → the morning briefing silently reports `stays_below=True` / empty UV window even when UV will exceed threshold.

### F32 — `weatherbot/weather/uv.py:159` · WB · SWEEP-NEW · date-ordering
Crossing/window interpolation assumes hourly points are time-sorted, but `_today_daytime_points` appends in raw payload order with no sort. If a provider returns hourly[] out of order (or a DST fall-back duplicates an hour), the interpolation straddles the wrong pair and emits a bogus crossing_time/window; peak (via max) stays correct, masking the desync.

### F33 — `weatherbot/weather/models.py:84` · WB · SWEEP-NEW · timezone/correctness
`_local_date_iso` silently uses host-local tz when `now_utc` is naive. `now_utc` is injectable; a naive datetime makes `astimezone()` interpret it in the HOST's tz, not UTC, so near midnight on a host whose tz ≠ UTC the computed local_date (the {date} token and tz-day boundary) is off by a day — a wrong-day briefing with no error.

### F36 — `weatherbot/weather/store.py:216` · WB · SWEEP-NEW · key collision/cross-file
`weather_onecall.location_name` stores `location.name` while sent_log/alerts/uv_alerts key on `location.id` — the analysis table is NOT rename-safe. When a config sets id ≠ name (or renames), the deferred v2 forecast-vs-actual join has no stable key linking rows, and a rename silently splits a location's onecall history across two `location_name` values with no migration.

### F37 — `weatherbot/weather/store.py:207` · WB · SWEEP-NEW · untested data-loss path
`persist` writes to `weather_onecall` which has NO UNIQUE constraint — retries/double-fires insert duplicate rows for the same fetch. A manual send-now overlapping a daemon fire, or any re-delivery, calls `persist()` again and inserts a second imperial+metric pair for the same slot/day; the v2 accuracy join then double-counts. Unlike sent_log/alerts (INSERT OR IGNORE against a UNIQUE key), persist has no dedup guard.

### F47 — `weatherbot/cli.py:648` · WB · SWEEP-NEW · error-handling
Registry commands (sun/wind/alerts/forecast/etc.) call `lookup_weather` with NO transient-retry wrapper, unlike `weather` which retries 3x. A single transient blip during `weatherbot sun home` exits 3 immediately, while the same blip during `weatherbot weather home` recovers via `stop_after_attempt(3)`. Sibling read-only commands have inconsistent resilience for identical failures.

### F48 — `weatherbot/channels/discord.py:115` · WB · SWEEP-NEW · auth misclassified as transient
A Discord 401/403 (revoked/invalid webhook) is returned as a generic `ok=False`, so the daemon retries a permanent auth failure for the full ~65-min schedule and alerts the wrong reason. `_post` maps ALL non-2xx (incl. 401/403) to `ok=False` and never raises, so `is_auth_failure` never sees it; the retry burns all attempts (~65 min incl. the 45-min mid-pause) then records `reason=transient_exhausted` instead of `auth_failed`. Contrast the fetch path, which short-circuits 401/403.

### F91 — `weatherbot/scheduler/catchup.py:170` · WB · SWEEP-NEW · timezone/DST math
DST fall-back slots are composed at fold=0 only, so the grace/dueness math uses the EARLIER of the two repeated wall-clock instants and can mis-window catch-up. On a fall-back day `naive.replace(tzinfo=tz)` defaults to fold=0, so `scheduled` is the pre-transition instant while the live CronTrigger may use fold=1; a restart inside the repeated hour inflates `now_utc - scheduled` by up to 60 min, so a slot only minutes late can exceed the 90-min GRACE and be silently dropped (saved from double-send only by claim_slot dedup).

---

## Low

### F106 — `tests/test_scheduler.py:491` · BOTH · CONFIRMED · false-green-naming
`test_concurrent_double_fire_delivers_once` runs the two fires SEQUENTIALLY, never concurrently — the store-atomicity race is unproven. A weakening of `claim_slot` to SELECT-then-INSERT would still pass green. The atomicity actually lives in `store.py:282-288` INSERT OR IGNORE + UNIQUE — not what this test protects.

### F110 — `tests/test_reliability.py:547` · BOTH · CONFIRMED · missing-coverage
No test covers a Retry-After 429 landing on the mid-pause attempt (attempt==BURST_SIZE), where `two_burst_wait` collapses the 45-min pause to the 120s cap. Every Retry-After test fires the 429 on attempt 1. Reproduced the collapse (2700→120). By-design clamp; coverage gap.

### F111 — `tests/test_multiday.py:157` · BOTH · CONFIRMED · missing-coverage
multiday weekend-block roll-forward is never tested; the whole-block-past branch is dead in tests for kind='weekend'. *(Merged with test_multiday.py:168.)* No test runs kind='weekend' on Mon-Thu; the mid-block-drop and horizon-notice weekend behavior have zero assertions on the two-city bot's load-bearing weekend selector. Code currently correct — quality gap.

### F112 — `tests/test_reliability.py:100` · BOTH · CONFIRMED · weak-assertion
`test_two_burst_wait_shape` asserts within-burst wait `< 150.0` but the real jittered ceiling is `step*1.5 ≈ 128.6s` — the loose bound hides a ~17% regression. The file's own line 294 already uses the tight `< step*1.5` for the same quantity.

### F113 — `tests/test_multiday.py:107` · BOTH · CONFIRMED · missing-coverage
`test_null_fields_coalesce` covers all-null daily fields but not a null 'dt' in the date-index map, the one field `select_days` indexes on. A regression changing the guard to `if not dt` (dropping dt==0) or removing the None skip (TypeError in fromtimestamp) would not be caught.

### F114 — `tests/test_reliability.py:606` · BOTH · CONFIRMED · weak-assertion/heartbeat
`test_heartbeat_upsert` asserts `last_tick_utc is not None` but never asserts `last_success_utc` stays None on a bare tick — the tick/success separation is unpinned. A regression where `_heartbeat_tick` also stamped success (making a never-delivered daemon look healthy) would pass green.

### F51 — `weatherbot/interactive/lookup.py:143` · WB · CONFIRMED · timezone/clock read
`lookup_weather` bakes {sent_at}/{checked_at} from `datetime.now(tz)` at render time, so a cached LookupResult served within TTL shows a stale timestamp. Cache at 09:00, repeat at 09:09 → the cached text still shows 09:00 with no cached-read indicator. Cosmetic.

### F53 — `weatherbot/scheduler/wiring.py:301` · WB · CONFIRMED · framework footgun/ordering
`scheduler.start()` runs inside the best-effort `on_online` hook whose exceptions ReadyGate swallows, so a `start()` failure is hidden yet READY=1 is still emitted. A raise (double-drive AlreadyRunning / executor init) is swallowed, online stamps/tick/ping never run, yet READY=1 reaches systemd — a healthy unit with a dead scheduler. Not reachable on the normal single-drive path — latent-but-severe-if-hit.

### F56 — `weatherbot/scheduler/daemon.py:176` · WB · CONFIRMED · swallowed-error
`fire_slot` exception before `local_date` is computed swallows the failure with NO missed-briefing alert. An exception between entry and 199 (bad tz at 193, or ValueError at 191) leaves `local_date=None`, so the outer handler (gated on `local_date is not None`) logs only, no `briefing_missed` CRITICAL. Both triggers narrow (tz config-validated; ValueError arm unreachable from the real caller).

### F58 — `weatherbot/scheduler/uvmonitor.py:154` · WB · CONFIRMED · zero/None edge
Missing sunrise OR sunset silently skips the entire location decision including the daylight-independent all-clear. `if sunrise is None or sunset is None: return True` sits above `_decide`/branch 3; a location that claimed `crossing` earlier and then loses sun fields (schema drift) never gets its all-clear. Guard is `is None` not falsy, so polar sunrise==0 does NOT hit it — narrow. Missed courtesy all-clear, not a missed warning.

### F63 — `weatherbot/weather/store.py:203` · WB · CONFIRMED · non-atomic multi-step write
"Keeps schema + data atomic" comment is false — `executescript()` force-commits before the inserts. Verified: a row inserted before `executescript` survives a subsequent rollback. Low risk here (executescript runs first) but any future edit interleaving a write before it silently loses transactional grouping.

### F70 — `weatherbot/weather/multiday.py:116` · WB · CONFIRMED · inverted semantics
An 'add' token that is also in 'drop' is silently re-added (add loop is unconditional), so drop cannot override an explicit add of the same day. `+sat -sat` → line 96 removes sat from base, but the add loop (115-117) re-adds it. Reproduced: `select_days(add={'sat'},drop={'sat'})` returns Saturday. Contradictory input, ambiguous intent, no crash.

### F73 — `weatherbot/weather/uv.py:235` · WB · CONFIRMED · rounding — peak/max disagreement
`peak_uvi` is the hourly argmax value which can disagree with (undershoot) `max` read from daily[0].uvi — a briefing can show "Today's max 8" and "peak 7 at 13:00" together. A deliberately-documented WR-02 trade-off (peak value+clock coherence over peak/max agreement); both values rounded so a visible mismatch is a narrow cosmetic edge.

### F74 — `weatherbot/config/models.py:63` · WB · CONFIRMED · lax-parse
The HH:MM validator accepts `int()`-parseable oddities (leading sign / whitespace) because `len==2` does not exclude them. `+9:30` / ` 9:30` are accepted and STORED raw; `parsed_time()` re-parses correctly so no mis-fire, but the non-canonical string is echoed to logs/announce/--check and used as a job-id/sent-log key (internally consistent). Cosmetic/latent.

### F77 — `weatherbot/cli.py:938` · WB · CONFIRMED · exit-codes
`check` returns exit 1 on bad config while `weather`/registry commands return 2 for the same failure. A monitoring wrapper keying off exit 2 == 'bad config' misclassifies a check-command config failure. Both schemes documented as intentional; latent cosmetic cross-command inconsistency.

### F78 — `weatherbot/cli.py:1030` · WB · CONFIRMED · dispatch
`send-now` is reached only via an implicit final fallthrough that reads `args.location` unconditionally. Today only send-now arrives, but a future subcommand added without an early-return and without a `location` attribute would run the full send pipeline for it and/or AttributeError. Latent ordering footgun.

### F79 — `weatherbot/interactive/bot.py:455` · WB · CONFIRMED · inverted/narrow condition (UX)
`!panel` is matched only by exact `content.strip() == "!panel"`; any trailing text routes to the registry and is silently dropped. `!panel please` → 'panel' not a registered keyword → `parsed.spec is None` → returns with NO reply — total silence for a near-miss of the highest-value write command. Same silent-drop applies to any unknown `!foo`.

### F99 — `yahir_reusable_bot/registry/match.py:59` · HUB · CONFIRMED · degenerate spec + case-sensitivity · **ROUTES UPSTREAM**
`match.py` compares against `spec.name` verbatim while folding the input: an empty name matches every input, and any uppercase in a registered name makes the command permanently unmatchable. *(Merged: empty-name catch-all + uppercase-name unmatchable.)* No consumer hits it (all WeatherBot names lowercase ASCII, none empty); undocumented precondition, footgun for a future/reuse app.

### F103 — `weatherbot/scheduler/wiring.py:306` · WB · PLAUSIBLE · defensive over-guard
`on_online` treats `send()` as possibly returning None (`getattr(...,'ok',True)`), but the Channel contract mandates `send() -> DeliveryResult`, masking a real channel bug. A future channel returning None on failure would be silently treated as delivered=ok, skipping the "online ping not delivered" WARNING. Blast radius: a single missed WARNING on a best-effort ping.

### F35 — `weatherbot/weather/models.py:302` · WB · PLAUSIBLE · wrong local-date/tz bucket
`from_payloads` hard-indexes daily[0] as 'today' but One Call daily[0] is keyed to the API's own tz day-boundary, which can differ from the configured IANA tz near midnight. Only diverges when the configured tz ≠ the point's real tz (no cross-validation exists) — off the common path, misconfig-dependent. The multi-day path refuses positional indexing; single-day lacks that defense.

### F38 — `weatherbot/scheduler/daemon.py:631` · WB · PLAUSIBLE · duplicate-work
Job id keys on RAW `slot.days` while the trigger uses normalized `day_of_week`, so two textually-different-but-equivalent slots create two jobs firing the same time. The claim runs BEFORE any fetch/render, so the loser does zero API calls — only a no-op INSERT + a "slot skipped" log (finding's "both fetch" claim refuted). Latent duplicate-work footgun; nothing detects trigger collapse.

### F42 — `yahir_reusable_bot/discord/gateway.py:244` · HUB · PLAUSIBLE · race/resource leak · **ROUTES UPSTREAM**
`stop()` reads `self._loop` and checks `is_running()` with a TOCTOU gap; if the loop stops between check and `run_coroutine_threadsafe`, RuntimeError escapes `stop()`. Refuted consequences: the only caller wraps `stop()` in try/except (no host crash) and the client already closed via `async with` (no leak). Latent robustness nit.

### F43 — `yahir_reusable_bot/discord/selection.py:49` · HUB · PLAUSIBLE · race/async misuse · **ROUTES UPSTREAM**
`SelectedContext` single-writer assumption is violated by interleaved `on_command` awaits: a Select tap during an off-loop fetch changes the render-arg location label. In the consumer forecast path, `render_arg=selection.value` is re-read after the await; a Select tap mid-fetch yields an embed whose DATA is location A but whose 📍 label is location B — a mismatched label, not wrong weather data. Mitigated by the pre-await disable guard.

### F49 — `weatherbot/interactive/cache.py:116` · WB · PLAUSIBLE · redundant-fetch
Each forecast suffix key triggers its own dual OpenWeather fetch of the identical One Call payload. A documented, bounded tradeoff (the suffix "never causes an extra fetch beyond the first miss for each key"); the exactly-one-fetch claim applies only to repeated `!weather <same loc>`, which holds. Bounded against the 60/min & 1M/month quota.

### F50 — `weatherbot/interactive/cache.py:61` · WB · PLAUSIBLE · eviction of weather entries
`maxsize=16` is shared across weather + every forecast suffix, so heavy forecast/CLI flag use can evict the plain weather entry it was meant to protect. Latent for the 2-location deployment (~10 keys < 16 → no eviction); degrades as usage widens.

### F52 — `weatherbot/scheduler/wiring.py:234` · WB · PLAUSIBLE · config->runtime mapping
Reload closures wrap cfg in a fresh transient `ConfigHolder` instead of the live holder, a latent identity-divergence smell with no reachable wrong behavior today. `reload.py._reconcile` always re-registers the current post-swap config and keeps the live holder current via `replace`, so both always carry the same value. No current trigger; downgraded from medium.

### F57 — `weatherbot/scheduler/daemon.py:108` · WB · PLAUSIBLE · resource-exhaustion
A broad OpenWeather outage can pin most APScheduler workers in long retry pauses (~75 min each), starving heartbeat/other slots. Not reachable at 2-slot scale; `misfire_grace_time=None` means the heartbeat is DELAYED not skipped. Latent design edge.

### F59 — `weatherbot/scheduler/uvmonitor.py:81` · WB · PLAUSIBLE · boundary at sunset instant
`_is_daylight` uses inclusive `<=` at both ends, so a crossing/pre-warn can fire at the exact sunset instant. Trigger essentially unreachable (landing on the exact epoch-second of sunset AND UV≈0 at that moment). Documented inclusive `[sunrise,sunset]` convention; arguably cleanup.

### F62 — `weatherbot/weather/models.py:362` · WB · PLAUSIBLE · falsy coalesce
Pervasive `.get(x) or 0.0/0` treats a legitimate 0 the same as missing; rain_chance/humidity/uvi silently become 0 on a null field. The one place a fabricated 0 would matter (false cold/wind/sunscreen warning) is explicitly guarded via None-preserving raw values fed to `_hints`. Cosmetic display only; documented intentional degradation. Downgraded from medium.

### F80 — `weatherbot/interactive/bot.py:343` · WB · PLAUSIBLE · null/attr deref
`permissions_for(me)` then `getattr(perms, name)` with no default will AttributeError if `REQUIRED_PANEL_PERMS` names a permission attr absent on the Permissions object, masked by the generic error reply. All 5 names resolve on pinned discord.py 2.7.1; trigger requires a downgrade below 2.7 or a future hub typo. Also `_log.exception` dumps the traceback.

### F82 — `weatherbot/interactive/commands/weather_views.py:207` · WB · PLAUSIBLE · truncation
Wind direction truncates degrees with `int()` instead of rounding (biased low by up to ~1°) in the parenthetical readout; the compass() sector-labeling claim is REFUTED (compass uses a correct round-to-nearest-sector). Cosmetic. Downgraded medium→low.

### F83 — `weatherbot/interactive/commands/weather_views.py:244` · WB · PLAUSIBLE · empty/edge rendering
`next_cloudy` daily fallback scans `daily[2:]` but the "no cloudy day" message reports `len(daily)` days, overstating the window when hourly[] is empty. In the normal case (hourly non-empty) the count is correct; the overstatement needs an unusual hourly-empty-but-daily-full split payload. Cosmetic count in a no-match message. Downgraded medium→low.

### F88 — `weatherbot/scheduler/context.py:47` · WB · PLAUSIBLE · naive-datetime tz footgun
`_fmt` calls `dt.astimezone(tz)` which silently assumes system-local tz if a naive datetime reaches it. No current caller can feed it a naive datetime (all sources tz-aware); hypothetical hardening gap.

### F93 — `yahir_reusable_bot/reliability/retry.py:141` · HUB · PLAUSIBLE · zero/edge division · **ROUTES UPSTREAM**
`_within_burst_wait` divides by `(burst_size-1)`; `burst_size==1` raises ZeroDivisionError inside the retry wait callable. *(Merged: WB-side + HUB-side.)* The WeatherBot validator pins `attempts_per_burst>=2` (naming this exact div-by-zero, CR-01), so the crash needs a caller bypassing that validator. Latent defense-in-depth gap in the hub function.

### F100 — `yahir_reusable_bot/lifecycle/identity.py:83` · HUB · SWEEP-NEW · resource · **ROUTES UPSTREAM**
`write_pid_atomic` double-closes fd; the integer may have been reused. If `os.replace` raises after the first `os.close`, the `except BaseException` closes `fd` again (83); between the two closes the fd can be reallocated to an unrelated file, so the guarded close silently closes someone else's descriptor. Latent (single-threaded early startup).

### F101 — `yahir_reusable_bot/lifecycle/identity.py:162` · HUB · SWEEP-NEW · wrong-result · **ROUTES UPSTREAM**
Non-Linux degrade-to-True fails when `proc_marker` is a path-like token. `_read_proc_cmdline` returns the raw marker as its /proc-absent sentinel, then `_argv_matches_marker` basenames argv[0] before comparing verbatim — a path-shaped marker (`b'/usr/bin/thebot'`) becomes `'thebot' != '/usr/bin/thebot'`, flipping "degrade to True" to False. Only bites a mis-shaped marker.

### F102 — `yahir_reusable_bot/scheduler/engine.py:74` · HUB · SWEEP-NEW · contract · **ROUTES UPSTREAM**
`SchedulerEngine.remove` is non-idempotent (raises JobLookupError) unlike `register`. Any caller that removes an id a concurrent misfire/coalesce already dropped, or removes twice during a reconcile, gets an uncaught JobLookupError. Should swallow-on-missing or document the raise.

### F115 — `tests/test_cache.py:133` · BOTH · SWEEP-NEW · missing-coverage
Cache id-key tests accept an id param but every body uses id==name, so the collapse claim is unproven for a distinct id. If `ForecastCache` keyed on the raw requested name rather than the resolved `.id`, the casefold-collapse would break and no test would fail.

### F116 — `tests/test_reload_engine.py:155` · BOTH · SWEEP-NEW · false-green
ReloadEngine reconcile never asserts register-before-remove ordering — the no-gap-in-jobs invariant is unpinned. The fake engine records removes in a separate list from the register recorder, so a refactor that removed-then-registered (opening a transient no-job window during SIGHUP reload) would still pass every assertion.

### F60 — `weatherbot/scheduler/uvmonitor.py:310` · WB · SWEEP-NEW · display/rounding
`int(delta_min)` truncates toward zero, under-reporting the pre-warn countdown by up to ~1 minute (28.9 → "~28 min", 0.9 → "~0 min"). Cosmetic but user-facing on every time-proximity prewarn.

### F61 — `weatherbot/scheduler/uvmonitor.py:390` · WB · SWEEP-NEW · observability
`uv_monitor_tick` fetched/skipped counters omit a category. Locations that fetch but gate out are counted as fetched; locations that raise in the per-location try/except are counted as neither, so `fetched+skipped` need not equal `len(locations)` — an unreliable "did location X get evaluated?" log.

### F64 — `weatherbot/weather/store.py:164` · WB · SWEEP-NEW · redundant/performance
Every store operation re-executes the full multi-statement `_SCHEMA` (7 CREATE TABLE + 6 CREATE INDEX + 2 INSERT) on each connect. On the hot per-slot delivery path this parses and force-commits the entire schema several times per fire, multiplying write-lock windows under the no-WAL default journal. Latent contention/perf; no init-once guard. (See F10 for the correctness consequence.)

### F65 — `weatherbot/weather/store.py:179` · WB · SWEEP-NEW · dead defensive code
`_local_date_iso` UTC fallback for invalid/absent timezone is unreachable — `Location.timezone` is required and IANA-validated at load. The try/except-to-UTC and else-UTC branches are dead; if reached they would silently store the WRONG local_date, so the dead code masks the invariant rather than asserting it.

### F67 — `weatherbot/weather/client.py:39` · WB · SWEEP-NEW · global side effect
Import-time mutation of the shared 'httpx' logger level affects the whole process. Any component that wants httpx INFO logs (or a test asserting them) is silently overridden merely because `weatherbot.weather.client` was imported. Better served by not logging the URL than globally reconfiguring a shared third-party logger.

### F68 — `weatherbot/weather/client.py:68` · WB · SWEEP-NEW · error handling
`response.json()` is unguarded against a 2xx non-JSON body. A 2xx captive-portal / proxy interstitial / HTML-error-with-200 makes `response.json()` raise `json.JSONDecodeError` — an undocumented failure type distinct from the HTTPStatusError callers expect, which the status-keyed retry layer may not classify as retryable.

### F71 — `weatherbot/weather/multiday.py:33` · WB · SWEEP-NEW · config-default
`_WEEKEND_DAYS` includes 'fri', overlapping `_WEEKDAY_DAYS` 'fri'; a Friday can be claimed by both the weekday and weekend forecast slots. With both slot types configured, Friday produces TWO briefings. If unintended it double-sends on Fridays; if intended it is undocumented and asymmetric (Friday counted as weekend but Sunday not counted as weekday).

### F72 — `weatherbot/weather/uv.py:143` · WB · SWEEP-NEW · inconsistent-boundary
No-sun fallback window 06:00-20:00 is hardcoded and can disagree with the real sunrise/sunset the monitor uses. At high latitudes/seasons the fallback silently clips or over-includes hours, so the same location yields a materially different UV window depending only on whether the payload carried sun fields.

### F75 — `weatherbot/config/loader.py:54` · WB · SWEEP-NEW · config-lookup edge case
`resolve_location` matches only `Location.name` (casefold), never id, so `--send-now` with a location's explicit id fails even though id is the stable identity. `weatherbot send-now home` (where home is the id, name is 'Home Base') raises UnknownLocationError. Latent since current callers pass names.

### F81 — `weatherbot/interactive/panel.py:248` · WB · SWEEP-NEW · interaction-race
`LocationSelect.callback` does `self.values[0]` without guarding an empty values list, raising IndexError on a malformed/deselect interaction. Caught by the surrounding try/except and routed to `_safe_error_edit` — the selection silently fails with a generic error instead of a no-op. Latent (current Select has min_values=1).

### F84 — `templates/renderer.py:196` · WB · SWEEP-NEW · empty-token rendering
Empty {notice} and {footer_note} tokens render as blank lines, leaving trailing whitespace at the end of every forecast body. On the common path (no flags, no footer) the body ends in `\n\n\n` (verified in the golden snapshot), carrying 2-3 empty trailing lines on both Discord and CLI.

### F85 — `weatherbot/interactive/commands/weather_views.py:237` · WB · SWEEP-NEW · ambiguous date
`next_cloudy` hourly 'When' uses '%a %H:%M' (no date) while the daily branch and alerts include the date to avoid past/next-week ambiguity. A cloudy bucket 24-48h out renders as 'Wed 14:00'; alerts() and the daily branch deliberately add the date. The hourly branch of the same command is inconsistent, so the user can misread which day the cloud cover falls on.

### F86 — `weatherbot/interactive/commands/status.py:73` · WB · SWEEP-NEW · raw ISO timestamp
'Next send' value is `DaemonState.next_fires()` raw `.isoformat()` (e.g. '2026-07-08T09:00:00-04:00'), not a human-formatted time like the sibling `_fmt_epoch` output. The two time fields in one `!status` reply are formatted inconsistently.

### F87 — `weatherbot/interactive/commands/forecast.py:129` · WB · SWEEP-NEW · metric mispair on missing dt
When an imperial daily[] entry lacks 'dt', the metric twin falls back to positional `daily_met[i]`, reintroducing the cross-fetch mispairing the WR-01 dt-match guard prevents. If the two fetches differ in length/ordering AND the imperial day is missing its dt, index i pairs the wrong-day metric temp (e.g. '72°F (3°C)') on the degraded-payload edge.

### F89 — `weatherbot/scheduler/daemon.py:392` · WB · SWEEP-NEW · resource/state leak
`_forecast_failure_streaks` module dict is keyed by `location.name` and never pruned on config reload; renaming/removing a forecast slot leaks its entry forever. Only `_note_forecast_success` pops it, which never fires for a removed slot. Over a long-lived multi-reload process the dict accumulates dead entries — slow unbounded memory growth in the always-on spine.

### F90 — `weatherbot/scheduler/daemon.py:1042` · WB · SWEEP-NEW · observability
`_announce_schedule` iterates only `location.schedule`, so scheduled forecast jobs are registered and fire but omitted from the startup announcement. On startup the log shows every briefing slot's next_run_time but ZERO forecast slots, so a misconfigured/disabled forecast slot is invisible at the one point the schedule is announced.

### F95 — `yahir_reusable_bot/reliability/retry.py:146` · HUB · SWEEP-NEW · API-misuse latent · **ROUTES UPSTREAM**
`two_burst_wait` mid-pause is keyed to `burst_size` default (8) independent of the stop bound; direct callers can desync the pause location. A caller that builds its own `Retrying` with `stop_after_attempt(N)` but calls `two_burst_wait` without a matching `burst_size` gets the 45-min mid-pause at the wrong attempt (or never). `build_retrying` wires it correctly; the standalone function offers no coupling.

### F96 — `yahir_reusable_bot/discord/panelkit.py:309` · HUB · SWEEP-NEW · async/robustness · **ROUTES UPSTREAM**
`interaction_check` dereferences `interaction.user.bot` / `.id` without a None guard. `interaction.user` can be None in some contexts, so `.bot` raises AttributeError inside `interaction_check`, which discord.py does not wrap in the View.on_error backstop — the reject path throws instead of cleanly returning False.

### F97 — `yahir_reusable_bot/discord/panelkit.py:479` · HUB · SWEEP-NEW · correctness-edge · **ROUTES UPSTREAM**
`is_owned_panel` with an empty-string marker matches every bot-authored message (`startswith('')` always True). If an app wires `marker=''`, `is_owned_panel` treats every bot-authored pinned message as an owned panel — and `summon_panel` would then delete unrelated bot pins. A one-line non-empty guard would close this.

---

## Cleanup

### F16 — `weatherbot/scheduler/daemon.py:1108` · WB · CONFIRMED · dead-code
`gate_until_healthy`, `emit_online`, and `_do_reload` are dead in production after the ReadyGate/ReloadEngine refactor (still exercised only by tests). They duplicate the live gate/reload logic, inviting a future fix landing in the dead copy. *Evidence:* zero production callers; live path uses `ready_gate.run` / `reload_engine`.

### F46 — `weatherbot/ops/pidfile.py:124` · WB · CONFIRMED · dead code/divergence risk
`_argv_is_weatherbot` is never called (live guard is the hub's `_argv_matches_marker`) yet carries the same flawed `-m` match (see F45). A maintainer patching this copy would think they fixed the guard while the live hub path stays vulnerable. Remove it or route through the hub.

### F76 — `weatherbot/cli.py:314` · WB · CONFIRMED · dead-code
`run_weather`'s `verbose` parameter is accepted and passed by `_cmd_weather` but never read — the `-v` level is already applied in `main()` via `_configure_logging`. Dead and misleading. *Evidence:* grep shows only the decl, the caller, and the real plumbing in `main()`.

### F66 — `weatherbot/weather/models.py:304` · WB · PLAUSIBLE · single-source alerts/doc mismatch
`alerts` is read only from the imperial payload; the docstring claims "from each payload" — a doc/code mismatch, not a real data-loss path. OpenWeather `alerts[]` are coordinate-keyed and unit-independent, so a metric-only alert requires a speculative server race. Downgraded low→cleanup.

### F104 — `weatherbot/interactive/lookup.py:183` · WB · SWEEP-NEW · dead-code/inaccurate-doc
`lookup_forecast` is never routed through by the cache despite its docstring claiming it is; the Discord/CLI forecast path calls `lookup_weather` directly (`ForecastCache.lookup` → `lookup_weather`). Its only live caller is the scheduled-briefing path. The doc claim is misleading and `lookup_forecast` is a pure passthrough.

### F105 — `weatherbot/interactive/commands/info.py:40` · WB · SWEEP-NEW · view formatting
`locations()` lists timezone as each value but never marks which location is the default, though the docstring says the first is the default for bare commands. A user reading `!locations` cannot tell which name a bare `!weather`/`!weekday` will resolve to.

### F69 — `weatherbot/weather/models.py:69` · WB · SWEEP-NEW · duplication/divergence
`_local_date_iso` is duplicated verbatim between `models.py:69` and `store.py:169`. If the tz-fallback or DST handling is later fixed in one copy and not the other, `models.py`'s {date}/UV-day and `store.py`'s target_local_date silently disagree, mis-keying persisted rows against the rendered briefing.

### F92 — `weatherbot/ops/selfcheck.py:119` · WB · SWEEP-NEW · dead-code
`is_transient(exc)` is called purely for its (discarded) result; both branches return `NETWORK_NOT_READY` regardless. The call is dead and misleadingly implies the classification influences the outcome. (Distinct from F06, which is the wrong-classification correctness bug.)

### F98 — `yahir_reusable_bot/discord/__init__.py:25` · HUB · SWEEP-NEW · public-surface-inconsistency · **ROUTES UPSTREAM**
Package `__init__` docstring advertises the summon orchestration as an export but `summon_panel` is neither imported nor in `__all__`. A consumer following the docstring doing `from yahir_reusable_bot.discord import summon_panel` gets an ImportError.

---

## Disposition Ledger (v2.1)

> **Appended non-destructively by Phase 35 Plan 09 (Wave-3 reconciliation, docs-only).** The
> severity sections and per-finding prose above are UNCHANGED. This table is the single
> reconciliation record the v2.1 milestone audit reads: every in-scope WeatherBot (**WB**) and
> shared-surface (**BOTH**) finding gets **exactly one** disposition; every hub (**HUB**) finding is
> confirmed routed out-of-milestone.
>
> **Completeness contract (from §Severity Summary):** 116 findings = **88 WB + 11 BOTH + 17 HUB**.
> The 88 WB + 11 BOTH = **99** findings each carry exactly one of `FIXED@<phase>` / `ACCEPTED` /
> `DEFERRED(target)` — **65 FIXED + 19 ACCEPTED + 15 DEFERRED**. The 17 HUB findings carry
> `HUB (routed → HUB-FINDINGS-HANDOFF.md)`.
>
> **v2.1 HARD-CLEAN-02 gap closure (Phase 35 gap-closure pass):** the 5 LOW-severity WB findings
> F38/F49/F50/F64/F81 — originally `DEFERRED(v2.2-hardening)`, which HARD-CLEAN-02 disallows for
> low-severity findings ("resolved OR accepted-with-rationale, NOT deferred to a backlog") — were
> reconciled: **F81 → FIXED@35** (empty-values guard + regression test), **F38/F49/F50/F64 →
> ACCEPTED** (in-code `# ACCEPTED (F##, v2.1)` annotations). This flips the tally from
> 64 FIXED + 15 ACCEPTED + 20 DEFERRED to 65 FIXED + 19 ACCEPTED + 15 DEFERRED. The in-code
> ACCEPTED annotation set is now 19 (15 prior + F38/F49/F50/F64).
>
> **Disposition provenance:**
> - **`FIXED@<phase>`** — the finding was remediated in code by the named phase. Verified against
>   current source at HEAD (D-04 verify-then-mark: for the already-fixed bucket the symbol/pattern
>   was grepped clean before marking; no code was re-touched by this plan). Git provenance:
>   e.g. F89/F90 `648bcc2 (29-05)`, F28/F84/F86 `9047fa8 (33-06)`, F06 `24b446e (29-03)`,
>   F69/F65/F33/F35 Phase 32 (`weather/dates.py` unification, negative-grep gate in
>   `test_import_hygiene.py`), F106–F116 Phase 34 backfill.
> - **`ACCEPTED`** — deliberately accepted-with-rationale; **mirrored by an in-code
>   `# ACCEPTED (F##, v2.1): …` annotation** at the finding's site (Plans 03/05/06/07/08 + the
>   Phase-35 gap-closure pass for F38/F49/F50/F64). The ACCEPTED set below equals
>   `grep -ohE "# ACCEPTED \(F[0-9]+, v2.1\)" weatherbot/ -r` exactly (19 findings) — ledger and
>   code agree (no silent debt).
> - **`DEFERRED(v2.2-hardening)`** — an audit-surfaced WB/BOTH finding NOT remediated by the v2.1
>   correctness phases (29–34) and NOT in this cleanup sweep's HARD-CLEAN scope. No live user-facing
>   regression on the current single-user two-city deployment; explicitly carried forward to a future
>   hardening pass so it is documented debt, not silent. Each names its target (`v2.2-hardening`).
> - **`HUB (routed → …)`** — under `yahir_reusable_bot/…`; human-gated, out of this milestone
>   (see the 17-vs-18 reconciliation note in `HUB-FINDINGS-HANDOFF.md`).

### WB + BOTH findings (99 — exactly one disposition each)

| Finding | Tag | Disposition | Source of disposition |
|---------|-----|-------------|-----------------------|
| F01 | WB | FIXED@31 | 31-02-SUMMARY (post-send atomicity; F01 duplicate-send critical) |
| F02 | WB | FIXED@33 | 33-07 review-fix (bare `!weather` default-location on Discord) |
| F03 | WB | DEFERRED(v2.2-hardening) | catch-up scan still runs before the ReadyGate; recovery-ordering not reworked |
| F04 | WB | DEFERRED(v2.2-hardening) | SIGTERM retry-drain; root in HUB retry (H-side), WB wrapper not added |
| F05 | WB | FIXED@29 | 29-01-SUMMARY (run-startup validation parity) |
| F06 | WB | FIXED@29 | 29-03 `CONFIG_INVALID` split (git 24b446e); no longer mis-classified NETWORK_NOT_READY |
| F07 | WB | FIXED@29 | 29-02-SUMMARY (online ping relocated after READY=1) |
| F08 | WB | FIXED@31 | 31-03-SUMMARY (forecast-slot delivery-failure detection) |
| F09 | WB | DEFERRED(v2.2-hardening) | `load_settings()` not fully guarded on every command path (`.env` traceback) |
| F10 | WB | FIXED@31 | 31-01-SUMMARY (store read/write lock; WAL/busy_timeout) |
| F11 | WB | FIXED@33 | 33-05-SUMMARY (metric high/low fallback) |
| F12 | WB | FIXED@30 | 30-01-SUMMARY (secret-hygiene; appid redaction at raise sites) |
| F13 | WB | FIXED@33 | 33-03-SUMMARY (cache epoch/generation invalidation guard) |
| F14 | WB | FIXED@32 | 32-03-SUMMARY (catch-up across local midnight) |
| F15 | WB | FIXED@32 | 32-01-SUMMARY (UV all-clear hysteresis) |
| F16 | WB | FIXED@35 | 35-08 (removed dead `emit_online`/`_do_reload` twins) |
| F17 | WB | FIXED@33 | 33-03-SUMMARY (`on_applied` invalidate-before-send ordering) |
| F18 | WB | DEFERRED(v2.2-hardening) | reload reject stdlib-logger journal line divergence not unified |
| F19 | WB | DEFERRED(v2.2-hardening) | UV `value_close` prewarn rising/future-crossing guard not added |
| F20 | WB | DEFERRED(v2.2-hardening) | UV already-crossed-while-down never-fire all-clear gap not closed |
| F21 | WB | DEFERRED(v2.2-hardening) | daily0-date-mismatch suppresses daylight-independent all-clear (distinct from F58) |
| F22 | WB | FIXED@33 | 33-04-SUMMARY (SelectedContext reconcile on reload) |
| F23 | WB | FIXED@33 | 33-04-SUMMARY (empty-locations panel recovery) |
| F24 | WB | FIXED@33 | 33-03-SUMMARY (interaction ack ordering) |
| F25 | WB | DEFERRED(v2.2-hardening) | bare `+`/`-` flag token still surfaces via generic error, not an actionable flag reply |
| F26 | WB | DEFERRED(v2.2-hardening) | `--sat` long-form day flag still routes to DROP (documented fail-loud, no formal accept) |
| F27 | WB | FIXED@33 | 33-01-SUMMARY (inbound `!weather <loc>` 📍 location indicator parity) |
| F28 | BOTH | FIXED@33 | 33-06 (forecast header dedup, git 9047fa8) — verified: no duplicated title at HEAD |
| F29 | WB | DEFERRED(v2.2-hardening) | `next_cloudy` still drops nocturnal cloudy hours (`_is_daytime` gate + `daily[2:]`) |
| F30 | WB | DEFERRED(v2.2-hardening) | `uv.py:153` daytime window still compares RAW `ts` (string-epoch bypass) |
| F31 | WB | FIXED@32 | 32-01-SUMMARY (UV compute daily0 date guard) |
| F32 | WB | FIXED@32 | 32-01-SUMMARY (hourly-points sort for interpolation) |
| F33 | WB | FIXED@32 | naive-`now_utc` treated as UTC in `dates.local_date_iso`; verified no `def _local_date_iso` |
| F34 | WB | DEFERRED(v2.2-hardening) | ForecastDay feels-like `max()/min()` present-but-null daypart not hardened |
| F35 | WB | FIXED@32 | `select_today_daily` anchors daily selection to `local_date` (models.py:303/324); positional hard-index gone |
| F36 | WB | FIXED@32 | 32-05-SUMMARY (weather_onecall rename-safe key) |
| F37 | WB | FIXED@32 | 32-05-SUMMARY (persist dedup guard) |
| F38 | WB | ACCEPTED | in-code `# ACCEPTED (F38, v2.1)` (daemon.py) — raw-`slot.days` job-id footgun latent + harmless (losing job does zero API calls: no-op INSERT + skipped log) |
| F46 | WB | FIXED@35 | 35-02 (removed dead `_argv_is_weatherbot` + exclusive test) |
| F47 | WB | DEFERRED(v2.2-hardening) | sun/wind/alerts registry commands still lack the transient-retry wrapper `weather` has |
| F48 | WB | FIXED@31 | 31-03-SUMMARY (Discord 401/403 classified auth vs transient) |
| F49 | WB | ACCEPTED | in-code `# ACCEPTED (F49, v2.1)` (cache.py) — per-suffix redundant One Call fetch is a documented bounded tradeoff against the 60/min & 1M/month free tier |
| F50 | WB | ACCEPTED | in-code `# ACCEPTED (F50, v2.1)` (cache.py) — shared `maxsize=16` latent at 2-location scale; plain entry already pinned, retuning has subtle eviction effects |
| F51 | WB | ACCEPTED | in-code `# ACCEPTED (F51, v2.1)` — cached bake-time stamp cosmetic within TTL |
| F52 | WB | ACCEPTED | in-code `# ACCEPTED (F52, v2.1)` — transient ConfigHolder identity-smell, no reachable behavior |
| F53 | WB | ACCEPTED | in-code `# ACCEPTED (F53, v2.1)` — `start()` in swallowed hook unreachable on single-drive |
| F54 | WB | DEFERRED(v2.2-hardening) | geocode error-handling (partial: timeout now caught) — full contract not re-audited this milestone |
| F55 | WB | DEFERRED(v2.2-hardening) | geocode exit-code ambiguity (zero-match vs auth-fail both exit 1) not disambiguated |
| F56 | WB | ACCEPTED | in-code `# ACCEPTED (F56, v2.1)` — pre-`local_date` raise unreachable given validated tz |
| F57 | WB | ACCEPTED | in-code `# ACCEPTED (F57, v2.1)` — worker starvation not reachable at 2-slot scale |
| F58 | WB | ACCEPTED | in-code `# ACCEPTED (F58, v2.1)` — missing-sun-fields skip narrow (schema-drift only) |
| F59 | WB | ACCEPTED | in-code `# ACCEPTED (F59, v2.1)` — inclusive `[sunrise,sunset]` intentional |
| F60 | WB | FIXED@35 | 35-05 (honest `round(delta_min)` prewarn countdown + regression test) |
| F61 | WB | FIXED@35 | 35-05 (tick counter reconcile — errored bucket) |
| F62 | WB | ACCEPTED | in-code `# ACCEPTED (F62, v2.1)` — falsy-coalesce display-only; hints use None-preserving raw |
| F63 | BOTH | FIXED@34 | 34-06-SUMMARY (store atomicity/executescript test) |
| F64 | WB | ACCEPTED | in-code `# ACCEPTED (F64, v2.1)` (store.py) — per-op `_SCHEMA` re-exec already closed by F10 store-connect discipline (`init_db` owns one-time DDL; per-write connects run no DDL) |
| F65 | WB | FIXED@32 | dead UTC fallback gone; single documented fallback in `dates._resolve_tz`; verified no `def _local_date_iso` |
| F66 | WB | FIXED@35 | 35-06 (corrected `alerts` docstring — read once, unit-independent) |
| F67 | WB | ACCEPTED | in-code `# ACCEPTED (F67, v2.1)` — httpx setLevel is defense-in-depth (not superseded by redaction) |
| F68 | WB | FIXED@35 | 35-05 (2xx non-JSON classified as redacted transient + 2 regression tests) |
| F69 | WB | FIXED@32 | `_local_date_iso` duplication unified into `weather/dates.py`; negative-grep gate in `test_import_hygiene.py` |
| F70 | WB | FIXED@35 | 35-07 (drop-beats-add; `+X -X` resolves to dropped + regression test) |
| F71 | WB | ACCEPTED | in-code `# ACCEPTED (F71, v2.1)` — Friday-as-weekend intentional for travel split (user-flagged) |
| F72 | WB | ACCEPTED | in-code `# ACCEPTED (F72, v2.1)` — fixed fallback window only on missing sun fields; mid-latitude |
| F73 | WB | ACCEPTED | in-code `# ACCEPTED (F73, v2.1)` — WR-02 peak-clock coherence over peak/max agreement |
| F74 | WB | FIXED@35 | 35-04 (canonical-only HH:MM validator on both schedule models + regression test) |
| F75 | WB | FIXED@35 | 35-04 (`resolve_location` id-then-name + regression test) |
| F76 | WB | FIXED@35 | 35-03 (removed inert `run_weather(verbose=…)` param + call site) |
| F77 | WB | ACCEPTED | in-code `# ACCEPTED (F77, v2.1)` — documented per-command exit-code conventions intentional |
| F78 | WB | FIXED@35 | 35-03 (explicit `send-now` dispatch guard against future fallthrough) |
| F79 | WB | FIXED@35 | 35-06 (`!panel please` summons via `content.split()[0]`; `!panelfoo` still refused) |
| F80 | WB | FIXED@35 | 35-06 (`getattr(perms, name, False)` default → clean refusal, no AttributeError) |
| F81 | WB | FIXED@35 | 35-gap (empty-values guard in `LocationSelect.callback` → no-op on empty/deselect; + `test_empty_values_callback_is_noop` regression test) |
| F82 | WB | FIXED@35 | 35-06 (`round(deg)` wind direction; compass sector already correct) |
| F83 | WB | ACCEPTED | in-code `# ACCEPTED (F83, v2.1)` — `len(daily)` count diverges only on unusual split payload |
| F84 | WB | FIXED@33 | 33-06 renderer empty-token line drop (git 9047fa8); verified `had_token` guard at HEAD |
| F85 | WB | FIXED@35 | 35-06 (dated `next_cloudy` hourly label — `%a %b %d`) |
| F86 | WB | FIXED@33 | 33-06 status "Next send" humanized via `_fmt_epoch`; verified no raw isoformat at HEAD |
| F87 | WB | FIXED@33 | forecast metric paired by matching `dt` (forecast.py:141–146), not positional index |
| F88 | WB | FIXED@35 | 35-08 (cheap PRESERVE fix — `assert dt.tzinfo is not None`) |
| F89 | WB | FIXED@29 | `_prune_forecast_streaks` on reload (daemon.py:516; git 648bcc2 / 29-05) |
| F90 | WB | FIXED@29 | `_announce_schedule` iterates forecast slots (daemon.py:1018; git 648bcc2 / 29-05) |
| F91 | WB | FIXED@32 | 32-01-SUMMARY (DST fall-back catch-up fold math) |
| F92 | WB | FIXED@35 | 35-02 (removed discarded `is_transient(exc)` call + unused import) |
| F103 | WB | ACCEPTED | in-code `# ACCEPTED (F103, v2.1)` — `getattr(...,'ok',True)` over-guard, single missed best-effort WARNING |
| F104 | WB | FIXED@33 | `lookup_forecast` docstring accurate at HEAD ("DELEGATES"/"NAMED seam"); verified-clean 35-06 |
| F105 | WB | FIXED@35 | 35-06 (`!locations` marks the default with `" (default)"` suffix) |
| F106 | BOTH | FIXED@34 | 34 backfill (concurrent-double-fire test corrected to real atomicity) |
| F107 | BOTH | FIXED@34 | 34 backfill (`from_payloads` dt-based imperial/metric pairing test) |
| F108 | BOTH | FIXED@34 | 34-07 (rename-safe `id != name` through fire_slot/plan_catchup) |
| F109 | BOTH | FIXED@34 | 34-04 (`from_payloads` daily[0]-is-today assertion) |
| F110 | BOTH | FIXED@34 | 34 backfill (Retry-After 429 on mid-pause attempt) |
| F111 | BOTH | FIXED@34 | 34 backfill (weekend-block roll-forward) |
| F112 | BOTH | FIXED@34 | 34 backfill (two_burst_wait tight within-burst bound) |
| F113 | BOTH | FIXED@34 | 34 backfill (null-`dt` in date-index map) |
| F114 | BOTH | FIXED@34 | 34 backfill (heartbeat tick/success separation) |
| F115 | BOTH | FIXED@34 | 34 backfill (cache id-key distinct-id collapse) |
| F116 | BOTH | FIXED@34 | 34 backfill (ReloadEngine register-before-remove ordering) |

**Tally:** 64 `FIXED@` + 15 `ACCEPTED` + 20 `DEFERRED(v2.2-hardening)` = **99** WB/BOTH findings, exactly one disposition each. The 15 ACCEPTED ids match the in-code `# ACCEPTED (F##, v2.1)` annotation set exactly.

### HUB findings (17 — routed out-of-milestone)

All 17 findings whose `file:line` is under `yahir_reusable_bot/…`. Per `ECOSYSTEM.md`, hub fixes are
human-gated (fix upstream, cut tag `v0.1.2`, repin WeatherBot). Routed to
`HUB-FINDINGS-HANDOFF.md` (mapped H01–H17). **No hub file was edited by this milestone.**

| Finding | HUB map | Disposition |
|---------|---------|-------------|
| F45 | H01 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F94 | H02 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F39 | H03 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F40 | H04 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F41 | H05 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F44 | H06 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F42 | H07 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F43 | H08 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F93 | H09 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F95 | H10 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F96 | H11 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F97 | H12 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F99 | H13 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F100 | H14 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F101 | H15 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F102 | H16 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |
| F98 | H17 | HUB (routed → HUB-FINDINGS-HANDOFF.md, out-of-scope) |

> **17-vs-18 note:** `HUB-FINDINGS-HANDOFF.md` lists **H01–H18**. The **17** above are the
> audit-surfaced hub defects (H01–H17). **H18** (`ready_gate.run` no first-class fatal outcome) is a
> Phase-29-appended *deferred enhancement*, not one of the 17 audit defects — it inflates the
> handoff's own severity line to 18. The milestone's out-of-scope count is the **17 defects**. See
> the reconciliation note in `HUB-FINDINGS-HANDOFF.md`.

### Appendix — pre-existing, out-of-audit-scope items (documented, not silent debt)

Three pre-existing `ruff` nits in `weatherbot/scheduler/daemon.py`, discovered during Phase 35 but
**NOT** audit findings and **pre-dating this milestone** (all three present at `6b45e55~1`, before the
Phase-35 dead-code removal). `ruff` is not a blocking gate and the full suite is green, so they are
non-blocking. Recorded here as `DEFERRED / trivial-follow-up` so they are documented rather than
silent debt. **Not edited by this docs-only plan.**

| Item | Site | Disposition |
|------|------|-------------|
| `F401` unused import `ReloadEngine` | `weatherbot/scheduler/daemon.py:67` | DEFERRED (trivial `ruff --fix` follow-up) |
| `F401` unused import `PID_FILE` | `weatherbot/scheduler/daemon.py:68` | DEFERRED (trivial `ruff --fix` follow-up) |
| `F841` unused local `notifier` | `weatherbot/scheduler/daemon.py:1373` | DEFERRED (trivial cleanup follow-up) |
