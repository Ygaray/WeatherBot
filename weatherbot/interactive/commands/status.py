"""The read-only ``status`` command handler (Plan 12-02, CMD-12 / D-02).

``status`` reports the four D-02 sections — next scheduled send per location,
alive + uptime, bot/UV-monitor liveness, and the last-briefing result — by reading
a :class:`~weatherbot.interactive.state.DaemonState`. It is READ-ONLY: it reads the
heartbeat via ``read_heartbeat`` (the only store call, a reader) and never writes
the store, config, or scheduler.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from weatherbot.interactive.commands import CommandReply
from weatherbot.weather.store import read_heartbeat

if TYPE_CHECKING:
    from weatherbot.interactive.state import DaemonState


def _fmt_epoch(epoch: int | None) -> str:
    """Format a Unix-UTC epoch as a readable UTC string, or 'none yet' when None."""
    if epoch is None:
        return "none yet"
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_uptime(delta) -> str:
    """Render a timedelta as a compact ``Nd Nh Nm`` string."""
    total = int(delta.total_seconds())
    if total < 0:
        total = 0
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def status(daemon_state: DaemonState) -> CommandReply:
    """Daemon liveness, next scheduled sends, and last-briefing result (CMD-12).

    Read-only: reports the four D-02 sections from the injected
    :class:`DaemonState`. The UV monitor (Phase 15) is reported "not running" until
    its liveness callable is supplied (A4).
    """
    lines: list[tuple[str, str]] = []

    # (1) Next scheduled send per location.
    fires = daemon_state.next_fires()
    if fires:
        for name, when in fires.items():
            lines.append((f"Next send — {name}", when))
    else:
        lines.append(("Next send", "no enabled schedule"))

    # (2) Alive + uptime.
    lines.append(("Daemon", f"alive, up {_fmt_uptime(daemon_state.uptime())}"))

    # (3) Bot + UV-monitor liveness.
    bot_state = "alive" if daemon_state.bot_alive() else "down"
    lines.append(("Discord bot", bot_state))
    if daemon_state.monitor_alive is None:
        monitor_state = "not running"
    else:
        monitor_state = "alive" if daemon_state.monitor_alive() else "down"
    lines.append(("UV monitor", monitor_state))

    # (4) Last briefing result (read-only heartbeat read).
    heartbeat = read_heartbeat(daemon_state.db_path)
    lines.append(("Last briefing", _fmt_epoch(heartbeat.get("last_success_utc"))))

    return CommandReply(title="Status", lines=tuple(lines))
