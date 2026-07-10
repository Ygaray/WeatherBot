"""The Discord webhook channel — the one v1 delivery implementation (DELV-01).

``DiscordWebhookChannel.send(text)`` posts the canonical plain-text body through
the channel-agnostic interface (DELV-02). ``send_briefing(text, forecast)`` is a
Discord-ONLY extra that additionally builds a rich embed from the same forecast
(D-13) and attaches it — the embed lives only here and never crosses the
``send(text)`` interface (DELV-03 / Pitfall 3 / T-04-03).

Both paths funnel through the private ``_post(text, embed)``, which maps the
webhook's HTTP status to a :class:`DeliveryResult`. A non-2xx response is an
*expected* failure (``ok=False``), not a raised exception. The webhook URL is a
bearer credential (T-04-01): it is stored privately, never logged, and never put
into a ``DeliveryResult.detail``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from discord_webhook import DiscordEmbed, DiscordWebhook
from requests.exceptions import RequestException

from weatherbot.branding import BRIEFING_COLOR_HEX

from .base import Channel, DeliveryResult

if TYPE_CHECKING:
    from weatherbot.weather.models import Forecast

_log = logging.getLogger(__name__)

# DELIV-04 (D-04): a permanent Discord send-auth failure (401/403) is surfaced as
# an ``httpx.HTTPStatusError`` so ``fire_slot``'s existing ``except
# httpx.HTTPStatusError`` arm (daemon.py:263) classifies it via ``is_auth_failure``
# → ``auth_failed`` and short-circuits the two-burst retry in ~1 attempt (rather
# than burning the full ~65-min schedule as ``transient_exhausted``). The carrier
# reuses the Phase-30 ``.response``-carrying type contract and, per T-31-07 / ASVS
# V7, is built with a REDACTED placeholder URL — the real webhook token must NEVER
# reach the exception message, ``str(exc)``, or a logged traceback.
_AUTH_STATUSES = frozenset({401, 403})
_REDACTED_WEBHOOK_URL = "https://discord/redacted"

# discord-webhook posts via the ``requests`` library; its logger can emit the
# full webhook URL (a credential) at INFO. Raise it to WARNING so the URL cannot
# leak into logs (Pitfall 5 / T-04-01).
logging.getLogger("discord_webhook").setLevel(logging.WARNING)


class DiscordWebhookChannel(Channel):
    """Deliver a briefing to a Discord incoming webhook (D-13/D-14)."""

    name = "discord"

    def __init__(self, webhook_url: str, username: str, avatar_url: str | None) -> None:
        # ``_url`` is a credential — kept private, never logged/echoed.
        self._url = webhook_url
        self._username = username
        self._avatar = avatar_url

    def send(self, text: str) -> DeliveryResult:
        """Channel-agnostic path: post the plain-text body only (DELV-03)."""
        return self._post(text, embed=None)

    def send_briefing(self, text: str, forecast: Forecast) -> DeliveryResult:
        """Discord-only path: post the text PLUS an internally-built embed (D-13).

        The embed is constructed here from the forecast and never travels through
        the channel-agnostic ``send(text)`` interface.
        """
        embed = DiscordEmbed(
            title=f"Weather — {forecast.location}", color=BRIEFING_COLOR_HEX
        )
        embed.add_embed_field(name="Now", value=forecast.temp_display)
        embed.add_embed_field(
            name="High / Low",
            value=f"{forecast.high_display} / {forecast.low_display}",
        )
        embed.add_embed_field(name="Rain", value=f"{forecast.rain_chance}%")
        embed.set_timestamp()
        return self._post(text, embed=embed)

    def _post(self, text: str, embed: DiscordEmbed | None) -> DeliveryResult:
        """POST the webhook, mapping the HTTP status to a DeliveryResult.

        Never raises on a non-2xx response and never includes the webhook URL in
        the returned ``detail`` (credential hygiene — T-04-01).
        """
        webhook = DiscordWebhook(
            url=self._url,
            content=text,
            username=self._username,
            avatar_url=self._avatar,
            rate_limit_retry=True,  # honor Discord 429s
        )
        if embed is not None:
            webhook.add_embed(embed)

        # A network-level failure (DNS/connection/timeout) raises rather than
        # returning a non-2xx response. Map it to ``ok=False`` so the docstring's
        # "never raises" contract holds and a transient blip can't crash the send.
        # The detail carries the EXCEPTION CLASS NAME ONLY — never the URL/secret.
        try:
            response = webhook.execute()  # normally a requests.Response
        except RequestException as exc:
            _log.warning("discord delivery error type=%s", type(exc).__name__)
            return DeliveryResult(ok=False, detail=type(exc).__name__)

        # ``execute`` can return None (or a list, for multi-part sends); guard
        # before reading ``.status_code`` so a missing response is a clean
        # failure, not an AttributeError.
        status = getattr(response, "status_code", None)
        if status is None:
            _log.warning("discord delivery error type=NoResponse")
            return DeliveryResult(ok=False, detail="NoResponse")

        ok = 200 <= status < 300
        if ok:
            _log.info("discord delivery ok status=%s", status)
            return DeliveryResult(ok=True)

        # DELIV-04 (D-04): a 401/403 is a PERMANENT auth misconfiguration (revoked
        # webhook), not a transient blip. RAISE an ``httpx.HTTPStatusError`` whose
        # ``.response.status_code`` is a plain int so the hub ``is_auth_failure``
        # classifier (which reads ONLY ``.response.status_code``) maps it to
        # ``auth_failed`` and the retry short-circuits in ~1 attempt (daemon.py:263).
        # The request/response are synthesized with a REDACTED placeholder URL and a
        # status-only message — the real webhook token (``self._url``) is NEVER passed
        # in, so it can't leak into ``str(exc)`` or a traceback (T-04-01 / T-31-07 /
        # ASVS V7). Every OTHER non-2xx (429/5xx/…) keeps the never-raise contract.
        if status in _AUTH_STATUSES:
            _log.warning("discord delivery auth-failed status=%s", status)
            request = httpx.Request("POST", _REDACTED_WEBHOOK_URL)
            resp = httpx.Response(status, request=request)
            raise httpx.HTTPStatusError(
                f"discord auth failure {status}", request=request, response=resp
            )

        # Failure detail carries the status + a short body snippet ONLY — never
        # the webhook URL.
        snippet = (response.text or "")[:200]
        _log.warning("discord delivery failed status=%s", status)
        return DeliveryResult(ok=False, detail=f"{status} {snippet}")
