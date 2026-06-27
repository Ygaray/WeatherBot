"""The channel-agnostic delivery seam (DELV-02).

``Channel`` is the pluggable interface every delivery provider implements. Its
single ``send(text: str) -> DeliveryResult`` method takes the canonical plain-text
briefing body and nothing else — the exact text path SMS/Telegram will reuse
later (D-12). Provider-specific enrichment (e.g. the Discord embed) must NOT
appear in this interface: keeping ``send`` text-only is what keeps delivery
pluggable and prevents Discord details leaking into the seam (DELV-03 / T-04-03).

This module deliberately knows nothing about Discord, embeds, or webhooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DeliveryResult:
    """Outcome of a delivery attempt.

    An *expected* failure (e.g. a non-2xx provider response) is reported as
    ``ok=False`` with a human-readable ``detail`` — it is NOT raised as an
    exception, so the orchestration layer can decide whether to retry/alert.
    ``detail`` must never carry a credential (the webhook URL / API key).
    """

    ok: bool
    detail: str = ""


class Channel(ABC):
    """A pluggable delivery provider (DELV-02).

    Subclasses set the class attribute ``name`` (the registry key) and implement
    ``send``. The interface is intentionally text-only.
    """

    #: Registry key for this provider (e.g. ``"discord"``).
    name: str = "channel"

    @abstractmethod
    def send(self, text: str) -> DeliveryResult:
        """Deliver the canonical plain-text briefing body."""
        raise NotImplementedError
