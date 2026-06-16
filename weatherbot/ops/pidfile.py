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

# Module-constant default PID-file path with an optional per-callsite override
# (mirrors store.py DEFAULT_DB_PATH / templates TEMPLATES_DIR). ``/run`` is the
# canonical runtime-state dir on the systemd host; a non-writable dir degrades
# gracefully (write_pid_atomic mkdir-then-replace surfaces the error to the
# daemon's visible startup, while the reader/guard simply report "no PID").
PID_FILE: Path = Path("/run/weatherbot.pid")


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

    Reads ``/proc/<pid>/cmdline`` and checks for ``b"weatherbot"`` BEFORE the
    caller signals it, so a SIGHUP can never be delivered to a recycled/unrelated
    PID (T-09-06). Returns ``False`` when the PID is not running
    (``FileNotFoundError`` on the cmdline path). If ``/proc`` itself is absent
    (non-Linux), the guard degrades to ``True`` — the host is Linux, so this only
    affects portability, and the documented degrade signals directly.

    ``cmdline_reader`` is an injectable reader (``pid -> bytes``) used by tests to
    stub the ``/proc`` read; production passes ``None`` and reads ``/proc``.
    """
    if cmdline_reader is None:
        cmdline_reader = _read_proc_cmdline
    try:
        cmdline = cmdline_reader(pid)
    except FileNotFoundError:
        # /proc/<pid>/cmdline missing -> the PID is not running (stale/recycled).
        return False
    return _argv_is_weatherbot(cmdline)


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
