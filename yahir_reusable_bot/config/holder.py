"""The ``ConfigHolder[T]`` — a generic single-owner cell for a live, immutable config (D-02).

This is the reusable-module generalization of the app's typed holder: one mutable
cell that holds a reference to the current frozen config snapshot of an APP-DEFINED type
``T``. Every live job reads the *reference*, so a single ``replace(new_config)`` changes what
all jobs see next — the seam the whole hot-reload engine rests on. ``T`` is an UNBOUND
``TypeVar`` (D-02): the module ships NO base class for apps to subclass — any bot passes its
own frozen config type with zero inheritance, the cleanest cross-repo import story.

Concurrency contract (preserved byte-for-byte from the analog, D-03a):

- ``current()`` is **lock-free**. It is a single ``LOAD_ATTR`` bytecode, which is atomic
  under the GIL against the single ``STORE_ATTR`` in ``replace()``. A reader therefore always
  observes the OLD or the NEW *whole* config — never a torn or partial one. (Proven by
  ``test_concurrent_read_swap_safe`` against the app holder and by
  ``test_concurrent_read_swap_safe_generic`` against this generic one.)
- ``replace(new_config)`` takes a plain non-reentrant lock that **serializes writers** and
  gives the engine a single place to hang an atomic swap.

What this holder deliberately does NOT do:

- It does **NOT check** ``new_config`` in ``replace()``. Validation is INJECTED at the engine
  (the app's concrete validator) — the holder never parses or validates, and NEVER calls
  pydantic (D-03 / Pitfall 1: ``TypeVar`` is erased at runtime, so a holder cannot
  self-parametrize a validator; validating on a base would silently drop fields).
- It does **NOT** record anything, copy, or clone. Snapshots are already frozen, so the
  shared reference is safe to hand out as-is.
- It owns the app's config object ONLY. The secrets object / ``.env`` never enters the holder
  (secrets live behind the restart boundary).
"""

from __future__ import annotations

import threading
from typing import Generic, TypeVar

# UNBOUND (D-02) — no module base class. Any bot passes its own frozen config type, so the
# module imposes zero inheritance. The bound is deliberately omitted: validation is injected
# at the engine, and a bound's mere existence would tempt the holder into validating itself.
T = TypeVar("T")


class ConfigHolder(Generic[T]):
    """Owns one live config reference with a lock-free read / locked swap.

    ``current()`` returns the held snapshot without acquiring any lock;
    ``replace(new_config)`` atomically rebinds the held reference under a lock.
    ``replace()`` performs no checking, copy, clone, or record (validation is injected
    at the :class:`~yahir_reusable_bot.config.ReloadEngine`).
    """

    def __init__(self, config: T) -> None:
        self._config = config
        self._lock = threading.Lock()

    def current(self) -> T:
        """Return the currently held config.

        Lock-free on purpose: a bare attribute load is one atomic bytecode under the GIL,
        so a concurrent reader sees either the old or the new whole snapshot — never a torn
        one.
        """
        return self._config

    def replace(self, new_config: T) -> None:
        """Atomically rebind the held reference to ``new_config``.

        Lock-guarded to serialize writers. Does NOT check ``new_config`` — validation is
        the engine's injected concern, and this cell never copies, clones, or records.
        """
        with self._lock:
            self._config = new_config
