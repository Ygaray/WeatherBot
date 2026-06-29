"""The reusable Discord *adapter* — gateway + persistent-view machinery (SEAM-07).

The adapter layer one level up from the channel-agnostic core (SMS/Slack have no
buttons, so this is not core plumbing). Exports the generic, weather-noun-free Discord
plumbing an app wires its own cosmetics + ``render`` into:

- :class:`SelectedContext` — the generic ``[I]`` holder for the panel's selected item
  (WeatherBot uses ``SelectedContext[str]``).
- :class:`PanelKit` — the persistent-view machinery + registry-derived command buttons +
  ownership test + clone path; ``marker`` / ``render`` / ``contributors`` are injected.
- :class:`BotThread` + :func:`build_client` — the gateway thread+own-loop + persistent-view
  registration + the create-before-delete summon orchestration.

Every name re-exported here is generic adapter vocabulary; the module contains NO weather
concept (no location/forecast/openweather/uv/briefing) and no ``wb:`` literal — the app
supplies those at the composition root (Phase-25 ``build_runtime``).
"""

from __future__ import annotations

from yahir_reusable_bot.discord.selection import SelectedContext

# NOTE: ``PanelKit`` (Task 2) and ``BotThread`` / ``build_client`` (Task 3) join the barrel
# as they land. The end-state ``__all__`` is the full adapter surface.
__all__ = ["SelectedContext"]
