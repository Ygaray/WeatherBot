"""The read-only ``status`` command handler (Plan 12-02, CMD-12 / D-02).

``status`` reports the four D-02 sections — next scheduled send per location,
alive + uptime, bot/UV-monitor liveness, and the last-briefing result — by reading
a :class:`~weatherbot.interactive.state.DaemonState`. It is READ-ONLY: it reads the
heartbeat via ``read_heartbeat`` (the only store call, a reader) and never writes
the store, config, or scheduler.
"""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from weatherbot.interactive.commands import CommandReply
from weatherbot.weather.store import read_heartbeat

if TYPE_CHECKING:
    from weatherbot.interactive.state import DaemonState


def _fmt_epoch(epoch: int | None, tz: tzinfo) -> str:
    """Format a Unix-UTC epoch as a humanized local 24-hour ``HH:MM`` clock (D-07).

    Returns ``'none yet'`` when ``None``. Otherwise localizes the Unix-UTC
    ``epoch`` into ``tz`` (the display zone) and renders a bare 24-hour ``HH:MM``
    (e.g. ``'09:00'``) with the raw ISO date and timezone offset dropped — the same
    local convention ``state.next_fires`` applies to "Next send", so both lines on a
    ``!status`` card read in the same (local) zone rather than one local + one UTC.
    Built with an explicit ``%H:%M`` directive (portable — no glibc-only ``%-``
    variant).
    """
    if epoch is None:
        return "none yet"
    return datetime.fromtimestamp(epoch, tz).strftime("%H:%M")


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


def status(daemon_state: DaemonState | None) -> CommandReply:
    """Daemon liveness, next scheduled sends, and last-briefing result (CMD-12).

    Read-only: reports the four D-02 sections from the injected
    :class:`DaemonState`. The UV monitor (Phase 15) reports "alive"/"down" from the
    daemon-supplied ``monitor_alive`` callable (registered ``__uvmonitor__`` job +
    live ``monitor_enabled``); it falls back to "not running" only when no callable is
    supplied (a bot built without a scheduler).

    Degrades gracefully when ``daemon_state`` is ``None`` (WR-04): a bot built
    without a scheduler (the ``build_client``/``build_on_message`` default, and
    several tests) would otherwise call ``None.next_fires()`` → ``AttributeError``,
    which the on_message envelope absorbs into the generic error reply, leaving
    ``!status`` permanently broken. Report a clear "unavailable" reply instead.
    """
    if daemon_state is None:
        return CommandReply(
            title="Status",
            text="Status unavailable — no daemon state (bot started without a scheduler).",
        )

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
    # "Last briefing" is not per-location, so localize to a defensible display zone:
    # the first configured location's tz (the same default F02 default-resolution
    # uses), matching how "Next send" above is localized (D-07). Falls back to UTC
    # when no locations are configured.
    display_locations = daemon_state.holder.current().locations
    display_tz = (
        ZoneInfo(display_locations[0].timezone)
        if display_locations
        else timezone.utc
    )
    heartbeat = read_heartbeat(daemon_state.db_path)
    lines.append(
        ("Last briefing", _fmt_epoch(heartbeat.get("last_success_utc"), display_tz))
    )

    return CommandReply(title="Status", lines=tuple(lines))
