---
gsd_state_version: 1.0
milestone: v2.1
milestone_name: Hardening
status: planning
last_updated: "2026-07-08T03:38:59.212Z"
last_activity: 2026-07-08
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-07 — v2.0 "The Great Decoupling" shipped)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Planning next milestone — v2.0 shipped (reusable bot core extracted to `YahirReusableBot`, pinned v0.1.1)

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-07-08 — Milestone v2.1 started

## v2.0 Roadmap at a Glance

| Phase | Goal (short) | Requirements |
|-------|--------------|--------------|
| 21 | Lay byte-identical golden/characterization snapshots (embeds, CLI, schedule plan, DB rows, custom_ids, exception identity) — the oracle every later phase re-runs | BHV-02, BHV-01 |
| 22 | Extract `Channel` + delivery-reliability into the clean in-place module boundary; stand up the import-lint/litmus-grep hygiene gate | SEAM-01, PKG-01 |
| 23 | Generic `SchedulerEngine.register(...)` + `OccurrenceStore` exactly-once + serialization-clean `JobStore` Protocol (in-memory impl only) | SEAM-02, SEAM-03 |
| 24 | Generic `ConfigHolder[T]` + `ReloadEngine` over an app-defined schema via injected `validate` / `desired_jobs` hooks | SEAM-04 |
| 25 | Lifecycle READY-gate on an app health-check + single composition root; prove the 4 leak-points are injected (litmus-grep clean) | SEAM-05, APP-01, APP-02 |
| 26 | Move the self-describing registry + shared dispatcher into the module; app registers commands; CLI/Discord/help derive, drift impossible | SEAM-06 |
| 27 | Relocate Discord adapter (`BotThread` + `PanelKit` + `SelectedContext`); inject `render` to fix the cycle by ownership; freeze custom_ids + `discord.py==2.7.1` | SEAM-07 |
| 28 | Physical split to `YahirReusableBot` repo + uv git dep + EXTENSION-GUIDE + live `yahir-mint` restart UAT | PKG-02, DOCS-01 |

**Dependency notes:** Leaf-seams-first, split-last. Goldens (21) before any move. Channel (22) is the lowest-risk warm-up and establishes the boundary + import-hygiene gate. Scheduler (23) before config-reload (24) because reload reconciles *jobs* through the engine. Lifecycle + composition root (25) follows config (it depends on the holder) and is where the four leak-points get wired/proven. Registry (26) registers commands at that root. The Discord adapter (27) is near-last — it consumes the registry *and* the relocated `render_embed`. The physical split (28) is strictly last, re-running the Phase-21 goldens against the git-pinned module. **Cross-cutting:** BHV-01 (suite green) re-runs every phase; PKG-01 import-hygiene + APP-02 litmus-grep are standing gates on every seam phase (22–27).

**Research flags (`--research-phase` candidates):** **Phase 23** (APScheduler serialization-clean `JobStore` seam — importable callable + picklable args + fire-time lookup, design-now/build-later), **Phase 24** (pydantic-v2 generic-validation pitfall + `validate`/`desired_jobs`/rollback hook shapes — highest-coupling seam), **Phase 27** (resolve the render cycle by ownership while preserving every v1.3 persistent-view/clone-path/custom_id invariant byte-identically), **Phase 28** (packaging/namespace/entry-point/dev-vs-deploy mechanics + live-host UAT — most "works locally, breaks on host" surface). Phases 21/22/25/26 have HIGH-confidence patterns (skip research-phase).

**Reuse anchors (brownfield — pure extraction, byte-identical):** the runtime stack is unchanged (httpx, APScheduler 3.x, tenacity, structlog, discord.py 2.7.1, watchfiles, cachetools, pydantic, SQLite). Existing seams to un-braid in place: `channels/base.py` + `reliability/retry.py` (→ Channel, Phase 22); `scheduler/daemon.py` `fire_slot`/`claim_slot`/`_register_jobs`/`_reconcile_jobs` (→ SchedulerEngine/OccurrenceStore, Phase 23); `config/holder.py` + `_do_reload`/`validate_config_and_templates`/`_desired_job_ids` (→ ConfigHolder[T]/ReloadEngine, Phase 24); `ops/sdnotify.py` + `ops/selfcheck.py` `gate_until_healthy`/`run_self_check` (→ Lifecycle + injected HealthCheck, Phase 25); `interactive/dispatch.py` + `registry.COMMANDS` (→ registry/dispatch seam, Phase 26); `interactive/bot.py` `render_embed` + `interactive/panel.py` `PanelView` (→ Discord adapter + PanelKit, cycle fix by DI, Phase 27). The litmus on every seam: *"could a reminder bot use this with zero weather assumptions?"*

## Performance Metrics

**Velocity (shipped):** v1.0 — 47 plans / Phases 1–5 / 11 days / 186 tests. v1.1 — 22 plans / Phases 6–11 / ~4 days / 291 tests. v1.2 — 15 plans / Phases 12–15 / 575 tests. v1.3 — 11 plans / Phases 16–20 / ~4 days / 649 tests / 18 feat commits.

**v2.0:** Phase 21 plans 21-01..21-05 all complete (5 plans). Suite now **732 tests green** on `main` (652 baseline + Wave-1 goldens/identity + 39 Plan-05 branch-fill characterizations), zero-flake. Branch-coverage audit over the 6 move-path packages is CLEAN (89%→93%, every uncovered move-path branch filled or excused with a named reason; no fail_under gate — D-08). 21-05 duration ~40min, 2 files created + 5 modified (4 pragma-only + .gitignore).

## Accumulated Context

### Decisions

Full decision log lives in PROJECT.md Key Decisions. v2.0-specific governing decisions (from milestone scope + research):

- **Pure extraction, byte-identical (whole milestone):** the existing suite + new golden tests are the acceptance contract — "tests green" is necessary but NOT sufficient; the Phase-21 goldens (embed bytes, CLI stdout/exit, schedule plan, DB rows, custom_ids, exception identity) are the byte-identical oracle. Never edit a test to make a "pure" refactor pass.
- **In-place seam first, physical split LAST:** un-braid mechanism from content into a clean internal package boundary (tests green) *before* the `git mv` to `YahirReusableBot`. The boundary subpackage is named what the extracted package will be, so the split is a `git mv` not a rename.
- **Module name decided up front:** `YahirReusableBot` (dist) / `yahir_reusable_bot` (import root), distinct from `weatherbot` (never shadow the import namespace). Ships NO console script — `weatherbot` console entry point stays app-side.
- **Layered core → adapters → app, one-way deps:** Core imports neither app nor adapter; every app behavior arrives via a PEP 544 Protocol or bare callable defined in the module's `seams.py`. The panel lives in the Discord *adapter* (SMS/Slack have no buttons).
- **JobStore: seam designed now, durable impl deferred (JOBSTORE-V2-01):** ship the Protocol + in-memory impl only; shape `register()` serialization-clean (importable callable + picklable identity-style args, live collaborators looked up at fire time) so the durable backend is a drop-in, not a redesign. No speculative backend built (YAGNI / rule-of-three).
- **Resolve the `render_embed`↔`PanelView` cycle by ownership, not a deferred import:** move `render_embed` app-side and inject it into `PanelKit` as `render`. Don't port the in-function import across the boundary.
- **Pin `discord.py==2.7.1` in the module; freeze `custom_id`s as a wire contract:** loose ranges let the host resolve an unverified version; re-namespacing custom_ids kills the live pinned panel. If they must change, ship a `!panel` re-summon migration + re-run the live UAT.
- **Lifecycle/config stay app-policy-free:** lifecycle gates READY on an app-provided health-check (no OpenWeather in the module), identity (PID path/runtime dir/unit/console name) parameterized, `.service` is a template; "which config keys are restart-only" stays app-side.
- [Phase ?]: Phase-21 golden harness FROZEN instant = 2026-06-20 13:00 UTC (epoch 1781960400); A3 confirmed time_machine freezes discord.utils.utcnow (no monkeypatch fallback needed); Wave-0 smokes A1/A3/A7 all discharged.
- [Phase ?]: interactive embed/custom_id goldens driven gateway-free through the REAL render path (lookup_weather + dispatch_reply + render_embed); status golden uses daemon_state=None reply doubling as the 📍-off cell
- [Phase ?]: Phase 21-04: pinned all 9 move-path exception identities (D-13 two-assert); pydantic.ValidationError uses verified pydantic_core._pydantic_core home; UnknownLocationError is the Phase-26 re-home tripwire; isinstance avoided as pin
- [Phase 21-05]: One-time move-path branch audit (D-08, no fail_under gate): classify each uncovered branch as FILLABLE (pin its untaken side with a characterization test) vs EXCUSED (runtime-lifecycle/defensive-payload/production-only, NAME why per D-09). 89%→93%, 80→48 partials; 39 fills in tests/test_golden_coverage_fill.py; 4 reason-bearing source pragmas (comment-only diff). Excused categories documented in 21-COVERAGE-AUDIT.md §3, not sprayed inline.
- [Phase 21-05]: retry.py `if dt is None` guard is UNREACHABLE on CPython 3.12 (parsedate_to_datetime always RAISES on malformed input, never returns None) — excused with a cross-version reason-bearing pragma, not a fill. The lazy-build_client blocks (lookup/selfcheck/uvmonitor) are production-only (tests inject a client) — same pragma treatment.
- [Phase ?]: 22-02: app-side briefing-capable Channel subclasses the one true module Channel (Pattern 2 shape a)
- [Phase ?]: 22-02: kept weatherbot/channels/base.py as a re-export shim (not deleted) so the five direct base.py importers stay byte-identical
- [Phase ?]: 22-03: app-side weatherbot.reliability.retry shim re-exports the FULL surface (constants + two_burst_wait + frozensets) so config.models, test_reliability, and the Phase-21 is_transient pin resolve to IDENTICAL objects
- [Phase ?]: 22-03: AlertSink port param renamed location_name -> target (litmus 'location' substring would trip location_id); runtime_checkable, store satisfies structurally; fire_slot byte-identical (D-07)
- [Phase ?]: SchedulerEngine is a thin non-owning registrar baking 3 invariant add_job kwargs once (D-03/D-15)
- [Phase ?]: OccurrenceStore + JobStore ship as define-only runtime_checkable Protocols (D-06a)
- [Phase ?]: 23-02: invariant kwargs centralized in engine.register; removed from all 4 daemon call sites (D-03)
- [Phase 23]: 23-02: read-only scheduler.get_jobs() reads outside _reconcile_jobs left byte-identical — rebind scoped to registration + reconcile read-throughs (D-16)
- [Phase ?]: Plan 24-01: honored D-01 (set[str]+injected register_jobs) and D-02 (unbound TypeVar, no module BaseConfig) verbatim; heartbeat/uvmonitor exclusion is an injected excluded_ids frozenset so the module names no app job id
- [Phase ?]: Plan 24-02: run_daemon drives the reusable ReloadEngine with all WeatherBot specifics injected (validate/desired_jobs/register_jobs/restore/excluded_ids/on_applied/on_rejected); SIGHUP->request_reload, main loop->service_pending, finally->stop, check-config->check — SEAM-04 proven byte-identical
- [Phase ?]: Plan 24-02: weatherbot/config/holder.py is a re-export shim (22-02 pattern); _do_reload kept as the byte-identical tested standalone though run_daemon now drives the engine
- [Phase ?]: Plan 24-03: SEAM-04 Gate-1 self-UAT PASS — all five reload paths (SIGHUP/file-watch/check-config/keep-old/reconcile-rollback) driven against the wired module ReloadEngine; reconcile-diff + keep-old + exactly-once-across-reload + schedule + sent_log goldens byte-identical to baseline 3567e48 (zero new diff, no golden updated). Live yahir-mint restart = deferred Gate-2 (Phase 28).
- [Phase ?]: Phase 26-01: generic CommandSpec shrinks to 5 fields (name/group/summary/opaque bind/neutral needs_flags); takes_location+handler subsumed by bind (D-01/D-02)
- [Phase ?]: Phase 26-01: both dispatcher coupling sites de-weathered — arm ladder collapses to spec.bind(ctx); group=='Forecast' fetch branch becomes neutral needs_flags + injected parse_flags/cache_suffix hooks (D-01 follow-through)
- [Phase ?]: bind closures authored in registry._wire_handlers (import-time) not wiring.py build_runtime — CLI/panel/bot resolve specs from the import-time global registry
- [Phase ?]: bind resolves handler live via BY_NAME[name].handler so replace(spec, handler=stub) test patches are honored with zero consumer-test edits
- [Phase ?]: 27-01: PanelKit render/contributors/marker are required no-default injected params; clone path re-invokes contributors (no isinstance on app types)
- [Phase ?]: 27-01: SelectedContext[I] is a lock-free single-writer holder cloned from ConfigHolder; discord.py pinned ==2.7.1 (adapter-owned)
- [Phase ?]: 27-02: render_embed signature kept unchanged; the render(reply,ctx) mismatch is bridged by the app _render_bridge closure at the composition root — cycle resolved by ownership (SC#2)
- [Phase ?]: 27-02: the forecast-grid variant is carried through the module's single on_command via an app-encoded '<name>|<variant>' dispatch key the app _dispatch closure decodes
- [Phase 28]: 28-01: YahirReusableBot repo created (fresh git init, clean import commit tagged v0.1.0 @ 138a907); file:// git-URL fallback used — real remote is a deploy prerequisite for Gate-2
- [Phase 28]: 28-01: direct_url.json contract CONFIRMED — uv git install writes vcs_info.commit_id + requested_revision (no dir_info on git install); 28-03 provenance reader builds on confirmed field names
- [Phase 28]: 28-02: WeatherBot re-pointed at yahir-reusable-bot via [tool.uv.sources] git TAG pin (tag=v0.1.0, file:// fallback); uv.lock froze sha 138a907d; wheel collapsed to ["weatherbot"], discord.py==2.7.1 now transitive. Gate-1 PASS (clean-venv frozen sync + weatherbot check/--help + 773-test byte-identical suite + uv build --no-sources + wheel-only-weatherbot). Real remote still the Gate-2 host blocker.
- [Phase 28]: 28-02: source-introspection tests repointed at the INSTALLED module (yahir_reusable_bot.__file__) — a missing in-tree path silently vacuous-passes anti-bake guards (Rule-3 fix beyond the plan's named test_import_hygiene.py: also test_injection_registry.py + test_panelkit_marker.py)
- [Phase ?]: [Phase 28]: 28-03: _module_provenance() reads the installed module's PEP 610 direct_url.json (vcs_info.commit_id + requested_revision) via stdlib importlib.metadata; emits a once-per-boot 'module provenance' structlog line (keys: module_version/module_sha/module_ref/editable) at the daemon run path. Live read = sha 138a907d / ref v0.1.0 / editable False; dir_info.editable is the dev-tree-vs-deploy tripwire; guarded total so a provenance read never crashes startup (T-28-10).
- [Phase ?]: Phase 28 process artifacts (D-06 repin ritual + promotion ledger) live WeatherBot-side under deploy/; D-08 Gate-1 self-UAT passes autonomously (5/5 criteria), live yahir-mint restart deferred to Gate-2.

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

- **[Phase 28] Live module-split restart UAT on host `yahir-mint`:** after the split + repin, deploy → `sudo systemctl restart weatherbot` → confirm the bot runs against the pinned module sha (startup-version-log line) and every button/dropdown on the already-pinned panel still routes (custom_id contract + persistent-view re-bind), correct default location. The clean-venv `uv sync --frozen` install + `weatherbot check`/`--help` + full suite is the gate that turns "works locally" into "works on host."

### Blockers/Concerns

[Issues that affect future work]

- **Carry-forward `[bot]` read-once-at-startup tech debt:** `[bot] operator_id` / `[reload] watch` / `panel_channel_id` are read once at startup (restart boundary). Keep this restart-boundary *policy* app-side during the config-reload extraction (Phase 24) — the generic holder must not enshrine a specific key list.
- **DATA-03 delivered-only persistence semantics** (open since v1.0): confirm when v2 analysis (ANLY-V2-01) reads the store — deferred beyond v2.0, not in extraction scope.
- ~~Deferred Gate-2 (v2.0 milestone-close): live yahir-mint restart + panel tap-through~~ **RESOLVED 2026-07-07** — live restart against the pinned module + panel/reload/briefing/CLI all verified; an `on_message` recursion bug found during this UAT was fixed and shipped as module **v0.1.1** (`7f3cc00`), which the deploy is now repinned to; a fetchable public remote replaced the `file://` URL.

## Deferred Items

Items acknowledged and carried forward:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Data semantics | DATA-03 delivered-only persistence — confirm when v2 analysis (ANLY-V2-01) reads the store. | Open (post-v2.0) | v1.0 close |
| Extension point | Durable/dynamic `JobStore` impl (JOBSTORE-V2-01) — seam designed in v2.0, impl deferred to a reminder-style consumer. | Deferred (designed in Phase 23) | v2.0 scope |
| Extension point | 2nd `Channel` adapter (Telegram/SMS/Slack — CHAN-V2-01/02/03) — abstraction shipped, impls deferred to their own milestones. | Deferred | v2.0 scope |
| Milestone-close audit | 6 self-UAT log artifacts (Gate-1 SELF-UAT for 23/24/25/27/28 + the passed 28-UAT) flagged by the open-artifact audit — all **0 pending scenarios**; non-blocking frontmatter-schema quirk, every phase VERIFICATION is `passed`. | Acknowledged (non-blocking) | v2.0 close |
| Test coverage | `ReloadEngine` reject/rollback path is unit-covered but not exercised by a boot/restart UAT (flagged in v2.0 audit). Optional targeted config-reject gate. | Deferred (optional) | v2.0 close |

_All v1.0–v1.3 host UATs were resolved at v1.3 Gate-2 close (2026-06-27); see milestones/*-MILESTONE-AUDIT.md._
| Phase 21 P01 | 18min | 2 tasks | 5 files |
| Phase 21 P02 | 20min | 3 tasks | 15 files |
| Phase 21 P03 | 22min | 3 tasks | 4 files |
| Phase 21 P04 | 10min | 1 tasks | 1 files |
| Phase 22 P01 | 9min | 3 tasks | 7 files |
| Phase 22 P02 | 4min | 3 tasks | 4 files |
| Phase 22 P03 | 8min | 3 tasks | 7 files |
| Phase 23 P01 | 6 | 3 tasks | 7 files |
| Phase 23 P02 | 3 | 3 tasks | 2 files |
| Phase 24 P01 | 10min | 3 tasks | 6 files |
| Phase 24 P02 | 9min | 3 tasks | 3 files |
| Phase 24 P03 | 5min | 2 tasks | 1 files |
| Phase 25 P01 | 10 | 2 tasks | 6 files |
| Phase 25 P02 | 30min | 3 tasks | 9 files |
| Phase 25 P03 | 6min | 2 tasks | 3 files |
| Phase 26 P01 | 7min | 3 tasks | 6 files |
| Phase 26 P02 | 8 | 3 tasks | 6 files |
| Phase 27 P01 | 9min | 3 tasks | 6 files |
| Phase 27 P02 | 13min | 3 tasks | 5 files |
| Phase 27 P04 | 38min | 1 tasks | 4 files |
| Phase 27 P03 | 14min | 3 tasks | 4 files |
| Phase 28 P01 | 20min | 3 tasks | 37 files |
| Phase 28 P02 | 7min | 3 tasks | 5 files |
| Phase 28 P03 | ~8min | 2 tasks | 2 files |
| Phase 28 P04 | 9min | 3 tasks | 3 files |

## Session Continuity

Last session: 2026-06-29T17:47:29.778Z
Stopped at: Completed 28-04-PLAN.md (Phase 28 ready_for_verification)
Resume file: None

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
