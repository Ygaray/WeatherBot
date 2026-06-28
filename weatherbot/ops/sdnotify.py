"""Re-export shim for the relocated systemd readiness notifier (SEAM-05, 25-02).

``SystemdNotifier`` was lifted VERBATIM into the reusable lifecycle layer
(:mod:`yahir_reusable_bot.lifecycle.sdnotify`) in Plan 25-01 — it was already
pure-stdlib (``socket`` / ``os`` only) and weather-noun-free, so it moved with no
change. This module stays as a thin re-export shim (mirroring the Phase-22
``channels/base.py`` and Phase-24 ``config/holder.py`` shim pattern) so every
existing import path — ``from weatherbot.ops import SystemdNotifier`` and
``from weatherbot.ops.sdnotify import SystemdNotifier`` — resolves to the
IDENTICAL object the daemon imported before the move. Tests that patch
``weatherbot.ops.sdnotify.SystemdNotifier`` and the ``test_sdnotify`` suite keep
working unchanged because the name they reach is the same class.
"""

from __future__ import annotations

from yahir_reusable_bot.lifecycle import SystemdNotifier

__all__ = ["SystemdNotifier"]
