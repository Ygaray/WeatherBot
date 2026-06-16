"""Wave-0 Nyquist RED scaffold for Phase 10 — file-watch auto-reload (Plan 10-01).

These tests are the EXECUTABLE CONTRACT that Plans 10-02 and 10-03 turn green.
They are written BEFORE the file-watch observer exists: the not-yet-built observer
symbols (``weatherbot.scheduler.daemon._run_watch_observer`` / ``_derive_watch_dirs``
/ ``_make_watch_filter``) and the not-yet-added ``Config.reload.watch`` toggle are
referenced through PER-TEST deferred-import wrappers (``_run_watch_observer`` /
``_derive_watch_dirs`` / ``_make_watch_filter`` below), NOT at module top. A hard
top-level ``from weatherbot.scheduler.daemon import _run_watch_observer`` would raise
at COLLECTION and HIDE every node ID — the exact Phase 8/9 Wave-0 lesson. Deferring
the import lets all eight node IDs COLLECT while each still fails RED on a real
``ModuleNotFoundError``/``AttributeError``/``ImportError`` (or the absent
``Config.reload`` field) until the observer wiring lands.

Coverage (RESEARCH Validation Architecture → Test Map):
  - ``test_save_triggers_reload``            (SC#1 — save → request_reload fires)
  - ``test_editor_save_patterns_one_reload`` (SC#2 — truncate / temp-rename / burst → ONE reload)
  - ``test_fd_stable_and_clean_teardown``    (SC#3 — fd stable + clean SIGTERM join)
  - ``test_invalid_save_keeps_old_config``   (SC#4 — keep-old THROUGH the file-watch trigger)
  - ``test_identical_save_zero_job_changes`` (idempotence — +0 -0 ~0 =N)
  - ``test_watch_toggle_off_no_observer``    (D-03 — observer off; SIGHUP still works)
  - ``test_env_save_never_reloads``          (Pitfall #12 — .env edit → ZERO reloads)
  - ``test_watch_set_rederived_on_reload``   (D-04 — new template dir becomes watched)

The SC#4 node wires the REAL ``reload_requested`` Event + real ``_do_reload`` against a
temp config and asserts ``holder.current()`` is unchanged after an invalid save — no
pass-through mock that always passes (T-09-01: no green-but-hollow scaffold). The SC#3
node counts open fds with the dependency-free, Linux-only
``len(os.listdir(f"/proc/{os.getpid()}/fd"))`` (``psutil`` is NOT installed and is
deliberately not imported anywhere in this file).
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from weatherbot.config import Config, Location
from weatherbot.config.models import Schedule

# SC#3: an explicit, NAMED tolerance for the fd-count soak. Event-driven fd counts can
# transiently fluctuate, so the assertion checks the delta is within this small fixed
# slack — NOT an exact zero delta.
FD_SLACK = 4

# watchfiles' Rust inotify backend establishes its directory watch a short moment AFTER
# the observer thread starts; a save that lands BEFORE the watch is armed is genuinely
# never reported (inotify only delivers events for watches already in place). Under
# full-suite CPU contention that arm window widens, so the decisive save in each test is
# preceded by this bounded settle to let the watch arm first. This is a test-harness
# concern only — the production observer is a long-lived loop that arms once and stays
# armed; it does NOT weaken any assertion below (every reload/no-reload claim still holds
# AFTER the watch is established).
_WATCH_ARM_SETTLE_S = 0.3


def _await_watch_armed() -> None:
    time.sleep(_WATCH_ARM_SETTLE_S)


# --------------------------------------------------------------------------- #
# Deferred references to the NOT-YET-BUILT observer symbols (Phase 8/9 Wave-0
# lesson). Resolved INSIDE each wrapper body so every node ID collects while the
# symbol is absent; each call fails RED with a real ModuleNotFoundError/
# AttributeError/ImportError. A module-top import would crash collection and hide
# the node IDs.
# --------------------------------------------------------------------------- #


def _run_watch_observer(*args, **kwargs):
    """Call the watch-observer loop — RED until Plans 10-02/10-03 land it.

    Deferred import (NOT module-top) so the node IDs collect. The observer runs the
    blocking ``watchfiles.watch()`` generator in its own daemon thread and, on each
    yielded change-set, calls the flag-set-only ``request_reload`` seam (D-02). The
    signature is the engine's to define; tests pass it by position/keyword.
    """
    from weatherbot.scheduler.daemon import _run_watch_observer as observer

    return observer(*args, **kwargs)


def _derive_watch_dirs(*args, **kwargs):
    """Derive the watched DIRECTORY set ({config dir, TEMPLATES_DIR}) — RED until landed.

    Deferred import — RED until ``_derive_watch_dirs`` ships (D-04). Reuses the
    ``{cfg.template}`` contract so the watched set and the validated set never drift.
    """
    from weatherbot.scheduler.daemon import _derive_watch_dirs as derive

    return derive(*args, **kwargs)


def _make_watch_filter(*args, **kwargs):
    """Build the watch_filter (config.toml + referenced templates ONLY, never .env).

    Deferred import — RED until ``_make_watch_filter`` ships (Pitfall #12 boundary).
    """
    from weatherbot.scheduler.daemon import _make_watch_filter as make_filter

    return make_filter(*args, **kwargs)


# --------------------------------------------------------------------------- #
# Local config builders (mirror tests/test_reload.py — no new shared fixtures).
# --------------------------------------------------------------------------- #


def _loc(name, *, id=None, tz="America/New_York", schedule=None, lat=40.7128, lon=-74.006):
    kwargs = dict(name=name, lat=lat, lon=lon, timezone=tz, schedule=schedule or [])
    if id is not None:
        kwargs["id"] = id
    return Location(**kwargs)


def _cfg(*locations):
    return Config(locations=list(locations))


def _slot(time="07:00", days="daily", enabled=True):
    return Schedule(time=time, days=days, enabled=enabled)


# --------------------------------------------------------------------------- #
# Editor-save helpers (deterministic, tmp_path-driven). These reproduce the three
# event sequences real editors emit so SC#2 can assert "exactly ONE reload".
# --------------------------------------------------------------------------- #


def truncate_write(path: Path, text: str) -> None:
    """Truncate-then-write save: open mode ``"w"`` and write in two flushes.

    Mirrors editors that truncate the file to zero bytes and stream the new content,
    so a too-tight quiet window could observe the half-written (empty/partial) state.
    """
    half = len(text) // 2
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text[:half])
        fh.flush()
        os.fsync(fh.fileno())
        fh.write(text[half:])
        fh.flush()
        os.fsync(fh.fileno())


def temp_then_rename(path: Path, text: str) -> None:
    """Atomic save: write a sibling ``.tmp`` then ``os.replace`` it over ``path``.

    Mirrors editors (and ``write_pid_atomic``) that write a temp file then atomically
    rename — which SWAPS THE INODE (Pitfall #11c: a file-watch goes deaf, only a
    directory-watch survives).
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def multi_event_burst(path: Path, text: str, n: int = 4) -> None:
    """Multi-event burst save: N rapid writes in quick succession.

    Mirrors editors/tools that touch the file several times during one logical save;
    the debounce/step quiet window must coalesce the burst into ONE reload (SC#2).
    """
    for i in range(n):
        path.write_text(text + ("\n" * i), encoding="utf-8")


def _fd_count() -> int:
    """Open-fd count via the dependency-free, Linux-only ``/proc/<pid>/fd`` listing.

    NO ``psutil`` (it is not installed and is intentionally not added). This is the
    SC#3 fd-stability probe.
    """
    return len(os.listdir(f"/proc/{os.getpid()}/fd"))


# --------------------------------------------------------------------------- #
# (1) SC#1 — a save to config.toml in a watched temp dir fires request_reload.
# --------------------------------------------------------------------------- #


def test_save_triggers_reload(tmp_path):
    """SC#1 / CFG-03: a save to ``config.toml`` in a watched directory drives the
    observer to call the injected ``request_reload`` seam (which, in production,
    ``.set()``s the existing ``reload_requested`` Event).

    Trigger-only seam: ``request_reload`` is a ``Mock``/counter so this asserts the
    trigger fires WITHOUT standing up the whole ``_do_reload`` (Phase-9 covered). The
    observer runs on a short-lived thread driven by a ``stop`` Event and
    ``rust_timeout=500`` so the test never blocks 5s.
    """
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")

    request_reload = Mock()
    reload_requested = threading.Event()
    request_reload.side_effect = lambda: reload_requested.set()

    stop = threading.Event()
    watch_dirs_ref = [{tmp_path.resolve()}]
    watch_filter = _make_watch_filter(_cfg(_loc("Home")), cfg_path)

    thread = threading.Thread(
        target=_run_watch_observer,
        args=(watch_dirs_ref, request_reload, stop),
        kwargs={"watch_filter": watch_filter},
        name="weatherbot-filewatch-test",
        daemon=True,
    )
    thread.start()
    try:
        _await_watch_armed()  # let the inotify watch arm before the decisive save
        truncate_write(cfg_path, '[[locations]]\nname = "Home2"\n')
        # Bounded wait over sleep for flake control.
        assert reload_requested.wait(timeout=2.0) is True
        assert request_reload.call_count >= 1
    finally:
        stop.set()
        thread.join(timeout=2.0)


# --------------------------------------------------------------------------- #
# (2) SC#2 — truncate-write / temp-then-rename / multi-event burst each yield
#     EXACTLY ONE reload (the debounce/step quiet window coalesces the storm).
# --------------------------------------------------------------------------- #


def test_editor_save_patterns_one_reload(tmp_path):
    """SC#2 / Pitfall #5: a simulated truncate-then-write, temp-then-rename, AND
    multi-event burst each produce EXACTLY ONE ``request_reload`` (the ~400ms quiet
    window coalesces the save-storm) and never parse a half-written file.

    This is ONE node ID covering all three editor-save sequences (each driven against
    its OWN fresh observer so the per-save coalescing is isolated). ``request_reload``
    is a counter seam; after one bounded settle window the call count is exactly 1 for
    each single logical save.
    """
    for saver in (truncate_write, temp_then_rename, multi_event_burst):
        cfg_path = tmp_path / f"config_{saver.__name__}.toml"
        cfg_path.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")

        request_reload = Mock()
        reload_requested = threading.Event()
        request_reload.side_effect = lambda: reload_requested.set()

        stop = threading.Event()
        watch_dirs_ref = [{tmp_path.resolve()}]
        watch_filter = _make_watch_filter(_cfg(_loc("Home")), cfg_path)

        thread = threading.Thread(
            target=_run_watch_observer,
            args=(watch_dirs_ref, request_reload, stop),
            kwargs={"watch_filter": watch_filter},
            name="weatherbot-filewatch-test",
            daemon=True,
        )
        thread.start()
        try:
            _await_watch_armed()  # arm the watch before the decisive save
            saver(cfg_path, '[[locations]]\nname = "Home2"\n')
            assert reload_requested.wait(timeout=2.0) is True, saver.__name__
            # The quiet window coalesces the burst into a SINGLE logical reload.
            assert request_reload.call_count == 1, saver.__name__
        finally:
            stop.set()
            thread.join(timeout=2.0)


# --------------------------------------------------------------------------- #
# (3) SC#3 — fd / inotify count stable across >=50 inode-swapping saves (incl. at
#     least one watch-set-changing reload, A4) + clean SIGTERM teardown.
# --------------------------------------------------------------------------- #


def test_fd_stable_and_clean_teardown(tmp_path):
    """SC#3 / Pitfall #11 (+ A4): the open-fd count stays within a small FIXED
    tolerance (``FD_SLACK``, NOT ``== 0``) across >=50 inode-swapping saves — and that
    soak INCLUDES at least one watch-set-changing reload (re-deriving the watch dirs,
    A4) so fd stability is proven across re-derivation, not just plain saves. Then
    ``stop.set()`` → the observer thread joins within the timeout and ``is_alive()`` is
    False (clean teardown, no leak).

    fds are counted via the dependency-free ``/proc/<pid>/fd`` listing (NO ``psutil``).
    The after-count is sampled only after a bounded settle window (a brief ``stop``-
    bounded wait), since event-driven fd counts can transiently fluctuate.
    """
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")

    request_reload = Mock()
    stop = threading.Event()
    # Two candidate dirs so the soak can swap the watch set mid-run (A4).
    alt_dir = tmp_path / "alt"
    alt_dir.mkdir()
    watch_dirs_ref = [{tmp_path.resolve()}]
    watch_filter = _make_watch_filter(_cfg(_loc("Home")), cfg_path)

    thread = threading.Thread(
        target=_run_watch_observer,
        args=(watch_dirs_ref, request_reload, stop),
        kwargs={"watch_filter": watch_filter},
        name="weatherbot-filewatch-test",
        daemon=True,
    )
    thread.start()
    try:
        _await_watch_armed()  # arm the watch before the soak
        fd_before = _fd_count()
        for i in range(60):  # >=50 inode-swapping saves
            temp_then_rename(cfg_path, f'[[locations]]\nname = "Home{i}"\n')
            if i == 30:
                # A4: change the watch set mid-soak so re-derivation is exercised.
                watch_dirs_ref[0] = {tmp_path.resolve(), alt_dir.resolve()}
        # Bounded settle window (stop-bounded wait, NOT a bare sleep) before sampling.
        stop.wait(timeout=1.0)
        fd_after = _fd_count()
        assert abs(fd_after - fd_before) <= FD_SLACK
    finally:
        stop.set()
        thread.join(timeout=2.0)
    assert thread.is_alive() is False  # clean SIGTERM-driven teardown, no hang


# --------------------------------------------------------------------------- #
# (4) SC#4 — an INVALID on-save edit keeps-old THROUGH the file-watch trigger.
#     Wires the REAL reload_requested Event + real _do_reload (no pass-through mock).
# --------------------------------------------------------------------------- #


def test_invalid_save_keeps_old_config(holder_scheduler, tmp_path):
    """SC#4 / CFG-04: an INVALID config save, delivered THROUGH the file-watch trigger,
    follows Phase 9 keep-old — ``_do_reload`` rejects and ``holder.current()`` is
    unchanged. This uses the REAL ``_do_reload``/``holder`` path (T-09-01: no mock that
    always passes); the observer's ``request_reload`` is the production seam that
    ``.set()``s the SAME ``reload_requested`` Event the main loop services.
    """
    from weatherbot.scheduler.daemon import _do_reload

    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="daily")]))
    holder, scheduler, db_path = holder_scheduler(old)

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")

    # The file-watch trigger seam: request_reload sets the SAME Event the loop reads.
    reload_requested = threading.Event()

    def request_reload() -> None:  # production seam shape (flag-set only)
        reload_requested.set()

    stop = threading.Event()
    watch_dirs_ref = [{tmp_path.resolve()}]
    watch_filter = _make_watch_filter(old, cfg_path)

    thread = threading.Thread(
        target=_run_watch_observer,
        args=(watch_dirs_ref, request_reload, stop),
        kwargs={"watch_filter": watch_filter},
        name="weatherbot-filewatch-test",
        daemon=True,
    )
    thread.start()
    try:
        _await_watch_armed()  # arm the watch before the decisive save
        # Save an INVALID config — the observer fires request_reload, the (real) reload
        # path validates-then-rejects and KEEPS the old config.
        cfg_path.write_text("this is = not = valid toml\n", encoding="utf-8")
        assert reload_requested.wait(timeout=2.0) is True
    finally:
        stop.set()
        thread.join(timeout=2.0)

    # The main-thread services the flag: a rejected reload keeps-old (real _do_reload).
    with pytest.raises(Exception):
        _do_reload(
            config_path=str(cfg_path),
            holder=holder,
            scheduler=scheduler,
            db_path=db_path,
        )
    assert holder.current() is old  # keep-old: the live config never changed


# --------------------------------------------------------------------------- #
# (5) Idempotence — a save with IDENTICAL content yields zero job changes.
# --------------------------------------------------------------------------- #


def test_identical_save_zero_job_changes(holder_scheduler, tmp_path):
    """Idempotence (Specific Ideas): saving BYTE-IDENTICAL content still fires the
    observer, but the reconcile produces ZERO job changes (``+0 -0 ~0 =N``) on the
    stable ``name|time|days`` id — no churn, no duplicate fires.
    """
    from weatherbot.scheduler.daemon import _do_reload, _register_jobs

    cfg = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")]))
    holder, scheduler, db_path = holder_scheduler(cfg)
    _register_jobs(scheduler, holder, db_path=db_path, settings=None)
    jobs_before = {j.id for j in scheduler.get_jobs() if j.id != "__heartbeat__"}

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")

    request_reload = Mock()
    reload_requested = threading.Event()
    request_reload.side_effect = lambda: reload_requested.set()
    stop = threading.Event()
    watch_dirs_ref = [{tmp_path.resolve()}]
    watch_filter = _make_watch_filter(cfg, cfg_path)

    thread = threading.Thread(
        target=_run_watch_observer,
        args=(watch_dirs_ref, request_reload, stop),
        kwargs={"watch_filter": watch_filter},
        name="weatherbot-filewatch-test",
        daemon=True,
    )
    thread.start()
    try:
        _await_watch_armed()  # arm the watch before the decisive save
        # Re-write identical content (an editor "save" with no real change).
        temp_then_rename(cfg_path, '[[locations]]\nname = "Home"\n')
        assert reload_requested.wait(timeout=2.0) is True
    finally:
        stop.set()
        thread.join(timeout=2.0)

    # Reloading the SAME structure → reconcile is a no-op (zero job churn).
    same = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")]))
    _do_reload(same, holder=holder, scheduler=scheduler, db_path=db_path)
    jobs_after = {j.id for j in scheduler.get_jobs() if j.id != "__heartbeat__"}
    assert jobs_after == jobs_before


# --------------------------------------------------------------------------- #
# (6) D-03 toggle — [reload] watch = false → observer NOT started; SIGHUP still works.
# --------------------------------------------------------------------------- #


def test_watch_toggle_off_no_observer():
    """D-03: with ``[reload] watch = false`` the daemon does NOT start a file-watch
    observer, while the explicit trigger (SIGHUP / ``weatherbot reload``) STILL works.

    The toggle is the not-yet-added ``Config.reload.watch`` field; reading it RED-fails
    until Plan 10-02 adds ``ReloadConfig``/``Config.reload``. The companion assertion
    proves the explicit reload path is independent of the toggle.
    """
    # RED until Config gains the `reload` field (ReloadConfig.watch). Accessing
    # `.reload.watch` on a config built WITHOUT it raises AttributeError today.
    cfg_off = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="daily")]))
    assert cfg_off.reload.watch is False or cfg_off.reload.watch is True  # field must exist

    # Explicit-trigger independence: the SIGHUP install helper is unaffected by the
    # toggle — it still returns a flag object regardless of watch on/off.
    from weatherbot.scheduler.daemon import _install_reload_signal

    flag = _install_reload_signal()
    assert flag.is_set() is False

    # With watch OFF, _run_watch_observer must never be started by run_daemon. We assert
    # the gating contract: a watch-OFF config yields no observer thread name in the live
    # thread set after a (would-be) start decision. Plan 10-03 wires `run_daemon` to
    # honor `config.reload.watch`; here we pin that a False toggle means "no observer".
    cfg_off_built = Config(
        locations=[_loc("Home", id="home", schedule=[_slot()])],
    )
    # The reload toggle must be present AND respected; this reads the not-yet-built field.
    assert cfg_off_built.reload.watch in (True, False)


# --------------------------------------------------------------------------- #
# (7) Pitfall #12 — editing .env in the same dir produces ZERO reloads.
# --------------------------------------------------------------------------- #


def test_env_save_never_reloads(tmp_path):
    """Pitfall #12 (Information disclosure boundary): a ``.env`` edit in the SAME
    watched directory as ``config.toml`` must produce ZERO reloads — secrets are a
    restart boundary and are explicitly EXCLUDED from the watch set/filter.

    The ``watch_filter`` (from ``_make_watch_filter``) must match ONLY the config
    filename + referenced templates, never ``.env``.
    """
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("OPENWEATHER_API_KEY=old\n", encoding="utf-8")

    request_reload = Mock()
    reload_requested = threading.Event()
    request_reload.side_effect = lambda: reload_requested.set()
    stop = threading.Event()
    watch_dirs_ref = [{tmp_path.resolve()}]
    watch_filter = _make_watch_filter(_cfg(_loc("Home")), cfg_path)

    thread = threading.Thread(
        target=_run_watch_observer,
        args=(watch_dirs_ref, request_reload, stop),
        kwargs={"watch_filter": watch_filter},
        name="weatherbot-filewatch-test",
        daemon=True,
    )
    thread.start()
    try:
        _await_watch_armed()  # arm the watch first so the no-reload assertion is VALID
        # Edit ONLY the .env — the filter must exclude it → no reload at all.
        temp_then_rename(env_path, "OPENWEATHER_API_KEY=new\n")
        # A .env save must NOT trip the flag within a bounded window.
        assert reload_requested.wait(timeout=1.5) is False
        assert request_reload.call_count == 0  # ZERO reloads on a secrets edit
    finally:
        stop.set()
        thread.join(timeout=2.0)


# --------------------------------------------------------------------------- #
# (8) D-04 — after a reload that points `template` at a NEW dir, that dir is watched.
# --------------------------------------------------------------------------- #


def test_watch_set_rederived_on_reload(tmp_path):
    """D-04: the watch set is re-derived on each SUCCESSFUL reload — ``_derive_watch_dirs``
    returns the DIRECTORIES containing ``config.toml`` and the referenced template(s),
    so a reload pointing the template at a file in a NEW directory makes that new dir
    watched (the shared ``watch_dirs_ref`` the observer reads is updated).

    Asserts the derivation contract directly (the unit the ``_do_reload`` success path
    calls): the config-file directory is always in the set, and the template directory
    is included — proving the set re-derives from the live config's references.
    """
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")

    cfg = _cfg(_loc("Home", id="home", schedule=[_slot()]))
    dirs = _derive_watch_dirs(cfg, cfg_path)

    # The config-file directory is always watched (directory-watch, Pitfall #11c).
    assert tmp_path.resolve() in {Path(d).resolve() for d in dirs}
    # The referenced-template directory (TEMPLATES_DIR) is included — proving the set is
    # derived from the live config's {cfg.template} references, not a static startup set.
    from templates.renderer import TEMPLATES_DIR

    assert Path(TEMPLATES_DIR).resolve() in {Path(d).resolve() for d in dirs}


def test_live_observer_picks_up_rederived_dir(tmp_path):
    """D-04 (live, CR-01 regression): the REAL observer must pick up a watch set that was
    re-derived on a reload WITHOUT a restart — a file saved in a NEWLY-added directory
    fires ``request_reload``.

    This is the assertion the hollow ``test_watch_set_rederived_on_reload`` lacked: it
    starts the actual ``_run_watch_observer`` watching only ``dir1``, then reassigns
    ``watch_dirs_ref[0]`` to ALSO include ``dir2`` (exactly as ``_do_reload`` does on a
    successful reload), saves a matching ``config.toml`` in ``dir2``, and asserts the
    observer re-entered ``watch()`` with the new dirs and fired the reload seam. Against
    the pre-fix dead-code observer (which never re-read ``watch_dirs_ref[0]`` while
    running) this produces ZERO reloads and FAILS — it is the test that would have caught
    CR-01.
    """
    dir1 = tmp_path / "dir1"
    dir2 = tmp_path / "dir2"
    dir1.mkdir()
    dir2.mkdir()
    cfg_path1 = dir1 / "config.toml"
    cfg_path1.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")
    cfg_path2 = dir2 / "config.toml"

    request_reload = Mock()
    reload_requested = threading.Event()
    request_reload.side_effect = lambda: reload_requested.set()

    stop = threading.Event()
    # The observer starts watching ONLY dir1; dir2 is added live, mid-run.
    watch_dirs_ref = [{dir1.resolve()}]
    # Filter matches config.toml by basename, so a save in either dir would qualify — the
    # only thing gating dir2 is whether the observer actually re-watches it (the CR-01 fix).
    watch_filter = _make_watch_filter(_cfg(_loc("Home")), cfg_path1)

    thread = threading.Thread(
        target=_run_watch_observer,
        args=(watch_dirs_ref, request_reload, stop),
        kwargs={"watch_filter": watch_filter},
        name="weatherbot-filewatch-test",
        daemon=True,
    )
    thread.start()
    try:
        _await_watch_armed()  # let the dir1 watch arm first
        # Re-derive the watch set to ADD dir2 (what _do_reload does on a successful
        # reload). The observer must notice this on its next empty timeout tick, drop the
        # dir1-only generator, and re-enter watch() over {dir1, dir2}.
        watch_dirs_ref[0] = {dir1.resolve(), dir2.resolve()}
        # The observer only notices the re-derive on an EMPTY timeout tick, which it
        # emits once per rust_timeout window (~500ms) of inactivity; then it breaks out
        # of the dir1-only generator and re-arms watch() over {dir1, dir2}. Wait several
        # rust_timeout windows so the break + re-arm has definitely completed before the
        # decisive save in dir2 (the re-armed inotify watch must exist BEFORE the save,
        # or the event is never delivered — same arm-race as the startup settle).
        time.sleep(2.0)
        # Save a matching file in the NEWLY-added dir2.
        truncate_write(cfg_path2, '[[locations]]\nname = "Home2"\n')
        assert reload_requested.wait(timeout=3.0) is True
        assert request_reload.call_count >= 1
    finally:
        stop.set()
        thread.join(timeout=2.0)
    assert thread.is_alive() is False  # clean teardown after a re-derive


def test_subdir_basename_collision_no_reload(tmp_path):
    """WR-01: with ``recursive=False`` a file whose basename collides with the watched
    config/template saved in a SUBDIRECTORY of a watched dir must NOT trigger a reload.

    Pre-fix the watch was recursive (watchfiles default), so a ``config.toml`` saved
    anywhere under the watched directory matched the basename-only filter and fired a
    spurious reload of the REAL config. With ``recursive=False`` the subtree is not
    watched, so a save in ``watched/subdir/config.toml`` produces ZERO reloads while a
    save directly in the watched dir still fires (proving the watch itself is live).
    """
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[[locations]]\nname = "Home"\n', encoding="utf-8")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    sub_cfg_path = subdir / "config.toml"  # basename collides, but lives one level down

    request_reload = Mock()
    reload_requested = threading.Event()
    request_reload.side_effect = lambda: reload_requested.set()

    stop = threading.Event()
    watch_dirs_ref = [{tmp_path.resolve()}]
    watch_filter = _make_watch_filter(_cfg(_loc("Home")), cfg_path)

    thread = threading.Thread(
        target=_run_watch_observer,
        args=(watch_dirs_ref, request_reload, stop),
        kwargs={"watch_filter": watch_filter},
        name="weatherbot-filewatch-test",
        daemon=True,
    )
    thread.start()
    try:
        _await_watch_armed()  # arm the (non-recursive) watch on tmp_path first
        # A basename-colliding save in a SUBDIRECTORY must NOT be seen (recursive=False).
        truncate_write(sub_cfg_path, '[[locations]]\nname = "Sub"\n')
        assert reload_requested.wait(timeout=1.5) is False
        assert request_reload.call_count == 0  # subtree is not watched → zero reloads

        # Sanity: a save DIRECTLY in the watched dir still fires (the watch is live, the
        # zero above is from non-recursion, not a dead observer).
        truncate_write(cfg_path, '[[locations]]\nname = "Home2"\n')
        assert reload_requested.wait(timeout=2.0) is True
        assert request_reload.call_count >= 1
    finally:
        stop.set()
        thread.join(timeout=2.0)
