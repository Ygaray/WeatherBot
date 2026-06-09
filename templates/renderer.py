"""Guarded plain-text template renderer (D-01/02/03/04).

Renders an editable ``.txt`` briefing template by substituting the flat
``str -> str`` placeholder map from ``Forecast.placeholders()`` into
``{placeholder}`` fields. Substitution runs NO arbitrary logic:

* it uses a guarded ``_Safe`` mapping over ``string.Formatter().vformat`` — never
  unpacking a real object into ``str.format`` (which would expose attribute/index
  access and enable format-string injection on a user-editable template, T-03-02)
  and never ``eval``;
* a missing/typo'd placeholder stays VISIBLE as ``{key}`` rather than crashing
  the send or rendering blank (T-03-03).

The ``render(template_text, values) -> str`` signature is the STABLE seam Phase 2
extends (D-04): TMPL-02's strict missing-field validation wraps this, it does not
replace it.
"""

from __future__ import annotations

import string
from pathlib import Path

# Default location of the editable template files (D-01: top-level templates/).
TEMPLATES_DIR = Path(__file__).resolve().parent


class _Safe(dict):
    """Mapping whose missing keys render visibly instead of raising.

    A typo'd or not-yet-supplied placeholder stays as the literal ``{key}`` so a
    misconfigured template is obvious in the delivered message rather than
    silently blank or a crash at send time (T-03-03).
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template_text: str, values: dict) -> str:
    """Substitute ``{placeholder}`` fields in ``template_text`` from ``values``.

    ``values`` is a flat ``str -> str`` whitelist (e.g. ``Forecast.placeholders()``).
    Guarded: missing keys stay visible; no attribute/index access; no ``eval``.
    """
    return string.Formatter().vformat(template_text, (), _Safe(values))


def load_template(name: str, templates_dir: str | Path = TEMPLATES_DIR) -> str:
    """Read an editable template file by name from ``templates_dir``."""
    path = Path(templates_dir) / name
    return path.read_text(encoding="utf-8")
