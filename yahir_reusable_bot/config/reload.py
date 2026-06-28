"""The ``ReloadEngine[T]`` — reusable config-reload orchestration (D-04..D-09).

This engine owns the genuinely-reusable control flow of a hot config reload, driving only
INJECTED callables so it carries zero app assumptions (a different bot reuses the whole engine
by wiring its own validator / job-deriver / registrar / side effects). It is the module-side
generalization of the app daemon's in-place reload machinery, lifted byte-identical in ordering
so the host's behavior stays unchanged.

What the engine owns (the reusable orchestration):

- ``reload(path)`` — the two-phase build-then-commit cycle: PHASE 1 validate-or-keep-old (an
  injected ``validate`` raise leaves the holder + jobs untouched and re-raises), PHASE 2 atomic
  swap + id-keyed diff-reconcile with all-or-nothing rollback (a reconcile throw rolls the
  holder back and re-runs the injected ``restore``, then re-raises).
- ``check(path)`` — PHASE-1 validate-only dry run: no swap, no reconcile, no scheduler touch.
- The id-keyed reconcile diff (``desired - live`` = add, ``desired & live`` = unchanged,
  ``live - desired`` = remove) over ``set[str]`` job ids (D-01), with the ADD phase delegated
  to the injected ``register_jobs`` (the full desired set, idempotent-swap) and the REMOVE
  phase driven through the host scheduler engine.
- The ``request_reload()`` / ``service_pending(path)`` flag pair (D-05): off-thread triggers
  (a signal handler, the watch thread) only flag-set; the actual reload runs synchronously on
  whatever thread calls ``service_pending`` (the host calls it from its main poll loop).
- An OPTIONAL engine-owned file-watch thread (``start_watching`` / ``stop``) that flag-sets on
  each settled change-set — so each new bot does NOT re-hand-write the pitfall-dense watch
  plumbing.

What the engine deliberately does NOT do (stays the host's / injected):

- It NEVER validates the config itself — validation routes ONLY through the injected concrete
  ``validate`` callable (the holder/engine cannot self-parametrize a generic validator at
  runtime; that is why the validator is injected). The engine never calls pydantic.
- It owns NO host lifecycle: no signal install, no main loop, no scheduler start/stop — exactly
  the non-owning discipline the scheduler engine follows.
- It names NO app job id. The daemon-internal ids to keep out of the reconcile diff arrive as
  an INJECTED ``excluded_ids`` frozenset, subtracted from the live set before diffing — so a
  reload never tears down a host's internal interval jobs, and the module never learns their
  names.
- The applied / rejected side effects are injected best-effort hooks invoked at the exact
  committed-success / before-re-raise points; a hook that raises is logged and swallowed and
  NEVER masks the engine's own result.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

import structlog

from .holder import ConfigHolder

_log = structlog.get_logger(__name__)

T = TypeVar("T")

# Watch-loop timings (lifted from the host observer): how long to wait for the change-set to
# settle, the upper grouping bound, and the Rust-loop timeout that bounds how often an empty
# tick yields (so a stop is honored sub-second and a re-derived watch set is picked up live).
_WATCH_QUIET_MS = 400
_WATCH_DEBOUNCE_MS = 1600
_WATCH_RUST_TIMEOUT_MS = 500


class ReloadEngine(Generic[T]):
    """Validate -> atomic-swap -> job-reconcile reload orchestrator over injected callables.

    Construct with the live holder + the host scheduler engine and the injected hooks; then
    drive by ``reload(path)`` / ``check(path)`` or off-thread via ``request_reload()`` +
    ``service_pending(path)``. The engine stores every collaborator by reference and invokes it
    opaquely — it never inspects ``T``, the validator's return, or the registrar's jobs.
    """

    def __init__(
        self,
        holder: ConfigHolder[T],
        scheduler_engine: Any,
        *,
        validate: Callable[[Any], T],
        desired_jobs: Callable[[T], set[str]],
        register_jobs: Callable[[T], None],
        restore: Callable[[T], None],
        excluded_ids: frozenset[str] = frozenset(),
        on_applied: Callable[[str], None] | None = None,
        on_rejected: Callable[[Exception], None] | None = None,
    ) -> None:
        self._holder = holder
        self._scheduler_engine = scheduler_engine
        self._validate = validate
        self._desired_jobs = desired_jobs
        self._register_jobs = register_jobs
        self._restore = restore
        self._excluded_ids = excluded_ids
        self._on_applied = on_applied
        self._on_rejected = on_rejected

        # Flag-set-only trigger (D-05): safe to .set() from a signal handler AND the watch
        # thread; the actual reload runs on the caller's thread via service_pending().
        self._reload_requested = threading.Event()

        # Watch-thread state (the engine owns the single long-lived observer + the shared
        # dir box; the host injects the re-derive via update_watch_dirs / on_applied).
        self._watch_thread: threading.Thread | None = None
        self._watch_dirs_ref: list[Any] | None = None

    # ------------------------------------------------------------------ #
    # check() — PHASE-1 validate-only dry run (D-06)
    # ------------------------------------------------------------------ #

    def check(self, path: Any) -> T:
        """Validate ``path`` only and return the result — no swap, reconcile, or scheduler touch."""
        return self._validate(path)

    # ------------------------------------------------------------------ #
    # reload() — two-phase build-then-commit (D-08 / D-09)
    # ------------------------------------------------------------------ #

    def reload(self, path: Any) -> None:
        """Validate -> swap -> reconcile with all-or-nothing rollback (lifted ordering).

        PHASE 1 (validate-or-keep-old): re-read + validate ``path`` via the injected
        ``validate``. On ANY raise, fire the best-effort ``on_rejected`` hook BEFORE re-raising,
        leaving the holder + job set UNTOUCHED (keep-old). PHASE 2 (atomic swap + reconcile):
        snapshot the old config, ``holder.replace(new)``, then reconcile; on ANY reconcile throw
        roll the holder back and re-run the injected ``restore`` (best-effort), then re-raise so
        the caller sees the failure with the OLD schedule fully intact. On success fire the
        best-effort ``on_applied`` hook with the diff summary.
        """
        # PHASE 1 — validate-or-keep-old. The injected validator owns the concrete catch set;
        # here a bare ``except Exception`` preserves the keep-old contract for any failure.
        try:
            new_cfg = self._validate(path)
        except Exception as exc:
            _log.error("reload rejected", reason=str(exc))
            # Post the rejection reason BEFORE re-raising (preserve the post-then-raise timing).
            # Best-effort: a hook failure is logged + swallowed; the ORIGINAL validation error
            # below is the one re-raised, keeping keep-old intact.
            self._best_effort_hook(self._on_rejected, exc, label="reload-rejected")
            raise

        # PHASE 2 — atomic swap + diff-reconcile, all-or-nothing rollback on any throw.
        old_cfg = self._holder.current()
        self._holder.replace(new_cfg)
        try:
            summary = self._reconcile()
        except Exception:
            # Roll back to the previous config AND rebuild the old job set from it, then
            # re-raise so the OLD schedule fires fully intact. The restore is best-effort and
            # must never mask the ORIGINAL reconcile error.
            self._holder.replace(old_cfg)
            try:
                self._restore(old_cfg)
            except Exception:  # noqa: BLE001 — restore is best-effort; surface the real cause
                _log.exception(
                    "reload rollback restore raised; original error re-raised"
                )
            _log.error("reload reconcile failed; rolled back to previous config")
            raise

        _log.info("reload applied", summary=summary)
        # Post the structured outcome + run any committed-success side effect. Best-effort: a
        # hook failure is logged + swallowed and MUST NOT abort the already-committed reload.
        self._best_effort_hook(self._on_applied, summary, label="reload-applied")

    def _reconcile(self) -> str:
        """Diff-reconcile live jobs to the held config on the stable id; return the diff summary.

        The DESIRED set is the injected ``desired_jobs`` over the current config; the LIVE set
        is the host scheduler's ids MINUS the injected ``excluded_ids`` frozenset (subtracted
        BEFORE diffing so a host-internal id is never counted as removable — the engine never
        learns the names). Every desired id is (re-)registered via the injected ``register_jobs``
        (the full desired set, idempotent swap); every live id the new config no longer wants is
        removed through the host scheduler. ``changed`` is 0 — content edits ride the holder swap.
        """
        desired = self._desired_jobs(self._holder.current())
        live = self._scheduler_engine.list_live_ids() - self._excluded_ids

        added = len(desired - live)
        unchanged = len(desired & live)
        changed = 0

        # ADD/replace every desired id via the injected registrar (idempotent swap): an
        # already-live id rides the holder swap; a new id is created.
        self._register_jobs(self._holder.current())

        # REMOVE every live id the new config no longer wants.
        removed = 0
        for job_id in live - desired:
            self._scheduler_engine.remove(job_id)
            removed += 1

        return f"+{added} -{removed} ~{changed} ={unchanged}"

    # ------------------------------------------------------------------ #
    # trigger flag pair (D-04 / D-05)
    # ------------------------------------------------------------------ #

    def request_reload(self) -> None:
        """Flag a reload — FLAG-SET ONLY (safe from a signal handler AND the watch thread)."""
        self._reload_requested.set()

    def service_pending(self, path: Any) -> bool:
        """If a reload is flagged, clear the flag and run ``reload(path)`` on the caller's thread.

        Returns ``True`` iff a reload was serviced, ``False`` when no reload was pending. Runs
        synchronously on whatever thread calls it — the host calls it from its main poll loop, so
        reload work never runs re-entrantly in a signal handler or on the observer thread (D-05).
        """
        if not self._reload_requested.is_set():
            return False
        self._reload_requested.clear()
        self.reload(path)
        return True

    # ------------------------------------------------------------------ #
    # optional engine-owned file-watch thread (D-04)
    # ------------------------------------------------------------------ #

    def start_watching(
        self,
        watch_dirs_ref: list[Any],
        *,
        watch_filter: Callable[[Any, str], bool],
        stop: threading.Event,
    ) -> None:
        """Spawn the single long-lived file-watch observer thread (flag-set only on change).

        ``watch_dirs_ref`` is a one-element box holding the current watch-dir set; the engine
        owns the thread and re-enters the ``watch()`` generator when a reload re-derived the box
        (via :meth:`update_watch_dirs`). On each settled, NON-EMPTY change-set the thread calls
        :meth:`request_reload` — the actual reload runs on the host's main thread via
        :meth:`service_pending`, never here (no re-entrant reload on the observer thread).
        """
        self._watch_dirs_ref = watch_dirs_ref
        self._watch_thread = threading.Thread(
            target=self._run_watch_observer,
            args=(watch_dirs_ref, stop),
            kwargs={"watch_filter": watch_filter},
            daemon=True,
        )
        self._watch_thread.start()

    def update_watch_dirs(self, new_dirs: Any) -> None:
        """Re-derive the shared watch-dir box; the observer picks it up on its next empty tick.

        Mutates ONLY the shared box — it does NOT construct a second observer or call watch()
        directly. The host's ``on_applied`` closure (which knows how to derive the dir set)
        calls this after a successful swap so a moved file becomes watched without a restart.
        """
        if self._watch_dirs_ref is not None:
            self._watch_dirs_ref[0] = new_dirs

    def _run_watch_observer(
        self,
        watch_dirs_ref: list[Any],
        stop: threading.Event,
        *,
        watch_filter: Callable[[Any, str], bool],
    ) -> None:
        """The observer loop: run the blocking ``watch()`` and flag-set on each non-empty change.

        Each outer iteration snapshots the dir box and opens one ``watch()`` generator on that
        snapshot. On a settled non-empty change-set it calls :meth:`request_reload`. On an empty
        timeout tick it compares the live box against the snapshot and, when a reload re-derived
        it, BREAKS so the outer loop re-enters ``watch()`` with the new dirs (releasing the old
        fds on exhaustion — no fd leak across re-derive). The single long-lived generator is
        given ``stop_event=stop`` + ``rust_timeout`` + ``yield_on_timeout=True`` so a stop is
        honored sub-second and an empty tick lets the loop re-check stop + the dir box.
        """
        # Lazy in-function import: keep the watch backend's transitive imports off the module's
        # import-time graph.
        from watchfiles import watch

        while not stop.is_set():
            dirs_snapshot = frozenset(watch_dirs_ref[0])
            for _changes in watch(
                *tuple(dirs_snapshot),
                step=_WATCH_QUIET_MS,
                debounce=_WATCH_DEBOUNCE_MS,
                rust_timeout=_WATCH_RUST_TIMEOUT_MS,
                yield_on_timeout=True,
                watch_filter=watch_filter,
                stop_event=stop,
                recursive=False,
            ):
                if stop.is_set():
                    return
                if _changes:
                    self.request_reload()
                # An empty set is a timeout tick: if the dir box was re-derived on a reload,
                # drop this generator so the outer loop re-enters watch() with the new dirs.
                elif frozenset(watch_dirs_ref[0]) != dirs_snapshot:
                    break
            if stop.is_set():
                return

    def stop(self) -> None:
        """Join the engine-owned observer thread (idempotent; the host's finally calls it).

        The host sets the shared ``stop`` event (which terminates the blocking ``watch()``
        generator sub-second) before calling this; here we only join the thread.
        """
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=2.0)
            if self._watch_thread.is_alive():
                _log.warning("file-watch observer did not stop within join timeout")

    # ------------------------------------------------------------------ #
    # best-effort hook guard (D-09)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _best_effort_hook(
        hook: Callable[[Any], None] | None, arg: Any, *, label: str
    ) -> None:
        """Invoke an optional hook best-effort: a None hook is a no-op; a raise is swallowed.

        A hook failure is logged (outcome-only) and swallowed so it can NEVER mask the engine's
        own result — the reject path's original error or the applied path's committed swap.
        """
        if hook is None:
            return
        try:
            hook(arg)
        except Exception:  # noqa: BLE001 — best-effort; never mask the engine result
            _log.warning(f"{label} hook failed; engine result unaffected")
