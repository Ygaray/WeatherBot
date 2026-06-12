"""Tests for the pure-stdlib sd_notify helper (OPS-02, D-05).

``SystemdNotifier.ready()`` sends a single ``READY=1`` AF_UNIX/SOCK_DGRAM datagram
to ``$NOTIFY_SOCKET`` when running under systemd, and is a silent no-op when
``NOTIFY_SOCKET`` is unset (so the daemon runs identically interactively and in
tests). A send to a bad/closed socket must NOT raise — readiness is best-effort.
"""

from __future__ import annotations

import socket

from weatherbot.ops import SystemdNotifier


def test_ready_is_noop_when_notify_socket_unset(monkeypatch):
    """With NOTIFY_SOCKET UNSET, ready() does nothing and raises nothing."""
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    # Must construct + signal without error and without a socket address.
    notifier = SystemdNotifier()
    assert notifier._addr is None
    notifier.ready()  # no exception


def test_ready_sends_ready_datagram_when_socket_set(monkeypatch, tmp_path):
    """With NOTIFY_SOCKET set to a real AF_UNIX/SOCK_DGRAM path, ready() delivers
    a single ``READY=1`` datagram to it."""
    sock_path = str(tmp_path / "notify.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(sock_path)
    server.settimeout(2.0)
    try:
        monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
        SystemdNotifier().ready()
        data = server.recv(64)
        assert data == b"READY=1"
    finally:
        server.close()


def test_send_to_bad_socket_does_not_raise(monkeypatch, tmp_path):
    """A send to a non-existent socket address swallows OSError (best-effort)."""
    # Point at a path that was never bound — sendto raises OSError, which the
    # notifier must swallow rather than crash the daemon.
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "does-not-exist.sock"))
    SystemdNotifier().ready()  # no exception
