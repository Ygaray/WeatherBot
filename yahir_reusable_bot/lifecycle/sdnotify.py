"""Pure-stdlib systemd readiness notifier (OPS-02, D-05).

Sends a single ``READY=1`` (and optionally ``WATCHDOG=1``) ``AF_UNIX`` /
``SOCK_DGRAM`` datagram to ``$NOTIFY_SOCKET`` — the systemd ``sd_notify`` wire
protocol. A no-op when ``NOTIFY_SOCKET`` is unset (running interactively or in
tests), so the daemon behaves identically with and without systemd.

stdlib ``socket`` / ``os`` ONLY — zero new dependencies. The ``sdnotify`` /
``systemd-python`` PyPI packages are deliberately NOT used (they are ~10 lines of
this same code; rejected per the project's minimal-dependency posture). The send
is best-effort: an ``OSError`` is swallowed (mirroring ``discord.py``'s
never-raise-on-transport-error posture) so a notify failure can never crash the
daemon — readiness signaling must not be load-bearing for liveness.
"""

from __future__ import annotations

import os
import socket


class SystemdNotifier:
    """READY=1 / WATCHDOG=1 to systemd; a no-op when not run under systemd.

    Reads ``NOTIFY_SOCKET`` once at construction. An abstract-namespace socket
    (leading ``@``) has its ``@`` replaced with a NUL byte per the sd_notify
    protocol. When the var is unset, ``self._addr`` is ``None`` and every send is
    a silent no-op.
    """

    def __init__(self) -> None:
        addr = os.environ.get("NOTIFY_SOCKET")
        # Abstract-namespace socket: a leading '@' must become a NUL byte ("\0").
        if addr and addr.startswith("@"):
            addr = "\0" + addr[1:]
        self._addr = addr or None

    def _send(self, msg: str) -> None:
        if self._addr is None:
            return  # not under systemd -> silently do nothing
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.sendto(msg.encode("utf-8"), self._addr)
        except OSError:
            # Never let a notify failure crash the daemon; readiness is
            # best-effort signaling (mirrors discord.py's never-raise posture).
            pass

    def ready(self) -> None:
        """Signal ``READY=1`` (systemd transitions the unit activating -> active)."""
        self._send("READY=1")

    def watchdog(self) -> None:
        """Signal ``WATCHDOG=1`` — present but unused in v1 (Pitfall 6 deferred)."""
        self._send("WATCHDOG=1")
