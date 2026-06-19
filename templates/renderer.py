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

# The canonical placeholder set (D-09): exactly the keys
# ``Forecast.placeholders()`` emits. A template may reference only these tokens;
# ``validate_template`` rejects anything else at load (D-10/11).
CANONICAL = {
    "temp",
    "feels_like",
    "high",
    "low",
    "rain",
    "wind",
    "humidity",
    "conditions",
    "location",
    "date",
    "hint",
    "alert",
    # Scheduler timing keys (D-12). These are NOT emitted by
    # ``Forecast.placeholders()`` (which stays weather-only) — they are merged in
    # at the render call site from ``scheduler.context.schedule_placeholders``.
    "sent_at",
    "checked_at",
    "schedule_note",
}

# Multi-day forecast token scopes (Plan 13-02), DISTINCT from CANONICAL — a
# forecast template references ONLY these, never the daily-briefing tokens.
#
# ``FORECAST_TOKENS`` is the whole-message (header/footer) scope: ``{days}`` is
# the code-built per-day block merged in at the render call site (same merge-in
# idiom as ``schedule_placeholders``), ``{notice}`` carries out-of-horizon flag
# notes (D-03), the rest is header/footer chrome.
FORECAST_TOKENS = {
    "location",
    "title",
    "range_label",
    "days",
    "footer_note",
    "notice",
}

# The per-day line-format scopes. ``DETAILED`` is the full set (D-02 "detail
# should be maximum"); ``COMPACT`` is a strict subset (label/high/low/sky only —
# compact intentionally drops rain/wind/uvi/feels/sun per D-02). These match
# ``ForecastDay.day_tokens(detailed)`` exactly (11 / 4 keys).
FORECAST_DAY_TOKENS_DETAILED = {
    "label",
    "high",
    "low",
    "sky",
    "rain",
    "wind",
    "uvi",
    "feels_high",
    "feels_low",
    "sunrise",
    "sunset",
}
FORECAST_DAY_TOKENS_COMPACT = {"label", "high", "low", "sky"}


def validate_template(template_text: str, allowed: set[str] = CANONICAL) -> None:
    """Raise ``ValueError`` on any ``{token}`` not in the canonical set (D-10).

    This WRAPS — never replaces — ``render``: it shares the exact ``_TOKEN``
    grammar so the validator and renderer agree on what a placeholder is. It is
    fired at every config load including ``--send-now`` (D-11) so a typo'd
    placeholder aborts the send loudly instead of shipping a literal token. The
    renderer's "leave unknown token visible" behavior remains as defense-in-depth.
    """
    unknown = {m.group(1) for m in _TOKEN.finditer(template_text)} - allowed
    if unknown:
        raise ValueError(
            f"Template uses unknown placeholder(s): {sorted(unknown)}. "
            f"Allowed: {sorted(allowed)}"
        )


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


def render_forecast(
    template_text: str,
    line_fmt: str,
    days: list[dict],
    header_values: dict,
    day_allowed: set[str],
) -> str:
    """Render a multi-day forecast: code-iterated per-day block + header/footer.

    The "no logic in templates" invariant (T-13-04) lives here: the per-day loop
    is in CODE, never in a template. The template owns the header/footer plus the
    single per-day ``line_fmt`` string; this helper iterates ``days`` and joins
    the rendered lines into the ``{days}`` slot.

    Both the per-day ``line_fmt`` (against ``day_allowed`` — the variant's
    ``FORECAST_DAY_TOKENS_*`` scope) and the whole-message ``template_text``
    (against ``FORECAST_TOKENS``) are validated fail-loud BEFORE any render, so a
    typo'd ``{token}`` aborts at load instead of shipping a literal (T-13-05).

    Reuses the EXISTING guarded ``validate_template``/``render`` — no second
    substitution engine, no ``str.format``/``Formatter``/``eval``.
    """
    validate_template(line_fmt, allowed=day_allowed)
    block = "\n".join(render(line_fmt, day) for day in days)
    validate_template(template_text, allowed=FORECAST_TOKENS)
    return render(template_text, {**header_values, "days": block})


def load_template(name: str, templates_dir: str | Path = TEMPLATES_DIR) -> str:
    """Read an editable template file by name from ``templates_dir``."""
    path = Path(templates_dir) / name
    return path.read_text(encoding="utf-8")
