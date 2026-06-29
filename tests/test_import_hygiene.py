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
