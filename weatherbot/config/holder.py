"""App-side re-export shim — ``ConfigHolder`` now lives in :mod:`yahir_reusable_bot.config` (D-02).

The generic ``ConfigHolder[T]`` was lifted into the reusable module in Plan 24-01. This shim
re-exports it from there so every existing ``from weatherbot.config.holder import ConfigHolder``
importer (``scheduler.daemon``, ``scheduler.uvmonitor``, ``cli``, the ``interactive.*`` modules,
plus ``test_config_holder`` and the other test importers) — and the Phase-21 pins that depend on
it — stays byte-identical, resolving to the IDENTICAL class object
(``weatherbot.config.holder.ConfigHolder is yahir_reusable_bot.config.ConfigHolder``).
"""

from yahir_reusable_bot.config import ConfigHolder

__all__ = ["ConfigHolder"]
