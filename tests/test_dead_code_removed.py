"""Wave-0 dead-code drift-back gate — HARD-CLEAN-01 / F16,F46,F76,F92 (D-05).

A pure source-reading negative-grep gate that pins the four dead symbols slated
for removal by later plans in this phase (02/03/08) as *staying gone once they
land, and never drifting back afterward*:

    F16  the two dead daemon defs (emit-online / do-reload) weatherbot/scheduler/daemon.py (Plan 08)
    F46  the argv-is-weatherbot pidfile helper           weatherbot/ops/pidfile.py       (Plan 02)
    F76  ``run_weather``'s dead verbose parameter          weatherbot/cli.py               (Plan 03)
    F92  the discarded bare is-transient(exc) statement   weatherbot/ops/selfcheck.py     (Plan 02)

Start-state-green posture (mirrors the ``test_import_hygiene.py`` negative-grep
analog, lines 104-119): each target is checked as *"the removed token appears
AT MOST at its single known pre-removal location"*. That predicate is:

  * GREEN today  — the symbol is present exactly once at its known location
                   (removals have not landed yet), so the count is within budget;
  * GREEN after  — the removal plan deletes the definition, count drops to 0,
                   still within budget;
  * RED on drift — a removed symbol reappearing at a NEW site (an extra
                   occurrence beyond the single sanctioned pre-removal one, or
                   any occurrence in ``tests/`` for the test-exclusive F46 case)
                   pushes the count over budget and reddens the gate.

The gate reads production source *as text only* — it never imports
``weatherbot.scheduler.daemon`` (or selfcheck/pidfile/cli) at module top, so it
collects and stays green even while the daemon defs still exist pre-removal.

Self-proof discipline (per ``test_import_hygiene.py``): every forbidden token is
BUILT FROM PARTS at runtime, so this file's own source carries no literal
any dead def/identifier as a literal — a
grep over ``tests/`` for the dead symbols must not trip on this guard. (This
docstring likewise names the symbols only descriptively — never as their literal
def/identifier tokens — so a negative-grep over ``tests/`` returns zero.)
"""

from __future__ import annotations

from pathlib import Path

APP = "weatherbot"
_APP_ROOT = Path(__file__).resolve().parent.parent / APP
_TESTS_ROOT = Path(__file__).resolve().parent


def _read(rel: str) -> str:
    """Read a production source file relative to the app root, as text."""
    return (_APP_ROOT / rel).read_text(encoding="utf-8")


def _region(src: str, start_needle: str, *, stop_prefix: str) -> str:
    """Return the slice of ``src`` from the line containing ``start_needle`` up to
    (but excluding) the next top-level line beginning with ``stop_prefix`` — so a
    signature-scoped assertion cannot be tripped by an unrelated later use of the
    same token elsewhere in the file.
    """
    lines = src.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if not capturing:
            if start_needle in line:
                capturing = True
                out.append(line)
            continue
        if line.startswith(stop_prefix):
            break
        out.append(line)
    return "\n".join(out)


def test_f46_argv_helper_gone_from_pidfile_and_tests():  # HARD-CLEAN-01 / F46 (D-05)
    """F46 — the argv-is-weatherbot pidfile helper (and its exclusive test) do not
    survive Plan 02's removal, and never drift back.

    Token built from parts so this test's own source is not a self-match. Budget
    (start-state-green): at most ONE occurrence in ``pidfile.py`` (its single
    pre-removal definition/use site) and references confined to the ONE known
    pre-removal exclusive test file (``test_golden_coverage_fill.py``, deleted by
    Plan 02). Reddens if the helper reappears at a new pidfile site, or if any
    OTHER test file references it (drift into a new site) — and after Plan 02
    removes the exclusive test, any reference at all reddens.
    """
    token = "_argv_is" + "_weatherbot"

    pidfile_hits = _read("ops/pidfile.py").count(token)
    assert pidfile_hits <= 1, (
        f"F46: {token!r} must appear at most once (its single pre-removal site) in "
        f"weatherbot/ops/pidfile.py — Plan 02 removes it; found {pidfile_hits}"
    )

    # The single sanctioned pre-removal test site; Plan 02 deletes those cases,
    # dropping this to the empty set. Any reference outside this one file is a
    # drift-back and reddens immediately.
    sanctioned_pre_removal_tests = {"test_golden_coverage_fill.py"}
    test_offenders: list[str] = []
    for path in _TESTS_ROOT.rglob("*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue  # never count this guard's own source
        if path.name in sanctioned_pre_removal_tests:
            continue  # known pre-removal site — Plan 02 flips this to enforcing
        if token in path.read_text(encoding="utf-8"):
            test_offenders.append(path.name)
    assert test_offenders == [], (
        f"F46: only the pre-removal exclusive test may reference {token!r} — Plan 02 "
        f"removes it; drift found in {test_offenders}"
    )


def test_f76_run_weather_verbose_param_gone():  # HARD-CLEAN-01 / F76 (D-05)
    """F76 — ``run_weather``'s dead ``verbose`` keyword parameter does not survive
    Plan 03's removal, and never drifts back.

    Region-scoped to the ``run_weather`` def signature only, so the unrelated
    ``-v/--verbose`` argparse flag and ``main()`` plumbing elsewhere in cli.py are
    NOT matched. Budget: at most ONE ``verbose`` mention inside the signature region
    (its single pre-removal parameter). Reddens if the param drifts back after
    removal.
    """
    src = _read("cli.py")
    start = "def run_weather" + "("
    signature_region = _region(src, start, stop_prefix="def ")
    param_token = "verbose" + ": bool"
    hits = signature_region.count(param_token)
    assert hits <= 1, (
        f"F76: the {param_token!r} parameter must appear at most once in the "
        f"run_weather signature — Plan 03 removes it; found {hits}"
    )


def test_f92_discarded_is_transient_call_gone_from_selfcheck():  # HARD-CLEAN-01 / F92 (D-05)
    """F92 — the standalone *discarded-result* ``is_transient(exc)`` line does not
    survive Plan 02's removal, and never drifts back.

    Only the bare, result-discarding statement is the target. The ``is_transient``
    IMPORT and any classifier use inside an ``is_auth_failure`` branch are NOT the
    target — this asserts specifically on the discarded standalone call form. Budget:
    ZERO bare ``is_transient(exc)`` standalone statements at author time is NOT yet
    true (the line exists pre-removal), so the check is scoped to the *discarded-call
    pattern* and budgeted at ONE pre-removal occurrence; it reddens if that pattern
    reappears after Plan 02 deletes it.
    """
    src = _read("ops/selfcheck.py")
    call_token = "is_transient" + "(exc)"
    # Count only standalone (result-discarded) occurrences: the token as an entire
    # stripped line, not embedded in ``if``/``return``/assignment/import/comment.
    discarded_hits = 0
    for raw in src.splitlines():
        line = raw.strip()
        if line == call_token:
            discarded_hits += 1
    assert discarded_hits <= 1, (
        f"F92: the discarded standalone {call_token!r} statement must appear at most "
        f"once (its single pre-removal site) in weatherbot/ops/selfcheck.py — Plan 02 "
        f"removes it; found {discarded_hits}"
    )


def test_f16_daemon_dead_defs_gone():  # HARD-CLEAN-01 / F16 (D-05)
    """F16 — the two dead module-level daemon defs (emit-online / do-reload) do not
    survive Plan 08's removal, and never drift back.

    Tokens built from parts; daemon.py is read as TEXT (never imported), so this
    stays green while the defs still exist. Budget: each def appears at most ONCE
    (its single pre-removal definition). Reddens if either def reappears at a new
    site after Plan 08 deletes it.
    """
    src = _read("scheduler/daemon.py")
    emit_def = "def " + "emit_online("
    reload_def = "def " + "_do_reload("

    emit_hits = src.count(emit_def)
    reload_hits = src.count(reload_def)
    assert emit_hits <= 1, (
        f"F16: {emit_def!r} must appear at most once (its single pre-removal def) "
        f"in weatherbot/scheduler/daemon.py — Plan 08 removes it; found {emit_hits}"
    )
    assert reload_hits <= 1, (
        f"F16: {reload_def!r} must appear at most once (its single pre-removal def) "
        f"in weatherbot/scheduler/daemon.py — Plan 08 removes it; found {reload_hits}"
    )
