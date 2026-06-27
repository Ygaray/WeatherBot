"""App-side channel shim over the channel-agnostic seam (DELV-02).

The clean, text-only ``Channel`` ABC (``send(text) -> DeliveryResult``) and the
``DeliveryResult`` dataclass now live in :mod:`yahir_reusable_bot.channels` — the
reusable, weather-agnostic module surface (D-03). This shim re-exports them so
every existing ``from weatherbot.channels(.base) import Channel, DeliveryResult``
importer stays byte-identical, and it re-homes the APP-side ``send_briefing``
default here:

``Channel`` exported from this module is a briefing-capable *subclass* of the
module's text-only ``Channel`` (so ``isinstance(ch, Channel)`` keeps testing the
ONE true class — Pitfall 3). It re-adds the default
``send_briefing(text, forecast) -> self.send(text)`` so the composition root can
dispatch explicitly without duck-typing, and a non-Discord channel needs no
override. The ``Forecast`` annotation import lives APP-side here so it does NOT
re-introduce a module → app import edge (D-03 / T-22-04).

This module deliberately carries no embed reference — embed enrichment stays
Discord-internal in :mod:`weatherbot.channels.discord` (DELV-03).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yahir_reusable_bot.channels import Channel as _BaseChannel
from yahir_reusable_bot.channels import DeliveryResult

if TYPE_CHECKING:
    from weatherbot.weather.models import Forecast

__all__ = ["Channel", "DeliveryResult"]


class Channel(_BaseChannel):
    """App-side, briefing-capable :class:`Channel` (IS-A the module's ``Channel``).

    Adds the default ``send_briefing`` over the text-only seam so the composition
    root dispatches explicitly. ``DiscordWebhookChannel`` overrides ``send_briefing``
    to attach its embed, which stays Discord-internal and never crosses
    ``send(text)``.
    """

    def send_briefing(self, text: str, forecast: Forecast) -> DeliveryResult:
        """Deliver the briefing, optionally with provider-specific enrichment.

        The composition root calls this for every channel so dispatch is explicit
        (not duck-typed on attribute presence). The default delegates to the
        text-only ``send`` — the channel-agnostic seam — so a non-Discord channel
        needs no override. ``DiscordWebhookChannel`` overrides this to attach its
        embed, which stays Discord-internal and never crosses ``send(text)``.
        """
        return self.send(text)
