"""Wave-0 Nyquist scaffold for Phase 8 — ConfigHolder + ``fire_slot`` holder refactor.

These tests are written BEFORE any production code exists. They import
``ConfigHolder`` (from ``weatherbot.config.holder`` — built in Plan 03) and call
``fire_slot(..., holder=...)`` (the ``holder=`` param lands in Plan 04). BOTH are
intentionally absent today, so this file lands **RED** (import error / unexpected
``holder=`` kwarg). That RED is the falsifiable specification: Plans 02–04 are
judged done by flipping the named subset of these tests GREEN.

Node IDs are written EXACTLY per ``08-VALIDATION.md`` Per-Task Verification Map:
``test_current_returns_held`` (SC#1a), ``test_replace_rebinds`` (SC#1b),
``test_concurrent_read_swap_safe`` (SC#1c), ``test_inflight_job_keeps_snapshot``
(SC#2a), ``test_unchanged_job_renders_after_replace`` (SC#2b / D-04),
``test_config_override_wins`` (D-01).

Helper reuse (VALIDATION Wave-0 #3 — DO NOT invent new fixtures): ``_config``,
``_slot``, ``_RecordingStop``, ``_Channel``, ``_patch_send_now`` are imported from
``tests.test_reliability``; ``tmp_db`` comes from conftest. "Config B" is built ONLY
via ``config_a.model_copy(update=...)`` (Pitfall 5 — never hand-build, never mutate
the frozen original). No code here hashes / sets / dict-keys a ``Config`` (Pitfall 1).
"""

from __future__ import annotations

import threading

from weatherbot.channels.base import DeliveryResult
from weatherbot.scheduler import daemon as daemon_mod

# Reuse the existing reliability-suite helpers verbatim (no re-invention).
from tests.test_reliability import (
    _Channel,
    _config,
    _patch_send_now,
    _RecordingStop,
    _slot,
)

# RED import (deferred): ``weatherbot.config.holder`` does not exist until Plan 03.
# This is the Nyquist signal — every test fails on purpose until the holder ships.
# The import is deferred to a helper (rather than top-of-module) ON PURPOSE: a hard
# top-level ``import`` would error at COLLECTION and hide the six node IDs, whereas
# VALIDATION.md requires all six to COLLECT and land RED at RUN time. ``_holder()``
# resolves the symbol per-test, so the file collects six tests and each fails with a
# real ``ModuleNotFoundError`` until Plan 03 lands the holder — the correct RED.


def _holder(config):
    """Construct a ``ConfigHolder`` — fails RED until ``weatherbot.config.holder``
    exists (Plan 03). Deferred so the six node IDs collect (VALIDATION Wave-0)."""
    from weatherbot.config.holder import ConfigHolder

    return ConfigHolder(config)


def _config_b():
    """Build a DISTINCT second config from the shared base via ``model_copy``.

    Never hand-build and never mutate the frozen original (Pitfall 5): rebind a
    single safe field (``template``) so ``config_a is not config_b`` while every
    other field stays valid.
    """
    config_a = _config()
    config_b = config_a.model_copy(update={"template": "other.txt"})
    return config_a, config_b


# --------------------------------------------------------------------------- #
# SC#1 — holder unit semantics: current() returns the held config; replace()
# rebinds; concurrent read/swap never tears.
# --------------------------------------------------------------------------- #


def test_current_returns_held():
    """SC#1a: ``ConfigHolder(config_a).current()`` is the exact held config."""
    config_a, _ = _config_b()
    holder = _holder(config_a)
    assert holder.current() is config_a


def test_replace_rebinds():
    """SC#1b: after ``holder.replace(config_b)``, ``current()`` is ``config_b``."""
    config_a, config_b = _config_b()
    holder = _holder(config_a)
    holder.replace(config_b)
    assert holder.current() is config_b


def test_concurrent_read_swap_safe():
    """SC#1c: ~8 readers + 1 writer racing never observe a torn / None read.

    Readers loop asserting ``current() is config_a or current() is config_b`` while
    a single writer alternates ``replace(config_a)/replace(config_b)`` for a bounded
    number of iterations. Any exception (including a torn/None read) is collected
    into a shared list; the test fails if that list is non-empty after ``join()``.
    A torn read is impossible by construction (atomic reference store) — this test
    GUARDS that invariant deterministically, with no real sleeps.
    """
    config_a, config_b = _config_b()
    holder = _holder(config_a)

    errors: list[BaseException] = []
    stop = threading.Event()
    ITERATIONS = 5000

    def reader():
        try:
            while not stop.is_set():
                seen = holder.current()
                if seen is not config_a and seen is not config_b:
                    raise AssertionError(f"torn/None read: {seen!r}")
        except BaseException as exc:  # noqa: BLE001 — record, never swallow
            errors.append(exc)

    def writer():
        try:
            for i in range(ITERATIONS):
                holder.replace(config_b if i % 2 else config_a)
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


# --------------------------------------------------------------------------- #
# SC#2 / D-01 / D-04 — fire_slot reads the holder ONCE per fire; an in-flight job
# keeps its snapshot; an unchanged job renders the NEW config after replace; an
# explicit config= override wins over the holder.
# --------------------------------------------------------------------------- #


def test_inflight_job_keeps_snapshot(tmp_db, monkeypatch):
    """SC#2a: a fire in flight keeps the config it read (single-read-per-fire).

    The recording fake ``send_now`` records the ``config`` it received on first
    call, signals the test, then BLOCKS on a second event. The test replaces the
    holder mid-flight, releases the block, joins the fire thread, and asserts the
    recorded config is STILL ``config_a`` — the mid-flight ``replace`` does not
    re-read into the running job.
    """
    config_a, config_b = _config_b()
    loc, slot = _slot(config_a)
    holder = _holder(config_a)

    seen: list = []
    entered = threading.Event()
    release = threading.Event()

    def fake_send_now(*args, **kwargs):
        seen.append(kwargs["config"])
        entered.set()
        release.wait(timeout=5)
        return DeliveryResult(ok=True)

    _patch_send_now(monkeypatch, fake_send_now)

    def fire():
        daemon_mod.fire_slot(
            loc, slot, holder=holder, db_path=tmp_db,
            channel=_Channel(), stop_event=_RecordingStop(),
        )

    t = threading.Thread(target=fire)
    t.start()
    assert entered.wait(timeout=5), "fire never entered send_now"
    holder.replace(config_b)  # swap WHILE the job is in flight
    release.set()
    t.join(timeout=5)

    assert seen == [config_a]
    assert seen[0] is config_a


def test_unchanged_job_renders_after_replace(tmp_db, monkeypatch):
    """SC#2b / D-04: the SAME job renders the NEW config after a replace.

    This is the phase's core proof: a job registered against the holder (no
    re-registration) passes ``config_b`` into ``send_now`` once the holder has been
    replaced — the reference, not a baked-in snapshot, is what each fire reads.
    """
    config_a, config_b = _config_b()
    loc, slot = _slot(config_a)
    holder = _holder(config_a)

    seen: list = []

    def fake_send_now(*args, **kwargs):
        seen.append(kwargs["config"])
        return DeliveryResult(ok=True)

    _patch_send_now(monkeypatch, fake_send_now)

    holder.replace(config_b)
    daemon_mod.fire_slot(
        loc, slot, holder=holder, db_path=tmp_db,
        channel=_Channel(), stop_event=_RecordingStop(),
    )

    assert seen == [config_b]
    assert seen[0] is config_b


def test_config_override_wins(tmp_db, monkeypatch):
    """D-01: an explicit ``config=`` argument wins over whatever the holder holds.

    The holder holds ``config_b`` but the caller passes ``config=config_a``; the
    recording ``send_now`` must see ``config_a`` (the explicit override is honored).
    """
    config_a, config_b = _config_b()
    loc, slot = _slot(config_a)
    holder = _holder(config_b)

    seen: list = []

    def fake_send_now(*args, **kwargs):
        seen.append(kwargs["config"])
        return DeliveryResult(ok=True)

    _patch_send_now(monkeypatch, fake_send_now)

    daemon_mod.fire_slot(
        loc, slot, config=config_a, holder=holder, db_path=tmp_db,
        channel=_Channel(), stop_event=_RecordingStop(),
    )

    assert seen == [config_a]
    assert seen[0] is config_a
