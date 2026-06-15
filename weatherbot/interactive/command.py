"""The pure, surface-agnostic ``weather <loc>`` command parser (D-01).

``parse_weather_command`` is the single source of truth for "is this a weather
command, and what location did they ask for?". It is **parse-don't-validate**
(D-01): it classifies raw command text and extracts the raw location string, but
it imports no ``Config`` and validates nothing against configured locations — the
"unknown location" signal stays distinct downstream (CMD-04). The Phase 7 CLI and
the Phase 11 Discord bot both feed raw text here and get identical semantics.

Security (T-06-01): the parser only uses ``str.strip``/``str.casefold``/slicing.
It never interpolates the user string through ``str.format``/``eval``/``exec`` or
a shell. A word-boundary guard (Open Question 2 / Pitfall 2, T-06-02) requires
whitespace after the keyword, so briefing-shaped text ("weather: ...") and words
like "weatherman" are classified ``NOT_A_COMMAND`` and cannot trip a fetch loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

_KEYWORD = "weather"


class CommandKind(Enum):
    """The three states a parsed command text can resolve to.

    ``NOT_A_COMMAND`` — the text is not a weather command at all.
    ``DEFAULT`` — bare ``weather`` keyword; caller should use its default location.
    ``LOCATED`` — ``weather <loc>``; the raw location substring is in ``location``.
    """

    NOT_A_COMMAND = auto()
    DEFAULT = auto()
    LOCATED = auto()


@dataclass(frozen=True)
class Command:
    """Result of parsing raw command text.

    ``location`` is the RAW (case-preserved) location substring for ``LOCATED``
    and ``None`` otherwise. Validation/normalization happens later (D-04).
    """

    kind: CommandKind
    location: str | None = None


def parse_weather_command(text: str) -> Command:
    """Classify raw command ``text`` into one of three states (parse-don't-validate, D-01).

    The keyword is matched case-insensitively (D-04); the extracted location keeps
    its raw case. A word-boundary guard requires whitespace to follow the keyword,
    so "weatherman" / "weather:" are ``NOT_A_COMMAND`` (Open Question 2, T-06-02).
    """
    stripped = text.strip()
    if not stripped.casefold().startswith(_KEYWORD):
        return Command(CommandKind.NOT_A_COMMAND)

    rest = stripped[len(_KEYWORD) :]
    # Word-boundary guard: anything other than whitespace right after the keyword
    # (e.g. "weatherman", "weather:") is not the command.
    if rest and not rest[0].isspace():
        return Command(CommandKind.NOT_A_COMMAND)

    location = rest.strip()
    if not location:
        return Command(CommandKind.DEFAULT)
    return Command(CommandKind.LOCATED, location=location)
