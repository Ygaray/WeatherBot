"""Config hot-reload surface: the generic holder cell + the reload-orchestration engine.

Exports :class:`ConfigHolder` (a lock-free-read / locked-swap cell over an app-defined
config type ``T``) and :class:`ReloadEngine` (validate -> atomic-swap -> job-reconcile with
all-or-nothing rollback, a flag-set/service-pending trigger pair, an engine-owned file-watch
thread, and best-effort applied/rejected hooks). Every per-app specific (the config type, the
validator, the job-deriver/registrar, the side effects) is injected, so a different bot reuses
the whole engine with zero app assumptions.
"""

from __future__ import annotations

from .holder import ConfigHolder
from .reload import ReloadEngine

__all__ = ["ConfigHolder", "ReloadEngine"]
