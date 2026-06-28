"""Pure-stdlib PID-file helper: atomic write + read + /proc staleness guard (D-03).

This module is the cross-process control primitive for the explicit reload path
(CFG-02). The daemon writes its PID here atomically at startup; the short-lived
``weatherbot reload`` sender reads it back, verifies via ``/proc/<pid>/cmdline``
that the PID is actually a weatherbot process (the PID-recycling defense), then
signals it.

stdlib ``os`` / ``tempfile`` / ``pathlib`` ONLY — zero new dependencies. No
``python-pidfile``/``fasteners`` package is warranted: the daemon is
single-instance and ``os.replace`` is atomic on POSIX (RESEARCH "Don't
Hand-Roll"). The module mirrors :mod:`weatherbot.ops.sdnotify`'s posture — it
reads an OS fact and never lets a missing/odd ``/proc`` crash the caller — but
the WRITER deliberately re-raises: a startup PID-write failure must be visible
(it runs inside ``run_daemon``'s startup, not on a hot path). Never imports
``cli``/``scheduler`` so it stays import-cycle-free.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from yahir_reusable_bot.lifecycle import is_running_process

# The WeatherBot ``/proc`` staleness marker (D-03): the bytes the generalized
# lifecycle guard matches against argv0's basename / the ``-m`` module form. This
# is WeatherBot's ``[project.scripts] weatherbot`` console-script identity; it
# stays an app-side constant (the module guard takes it as an injected
# ``proc_marker`` and names no weather noun). ``is_weatherbot_pid`` threads this
# default, reproducing the pre-25-02 ``b"weatherbot"`` guard byte-identically.
WEATHERBOT_PROC_MARKER: bytes = b"weatherbot"

# Module-constant default PID-file path with an optional per-callsite override
# (mirrors store.py DEFAULT_DB_PATH / templates TEMPLATES_DIR). The file lives
# INSIDE the systemd ``RuntimeDirectory=weatherbot`` dir (``/run/weatherbot/``),
# which systemd creates owned by the non-root service ``User=`` at start (and
# removes on stop) — so the non-root daemon can write its PID there without the
# ``PermissionError [Errno 13]`` that bare root-owned ``/run`` produced (the
# Phase 11 UAT crash-loop fix). The ``pid_file.parent.mkdir(...)`` in
# ``write_pid_atomic`` remains a graceful fallback (e.g. running outside systemd)
# but is no longer the load-bearing mechanism: the unit's ``RuntimeDirectory=``
# is. A non-writable dir still degrades cleanly (write_pid_atomic surfaces the
# error to the daemon's visible startup; the reader/guard simply report "no PID").
PID_FILE: Path = Path("/run/weatherbot/weatherbot.pid")


def write_pid_atomic(pid_file: Path | str = PID_FILE) -> None:
    """Write ``os.getpid()`` to ``pid_file`` atomically (temp + ``os.replace``).

    A reader never observes a partial/torn PID file: the pid is written to a temp
    file in the same directory, then ``os.replace`` (atomic on POSIX) swaps it
    into place (T-09-07). On any error the temp file is unlinked and the error is
    RE-RAISED — this runs in ``run_daemon`` startup where a PID-write failure must
    be loud, not swallowed.
    """
    pid_file = Path(pid_file)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(pid_file.parent), prefix=".wbpid-")
    try:
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        os.replace(tmp, pid_file)  # atomic on POSIX — never a partial PID file
    except BaseException:
        # Best-effort cleanup of the temp file, then re-raise so the daemon
        # startup sees the failure. fd may already be closed (after os.close);
        # closing twice raises OSError, so guard it.
        try:
            os.close(fd)
        except OSError:
            pass
        Path(tmp).unlink(missing_ok=True)
        raise


def read_pid(pid_file: Path | str = PID_FILE) -> int:
    """Return the int PID stored in ``pid_file``.

    Raises ``FileNotFoundError`` when the file is absent and ``ValueError`` when
    its contents are not a clean integer — the established catch set the
    ``do_reload`` sender handles to report "no valid PID file" (outcome-only, no
    secrets).
    """
    text = Path(pid_file).read_text(encoding="utf-8").strip()
    return int(text)


def is_weatherbot_pid(
    pid: int,
    cmdline_reader: Callable[[int], bytes] | None = None,
) -> bool:
    """Return True only if PID ``pid`` is a live weatherbot process (D-03 guard).

    A thin app-side wrapper over the relocated, marker-parameterized lifecycle
    guard (:func:`yahir_reusable_bot.lifecycle.is_running_process`, Plan 25-01):
    it delegates with the WeatherBot ``proc_marker = WEATHERBOT_PROC_MARKER``
    (``b"weatherbot"``), so the behavior is byte-identical to the pre-25-02 guard —
    ``is_weatherbot_pid(pid)`` returns exactly what it returned before for the same
    ``/proc`` cmdline. The ``weatherbot``-named symbol stays here in the weather
    path (the litmus only scans ``yahir_reusable_bot/**``); the module side is
    noun-free.

    Reads ``/proc/<pid>/cmdline`` and matches the marker BEFORE the caller signals
    it, so a SIGHUP can never be delivered to a recycled/unrelated PID (T-09-06).
    Returns ``False`` when the PID is not running (``FileNotFoundError`` on the
    cmdline path). If ``/proc`` itself is absent (non-Linux), the guard degrades to
    ``True`` — the host is Linux, so this only affects portability.

    ``cmdline_reader`` is an injectable reader (``pid -> bytes``) used by tests to
    stub the ``/proc`` read; production passes ``None``. When ``None``, the app's
    own ``_read_proc_cmdline`` (which degrades to ``b"weatherbot"`` off-Linux) is
    threaded through so the WeatherBot degrade wording stays exact.
    """
    reader = _read_proc_cmdline if cmdline_reader is None else cmdline_reader
    return is_running_process(
        pid,
        proc_marker=WEATHERBOT_PROC_MARKER,
        cmdline_reader=reader,
    )


def _argv_is_weatherbot(cmdline: bytes) -> bool:
    """Return True only when NUL-separated ``cmdline`` names the weatherbot PROGRAM.

    The PID-recycling defense (T-09-06) must key on program identity, NOT on the
    token appearing anywhere in argv (CR-02). A raw ``b"weatherbot" in cmdline``
    substring test wrongly accepts unrelated recycled-PID processes whose argv
    merely *mentions* the path — ``vim .../weatherbot/config.toml``,
    ``tail -f weatherbot.log`` — and would deliver SIGHUP (default disposition:
    terminate) to them. So match ``argv0``'s basename, and for the
    ``python -m weatherbot`` form match the ``-m`` module target in the next two
    fields; never the whole buffer.
    """
    argv = [part for part in cmdline.split(b"\x00") if part]
    if not argv:
        return False
    prog = Path(argv[0].decode("utf-8", "replace")).name
    if prog == "weatherbot":
        return True
    # `python -m weatherbot [run]`: interpreter is argv0, `-m` then the module name.
    return b"-m" in argv[1:3] and b"weatherbot" in argv[1:4]


def _read_proc_cmdline(pid: int) -> bytes:
    """Read ``/proc/<pid>/cmdline`` raw bytes (NUL-separated argv).

    Raises ``FileNotFoundError`` when the PID is not running. When ``/proc`` as a
    whole is absent (non-Linux), degrade by returning a sentinel that contains
    ``b"weatherbot"`` so :func:`is_weatherbot_pid` signals directly (documented
    degraded guard; host is Linux).
    """
    proc_pid = Path(f"/proc/{pid}/cmdline")
    if not Path("/proc").exists():
        return b"weatherbot"  # /proc absent (non-Linux) -> degrade to signal
    return proc_pid.read_bytes()
