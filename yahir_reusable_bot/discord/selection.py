"""The ``SelectedContext[I]`` — a generic typed holder for the panel's selected item (D-02).

This is the reusable-module generalization of the panel's old hardcoded in-memory
selection (the single value a dropdown ``set``s and the command buttons ``read``). It
holds a reference to the currently selected item of an APP-DEFINED type ``I``. An app
parameterizes it with its own item type (``SelectedContext[str]``,
``SelectedContext[SomeId]``, …); the module imposes no domain concept and no inheritance.

``I`` is an UNBOUND ``TypeVar`` (D-02), cloned VERBATIM from the
:class:`~yahir_reusable_bot.config.holder.ConfigHolder` precedent: the module ships NO
base class for apps to subclass — any bot parameterizes ``SelectedContext`` with its own
item type with zero inheritance, the cleanest cross-repo import story. The bound is
deliberately omitted.

Concurrency contract — NO lock (deliberately simpler than ``ConfigHolder``): the
selection is **single-writer**. It is mutated ONLY inside the panel's ``on_select``
callback, which runs on the gateway event loop; every other access is a read on that same
loop. There is no cross-thread writer to serialize, so (unlike the config holder, which a
file-watch thread mutates) this cell carries no lock. The button callbacks read ``.value``
(the in-memory selection) and NEVER re-read ``Select.values`` (empty outside an active
select interaction — Pitfall 3).
"""

from __future__ import annotations

from typing import Generic, TypeVar

# UNBOUND (D-02) — no module base class. Any bot passes its own selected-item type, so the
# module imposes zero inheritance. The bound is deliberately omitted (the holder precedent).
I = TypeVar("I")


class SelectedContext(Generic[I]):
    """A typed holder for the panel's currently selected item of type ``I`` (D-02).

    Replaces the panel's old hardcoded in-memory selection: ``value`` returns the held
    item (read per tap by the command callbacks) and ``set`` rebinds it (called from the
    dropdown's ``on_select``). No lock — selection is single-writer on the gateway loop.
    """

    def __init__(self, value: I) -> None:
        self._value: I = value

    @property
    def value(self) -> I:
        """Return the currently selected item."""
        return self._value

    def set(self, value: I) -> None:
        """Rebind the held selection to ``value`` (called from the dropdown callback)."""
        self._value = value
