"""Static systemd-unit directive assertions (Plan 29-02, Wave 0 — HARD-STARTUP-03 / D-05).

These tests read ``deploy/weatherbot.service`` from the repo root and pin the three
D-05 restart-policy directives that 29-06 amends the unit to satisfy:

1. ``Restart=on-failure`` present AND ``Restart=always`` absent — so a clean exit
   (exit 0) does NOT trigger a restart, while a fatal exit (non-zero, from the
   HARD-STARTUP-02 config-invalid path) DOES. Paired with the fatal-vs-clean exit
   code the daemon now returns, this is what makes systemd honor the distinction.
2. ``StartLimitIntervalSec=300`` + ``StartLimitBurst=5`` in the ``[Unit]`` section
   specifically (Pitfall 3: systemd SILENTLY IGNORES StartLimit* placed in
   ``[Service]``, so a wrong-section directive defeats the crash-loop bound — T-29-04).
3. ``TimeoutStartSec=infinity`` STILL present (D-05 must not regress the transient
   deferred-online path — the gate can legitimately wait minutes-to-hours; a finite
   start timeout + a restart policy would turn that wait into a disguised crash-loop).

These are RED until 29-06 amends the unit — that is EXPECTED within Wave 0. They are
the phase gate for the unit edit (the live redeploy effect is a deferred Gate-2
human-UAT item, but the static directive check gates the phase now): they encode the
exact directive assertions and flip to XPASS the moment 29-06 amends the unit, at
which point the ``xfail`` marker is removed and they become the standing green gate.

The two impl-dependent cases carry ``xfail(strict=False)`` — NOT to soften the gate,
but to keep the milestone's execution-only chain at suite ``exit 0`` (the same
invariant 29-01 held), exactly as the Wave-0 RED contract directs when a hard red
would otherwise break the suite run. The assertion bodies are unchanged, so they
still fully encode the D-05 directive contract; ``strict=False`` lets the flip to
green surface as XPASS (a visible "29-06 landed" signal) rather than an error.

The parse is a small SECTION-AWARE line-scan (not ``configparser``, which chokes on
systemd's duplicate keys) resolved via a repo-root-relative path so it is
cwd-independent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Impl lands in 29-06 (the amended systemd unit). Kept xfail(strict=False) to hold
# the suite at exit 0 for the execution-only chain; remove the marker when 29-06
# amends deploy/weatherbot.service (they then become standing green directive gates).
_lands_in_29_06 = pytest.mark.xfail(
    strict=False,
    reason="restart-policy directives (Restart=on-failure + StartLimit*) land in 29-06",
)

_SERVICE_UNIT = (
    Path(__file__).resolve().parents[1] / "deploy" / "weatherbot.service"
)


def _parse_sections(text: str) -> dict[str, list[str]]:
    """Split a systemd unit into ``{section: [raw directive lines]}``.

    A line-scan keyed on ``[Section]`` headers. Comment (``#``) and blank lines are
    dropped; every other line is attributed to the CURRENT section. Duplicate keys
    (which systemd allows and ``configparser`` rejects) are preserved as list entries.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _read_sections() -> dict[str, list[str]]:
    assert _SERVICE_UNIT.exists(), f"missing systemd unit: {_SERVICE_UNIT}"
    return _parse_sections(_SERVICE_UNIT.read_text(encoding="utf-8"))


@_lands_in_29_06
def test_service_restart_on_failure():
    """D-05: Restart=on-failure present, Restart=always absent (across all sections).

    A clean exit (0) must NOT restart; only a fatal (non-zero) exit does — so the
    HARD-STARTUP-02 fatal-vs-clean exit code is actually honored by systemd.
    """
    sections = _read_sections()
    all_lines = [line for lines in sections.values() for line in lines]
    assert "Restart=on-failure" in all_lines, (
        "deploy/weatherbot.service must set Restart=on-failure (D-05)"
    )
    assert "Restart=always" not in all_lines, (
        "Restart=always must be removed (a clean exit must not restart, D-05)"
    )


@_lands_in_29_06
def test_service_start_limit_in_unit_section():
    """D-05 / T-29-04 / Pitfall 3: StartLimit* MUST live in [Unit], not [Service].

    systemd silently ignores StartLimitIntervalSec/StartLimitBurst placed in
    [Service], which would defeat the crash-loop bound. Assert both are in [Unit].
    """
    sections = _read_sections()
    unit = sections.get("Unit", [])
    service = sections.get("Service", [])

    assert "StartLimitIntervalSec=300" in unit, (
        "StartLimitIntervalSec=300 must be in the [Unit] section (Pitfall 3)"
    )
    assert "StartLimitBurst=5" in unit, (
        "StartLimitBurst=5 must be in the [Unit] section (Pitfall 3)"
    )
    # And explicitly NOT mis-sectioned into [Service] (where systemd ignores them).
    assert "StartLimitIntervalSec=300" not in service, (
        "StartLimitIntervalSec must NOT be in [Service] — systemd ignores it there"
    )
    assert "StartLimitBurst=5" not in service, (
        "StartLimitBurst must NOT be in [Service] — systemd ignores it there"
    )


def test_service_keeps_timeout_start_sec_infinity():
    """D-05: TimeoutStartSec=infinity STILL present (must not regress the transient
    deferred-online protection when adding the restart policy)."""
    sections = _read_sections()
    service = sections.get("Service", [])
    assert "TimeoutStartSec=infinity" in service, (
        "TimeoutStartSec=infinity must remain in [Service] (D-05 / Pitfall 2)"
    )
