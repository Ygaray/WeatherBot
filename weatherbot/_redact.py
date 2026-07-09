"""Redact the OpenWeather appid (API key) from any surfaced text (HARD-SEC-01).

The ``appid`` travels in the request query string, so httpx's
``raise_for_status()`` message — ``"...for url '<URL with appid=<key>>'"`` — embeds
the secret in the clear. This one pure helper scrubs that value to ``appid=***`` at
both the source raise sites (``weather/client.py``, D-01) and the ``_LiveStderr``
stderr backstop (``__init__.py``, D-02): one function, two callers, belt-and-suspenders.
"""

from __future__ import annotations

import re

# Hub-promotion candidate (OpenWeather-specific for now; see 30-CONTEXT Deferred
# Ideas). Kept app-local — a 4-line regex is not worth a ``_promotable/`` quarantine.
#
# Match ``appid=`` then the value up to (but NOT including) the first delimiter — an
# ``&``, whitespace, quote, angle bracket, or backslash — or end-of-string. Stopping
# at the value boundary means the scrub never eats the following query params, the
# trailing quote, or httpx's MDN link (D-03: endpoint + status stay diagnosable). A
# URL-encoded value (``appid=A%2Fb``) is captured whole (``%``/hex are non-delimiters).
# ``re.IGNORECASE`` so an uppercase ``APPID=`` token is redacted too.
_APPID_RX = re.compile(r"(appid=)[^&\s\"'<>\\]+", re.IGNORECASE)


def redact_appid(text: str) -> str:
    """Replace every ``appid=<value>`` with ``appid=***``, preserving endpoint + status."""
    return _APPID_RX.sub(r"\1***", text)
