"""WeatherBot package.

Sets a project-wide structlog default that renders to STDERR (not STDOUT). This is
a correctness requirement, not cosmetics: the ``weather`` one-shot prints the briefing
to STDOUT (CMD-01, pipeable), so any log line must stay off STDOUT or it pollutes the
briefing. structlog's library default renders to STDOUT and ignores the stdlib level;
the CLI's ``_configure_logging`` further tunes the effective level per subcommand (D-09),
but this baseline guarantees logs go to STDERR for every entry path (CLI, daemon, tests).

The logger factory writes through a thin proxy that resolves ``sys.stderr`` lazily on
every write, so the binding survives test harnesses (pytest ``capsys``) that swap
``sys.stderr`` per test — a fixed stream reference would raise "I/O operation on closed
file" once the captured stream is torn down.
"""

from __future__ import annotations

import logging
import sys

import structlog


class _LiveStderr:
    """A file-like proxy that always forwards to the CURRENT ``sys.stderr``.

    structlog's ``PrintLoggerFactory`` binds its target stream once at configure time.
    Binding the live ``sys.stderr`` object directly breaks under pytest ``capsys`` (which
    replaces ``sys.stderr`` per test, then closes it). Resolving ``sys.stderr`` on each
    ``write``/``flush`` keeps logging correct across stream swaps.
    """

    def write(self, data: str) -> int:
        return sys.stderr.write(data)

    def flush(self) -> None:
        sys.stderr.flush()


structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(file=_LiveStderr()),
    cache_logger_on_first_use=False,
)
