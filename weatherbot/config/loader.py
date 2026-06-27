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
    """Raise ``ValueError`` if two locations share a name OR id (case-insensitive).

    ``resolve_location`` matches names by casefold, so duplicate names would make
    ``--send-now "<name>"`` ambiguous. The ``id`` is the stable sent-log identity
    (D-01); two locations sharing an id (e.g. ``Home``/``home``) would collide on
    the exactly-once ``(location, send_time, local_date)`` key. Both checks casefold
    for the COLLISION test ONLY — the stored value stays RAW (D-01). This fail-loud
    helper is run at config load (and by ``--check``/``check-config``) so a duplicate
    is caught at setup, never at 9am.
    """
    seen: dict[str, str] = {}
    seen_id: dict[str, str] = {}
    for loc in config.locations:
        key = loc.name.casefold()
        if key in seen:
            raise ValueError(
                f"Duplicate location name {loc.name!r} "
                f"(collides with {seen[key]!r}); location names must be unique."
            )
        seen[key] = loc.name
        # ``id`` defaults to the raw name (filled by Location's after-validator),
        # so it is never None here. Casefold for the collision test only.
        id_key = loc.id.casefold()
        if id_key in seen_id:
            raise ValueError(
                f"Duplicate location id {loc.id!r} "
                f"(collides with {seen_id[id_key]!r}); location ids must be unique."
            )
        seen_id[id_key] = loc.id


def validate_config_and_templates(
    path: str | Path, templates_dir: str | Path | None = None
) -> Config:
    """The ONE shared offline config validator (D-05/D-08) — zero network, no Jinja2.

    Both ``--check-config`` (CFG-08) and the hot-reload engine (CFG-04) call this so
    a config that passes one is exactly a config the other accepts. It performs, in
    order: TOML parse + pydantic schema validation (incl. the ``id`` default) via
    :func:`load_config`; the unique name + unique id check via
    :func:`assert_unique_names`; and template-token validation via the EXISTING regex
    :func:`~templates.renderer.validate_template` (an allow-list check — NOT a Jinja2
    render). It touches NO network and never calls ``run_self_check``/``do_check``
    (Pitfall 8): it constructs a :class:`Config` only, never ``Settings``/secrets.

    The established catch set PROPAGATES so callers do reject-and-keep-old (reload) or
    report-fail (check-config):

    * ``FileNotFoundError`` — missing config OR template file,
    * ``tomllib.TOMLDecodeError`` — malformed TOML,
    * ``pydantic.ValidationError`` — missing/invalid field,
    * ``ValueError`` — duplicate name/id OR unknown template ``{token}``.
    """
    # Lazy import to mirror this module's non-cyclic import idiom (renderer pulls in
    # config-adjacent code); keeping it in-function avoids any partial-init cycle.
    from templates.renderer import (
        FORECAST_TEMPLATE_NAMES,
        FORECAST_TOKENS,
        forecast_day_allowed,
        load_template,
        validate_template,
    )

    cfg = load_config(path)
    assert_unique_names(cfg)

    def _load(name: str) -> str:
        if templates_dir is not None:
            return load_template(name, templates_dir)
        return load_template(name)

    # Validate the token set of every referenced briefing template. Today
    # ``Config.template`` is a single shared template, but build this over a SET so
    # future per-location templates extend the contract without a rewrite
    # (RESEARCH Pattern 2). These validate against the canonical briefing token set.
    referenced_templates = {cfg.template}
    for template_name in referenced_templates:
        validate_template(_load(template_name))

    # Validate every forecast template referenced by a ``location.forecast`` slot
    # (FCAST-06, Pitfall 5): a bad forecast template is rejected at load AND at reload
    # (keep-old) exactly like the briefing template — so a typo'd ``{token}`` can never
    # reach a scheduled fire. Each (kind, variant) maps (via the renderer's single
    # source of truth) to a whole-message template — validated against
    # ``FORECAST_TOKENS`` — and a sibling per-day line template — validated against the
    # variant's day-token scope. Deduplicated so two slots of the same (kind, variant)
    # validate once.
    seen_forecast: set[tuple[str, str]] = set()
    for location in cfg.locations:
        for fc in location.forecast:
            key = (fc.kind, fc.variant)
            if key in seen_forecast:
                continue
            seen_forecast.add(key)
            whole_name, line_name = FORECAST_TEMPLATE_NAMES[key]
            validate_template(_load(whole_name), allowed=FORECAST_TOKENS)
            validate_template(
                _load(line_name), allowed=forecast_day_allowed(fc.variant)
            )

    return cfg
