"""Guarded plain-text template renderer (D-01/02/03/04).

Renders an editable ``.txt`` briefing template by substituting the flat
``str -> str`` placeholder map from ``Forecast.placeholders()`` into
``{placeholder}`` fields. Substitution runs NO arbitrary logic:

* it does a plain regex substitution of ``{name}`` tokens (``name`` limited to
  word characters) against the whitelist map — it never routes the template
  through ``str.format``/``Formatter``, so ``{x.attr}``, ``{x[0]}`` and ``{0}``
  are NOT interpreted (no attribute/index/positional access, no format-string
  injection on a user-editable template, T-03-02), and never ``eval``;
* an unknown/typo'd token or an unbalanced ``{`` stays VISIBLE as written rather
  than crashing the send or rendering blank (T-03-03).

The ``render(template_text, values) -> str`` signature is the STABLE seam Phase 2
extends (D-04): TMPL-02's strict missing-field validation wraps this, it does not
replace it.
"""

from __future__ import annotations

import re
from pathlib import Path

# Default location of the editable template files (D-01: top-level templates/).
TEMPLATES_DIR = Path(__file__).resolve().parent

# A placeholder token: ``{name}`` where ``name`` is word characters only. This
# deliberately does NOT match ``{x.attr}``, ``{x[0]}``, ``{0:spec}`` or a lone
# ``{`` — those are left untouched rather than interpreted (T-03-02/T-03-03).
_TOKEN = re.compile(r"\{(\w+)\}")


def render(template_text: str, values: dict) -> str:
    """Substitute ``{placeholder}`` tokens in ``template_text`` from ``values``.

    ``values`` is a flat ``str -> str`` whitelist (e.g. ``Forecast.placeholders()``).
    Guarded: a token whose name is not in ``values`` stays VISIBLE as written; no
    attribute/index/positional access; no ``str.format``; no ``eval``.
    """

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        return str(values[key]) if key in values else match.group(0)

    return _TOKEN.sub(_sub, template_text)


def load_template(name: str, templates_dir: str | Path = TEMPLATES_DIR) -> str:
    """Read an editable template file by name from ``templates_dir``."""
    path = Path(templates_dir) / name
    return path.read_text(encoding="utf-8")
