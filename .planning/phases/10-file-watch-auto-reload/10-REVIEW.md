---
phase: 10-file-watch-auto-reload
reviewed: 2026-06-16T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - weatherbot/scheduler/daemon.py
  - weatherbot/config/models.py
  - tests/test_filewatch.py
  - pyproject.toml
findings:
  critical: 1
  warning: 4
  info: 2
  total: 7
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-06-16
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Phase 10 adds a `watchfiles` observer thread that flag-sets the existing Phase 9
`reload_requested` Event, a `ReloadConfig` toggle, and a green-turned RED scaffold.
The Event hand-off (observer → main-thread `_do_reload`) is correctly flag-set-only,
SIGTERM teardown via `stop_event` + `rust_timeout=500` + thread join is sound, and the
`.env` secrets-never-reloaded boundary holds (a `.env` basename is rejected by the
filter, verified empirically).

However, the headline **D-04 "re-derive the watch set on reload"** capability is
**non-functional on a live observer** — verified by direct experiment. The shared
`watch_dirs_ref[0]` cell is only re-read at the top of the observer's OUTER `while`
loop, which is never re-entered while the daemon is running, because the `watchfiles`
`watch()` generator with `yield_on_timeout=True` does **not** return on a timeout tick;
it keeps yielding empty sets inside the same generator and only exhausts when `stop` is
set. So a template moved to a new directory is never watched until the next restart, and
the test that "covers" D-04 only asserts the pure derivation helper, never the live
re-watch — green but hollow. A second, related defect: the watch is `recursive=True`
(watchfiles default, never overridden) and the filter matches on **basename only**, so a
`config.toml` (or the template basename) saved anywhere in a subdirectory under the
watched dir triggers a spurious reload of the real config.

## Critical Issues

### CR-01: D-04 watch-set re-derivation is dead code on a live observer (new dir never watched)

**File:** `weatherbot/scheduler/daemon.py:892-914` (`_run_watch_observer`), with the dead write at `weatherbot/scheduler/daemon.py:655-656` (`_do_reload`)

**Issue:** `_do_reload` re-derives and reassigns `watch_dirs_ref[0]` after a successful
reload (D-04: "a template that moved to a NEW directory becomes watched without a
restart"). The observer is supposed to pick this up by re-reading `watch_dirs_ref[0]` at
the top of its OUTER `while not stop.is_set()` loop and re-entering `watch()` with the
new dirs. But that outer loop is only re-entered when the inner `for _changes in watch(...)`
loop **ends** — i.e. when the `watch()` generator returns. With `yield_on_timeout=True`,
`watch()` does NOT return on a timeout tick; it yields an empty `set()` and stays inside
the same generator, bound to the ORIGINAL `*dirs` snapshot. The generator only exhausts
when `stop` is set (shutdown). Therefore the reassigned `watch_dirs_ref[0]` is never read
again, and a template relocated to a new directory is **silently not watched** until the
process restarts.

Verified empirically: starting the real `_run_watch_observer` watching only `dir1`, then
reassigning `watch_dirs_ref[0] = {dir1, dir2}` (as `_do_reload` does) and editing
`config.toml` in `dir2`, produces **0** reload calls. The comment at lines 893-895
("the prior generator's inotify fds are released on exhaustion before the new one opens")
describes behavior that never occurs while the daemon is alive.

The test `test_watch_set_rederived_on_reload` (tests/test_filewatch.py:526-548) does NOT
catch this — it only calls `_derive_watch_dirs(...)` and asserts the returned set; it
never starts an observer and never verifies a save in the newly-added dir triggers a
reload. The `test_fd_stable_and_clean_teardown` soak reassigns `watch_dirs_ref[0]` at
i==30 but only asserts fd stability, not that the new dir is watched — so the dead
re-derive masquerades as covered.

**Fix:** Make the inner loop honor a watch-set change by exiting the `watch()` generator
when the cell changes, then re-entering with the new dirs. For example, snapshot the
current dirs and break out of the inner loop when `watch_dirs_ref[0]` differs:

```python
while not stop.is_set():
    dirs_snapshot = frozenset(watch_dirs_ref[0])
    for _changes in watch(
        *tuple(dirs_snapshot),
        step=WATCH_QUIET_MS,
        debounce=WATCH_DEBOUNCE_MS,
        rust_timeout=WATCH_RUST_TIMEOUT_MS,
        yield_on_timeout=True,
        watch_filter=watch_filter,
        stop_event=stop,
    ):
        if stop.is_set():
            return
        if _changes:
            request_reload()
        # On a timeout tick (empty set), re-check whether the watch set was
        # re-derived on a reload; if so, drop this generator so the outer loop
        # re-enters watch() with the new dirs (D-04).
        elif frozenset(watch_dirs_ref[0]) != dirs_snapshot:
            break
    if stop.is_set():
        return
```

After this fix, add a real assertion to `test_watch_set_rederived_on_reload` (or a new
node) that starts the observer, swaps the watch set to include a new dir, saves a
matching file there, and asserts `request_reload` fires — closing the green-but-hollow gap.

## Warnings

### WR-01: Recursive watch + basename-only filter triggers spurious reloads from subdirectories

**File:** `weatherbot/scheduler/daemon.py:861-865` (`_watch_filter`), `weatherbot/scheduler/daemon.py:897-905` (`watch()` call)

**Issue:** `watch()` is called without `recursive=False`, so it uses the watchfiles
default `recursive=True` and watches the entire subtree under each watched directory. The
filter matches on **basename only** (`Path(path).name in allowed`). Default deployment
has config dir = CWD / project root (`config.toml` default, cli.py:585), so the watch
covers `data/`, any nested project dirs, etc. A file named `config.toml` or
`briefing-sectioned.txt` saved/edited ANYWHERE in the subtree triggers a reload that
re-reads the REAL `config_path`. Verified empirically: creating `subdir/config.toml`
under the watched dir fired one reload.

Consequences: (a) spurious reloads (each runs validate → swap → reconcile and, on
success, posts no message but does churn the job table — and re-derives watch dirs);
(b) the recursive watch opens inotify watches on every subdirectory in the tree,
including ones that may hold secrets — the filter still gates the trigger so this is not
a direct secret leak, but it is a wider surface than intended (the design says "watch the
config dir + TEMPLATES_DIR", not their entire recursive subtrees).

**Fix:** Pass `recursive=False` to `watch()` (the design watches specific directories,
not trees), and/or match on the resolved absolute path against the exact watched files
rather than basename:

```python
for _changes in watch(
    *dirs,
    step=WATCH_QUIET_MS,
    debounce=WATCH_DEBOUNCE_MS,
    rust_timeout=WATCH_RUST_TIMEOUT_MS,
    yield_on_timeout=True,
    watch_filter=watch_filter,
    stop_event=stop,
    recursive=False,
):
```

Strengthening the filter to compare full resolved paths (not basenames) would also close
the collision, and is the more defensive of the two.

### WR-02: `[reload] watch` defaults ON, so config dir/CWD is watched recursively by default

**File:** `weatherbot/config/models.py:245` (`watch: bool = True`), `weatherbot/scheduler/daemon.py:1062`

**Issue:** `ReloadConfig.watch` defaults to `True`, so every existing config with no
`[reload]` table silently gains a recursive file-watch over the config directory (= CWD
in the default deployment). Combined with WR-01, this means existing deployments inherit
the recursive-subtree watch and the basename-collision spurious-reload behavior without
any opt-in. The auto-reload behavior changing the running schedule on any save is a
meaningful behavior change to ship enabled-by-default.

**Fix:** This is a design decision (D-03 chose default-on), but at minimum it raises the
stakes of WR-01 — fix WR-01 so default-on is safe. If the recursive surface cannot be
narrowed, consider defaulting `watch = False` so auto-reload is opt-in.

### WR-03: Comment claims fd release "before the new one opens" — describes behavior that never runs

**File:** `weatherbot/scheduler/daemon.py:893-895`

**Issue:** The comment ("the prior generator's inotify fds are released on exhaustion
before the new one opens, so fd count stays flat across a watch-set re-derive") documents
a re-derive flow that, per CR-01, never executes on a live observer. The comment is
actively misleading: it asserts a correctness property (no fd leak across re-derive) for
a path that is currently dead. Once CR-01 is fixed the comment becomes true; until then it
hides the bug from a reader.

**Fix:** Tie the comment to the actual mechanism that re-enters `watch()` (the inner-loop
break added in CR-01's fix), or remove the claim until the re-derive path works.

### WR-04: `watch_thread.join(timeout=2.0)` can leave a lingering thread without detection

**File:** `weatherbot/scheduler/daemon.py:1166-1168`

**Issue:** On shutdown the code does `stop.set(); watch_thread.join(timeout=2.0)` but
never checks `watch_thread.is_alive()` afterward. With `rust_timeout=500` the join should
return well under 2s, but if the observer is mid-`request_reload`/blocked the join can
silently time out and leave the (daemon) thread running, with no log line recording the
failed teardown. The teardown is a stated success criterion (SC#3); a silent join timeout
defeats the diagnostic value.

**Fix:** Log if the join times out:

```python
if watch_thread is not None:
    stop.set()
    watch_thread.join(timeout=2.0)
    if watch_thread.is_alive():
        _log.warning("file-watch observer did not stop within join timeout")
```

## Info

### IN-01: `_derive_watch_dirs` / `_make_watch_filter` loop over a single-element set with an unused loop var

**File:** `weatherbot/scheduler/daemon.py:841-842`, `weatherbot/scheduler/daemon.py:858-859`

**Issue:** Both helpers iterate `for _template_name in {config.template}:` over a
one-element set, and `_derive_watch_dirs` never uses `_template_name` inside the loop body
(it adds the same `TEMPLATES_DIR` every iteration). The intent (future per-location
templates) is documented, but as written `_derive_watch_dirs`'s loop is a no-op wrapper
around a single unconditional `dirs.add(...)`. Harmless today; flagged so the
"build over a SET" intent is revisited when multi-template lands (the derive loop would
need to map each template name to its own dir, which it currently does not).

**Fix:** When multi-template arrives, derive the directory per template name; until then,
the loop in `_derive_watch_dirs` could be a plain `dirs.add(Path(TEMPLATES_DIR).resolve())`.

### IN-02: `request_reload` logs at DEBUG while the observer-start logs at INFO — reload triggers are not greppable by default

**File:** `weatherbot/scheduler/daemon.py:1068`

**Issue:** The file-watch `request_reload` closure logs `_log.debug("file-watch change
detected; requesting reload")`. The SIGHUP/CLI reload outcomes are mirrored at INFO via
`_stdlog` (per the module's "reload OUTCOME lines must be capturable" rationale at
lines 88-95). A file-watch-driven reload only surfaces the subsequent `_do_reload`
"reload applied" line, but the *trigger cause* (a file save) is invisible at the default
log level — making "why did the schedule change at 14:03?" harder to reconstruct on the
host journal, which is the exact multi-day-diagnosis goal called out in the module
docstring.

**Fix:** Log the trigger at INFO (outcome-only, no path/secret), e.g.
`_log.info("file-watch change detected; reload requested")`.

---

_Reviewed: 2026-06-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
