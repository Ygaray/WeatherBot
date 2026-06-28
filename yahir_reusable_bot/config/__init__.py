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

# NOTE: ``from .reload import ReloadEngine`` is added in Task 2 of this same plan (24-01),
# once ``reload.py`` lands — see the barrel-completion edit there. Splitting the import this
# way keeps each task's commit independently green (Task 1's holder test can resolve the
# barrel before the engine module exists). The final barrel exports both symbols.
__all__ = ["ConfigHolder"]
