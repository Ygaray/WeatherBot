# YahirReusableBot — Audit Findings Handoff (from WeatherBot v2.1 audit)

> Generated 2026-07-07 from WeatherBot's whole-project multi-agent audit. These are the
> **17 findings that fall in the hub** (`yahir_reusable_bot/…`). Per `ECOSYSTEM.md`, hub fixes
> are human-gated: fix here in the hub repo, run this repo's suite + import-hygiene/litmus/grimp
> gates, then **you** cut the tag (v0.1.2) and repin WeatherBot. Bring this file into
> `YahirReusableBot` and run `/gsd-new-milestone` there.


**Severity:** high 2 · medium 4 · low 10 · cleanup 1  (total 17)


## High

### H01 — `yahir_reusable_bot/lifecycle/identity.py:149` · high · CONFIRMED · PID-recycling false positive / wrong-condition argv match

'-m' module match uses `proc_marker in argv[1:4]` (and assumes -m is argv[1]), so it both false-positives on 'python -m <tool> weatherbot' and false-negatives when interpreter flags precede -m (ROUTES UPSTREAM)


*Scenario:* _argv_matches_marker returns `b'-m' in argv[1:3] and proc_marker in argv[1:4]`. (a) FALSE POSITIVE: a recycled PID running `python -m pytest weatherbot` or `python -m http.server weatherbot` has the marker as a POSITIONAL ARG in argv[3], so both clauses are True and `weatherbot reload` delivers SIGHUP (default disposition: terminate) to that unrelated process — the exact PID-recycling mis-delivery the guard claims to prevent. (b) FALSE NEGATIVE: a genuine daemon started with an interpreter flag before -m (e.g. `python -W ignore -m weatherbot run`, `python -O -m weatherbot`) has argv[1:3] without '-m', so a live daemon is reported NOT running and reload refuses to signal it. Fix: pin to `len(argv)>=3 and argv[1]==b'-m' and argv[2]==proc_marker`.


*Evidence:* Verified empirically: True for `-m pytest weatherbot` and `-m http.server weatherbot`, True for genuine `-m weatherbot run`. Existing guard test (test_reload.py:561) only covers non-'-m' decoys. Reachable via PID recycling + specific argv shape; defense-in-depth safety-guard breakage. Flags-before-m false-negative is sweep-unverified.

### H02 — `yahir_reusable_bot/reliability/retry.py:87` · high · SWEEP-NEW · HUB reliability / transient classification

is_transient misses common transient httpx failures (RemoteProtocolError, WriteError), so they are NOT retried (ROUTES UPSTREAM)


*Scenario:* is_transient only matches TimeoutException, ConnectError, ReadError. httpx.RemoteProtocolError ('Server disconnected without sending a response') and httpx.WriteError are sibling NetworkError/ProtocolError subclasses NOT in that tuple. A server hangup mid-response — routine for OpenWeather/Discord — falls through is_transient()==False, so the retry predicate does not fire, the whole two-burst schedule is skipped, and fire_slot records it as reason=internal_error instead of retrying and (on exhaustion) transient_exhausted. Realistic network blips silently miss the briefing with the wrong alert reason. Catching httpx.TransportError or NetworkError would fix it.


## Medium

### H03 — `yahir_reusable_bot/config/reload.py:150` · medium · CONFIRMED · giving up without alerting / missing hook

PHASE-2 reconcile failure rolls back and re-raises but never fires on_rejected, so a real reconcile-time reload failure produces no rejection alert (ROUTES UPSTREAM)


*Scenario:* A config is valid (PHASE 1 passes) but a job id fails to (de)register during _reconcile (scheduler_engine.remove raises JobLookupError, or register_jobs raises). The engine rolls the holder back, restores, logs, and re-raises — but unlike the PHASE-1 reject path it never calls _best_effort_hook(self._on_rejected, ...). The host's alerting hook (wired to Discord 'config reload rejected') silently never fires. The common cause (malformed edited config) is a PHASE-1 failure and DOES alert; the uncovered path is the narrower PHASE-2 reconcile failure.


*Evidence:* reload.py PHASE-1 fires reject hook (L138) then raise; PHASE-2 (146-158) rolls back + restore + log + raise, no reject hook. _reconcile calls remove (189, delegates to APScheduler remove_job -> JobLookupError) and register_jobs (184). Host wires on_rejected=channel.send (wiring.py:255-259). Rolls back safely, error logged — no data loss.

### H04 — `yahir_reusable_bot/discord/gateway.py:273` · medium · PLAUSIBLE · async misuse / unhandled disconnect

No reconnect supervisor: a non-recoverable disconnect from client.start permanently kills the interactive bot with no retry (ROUTES UPSTREAM)


*Scenario:* _amain runs `async with self._client: await self._client.start(token)` with no retry loop. discord.py's default reconnect=True absorbs transient blips, but a NON-recoverable disconnect (auth/intents close codes, exhausted retries, session invalidation) escapes _run, sets _failed=True, and ends the thread. is_alive() stays False forever. The consumer calls bot.start() once (daemon.py:1522) and the park loop never polls is_alive() to respawn — every subsequent !panel/interaction is silently dead until a human restarts the service. Bounded by failure isolation: scheduled briefings run on a separate thread and are unaffected.


*Evidence:* gateway.py:273-278 no retry; 269-271 except -> _failed; is_alive 240. Consumer daemon.py:1522 single start, park loop 1535 services only stop/reload. Death requires a non-recoverable disconnect (less common than 'any blip'); no data loss, no briefing miss.

### H05 — `yahir_reusable_bot/discord/gateway.py:167` · medium · CONFIRMED · non-atomic multi-step write / resource leak / error-handling

summon_panel create-before-delete + Forbidden-only catch: pin() or old.delete() raising a non-Forbidden error leaves duplicate live pinned panels and can leave the fresh panel unpinned (ROUTES UPSTREAM)


*Scenario:* On resummon the fresh panel is sent+pinned first (166-167), THEN a loop deletes old panels (171-172), and the only handler catches discord.Forbidden (180). (a) An old.delete() raising discord.NotFound (already deleted by another actor) or discord.HTTPException (transient 5xx) bypasses the Forbidden catch, aborts the remaining deletes, and leaves 2+ live pinned panels — and since setup_hook add_view registers by static custom_id, taps on stale panels still route, so the operator can drive a stale panel. (b) On a channel at Discord's 50-pin cap, msg.pin() momentarily hits 51 and raises HTTPException, also uncaught, leaving the fresh panel sent-but-unpinned. Fix: delete-then-pin (or reserve headroom) and per-item try/except catching HTTPException/NotFound.


*Evidence:* Verified via MRO that NotFound/HTTPException are NOT subclasses of Forbidden (siblings under HTTPException). add_view registers by static custom_id (gateway.py:100) so surviving stale panels dispatch to the live callback. Consumer on_message envelope (bot.py:458-461) swallows the bubble but the duplicate-live-panel / unpinned state persists. 50-pin-cap and general non-Forbidden arms are sweep-unverified.

### H06 — `yahir_reusable_bot/registry/match.py:61` · medium · CONFIRMED · off-by-one / unicode

arg substring is sliced from the raw string using the folded keyword length, so a casefold that changes length misaligns the slice (ROUTES UPSTREAM)


*Scenario:* The prefix test uses folded (folded.startswith(spec.name)) but the arg is cut from the un-folded original: rest = stripped[len(spec.name):]. casefold() is not length-preserving ('ß'->'ss', ﬁ ligature->'fi'). For input 'ßtatus arg' against spec name 'sstatus', len(name)=7 slices the 10-char raw string mid-token, so the word-boundary guard reads the wrong character and the extracted arg is corrupted/mis-detected.


*Evidence:* match.py L59 prefix test on casefolded, L61 slice length from folded keyword applied to un-folded original. Reproduced: match_command('ßtatus arg',[spec 'sstatus'])->spec=None; 'ﬁnd hello'->spec=None. UNREACHABLE on WeatherBot (all spec names lowercase ASCII) — generic hub-matcher bug.


## Low

### H07 — `yahir_reusable_bot/discord/gateway.py:244` · low · PLAUSIBLE · race / resource leak

stop() reads self._loop and checks is_running() with a TOCTOU gap; if the loop stops between check and run_coroutine_threadsafe, RuntimeError escapes stop() (ROUTES UPSTREAM)


*Scenario:* The bot loop is tearing down (after a crash) exactly as the host calls stop(). loop.is_running() returns True, then the loop stops before asyncio.run_coroutine_threadsafe(self._client.close(), loop) (246, OUTSIDE the try) schedules -> RuntimeError('Event loop is closed'), NOT caught (only future.result()'s except at 247-250 is). Refuted consequences: the ONLY caller (daemon.py:1587-1591) wraps stop() in try/except so it never crashes host teardown; and client.close() already ran via `async with self._client` __aexit__, so no leak. Latent robustness nit.


*Evidence:* gateway.py:245 is_running check, :246 run_coroutine_threadsafe outside try. Reproduced RuntimeError when loop closes after is_running()==True. Caller wraps stop() (daemon.py:1587-1591); client closed via async-with context — no crash, no leak.

### H08 — `yahir_reusable_bot/discord/selection.py:49` · low · PLAUSIBLE · race / async misuse

SelectedContext single-writer assumption is violated by interleaved on_command awaits: a Select tap during an off-loop fetch changes the render-arg location label (ROUTES UPSTREAM)


*Scenario:* discord.py dispatches each interaction as its own task, so a second interaction runs during any await. In the consumer forecast path, wiring.py:415 reads selection.value pre-await (flags, correct) then wiring.py:427 RE-reads it AFTER await dispatch_spec: `render_arg=selection.value`. If the operator taps the Select during the fetch, render_arg picks up the NEW location -> embed whose weather DATA is location A but whose 📍 label is location B — a mismatched label, not wrong weather data. Mitigated: argless path reuses the captured local arg (safe); on_command disables components before the await as a double-tap guard.


*Evidence:* panelkit.py:355 passes holder by reference; writer panel.py:248 sync on same loop. Consumer wiring.py:415 pre-await read, :427 post-await re-read. Cosmetic wrong-location label in a narrow race; not data loss.

### H09 — `yahir_reusable_bot/reliability/retry.py:141` · low · PLAUSIBLE · zero/edge division

_within_burst_wait divides by (burst_size-1); burst_size==1 raises ZeroDivisionError inside the retry wait callable (ROUTES UPSTREAM)


*Scenario:* step = burst_spread_s/(burst_size-1) -> ZeroDivisionError when burst_size==1. The early-return guard at 137 (if attempt_number==burst_size: return mid_pause_s) shields only the FIRST retry when burst_size==1; the SECOND retry falls through to 141 and raises from inside tenacity's wait during retry — crashing the retry loop instead of degrading. two_burst_wait/build_retrying default burst_size=8 with NO internal ==1 guard and are re-exported on the public surface. In WeatherBot the config validator pins attempts_per_burst>=2 (models.py:297), so the crash requires a caller bypassing that validator (another ecosystem bot, a test, a future config path).


*Evidence:* retry.py:141 real div; 137 guard shields only the first retry when burst_size==1. WB validator pins >=2 (comment names this exact div-by-zero, CR-01). Latent defense-in-depth gap in the hub function; no reachable failing path in this repo.

### H10 — `yahir_reusable_bot/reliability/retry.py:146` · low · SWEEP-NEW · HUB reliability / API-misuse latent

two_burst_wait mid-pause is keyed to burst_size default (8) independent of the stop bound; direct callers can desync the pause location (ROUTES UPSTREAM)


*Scenario:* two_burst_wait is an importable module function whose mid-pause fires when attempt_number==burst_size, defaulting burst_size=8. A caller that builds its own Retrying with stop_after_attempt(N) but calls two_burst_wait without a matching burst_size gets the 45-min mid-pause at the wrong attempt (or never), silently distorting the budget the module guarantees. build_retrying wires this correctly, but the standalone function offers no coupling/assertion.

### H11 — `yahir_reusable_bot/discord/panelkit.py:309` · low · SWEEP-NEW · async/robustness

interaction_check dereferences interaction.user.bot / .id without a None guard (ROUTES UPSTREAM)


*Scenario:* discord.py types interaction.user as User|Member but it can be None in some interaction contexts. interaction.user.bot then raises AttributeError inside interaction_check, which discord.py does not wrap in the View.on_error backstop for interaction_check — the reject path throws instead of cleanly returning False, so the operator gate fails unpredictably for that interaction.

### H12 — `yahir_reusable_bot/discord/panelkit.py:479` · low · SWEEP-NEW · correctness-edge

is_owned_panel with an empty-string marker matches every bot-authored message (startswith('') always True) (ROUTES UPSTREAM)


*Scenario:* marker is REQUIRED with no default but nothing validates it is non-empty. If an app wires marker='' at its composition root, cid.startswith('') returns True for any component, so is_owned_panel treats every bot-authored pinned message as an owned panel — and summon_panel would then delete unrelated bot pins. A one-line non-empty guard would close this.

### H13 — `yahir_reusable_bot/registry/match.py:59` · low · CONFIRMED · empty/degenerate spec + case-sensitivity contract gap

match.py compares against spec.name verbatim while folding the input: an empty name matches every input, and any uppercase in a registered name makes the command permanently unmatchable (ROUTES UPSTREAM)


*Scenario:* (a) A spec with name=='' makes folded.startswith('') always True; for a blank/whitespace-only message stripped=='' so the word-boundary guard doesn't fire and match_command returns ParsedCommand(spec=empty_spec, arg=None), claiming blank input as that command. (b) Input is casefolded (folded=stripped.casefold()) but spec.name is used raw, so a spec registered with an uppercase letter (e.g. 'Status') is permanently unmatchable — folded 'status ...' never startswith 'Status'. No non-empty/lowercase validation on spec.name exists.


*Evidence:* match.py:57-59/61/64-67 verified; reproduced empty-name blank-input claim and 'Status' unmatchable. No consumer hits it (all WeatherBot names lowercase ASCII, none empty). Undocumented precondition; footgun for a future/reuse app.

### H14 — `yahir_reusable_bot/lifecycle/identity.py:83` · low · SWEEP-NEW · resource

write_pid_atomic double-closes fd; the integer may have been reused (ROUTES UPSTREAM)


*Scenario:* On the success sub-path os.write->os.close(fd)(76)->os.replace(77): if os.replace raises, control enters `except BaseException` and calls os.close(fd) again (83). Between the first close and this second close the fd integer can be reallocated by the OS to an unrelated file opened by another thread, so the guarded os.close silently closes someone else's descriptor. The `except OSError: pass` guard hides it. Latent (single-threaded early startup makes it rare); a `closed` flag would be correct.

### H15 — `yahir_reusable_bot/lifecycle/identity.py:162` · low · SWEEP-NEW · wrong-result

non-Linux degrade-to-True fails when proc_marker is a path-like token (ROUTES UPSTREAM)


*Scenario:* _read_proc_cmdline returns the raw proc_marker as its /proc-absent sentinel (162), then _argv_matches_marker basenames argv[0] (prog = Path(...).name, 145) before comparing to proc_marker verbatim. If a bot supplies a path-shaped proc_marker (e.g. b'/usr/bin/thebot'), prog becomes 'thebot' != '/usr/bin/thebot', so the documented non-Linux 'degrade to True' actually returns False — the guard flips to the opposite of its stated portability behavior. proc_marker is documented as a basename token, so this only bites a mis-shaped marker.

### H16 — `yahir_reusable_bot/scheduler/engine.py:74` · low · SWEEP-NEW · contract

SchedulerEngine.remove is non-idempotent (raises JobLookupError) unlike register (ROUTES UPSTREAM)


*Scenario:* remove() forwards straight to scheduler.remove_job(job_id), which raises APScheduler's JobLookupError when the id is not currently scheduled. register() bakes in behavior-preserving options and callers guard removes via list_live_ids, but the engine's own surface is asymmetric: any caller that removes an id a concurrent misfire/coalesce already dropped, or removes twice during a reconcile, gets an uncaught JobLookupError. Should either swallow-on-missing or document the raise.


## Cleanup

### H17 — `yahir_reusable_bot/discord/__init__.py:25` · cleanup · SWEEP-NEW · public-surface-inconsistency

Package __init__ docstring advertises the summon orchestration as an export but summon_panel is neither imported nor in __all__ (ROUTES UPSTREAM)


*Scenario:* The __init__ docstring (11-12) says the adapter exports 'the create-before-delete summon orchestration', and gateway.py lists summon_panel in its __all__, but the package __init__ only re-exports BotThread/build_client/PanelKit/SelectedContext. A consumer following the docstring doing `from yahir_reusable_bot.discord import summon_panel` gets an ImportError.
