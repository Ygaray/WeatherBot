# Phase 10: File-Watch Auto-Reload - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

A thin **convenience layer** over the trusted Phase 9 reload engine: the running
daemon watches `config.toml` **and** the template files it references for saves, and
funnels detected edits — **debounced** to absorb editor save-storms and partial writes
— into the SAME validate → atomic-swap → job-reconcile path that SIGHUP / `weatherbot
reload` already drive. No new reload semantics are introduced; file-watch only *triggers*
the existing engine.

**Closes:** CFG-03 (daemon auto-detects config/template saves and reloads automatically,
debounced).

**Builds on Phase 9:** `run_daemon`'s main poll loop already services a
`reload_requested` `threading.Event` → runs `_do_reload` on the main thread (validate,
keep-old-on-failure, two-phase build-then-commit, job diff-reconcile). Phase 10 sets that
same flag from a file-watch observer thread. Because the reload path is unchanged,
**roadmap SC#4 (a failed auto-reload keeps the old config and the daemon keeps running) is
inherited for free** — a bad on-save edit goes through Phase 9's reject-and-keep-old path.

**Out of scope (own phases / permanently out):**
- Discord posting of reload outcome — Phase 11 (CFG-07). This phase logs only (inherits
  CFG-06's per-reload log line via Phase 9).
- `.env` / secrets hot-reload — **permanent restart boundary** (Phase 9 D-04, Pitfall #12).
  The watch set is config + templates only; never `.env`.
- systemd `ExecReload` / `systemctl reload` / sd_notify reload handshake — explicitly
  declined in Phase 9 (D-04). Reload stays always-ready and never touches the READY gate.
- Any change to the reload engine's validate/swap/reconcile logic itself (Phase 9 owns it).
</domain>

<decisions>
## Implementation Decisions

### Watcher library (resolves the ROADMAP-vs-PITFALLS conflict)
- **D-01: Use `watchfiles`** as the file-watch library — honoring the ROADMAP Phase 10
  wording ("watchfiles directory-watch with debounce") **over** PITFALLS.md's `watchdog`
  recommendation. Rationale: `watchfiles` has **built-in debounce** (`debounce`/`step`
  params) so we don't hand-roll save-storm coalescing; a Rust `notify` backend; a tiny
  `watch()` / `awatch()` API; and native directory-watch + inode-swap handling (Pitfall #5/#11
  needs). New runtime dependency — add to `pyproject.toml` (current deps: apscheduler, httpx,
  pydantic, pydantic-settings, structlog, tenacity, discord-webhook). `watchdog` was
  considered and **rejected**: more boilerplate (Observer + FileSystemEventHandler) and we'd
  hand-roll the debounce ourselves, and it contradicts the roadmap's explicit pick.
  **Note:** `watchfiles` is not currently in CLAUDE.md's stack table — planner/researcher
  should confirm the current pinned version (check PyPI; CLAUDE.md was last version-checked
  2026-06-09 and does not list it).

### Funnel mechanism (how a save triggers reload)
- **D-02: The watcher sets the existing `reload_requested` Event** via a small
  `request_reload()` seam, reusing Phase 9's exact main-loop `_do_reload` path. The
  observer runs in its own thread; after the debounce settles it calls a closure that
  `.set()`s the `reload_requested` `threading.Event` that `run_daemon` already polls
  (`daemon.py` ~line 961, `while not stop.wait(timeout=1.0): if reload_requested.is_set(): …`).
  The actual reload still runs on the **main thread**, not the watcher thread — identical to
  the SIGHUP path. Chosen over **self-SIGHUP (`os.kill(os.getpid(), signal.SIGHUP)`)**:
  setting the in-process Event is simpler, has no signal round-trip, and is trivially
  unit-testable without installing signal handlers. (Self-SIGHUP's only edge was "provably
  identical to the explicit trigger" — but both funnel to the same `_do_reload`, so the
  in-process Event already gives that guarantee.)
- **Inherited correctness (no new work):** since reload goes through `_do_reload`,
  keep-old-on-failure (SC#4) and exactly-once-across-reload (Phase 9 D-01/D-02) hold
  unchanged. An identical-content save produces zero job changes (Phase 9 idempotent
  reconcile), so even an over-eager trigger is harmless.

### Enable / default + toggle surface
- **D-03: File-watch is ON by default**, disabled via a **config.toml toggle**
  (e.g. a `[reload] watch = true` field, default `true`). This matches CFG-03's
  "daemon auto-detects" intent. **Config toggle only — no CLI `--no-watch` flag** (single
  source of truth, consistent with CLAUDE.md's "all settings editable without code changes"
  and the existing config-driven design). The explicit trigger (SIGHUP / `weatherbot reload`)
  **always works regardless** of this toggle, so the daemon is fully functional with watch
  off (Pitfall #11 "keep file-watch optional"). The toggle is a non-secret `Config` field
  (lives in the validated config the `ConfigHolder` owns) — planner to confirm exact field
  name/placement.

### Watch scope + debounce timing
- **D-04: Re-derive the watch set on each successful reload.** Watch the **directories**
  containing `config.toml` + the currently-referenced template files (directory-watch, not
  file-watch, so atomic-rename inode swaps don't go deaf — Pitfall #11). After a successful
  reload that changes WHICH templates the config references, **update the watched directory
  set** so an edit pointing config at a template in a new directory stays auto-watched.
  Chosen over a static-at-startup watch set (simpler, but would miss a reload that introduces
  a new template dir — explicit trigger would still catch it).
- **D-05: ~400ms fixed debounce quiet-window**, as a **module constant (not configurable)**.
  Long enough to coalesce truncate-then-write / temp-then-rename / multi-event editor saves
  into **exactly one** reload (SC#2), short enough to feel instant. Rejected: exposing it in
  config (knob almost nobody changes — unnecessary surface) and `watchfiles`' default ~50ms
  `step` (too tight — risks firing mid-write on slower temp-then-rename sequences, weakening
  SC#2). Planner maps ~400ms onto `watchfiles`' `debounce`/`step` parameters (or `awatch`
  equivalents).

### Observer lifecycle (inherited constraint, locked by Pitfall #11 + SC#3)
- A **single long-lived observer**, started in `run_daemon` and **stopped in the existing
  `finally` clean-shutdown path** alongside `scheduler.shutdown(wait=False)` — never a
  per-event observer. The watch must shut down cleanly on SIGTERM and keep the
  file-descriptor / inotify-watch count stable over a long-uptime soak (SC#3, Pitfall #11a).
- **Never write anything back near the watched files** during reload (no `.bak`, no
  auto-format into the watched dir) — prevents the reload-loop failure (Pitfall #11b).
  Already true: reload is config-only and writes nothing to the config/template dirs.

### Claude's Discretion
Left to research/planning:
- Exact `watchfiles` API surface: blocking `watch()` in a dedicated thread vs `awatch()` —
  the daemon is currently sync/threaded (`BackgroundScheduler`, `threading.Event`), so a
  plain thread running `watch()` and calling `request_reload()` likely fits best; planner
  confirms.
- Exact mapping of the ~400ms quiet-window onto `watchfiles`' `debounce` (max wait) and
  `step` (poll/quiet) parameters.
- Where the `request_reload()` seam lives and how the observer thread receives the
  `reload_requested` Event reference (it's created inside `run_daemon`).
- Exact `Config` field name/section for the `watch` toggle and how it threads into the
  observer-start decision.
- How the watcher distinguishes/derives the template directories from the live config
  (re-derive on reload, D-04) — likely from the same template paths Phase 9's reload reads.
- The fd-stability soak verification approach for SC#3 (e.g. simulated inode-swapping saves
  + `/proc/<pid>/fd` count assertion) within the test suite's constraints.
- Behavior when a watched directory is itself deleted/recreated (graceful re-watch vs log).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & requirements
- `.planning/ROADMAP.md` — Phase 10 entry (goal, depends-on Phase 9, the 4 success criteria);
  specifies `watchfiles` directory-watch with debounce funneling into the Phase 9 reload
  engine. **Note:** the Phase 10 line is currently checkbox-marked `[x] completed 2026-06-16`,
  but no phase artifacts exist — treat the phase as NOT-yet-built; the checkbox is to be
  reconciled (see "Specific Ideas").
- `.planning/REQUIREMENTS.md` — **CFG-03** (the one requirement this phase closes); CFG-07
  (Phase 11) and `.env` reload (out, restart boundary) are explicitly NOT in this phase.

### Pitfalls research (this phase is a primary target)
- `.planning/research/PITFALLS.md` — **MANDATORY.** **Pitfall #5** (editor save timing:
  truncate-then-write / temp-then-rename / multi-event → debounce + validate-then-swap;
  ~line 96) and **Pitfall #11** (file-watch fd leaks / infinite reload loops / watching the
  wrong inode → single long-lived directory-observer, clean teardown, never write back near
  watched files; ~line 216). Also the "Looks Done But Isn't" hot-reload checklist (~line 339)
  and the file-watch ↔ editor-save Integration Gotchas row (~line 302). Note: PITFALLS.md
  recommends `watchdog`; **D-01 overrides this in favor of the roadmap's `watchfiles`.**

### Prior-phase context this phase builds directly on
- `.planning/phases/09-reload-engine-explicit-trigger/09-CONTEXT.md` — the reload engine this
  phase funnels into: D-04 (no `ExecReload`, always-ready), the `reload_requested` Event +
  main-loop poll seam, keep-old-on-failure, two-phase build-then-commit, and the explicit
  deferral of "File-watch auto-reload + debounce — Phase 10 (CFG-03); reuse this phase's
  reload engine as the funnel (Pitfalls #5, #11)."

### Code this phase extends
- `weatherbot/scheduler/daemon.py` — **the integration site.**
  - `run_daemon` (~line 817): owns `stop` Event, `ConfigHolder`, `scheduler`, `config_path`,
    and the `try/finally` clean-shutdown block — the observer is started here and stopped in
    `finally` alongside `scheduler.shutdown`.
  - `_install_reload_signal` (~line 793) and the main poll loop (~line 954–985): the
    `reload_requested` Event + `if reload_requested.is_set(): … _do_reload(...)` servicing the
    flag on the main thread — D-02's `request_reload()` sets this same Event.
  - `_do_reload` (~line 531): the unchanged target path (validate → `holder.replace` →
    reconcile → rollback); note it requires `config_path` (the loop warns + skips if
    `config_path is None`, ~line 966) — file-watch only runs when a config PATH exists.
- `weatherbot/config/models.py` / `weatherbot/config/loader.py` — where the `[reload] watch`
  toggle (D-03) is added as a validated `Config` field, and where the template paths the
  watch set is derived from (D-04) are defined.
- `templates/renderer.py` — `validate_template` (the offline token allow-list Phase 9's
  reload validation uses); confirms which template files config references (watch-set source).
- `pyproject.toml` — add the `watchfiles` dependency (D-01).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`reload_requested` `threading.Event` + main-loop poll** (`daemon.py` ~954–985, Phase 9) —
  the ready-made trigger seam. File-watch sets it; the main loop already runs `_do_reload`
  on the main thread. Zero new reload plumbing needed.
- **`_do_reload`** (`daemon.py` ~531) — the complete validate/swap/reconcile/keep-old engine,
  reused verbatim. File-watch adds NO reload logic.
- **Existing SIGTERM clean-shutdown `finally`** (`run_daemon`) — the observer's teardown hook;
  reuse v1's shutdown path so SIGTERM stops the scheduler AND the observer cleanly (SC#3).
- **`watchfiles` built-in debounce** (`watch()`/`awatch()` `debounce`/`step`) — implements
  D-05's quiet-window without a hand-rolled timer.

### Established Patterns
- **Flag-set-then-service-on-main-thread** — the SIGHUP handler sets a flag; the main loop
  does the work (never re-entrant). D-02 mirrors this exactly: the observer thread only sets
  the Event; `_do_reload` runs on the main thread.
- **Config is a validated, frozen `Config` owned by `ConfigHolder`** (Phase 8) — the new
  `watch` toggle is just another validated field; readers see a consistent snapshot.
- **`config_path`-gated reload** — `run_daemon` already skips reload when `config_path is
  None` (~966); file-watch is likewise only meaningful when a real config PATH is being run.

### Integration Points
- file save → `watchfiles` observer (own thread) → debounce settles → `request_reload()` sets
  `reload_requested` → main loop runs `_do_reload` (validate → swap → reconcile, keep-old).
- observer lifecycle ↔ `run_daemon`'s `try/finally`: start after scheduler/holder set up,
  stop in `finally` with `scheduler.shutdown` (single observer, clean teardown).
- watch set ↔ live config's template paths: derived at startup and **re-derived after each
  successful reload** (D-04).
</code_context>

<specifics>
## Specific Ideas

- **ROADMAP checkbox reconciliation:** `.planning/ROADMAP.md` line ~37 marks Phase 10 as
  `[x] ... (completed 2026-06-16)`, but there is no phase directory, no plans, no
  implementation, and CFG-03 is still `[ ]` Pending in REQUIREMENTS.md. The checkbox is
  premature — the phase is being discussed/planned now. Reconcile the roadmap (and the
  REQUIREMENTS coverage table line `| CFG-03 | Phase 10 | Pending |`) when the phase actually
  verifies.
- **The single most important test (SC#2, Pitfall #5):** simulate a realistic editor save —
  truncate-then-write AND temp-then-rename AND a multi-event burst — and assert it produces
  **exactly ONE** reload and **never parses a half-written file** (the debounce + directory-watch
  guarantee).
- **The fd-stability check (SC#3, Pitfall #11):** prove the single observer's
  file-descriptor / inotify-watch count stays stable across many inode-swapping saves, and
  that SIGTERM tears the observer down cleanly (no leak over long uptime).
- **The keep-old check (SC#4):** an on-save edit that is *invalid* must follow Phase 9's
  reject-and-keep-old path — the live daemon keeps running on the previous config (this is
  inherited, but assert it end-to-end through the file-watch trigger, not just SIGHUP).
- Verify a save with **identical content** to the live config produces zero job changes
  (Phase 9 idempotent reconcile) — over-eager triggers are harmless.
</specifics>

<deferred>
## Deferred Ideas

- **Discord posting of reload outcome** (success summary / rejection reason) — Phase 11
  (CFG-07). This phase logs only.
- **`.env` / secrets hot-reload** — permanently out of scope; secrets are a restart boundary
  (Pitfall #12).
- **systemd `ExecReload` / `systemctl reload`** — declined in Phase 9 (D-04); revisit only if
  a future requirement makes `systemctl reload` a needed surface.
- **A configurable debounce window** — considered (D-05) and deferred as unnecessary config
  surface; revisit only if a real operator need for tuning appears.

Discussion stayed within the Phase 10 boundary (file-watch trigger only; the reload engine
itself is Phase 9 and untouched).

</deferred>

---

*Phase: 10-File-Watch Auto-Reload*
*Context gathered: 2026-06-16*
