"""The generic command spec + dispatch context the registry mechanism reads.

This is the module half of the relocated command registry (SEAM-06): a generic,
weather-noun-free :class:`CommandSpec` an app registers into the mechanism, plus
the :class:`DispatchContext` DTO the opaque per-command ``bind`` callable receives.

``CommandSpec`` is a verbatim genericization of the app's frozen spec (the app's
richer spec adds its own fields and satisfies this one structurally). It carries
ONLY surface-agnostic fields:

- ``name`` — the keyword every surface reads and the matcher matches.
- ``group`` — a generic help-section header string. The app fills it with its own
  section names; the module NEVER reads its value semantically (the old
  ``spec.group == "Forecast"`` coupling is gone — see ``needs_flags`` below).
- ``summary`` — the one-line help description.
- ``bind`` — an OPAQUE, app-authored callable taking a :class:`DispatchContext`
  and returning whatever the app's handler produces. The module invokes it and
  never inspects its body, args, or return — the same opaque-callable discipline
  the module already ships on ``SchedulerEngine.callback`` /
  ``ReloadEngine.validate``. This subsumes the app's old ``takes_location`` +
  ``handler`` fields: the arg-binding ladder lives inside each app ``bind`` closure.
- ``needs_flags`` — the NEUTRAL pre-dispatch signal. It replaces the dispatcher's
  old ``spec.group == "Forecast"`` read so the module's fetch path can widen the
  cache key (via app-injected hooks) without naming any app-specific group. The
  app sets it on the specs whose fetch needs the flags-parse + suffix branch.

``DispatchContext`` bundles the four values the app's ``bind`` closure needs
(``result`` / ``config`` / ``flags`` / ``daemon_state``) — exactly the four params
the app's old ``dispatch_reply`` took, kept as generic field names so a different
bot's closures read the same bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DispatchContext:
    """The generic per-call context the app's opaque ``bind`` closure receives.

    A frozen bundle of the four values an app handler may need: the (optionally)
    pre-fetched ``result``, the live ``config``, the parsed ``flags`` (``None`` for
    specs that take no flags), and the read-only ``daemon_state``. All four field
    names are generic — the module never reads them semantically; it only hands the
    bundle to ``spec.bind(ctx)``.
    """

    result: Any = None
    config: Any = None
    flags: Any = None
    daemon_state: Any = None


@dataclass(frozen=True)
class CommandSpec:
    """One registered command — the immutable, surface-agnostic spec.

    See the module docstring for the field contract. ``bind`` is opaque (the module
    invokes it, never inspects it); ``needs_flags`` is the neutral pre-dispatch
    signal that replaces any app-specific group read. The spec is frozen — mutating
    a field raises ``FrozenInstanceError``.
    """

    name: str
    group: str
    summary: str
    bind: Callable[["DispatchContext"], Any]
    needs_flags: bool = False
