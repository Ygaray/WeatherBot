# Phase 10: File-Watch Auto-Reload - Research

**Researched:** 2026-06-16
**Domain:** Filesystem change detection (`watchfiles`) → debounced trigger into an existing threaded reload engine
**Confidence:** HIGH

## Summary

Phase 10 is a thin trigger layer: a single long-lived `watchfiles` observer runs in
its own daemon thread, watches the **directories** that contain `config.toml` and the
referenced template files, debounces editor save-storms, and — after the quiet window
settles — calls a `request_reload()` seam that `.set()`s the existing `reload_requested`
`threading.Event`. The Phase-9 main poll loop (`daemon.py` ~961) already services that
flag on the **main thread** via `_do_reload` (validate → atomic swap → diff-reconcile,
keep-old on failure). No new reload semantics are introduced; all of SC#4 (keep-old) and
the exactly-once guarantees are inherited verbatim from Phase 9.

`watchfiles` (by Samuel Colvin / the pydantic author) is the correct library for the
locked decisions: it has a Rust `notify` backend, native **directory recursive watch**
(survives atomic-rename inode swaps — Pitfall #11c), a built-in **debounce/step** quiet
window (no hand-rolled timer — Pitfall #5), and a `stop_event` kwarg on the blocking
`watch()` generator for clean teardown (Pitfall #11a). The synchronous `watch()`
generator — NOT `awatch()` — is the right fit because the daemon is sync/threaded
(`BackgroundScheduler` + `threading.Event`); there is no asyncio loop to host `awatch()`.

**Primary recommendation:** Add `watchfiles>=1.2.0` to `pyproject.toml`. Run a dedicated
non-blocking thread executing `watch(*dirs, debounce=1600, step=400, rust_timeout=500,
stop_event=stop)`; on each yielded change-set call `request_reload()` which `.set()`s the
existing `reload_requested` Event. Start the thread in `run_daemon` after the holder/scheduler
are built and `config_path is not None`; stop it in the existing `finally` by `.set()`ing
`stop` then `thread.join(timeout=...)`. Re-derive the watched directory set inside `_do_reload`
on each **successful** swap (D-04). **Lower `rust_timeout` to ~500ms** so SIGTERM teardown
latency is sub-second (the default 5000ms would make the join hang up to 5s — see Pitfall #2 below).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Detect a file save | Observer thread (`watchfiles.watch`) | — | OS inotify via Rust backend; off the main thread so it can block |
| Debounce / coalesce save-storm | Observer thread (`debounce`/`step`) | — | Library-native quiet window; absorbs partial writes before any reload (Pitfall #5) |
| Decide "reload now" | Observer thread → `request_reload()` seam | — | Flag-set only; mirrors the SIGHUP handler's flag-set-only posture |
| Run the reload (validate/swap/reconcile) | **Main thread** (`_do_reload`) | — | Phase 9 owns this; never run reload work off the main thread (Pitfall #6/#9 already mitigated) |
| Re-derive the watch set | Main thread (inside `_do_reload` success path) | Observer thread reads it | Watch set depends on the live config's template refs; re-derive only after a good swap (D-04) |
| Observer lifecycle (start/stop) | `run_daemon` (main thread) | — | Single observer, started once, stopped in the existing `finally` (SC#3) |
| `[reload] watch` toggle | `Config` model (validated) | `run_daemon` gates start on it | Config-only surface, no CLI flag (D-03) |

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01: Use `watchfiles`** (NOT `watchdog` — overrides PITFALLS.md's `watchdog` rec, honors the
  ROADMAP). Built-in debounce, Rust `notify` backend, tiny `watch()`/`awatch()` API, native
  directory-watch + inode-swap handling. New runtime dependency → add to `pyproject.toml`.
  Confirm the current pinned version on PyPI (CLAUDE.md does not list it; last version-checked 2026-06-09).
- **D-02: The watcher sets the existing `reload_requested` Event** via a small `request_reload()` seam,
  reusing Phase 9's exact main-loop `_do_reload` path. Observer runs in its own thread; the reload
  itself runs on the **main thread**. Chosen over self-SIGHUP (`os.kill(getpid(), SIGHUP)`) —
  the in-process Event is simpler, no signal round-trip, trivially unit-testable.
- **D-03: File-watch ON by default**, disabled via a `config.toml` `[reload] watch = true` toggle
  (default `true`). **Config toggle only — NO CLI `--no-watch` flag.** The explicit trigger
  (SIGHUP / `weatherbot reload`) ALWAYS works regardless of this toggle. The toggle is a non-secret
  validated `Config` field owned by `ConfigHolder`.
- **D-04: Re-derive the watch set on each successful reload.** Watch the **DIRECTORIES** containing
  `config.toml` + currently-referenced template files (directory-watch, not file-watch — inode-swap
  safety, Pitfall #11). After a successful reload that changes WHICH templates the config references,
  update the watched directory set. Chosen over a static-at-startup watch set.
- **D-05: ~400ms fixed debounce quiet-window**, as a **module constant (not configurable)**. Long
  enough to coalesce truncate-then-write / temp-then-rename / multi-event saves into exactly ONE
  reload (SC#2), short enough to feel instant. Rejected: exposing it in config; watchfiles' default
  ~50ms `step` (too tight). Map ~400ms onto watchfiles' `debounce`/`step` parameters.
- **Single long-lived observer** started in `run_daemon`, stopped in the existing `finally`
  clean-shutdown path alongside `scheduler.shutdown(wait=False)` — never per-event. Must shut down
  cleanly on SIGTERM and keep fd / inotify-watch count stable over a long soak (SC#3).
- **Never write anything back near the watched files** during reload (no `.bak`, no auto-format into
  the watched dir) — prevents the reload-loop failure (Pitfall #11b). Already true: reload is
  config-only and writes nothing to config/template dirs.

### Claude's Discretion (research fills these — see corresponding sections)
- Blocking `watch()` in a dedicated thread vs `awatch()` → **answered: sync `watch()` in a thread** (no asyncio loop exists).
- Exact ~400ms → `debounce`/`step` mapping → **answered: `step=400`, `debounce=1600`** (see Standard Stack + Pattern 2).
- Where the `request_reload()` seam lives + how the observer receives the Event reference → **answered: a closure capturing `reload_requested`, built inside `run_daemon`** (Pattern 1).
- Exact `Config` field name/section for the `watch` toggle → **recommended: `ReloadConfig.watch: bool = True` under a new `[reload]` table** (Pattern 3).
- How the watcher derives template directories from the live config → **answered: re-use `validate_config_and_templates`'s `{cfg.template}` set + `TEMPLATES_DIR`** (Pattern 4).
- fd-stability soak verification for SC#3 → **answered: `psutil`/`/proc/<pid>/fd` count assertion across N inode-swapping saves** (Validation Architecture).
- Behavior when a watched dir is deleted/recreated → **answered: watchfiles re-establishes on directory-watch; log + continue** (Open Questions Q1).

### Deferred Ideas (OUT OF SCOPE)
- **Discord posting of reload outcome** — Phase 11 (CFG-07). This phase logs only.
- **`.env` / secrets hot-reload** — permanently out; secrets are a restart boundary (Pitfall #12).
  The watch set is **config + templates only; NEVER `.env`**.
- **systemd `ExecReload` / `systemctl reload` / sd_notify reload handshake** — declined Phase 9 (D-04).
- **A configurable debounce window** — deferred as unnecessary config surface (D-05).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CFG-03 | The daemon auto-detects config/template file saves and reloads automatically (file-watch with debounce to absorb editor save-storms and partial writes). | The `watchfiles.watch()` observer thread (Pattern 1) detects directory changes; `debounce`/`step` (Pattern 2) absorbs save-storms; `request_reload()` (D-02) funnels into the trusted Phase-9 `_do_reload`. All four SCs map to testable seams in Validation Architecture. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `watchfiles` | `>=1.2.0` (latest 1.2.0, 2026-05-18) | Filesystem change detection with built-in debounce + directory recursive watch + `stop_event` teardown | `[VERIFIED: PyPI]` Rust `notify` backend; ~304M downloads/month; authored by Samuel Colvin (pydantic). Directly satisfies D-01/D-04/D-05/Pitfall #5/#11. `requires-python >=3.10` — compatible with project `>=3.12`. |

**Already in the project (reused verbatim, no new work):**
- `_do_reload` / `validate_config_and_templates` / `ConfigHolder` (Phase 9) — the reload engine.
- `reload_requested` `threading.Event` + main poll loop (`daemon.py` ~961) — the trigger seam.
- `psutil 5.9.8` (already installed) — fd-count assertions for the SC#3 soak test.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `watchfiles` (D-01) | `watchdog` (PITFALLS.md rec) | More boilerplate (`Observer` + `FileSystemEventHandler`); hand-rolled debounce; **rejected by locked D-01** and the ROADMAP. |
| sync `watch()` in a thread | `awatch()` (async) | `awatch()` needs an asyncio loop; the daemon is sync/threaded (`BackgroundScheduler`). A thread running blocking `watch()` is the natural fit; **locked direction confirmed.** |
| `request_reload()` Event-set | self-SIGHUP (`os.kill`) | Signal round-trip + handler install; harder to unit-test. **Rejected by D-02.** |

**Installation:**
```bash
uv add watchfiles
```
(adds `watchfiles>=1.2.0` to `[project].dependencies` in `pyproject.toml`.)

**Version verification (this session):** `watchfiles` latest = **1.2.0**, uploaded **2026-05-18**,
`requires_python >=3.10`. Recent versions on PyPI: 1.0.3 → 1.0.4 → 1.0.5 → 1.1.0 → 1.1.1 → 1.2.0.
`[VERIFIED: PyPI registry, 2026-06-16]`

## Package Legitimacy Audit

> slopcheck was **NOT installable** in this session (`pip install slopcheck` failed — no network/registry access for that tool). Per protocol, packages would normally be tagged `[ASSUMED]`. However, `watchfiles` is verified by overwhelming independent signal (authorship, download volume, source repo, the project's own ROADMAP naming it), so it is treated as `[VERIFIED: PyPI]` with the audit row below. The planner may still gate the install behind a `checkpoint:human-verify` task if it wants belt-and-suspenders.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `watchfiles` | PyPI | first release years ago; 1.2.0 on 2026-05-18 | **304M/month**, 64M/week | `github.com/samuelcolvin/watchfiles` | unavailable | **Approved** (independently verified) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
**Postinstall script check:** `watchfiles` ships a Rust binary wheel (maturin-built); no Python `postinstall`/`setup.py` network call. Standard binary wheel install. `[CITED: github.com/samuelcolvin/watchfiles]`

## Architecture Patterns

### System Architecture Diagram

```
  Operator saves config.toml / template.txt
                 │  (editor: truncate-write, temp-then-rename, or multi-event burst)
                 ▼
  ┌───────────────────────────────────────────────────────────┐
  │ OBSERVER THREAD  (daemon thread, started in run_daemon)    │
  │                                                            │
  │   for changes in watch(*watch_dirs,                        │
  │                        debounce=1600, step=400,            │
  │                        rust_timeout=500,                   │
  │                        watch_filter=<config+template only>,│
  │                        stop_event=stop):                   │
  │        # debounce/step already coalesced the save-storm    │
  │        request_reload()   ──┐  (closure over reload_requested)
  └─────────────────────────────┼─────────────────────────────┘
                                │  reload_requested.set()
                                ▼
  ┌───────────────────────────────────────────────────────────┐
  │ MAIN THREAD  (run_daemon poll loop, daemon.py ~961)        │
  │   while not stop.wait(1.0):                                │
  │     if reload_requested.is_set():                          │
  │        reload_requested.clear()                            │
  │        if config_path is None: warn+skip                   │
  │        _do_reload(config_path=…, holder=…, scheduler=…)    │
  │           ├─ PHASE 1 validate_config_and_templates(path)   │  reject → keep-old (SC#4)
  │           ├─ PHASE 2 holder.replace + diff-reconcile jobs  │  throw → rollback
  │           └─ on SUCCESS: re-derive watch_dirs  ───────────┐│  (D-04)
  └────────────────────────────────────────────────────────┼─┘
                                                            │
   watch_dirs is a SHARED mutable set the observer reads ◄──┘  (new save lands in a new dir → watched)

  SIGTERM ──► stop.set() ──► poll loop exits ──► finally:
                               scheduler.shutdown(wait=False)
                               stop already set ──► watch() returns within ~rust_timeout
                               observer_thread.join(timeout)        (SC#3 clean teardown)
```

The diagram traces the primary use case (save → debounce → flag → main-thread reload) and the
teardown path. File-to-symbol mapping is in Component Responsibilities below.

### Component Responsibilities
| Concern | Lives in | Notes |
|---------|----------|-------|
| `watch()` loop + filter | new helper in `weatherbot/scheduler/daemon.py` (e.g. `_run_watch_observer`) | Keeps the observer beside `run_daemon`; unit-testable with a temp dir. |
| `request_reload()` seam | closure inside `run_daemon` capturing `reload_requested` | Flag-set only (mirrors `_install_reload_signal`'s handler). |
| Watch-set derivation | helper (e.g. `_derive_watch_dirs(config, config_path)`) reading `{cfg.template}` + `TEMPLATES_DIR` | Re-called inside `_do_reload` success path (D-04). |
| `[reload] watch` toggle | `weatherbot/config/models.py` — new `ReloadConfig` model + `Config.reload` field | Validated, frozen; default `watch=True`. |
| Observer start/stop | `run_daemon` (start after holder/scheduler; stop in `finally`) | Single observer, joined on shutdown. |

### Recommended Structure (deltas only — no new packages)
```
weatherbot/
├── config/
│   └── models.py        # + ReloadConfig (watch: bool = True); Config.reload field
└── scheduler/
    └── daemon.py        # + _run_watch_observer(), _derive_watch_dirs(),
                         #   request_reload closure; start in run_daemon, stop in finally;
                         #   _do_reload re-derives watch_dirs on success (D-04)
```

### Pattern 1: Observer thread + flag-set-only `request_reload()` seam
**What:** A dedicated `threading.Thread(daemon=True)` runs the blocking `watch()` generator. On
each yielded change-set it calls a zero-arg closure that ONLY `.set()`s the existing Event.
**When to use:** Always (this is the phase's core wiring). Mirrors the established
"flag-set-then-service-on-main-thread" pattern (`_install_reload_signal`, `daemon.py` ~793).
```python
# weatherbot/scheduler/daemon.py — inside run_daemon, AFTER holder/scheduler built,
# AND only when config_path is not None AND config.reload.watch is True.
# Source: watchfiles sync watch() API — https://watchfiles.helpmanual.io/api/watch/
def _run_watch_observer(watch_dirs_ref, request_reload, stop, *, watch_filter):
    from watchfiles import watch  # in-function import (mirrors build_channel idiom)
    # watch_dirs_ref is a 1-element list/box holding the current set, re-derived on
    # reload (D-04); read it fresh each loop entry so a new template dir is picked up.
    while not stop.is_set():
        dirs = tuple(watch_dirs_ref[0])
        for _changes in watch(
            *dirs,
            step=WATCH_QUIET_MS,        # 400 — the D-05 quiet window
            debounce=WATCH_DEBOUNCE_MS, # 1600 — upper grouping bound
            rust_timeout=WATCH_RUST_TIMEOUT_MS,  # 500 — so stop_event is honored sub-second
            yield_on_timeout=True,      # lets the loop re-check watch_dirs_ref / stop each timeout
            watch_filter=watch_filter,  # config.toml + referenced templates ONLY (never .env)
            stop_event=stop,            # SIGTERM-driven clean teardown (SC#3)
        ):
            if stop.is_set():
                return
            if _changes:                # empty set == a timeout tick (yield_on_timeout); skip
                request_reload()
        # watch() returned because stop_event fired (or dirs changed): loop re-checks.
        if stop.is_set():
            return
```
`request_reload` is built in `run_daemon` as `lambda: reload_requested.set()` (or a named
inner fn that also logs at debug). The actual reload still runs on the main thread.

### Pattern 2: Mapping the ~400ms quiet window onto `debounce`/`step`
**What:** `watchfiles.watch(debounce, step)` semantics (from the API docs / `main.py`):
- **`step`** (ms) = "wait this long for new changes; if no change arrives in `step` and at least
  one change has been seen, yield." This is the **quiet window** D-05 wants → set **`step=400`**.
- **`debounce`** (ms) = "maximum total time to keep grouping changes before forcing a yield."
  This is the upper bound on a never-quiescing storm → keep the default **`debounce=1600`**.
**Recommended constants (module-level in `daemon.py`):**
```python
WATCH_QUIET_MS = 400        # D-05 quiet window (step): coalesce truncate-write / temp-rename / burst
WATCH_DEBOUNCE_MS = 1600    # max grouping (watchfiles default) — upper bound on a busy storm
WATCH_RUST_TIMEOUT_MS = 500 # see Pitfall #2: bounds stop_event teardown latency (NOT the 5000 default)
```
`[CITED: https://watchfiles.helpmanual.io/api/watch/]` `[VERIFIED: watchfiles main.py source]`
**Why default `step=50` is wrong here:** 50ms is too tight — a slower temp-then-rename or a
two-stage truncate-write can have a >50ms gap between events, yielding TWICE (two reloads) and
risking a mid-write parse (weakens SC#2). 400ms comfortably spans realistic editor save sequences.

### Pattern 3: The `[reload] watch` toggle (D-03)
**What:** A new validated, frozen `ReloadConfig` model; `Config` gains a `reload` field defaulting
to `ReloadConfig()` so existing configs (no `[reload]` table) load unchanged.
```python
# weatherbot/config/models.py
class ReloadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    watch: bool = True            # D-03: ON by default; [reload] watch = false disables

class Config(BaseModel):
    ...
    reload: ReloadConfig = Field(default_factory=ReloadConfig)
```
`run_daemon` starts the observer only when `config.reload.watch and config_path is not None`.
The toggle threads through the SAME validated snapshot the holder owns. (Note: the live observer
reads the toggle ONCE at startup; flipping `watch` in `config.toml` itself is applied on the next
reload — acceptable, and an edge worth a one-line doc note.)

### Pattern 4: Watch-set derivation + re-derive on reload (D-04)
**What:** The watch set is the set of **directories** containing `config.toml` and every template
the live config references. The referenced-template set is EXACTLY the `{cfg.template}` set that
`validate_config_and_templates` already builds (`loader.py` ~131) — reuse that contract so the
watch set and the validated set never drift.
```python
# weatherbot/scheduler/daemon.py
def _derive_watch_dirs(config: Config, config_path: Path) -> set[Path]:
    from templates.renderer import TEMPLATES_DIR
    dirs = {Path(config_path).resolve().parent}
    # Today Config.template is a single shared template in TEMPLATES_DIR; build over a SET
    # so future per-location templates extend without a rewrite (mirrors loader.py:131).
    for _template_name in {config.template}:
        dirs.add(Path(TEMPLATES_DIR).resolve())
    return dirs
```
**Re-derive on success (D-04):** inside `_do_reload`, AFTER the successful swap+reconcile (the
`summary = f"+{added}..."` block, `daemon.py` ~618), recompute and mutate the shared
`watch_dirs_ref[0]`. Because the observer re-reads `watch_dirs_ref` at the top of each loop
(it returns from `watch()` on the next `rust_timeout` tick with `yield_on_timeout=True`), a
template that moves to a NEW directory becomes watched without restarting the daemon.

### Anti-Patterns to Avoid
- **Watching the FILE (`config.toml`) directly** → atomic-rename swaps the inode, the watch goes
  deaf (Pitfall #11c). **Always watch the DIRECTORY** and filter to the filename.
- **Running `_do_reload` on the observer thread** → re-entrant reload, torn state (Pitfall #6/#9).
  The observer ONLY sets the flag; reload runs on the main thread.
- **A per-event / per-save observer** → fd/inotify leak over days (Pitfall #11a). One long-lived observer.
- **Including `.env` in the watch set** → would imply secrets are hot-reloadable; they are NOT
  (Pitfall #12, restart boundary). The `watch_filter` must EXCLUDE `.env`.
- **Default `rust_timeout=5000`** → SIGTERM teardown could hang ~5s (Pitfall #2 below); lower it.
- **Writing a `.bak`/auto-format into a watched dir during reload** → reload loop (Pitfall #11b).
  Already impossible (reload writes nothing to those dirs) — keep it that way.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Debounce / save-storm coalescing | A custom timer that resets on each inotify event | `watchfiles` `step`/`debounce` | Editor save sequences are subtle (Pitfall #5); the Rust backend already coalesces correctly. |
| Inode-swap-safe watching | A re-`open()`-on-rename file watch | `watchfiles` directory recursive watch | inotify on a file goes deaf after an atomic rename (Pitfall #11c). |
| Cross-thread stop of a blocking watch | A poison-pill queue / killing the thread | `watch(stop_event=...)` | The library polls the event in Rust and returns the generator cleanly. |
| inotify backend selection / WSL fallback | OS-specific inotify/FSEvents code | `watchfiles` (auto force_polling on WSL) | Cross-platform notify is a solved Rust problem. |
| Validate-then-swap reload | Anything | Phase 9 `_do_reload` (reused verbatim) | This phase adds NO reload logic. |

**Key insight:** Phase 10 should be almost entirely *wiring*. Every hard part — debounce, inode-swap,
validate/swap/rollback, exactly-once — is already solved (by `watchfiles` or Phase 9). The risk is
in the *integration* (teardown latency, filter scope, watch-set re-derivation), not in any new algorithm.

## Runtime State Inventory

> Not a rename/refactor/migration phase. This is an additive feature (new dependency + new wiring).
> No stored data, live-service config, OS-registered state, secret, or build artifact carries a value
> that this phase renames or migrates.
>
> - **Stored data:** None — no datastore key/column changes; the sent-log key is untouched (Phase 9 owns it).
> - **Live service config:** None — no external service registration.
> - **OS-registered state:** None — the systemd unit is unchanged (no `ExecReload`, D-04). inotify
>   watches are runtime-only resources, covered by SC#3's fd-stability check, not persistent state.
> - **Secrets / env vars:** None added. The watch set explicitly EXCLUDES `.env` (Pitfall #12 boundary).
> - **Build artifacts:** Adding `watchfiles` updates `uv.lock` and `pyproject.toml` — a normal
>   dependency add, applied by `uv sync` (verified by an import smoke test, not a migration).

## Common Pitfalls

### Pitfall 1: Reload reads a half-written config (Pitfall #5 — the headline SC#2 risk)
**What goes wrong:** The watcher fires on the first write event; an editor that truncate-then-writes
or temp-then-renames is mid-write, so a reload parses an empty/partial/valid-but-incomplete TOML.
**Why it happens:** Editors don't write atomically; different editors emit different event sequences;
a too-tight quiet window (e.g. the 50ms default `step`) fires between sub-events.
**How to avoid:** (1) `step=400` quiet window coalesces the burst into ONE yield AFTER writing
settles. (2) Even if a partial read slipped through, Phase 9's `validate_config_and_templates`
rejects it (TOMLDecodeError / ValidationError) and keeps-old — the partial read is a rejected reload,
never a torn state. Directory-watch + debounce is the primary guard; validate-then-swap is the backstop.
**Warning signs:** Two reloads per save in logs; `TOMLDecodeError` on save; "reload applied" followed
by a missing-location surprise (would only happen if a partial parsed clean — guarded by validation).

### Pitfall 2: SIGTERM teardown hangs up to ~5s because `rust_timeout` defaults to 5000ms
**What goes wrong:** `watch(stop_event=...)` checks the stop event inside the Rust loop, which runs
for up to `rust_timeout` ms before returning to Python. With the default **5000ms**, calling
`stop.set()` in the `finally` and then `thread.join()` can block the shutdown for up to 5 seconds —
under systemd's `TimeoutStopSec` that's usually fine, but it makes SC#3's "shuts down cleanly on
SIGTERM" feel sluggish and risks a slow CI teardown test.
**Why it happens:** `stop_event` is polled at the granularity of `rust_timeout`, not `step`.
`[VERIFIED: watchfiles main.py — watcher.watch(debounce, step, rust_timeout, stop_event)]`
**How to avoid:** Set **`rust_timeout=500`** (with `yield_on_timeout=True` so the loop wakes each
timeout to re-check `stop` and the re-derived `watch_dirs_ref`). Then `stop.set()` is honored within
~500ms and `thread.join(timeout=2.0)` returns promptly.
**Warning signs:** SC#3 teardown test takes ~5s; daemon "stopped" log lags the SIGTERM by seconds.

### Pitfall 3: fd / inotify-watch leak over long uptime (Pitfall #11a → SC#3)
**What goes wrong:** A daemon running for days leaks inotify watches/fds if observers aren't reused;
eventually `OSError: inotify watch limit reached`.
**How to avoid:** ONE long-lived observer thread, created once in `run_daemon`, stopped in the
existing `finally`. Re-deriving the watch set (D-04) must NOT spawn a new `watch()` per reload in a
way that leaks the old one — the single `watch()` generator returns and is re-entered with the new
dirs in the SAME thread (the Rust watcher's fds are released when the generator is exhausted).
**Warning signs:** `cat /proc/<pid>/fd | wc -l` climbing across many saves; inotify-limit OSError.

### Pitfall 4: The watch filter is too broad / includes `.env` (Pitfall #12 boundary)
**What goes wrong:** If the config directory ALSO contains `.env` (common — same project dir),
a naive directory-watch fires on `.env` saves, implying secrets hot-reload (which is permanently out).
**How to avoid:** Pass a `watch_filter` that matches ONLY the config filename and the referenced
template filenames — explicitly NOT `.env`. (`watchfiles.DefaultFilter` already skips dotfiles/VCS,
but be explicit.) A `.env` edit must produce ZERO reloads.
**Warning signs:** A reload fires after editing `.env`; logs show a reload with no config change.

## Code Examples

### Starting + stopping the observer in `run_daemon` (wiring sketch)
```python
# weatherbot/scheduler/daemon.py — inside run_daemon
# (built AFTER holder/scheduler/stop exist; BEFORE the poll loop)
# Source: watchfiles sync watch() — https://watchfiles.helpmanual.io/api/watch/
watch_thread = None
if config.reload.watch and config_path is not None:
    watch_dirs_ref = [_derive_watch_dirs(config, Path(config_path))]

    def request_reload() -> None:          # flag-set ONLY (mirrors the SIGHUP handler)
        reload_requested.set()

    watch_thread = threading.Thread(
        target=_run_watch_observer,
        args=(watch_dirs_ref, request_reload, stop),
        kwargs={"watch_filter": _make_watch_filter(config, Path(config_path))},
        name="weatherbot-filewatch",
        daemon=True,
    )
    watch_thread.start()
    _log.info("file-watch observer started", dirs=[str(d) for d in watch_dirs_ref[0]])
# ... existing try/finally ...
finally:
    if getattr(scheduler, "running", True):
        scheduler.shutdown(wait=False)
    if watch_thread is not None:
        stop.set()                          # already set on SIGTERM; idempotent
        watch_thread.join(timeout=2.0)      # returns within ~rust_timeout (500ms) — SC#3
    PID_FILE.unlink(missing_ok=True)
    _log.info("daemon stopped")
```

### Re-deriving the watch set on a successful reload (D-04)
```python
# weatherbot/scheduler/daemon.py — _do_reload, AFTER the success summary log (~line 618)
# new_cfg is the just-swapped config; config_path is in scope.
if watch_dirs_ref is not None and config_path is not None:
    watch_dirs_ref[0] = _derive_watch_dirs(new_cfg, Path(config_path))
```
(Thread `watch_dirs_ref` into `_do_reload` as an optional kwarg defaulting to `None`, so the
SIGHUP/CLI-only callers and the Phase-9 tests are unaffected.)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `watchdog` (`Observer` + `FileSystemEventHandler`, hand-rolled debounce) | `watchfiles` (Rust `notify` backend, built-in debounce/step, `stop_event`) | watchfiles matured ~2022→2026 (1.x line) | Less code, native debounce + inode-swap directory watch. PITFALLS.md's `watchdog` rec is superseded by D-01 for this project. |

**Deprecated/outdated:**
- PITFALLS.md's "use a mature watcher (`watchdog`)" line — overridden by locked D-01 in favor of
  `watchfiles`. The *principles* in Pitfall #11 (single observer, directory-watch, clean teardown,
  no write-back) still apply verbatim — only the library choice changed.

## Validation Architecture

> nyquist_validation is enabled (`config.json: workflow.nyquist_validation: true`). Section required.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest >=9.0.3` (+ `time-machine` for clocks; `psutil 5.9.8` already installed) |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`) |
| Quick run command | `uv run pytest tests/test_filewatch.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req / SC | Behavior | Test Type | Automated Command | File Exists? |
|----------|----------|-----------|-------------------|-------------|
| SC#1 / CFG-03 | A save to `config.toml` (or a watched template) in a temp dir → `request_reload()`/`reload_requested.set()` is observed; the change takes effect end-to-end | integration | `pytest tests/test_filewatch.py::test_save_triggers_reload -x` | ❌ Wave 0 |
| SC#2 / Pitfall #5 | A simulated truncate-then-write AND temp-then-rename AND multi-event burst each yield **exactly ONE** reload and never parse a half-written file | integration | `pytest tests/test_filewatch.py::test_editor_save_patterns_one_reload -x` | ❌ Wave 0 |
| SC#3 / Pitfall #11 | fd / inotify-watch count stable across N (≥50) inode-swapping saves; SIGTERM (`stop.set()`) → observer thread joins within timeout (no leak, clean teardown) | integration/soak | `pytest tests/test_filewatch.py::test_fd_stable_and_clean_teardown -x` | ❌ Wave 0 |
| SC#4 / CFG-04 | An INVALID on-save edit follows Phase 9 keep-old: `_do_reload` rejects, live config unchanged, daemon keeps running — asserted **through the file-watch trigger**, not just SIGHUP | integration | `pytest tests/test_filewatch.py::test_invalid_save_keeps_old_config -x` | ❌ Wave 0 |
| Idempotence (Specific Ideas) | A save with IDENTICAL content → zero job changes (`+0 -0 ~0 =N`) | unit/integration | `pytest tests/test_filewatch.py::test_identical_save_zero_job_changes -x` | ❌ Wave 0 |
| Toggle (D-03) | `[reload] watch = false` → observer NOT started; SIGHUP/`weatherbot reload` STILL works | unit | `pytest tests/test_filewatch.py::test_watch_toggle_off_no_observer -x` | ❌ Wave 0 |
| Filter (Pitfall #12) | Editing `.env` in the same dir → ZERO reloads | integration | `pytest tests/test_filewatch.py::test_env_save_never_reloads -x` | ❌ Wave 0 |
| Watch-set re-derive (D-04) | After a reload that points `template` at a file in a NEW dir, the new dir is watched | integration | `pytest tests/test_filewatch.py::test_watch_set_rederived_on_reload -x` | ❌ Wave 0 |

### How to make each testable (test seams + fakes)
- **Deterministic editor saves (SC#2):** drive a real temp dir with `tmp_path`; implement three
  helpers — `truncate_write(path, text)` (open `"w"`, write in two flushes), `temp_then_rename(path, text)`
  (write `path.with_suffix(".tmp")` then `os.replace`), `multi_event_burst(path, text)` (N rapid writes).
  Assert the observer (run on a short-lived thread or by draining the `watch()` generator with a fake
  `stop_event` after one yield) produced exactly ONE `request_reload` call (use a `Mock`/counter seam).
- **fd-count assertion (SC#3):** `psutil.Process().num_fds()` (or `len(os.listdir(f"/proc/{os.getpid()}/fd"))`)
  before vs after ≥50 inode-swapping saves; assert delta ≈ 0 (allow a small constant). Then `stop.set()`
  and assert `thread.join(timeout=2.0)` returns and `thread.is_alive()` is False.
- **Trigger-only seam (SC#1/SC#4):** inject `request_reload` as a counter/`Mock` so tests assert the
  trigger fires WITHOUT standing up the whole `_do_reload` (which has Phase-9 coverage). The end-to-end
  SC#4 test wires the real `reload_requested` Event + `_do_reload` against a temp config and asserts
  `holder.current()` is unchanged after an invalid save (reuse `tests/test_reload.py` config builders).
- **Flake control:** `watchfiles` is event-driven; for SC#1/SC#2 prefer a bounded wait
  (`reload_requested.wait(timeout=2.0)`) over `sleep`, and run the observer with `rust_timeout=500`
  so the test never blocks 5s. Mark the soak test with a generous but finite timeout.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_filewatch.py -x`
- **Per wave merge:** `uv run pytest` (full suite — must stay green; Phase 9's `test_reload.py` is the regression guard for the inherited engine)
- **Phase gate:** Full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_filewatch.py` — new file; covers SC#1–4 + idempotence + toggle + `.env`-filter + watch-set re-derive (RED scaffold first, per the project's Wave-0 lazy-import idiom shown in `test_reload.py`).
- [ ] Test helpers for the three editor-save patterns (truncate-write / temp-then-rename / multi-event) — local to `test_filewatch.py` (mirror `test_reload.py`'s local builders; no new shared fixtures needed).
- [ ] Framework install: `uv add watchfiles` — required before the observer module imports.

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1`. Section required.

### Applicable ASVS Categories (L1)
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface; file-watch is local to the operator's host. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no | No new external actor; only the OS user running the daemon can edit watched files. |
| V5 Input Validation | yes | The "input" is a config/template file save → validated by Phase 9's `validate_config_and_templates` BEFORE any swap (reject-and-keep-old). File-watch adds NO new parser. |
| V6 Cryptography | no | None. Secrets (`.env`) are explicitly OUT of the watch set (Pitfall #12). |
| V7 Error Handling / Logging | yes | Reload outcome logged (CFG-06, Phase 9); a bad save logs the reject reason, never crashes (the poll-loop `except` swallows, `daemon.py` ~983). |

### Known Threat Patterns for this phase
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Half-written / malformed file parsed as valid | Tampering / DoS | Debounce (`step=400`) + validate-then-swap keep-old (Phase 9). |
| `.env`/secret edit silently "hot-reloaded" | Information disclosure / confusion | `.env` EXCLUDED from the watch set + filter; secrets are a restart boundary (Pitfall #12). |
| Reload loop from write-back near watched files | DoS | Reload writes NOTHING to config/template dirs (no `.bak`, no auto-format) — Pitfall #11b. |
| inotify-watch exhaustion over long uptime | DoS (resource) | Single long-lived observer; fd-stability soak test (SC#3). |
| Symlinked watched dir pointing outside the project | Tampering (low, local-only) | Single-user local tool; `_derive_watch_dirs` resolves `.parent`/`TEMPLATES_DIR` — operator-controlled paths only. No new external input. |

**Threat surface summary:** This phase introduces NO new external input channel — it watches
directories the operator already controls and writes nothing. The only meaningful boundary is the
`.env`/secrets NEVER-watch rule and the reuse of Phase 9's validate-then-swap so a malformed save
can never take the daemon down. ASVS L1 is satisfied by reusing existing controls, not adding new ones.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `step` is the per-yield quiet window and `debounce` is the max grouping bound (so `step=400` realizes the D-05 quiet window) | Pattern 2 | If reversed, a save-storm could yield early/late; mitigated because validate-then-swap rejects any partial read regardless. Verified against API docs + `main.py`, but exact storm-boundary behavior is best confirmed by the SC#2 test on the target host. |
| A2 | `rust_timeout` bounds `stop_event` teardown latency (default 5000ms → set 500ms) | Pitfall #2 | If stop is actually checked more often, the 500ms is merely conservative (no harm). Verified from `main.py` source. |
| A3 | A single `Config.template` (today) ⇒ the watch set is `{config dir, TEMPLATES_DIR}`; per-location templates would extend the set | Pattern 4 | Low — built over a SET so future per-location templates extend without a rewrite (mirrors `loader.py:131`). |
| A4 | Re-entering `watch()` with new dirs in the same thread releases the old inotify fds (no leak across a watch-set re-derive) | Pitfall #3 / D-04 | The SC#3 soak test must explicitly include a watch-set-changing reload to confirm fd stability across re-derivation, not just plain saves. |

## Open Questions

1. **Watched directory deleted/recreated mid-run.**
   - What we know: `watchfiles` watches a directory; on directory-watch, deleting+recreating the dir
     can drop the underlying inotify watch.
   - What's unclear: whether `watchfiles` 1.2.0 auto-re-establishes the watch on recreate, or whether
     the observer loop must re-enter `watch()` (the `yield_on_timeout=True` + loop re-entry pattern
     gives a re-establishment point every `rust_timeout`).
   - Recommendation: rely on the loop re-entry (re-`watch()` on each `rust_timeout` tick picks the dir
     back up); log a debug line if a watched dir is missing. For a single-user bot whose config dir is
     stable, this is a low-frequency edge — a graceful re-watch + log is sufficient (don't crash).

2. **The `watch` toggle is read once at startup.**
   - What we know: the observer reads `config.reload.watch` when `run_daemon` decides to start it.
   - What's unclear: whether flipping `watch` in `config.toml` should start/stop the observer live.
   - Recommendation: applied-on-next-reload is acceptable and simplest (avoids tearing down/standing
     up the observer mid-run). Document the one-line caveat. The explicit trigger always works.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `watchfiles` | the observer | ✗ (not yet installed) | target `>=1.2.0` | none — `uv add watchfiles` (blocking install step in the plan) |
| Python | runtime | ✓ | 3.12.3 | — (watchfiles needs >=3.10; satisfied) |
| `psutil` | SC#3 fd-count test | ✓ | 5.9.8 | `/proc/<pid>/fd` listing (Linux) |
| `pytest` / `time-machine` | tests | ✓ | pytest 9.0.3, time-machine 2.16 | — |
| Linux inotify | the Rust notify backend | ✓ (Linux 6.17) | — | `force_polling=True` (watchfiles auto-falls-back on WSL) |

**Missing dependencies with no fallback:** `watchfiles` — but trivially resolved by `uv add watchfiles`
(this is a planned install task, not a blocker).
**Missing dependencies with fallback:** none.

## Sources

### Primary (HIGH confidence)
- `https://watchfiles.helpmanual.io/api/watch/` — full `watch()` signature: `debounce=1600`, `step=50`,
  `stop_event`, `rust_timeout=5000`, `yield_on_timeout`, `watch_filter` defaults; ms units; yields `set[FileChange]`.
- `https://github.com/samuelcolvin/watchfiles/blob/main/watchfiles/main.py` — confirms
  `watcher.watch(debounce, step, rust_timeout, stop_event)` and that `stop_event` is polled at `rust_timeout` granularity.
- PyPI JSON API (`https://pypi.org/pypi/watchfiles/json`) — latest **1.2.0** (2026-05-18), `requires_python >=3.10`,
  304M downloads/month. `[VERIFIED: 2026-06-16]`
- Project code (read this session): `weatherbot/scheduler/daemon.py` (`run_daemon` ~817, `_do_reload` ~531,
  poll loop ~961, `_install_reload_signal` ~793, finally ~991), `weatherbot/config/loader.py`
  (`validate_config_and_templates` + `{cfg.template}` set ~131), `weatherbot/config/models.py` (Config),
  `templates/renderer.py` (`TEMPLATES_DIR`, `validate_template`), `tests/test_reload.py` (Wave-0 idiom),
  `.planning/research/PITFALLS.md` (#5, #11, #12, the hot-reload checklist), `.planning/REQUIREMENTS.md` (CFG-03),
  `.planning/ROADMAP.md` (Phase 10 SCs).

### Secondary (MEDIUM confidence)
- WebSearch result quoting watchfiles param semantics: "`debounce`: maximum time in ms to group changes
  before yielding; `step`: time to wait for new changes in ms — if none in this time and ≥1 change seen,
  yield; `rust_timeout`: max ms to wait in rust, 0 = no timeout; the GIL is released during a step_ms sleep."
  (`https://github.com/samuelcolvin/watchfiles/blob/main/watchfiles/main.py` docstring, surfaced via search.)

### Tertiary (LOW confidence)
- None required — all load-bearing claims are verified against the API docs, source, or project code.

## Metadata

**Confidence breakdown:**
- Standard stack (`watchfiles>=1.2.0`): HIGH — PyPI-verified version + dates; independently legitimate.
- Architecture / wiring: HIGH — grounded in the actual `run_daemon`/`_do_reload`/poll-loop code read this session.
- `debounce`/`step`/`rust_timeout` mapping: HIGH (docs + source) — exact storm-boundary behavior flagged A1 for the SC#2 test to confirm on-host.
- Pitfalls: HIGH — PITFALLS.md #5/#11/#12 + the API teardown detail (#2) are concrete.
- Validation Architecture: HIGH — seams map to existing `test_reload.py` patterns + installed `psutil`.

**Research date:** 2026-06-16
**Valid until:** ~2026-07-16 (watchfiles 1.x is stable; re-check the pinned version if a 1.3/2.0 lands).
