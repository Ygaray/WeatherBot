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

from weatherbot.interactive import registry
from weatherbot.interactive.registry import CommandSpec
from weatherbot.scheduler.days import _DAYS

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


@dataclass(frozen=True)
class ParsedCommand:
    """Result of the registry-driven parse (Phase 12, CMD-09/CMD-16).

    ``spec`` is the matched :class:`~weatherbot.interactive.registry.CommandSpec`
    (``None`` when the text is not a registered command). ``arg`` is the RAW
    (case-preserved) argument substring for location-taking commands, or ``None``
    for a bare command (caller uses the default location downstream, D-01).
    """

    spec: CommandSpec | None = None
    arg: str | None = None


def parse_command(text: str) -> ParsedCommand:
    """Classify ``text`` against the command registry (parse-don't-validate, D-01).

    Iterates the registry **longest-keyword-first** so a longer command (e.g.
    ``next-cloudy``) is matched before any shorter command that prefixes it
    (Pitfall 4). The keyword is matched case-insensitively; the extracted arg keeps
    its RAW case. The SAME word-boundary guard as :func:`parse_weather_command`
    applies (whitespace must follow the keyword) so "sunny" never matches "sun"
    (T-06-02). The parser is PURE — only ``str.strip``/``str.casefold``/slicing,
    never ``str.format``/``eval``/``exec`` (the T-06-01 security contract).
    """
    stripped = text.strip()
    folded = stripped.casefold()
    for spec in registry.COMMANDS_BY_KEYWORD_LEN_DESC:
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


@dataclass(frozen=True)
class ForecastFlags:
    """Parsed result of the shared ``+day``/``-day``/``+compact`` flag grammar.

    Both the CLI and the Discord bot feed raw forecast argument text through
    :func:`parse_forecast_flags` and get this identical frozen result (Phase 6
    shared-core principle — one grammar, two surfaces).

    ``variant`` is ``"detailed"`` (the default, D-02) or ``"compact"``. ``add`` /
    ``drop`` are the raw day-token sets from ``+day`` / ``-day`` flags (validated
    against ``days._DAYS``); dedup/calendar-ordering is NOT done here — that is
    ``multiday.select_days``' job (D-03). ``location`` is the RAW (case-preserved)
    location substring, or ``None`` when only flags (or nothing) were given.
    """

    variant: str = "detailed"
    add: frozenset[str] = frozenset()
    drop: frozenset[str] = frozenset()
    location: str | None = None


def parse_forecast_flags(arg: str | None) -> ForecastFlags:
    """Parse a forecast argument string into a frozen :class:`ForecastFlags` (FCAST-03/04).

    Grammar (tokens are whitespace-separated, case-insensitive):

    - ``+compact`` / ``--compact`` → ``variant="compact"``; ``+detailed`` /
      ``--detailed`` → ``variant="detailed"`` (the default when neither is given).
    - ``+<day>`` → add the day; ``-<day>`` → drop the day. ``<day>`` MUST be one of
      the ``mon``..``sun`` abbreviations in ``days._DAYS`` (A4 — presets like
      ``weekends`` are NOT valid flag tokens); an unknown token raises a fail-loud
      ``ValueError`` listing ``sorted(_DAYS)`` (T-13-07 / V5 input validation).
    - any remaining non-flag token(s) form the LOCATION substring, joined with a
      single space and kept in RAW case (mirrors :func:`parse_command`).

    Security (T-13-07 / T-06-01): this parser only uses ``str.split`` /
    ``str.casefold`` / slicing — it never interpolates the user string through
    ``str.format`` / ``eval`` / ``exec`` or a shell.
    """
    if arg is None:
        return ForecastFlags()

    variant = "detailed"
    add: set[str] = set()
    drop: set[str] = set()
    location_parts: list[str] = []

    for token in arg.split():
        folded = token.casefold()
        if folded in ("+compact", "--compact"):
            variant = "compact"
        elif folded in ("+detailed", "--detailed"):
            variant = "detailed"
        elif folded.startswith("+"):
            add.add(_day_token(folded[1:]))
        elif folded.startswith("-"):
            # ``-`` covers both ``-day`` and the ``--day`` slice fallthrough; the
            # ``--compact``/``--detailed`` variants are handled above, so any other
            # ``--xxx`` here is treated as a (failing) day token, fail-loud.
            drop.add(_day_token(folded.lstrip("-")))
        else:
            location_parts.append(token)

    location = " ".join(location_parts) or None
    return ForecastFlags(
        variant=variant,
        add=frozenset(add),
        drop=frozenset(drop),
        location=location,
    )


def forecast_cache_suffix(command: str, flags: ForecastFlags) -> str:
    """Build the ForecastCache key suffix for a forecast command (A5 collision guard).

    The suffix encodes the command name, the variant, and the SORTED add/drop flag
    tokens so a ``!weather home`` (suffix ``None``) and a
    ``!weekday-forecast home --compact +sat`` never collide on the same location-id
    cache key. Both surfaces (CLI + Discord) derive the suffix HERE so the key can
    never drift between them.
    """
    add = ",".join(sorted(flags.add))
    drop = ",".join(sorted(flags.drop))
    return f"{command}|{flags.variant}|+{add}|-{drop}"


def _day_token(token: str) -> str:
    """Validate a ``+day``/``-day`` token against ``days._DAYS`` (fail-loud, A4)."""
    if token not in _DAYS:
        raise ValueError(
            f"unknown day flag {token!r}: use one of {sorted(_DAYS)}"
        )
    return token
