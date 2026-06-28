"""Generic health-probe result DTO for the reusable lifecycle layer (SEAM-05, D-02).

The module-side generalization of the app's classified self-check outcome. A bot
supplies a ``health_check`` callable returning a :class:`HealthResult`; the
:class:`~yahir_reusable_bot.lifecycle.ready_gate.ReadyGate` logs ``reason`` /
``detail`` OPAQUELY and branches its startup re-probe log level on the NEUTRAL
:class:`Severity` field — NEVER by comparing ``reason`` to an app-named string.

This is the crux of the litmus-clean lifecycle seam: the gate must decide
"log this failing probe at CRITICAL vs WARNING" without naming a weather concept
like ``auth_failed``. So the *severity* of a failure is carried as an explicit,
app-authored, weather-noun-free field on the result — the app classifies (its
own ``auth_failed`` -> ``Severity.CRITICAL``, transient -> ``Severity.WARNING``)
at the boundary adapter, and the module merely branches on the rung. ``reason`` /
``detail`` remain opaque passthrough the module logs but never inspects; a
reminder bot supplies its own predicate with its own reasons and the same two
rungs.

``detail`` is outcome-only (a status code / exception class name), NEVER a secret
— the contract preserved verbatim from the app-side ``CheckResult`` (T-04-01 /
T-25-03 accept).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    """Neutral failure-severity rungs the gate branches its startup log on.

    Two rungs cover today's split (the app maps its own classification onto
    them at the boundary): :attr:`WARNING` for a recoverable / transient failed
    probe (the gate logs at ``warning`` and keeps re-probing), :attr:`CRITICAL`
    for a confirmed serious failure (the gate logs at ``critical`` but, per the
    stay-alive contract, still keeps re-probing — a dead process can answer no
    future status query). The enum is ordered so ``>=`` comparisons are possible
    if more rungs are added later, but the module only distinguishes "CRITICAL
    rung vs not" today. Carries NO app/weather concept — a reminder bot reuses it
    unchanged.
    """

    WARNING = 10
    CRITICAL = 30


@dataclass(frozen=True)
class HealthResult:
    """The result of one app-provided health probe (generic, weather-noun-free).

    ``ok`` is the pass/fail flag the gate keys its online transition on.
    ``reason`` / ``detail`` are OPAQUE passthrough the gate logs but never
    compares — a bot puts whatever classification string it likes there.
    ``severity`` is the NEUTRAL field the gate branches the startup re-probe log
    level on (defaults to :attr:`Severity.WARNING`); it is only meaningful on a
    failing (``ok=False``) result.
    """

    ok: bool
    reason: str
    detail: str = ""
    severity: Severity = Severity.WARNING
