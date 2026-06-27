"""The import-hygiene gates — the reusable module must never reach back into the app.

``yahir_reusable_bot`` is the clean core future bots import (D-01). Its whole value is a
ONE-WAY dependency: the host app may import the module, but no module file may ever import
``weatherbot`` (or any ``weatherbot.*`` submodule). A second, softer contract guards the
module's PUBLIC SURFACE: no ``def``/``class``/parameter/annotation NAME may carry a weather
noun (``weather|forecast|location|openweather|\\buv\\b|briefing``) — so the relocated code
reads as a generic bot core, not a weather bot in disguise (D-11/D-13). Docstrings and
comments are PROSE and are deliberately ignored (the retry engine legitimately mentions
"OpenWeather"/"Discord"/"briefing" in its prose — that is out of scope, deferred to DOCS-01).

Three standing gates enforce this, each paired with a self-proof — exactly the discipline of
``tests/test_oracle_selfproof.py``: a guard is only trustworthy if a deliberately-injected
violation is PROVEN to trip it. So every gate has TWO halves:

1. The REAL module tree must PASS the gate (the scaffold/relocated code is clean).
2. A deliberately-injected leak/noun, run through the SAME gate logic, must FAIL — wrapped in
   ``pytest.raises(AssertionError)`` (or asserting the helper flags it). The self-proofs call
   the SAME module-level helpers the gates use (``_scan_app_leaks`` / ``_public_names``), NOT a
   copy — so a green self-proof proves the REAL gate logic bites, not a parallel reimplementation.

These are ordinary STANDING pytest asserts, NOT ``xfail`` markers (an ``xfail`` reads inverted —
a "passing" expected-failure is itself a failing assertion — and was rejected for the oracle
self-proofs too). They go RED the instant a real leak/noun is introduced OR the instant a gate
is silently weakened. This file is the STANDING gate phases 23–27 re-run as each real surface
moves into the module (D-13).

The three gates are complementary:
- The grimp graph gate is STATIC — it sees module-import-time AND function-local AND
  TYPE_CHECKING edges (grimp counts TYPE_CHECKING imports by default; we KEEP that default so
  the gate catches a type-only app import — passing ``exclude_type_checking_imports=True`` would
  HIDE the very leak the gate exists for).
- The isolated-import smoke gate is DYNAMIC — it imports every module with the ``weatherbot``
  namespace blocked, catching module-import-time + TYPE_CHECKING-realized leaks loudly. (A purely
  function-local app import only trips if the function runs; the grimp static gate is the
  authority for those — that is why PKG-01 asks for both.)
- The AST litmus is a NAME scan over the public signature surface — prose-immune by construction.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
import sys
from pathlib import Path

import grimp
import pytest

MODULE = "yahir_reusable_bot"
APP = "weatherbot"

# D-13 locked litmus pattern. Known gap: ``\buv\b`` only matches a STANDALONE ``uv`` — a
# ``uv_index``-style name slips through because ``_`` is a ``\w`` char (no word boundary after
# ``uv``). This is a documented limitation, NOT a bug to fix: the pattern is the roadmap's
# locked literal (D-13). The moving code (Channel ``send(text)`` + retry primitives) has zero
# ``uv`` names, so the gate is clean today.
_LITMUS = re.compile(r"weather|forecast|location|openweather|\buv\b|briefing", re.IGNORECASE)

_MODULE_ROOT = Path(__file__).resolve().parent.parent / MODULE


# ---------------------------------------------------------------------------
# Shared gate logic — the SAME helpers the gates AND their self-proofs call.
# ---------------------------------------------------------------------------


def _scan_app_leaks(
    importers_to_targets: dict[str, set[str]],
) -> list[tuple[str, str]]:
    """Flag every (importer, imported) edge that points at the app package.

    The prefix check (``== APP`` or ``startswith(APP + ".")``) auto-scales as the module
    grows across phases 23–27 — no per-module edit. Takes a plain edge mapping so the
    self-proof can drive it with a SYNTHETIC leak set (proving the scan logic, not a copy).
    """
    leaks: list[tuple[str, str]] = []
    for importer, targets in importers_to_targets.items():
        for target in targets:
            if target == APP or target.startswith(APP + "."):
                leaks.append((importer, target))
    return leaks


def _public_names(source: str) -> list[str]:
    """Extract public SIGNATURE-surface names from Python source (NOT prose).

    Collects ``def``/``async def``/``class`` names, ``arg`` names + their unparsed
    annotations, and function return annotations. Docstrings and comments are never
    visited, so prose mentions of a weather noun are ignored by construction (D-11).
    """
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        if isinstance(node, ast.arg):
            names.append(node.arg)
            if node.annotation is not None:
                names.append(ast.unparse(node.annotation))
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.returns is not None
        ):
            names.append(ast.unparse(node.returns))
    return names


class _AppBlocker:
    """A ``sys.meta_path`` finder that raises ``ImportError`` for any app import."""

    def find_spec(self, name, path=None, target=None):  # noqa: ANN001
        if name == APP or name.startswith(APP + "."):
            raise ImportError(f"BLOCKED app import inside the reusable module: {name}")
        return None  # defer to the normal finders for everything else


# ---------------------------------------------------------------------------
# Gate 1: grimp import-graph — no module → app edge (TYPE_CHECKING incl. by default).
# ---------------------------------------------------------------------------


def test_module_imports_zero_app_code():
    """No ``yahir_reusable_bot.*`` module may directly import ``weatherbot.*`` (D-09).

    Builds the grimp import graph with the DEFAULT ``exclude_type_checking_imports=False``
    so TYPE_CHECKING edges are graphed — that is a FEATURE: the gate catches a type-only app
    import (e.g. the historic ``Forecast`` leak). The failure message includes the offending
    pair and ``get_import_details`` line numbers. On the clean scaffold there are zero leaks.
    """
    graph = grimp.build_graph(MODULE)  # TYPE_CHECKING edges included (default — KEEP it)
    edges = {
        module: graph.find_modules_directly_imported_by(module)
        for module in graph.modules
    }
    leaks = _scan_app_leaks(edges)
    detail = {
        (imp, tgt): [
            (d["line_number"], d["line_contents"])
            for d in graph.get_import_details(importer=imp, imported=tgt)
        ]
        for imp, tgt in leaks
    }
    assert leaks == [], f"reusable module imports app code: {detail}"


def test_selfproof_import_gate_catches_injected_app_edge():
    """Prove the grimp leak-scan is not a no-op: a synthetic app edge MUST be flagged.

    Drives the SAME ``_scan_app_leaks`` helper the real gate uses against a synthetic edge
    set carrying a ``(importer, "weatherbot.weather.models")`` pair (plus a benign
    third-party edge that must NOT be flagged). If the scan were ever loosened to a no-op,
    this self-proof goes RED.
    """
    synthetic = {
        "yahir_reusable_bot.channels.base": {
            "weatherbot.weather.models",  # the injected leak — must be flagged
            "httpx",  # a legitimate third-party edge — must NOT be flagged
        }
    }
    leaks = _scan_app_leaks(synthetic)
    assert leaks == [("yahir_reusable_bot.channels.base", "weatherbot.weather.models")]


# ---------------------------------------------------------------------------
# Gate 2: isolated-import smoke — import every module with `weatherbot` blocked.
# ---------------------------------------------------------------------------


def test_module_imports_with_app_blocked():
    """Every ``yahir_reusable_bot.*`` module imports cleanly with the app namespace blocked.

    Installs an ``_AppBlocker`` ``sys.meta_path`` finder that raises ``ImportError`` for any
    ``weatherbot``/``weatherbot.*`` name, then imports every module under the package via
    ``pkgutil.walk_packages``. A module-import-time OR TYPE_CHECKING-realized app import would
    raise loudly here. The ``finally:`` removes the blocker AND purges ``sys.modules`` keys
    starting with ``yahir_reusable_bot`` so other tests re-import cleanly.
    """
    blocker = _AppBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        pkg = importlib.import_module(MODULE)
        for info in pkgutil.walk_packages(pkg.__path__, prefix=MODULE + "."):
            importlib.import_module(info.name)  # raises if the module reaches app code
    finally:
        sys.meta_path.remove(blocker)
        for key in [k for k in sys.modules if k.startswith(MODULE)]:
            del sys.modules[key]


def test_selfproof_isolated_import_catches_app_import():
    """Prove the blocker actually blocks: importing app code under it MUST raise ImportError.

    With the SAME ``_AppBlocker`` installed, a FRESH resolution of a real ``weatherbot.*``
    module must raise ``ImportError``. If the blocker were ever a no-op, the import would
    succeed and the ``pytest.raises`` would go unsatisfied → this self-proof goes RED.

    ``sys.meta_path`` finders are only consulted on a ``sys.modules`` cache MISS. In the full
    suite a prior test will already have imported ``weatherbot.weather.models``, so we must
    EVICT it (and any submodule entries) before importing under the blocker — otherwise
    ``import_module`` returns the cached object without ever consulting the finder, and the
    self-proof would silently pass for the wrong reason (a test-ordering false-negative). The
    ``finally:`` restores every evicted entry so we leave ``sys.modules`` byte-identical and
    other tests re-import the real module cleanly.
    """
    target = "weatherbot.weather.models"
    saved = {k: sys.modules[k] for k in list(sys.modules) if k == target or k == "weatherbot"}
    for key in saved:
        del sys.modules[key]
    blocker = _AppBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        with pytest.raises(ImportError):
            importlib.import_module(target)
    finally:
        sys.meta_path.remove(blocker)
        # drop any partial entry the blocked import may have left, then restore originals
        for key in [k for k in sys.modules if k == target or k == "weatherbot"]:
            del sys.modules[key]
        sys.modules.update(saved)


# ---------------------------------------------------------------------------
# Gate 3: AST signature-only litmus — no weather noun in the public name surface.
# ---------------------------------------------------------------------------


def test_litmus_clean():
    """No ``def``/``class``/param/annotation NAME under the module matches a weather noun.

    Walks every ``.py`` under ``yahir_reusable_bot/``, AST-extracts the public signature
    surface via ``_public_names`` (NOT docstrings/comments), and asserts none matches the
    D-13 litmus pattern. Prose is ignored by construction. On the clean scaffold → zero hits.
    """
    hits = {
        (path.name, name)
        for path in _MODULE_ROOT.rglob("*.py")
        for name in _public_names(path.read_text(encoding="utf-8"))
        if _LITMUS.search(name)
    }
    assert hits == set(), f"weather noun in module public surface: {sorted(hits)}"


def test_selfproof_litmus_catches_weather_noun():
    """Prove the litmus catches a NAME and ignores PROSE — through the SAME extractor.

    Half 1: a synthetic ``def send_briefing(forecast): ...`` source fed through
    ``_public_names`` must surface names the litmus matches (the ``send_briefing`` def name and
    the ``forecast`` param). Half 2: a source whose ONLY weather noun lives in a docstring must
    yield zero litmus hits — proving prose is ignored (D-11). If the extractor ever started
    surfacing prose, or stopped surfacing signature names, this self-proof goes RED.
    """
    leaky = "def send_briefing(forecast):\n    return forecast\n"
    leaky_hits = [n for n in _public_names(leaky) if _LITMUS.search(n)]
    assert leaky_hits, "litmus extractor failed to surface a weather noun in a signature"

    prose_only = (
        "def send(text):\n"
        '    """Deliver the weather briefing for the configured location."""\n'
        "    return text\n"
    )
    prose_hits = [n for n in _public_names(prose_only) if _LITMUS.search(n)]
    assert prose_hits == [], f"litmus must ignore prose, but flagged: {prose_hits}"
