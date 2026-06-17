"""Shared brand constants used across delivery surfaces (IN-03).

The briefing brand color is referenced by BOTH the webhook channel
(``discord-webhook`` wants the hex *string* ``"03b2f8"``) and the inbound gateway
bot (``discord.py``'s :class:`discord.Embed` wants the *int* ``0x03B2F8``). Define
it once here and derive both forms so a brand-color change is a single edit that
can never drift between the two modules.
"""

from __future__ import annotations

# Single source of truth for the briefing brand color (hex, no leading ``#``).
BRIEFING_COLOR_HEX = "03b2f8"

# Derived forms — never hand-write these literals elsewhere.
BRIEFING_COLOR_INT = int(BRIEFING_COLOR_HEX, 16)
