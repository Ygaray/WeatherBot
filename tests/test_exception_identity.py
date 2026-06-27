"""Exception-identity pins for every move-path error type (D-13 / SC3).

Each move-path error type is pinned with TWO asserts (D-13):

1. **``is``-identity through the caller's import path** — import the type the same
   way the catching code does (``import httpx``; ``from tenacity import RetryError``;
   ``from weatherbot.interactive.lookup import UnknownLocationError``) and assert it
   ``is`` the canonical object. This is the tightest guard: a later *broadened*
   ``except`` cannot swallow a type whose identity is pinned here.
2. **Frozen ``(__module__, __qualname__)`` tuple** — turns the fully-qualified name
   into the literal under test, so a re-home/rename fails with a crisp old-vs-new diff
   rather than silently slipping through an output golden.

A subclass/instance check is deliberately **NOT** used as the pin: it permits the
very ``except``-broadening this file guards against (a subclass would still pass).

All tuples below were verified empirically against the installed dependency
versions (see PATTERNS.md § test_exception_identity.py). Two values are load-bearing:

- ``pydantic.ValidationError`` lives in ``pydantic_core._pydantic_core`` (pydantic v2
  re-exports it from ``pydantic``); the frozen tuple pins the REAL module, not
  ``"pydantic"`` (the RESEARCH row was wrong — PATTERNS corrected it).
- ``UnknownLocationError`` is the one app-defined type that **re-homes in Phase 26**.
  Pinning ``("weatherbot.interactive.lookup", "UnknownLocationError")`` makes that move
  fail loud so the catch contract is re-pointed deliberately, not silently broken.

Pure type introspection — no I/O, no network, no snapshot file.
"""

from __future__ import annotations

import discord
import httpx
from pydantic import ValidationError
from tenacity import RetryError

from weatherbot.interactive.lookup import UnknownLocationError


# ---------------------------------------------------------------------------
# httpx move-path errors — caught in reliability/retry.py + cli.py via `import httpx`
# ---------------------------------------------------------------------------


def test_httpstatuserror_identity() -> None:
    from httpx import HTTPStatusError

    # (1) is-identity through the caller's import path
    assert HTTPStatusError is httpx.HTTPStatusError
    # (2) frozen (__module__, __qualname__) — a re-home/rename fails loud
    assert (HTTPStatusError.__module__, HTTPStatusError.__qualname__) == (
        "httpx",
        "HTTPStatusError",
    )


def test_timeoutexception_identity() -> None:
    from httpx import TimeoutException

    assert TimeoutException is httpx.TimeoutException
    assert (TimeoutException.__module__, TimeoutException.__qualname__) == (
        "httpx",
        "TimeoutException",
    )


def test_connecterror_identity() -> None:
    from httpx import ConnectError

    assert ConnectError is httpx.ConnectError
    assert (ConnectError.__module__, ConnectError.__qualname__) == (
        "httpx",
        "ConnectError",
    )


def test_readerror_identity() -> None:
    from httpx import ReadError

    assert ReadError is httpx.ReadError
    assert (ReadError.__module__, ReadError.__qualname__) == (
        "httpx",
        "ReadError",
    )


# ---------------------------------------------------------------------------
# discord move-path errors — caught via `import discord`; live in discord.errors
# ---------------------------------------------------------------------------


def test_loginfailure_identity() -> None:
    from discord import LoginFailure

    assert LoginFailure is discord.LoginFailure
    assert (LoginFailure.__module__, LoginFailure.__qualname__) == (
        "discord.errors",
        "LoginFailure",
    )


def test_forbidden_identity() -> None:
    from discord import Forbidden

    assert Forbidden is discord.Forbidden
    assert (Forbidden.__module__, Forbidden.__qualname__) == (
        "discord.errors",
        "Forbidden",
    )


# ---------------------------------------------------------------------------
# tenacity move-path error — caught via `from tenacity import RetryError`
# ---------------------------------------------------------------------------


def test_retryerror_identity() -> None:
    from tenacity import RetryError as RetryErrorLocal

    assert RetryErrorLocal is RetryError
    assert (RetryError.__module__, RetryError.__qualname__) == (
        "tenacity",
        "RetryError",
    )


# ---------------------------------------------------------------------------
# pydantic move-path error — caught via `from pydantic import ValidationError`
# CRITICAL: __module__ is pydantic_core._pydantic_core, NOT "pydantic" (v2 re-export)
# ---------------------------------------------------------------------------


def test_validationerror_identity() -> None:
    from pydantic import ValidationError as ValidationErrorLocal

    assert ValidationErrorLocal is ValidationError
    # ⚠ The real home is pydantic_core._pydantic_core (pydantic v2 re-exports it).
    assert (ValidationError.__module__, ValidationError.__qualname__) == (
        "pydantic_core._pydantic_core",
        "ValidationError",
    )


# ---------------------------------------------------------------------------
# app-defined move-path error — LOAD-BEARING: re-homes in Phase 26.
# Caught in cli.py via `from weatherbot.interactive.lookup import UnknownLocationError`.
# ---------------------------------------------------------------------------


def test_unknownlocationerror_identity() -> None:
    from weatherbot.interactive.lookup import (
        UnknownLocationError as UnknownLocationErrorLocal,
    )

    assert UnknownLocationErrorLocal is UnknownLocationError
    # When Phase 26 moves this type, the frozen tuple fails loud so the catch
    # contract gets re-pointed deliberately rather than silently broadened.
    assert (
        UnknownLocationError.__module__,
        UnknownLocationError.__qualname__,
    ) == ("weatherbot.interactive.lookup", "UnknownLocationError")


# ---------------------------------------------------------------------------
# D-13 behavioral backstop — raise a REAL httpx.HTTPStatusError(429) through the
# reliability classifier and assert it's classified transient. Pins the catch
# contract end-to-end, alongside (not replacing) the identity pins above.
# ---------------------------------------------------------------------------


def test_real_429_classifies_transient() -> None:
    from weatherbot.reliability.retry import is_transient

    request = httpx.Request("GET", "https://example.test/owm")
    response = httpx.Response(429, request=request)
    exc = httpx.HTTPStatusError("rate limited", request=request, response=response)

    assert is_transient(exc) is True
