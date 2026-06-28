"""Wave-0 safety net for the OccurrenceStore + JobStore Protocol contracts (Phase 23).

``AlertSink`` (the only prior port) shipped untested, so these asserts are written
directly from the Protocol contract. Two things are pinned:

1. Both ports are ``@runtime_checkable`` Protocols — a host adapter can be
   ``isinstance``-checked structurally, no subclassing.
2. Structural satisfaction works against a class INSTANCE (Pitfall 6): a
   ``runtime_checkable`` ``isinstance`` checks attribute PRESENCE only, so a tiny
   conforming class with ``claim``/``was_fired``/``release`` methods satisfies
   ``OccurrenceStore``. (Per D-06a the port is the type contract; the app's calls
   stay bare against the concrete store functions.)
"""

from __future__ import annotations

import os
import typing

from yahir_reusable_bot.ports import JobStore, MemoryJobStore, OccurrenceStore


def test_occurrence_store_is_runtime_checkable_protocol():
    """OccurrenceStore is a runtime_checkable Protocol."""
    assert issubclass(OccurrenceStore, typing.Protocol)  # type: ignore[arg-type]
    # runtime_checkable lets isinstance work against this Protocol at all.
    assert getattr(OccurrenceStore, "_is_runtime_protocol", False) is True


def test_jobstore_is_runtime_checkable_protocol():
    """JobStore is a runtime_checkable Protocol."""
    assert issubclass(JobStore, typing.Protocol)  # type: ignore[arg-type]
    assert getattr(JobStore, "_is_runtime_protocol", False) is True


def test_occurrence_store_structurally_satisfied_by_instance():
    """A class INSTANCE exposing claim/was_fired/release satisfies OccurrenceStore (Pitfall 6)."""

    class _ConformingStore:
        def claim(self, handle: str | os.PathLike[str], key: str, occurrence: str) -> bool:
            return True

        def was_fired(self, handle: str | os.PathLike[str], key: str, occurrence: str) -> bool:
            return False

        def release(self, handle: str | os.PathLike[str], key: str, occurrence: str) -> None:
            return None

    assert isinstance(_ConformingStore(), OccurrenceStore)

    # A class missing a method is NOT a structural match.
    class _PartialStore:
        def claim(self, handle, key, occurrence) -> bool:
            return True

    assert not isinstance(_PartialStore(), OccurrenceStore)


def test_memory_jobstore_instantiates():
    """MemoryJobStore() is constructible — the shipped define-only in-memory impl."""
    store = MemoryJobStore()
    assert store is not None
