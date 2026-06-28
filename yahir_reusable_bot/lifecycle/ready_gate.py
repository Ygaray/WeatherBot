"""The ``ReadyGate`` — reusable systemd-readiness gate over an injected health-check.

The module-side generalization of the app daemon's startup gate (SEAM-05, D-01),
cloning the ``ReloadEngine`` recipe: constructor-injection + opaque passthrough +
symmetric best-effort hooks. It owns the genuinely-reusable, pitfall-dense triad a
reminder bot would otherwise re-hand-write:

- the interruptible ``while not stop.is_set()`` re-probe loop — it calls the
  INJECTED ``health_check`` on every pass, branches the startup log level on the
  NEUTRAL :class:`~yahir_reusable_bot.lifecycle.health.Severity` field of the
  returned :class:`HealthResult` (NEVER by comparing ``reason`` to an app string),
  and waits on ``stop.wait(interval)`` — NEVER ``time.sleep`` — so a ``systemctl
  stop`` mid-probe breaks promptly (Pitfall 2, T-25-02);
- the ``READY=1`` emit — the module owns ONLY ``notifier.ready()`` and a
  weather-noun-free structured online log; and

What the gate deliberately does NOT do (stays the app's / injected, D-02a): it
owns ZERO durable I/O. The durable health row, the heartbeat tick, and the online
ping all ride the injected best-effort ``on_online`` hook (invoked once on the
first pass) and the per-outcome ``on_fail`` hook (invoked on each failing probe).
A hook that raises is logged + swallowed and NEVER masks the gate result.

Heartbeat tick (D-01): this gate uses the sanctioned Option (d) — it does NOT
hold a scheduler handle. The app re-registers the ``__heartbeat__`` IntervalTrigger
tick via the existing ``SchedulerEngine.register(...)`` one-liner at the
composition root, so ``run_daemon`` stays byte-identical and the gate carries no
scheduler dependency.
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from .health import HealthResult, Severity

_log = structlog.get_logger(__name__)

# Startup self-check re-probe cadence (lifted from the app daemon, D-04). 120s:
# frequent enough that a recovered network / propagating credential recovers
# within ~2 min of becoming good, gentle enough it never approaches any upstream
# rate limit. A module default — an app may override per construction.
RE_PROBE_INTERVAL_S = 120


class ReadyGate:
    """Gate systemd ``READY=1`` on an injected health-check, re-probing until it passes.

    Construct with the ``health_check`` callable + a ``notifier`` (anything with a
    ``ready()`` method) positionally, and the optional hooks keyword-only. Drive by
    :meth:`run` with a ``threading.Event``-style ``stop``. The gate stores every
    collaborator by reference and invokes it opaquely — it never inspects the
    health result beyond ``ok`` and the neutral ``severity`` rung.
    """

    def __init__(
        self,
        health_check: Callable[[], HealthResult],
        notifier: Any,
        *,
        re_probe_interval: float = RE_PROBE_INTERVAL_S,
        on_online: Callable[..., None] | None = None,
        on_fail: Callable[[HealthResult], None] | None = None,
    ) -> None:
        self._health_check = health_check
        self._notifier = notifier
        self._re_probe_interval = re_probe_interval
        self._on_online = on_online
        self._on_fail = on_fail

    def run(self, stop) -> bool:
        """Re-probe until the health-check passes or ``stop`` is set (lifted ordering).

        On EVERY non-ok outcome the per-outcome ``on_fail`` hook fires (the app
        stamps its durable health row there, D-02a), then the startup log branches
        on the NEUTRAL ``result.severity`` rung — CRITICAL rung -> ``critical``,
        else ``warning`` — NEVER comparing ``reason`` to an app-named string. The
        re-probe wait is the interruptible ``stop.wait(interval)`` (NEVER
        ``time.sleep``, Pitfall 2): it returns True if ``stop`` was set during the
        wait, so a shutdown mid-probe breaks promptly.

        Returns ``True`` once the health-check first passes — at which point the
        gate fires the ``on_online`` hook (the app's health-row ``online`` stamp +
        tick + ping, D-02a), emits ``READY=1`` via ``notifier.ready()``, and logs
        the structured online event. Returns ``False`` if ``stop`` was set first
        (clean shutdown during the gate — the caller falls straight through without
        starting work or emitting the online signal).
        """
        while not stop.is_set():
            result = self._health_check()
            if result.ok:
                # First pass: app side-effects ride on_online (D-02a); the module
                # owns ONLY the structured log + READY=1, at this exact point so the
                # emit ordering stays byte-identical.
                self._best_effort_hook(self._on_online, result, label="on_online")
                _log.info("bot online")
                self._notifier.ready()
                return True
            # Per-outcome hook (the app's durable health row, D-02a).
            self._best_effort_hook(self._on_fail, result, label="on_fail")
            # Branch the startup log on the NEUTRAL severity rung, NOT a reason string.
            if result.severity >= Severity.CRITICAL:
                _log.critical(
                    "startup self-check critical failure",
                    reason=result.reason,
                    detail=result.detail,
                )
            else:
                _log.warning(
                    "startup self-check not ready",
                    reason=result.reason,
                    detail=result.detail,
                )
            # Interruptible re-probe wait: returns True if stop was set during the
            # wait -> clean shutdown (NEVER a blocking time.sleep, Pitfall 2).
            if stop.wait(self._re_probe_interval):
                break
        return False

    # ------------------------------------------------------------------ #
    # best-effort hook guard (cloned verbatim from ReloadEngine, D-09)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _best_effort_hook(
        hook: Callable[[Any], None] | None, arg: Any, *, label: str
    ) -> None:
        """Invoke an optional hook best-effort: a None hook is a no-op; a raise is swallowed.

        A hook failure is logged (outcome-only) and swallowed so it can NEVER mask
        the gate's own result — the online transition or the re-probe outcome.
        """
        if hook is None:
            return
        try:
            hook(arg)
        except Exception:  # noqa: BLE001 — best-effort; never mask the engine result
            _log.warning(f"{label} hook failed; engine result unaffected")
