"""The reusable Discord *adapter* — gateway + persistent-view machinery (SEAM-07).

The adapter layer one level up from the channel-agnostic core (SMS/Slack have no
buttons, so this is not core plumbing). Exports the generic, domain-agnostic Discord
plumbing an app wires its own cosmetics + ``render`` into:

- :class:`SelectedContext` — the generic ``[I]`` holder for the panel's selected item
  (an app parameterizes it with its own item type, e.g. ``SelectedContext[str]``).
- :class:`PanelKit` — the persistent-view machinery + registry-derived command buttons +
  ownership test + clone path; ``marker`` / ``render`` / ``contributors`` are injected.
- :class:`BotThread` + :func:`build_client` — the gateway thread+own-loop + persistent-view
  registration + the create-before-delete summon orchestration.

Every name re-exported here is generic adapter vocabulary; the module names no app domain
concept and bakes no marker literal of its own — the app supplies those at its composition
root (the Phase-25 ``build_runtime``).
"""

from __future__ import annotations

from yahir_reusable_bot.discord.gateway import BotThread, build_client
from yahir_reusable_bot.discord.panelkit import PanelKit
from yahir_reusable_bot.discord.selection import SelectedContext

__all__ = ["BotThread", "build_client", "PanelKit", "SelectedContext"]
