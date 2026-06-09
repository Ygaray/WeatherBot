"""Pluggable delivery channels (DELV-01/02/03).

The channel-agnostic :class:`Channel` ABC + :class:`DeliveryResult`, the one v1
implementation :class:`DiscordWebhookChannel` (with its embed kept internal), and
the :func:`build_channel` factory that selects a provider by config.
"""

from .base import Channel, DeliveryResult
from .discord import DiscordWebhookChannel
from .factory import build_channel

__all__ = [
    "Channel",
    "DeliveryResult",
    "DiscordWebhookChannel",
    "build_channel",
]
