"""The ``OccurrenceStore`` port — a generic exactly-once gate (D-06/D-07).

A scheduled job that does side-effecting work (a network send) must fire at most
once per ``(job identity, occurrence)`` even across overlapping fires or a
restart mid-flight. That guard is HOST policy: where the claim row lives, what
backend enforces atomicity, and how it is keyed all belong to the app. The module
owns only the *contract*.

``OccurrenceStore`` is that contract: a :class:`typing.Protocol` exposing the
full claim lifecycle the orchestration consumes — ``claim`` (the atomic
check-and-mark taken BEFORE the side-effecting work; ``True`` iff this caller
won), ``was_fired`` (the plain read), and ``release`` (re-open a won claim when
the later work fails, so the occurrence stays re-fireable). It is a STRUCTURAL
protocol, so a host's existing ``INSERT OR IGNORE … rowcount == 1`` adapter
satisfies it without any subclassing or registration (D-08).

Neutral by construction: the host's store names its slot key after a domain
noun, but the PORT renames it to the neutral ``key`` so no domain noun appears in
the module's public name surface (the AST litmus walks this file). Argument TYPES
are likewise neutral — ``str | os.PathLike`` for the store handle, ``str`` for
the key/occurrence, ``bool``/``None`` for the results. The adapter's parameterized
``?``-only SQL is the load-bearing invariant the port preserves by NEVER inlining
a key into a query string (the host keeps its SQLi-safe binding).
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class OccurrenceStore(Protocol):
    """Generic exactly-once gate keyed on ``(handle, key, occurrence)``.

    The orchestration calls :meth:`claim` once BEFORE doing side-effecting work
    (deliver only if it won), reads with :meth:`was_fired`, and calls
    :meth:`release` to re-open the claim if that later work fails. The host
    supplies the implementation (e.g. an atomic ``INSERT OR IGNORE`` row); the
    module depends only on this structural shape.
    """

    def claim(
        self,
        handle: str | os.PathLike[str],
        key: str,
        occurrence: str,
    ) -> bool:
        """Atomically claim ``(key, occurrence)`` before the side-effecting work.

        Returns ``True`` iff THIS caller won the claim (inserted the row); a
        ``False`` means the occurrence was already claimed, so this caller must
        NOT perform the side effect. Exactly one ``True`` across concurrent claims.
        """
        ...

    def was_fired(
        self,
        handle: str | os.PathLike[str],
        key: str,
        occurrence: str,
    ) -> bool:
        """Has this ``(key, occurrence)`` already been claimed/fired? (plain read)."""
        ...

    def release(
        self,
        handle: str | os.PathLike[str],
        key: str,
        occurrence: str,
    ) -> None:
        """Re-open a previously-won claim so the occurrence can be re-fired.

        Called when the work AFTER a won claim fails, so the occurrence stays
        re-fireable on the next catch-up/retry. A no-op when no claim exists.
        """
        ...
