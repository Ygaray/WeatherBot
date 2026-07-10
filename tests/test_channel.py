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


def test_base_send_briefing_defaults_to_send_text():
    # WR-05: a non-Discord channel that implements only the text-only ``send``
    # gets a ``send_briefing`` (from the ABC) that delegates to ``send(text)``,
    # so the composition root can dispatch explicitly without duck-typing.
    class _TextOnlyChannel(Channel):
        name = "textonly"

        def __init__(self):
            self.sent: list[str] = []

        def send(self, text: str) -> DeliveryResult:
            self.sent.append(text)
            return DeliveryResult(ok=True)

    ch = _TextOnlyChannel()
    result = ch.send_briefing("body", forecast=_FakeForecast())
    assert result.ok is True
    # Delegated to the text-only seam; no embed/forecast crossed send().
    assert ch.sent == ["body"]


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


# --- DELIV-04 (HARD-DELIV-04, D-04): 401/403 -> raise httpx.HTTPStatusError --


@pytest.mark.parametrize("status", [401, 403])
def test_auth_status_raises_httpx_status_error(patch_execute, status):
    """A 401/403 is a PERMANENT auth failure: ``_post`` RAISES an
    ``httpx.HTTPStatusError`` whose ``.response.status_code`` is a plain int, so the
    daemon's ``is_auth_failure`` classifier maps it to ``auth_failed`` and the retry
    short-circuits (rather than returning ok=False and burning the schedule)."""
    import httpx

    patch_execute["status"] = status
    patch_execute["text"] = "Unauthorized"
    ch = DiscordWebhookChannel("https://discord.test/wh", username="u", avatar_url=None)

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        ch.send("body")

    exc = excinfo.value
    assert exc.response is not None
    assert exc.response.status_code == status
    assert isinstance(exc.response.status_code, int)


@pytest.mark.parametrize("status", [429, 500, 502, 400, 404])
def test_non_auth_non_2xx_still_returns_failure_not_raise(patch_execute, status):
    """The never-raise contract NARROWS for auth only: every OTHER non-2xx
    (transient 429/5xx, and the non-auth 4xx 400/404) still returns
    ``DeliveryResult(ok=False)`` and does NOT raise (DELIV-04 scope guard)."""
    patch_execute["status"] = status
    patch_execute["text"] = "boom"
    ch = DiscordWebhookChannel("https://discord.test/wh", username="u", avatar_url=None)
    result = ch.send("body")  # must NOT raise
    assert result.ok is False
    assert result.detail


@pytest.mark.parametrize("status", [401, 403])
def test_auth_raise_carries_no_webhook_token(patch_execute, status):
    """T-31-07 / ASVS V7: the synthesized ``httpx.HTTPStatusError`` for a 401/403
    carries a REDACTED placeholder URL and a status-only message — the real webhook
    token must NEVER appear in ``str(exc)``, the request URL, or the response URL."""
    import httpx

    patch_execute["status"] = status
    patch_execute["text"] = "Forbidden"
    secret_url = "https://discord.com/api/webhooks/123/SUPER-SECRET-TOKEN"
    ch = DiscordWebhookChannel(secret_url, username="u", avatar_url=None)

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        ch.send("body")

    exc = excinfo.value
    # No webhook token anywhere in the exception's text or its request/response URLs.
    assert "SUPER-SECRET-TOKEN" not in str(exc)
    assert secret_url not in str(exc)
    assert "SUPER-SECRET-TOKEN" not in str(exc.request.url)
    assert "SUPER-SECRET-TOKEN" not in str(exc.response.request.url)


def test_auth_raise_logs_no_webhook_token(patch_execute, caplog):
    """The 401/403 warning log line (like every other _post log) carries the status
    only — never the webhook token (T-04-01 parity for the auth branch)."""
    import httpx

    patch_execute["status"] = 401
    secret_url = "https://discord.com/api/webhooks/123/SUPER-SECRET-TOKEN"
    ch = DiscordWebhookChannel(secret_url, username="u", avatar_url=None)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(httpx.HTTPStatusError):
            ch.send("body")
    for record in caplog.records:
        assert "SUPER-SECRET-TOKEN" not in record.getMessage()
        assert secret_url not in record.getMessage()


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


# --- WR-02: network-level failures don't escape send() ----------------------


def test_network_error_returns_failure_not_raise(monkeypatch):
    # A connection/DNS error raises from execute(); send() must map it to
    # ok=False (honoring the "never raises" contract), not propagate it.
    import weatherbot.channels.discord as discord_mod
    from requests.exceptions import ConnectionError as ReqConnectionError

    def boom(self, *args, **kwargs):
        raise ReqConnectionError("Failed to establish a new connection")

    monkeypatch.setattr(discord_mod.DiscordWebhook, "execute", boom, raising=True)
    ch = DiscordWebhookChannel("https://discord.test/wh", username="u", avatar_url=None)
    result = ch.send("body")  # must NOT raise
    assert result.ok is False
    assert result.detail  # carries a diagnostic (the exception class name)


def test_network_error_detail_carries_no_secret(monkeypatch):
    # The error detail must be the exception CLASS NAME only — never the URL
    # (a bearer credential) or any token within it (T-04-01).
    import weatherbot.channels.discord as discord_mod
    from requests.exceptions import ConnectionError as ReqConnectionError

    secret_url = "https://discord.com/api/webhooks/123/SUPER-SECRET-TOKEN"

    def boom(self, *args, **kwargs):
        # Even if the underlying error text echoed the URL, it must not leak.
        raise ReqConnectionError(f"could not connect to {secret_url}")

    monkeypatch.setattr(discord_mod.DiscordWebhook, "execute", boom, raising=True)
    ch = DiscordWebhookChannel(secret_url, username="u", avatar_url=None)
    result = ch.send("body")
    assert result.ok is False
    assert "SUPER-SECRET-TOKEN" not in result.detail
    assert secret_url not in result.detail
    assert result.detail == "ConnectionError"


def test_none_response_returns_failure(monkeypatch):
    # execute() can return None (e.g. some multi-part paths); guard before
    # reading .status_code so it's a clean failure, not an AttributeError.
    import weatherbot.channels.discord as discord_mod

    monkeypatch.setattr(
        discord_mod.DiscordWebhook,
        "execute",
        lambda self, *a, **k: None,
        raising=True,
    )
    ch = DiscordWebhookChannel("https://discord.test/wh", username="u", avatar_url=None)
    result = ch.send("body")  # must NOT raise
    assert result.ok is False
    assert result.detail


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


# --- WR-01: the fatal-boot path builds the channel with config=None ---------
# ``_fatal_config_exit`` (cli.py) calls ``build_channel(None, settings)`` when the
# config failed to load, so the Discord fatal alert can still fire. Previously
# ``_build_discord`` dereferenced ``config.webhook`` and raised AttributeError,
# which the best-effort caller swallowed — the operator never got the Discord
# alert on the PRIMARY fatal path (D-07/D-08). This is the tight factory-level
# guard for that regression; the cli tests stub ``build_channel`` and so never
# exercised the real factory here.


def test_build_channel_none_config_uses_settings_and_default_identity(patch_execute):
    settings = SimpleNamespace(discord_webhook_url="https://discord.test/fatal-wh")
    # Must NOT raise (was AttributeError on None.webhook before the fix).
    ch = build_channel(None, settings)
    assert isinstance(ch, DiscordWebhookChannel)
    assert isinstance(ch, Channel)
    # The webhook URL is still sourced from settings (the only thing needed to send).
    ch.send("fatal alert body")
    webhook = patch_execute["webhook"]
    assert webhook.url == "https://discord.test/fatal-wh"
    # Falls back to the default "WeatherBot" display identity (no config).
    assert webhook.username == "WeatherBot"
    assert webhook.avatar_url is None
