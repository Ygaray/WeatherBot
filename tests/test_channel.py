"""Channel ABC + DiscordWebhookChannel tests (DELV-01/02/03, D-14).

All tests run OFFLINE: ``DiscordWebhook.execute`` is monkeypatched to a fake
response so no real Discord webhook is ever hit. The webhook URL is treated as a
credential and must never appear in a log line or exception (Pitfall 5 / T-04-01).

The load-bearing isolation assertion (DELV-03 / T-04-03): the embed is a
Discord-only enrichment that lives ONLY inside ``send_briefing`` — it must never
be a parameter of the channel-agnostic ``Channel.send(text)`` interface, and a
``Forecast`` must never reach ``send``.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from weatherbot.channels import (
    Channel,
    DeliveryResult,
    DiscordWebhookChannel,
    build_channel,
)


@dataclass
class _FakeForecast:
    """Minimal stand-in carrying only the embed display fields used here."""

    location: str = "New York"
    temp_display: str = "72°F (22°C)"
    high_display: str = "78°F (26°C)"
    low_display: str = "61°F (16°C)"
    rain_chance: int = 10


def _fake_response(status_code: int, text: str = "ok"):
    return SimpleNamespace(status_code=status_code, text=text)


@pytest.fixture
def patch_execute(monkeypatch):
    """Monkeypatch ``DiscordWebhook.execute`` to capture the built webhook offline.

    Returns a one-element list that receives the ``DiscordWebhook`` instance the
    channel built, plus lets the caller control the faked status code.
    """
    import weatherbot.channels.discord as discord_mod

    captured: dict = {"webhook": None, "status": 204, "text": "ok"}

    def fake_execute(self, *args, **kwargs):
        captured["webhook"] = self
        return _fake_response(captured["status"], captured["text"])

    monkeypatch.setattr(
        discord_mod.DiscordWebhook, "execute", fake_execute, raising=True
    )
    return captured


# --- DELV-02: Channel ABC contract -----------------------------------------


def test_channel_is_abc_with_text_only_send():
    assert inspect.isabstract(Channel)
    sig = inspect.signature(Channel.send)
    # send(self, text) — exactly one non-self parameter named "text".
    params = [p for p in sig.parameters if p != "self"]
    assert params == ["text"]
    assert sig.parameters["text"].annotation in (str, "str")


def test_discord_channel_implements_channel_and_returns_result(patch_execute):
    ch = DiscordWebhookChannel(
        "https://discord.test/webhook/secret",
        username="WeatherBot ☀️",
        avatar_url="https://img.test/a.png",
    )
    assert isinstance(ch, Channel)
    result = ch.send("plain text body")
    assert isinstance(result, DeliveryResult)
    assert result.ok is True


# --- DELV-03 / T-04-03: embed isolation ------------------------------------


def test_send_signature_takes_only_text():
    sig = inspect.signature(DiscordWebhookChannel.send)
    params = [p for p in sig.parameters if p != "self"]
    assert params == ["text"]
    # No forecast/embed parameter sneaks into the channel-agnostic interface.
    assert "forecast" not in params
    assert "embed" not in params


def test_send_does_not_attach_an_embed(patch_execute):
    ch = DiscordWebhookChannel("https://discord.test/wh", username="u", avatar_url=None)
    ch.send("body only")
    webhook = patch_execute["webhook"]
    # The plain text path attaches NO embed (embed never crosses send(text)).
    assert webhook.get_embeds() == []


def test_send_briefing_builds_internal_embed(patch_execute):
    ch = DiscordWebhookChannel("https://discord.test/wh", username="u", avatar_url=None)
    result = ch.send_briefing("body", _FakeForecast())
    assert result.ok is True
    webhook = patch_execute["webhook"]
    embeds = webhook.get_embeds()
    assert len(embeds) == 1  # the Discord-only enrichment, built internally


def test_base_module_has_no_embed_reference():
    import weatherbot.channels.base as base_mod

    src = inspect.getsource(base_mod)
    assert "DiscordEmbed" not in src  # interface is embed-free (DELV-03)


# --- D-14: custom identity --------------------------------------------------


def test_webhook_carries_username_and_avatar(patch_execute):
    ch = DiscordWebhookChannel(
        "https://discord.test/wh",
        username="WeatherBot ☀️",
        avatar_url="https://img.test/avatar.png",
    )
    ch.send("hello")
    webhook = patch_execute["webhook"]
    assert webhook.username == "WeatherBot ☀️"
    assert webhook.avatar_url == "https://img.test/avatar.png"


# --- expected-failure path: non-2xx -> DeliveryResult(ok=False) -------------


def test_non_2xx_returns_failure_not_raise(patch_execute):
    patch_execute["status"] = 404
    patch_execute["text"] = "not found"
    ch = DiscordWebhookChannel("https://discord.test/wh", username="u", avatar_url=None)
    result = ch.send("body")  # must NOT raise
    assert result.ok is False
    assert result.detail  # carries some diagnostic detail


# --- T-04-01: the webhook URL (a credential) never leaks --------------------


def test_failure_detail_does_not_leak_webhook_url(patch_execute):
    patch_execute["status"] = 500
    patch_execute["text"] = "server error"
    secret_url = "https://discord.com/api/webhooks/123/SUPER-SECRET-TOKEN"
    ch = DiscordWebhookChannel(secret_url, username="u", avatar_url=None)
    result = ch.send("body")
    assert "SUPER-SECRET-TOKEN" not in result.detail
    assert secret_url not in result.detail


def test_no_log_record_contains_the_webhook_url(patch_execute, caplog):
    secret_url = "https://discord.com/api/webhooks/123/SUPER-SECRET-TOKEN"
    ch = DiscordWebhookChannel(secret_url, username="u", avatar_url=None)
    with caplog.at_level(logging.DEBUG):
        ch.send("body")
        patch_execute["status"] = 500
        ch.send("body again")
    for record in caplog.records:
        assert "SUPER-SECRET-TOKEN" not in record.getMessage()
        assert secret_url not in record.getMessage()


# --- factory / registry -----------------------------------------------------


def test_build_channel_builds_discord_with_identity():
    config = SimpleNamespace(
        webhook=SimpleNamespace(
            username="WeatherBot ☀️", avatar_url="https://img.test/a.png"
        )
    )
    settings = SimpleNamespace(discord_webhook_url="https://discord.test/wh")
    ch = build_channel(config, settings)
    assert isinstance(ch, DiscordWebhookChannel)
    assert isinstance(ch, Channel)
    assert ch.name == "discord"
