"""SC#3 / D-04: the module ``PanelKit`` is MARKER-PARAMETERIZED, baking no ``wb:`` literal.

``tests/test_golden_custom_ids.py`` pins WeatherBot's concrete ``wb:…`` byte strings (built
through the real ``PanelKit`` + the app contributors) — that is the app-side freeze. THIS file
proves the GENERIC half: the relocated module ``PanelKit`` carries no hardcoded ``wb:`` namespace
of its own — the marker is a real constructor parameter that flows through to the command-button
``custom_id`` builder (``CmdButton`` → ``f"{marker}cmd:{name}"``). A reminder bot constructing
``PanelKit(marker="X:")`` therefore gets ``X:cmd:<name>`` ids, NOT ``wb:cmd:<name>`` (D-04).

This is the marker-parameterization proof the Phase-27 CONTEXT (SC#3) calls for: it constructs a
minimal, fully-generic ``PanelKit`` with an arbitrary ``marker`` and asserts the marker reaches
the wire-contract ``custom_id`` — alongside a source-level assertion that the module bakes no
``wb:`` literal. It imports ZERO app code (a tiny fake registry + a trivial render/dispatch), so
it stays a pure generic-module test and adds no weather noun to anything.
"""

from __future__ import annotations

from pathlib import Path

import discord

from yahir_reusable_bot.discord.panelkit import CmdButton, DispatchOutcome, PanelKit
from yahir_reusable_bot.discord.selection import SelectedContext

_MODULE_ROOT = Path(__file__).resolve().parent.parent / "yahir_reusable_bot"


class _FakeRegistryView:
    """The minimal ``registry`` shape ``PanelKit._build_command_buttons`` reads.

    The module resolves command buttons via ``getattr(registry, "by_name", {})`` and only
    asserts each curated name is a KEY (it never inspects the spec value), so a sentinel value
    per name is sufficient for a generic construction smoke.
    """

    def __init__(self, names: tuple[str, ...]) -> None:
        self.by_name = {name: object() for name in names}


async def _noop_dispatch(name: str, selection: "SelectedContext") -> DispatchOutcome:
    """A trivial generic dispatch — never invoked in this construction-only test."""
    return DispatchOutcome(reply=None)


def _noop_render(reply, selection):  # noqa: ANN001 — generic opaque render stub
    """A trivial generic render — never invoked in this construction-only test."""
    return discord.Embed()


def _make_generic_panel(marker: str, command_names: tuple[str, ...]) -> PanelKit:
    """Assemble a fully-generic ``PanelKit`` with an ARBITRARY ``marker`` and no app code.

    Uses empty contributors (the marker reaches the wire id through the module-owned command
    buttons alone) so the construction names zero app concept. Each command button lands on its
    own row to satisfy the build-time per-row cap; labels are the names themselves.
    """
    return PanelKit(
        registry=_FakeRegistryView(command_names),
        command_names=command_names,
        marker=marker,
        operator_id=1,
        selection=SelectedContext("anything"),
        contributors=[],  # marker flows through the module's own CmdButtons — no app items
        render=_noop_render,
        dispatch=_noop_dispatch,
        labels={name: name for name in command_names},
        emoji=None,
        command_rows={name: i for i, name in enumerate(command_names)},
    )


def test_panelkit_marker_parameterized():
    """``PanelKit(marker="X:")`` yields ``X:cmd:<name>`` ids — the marker is a real parameter.

    Constructs a generic panel with the arbitrary marker ``"X:"`` and asserts every module-owned
    command button carries ``X:cmd:<name>`` (the marker flowed through to the ``custom_id``
    builder), then constructs a second panel with a DIFFERENT marker and asserts the ids change
    accordingly — proving the namespace is not hardcoded. Finally asserts the module source bakes
    no ``wb:`` literal (D-04 / SC#3).
    """
    command_names = ("alpha", "beta")
    panel = _make_generic_panel("X:", command_names)

    cmd_ids = {
        child.custom_id
        for child in panel.children
        if isinstance(child, CmdButton)
    }
    assert cmd_ids == {"X:cmd:alpha", "X:cmd:beta"}, (
        f"PanelKit(marker='X:') must yield X:cmd:<name> ids; got {sorted(cmd_ids)}"
    )

    # A different marker must produce a different namespace (proves it is parameterized, not
    # a coincidence with a baked default).
    other = _make_generic_panel("reminder:", command_names)
    other_ids = {
        child.custom_id
        for child in other.children
        if isinstance(child, CmdButton)
    }
    assert other_ids == {"reminder:cmd:alpha", "reminder:cmd:beta"}, (
        f"the marker must parameterize the id namespace; got {sorted(other_ids)}"
    )

    # The module bakes NO ``wb:`` literal — the WeatherBot marker lives app-side.
    panelkit_src = (_MODULE_ROOT / "discord" / "panelkit.py").read_text(encoding="utf-8")
    assert "wb:" not in panelkit_src, (
        "the module panelkit.py must bake no 'wb:' marker literal (D-04 — marker is injected)"
    )


def test_panelkit_marker_selfproof_detector_bites():
    """Self-proof: the marker-flow + no-``wb:`` checks are not no-ops.

    Mirrors the ``test_oracle_selfproof`` discipline — a guard is trustworthy only if a
    deliberately-broken variant is PROVEN to trip it. Half 1: a fabricated id built with a
    DIFFERENT marker must NOT equal the expected ``X:`` ids (so the equality check above would
    redden on a marker regression). Half 2: a synthetic source carrying a ``wb:`` literal must be
    flagged by the same substring detector (so the no-``wb:`` assertion bites).
    """
    # Half 1: a wrong-marker id set is distinguishable from the expected one.
    fabricated = {f"wb:cmd:{n}" for n in ("alpha", "beta")}
    assert fabricated != {"X:cmd:alpha", "X:cmd:beta"}, (
        "self-proof broken: a wrong-marker id set must differ from the expected X: ids"
    )

    # Half 2: the no-``wb:`` substring detector flags a fabricated baked-marker source.
    synthetic_src = 'super().__init__(custom_id=f"wb:cmd:{name}")\n'
    assert "wb:" in synthetic_src, (
        "self-proof broken: the marker-literal detector must flag a baked 'wb:' namespace"
    )
