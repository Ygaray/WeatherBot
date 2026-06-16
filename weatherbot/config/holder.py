"""The ``ConfigHolder`` — single owner of the live, immutable ``Config`` (D-04).

This module gives the daemon one mutable cell that holds a reference to the
current frozen ``Config`` snapshot. Every live job reads the *reference*, so a
single ``replace(new_config)`` changes what all jobs render next — that is the
seam the whole hot-reload milestone rests on.

Concurrency contract:

- ``current()`` is **lock-free**. It is a single ``LOAD_ATTR`` bytecode, which
  is atomic under the GIL against the single ``STORE_ATTR`` in ``replace()``.
  A reader therefore always observes the OLD or the NEW *whole* ``Config`` —
  never a torn or partial one. (Proven by ``test_concurrent_read_swap_safe``.)
- ``replace(new_config)`` takes a plain non-reentrant lock (no re-entrant
  acquire is needed) that **serializes writers** and gives Phase 9 a single
  place to later hang an atomic check-then-swap.

What this holder deliberately does NOT do:

- It does **NOT check** ``new_config`` in ``replace()``. The check-before-swap
  boundary is Phase 9 / CFG-04 territory and is explicitly deferred — here
  ``replace()`` only rebinds.
- It does **NOT** record anything, copy, or clone. Snapshots are already
  frozen, so the shared reference is safe to hand out as-is.
- It owns a ``Config`` ONLY. The secrets object / ``.env`` never enters the
  holder (Pitfall #12 — secrets live behind the restart boundary).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weatherbot.config.models import Config


class ConfigHolder:
    """Owns one live ``Config`` reference with a lock-free read / locked swap.

    ``current()`` returns the held snapshot without acquiring any lock;
    ``replace(new_config)`` atomically rebinds the held reference under a lock.
    ``replace()`` performs no checking (that is Phase 9 / CFG-04).
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()

    def current(self) -> Config:
        """Return the currently held ``Config``.

        Lock-free on purpose: a bare attribute load is one atomic bytecode
        under the GIL, so a concurrent reader sees either the old or the new
        whole snapshot — never a torn one.
        """
        return self._config

    def replace(self, new_config: Config) -> None:
        """Atomically rebind the held reference to ``new_config``.

        Lock-guarded to serialize writers. Does NOT check ``new_config`` —
        the check-before-swap boundary is deferred to Phase 9 (CFG-04).
        """
        with self._lock:
            self._config = new_config
