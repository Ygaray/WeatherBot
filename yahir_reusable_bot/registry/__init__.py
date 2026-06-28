"""The generic command-registry + dispatcher mechanism (SEAM-06).

Exports the relocated, weather-noun-free registry plumbing an app registers its own
commands into: the generic :class:`CommandSpec` + :class:`DispatchContext`, the
:class:`CommandRegistry` type + :func:`build_registry` constructor entry, the opt-in
:func:`match_command` text matcher (+ its :class:`ParsedCommand` result), and the
dispatcher shell (:func:`dispatch_spec` / :func:`dispatch_reply`). Every app specific
— the command names, the handler closures, the flag grammar — is injected; the module
assembles nothing of its own (a different bot registers its own specs into the same
mechanism).
"""

from __future__ import annotations

from yahir_reusable_bot.registry.dispatch import dispatch_reply, dispatch_spec
from yahir_reusable_bot.registry.match import ParsedCommand, match_command
from yahir_reusable_bot.registry.registry import CommandRegistry, build_registry
from yahir_reusable_bot.registry.spec import CommandSpec, DispatchContext

__all__ = [
    "CommandSpec",
    "DispatchContext",
    "CommandRegistry",
    "build_registry",
    "match_command",
    "ParsedCommand",
    "dispatch_spec",
    "dispatch_reply",
]
