"""Loaders: read TOML config and env secrets, validate into typed objects.

``load_config`` reads ``config.toml`` with stdlib ``tomllib`` (binary mode) and
validates it into a :class:`Config`, failing loud on malformed input.
``load_settings`` constructs :class:`Settings` from env / ``.env``.
``resolve_location`` implements the ``--send-now [location]`` selection (D-07).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .models import Config, Location
from .settings import Settings


def load_config(path: str | Path) -> Config:
    """Read and validate ``config.toml`` into a :class:`Config`.

    Raises ``pydantic.ValidationError`` on malformed/missing required fields
    (fail-loud at load, never at 9am).
    """
    path = Path(path)
    with path.open("rb") as fh:  # tomllib requires binary mode
        raw = tomllib.load(fh)
    return Config.model_validate(raw)


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Construct :class:`Settings` from env / ``.env``.

    ``env_file`` overrides the default ``.env`` location (used by tests).
    """
    if env_file is not None:
        return Settings(_env_file=str(env_file))  # type: ignore[call-arg]
    return Settings()


def resolve_location(config: Config, name: str | None) -> Location:
    """Select the target location for a send (D-07).

    - ``name is None`` -> the first/default location.
    - otherwise -> case-insensitive match on ``Location.name``.
    Raises :class:`~weatherbot.interactive.lookup.UnknownLocationError` (a
    backward-compatible ``ValueError`` subclass, D-07) if no location matches, so
    the whole v1.0 path inherits the richer error while every existing
    ``except ValueError`` caller stays green (Pitfall 5).
    """
    if not config.locations:
        raise ValueError("No locations configured in config.toml")
    if name is None:
        return config.locations[0]
    target = name.strip().casefold()
    for loc in config.locations:
        if loc.name.casefold() == target:
            return loc
    # Lazy import to keep the config<-interactive edge non-cyclic: interactive
    # imports ``resolve_location`` from ``weatherbot.config`` at module top, so
    # importing the error type here at call time (not module top) avoids any
    # partial-init cycle (Pitfall 5 / T-06-07).
    from weatherbot.interactive.lookup import UnknownLocationError

    raise UnknownLocationError(name, [loc.name for loc in config.locations])


def assert_unique_names(config: Config) -> None:
    """Raise ``ValueError`` if two locations share a name (case-insensitive).

    ``resolve_location`` matches names by casefold, so duplicate names would make
    ``--send-now "<name>"`` ambiguous. This fail-loud helper is run at config load
    (and by ``--check``) so a duplicate is caught at setup, never at 9am.
    """
    seen: dict[str, str] = {}
    for loc in config.locations:
        key = loc.name.casefold()
        if key in seen:
            raise ValueError(
                f"Duplicate location name {loc.name!r} "
                f"(collides with {seen[key]!r}); location names must be unique."
            )
        seen[key] = loc.name
