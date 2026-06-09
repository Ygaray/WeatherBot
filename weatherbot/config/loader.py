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
    Raises ``ValueError`` with a clear message if no location matches.
    """
    if not config.locations:
        raise ValueError("No locations configured in config.toml")
    if name is None:
        return config.locations[0]
    target = name.strip().casefold()
    for loc in config.locations:
        if loc.name.casefold() == target:
            return loc
    known = ", ".join(loc.name for loc in config.locations)
    raise ValueError(f"No location named {name!r}; configured locations: {known}")
