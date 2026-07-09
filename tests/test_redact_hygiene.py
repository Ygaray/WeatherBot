"""Regression suite for HARD-SEC-01 — the OpenWeather ``appid`` must never leak.

Proves the API key is absent from ``str(exc)``, the FULL traceback (as
``_log.exception`` renders it), and captured stderr on all three leak paths
(One Call fetch, geocode, Discord ``on_message``), plus a ``.response.status_code``
type-contract canary and the ``redact_appid`` boundary behavior (D-03: endpoint +
status stay visible).

CRITICAL — capture mechanism: use ``capsys``, NEVER the stdlib-log-record capture
fixture. The project logs through ``structlog.PrintLoggerFactory(file=_LiveStderr())``,
which bypasses stdlib logging entirely, so that fixture captures 0 records (RESEARCH
Pitfall 2). The ``_LiveStderr`` proxy resolves ``sys.stderr`` lazily per write, so
``capsys``'s per-test stream swap sees the rendered event + traceback.
"""

from __future__ import annotations

import traceback

import httpx
import pytest

from weatherbot._redact import redact_appid
from weatherbot.config.models import Location
from weatherbot.weather import client

# A fake sentinel key — the value that must never survive redaction anywhere. Reused
# by every test in this module (helper boundaries + all three leak paths).
SENTINEL = "SENTINELKEY_do_not_leak_123"

# A location built exactly as tests/test_client.py:21 does (offline; never geocoded).
_LOC = Location(name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York")


def _install_mock(monkeypatch, handler):
    """Patch httpx.Client so every request is served by ``handler`` (offline).

    Copied from tests/test_client.py:25-35 — no network, no live gateway.
    """
    real_init = httpx.Client.__init__

    def fake_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", fake_init)


def _401_handler(request: httpx.Request) -> httpx.Response:
    """A 401 whose request URL carries ``appid=<SENTINEL>`` (the leak source)."""
    return httpx.Response(
        401, request=request, json={"cod": 401, "message": "Invalid API key"}
    )


def test_redact_helper_boundaries():
    """D-03 / Pitfall 3: ``redact_appid`` replaces only the key VALUE with ``***``,
    stopping at the first delimiter so following params, the trailing quote, and the
    endpoint/status the daemon needs all survive. Also case-insensitive."""
    # (1) The real raise_for_status message form: params after appid must survive.
    real = f"for url 'x?lat=1&appid={SENTINEL}&units=imperial'"
    out = redact_appid(real)
    assert SENTINEL not in out
    assert "appid=***" in out
    assert "units=imperial" in out  # D-03: following params preserved

    # (2) Stops at the '&' — the next param is intact.
    out2 = redact_appid(f"appid={SENTINEL}&next=1")
    assert out2 == "appid=***&next=1"

    # (3) URL-encoded value: the %XX is part of the captured value, stops at '&'.
    out3 = redact_appid("appid=A%2Fdef&units=x")
    assert out3 == "appid=***&units=x"

    # (4) Quote-terminated (as httpx's message ends the URL): stops at the "'".
    out4 = redact_appid(f"...appid={SENTINEL}'")
    assert out4 == "...appid=***'"

    # (5) Case-insensitive: an uppercase APPID= token is also redacted.
    out5 = redact_appid(f"APPID={SENTINEL}&units=x")
    assert SENTINEL not in out5
    assert "units=x" in out5


def test_onecall_failure_redacts_key_and_keeps_status(monkeypatch):
    """D-01 leak path 1 + HARD constraint: a 401 from ``fetch_onecall`` re-raises a
    REDACTED ``httpx.HTTPStatusError``. The sentinel is absent from ``str(exc)`` AND
    from the FULL traceback (as ``_log.exception`` renders it — the guard that catches
    a missing ``from None``), while ``.response.status_code`` stays readable and the
    type stays ``HTTPStatusError`` (6+ downstream branches unchanged)."""
    _install_mock(monkeypatch, _401_handler)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        client.fetch_onecall(_LOC, key=SENTINEL)
    exc = ei.value

    # Type-contract canary (LOCKED): type + .response.status_code preserved.
    assert type(exc).__name__ == "HTTPStatusError"
    assert exc.response.status_code == 401

    # The key is gone from the message ...
    assert SENTINEL not in str(exc)
    # ... AND from the full traceback (Pitfall 1: without `from None` the key-bearing
    # original still prints through the __context__ chain). This is the load-bearing
    # assertion that a missing `from None` would fail.
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert SENTINEL not in tb


def test_geocode_failure_redacts_key(monkeypatch):
    """D-01 leak path 2: a 401 from ``geocode`` re-raises the same redacted,
    type-preserving ``httpx.HTTPStatusError`` — sentinel absent from ``str(exc)``,
    ``.response.status_code`` still readable."""
    _install_mock(monkeypatch, _401_handler)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        client.geocode("Paris", key=SENTINEL)
    exc = ei.value
    assert SENTINEL not in str(exc)
    assert exc.response.status_code == 401


_OPERATOR_ID = 12345


def _run(coro):
    """Drive a coroutine to completion (no live gateway) — the test_bot.py idiom
    (NOT ``@pytest.mark.asyncio``; the repo drives coroutines with ``asyncio.run``)."""
    import asyncio

    return asyncio.run(coro)


class _FakeHolder:
    """Minimal ConfigHolder stand-in — ``current()`` returns a sentinel config."""

    def current(self):
        return object()


def test_discord_on_message_does_not_dump_key(fake_discord_message, monkeypatch, capsys):
    """D-02 / F12 end-to-end: a failing ``!weather <loc>`` over Discord lets the
    ``except Exception: _log.exception(...)`` envelope (bot.py:507) render the FULL
    traceback to stderr. Prove (a) the source-fixed path is clean AND (b) the
    ``_LiveStderr`` backstop independently scrubs a RAW un-redacted ``appid=<SENTINEL>``
    log line — proving option-(a) catches even a future/forgotten source leak.

    Uses ``capsys`` (NEVER the stdlib-log-record capture fixture — ``PrintLoggerFactory``
    bypasses stdlib logging, Pitfall 2). The test does NOT call ``cli._configure_logging``
    (Assumption A2), so ``_log`` routes through the package-default ``_LiveStderr``.
    """
    from weatherbot.interactive import bot

    # (a) Drive on_message so the reply path raises a key-bearing HTTPStatusError. The
    # whole registry dispatch runs inside the non-propagating envelope: monkeypatch
    # dispatch_spec (imported at bot module top) to raise BEFORE any real lookup.
    request = httpx.Request("GET", f"https://api.openweathermap.org/x?appid={SENTINEL}")
    response = httpx.Response(401, request=request)
    leaky = httpx.HTTPStatusError(
        f"Client error '401' for url 'https://api.openweathermap.org/x?appid={SENTINEL}'",
        request=request,
        response=response,
    )

    async def _boom(*args, **kwargs):
        raise leaky

    monkeypatch.setattr(bot, "dispatch_spec", _boom, raising=True)

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!weather home"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=object()
    )
    # The envelope swallows the exception (CMD-08 — must not re-raise).
    _run(handler(msg))

    err = capsys.readouterr().err
    # The full traceback that _log.exception rendered to stderr carries NO key value.
    assert SENTINEL not in err

    # (b) Backstop independence: emit a RAW un-redacted appid=<SENTINEL> log line
    # through the package logger (as a future/forgotten call site might) and prove the
    # _LiveStderr.write backstop scrubs it — even though nothing redacted it at source.
    import structlog

    structlog.get_logger(__name__).error(
        "future leak", url=f"https://api.openweathermap.org/x?appid={SENTINEL}&units=x"
    )
    err2 = capsys.readouterr().err
    assert SENTINEL not in err2  # backstop caught the raw un-redacted leak
    assert "appid=***" in err2  # scrubbed to the placeholder (D-03)
