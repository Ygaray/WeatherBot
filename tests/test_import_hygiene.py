"""The one APP-side import-hygiene invariant that survives the physical repo split.

After the Phase-28 split, the reusable core lives in its own repo
(``YahirReusableBot`` / import root ``yahir_reusable_bot``), and the module's
import-hygiene gates (grimp module→app leak scan, isolated-import blocker smoke,
AST signature litmus, and their self-proofs) now run *in that repo* against the
module source — they cannot run here, because there is no in-tree
``yahir_reusable_bot`` package to graph anymore.

What STAYS app-side is a pure APP invariant that has nothing to do with the
module boundary: the Phase-27 render-cycle was resolved by OWNERSHIP, not by a
deferred in-function import. ``render_embed`` stays app-side and is INJECTED into
the module ``PanelKit`` as ``render`` at the composition root; the module owns the
panel view. This gate is the standing SC#2 proof that neither former cycle
endpoint (``weatherbot/interactive/bot.py`` / ``panel.py``) ever reintroduces a
deferred ``import render_embed`` / ``import PanelView`` edge. It reads only app
source, so it belongs here, not in the module repo.

The self-proof discipline is preserved: the substring detector is exercised
against a synthetic source carrying a forbidden edge, so a green test proves the
check bites rather than being a no-op against an empty token set.
"""

from __future__ import annotations

from pathlib import Path

APP = "weatherbot"

# The app interactive package — the two former render-cycle endpoints live here.
_REPO_ROOT_INTERACTIVE = Path(__file__).resolve().parent.parent / APP / "interactive"


def test_no_deferred_cycle_import_survives_in_app_interactive():
    """SC#2: ``bot.py``/``panel.py`` carry NO ``import PanelView``/``import render_embed`` edge.

    The render-cycle (``render_embed`` ↔ ``PanelView``) was resolved by OWNERSHIP, not by a
    deferred in-function import: ``render_embed`` stays app-side and is INJECTED into the module
    ``PanelKit`` as ``render`` at the composition root, and the module owns the panel view. This
    gate is the explicit SC#2 proof — it reads the source of the two former cycle endpoints and
    asserts NEITHER still names an ``import`` of the other symbol. It reddens the instant either
    deferred edge is reintroduced.

    The forbidden tokens are BUILT FROM PARTS at runtime (``"import" + " " + symbol``) so this
    test's OWN source carries no literal ``import PanelView`` / ``import render_embed`` string —
    a negative-grep gate must not self-invalidate a future grep over the tests tree.
    """
    app_interactive = _REPO_ROOT_INTERACTIVE
    forbidden_symbols = ("PanelView", "render_embed")
    # Reconstruct the forbidden edge tokens without inlining them as literals (so a future
    # grep over tests/ for the cycle edge does not trip on this guard's own source).
    _imp = "import"
    forbidden_edges = [f"{_imp} {sym}" for sym in forbidden_symbols]

    offenders: list[tuple[str, str]] = []
    for fname in ("bot.py", "panel.py"):
        src = (app_interactive / fname).read_text(encoding="utf-8")
        for edge in forbidden_edges:
            if edge in src:
                offenders.append((fname, edge))
    assert offenders == [], (
        "a deferred render-cycle import edge survives the relocation (SC#2 violated): "
        f"{offenders}"
    )

    # Self-proof: the SAME substring detector flags a synthetic source that DOES carry a
    # forbidden edge — proving the check bites (it is not a no-op against an empty token set).
    synthetic = f"from x {forbidden_edges[1]}\n"  # a fabricated deferred render_embed import
    synthetic_hits = [e for e in forbidden_edges if e in synthetic]
    assert synthetic_hits == [forbidden_edges[1]], (
        "self-proof broken: the cycle-edge detector must flag a synthetic forbidden import"
    )


# --- Phase 32 / HARD-TZ-04: ONE shared local-date helper (D-08/F69) ----------
# Wave-0 failing-first (RED) regression tests. They pin the CORRECT-but-not-yet-
# implemented state; plan 32-02 (creates weatherbot/weather/dates.py) + 32-04
# (swaps the three call sites) turn them GREEN. It is EXPECTED that they FAIL now:
# the import-hygiene gate fails an assertion (the three files still define their own
# ``_local_date_iso`` and do NOT import ``weatherbot.weather.dates``), and the
# same-output test fails on ImportError because ``dates.py`` does not exist yet.

_APP_ROOT = Path(__file__).resolve().parent.parent / APP

# The three modules that today carry divergent ``_local_date_iso`` copies (F69).
_DATES_CALLERS = (
    "weather/models.py",
    "weather/store.py",
    "scheduler/uvmonitor.py",
)


def test_dates_single_helper_no_local_copies():  # D-08 / F69
    """``models``, ``store``, ``uvmonitor`` all resolve local date through the ONE
    ``weatherbot.weather.dates`` helper — none still defines its own ``_local_date_iso``.

    F69: three verbatim/near-verbatim ``def _local_date_iso(`` copies (models.py:69,
    store.py:210, uvmonitor.py:84) can drift so the rendered ``{date}`` and the stored
    ``local_date`` key disagree. The D-08 fix collapses them into ONE pure
    ``weatherbot.weather.dates`` helper imported by all three. This source-reading gate
    reddens until that unification lands.
    """
    # Build the forbidden own-definition token from parts so this test's OWN source
    # carries no literal ``def _local_date_iso(`` (a negative-grep gate must not
    # self-invalidate a future grep over tests/).
    own_def = "def " + "_local_date_iso("
    dates_import = "weatherbot.weather.dates"

    offenders_own_def: list[str] = []
    missing_import: list[str] = []
    for rel in _DATES_CALLERS:
        src = (_APP_ROOT / rel).read_text(encoding="utf-8")
        if own_def in src:
            offenders_own_def.append(rel)
        if dates_import not in src:
            missing_import.append(rel)

    assert offenders_own_def == [], (
        "these files must NOT define their own _local_date_iso (D-08): "
        f"{offenders_own_def}"
    )
    assert missing_import == [], (
        "these files must import the shared weatherbot.weather.dates helper (D-08): "
        f"{missing_import}"
    )


def test_dates_helper_same_output_and_deterministic():  # D-08 / HARD-TZ-04
    """The shared ``dates`` helper is pure: ``local_date_for(location, now)`` agrees
    with ``local_date_iso(now, tz)`` for the same ``(now, tz)``, is deterministic
    (idempotent — same inputs → same output, no shared state), and treats a naive
    ``now`` as UTC (D-06).

    RED today because ``weatherbot/weather/dates.py`` does not exist yet — the import
    inside the test body raises ``ModuleNotFoundError`` (an acceptable RED for this
    Wave-0 test; it becomes an assertion once plan 32-02 lands the module).
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from weatherbot.config.models import Location
    from weatherbot.weather.dates import local_date_for, local_date_iso

    tz = ZoneInfo("America/New_York")
    loc = Location(name="NY", lat=40.7128, lon=-74.006, timezone="America/New_York")

    # An aware UTC instant that lands on 2024-06-13 local in NY (23:30 EDT).
    now = datetime(2024, 6, 14, 3, 30, tzinfo=timezone.utc)

    # The wrapper (Location-resolving) and the primitive (tz) agree for the same input.
    assert local_date_for(loc, now) == local_date_iso(now, tz) == "2024-06-13"

    # Deterministic / idempotent: repeated calls with the same inputs give the same
    # output and never mutate shared state (safe under the daemon/UV-tick/heartbeat).
    assert local_date_iso(now, tz) == local_date_iso(now, tz)
    assert local_date_for(loc, now) == local_date_for(loc, now)

    # D-06: a NAIVE now is treated as UTC (not host-local) → same 2024-06-13 date.
    naive = datetime(2024, 6, 14, 3, 30)  # naive — no tzinfo.
    assert local_date_iso(naive, tz) == "2024-06-13"
