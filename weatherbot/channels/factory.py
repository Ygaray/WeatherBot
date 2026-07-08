"""Channel factory: build a :class:`Channel` from config + secrets (DELV-02).

``build_channel`` selects the provider by a ``"type"`` key (default ``"discord"``)
from a small registry dict — adding SMS/Telegram later is one registry entry plus
a constructor, with no change to the composition root. The Discord webhook URL is
a secret and is read from ``Settings`` (CONF-02), while the display identity
(username + avatar) is non-secret config (D-14).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .base import Channel
from .discord import DiscordWebhookChannel

if TYPE_CHECKING:
    from weatherbot.config.models import Config
    from weatherbot.config.settings import Settings


def _build_discord(config: Config | None, settings: Settings) -> Channel:
    # Only ``settings.discord_webhook_url`` (the secret) is needed to send; the
    # config supplies the NON-secret display identity. On the fatal-boot path
    # (WR-01) the config failed to load and ``config`` is ``None`` — fall back to
    # a default identity so the operator still gets the Discord fatal alert
    # instead of an AttributeError swallowed by the best-effort caller.
    username = config.webhook.username if config is not None else "WeatherBot"
    avatar_url = config.webhook.avatar_url if config is not None else None
    return DiscordWebhookChannel(settings.discord_webhook_url, username, avatar_url)


# Registry of provider builders keyed by config "type". Add SMS/Telegram here.
_REGISTRY: dict[str, Callable[["Config | None", "Settings"], Channel]] = {
    "discord": _build_discord,
}

DEFAULT_TYPE = "discord"


def build_channel(
    config: Config | None, settings: Settings, *, channel_type: str | None = None
) -> Channel:
    """Construct the configured delivery channel.

    ``channel_type`` defaults to ``"discord"`` (the only v1 provider). Raises
    ``ValueError`` for an unknown type so a misconfiguration fails loud.

    ``config`` may be ``None`` on the fatal-boot path (``_fatal_config_exit``),
    where the config failed to load: the display identity then falls back to
    defaults while the webhook URL is still read from ``settings`` (WR-01).
    """
    selected = channel_type or DEFAULT_TYPE
    try:
        builder = _REGISTRY[selected]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown channel type {selected!r}; known types: {known}"
        ) from None
    return builder(config, settings)
