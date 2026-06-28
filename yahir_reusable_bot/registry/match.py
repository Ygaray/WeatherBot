"""The generic longest-keyword-first + word-boundary command matcher (D-04).

``match_command`` is the relocated, surface-agnostic text-command matcher (a verbatim
lift of the app's ``parse_command``, parameterized over the keyword-ordered specs). It
is an OPT-IN free function, not a registry method: its sole consumer is a text-command
path (a button/slash bot resolves commands by name and never needs it), so a registry
type stays decoupled from any text grammar.

Load-bearing invariants preserved exactly from the app original:

- **Longest-keyword-first** — the caller supplies the specs already ordered
  longest-name-first (e.g. via ``CommandRegistry.by_keyword_len_desc``), so a longer
  command matches before any shorter command that prefixes it.
- **Word-boundary guard** — whitespace (or end-of-string) must follow the keyword, so
  "sunny" never matches a "sun" spec and "status:" never matches a "status" spec.
- **Security** — only ``str.strip`` / ``str.casefold`` / slicing; never
  ``str.format`` / ``eval`` / ``exec``.

The matcher reads ONLY ``spec.name`` — structurally typed, so an app's richer spec
satisfies it. The app-specific flag grammar (flag parsing, cache-suffix derivation,
day-token validation) STAYS app-side and never enters this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from yahir_reusable_bot.registry.spec import CommandSpec


@dataclass(frozen=True)
class ParsedCommand:
    """Result of matching raw command text against the registered specs.

    ``spec`` is the matched :class:`CommandSpec` (``None`` when the text is not a
    registered command). ``arg`` is the RAW (case-preserved) argument substring for a
    command that carries an argument, or ``None`` for a bare command.
    """

    spec: CommandSpec | None = None
    arg: str | None = None


def match_command(text: str, specs: Iterable[CommandSpec]) -> ParsedCommand:
    """Match ``text`` against ``specs`` (longest-keyword-first, word-boundary, pure).

    Iterate the caller-supplied ``specs`` (which MUST be ordered longest-name-first)
    and return the first whose ``name`` is a casefold prefix of the stripped text
    followed by whitespace-or-end. The keyword is matched case-insensitively; the
    extracted arg keeps its RAW case. Non-command text returns ``spec=None, arg=None``.

    Pure: only ``str.strip`` / ``str.casefold`` / slicing — never ``str.format`` /
    ``eval`` / ``exec`` (the security contract carried over verbatim).
    """
    stripped = text.strip()
    folded = stripped.casefold()
    for spec in specs:
        if not folded.startswith(spec.name):
            continue
        rest = stripped[len(spec.name) :]
        # Word-boundary guard: anything other than whitespace right after the
        # keyword (e.g. "sunny", "status:") is not this command.
        if rest and not rest[0].isspace():
            continue
        arg = rest.strip() or None
        return ParsedCommand(spec=spec, arg=arg)
    return ParsedCommand(spec=None, arg=None)
