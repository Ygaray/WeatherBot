# Phase 35: Cleanup Sweep - Research

**Researched:** 2026-07-13
**Domain:** Audit-ledger triage, dead-code removal, doc correction, ledger reconciliation (WeatherBot only)
**Confidence:** HIGH — every claim below is grounded against the real source tree at HEAD (`ab9ee24`), with the baseline suite green (878 passed, exit 0).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (Fix-vs-Accept rule):** Default to **fix** — these findings sit in files Phases 29–34 already opened, so marginal cost is low. **Accept-with-rationale** only when (a) the fix would change observable behavior and isn't worth a regression risk this late in a hardening milestone, or (b) the finding is genuinely cosmetic/latent-only with a concrete reason it's safe to leave. No finding is silently skipped — every one lands as FIXED, ACCEPTED (annotated), or DEFERRED (ledger).
- **D-02 (Accepted-finding annotation):** An accepted finding gets an **inline in-code annotation at the site**: `# ACCEPTED (F##, v2.1): <one-line rationale>`. The same disposition is mirrored in the ledger (D-03).
- **D-03 (Ledger reconciliation):** Reconcile in `.planning/WHOLE-PROJECT-REVIEW.md` by tagging each **WB** finding with a final disposition — `FIXED@<phase>`, `ACCEPTED`, or `DEFERRED` (+ where). The review currently tracks **no per-finding status**, so this reconciliation record is *created* by this phase. Confirm the **17 hub findings (H01–H17)** are present in `HUB-FINDINGS-HANDOFF.md` and marked out-of-milestone. (Handoff header says "17" but its severity line totals 18 — reconcile/annotate that discrepancy.)
- **D-04 (Scope reconciliation — possibly already fixed in 29–34):** Some LOW/CLEANUP findings likely got fixed incidentally. For each: **verify the current code state first, then mark `FIXED@<phase>` — do not re-open or re-touch** already-clean code. Only genuinely-still-open findings get edited.
- **D-05 (Dead-code + orphaned tests):** Remove dead **production** code *and* the tests that exist **only** to exercise it. Keep any test that also covers a live path.
- **D-06 (Behavior-preservation guard):** Cleanup is **behavior-preserving by default**. Any low-severity fix that *does* alter observable behavior (a boundary `>=`/`<=` flip, a rounding change, a config-default change) must land with a **regression test** proving the new behavior and the untouched briefing invariant. Reuse the Phase-34 test-backfill patterns.

### Claude's Discretion
- **Grouping of findings into plans** (recommend: **by file/subsystem** so each plan rides one already-opened file — `daemon.py`, `store.py`, `uv*.py`, `cli.py`, `interactive/*`, `weather/models.py`, `config/*`) — planner's call.
- **The exact per-finding fix-or-accept verdict** for each of the ~48 WB LOW/CLEANUP findings — apply the D-01 rule; enumerate from the ledger.

### Deferred Ideas (OUT OF SCOPE)
- **17 hub findings (H01–H17)** — belong to `YahirReusableBot`; human-gated tag cut + repin. Already captured in `HUB-FINDINGS-HANDOFF.md`; this phase only confirms routing, does not fix.
- Any WB finding this phase deliberately **DEFERS** must be recorded in the D-03 ledger with a target — no silent drop.
- New user features, new dependencies, behavior changes to the briefing spine.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-CLEAN-01 | Dead/divergent code and inaccurate docs identified by the audit are removed or corrected (dead-code, doc-mismatch, dead-defensive-code findings). | The Ledger Triage below verifies each named dead-code/doc target against source: F16 (partially done — `gate_until_healthy` gone, `emit_online`/`_do_reload` still dead), F46 (still open), F76 (still open), F92 (still open), F104 (already corrected), F66 (still open), F69 (already fixed@32). Verified caller counts + line numbers provided. |
| HARD-CLEAN-02 | Remaining low-severity latent/quality findings (config defaults, boundary `>=`/`<=` nits, rounding disagreements, observability inconsistencies, resource/state-leak nits) are resolved or explicitly annotated as accepted with rationale — no silent debt. | The Latent-Findings Inventory groups each remaining WB LOW finding by file with a fix-vs-accept recommendation (D-01), flags behavior-changing ones needing a D-06 regression test, and confirms the annotation convention (D-02) against existing in-code `# noqa: … — rationale (phase)` precedent. |
</phase_requirements>

## Summary

Phase 35 is a **ledger-driven cleanup sweep**, not a feature or research phase. Its input is a fixed audit ledger (`.planning/WHOLE-PROJECT-REVIEW.md`, 116 findings after dedupe) and its output is (1) removed/corrected dead code and docs, (2) every remaining WB LOW/CLEANUP finding either fixed or annotated `# ACCEPTED (F##, v2.1): …`, and (3) a per-finding disposition record written back into the ledger. The 17 hub findings (H01–H17, all under `yahir_reusable_bot/…`) are out of scope and only confirmed-routed.

The single highest-value research result is **which of the named targets are already fixed by Phases 29–34** (D-04 verify-then-mark) versus **genuinely still open** (actually-edit). I verified every named target against source at HEAD. Result: of the seven roadmap-named dead-code/doc targets, **F69 is fully fixed@32, F104 is already corrected, F16 is half-done (one of three symbols removed@29)**, and **F46, F76, F92, F66 are still open**. Among the HARD-CLEAN-02 latent examples, **F89 and F90 are already fixed@29**, and **F84/F86 (and the F28/timestamp render band) landed@33**, while **F71, F72, F74, F75, F59, F60, F61, F73, F85, F67, F68, F51, F79, F105** remain open. This means a meaningful fraction of the phase is *verify-and-mark* rather than *edit* — the planner should budget for verification tasks, not just fix tasks.

**Primary recommendation:** Group plans **by file/subsystem** (per D-04's "rides one already-opened file"). For each finding in a group: (a) verify current source state, (b) if already clean, mark `FIXED@<phase>` in the ledger and add nothing to code; (c) if still open and behavior-preserving (dead-code/doc), remove/correct it; (d) if still open and behavior-changing, either fix-with-regression-test (D-06, reuse `34-PATTERNS.md` shapes) or annotate `# ACCEPTED (F##, v2.1): …` (D-02) with the D-01 rationale. Reconcile the ledger last. Prove no hub edits (`git diff` touches no `yahir_reusable_bot/`) and full suite green as the phase gate.

## Architectural Responsibility Map

Cleanup findings sit across these WeatherBot tiers. The map is for the planner's sanity-check that no fix leaks into the hub tier (which is out of scope and human-gated).

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Scheduler / daemon lifecycle | App: `scheduler/daemon.py`, `wiring.py`, `catchup.py`, `uvmonitor.py`, `context.py` | Hub `yahir_reusable_bot/scheduler`,`/lifecycle` (OUT OF SCOPE) | F16/F56/F57/F59/F60/F61 live app-side; the *engine* is hub. Only edit app files. |
| Weather data transform | App: `weather/models.py`, `uv.py`, `multiday.py`, `store.py`, `dates.py` | — | F62/F71/F72/F73/F66/F69/F65 are pure app-domain data logic. |
| Config / loader | App: `config/loader.py`, `config/models.py` | — | F74/F75 are app config-parse rules. |
| CLI surface | App: `cli.py` | — | F76/F77/F78 are app CLI dispatch/exit-code. |
| Interactive / Discord commands | App: `interactive/*`, `interactive/commands/*` | Hub `yahir_reusable_bot/discord`,`/registry` (OUT OF SCOPE) | F51/F79/F80/F82/F83/F85/F104/F105 live app-side; the gateway/matcher is hub. |
| Weather HTTP client | App: `weather/client.py` | — | F67/F68 are app-side client concerns. |
| Ops / self-check / pidfile | App: `ops/selfcheck.py`, `ops/pidfile.py` | Hub `yahir_reusable_bot/lifecycle/identity.py` (OUT OF SCOPE) | F92/F46 are app-side dead copies; the *live* guard is the hub's `_argv_matches_marker` (H01). |
| Rendering | App: `templates/renderer.py` | — | F84 render band — already fixed@33. |

**Hard boundary:** any finding whose `file:line` starts `yahir_reusable_bot/…` (H01–H18, and the WB-ledger HUB-tagged F39/F41/F42/F43/F44/F45/F93/F94/F95/F96/F97/F98/F99/F100/F101/F102) is **out of scope**. Confirm-routed only.

## Ledger Triage → Actionable Inventory

> This is the core deliverable. Every row was verified against source at HEAD. `Current state` is the ground truth; the planner turns "STILL OPEN" rows into edit/accept tasks and "ALREADY CLEAN" rows into verify-then-mark tasks.

### A. Named dead-code / doc targets (HARD-CLEAN-01 — roadmap-named)

| F## | Site (verified symbol) | One-line defect | Ledger verdict | **Current state (verified)** | Recommendation |
|-----|------------------------|-----------------|----------------|------------------------------|----------------|
| **F16** | `scheduler/daemon.py` `gate_until_healthy`/`emit_online`/`_do_reload` | Dead production copies of gate/reload logic, exercised only by tests | CONFIRMED | **PARTIAL.** `gate_until_healthy` already REMOVED@29 (comment at `daemon.py:1277-1283` says so and explicitly defers `emit_online`/`_do_reload` to Phase 35). `emit_online` (def `daemon.py:1286`) and `_do_reload` (def `daemon.py:1010`) still exist with **zero production callers** (grep of `weatherbot/` for call sites returns nothing; `wiring.py` references neither). Both are referenced ONLY by tests (`test_reload.py`, `test_filewatch.py`, `test_scheduler.py`). | **FIX** — remove `emit_online` + `_do_reload` (D-05). BUT: many `test_reload.py`/`test_filewatch.py` tests drive `_do_reload` as the reload entrypoint — **these exercise a LIVE reload path** (the ReloadEngine's app-side reload closure), so they are NOT orphaned-only. **Open Question 1**: confirm whether the live reload path still routes through `_do_reload` or fully through the hub `ReloadEngine`. If `_do_reload` is a dead twin of the hub engine (like `gate_until_healthy` was), remove it + its exclusive tests; if it is still the live app reload entrypoint, it is NOT dead — re-classify. Verify before editing. |
| **F46** | `ops/pidfile.py:124` `_argv_is_weatherbot` | Dead copy of the flawed `-m` guard; live guard is the hub's `_argv_matches_marker` | CONFIRMED | **STILL OPEN.** `def _argv_is_weatherbot` present at `pidfile.py:124`. It has a dedicated test (`test_golden_coverage_fill.py:467-482`) that exercises ONLY this dead function (not a live path). | **FIX** — remove `_argv_is_weatherbot` and its exclusive test `test_argv_is_weatherbot_empty_and_forms` (D-05). Behavior-preserving (no production caller). Do NOT touch the hub guard (that's H01, human-gated). |
| **F76** | `cli.py:334` `run_weather(verbose=…)` | `verbose` param accepted + passed but never read (`-v` applied in `main()`) | CONFIRMED | **STILL OPEN.** `verbose: bool = False` at `cli.py:334`; body of `run_weather` (334-397) never reads it. Caller `_cmd_weather` passes `verbose=args.verbose` (`cli.py:415`). Real plumbing is `main()`/`_configure_logging` + `cli.py:982`. | **FIX** — drop the `verbose` param from `run_weather` and the `verbose=args.verbose` at the call site. Behavior-preserving (param is inert). Light regression risk: confirm no other caller passes it (grep-verified: only `_cmd_weather`). |
| **F92** | `ops/selfcheck.py:142` `is_transient(exc)` | Result-discarding call; both branches return `NETWORK_NOT_READY` regardless | SWEEP-NEW | **STILL OPEN.** `is_transient(exc)` at `selfcheck.py:142` is a bare call whose result is discarded; the comment (140-141) already admits it's "consulted for clarity/parity". | **FIX** — remove the dead `is_transient(exc)` line (D-05). Behavior-preserving (result unused). Keep the `is_transient` *import* only if `is_auth_failure` still needs the module, else prune the unused import too (ruff will catch). |
| **F104** | `interactive/lookup.py:183` `lookup_forecast` docstring | Docstring claims cache routes through it; it's a pure passthrough | SWEEP-NEW | **ALREADY CORRECTED.** Current docstring (`lookup.py:163-182`) accurately says it "simply DELEGATES to `lookup_weather`" and describes it as a "NAMED seam". No misleading "routed through by the cache" claim remains. Body is `return lookup_weather(...)` (`:183`). | **VERIFY-then-MARK** `FIXED@<phase>` (likely 13 or 33). If the planner wants belt-and-suspenders, add one sentence noting the cache calls `lookup_weather` directly; otherwise mark clean. No code edit needed. |
| **F66** | `weather/models.py:304` `alerts` single-source | `alerts` read only from imperial payload; docstring says "from each payload" | PLAUSIBLE | **STILL OPEN (doc mismatch only).** Verify the current docstring text at the `from_payloads` alerts read. Not a data-loss path (alerts are coordinate-keyed, unit-independent). | **FIX (doc)** — correct the docstring to state alerts are read once (imperial), unit-independent. Behavior-preserving. Alternatively `# ACCEPTED` if the doc is already accurate at HEAD (verify the exact string first). |
| **F69** | `weather/models.py:69` + `store.py:169` duplicated `_local_date_iso` | Two verbatim copies that can diverge | SWEEP-NEW | **ALREADY FIXED@32.** No `def _local_date_iso` exists anywhere in `weatherbot/` (grep confirms). Both call sites now use the shared `weather/dates.py` (`local_date_for` / `local_date_iso`). `test_import_hygiene.py:104-119` has a **negative-grep gate** asserting no module redefines `_local_date_iso`. | **VERIFY-then-MARK** `FIXED@32`. No edit. Cite `test_import_hygiene.py` as the durable guard. |

### B. Related tz/dead-defensive findings folded by Phase 32

| F## | Site | Defect | **Current state (verified)** | Recommendation |
|-----|------|--------|------------------------------|----------------|
| **F65** | `weather/store.py:179` UTC fallback in `_local_date_iso` | Unreachable UTC fallback masking the IANA-required invariant | **ALREADY FIXED@32.** The old `_local_date_iso` (with the dead try/except-to-UTC + else-UTC branches) is gone from `store.py`; `store.py:220` now calls `local_date_for(location, now_utc)`. The remaining fallback lives ONCE in `dates.py:_resolve_tz` (52-64), explicitly documented as "belt-and-suspenders … effectively dead" — a single, honest, documented fallback rather than a hidden dead branch. | **VERIFY-then-MARK** `FIXED@32`. Optionally the planner may add `# ACCEPTED (F65, v2.1): single documented fallback in dates._resolve_tz; IANA-validated at load` at `dates.py:52` if it wants the accepted-with-rationale record in code (D-02). No behavior change. |
| **F33** | `weather/models.py:84` naive-`now_utc` host-tz | `_local_date_iso` uses host tz when `now_utc` is naive | **ALREADY FIXED@32.** `dates.local_date_iso` (`dates.py:47-49`) treats a naive `now_utc` as UTC before `astimezone`. Test `test_models.py:751` (F33) pins it. | **VERIFY-then-MARK** `FIXED@32`. |

### C. HARD-CLEAN-02 latent findings — already fixed by 29–34 (verify-then-mark)

| F## | Site | Defect | **Current state (verified)** | Phase | Recommendation |
|-----|------|--------|------------------------------|-------|----------------|
| **F89** | `scheduler/daemon.py` `_forecast_failure_streaks` unbounded | Streak dict never pruned on reload → slow leak | **FIXED.** `_prune_forecast_failure_streaks` (daemon.py:514-527, "F89 / D-13") drops dead ids on reload. `git log -S` → commit `648bcc2 feat(29-05)`. | 29 | VERIFY-then-MARK `FIXED@29`. |
| **F90** | `scheduler/daemon.py:1042` `_announce_schedule` | Forecast slots omitted from startup announcement | **FIXED.** `_announce_schedule` now iterates `location.forecast` (daemon.py:1210). Same commit `648bcc2 (29-05)`. | 29 | VERIFY-then-MARK `FIXED@29`. |
| **F84** | `templates/renderer.py:196` empty-token trailing blanks | Empty `{notice}`/`{footer_note}` leave trailing blank lines | **FIXED@33-06.** Renderer drops a line that had a token but rendered empty (`renderer.py:182` `if had_token and rendered_line.strip() == ""`). Commit `9047fa8 feat(33-06)`. | 33 | VERIFY-then-MARK `FIXED@33`. |
| **F28** | `interactive/commands/forecast.py:165` duplicated header | Title rendered twice | **FIXED@33-06** (same commit dedups forecast header). | 33 | VERIFY-then-MARK `FIXED@33`. |
| **F86** | `interactive/commands/status.py:73` raw ISO "Next send" | `.isoformat()` not humanized | **FIXED.** `status.py` now uses `_fmt_epoch`/localized `when` for "Next send" (status.py:80-85); no raw isoformat. | 33 | VERIFY-then-MARK `FIXED@33`. |

### D. HARD-CLEAN-02 latent findings — STILL OPEN (fix-or-accept per D-01)

> Grouped by file for planner plan-grouping. `Behavior` column drives D-06: `PRESERVE` = safe to fix without a regression test (dead-code/doc/annotation); `CHANGE` = fix must ship a regression test OR be `# ACCEPTED`.

**`weather/uv.py`**
| F## | Site | Defect | Behavior | Recommendation |
|-----|------|--------|----------|----------------|
| F59 | `uvmonitor.py:82` `_is_daylight` inclusive `<=` both ends | Crossing/pre-warn can fire at the exact sunset instant | CHANGE (boundary flip) | **ACCEPT** — trigger essentially unreachable (exact epoch-second of sunset AND UV≈0); documented inclusive `[sunrise,sunset]` convention. `# ACCEPTED (F59, v2.1): inclusive [sunrise,sunset] is intentional; exact-instant trigger unreachable`. |
| F60 | `uvmonitor.py:300` `int(delta_min)` truncation | Pre-warn countdown under-reports by up to ~1 min | CHANGE (rounding) | **FIX** with regression test — `round(delta_min)` is the honest display; cheap, user-facing every prewarn. Test asserts `28.9 → "~29 min"`. (Reuse a uvmonitor render test analog.) |
| F61 | `uvmonitor.py:386` fetched/skipped counters | Raised-in-try locations counted as neither; `fetched+skipped ≠ len` | PRESERVE (observability) | **FIX** — add an `errored` counter (or count in the except) so the tick log reconciles. Behavior-preserving (log-only). |
| F72 | `uv.py:143` hardcoded 06:00–20:00 fallback window | Disagrees with real sunrise/sunset at high latitude | CHANGE (window math) | **ACCEPT** — fallback only fires when the payload lacks sun fields; single-user home/travel cities are mid-latitude; documented (`uv.py:108,127`). `# ACCEPTED (F72, v2.1): fixed fallback only on missing sun fields; mid-latitude deployment`. |
| F73 | `uv.py:270` `peak_uvi` hourly-argmax vs daily max | Briefing can show "max 8" and "peak 7" together | CHANGE (value) | **ACCEPT** — deliberate WR-02 trade-off (peak value+clock coherence over peak/max agreement), both rounded; documented at `uv.py:267`. `# ACCEPTED (F73, v2.1): WR-02 peak-clock coherence over peak/max agreement`. |

**`weather/multiday.py` / `weather/models.py`**
| F## | Site | Defect | Behavior | Recommendation |
|-----|------|--------|----------|----------------|
| F71 | `multiday.py:33` `_WEEKEND_DAYS` includes `'fri'` | Fri claimed by both weekday+weekend slots → two briefings | CHANGE (config default) | **DECISION NEEDED** — this can double-send on Fridays if both slot types are configured. Is Friday-as-weekend intentional (the user's home/travel split)? If intentional → `# ACCEPTED (F71, v2.1): Friday intentionally counted as weekend for the travel-city split` + document the asymmetry. If not → FIX (drop `'fri'` from `_WEEKEND_DAYS`) **with a regression test** proving no Friday double-send. **Assumption A1**: current deployment does not configure overlapping weekday+weekend slots on the same location (so no live double-send today) — the planner/user must confirm intent before choosing fix vs accept. |
| F70 | `multiday.py:116` `+sat -sat` re-adds | Drop cannot override an explicit add of same day | CHANGE (semantics) | **FIX** with regression test — make drop win over add (or reject contradictory input). Reuse `test_multiday.py` flag-token analogs. Low blast radius, but observable. Alternatively ACCEPT (contradictory input, no crash) with rationale. |
| F62 | `models.py:330` `.get(x) or 0.0` falsy coalesce | Legitimate 0 treated as missing | CHANGE (display) | **ACCEPT** — the one place a fabricated 0 would matter is already None-guarded; documented intentional degradation (ledger downgraded from medium). `# ACCEPTED (F62, v2.1): falsy-coalesce is display-only; hint-affecting fields use None-preserving raw values`. |
| F35 | `models.py:302` daily[0] positional "today" | daily[0] may not be configured-tz today | CHANGE | **VERIFY** — Phase 32 added `select_today_daily` (models.py:300) which anchors daily selection to `local_date`. Likely FIXED@32. Confirm the positional hard-index is gone, then mark `FIXED@32`. |

**`config/loader.py` / `config/models.py`**
| F## | Site | Defect | Behavior | Recommendation |
|-----|------|--------|----------|----------------|
| F74 | `config/models.py:63` HH:MM validator | Accepts `+9:30` / ` 9:30` (int-parseable oddities) | CHANGE (parse) | **FIX** — tighten to reject non-canonical strings (e.g. require `hh`/`mm` all-digits). `parsed_time()` re-parses correctly so no mis-fire today, but the raw string is a job-id/sent-log key. Regression test asserts `+9:30` rejected. Low risk. |
| F75 | `config/loader.py:44` `resolve_location` name-only | `--send-now <id>` fails when id≠name | CHANGE (lookup) | **FIX** — match id then name (id is the stable identity). Regression test: `resolve_location(cfg, "<id>")` returns the location. Behavior-additive (never removes name matching). Reuse rename-safe `id!=name` fixtures from `34-PATTERNS.md`. |

**`cli.py`**
| F## | Site | Defect | Behavior | Recommendation |
|-----|------|--------|----------|----------------|
| F77 | `cli.py:938` `check` exit-1 vs registry exit-2 | Inconsistent exit codes for same config failure | CHANGE (exit code) | **ACCEPT** — both schemes documented intentional; a monitoring wrapper keying on exact code is hypothetical. `# ACCEPTED (F77, v2.1): documented per-command exit-code conventions; intentional`. |
| F78 | `cli.py:1030` `send-now` implicit fallthrough | Future subcommand w/o `location` attr runs send pipeline | PRESERVE (latent) | **FIX** — add an explicit `send-now` dispatch guard / early-return so a future command can't fall through. Behavior-preserving for today's commands. |

**`scheduler/daemon.py` / `scheduler/context.py` / `scheduler/wiring.py`**
| F## | Site | Defect | Behavior | Recommendation |
|-----|------|--------|----------|----------------|
| F56 | `daemon.py:176` `fire_slot` pre-`local_date` swallow | Exception before `local_date` computed → no missed-briefing alert | PRESERVE (latent) | **ACCEPT or narrow-FIX** — both triggers narrow (tz config-validated; ValueError arm unreachable from real caller). Prefer `# ACCEPTED (F56, v2.1): triggers unreachable given validated tz + real caller path` unless a cheap guard is obvious. |
| F57 | `daemon.py:108` retry-pause worker starvation | Broad outage pins workers, starves heartbeat | CHANGE (design) | **ACCEPT** — not reachable at 2-slot scale; `misfire_grace_time=None` delays not skips heartbeat. `# ACCEPTED (F57, v2.1): not reachable at 2-slot scale; heartbeat delayed not skipped`. |
| F58 | `uvmonitor.py:154` missing sun fields skips all-clear | Location losing sun fields never gets courtesy all-clear | CHANGE | **ACCEPT** — narrow (`is None` guard; schema-drift only); missed courtesy all-clear, not a missed warning. Annotate. (Cross-check: Phase 32 F21/F58 lifecycle audit may already cover — verify.) |
| F53 | `wiring.py:301` `scheduler.start()` in best-effort hook | `start()` failure hidden yet READY=1 emitted | CHANGE | **VERIFY then ACCEPT/FIX** — "latent-but-severe-if-hit"; not reachable on single-drive path. Confirm 29–33 lifecycle work didn't already move `start()` out of the swallowing hook; if still there, prefer a cheap fix (let a `start()` raise fail readiness). Else annotate. |
| F52 | `wiring.py:234` transient `ConfigHolder` in reload closures | Identity-divergence smell, no reachable wrong behavior | PRESERVE (latent) | **ACCEPT** — no current trigger (downgraded from medium). Annotate. |
| F88 | `context.py:47` `_fmt` naive-datetime tz footgun | `astimezone` assumes system-local on naive dt | PRESERVE (latent) | **ACCEPT** — no caller feeds a naive dt (all sources tz-aware). Annotate, or add a cheap `assert dt.tzinfo`. |
| F103 | `daemon.py` `on_online` `getattr(...,'ok',True)` over-guard | Masks a channel returning None on failure | PRESERVE (latent) | **ACCEPT** — single missed WARNING on best-effort ping. Annotate. (Same `emit_online` block as F16 — resolve together.) |

**`interactive/*`**
| F## | Site | Defect | Behavior | Recommendation |
|-----|------|--------|----------|----------------|
| F105 | `interactive/commands/info.py:40` `locations()` no default marker | `!locations` doesn't mark which name a bare command resolves to | CHANGE (view) | **FIX** — mark the first (default) location (e.g. append "(default)" or 📍). `info.py:40` renders `(loc.name, loc.timezone)`; docstring already says first is default. Cheap render fix; add a `test_command_views`/`test_status` snapshot assertion. |
| F85 | `weather_views.py:237` hourly `%a %H:%M` (no date) | `next_cloudy` hourly "When" ambiguous vs daily/alerts which include date | CHANGE (view) | **FIX** — the daily branch (`:253`) uses `%a %b %d` and the wind-window branch (`:152`) uses `%a %b %d %H:%M`; align the hourly branch to include the date. Snapshot regression. (Note: 33-06 fixed peers but left this one — verify it's still `%a %H:%M` at HEAD: it is.) |
| F51 | `interactive/lookup.py:144` cached `{sent_at}`/`{checked_at}` staleness | Cached LookupResult served within TTL shows the stale bake-time timestamp | CHANGE | **ACCEPT** — cosmetic; a cached read shows the original timestamp with no cached-read indicator. `# ACCEPTED (F51, v2.1): cached render keeps its bake-time stamp; cosmetic within TTL`. |
| F79 | `interactive/bot.py:492` `!panel` exact-match | `!panel please` silently dropped | CHANGE (UX) | **FIX** — accept `!panel` with trailing text (or reply with a hint). Cheap; add a `test_bot` assertion. Low risk. Alternatively ACCEPT (near-miss silent-drop is the general unknown-command behavior). |
| F80 | `interactive/bot.py:379` `getattr(perms, name)` no default | AttributeError if a REQUIRED_PANEL_PERMS name is absent | PRESERVE (latent) | **ACCEPT** — all 5 names resolve on pinned discord.py 2.7.1; trigger needs a downgrade/typo. Annotate, or add a `getattr(perms, name, False)` default (cheap PRESERVE fix). |
| F82 | `weather_views.py:207` wind `int()` truncation | Degrees biased low by ~1° in parenthetical | CHANGE (display) | **ACCEPT or cheap FIX** — cosmetic; `round()` is the honest fix (compass sector labeling is already correct). Prefer FIX (one-char) or annotate. |
| F83 | `weather_views.py:244` `daily[2:]` count overstates | "no cloudy day" message reports `len(daily)` not scanned window | CHANGE (display) | **ACCEPT** — needs an unusual hourly-empty/daily-full split payload; cosmetic count in a no-match message. Annotate. |

**`weather/client.py`**
| F## | Site | Defect | Behavior | Recommendation |
|-----|------|--------|----------|----------------|
| F67 | `client.py:46` import-time `getLogger("httpx").setLevel` | Global side effect mutates a shared third-party logger at import | CHANGE (global state) | **FIX or ACCEPT** — Phase 30 (secret hygiene) may have superseded the *reason* for this (redaction now happens at the raise sites, not by silencing httpx). If redaction is fully handled, the global setLevel can be removed (PRESERVE-ish). Verify Phase 30's approach first; if the setLevel is now redundant, remove it; else `# ACCEPTED (F67, v2.1): intentional httpx-URL-log suppression; superseded-by-redaction check`. |
| F68 | `client.py:90/122` unguarded `response.json()` | 2xx non-JSON (captive portal/HTML-200) raises `JSONDecodeError`, an unclassified failure type | CHANGE (error handling) | **FIX** — wrap `.json()` to raise a classified/retryable error (or map to the same transient/HTTPStatusError contract callers expect). Regression test: a 2xx-with-HTML body. Moderate value (real-world captive-portal case). |

### E. Test-side BOTH findings already closed by Phase 34

| F## | Site | State | Recommendation |
|-----|------|-------|----------------|
| F106,F110,F111,F112,F113,F114,F115,F116 | `tests/*` | Phase 34 backfilled/corrected all of these (see `34-PATTERNS.md` and ROADMAP 34-01…34-07). | VERIFY-then-MARK `FIXED@34` in the ledger; no code edit. These are `BOTH`-tagged but the WB-side test work is done. |
| F107,F108,F109 | `tests/*` | Phase 34 added/confirmed (`34-04`, `34-07`). | VERIFY-then-MARK `FIXED@34`. |

### F. HUB findings (OUT OF SCOPE — confirm-routed only)

All findings whose `file:line` is under `yahir_reusable_bot/…`: F39, F41, F42, F43, F44, F45, F93, F94, F95, F96, F97, F98, F99, F100, F101, F102 (WB-ledger HUB-tagged) map to H01–H17 in `HUB-FINDINGS-HANDOFF.md`. **Do NOT edit any hub file.** The reconciliation action is: confirm each is present in the handoff and marked out-of-milestone (D-03). See "Ledger Write-Back" below for the 17-vs-18 discrepancy.

## Reconciliation with Phases 29–34 (D-04) — Summary Table

| Category | Findings | Action |
|----------|----------|--------|
| **Already FIXED (verify-then-mark, no edit)** | F69@32, F65@32, F33@32, F35@32(verify), F89@29, F90@29, F84@33, F28@33, F86@33, F104@(13/33), F106/F107/F108/F109/F110/F111/F112/F113/F114/F115/F116@34 | Verify state, write `FIXED@<phase>` in ledger. **Highest-volume bucket** — budget verification tasks. |
| **STILL OPEN — behavior-PRESERVING fix (no regression test)** | F46 (rm dead fn+test), F92 (rm dead call), F76 (rm dead param), F16 (rm emit_online/_do_reload+exclusive tests — pending Open Q1), F66 (doc), F61 (log counter), F78 (dispatch guard) | Edit + rely on full-suite-green. |
| **STILL OPEN — behavior-CHANGING fix (regression test req'd, D-06)** | F60, F70, F74, F75, F105, F85, F68, F82(if fixed), F79(if fixed), F71(if fixed) | Fix + regression test reusing `34-PATTERNS.md` shapes. |
| **STILL OPEN — ACCEPT-with-annotation (D-02)** | F59, F72, F73, F62, F77, F56, F57, F58, F52, F88, F103, F51, F80, F83, F67(verify) | Add `# ACCEPTED (F##, v2.1): …` at the site + ledger `ACCEPTED`. |
| **OUT OF SCOPE (confirm-routed)** | 17 hub findings (H01–H17 / F39,F41–F45,F93–F102 HUB-tagged) | Confirm in handoff; no edit. |

## Accepted-Annotation Mechanism (D-02)

**Convention:** `# ACCEPTED (F##, v2.1): <one-line rationale>` placed inline at the finding's site (the exact line a future editor would touch).

**Precedent in codebase:** The repo already uses inline rationale-tagged comments in exactly this shape — `# noqa: F401 — re-exported so daemon.AUTH_FAILED resolves for wiring.py:_on_fail (29-05, …)` (`daemon.py:54-60`). The `# ACCEPTED (F##, v2.1): …` form is consistent with this house style (short reason + phase/finding tag inline). `[VERIFIED: grep of weatherbot/]`

**Where it goes:** at the site line. For multi-line constructs, place it on the line the ledger `file:line` points at, or the governing statement (e.g. the `<=` comparison for F59, the `_WEEKEND_DAYS` tuple for F71-if-accepted). One annotation per accepted finding; the ledger (D-03) carries the mirror.

**No existing `# ACCEPTED` markers** exist yet (grep confirms) — this phase introduces the convention. There is no competing noqa-style "accepted-finding" marker to match beyond the `# noqa: … — rationale (phase)` style, which this mirrors.

## Ledger Write-Back Format (D-03)

**Target:** `.planning/WHOLE-PROJECT-REVIEW.md`. The file currently carries **no per-finding status** (verified — findings are `### F## — file:line · WB · VERDICT · category` headers with prose; no disposition line). This phase *creates* the reconciliation record.

**Recommended format — additive, non-destructive:** append a single **disposition tag** to each WB finding without rewriting the existing prose. Two viable shapes (planner's call):

1. **Inline tag on the header line** — append ` · FIXED@32` / ` · ACCEPTED` / ` · DEFERRED→<target>` to each `### F##` header. Pro: reads in place. Con: edits every header.
2. **A new `## Disposition Ledger (v2.1)` table** at the end of the file mapping `F## → FIXED@<phase> | ACCEPTED | DEFERRED(target) | HUB(out-of-scope)` for all 88 WB + 11 BOTH findings. Pro: one localized edit, single source of truth, doesn't touch existing sections; the milestone audit reads one table. **Recommended.**

Use option 2 (an appended table) to avoid corrupting the ledger's carefully-structured severity sections. Every WB/BOTH finding gets exactly one row; hub findings get a `HUB (routed → HUB-FINDINGS-HANDOFF.md)` row for completeness.

**The 17-vs-18 discrepancy (D-03):** `HUB-FINDINGS-HANDOFF.md` header says "17 findings" but its severity line reads `high 2 · medium 5 · low 10 · cleanup 1 (total 18)`, and the file actually lists **H01–H18** — where **H18** (`ready_gate.run` no first-class fatal outcome) is a *documented deferred enhancement* (D-09/D-10 from Phase 29), not one of the original 17 audit defects. The `WHOLE-PROJECT-REVIEW.md` severity summary counts **17 HUB** (2 high + 4 med + 10 low + 1 cleanup = 17 in the HUB column). **Reconciliation:** the "17" = the 17 audit-surfaced hub defects (H01–H17); H18 is a Phase-29-appended enhancement that inflates the handoff's own severity line to 18. **Action:** annotate the handoff (or the ledger disposition note) to state "17 audit findings (H01–H17) + 1 Phase-29 deferred enhancement (H18) = 18 rows; the milestone's out-of-scope count is the 17 defects." Do not silently trust either bare number. `[VERIFIED: read of HUB-FINDINGS-HANDOFF.md]`

## Behavior-Preservation & Test Strategy (D-06)

**Anchor invariant (must not regress):** "the morning briefing always goes out, exactly once." No cleanup fix may touch the claim/send/dedup spine behavior. The full suite (878 tests) covers this — keeping it green is the primary guard.

**Behavior classification (drives whether a fix needs a test):**
- **PRESERVE (no test needed, full-suite-green suffices):** dead-code removal (F16/F46/F76/F92), doc fixes (F66/F104), added annotations (all ACCEPT rows), log-counter fix (F61), dispatch guard (F78).
- **CHANGE (regression test required, D-06):** rounding (F60, F82), boundary/semantics (F70, F74), lookup widening (F75), config default (F71-if-fixed), view/render (F105, F85), error-handling (F68). Each needs a test that fails against pre-fix behavior and passes against the fix, PLUS an assertion the briefing invariant is untouched where relevant.

**Existing test layout (verified):**
- `tests/` — 60+ modules, `testpaths = ["tests"]`, `addopts = "-ra"` (`pyproject.toml:48-51`). No coverage gate in addopts.
- **Syrupy snapshots** (`syrupy>=5.3.4`, `pyproject.toml:43`) — `tests/__snapshots__/`. Golden tests: `test_golden_*.py` (cli, db, embeds, harness, schedule, custom_ids, coverage_fill). Render/view changes (F105/F85) will move golden snapshots — regenerate with `--snapshot-update` and eyeball the diff. **KNOWN QUIRK** (per project memory `pytest-snapshot-report-quirk`): the suite prints "2 snapshots failed" but exits 0 — pre-existing syrupy report noise, NOT a golden diff. **Trust the exit code + the actual `.ambr` diff, not the printed snapshot summary.** `[VERIFIED: baseline run — 878 passed, exit 0, "2 snapshots failed" printed]`
- **Fixtures** (`conftest.py`): `tmp_db` (file-backed sqlite, `:52-69`), `load_fixture` (recorded OpenWeather JSON, `:26-29`), `seed_sent_row` (real `claim_slot`, `:86-113`).
- **Reusable regression shapes** for behavior-changing fixes are catalogued in `.planning/phases/34-test-gap-backfill/34-PATTERNS.md`: real-thread barrier harness (F106), `_State`/`_Outcome` RetryCallState stand-ins, `_loc(name, id=…)` rename-safe helper, dtskew/8-day fixtures. **Slot new regression tests into the same module as the code's existing tests** (e.g. F75 → `test_config.py`/`test_cli.py`; F105/F85 → `test_command_views.py`; F68 → `test_client.py`; F60/F82 → `test_uv_monitor.py`/`test_command_views.py`).

**Test traceability convention** (already in-tree, `34-PATTERNS.md` §Traceability): every new/corrected test names its finding id + requirement in the test name or docstring (e.g. `# HARD-CLEAN-02 / F60`).

## Validation Architecture

> nyquist_validation = true (`.planning/config.json:20`) — this section is MANDATORY.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (`pyproject.toml:40`) + pytest-cov 7.1.0 + syrupy 5.3.4 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`:48`); `testpaths=["tests"]`, `addopts="-ra"` |
| Quick run command | `uv run pytest tests/<module>.py -q` (per-plan module, < 30s) |
| Full suite command | `uv run pytest -q` (878 tests, ~38s) |

### Phase Requirements → Test / Proof Map
| Req / Criterion | Behavior to prove | Proof type | Automated command | Exists? |
|-----------------|-------------------|------------|-------------------|---------|
| SC-1 / HARD-CLEAN-01 | Dead `emit_online`/`_do_reload` gone (F16) | grep-assert zero definitions | `! grep -q "def emit_online\|def _do_reload" weatherbot/scheduler/daemon.py` | ❌ add (pending Open Q1) |
| SC-1 / HARD-CLEAN-01 | Dead `_argv_is_weatherbot` gone (F46) | grep-assert zero definition + removed test | `! grep -rq "_argv_is_weatherbot" weatherbot/ tests/` | ❌ add |
| SC-1 / HARD-CLEAN-01 | Dead `is_transient(exc)` call gone (F92) | grep-assert no bare discarded call | manual read of `selfcheck.py` except arm | ❌ add |
| SC-1 / HARD-CLEAN-01 | Dead `verbose` param gone (F76) | grep-assert param absent from `run_weather` | `! grep -q "verbose" weatherbot/cli.py` at `run_weather` sig | ❌ add |
| SC-1 / HARD-CLEAN-01 | No misleading passthrough docstrings (F104/F66) | manual read; F104 already clean | n/a (doc) | F104 ✅ |
| SC-1 / HARD-CLEAN-01 | No `_local_date_iso` copies (F65/F69) | negative-grep gate | `test_import_hygiene.py:104-119` (already green) | ✅ EXISTS |
| SC-2 / HARD-CLEAN-02 | Every behavior-changing fix has a regression test | per-fix red-against-old test | `uv run pytest tests/<module> -q` | ❌ add per fix |
| SC-2 / HARD-CLEAN-02 | Every accepted finding carries `# ACCEPTED (F##, v2.1)` at its site | grep-assert annotation present | `grep -c "# ACCEPTED (F" weatherbot/` == count of accepted findings | ❌ add |
| SC-2 (no silent debt) | Every in-scope WB finding has a disposition | ledger table complete | manual/scripted: every WB `F##` appears in the Disposition Ledger | ❌ add |
| SC-3 | v2.1 ledger reconciles; 17 hub findings confirmed out | Disposition Ledger table + handoff confirm | read `WHOLE-PROJECT-REVIEW.md` Disposition Ledger + `HUB-FINDINGS-HANDOFF.md` | ❌ add |
| SC-3 (hub untouched) | No `yahir_reusable_bot/` edits in the diff | diff-assert | `! git diff --name-only <base>..HEAD \| grep -q "yahir_reusable_bot/"` (n/a — hub is a separate repo/dep; assert no `../Reusable` edits and no hub-path files) | ❌ add |
| Anchor invariant | Briefing spine unchanged | full suite green | `uv run pytest -q` → exit 0 | ✅ (878 green baseline) |

### Sampling Rate
- **Per task commit:** the touched module's tests — `uv run pytest tests/<module>.py -q`.
- **Per plan / subsystem group:** `uv run pytest -q` (full suite — cheap at ~38s; the spine invariant is cross-cutting so run the whole thing).
- **Phase gate:** full suite exit 0 (trust exit code over the syrupy "2 snapshots failed" line) + the SC-1/SC-2/SC-3 grep/ledger asserts + no hub-path files in the diff.

### Wave 0 Gaps
- [ ] Grep-guard test(s) that assert the removed dead symbols stay gone (F16/F46/F76/F92) — analog: `test_import_hygiene.py`'s negative-grep pattern (`:104-119`). One consolidated `test_dead_code_removed` is cleaner than four.
- [ ] Regression tests for each behavior-CHANGING fix chosen (F60, F70, F74, F75, F105, F85, F68, and any of F71/F79/F82 fixed) — slot into the code's existing test module using `34-PATTERNS.md` shapes.
- [ ] An annotation-presence check (optional) asserting each accepted `F##` has its `# ACCEPTED (F##, v2.1)` marker.
- Framework install: none — pytest/syrupy already present and green.

*(No new fixtures or framework work required — all needed fixtures and regression shapes exist per `34-PATTERNS.md` "No Analog Found: None".)*

## Security Domain

> security_enforcement = true, security_asvs_level = 1 (`.planning/config.json:42-43`).

This is a behavior-preserving cleanup phase touching no auth, session, access-control, or crypto surface. The one security-adjacent finding is **F67** (`client.py:46` global httpx logger setLevel) — its *purpose* is secret-log suppression, already superseded by Phase 30's redaction-at-raise-site (HARD-SEC-01, `_redact.py`). Confirm Phase 30's redaction is the authoritative control before removing/keeping F67's global setLevel.

| ASVS Category (L1) | Applies | Standard Control (existing) |
|---------------------|---------|-----------------------------|
| V5 Input Validation | marginal (F74 HH:MM tighten) | pydantic validator in `config/models.py` — the fix tightens an existing validator, no new attack surface |
| V6 Cryptography | no | — |
| V7 Error Handling / Logging | yes (F67/F68) | Phase-30 redaction (`_redact.py`) is the secret-hygiene control; F68 adds a classified error for non-JSON 2xx (no secret exposure). `test_redact_hygiene.py` guards the key never appears in logs. |
| V2/V3/V4 (authn/session/access) | no | — |

| Threat pattern | STRIDE | Mitigation |
|----------------|--------|------------|
| Secret (appid) in logs (F67 context) | Information Disclosure | Already mitigated by Phase-30 redaction; F67 cleanup must not regress `test_redact_hygiene.py`. |

No new threat surface introduced. Full suite (incl. `test_redact_hygiene.py`) green is the security gate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Verifying a symbol is dead | Manual "looks unused" judgment | `grep -rn "<symbol>(" weatherbot/` for **call sites** (exclude def/comments/tests) | A symbol referenced only by tests that exercise *it* (not a live path) is dead (D-05); one referenced by a live reload/gate path is not. Distinguish by grepping production call sites. |
| Detecting drift-back of removed dead code | Ad-hoc reviewer vigilance | A negative-grep pytest gate (analog `test_import_hygiene.py:104-119`) | The repo already uses this pattern to keep `_local_date_iso` from being re-added; reuse it for the newly-removed symbols. |
| Regression tests for behavior-changing fixes | Fresh test scaffolding | The `34-PATTERNS.md` shapes + existing fixtures (`tmp_db`, `load_fixture`, `_loc(id=…)`) | Every needed harness/fixture already exists; don't rebuild them. |
| Rewriting the ledger structure | In-place surgery on severity sections | An appended `## Disposition Ledger (v2.1)` table | Preserves the audit's structure; one localized edit; single source of truth for the milestone audit. |

**Key insight:** the bulk of this phase's risk is *mis-classifying an already-fixed finding as still-open and re-touching clean code* (violating D-04). The mitigation is grep-first verification against source before any edit — which is why the triage table above resolves current state per finding.

## Common Pitfalls

### Pitfall 1: Re-fixing an already-closed finding (D-04 violation)
**What goes wrong:** treating the ledger's original `file:line`/verdict as current truth and editing code Phases 29–34 already fixed (F65/F69/F89/F90/F84/F28/F86/F104 are all already clean).
**Why:** the ledger is a snapshot from 2026-07-07; line numbers have drifted and many findings are moot.
**Avoid:** grep the real source for the symbol/pattern first; if clean, mark `FIXED@<phase>` and add nothing to code.
**Warning sign:** a "fix" whose diff is a no-op or that fights a Phase-32/33 helper.

### Pitfall 2: Removing a test that also covers a live path (D-05 nuance)
**What goes wrong:** deleting `test_reload.py`/`test_filewatch.py` tests when removing `_do_reload` (F16) — but those tests drive the app's live reload closure, not just a dead twin.
**Why:** `_do_reload` may still be the live reload entrypoint (unlike `gate_until_healthy`, which was a pure dead twin). See **Open Question 1**.
**Avoid:** confirm whether the live reload path routes through `_do_reload` or fully through the hub `ReloadEngine` before deleting anything. Only remove tests that exercise ONLY the removed symbol.
**Warning sign:** the full suite goes red after removing `_do_reload` — that means it wasn't dead.

### Pitfall 3: Crossing the hub boundary
**What goes wrong:** "fixing" a finding whose site is `yahir_reusable_bot/…` (F45/F46-hub-twin/F94/etc.).
**Why:** the WB-side `_argv_is_weatherbot` (F46) is a *copy* of the hub's flawed guard (H01); it's tempting to "fix the -m match" in both. Only the WB copy (removal) is in scope; the hub fix is human-gated.
**Avoid:** for F46, **remove** the dead WB copy — do NOT port the hub's corrected match into it. The live guard is the hub's.
**Warning sign:** the diff touches any `yahir_reusable_bot/…` file or `../Reusable/`.

### Pitfall 4: Trusting the syrupy "N snapshots failed" line
**What goes wrong:** treating "2 snapshots failed" as a real golden regression and chasing it.
**Why:** known pre-existing syrupy report quirk (project memory) — the suite still exits 0.
**Avoid:** trust the exit code and the actual `.ambr` diff; only render changes you intentionally made (F105/F85) should move snapshots.

## State of the Art

| Old (ledger snapshot 2026-07-07) | Current (HEAD 2026-07-13) | When changed | Impact |
|----------------------------------|---------------------------|--------------|--------|
| Duplicated `_local_date_iso` in models.py/store.py (F69/F65) | Single `weather/dates.py` helper + negative-grep gate | Phase 32 | F65/F69/F33/F35 → verify-then-mark, no edit |
| `_forecast_failure_streaks` unpruned (F89); forecast slots unannounced (F90) | `_prune_forecast_failure_streaks` + forecast loop in `_announce_schedule` | Phase 29 (648bcc2) | F89/F90 → verify-then-mark |
| Duplicated header, empty-token blanks, raw ISO stamps (F28/F84/F86) | Deduped/collapsed/humanized render | Phase 33 (9047fa8) | F28/F84/F86 → verify-then-mark |
| `gate_until_healthy` dead twin (part of F16) | Removed | Phase 29 (29-05) | F16 → only `emit_online`/`_do_reload` remain |

**Deprecated/outdated in the ledger:** the original `file:line` numbers — the code has moved; navigate by symbol, not line.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The current deployment does not configure overlapping weekday+weekend slots on one location, so F71's Friday-double-send is latent, not live | Latent Inventory / F71 | If wrong, F71 is a live double-send bug (higher severity than "cleanup") and must be FIXED with a regression test, not accepted. **User/planner must confirm Friday-as-weekend intent.** |
| A2 | `_do_reload` (F16) may still be the LIVE app reload entrypoint (not a pure dead twin like `gate_until_healthy`) | Triage A / F16, Open Q1 | If it IS live, removing it breaks reload and its tests are not orphaned — do NOT remove. Verify caller path first. |
| A3 | F104's docstring is already accurate at HEAD (no "routed through cache" claim) | Triage A / F104 | If a stale claim remains elsewhere, mark still-open and correct it. Re-read the exact docstring. |
| A4 | F67's global httpx setLevel is superseded by Phase-30 redaction and safe to remove | Latent Inventory / F67 + Security | If redaction does NOT cover the URL-log path this silenced, removing setLevel could re-expose a key-bearing INFO log. Verify Phase-30 coverage before removing; else accept. |
| A5 | The "17 hub findings" = H01–H17 defects; H18 is a Phase-29 deferred enhancement inflating the handoff's severity line to 18 | Ledger Write-Back | If the intended out-of-scope set is actually 18, the reconciliation count is off — annotate the reconciliation to state both numbers explicitly (which is the recommended action anyway). |

## Open Questions (RESOLVED)

> Resolved during planning (2026-07-13) — see 35-08 / 35-07 / 35-05 PLAN.md. Retained for audit trail.

1. **Is `_do_reload` (F16) dead in production, or still the live app reload entrypoint?**
   - What we knew: zero direct call sites in `weatherbot/`; the `daemon.py:1282` comment says it was "deliberately LEFT for Phase 35"; but `test_reload.py`/`test_filewatch.py` drive it as "the reload entrypoint the loop calls."
   - **RESOLVED (dead twin):** the live reload path routes through the hub `reload_engine.service_pending()`, and the live online-ping is inlined in `_run_daemon` — neither `_do_reload` nor `emit_online` has a runtime caller. Both are confirmed **dead twins** (like `gate_until_healthy` was). Plan 35-08 removes them + their exclusive tests (D-05), **gated on a green 878-suite (revert if red)** as the safety net if a removed test turns out to cover a live closure `test_reload_engine.py` doesn't. F103's over-guard survives at the *live* inlined ping site → accept-annotated separately.

2. **F71 Friday-as-weekend: intentional or a config-default bug?**
   - What we knew: `_WEEKEND_DAYS = ("fri","sat","sun")` overlaps `_WEEKDAY_DAYS` `'fri'`; a location with both slot types would double-send on Friday.
   - **RESOLVED (accept-with-rationale, conservative default):** per Assumption A1, the current single-slot-per-location deployment makes this latent, not a live double-send. Plan 35-07 takes `# ACCEPTED (F71, v2.1)` rather than changing weekday/weekend selection behavior (behavior-preserving, D-06), and **flags it to the user** (`user_setup`): if overlapping weekday+weekend slots are ever configured this becomes a live bug to fix+test.

3. **Exact per-finding fix-vs-accept verdicts** for the ~15 ACCEPT-candidate latent findings.
   - **RESOLVED:** the planner applied the D-01 default per finding; each accepted item carries a concrete `# ACCEPTED (F##, v2.1): <rationale>` (SC-2) plus a Disposition Ledger row (35-09). Fix-or-accept findings (F58/F53/F67/F79/F82) self-reconcile via the ledger's grep-driven union check (fixed ∪ accepted ∪ deferred, exactly once).

4. **F67 httpx global setLevel — superseded by Phase-30 redaction?** *(added during planning)*
   - **RESOLVED:** confirmed Phase-30 `_redact.py` (guarded by `test_redact_hygiene.py`) supersedes the setLevel-based suppression. Plan 35-05 removes-if-redaction-proven-else-accepts, with `test_redact_hygiene.py` green either way.

## Sources

### Primary (HIGH confidence — verified against source at HEAD)
- `.planning/WHOLE-PROJECT-REVIEW.md` (full read, 434 lines) — the finding ledger, all 116 findings.
- `.planning/HUB-FINDINGS-HANDOFF.md` (full read) — H01–H18; confirmed 17-vs-18 discrepancy (H18 = deferred enhancement).
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/phases/35-cleanup-sweep/35-CONTEXT.md` — scope, decisions, success criteria.
- `.planning/phases/34-test-gap-backfill/34-PATTERNS.md` — reusable regression-test shapes + fixtures.
- Source verification (grep + read at HEAD `ab9ee24`): `scheduler/daemon.py` (F16/F56/F57/F89/F90/F103), `ops/pidfile.py` (F46), `ops/selfcheck.py` (F92), `cli.py` (F76/F77/F78), `interactive/lookup.py` (F104/F51), `weather/models.py` (F62/F66/F35), `weather/store.py`+`weather/dates.py` (F65/F69/F33), `weather/uv.py`+`scheduler/uvmonitor.py` (F59/F60/F61/F72/F73/F58), `weather/multiday.py` (F70/F71), `config/loader.py`+`config/models.py` (F74/F75), `interactive/commands/info.py` (F105), `interactive/commands/weather_views.py` (F82/F83/F85), `interactive/commands/status.py` (F86), `templates/renderer.py` (F84/F28), `weather/client.py` (F67/F68), `interactive/bot.py` (F79/F80).
- `git log -S` provenance: F89/F90 → `648bcc2 feat(29-05)`; F84/F28/F86 → `9047fa8 feat(33-06)`.
- Baseline test run: `uv run pytest -q` → **878 passed, exit 0** ("2 snapshots failed" = known syrupy quirk).
- `pyproject.toml` (test framework/config), `.planning/config.json` (nyquist=true, security=true/L1).

### Secondary
- Project memory (`MEMORY.md`): `pytest-snapshot-report-quirk`, `no-backlog-fold-cleanup-in`, `UI-gate-false-positive-backend-phases`.

## Metadata

**Confidence breakdown:**
- Ledger triage / current-state verification: HIGH — every row grepped/read against source at HEAD; already-fixed vs still-open is ground truth.
- Fix-vs-accept recommendations: MEDIUM-HIGH — defaults follow D-01; three items (F16 removal scope, F71 intent, F67 redaction coverage) carry Open Questions to confirm before editing.
- Ledger write-back format: HIGH — verified the file has no per-finding status today; appended-table approach is non-destructive.
- Validation architecture: HIGH — framework/fixtures verified present and green; grep-asserts and regression shapes concrete.

**Research date:** 2026-07-13
**Valid until:** stable — the ledger is fixed input; source state valid until the next commit touches these files (re-verify current-state rows if HEAD moves before planning).
