"""The D-02 ``days`` vocabulary: validate + normalize to an APScheduler string.

This module is intentionally dependency-free (no config, no apscheduler import)
so ``weatherbot.config.models`` can import ``parse_days`` from it without an
import cycle. ``parse_days`` is the single source of truth for the day-of-week
grammar shared by the config model, the live cron trigger, and the catch-up
planner (Plan 03) — so the planner and the trigger can never disagree.

The ``day_of_week`` grammar (``"mon"``, ``"sat,sun"``, ``"mon-fri"``,
``"mon-sun"``) is exactly what APScheduler 3.x ``CronTrigger`` accepts natively
(CITED: apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html).
"""

from __future__ import annotations

# Friendly presets normalize to an APScheduler ``day_of_week`` string (D-02).
_PRESETS = {
    "daily": "mon-sun",
    "weekdays": "mon-fri",
    "mon-fri": "mon-fri",
    "weekends": "sat,sun",
}

# The seven valid day tokens for a comma list (Monday-first, APScheduler order).
_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def parse_days(raw: str) -> str:
    """Validate + normalize the D-02 ``days`` vocabulary.

    Accepts a preset (``daily``/``weekdays``/``mon-fri``/``weekends``) or a
    comma-separated list of day tokens (``mon``..``sun``), case- and
    whitespace-insensitive. Returns a normalized APScheduler ``day_of_week``
    string. Raises ``ValueError`` (listing the allowed presets + day tokens)
    on an empty value or any unknown token, so a bad config token fails loud
    at load (mirrors ``Location._units_valid``, D-02).
    """
    key = raw.strip().lower()
    if key in _PRESETS:
        return _PRESETS[key]
    tokens = [t.strip() for t in key.split(",") if t.strip()]
    bad = [t for t in tokens if t not in _DAYS]
    if not tokens or bad:
        raise ValueError(
            f"invalid days value {raw!r}: use a preset "
            f"({sorted(_PRESETS)}) or a comma list of {sorted(_DAYS)}"
        )
    return ",".join(tokens)
