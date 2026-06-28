"""Direct-module proof that ``ConfigHolder[T]`` is a generic storage cell (Phase 24, D-02).

The weather-typed oracle (``tests/test_config_holder.py::test_concurrent_read_swap_safe``)
proves the lock-free-read / locked-swap MECHANISM stays byte-identical. This file proves
the GENERALIZATION: ``ConfigHolder`` now carries an UNBOUND ``T`` — any bot can pass its own
frozen config type with zero inheritance (the reminder-bot litmus, in test form). It mirrors
``tests/test_scheduler_engine.py``'s direct-module style: construct the cell, drive its verbs,
read the result back — no daemon, no weather config.

The ``T`` carried here is a plain ``@dataclass(frozen=True)`` with fields UNRELATED to weather
(a stand-in for a future reminder bot's config). If ``ConfigHolder`` had a bound ``TypeVar`` /
a module ``BaseConfig`` this non-weather type would not satisfy it — round-tripping it proves
the unbound contract genuinely accepts any type (D-02).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from yahir_reusable_bot.config import ConfigHolder


@dataclass(frozen=True)
class _ReminderConfig:
    """A non-weather frozen config (the reminder-bot stand-in for ``T``)."""

    label: str
    interval_minutes: int


def _config_a() -> _ReminderConfig:
    return _ReminderConfig(label="standup", interval_minutes=15)


def _config_b() -> _ReminderConfig:
    return _ReminderConfig(label="lunch", interval_minutes=60)


def test_current_returns_held_non_weather_type():
    """``ConfigHolder(cfg).current()`` is the exact held NON-weather object (identity)."""
    cfg = _config_a()
    holder: ConfigHolder[_ReminderConfig] = ConfigHolder(cfg)
    assert holder.current() is cfg


def test_replace_rebinds_non_weather_type():
    """After ``replace(cfg_b)``, ``current()`` is ``cfg_b`` — no copy/clone/validation."""
    cfg_a, cfg_b = _config_a(), _config_b()
    holder: ConfigHolder[_ReminderConfig] = ConfigHolder(cfg_a)
    holder.replace(cfg_b)
    assert holder.current() is cfg_b


def test_concurrent_read_swap_safe_generic():
    """~8 readers + 1 writer racing on the generic holder never see a torn / None read.

    Ported verbatim in intent from ``test_config_holder.py::test_concurrent_read_swap_safe``
    against the GENERIC holder carrying a non-weather ``T``: readers loop asserting
    ``current() is cfg_a or current() is cfg_b`` while one writer alternates the two; any
    torn/None read is recorded and fails the test. A torn read is impossible by construction
    (one atomic reference store under the GIL) — this guards that invariant deterministically.
    """
    cfg_a, cfg_b = _config_a(), _config_b()
    holder: ConfigHolder[_ReminderConfig] = ConfigHolder(cfg_a)

    errors: list[BaseException] = []
    stop = threading.Event()
    ITERATIONS = 5000

    def reader():
        try:
            while not stop.is_set():
                seen = holder.current()
                if seen is not cfg_a and seen is not cfg_b:
                    raise AssertionError(f"torn/None read: {seen!r}")
        except BaseException as exc:  # noqa: BLE001 — record, never swallow
            errors.append(exc)

    def writer():
        try:
            for i in range(ITERATIONS):
                holder.replace(cfg_b if i % 2 else cfg_a)
        except BaseException as exc:  # noqa: BLE001 — record, never swallow
            errors.append(exc)
        finally:
            stop.set()

    readers = [threading.Thread(target=reader) for _ in range(8)]
    w = threading.Thread(target=writer)
    for t in readers:
        t.start()
    w.start()
    w.join()
    for t in readers:
        t.join()

    assert not errors, f"concurrent read/swap recorded errors: {errors!r}"
