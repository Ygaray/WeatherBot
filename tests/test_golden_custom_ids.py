"""Byte-exact ``custom_id`` pins for the persistent panel (Plan 21-02, D-02/D-03).

Every panel component carries a static ``wb:``-prefixed ``custom_id`` — these strings ARE
the panel's post-restart routing contract (``add_view`` re-binds callbacks purely by
``custom_id``) AND the unforgeable ``_PANEL_MARKER`` the ``!panel`` summon scan keys on. A
single byte flip in any id silently breaks routing or the owned-panel match while every
intent-level panel test stays green — exactly what a Phase-27 re-home could introduce.

Two pins (D-02/D-03):

1. An INLINE-literal pin of the first child's ``custom_id`` (``wb:loc:select``) — the
   human-readable D-03 anchor that names the exact expected string in the test source.
2. A raw-bytes golden of the FULL ordered id set joined by newline
   (``SingleFileSnapshotExtension`` via the ``bytes_snapshot`` fixture) — order-preserving
   and byte-exact, so a single flipped byte OR a reordered child fails (D-02).

The view is built gateway-free via the shipped ``test_panel.py`` stand-ins
(``_make_panel`` / ``_FakeHolder`` / ``_SpyCache``) — no discord gateway, no network. No
secret enters the ids (placeholder location names only).
"""

from __future__ import annotations

from tests.test_panel import _FakeHolder, _SpyCache, _make_panel
from weatherbot.interactive import panel


def _panel_view():
    """Build a real ``PanelView`` gateway-free (two placeholder locations)."""
    return _make_panel(panel, holder=_FakeHolder(["home", "travel"]), cache=_SpyCache())


def test_first_child_custom_id_is_loc_select():
    """D-03: the first panel child's ``custom_id`` is exactly ``wb:loc:select`` (inline pin).

    An inline literal (not a snapshot) so the expected marker string is visible right here
    in the test source — the human-readable anchor for the unforgeable ``wb:`` panel marker.
    """
    view = _panel_view()
    assert view.children[0].custom_id == "wb:loc:select"


def test_all_custom_ids_byte_golden(bytes_snapshot):
    """D-02: the FULL ordered set of child ``custom_id``s is byte-identical to the golden.

    Joins every child ``custom_id`` (in child order) by newline and pins the raw bytes via
    ``SingleFileSnapshotExtension`` — a single byte flip in ANY id, or a reordered child,
    fails the comparison. This is the load-bearing routing/marker contract the later
    Discord-adapter extraction (Phase 27) re-runs.
    """
    view = _panel_view()
    ids = [c.custom_id for c in view.children]
    assert "\n".join(ids).encode() == bytes_snapshot(name="all_custom_ids")
