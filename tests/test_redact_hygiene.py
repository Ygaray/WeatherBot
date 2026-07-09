"""Regression suite for HARD-SEC-01 — the OpenWeather ``appid`` must never leak.

Proves the API key is absent from ``str(exc)``, the FULL traceback (as
``_log.exception`` renders it), and captured stderr on all three leak paths
(One Call fetch, geocode, Discord ``on_message``), plus a ``.response.status_code``
type-contract canary and the ``redact_appid`` boundary behavior (D-03: endpoint +
status stay visible).

CRITICAL — capture mechanism: use ``capsys``, NEVER ``caplog``. The project logs
through ``structlog.PrintLoggerFactory(file=_LiveStderr())``, which bypasses stdlib
logging entirely, so ``caplog`` captures 0 records (RESEARCH Pitfall 2). The
``_LiveStderr`` proxy resolves ``sys.stderr`` lazily per write, so ``capsys``'s
per-test stream swap sees the rendered event + traceback.
"""

from __future__ import annotations

import traceback

import httpx
import pytest

from weatherbot._redact import redact_appid

# A fake sentinel key — the value that must never survive redaction anywhere. Reused
# by every test in this module (helper boundaries + all three leak paths).
SENTINEL = "SENTINELKEY_do_not_leak_123"


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
