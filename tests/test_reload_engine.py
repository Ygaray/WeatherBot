"""Direct-engine proof for ``ReloadEngine[T]`` (Phase 24, D-04..D-09).

Mirrors ``tests/test_scheduler_engine.py``'s direct-module discipline: construct the engine
with STUB collaborators (``validate``/``desired_jobs``/``register_jobs``/``restore``) and a
fake scheduler-engine (recording ``list_live_ids`` / ``remove`` calls), drive each verb, and
read the result back — no daemon, no weather config, no real scheduler.

The contract under test (all behavior-preserving lifts from ``daemon.py``'s reload machinery):

- ``check(path)`` is validate-only — no swap, no reconcile, no scheduler touch.
- ``reload(path)`` keep-old on a validator raise: ``on_rejected(exc)`` fires BEFORE the
  re-raise, holder + jobs untouched.
- ``reload(path)`` committed success: holder swapped, ``register_jobs`` called with the new
  config, every ``live - desired`` id removed, an EXCLUDED id is never removed (the injected
  ``excluded_ids`` frozenset is subtracted before diffing — Pitfall 2), ``on_applied`` gets
  the exact byte-identical ``+a -r ~c =u`` summary string.
- reconcile throw -> holder restored to old + ``restore(old)`` called + ORIGINAL error
  re-raised; a ``restore`` that itself raises is swallowed and never masks the cause.
- ``request_reload()`` only flag-sets; ``service_pending(path)`` returns False when unset,
  else clears + runs ``reload(path)`` + returns True.
- ``on_applied`` / ``on_rejected`` are best-effort: a hook that raises is swallowed and never
  changes ``reload()``'s outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from yahir_reusable_bot.config import ConfigHolder, ReloadEngine


@dataclass(frozen=True)
class _Cfg:
    """A non-weather frozen config carried as ``T`` through the engine."""

    tag: str


class _FakeSchedulerEngine:
    """Records ``list_live_ids`` reads + ``remove`` calls (the engine's REMOVE seam)."""

    def __init__(self, live: set[str]) -> None:
        self._live = set(live)
        self.removed: list[str] = []

    def list_live_ids(self) -> set[str]:
        return set(self._live)

    def remove(self, job_id: str) -> None:
        self.removed.append(job_id)
        self._live.discard(job_id)


def _make_engine(
    *,
    holder_cfg: _Cfg,
    live: set[str],
    desired: set[str],
    excluded_ids: frozenset[str] = frozenset(),
    validate=None,
    restore=None,
    on_applied=None,
    on_rejected=None,
):
    """Build a ReloadEngine with recording stubs; returns (engine, holder, fake_sched, calls)."""
    holder: ConfigHolder[_Cfg] = ConfigHolder(holder_cfg)
    fake = _FakeSchedulerEngine(live)
    calls: dict[str, list] = {"register": [], "restore": [], "validate": []}

    def _default_validate(path):
        calls["validate"].append(path)
        return _Cfg(tag=f"validated::{path}")

    def _register(cfg):
        calls["register"].append(cfg)

    def _default_restore(old):
        calls["restore"].append(old)

    engine = ReloadEngine(
        holder,
        fake,
        validate=validate if validate is not None else _default_validate,
        desired_jobs=lambda _cfg: set(desired),
        register_jobs=_register,
        restore=restore if restore is not None else _default_restore,
        excluded_ids=excluded_ids,
        on_applied=on_applied,
        on_rejected=on_rejected,
    )
    return engine, holder, fake, calls


# --------------------------------------------------------------------------- #
# check() — validate-only (D-06)
# --------------------------------------------------------------------------- #


def test_check_is_validate_only():
    """check(path) returns validate(path) and touches no swap/reconcile/scheduler."""
    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"), live={"a"}, desired={"a", "b"}
    )
    result = engine.check("cfg.toml")

    assert result == _Cfg(tag="validated::cfg.toml")
    assert calls["validate"] == ["cfg.toml"]
    assert calls["register"] == []  # no reconcile
    assert fake.removed == []  # no scheduler touch
    assert holder.current() == _Cfg("old")  # no swap


# --------------------------------------------------------------------------- #
# reload() PHASE 1 — keep-old on validator raise (D-08 / D-09 timing)
# --------------------------------------------------------------------------- #


def test_reload_keeps_old_on_validator_raise_and_posts_rejected_first():
    """A validator raise: on_rejected fires BEFORE re-raise; holder + jobs untouched."""
    boom = ValueError("bad config")
    order: list[str] = []

    def _validate(path):
        order.append("validate")
        raise boom

    def _on_rejected(exc):
        order.append(f"rejected:{exc}")

    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"),
        live={"a"},
        desired={"a"},
        validate=_validate,
        on_rejected=_on_rejected,
    )

    with pytest.raises(ValueError) as ei:
        engine.reload("cfg.toml")

    assert ei.value is boom  # ORIGINAL error re-raised
    assert order == ["validate", "rejected:bad config"]  # rejected posted before raise
    assert holder.current() == _Cfg("old")  # keep-old: no swap
    assert calls["register"] == []  # no reconcile
    assert fake.removed == []  # no jobs touched


# --------------------------------------------------------------------------- #
# reload() PHASE 2 — committed success: diff + removes + excluded + summary (D-01/D-09)
# --------------------------------------------------------------------------- #


def test_reload_committed_success_diff_removes_excluded_and_summary():
    """Holder swaps; register called; live-desired removed; excluded never removed; summary exact."""
    applied: list[str] = []
    new_cfg = _Cfg("new")

    # live has: a (kept), gone (to remove), __excluded__ (must NOT be removed).
    # desired has: a (unchanged), b (added). => +1 -1 ~0 =1
    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"),
        live={"a", "gone", "__excluded__"},
        desired={"a", "b"},
        excluded_ids=frozenset({"__excluded__"}),
        validate=lambda _p: new_cfg,
        on_applied=lambda s: applied.append(s),
    )

    engine.reload("cfg.toml")

    assert holder.current() is new_cfg  # committed swap
    assert calls["register"] == [new_cfg]  # ADD via injected registrar, full desired set
    assert fake.removed == ["gone"]  # only the non-excluded live-desired id
    assert "__excluded__" not in fake.removed  # Pitfall 2 — excluded id survives
    assert applied == ["+1 -1 ~0 =1"]  # byte-identical summary, added/removed/changed/unchanged


def test_reload_excluded_id_never_removed_even_when_not_desired():
    """An excluded id absent from desired is still never removed (frozenset subtracted first)."""
    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"),
        live={"__heartbeat__", "__uvmonitor__"},
        desired=set(),
        excluded_ids=frozenset({"__heartbeat__", "__uvmonitor__"}),
        validate=lambda _p: _Cfg("new"),
    )

    engine.reload("cfg.toml")

    assert fake.removed == []  # both excluded -> live becomes empty -> nothing to remove


# --------------------------------------------------------------------------- #
# reload() PHASE 2 — reconcile throw => all-or-nothing rollback (D-08)
# --------------------------------------------------------------------------- #


def test_reload_reconcile_throw_rolls_back_and_reraises():
    """A reconcile throw: holder restored to old + restore(old) called + original error re-raised."""
    reconcile_err = RuntimeError("reconcile blew up")

    def _register(cfg):
        raise reconcile_err

    holder: ConfigHolder[_Cfg] = ConfigHolder(_Cfg("old"))
    fake = _FakeSchedulerEngine({"a"})
    restored: list = []

    engine = ReloadEngine(
        holder,
        fake,
        validate=lambda _p: _Cfg("new"),
        desired_jobs=lambda _c: {"a", "b"},
        register_jobs=_register,
        restore=lambda old: restored.append(old),
    )

    with pytest.raises(RuntimeError) as ei:
        engine.reload("cfg.toml")

    assert ei.value is reconcile_err  # ORIGINAL reconcile error re-raised
    assert holder.current() == _Cfg("old")  # rolled back to old_cfg
    assert restored == [_Cfg("old")]  # restore(old) called


def test_reload_restore_raise_is_swallowed_and_does_not_mask_cause():
    """A restore that itself raises is swallowed; the ORIGINAL reconcile error still surfaces."""
    reconcile_err = RuntimeError("reconcile blew up")

    def _register(cfg):
        raise reconcile_err

    def _restore(old):
        raise RuntimeError("restore also blew up")

    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"),
        live={"a"},
        desired={"a", "b"},
        validate=lambda _p: _Cfg("new"),
        restore=_restore,
    )

    # register_jobs is the default recorder, override engine's registrar via a fresh build:
    holder2: ConfigHolder[_Cfg] = ConfigHolder(_Cfg("old"))
    fake2 = _FakeSchedulerEngine({"a"})
    engine2 = ReloadEngine(
        holder2,
        fake2,
        validate=lambda _p: _Cfg("new"),
        desired_jobs=lambda _c: {"a", "b"},
        register_jobs=_register,
        restore=_restore,
    )

    with pytest.raises(RuntimeError) as ei:
        engine2.reload("cfg.toml")

    assert ei.value is reconcile_err  # restore's error did NOT mask the cause
    assert holder2.current() == _Cfg("old")  # still rolled back


# --------------------------------------------------------------------------- #
# trigger flag pair — request_reload / service_pending (D-04 / D-05)
# --------------------------------------------------------------------------- #


def test_service_pending_false_when_flag_unset():
    """service_pending returns False and runs nothing when the flag is not set."""
    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"), live={"a"}, desired={"a"}
    )
    assert engine.service_pending("cfg.toml") is False
    assert calls["validate"] == []  # reload never ran


def test_request_reload_then_service_pending_runs_reload_once():
    """request_reload flag-sets; the next service_pending clears it, runs reload, returns True."""
    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"),
        live={"a"},
        desired={"a"},
        validate=lambda _p: _Cfg("new"),
    )

    engine.request_reload()
    assert engine.service_pending("cfg.toml") is True
    assert holder.current() == _Cfg("new")  # reload ran
    # Flag cleared: a second service_pending with no new request is a no-op.
    assert engine.service_pending("cfg.toml") is False


# --------------------------------------------------------------------------- #
# best-effort hooks — a raising hook never changes reload()'s outcome (D-09)
# --------------------------------------------------------------------------- #


def test_on_applied_raise_is_swallowed_reload_still_succeeds():
    """An on_applied hook that raises is swallowed; the reload still commits successfully."""
    def _boom(_summary):
        raise RuntimeError("post failed")

    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"),
        live={"a"},
        desired={"a"},
        validate=lambda _p: _Cfg("new"),
        on_applied=_boom,
    )

    engine.reload("cfg.toml")  # must NOT raise
    assert holder.current() == _Cfg("new")  # commit stuck


def test_on_rejected_raise_is_swallowed_original_error_still_raised():
    """An on_rejected hook that raises is swallowed; the ORIGINAL validator error still surfaces."""
    boom = ValueError("bad config")

    def _validate(_p):
        raise boom

    def _bad_hook(_exc):
        raise RuntimeError("post failed")

    engine, holder, fake, calls = _make_engine(
        holder_cfg=_Cfg("old"),
        live={"a"},
        desired={"a"},
        validate=_validate,
        on_rejected=_bad_hook,
    )

    with pytest.raises(ValueError) as ei:
        engine.reload("cfg.toml")
    assert ei.value is boom  # hook's error did not mask the validator error
    assert holder.current() == _Cfg("old")  # keep-old intact
