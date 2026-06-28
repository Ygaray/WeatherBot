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
import contextlib
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


@contextlib.contextmanager
def _injected_app_leak():
    """Write a REAL leaking module into the package, yield its dotted name, then remove it.

    The synthetic-input self-proofs prove the *helpers* (``_scan_app_leaks`` /
    ``_AppBlocker``) bite, but they never exercise the gates' real wiring — which is exactly
    where CR-01 (single-package grimp build) and CR-02 (no cache eviction) hid. These
    real-gate self-proofs feed a genuine module-level ``import weatherbot.*`` through the
    ACTUAL gate (a real ``grimp.build_graph`` / a real isolated-import walk) and assert it goes
    red. The ``finally:`` unlinks the temp file and drops any ``sys.modules`` entry it created,
    so the tree is left byte-identical (the litmus ``rglob`` and the clean gates never see it).
    """
    leak_path = _MODULE_ROOT / "_leak_selfproof.py"
    leak_mod = f"{MODULE}._leak_selfproof"
    leak_path.write_text("import weatherbot.config.models  # noqa\n", encoding="utf-8")
    try:
        yield leak_mod
    finally:
        leak_path.unlink(missing_ok=True)
        sys.modules.pop(leak_mod, None)


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
    # Build the graph over BOTH packages (CR-01): a single-package build of MODULE never
    # graphs ``weatherbot.*`` targets (they live in a different top-level package), so a real
    # ``import weatherbot.*`` leak produces NO edge and the scan silently passes. Graphing APP
    # too makes the cross-package edge visible; we then restrict the scan to module-OWNED
    # importers so the legitimate app → module edges (the allowed one-way direction) are ignored.
    # ``cache_dir=None`` DISABLES grimp's on-disk cache (``.grimp_cache/``). A standing
    # correctness gate must read source FRESH every run — a cached import graph can go stale
    # (e.g. survive a leak being added/removed) and make the gate both false-pass and
    # false-fail. Determinism over speed: the graph builds in well under a second.
    graph = grimp.build_graph(MODULE, APP, cache_dir=None)  # TYPE_CHECKING edges incl. (default)
    edges = {
        module: graph.find_modules_directly_imported_by(module)
        for module in graph.modules
        if module == MODULE or module.startswith(MODULE + ".")
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


def test_config_module_never_imports_pydantic():
    """No ``yahir_reusable_bot.config.*`` module may import ``pydantic`` (D-03 / Pitfall 1).

    The grimp leak-scan above only guards the module→APP boundary; it does NOT catch a
    THIRD-PARTY ``pydantic`` import. The config hot-reload seam must route ALL validation
    through the app's injected concrete validator — the module never parses/validates the
    config itself (validating on an unparametrized base silently drops subclass fields, and a
    ``Generic[T]`` holder cannot self-parametrize a ``TypeAdapter`` because ``TypeVar`` is
    erased at runtime). So an explicit gate clones the same grimp-graph idiom and asserts no
    ``config``-subpackage module directly imports ``pydantic`` (or any ``pydantic.*``).
    ``cache_dir=None`` reads source FRESH every run (no stale-cache false-pass/fail).
    """
    graph = grimp.build_graph(MODULE, cache_dir=None)
    offenders: list[tuple[str, str]] = []
    for module in graph.modules:
        if not module.startswith(MODULE + ".config"):
            continue
        for imported in graph.find_modules_directly_imported_by(module):
            if imported == "pydantic" or imported.startswith("pydantic."):
                offenders.append((module, imported))
    assert offenders == [], (
        f"config module imports pydantic — validation must be injected (D-03): {offenders}"
    )


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


def test_selfproof_import_gate_catches_real_app_edge():
    """Prove the REAL grimp gate (not just the helper) reddens on a genuine app import (CR-01).

    Injects a real module-level ``import weatherbot.config.models`` into the package and runs
    the EXACT gate logic — a real ``grimp.build_graph(MODULE, APP)`` over module-owned
    importers. A single-package build (the CR-01 bug) would graph no cross-package edge and
    this would stay green; the two-package build flags the leak. This is the regression that
    the synthetic-dict self-proof above could not catch.
    """
    with _injected_app_leak() as leak_mod:
        graph = grimp.build_graph(MODULE, APP, cache_dir=None)  # fresh read — never the cache
        edges = {
            module: graph.find_modules_directly_imported_by(module)
            for module in graph.modules
            if module == MODULE or module.startswith(MODULE + ".")
        }
        leaks = _scan_app_leaks(edges)
    assert any(
        imp == leak_mod and (tgt == APP or tgt.startswith(APP + "."))
        for imp, tgt in leaks
    ), f"real grimp gate failed to catch an injected app import: {leaks}"


# ---------------------------------------------------------------------------
# Gate 2: isolated-import smoke — import every module with `weatherbot` blocked.
# ---------------------------------------------------------------------------


def test_module_imports_with_app_blocked():
    """Every ``yahir_reusable_bot.*`` module imports cleanly with the app namespace blocked.

    Installs an ``_AppBlocker`` ``sys.meta_path`` finder that raises ``ImportError`` for any
    ``weatherbot``/``weatherbot.*`` name, then imports every module under the package via
    ``pkgutil.walk_packages``. A module-import-time OR TYPE_CHECKING-realized app import would
    raise loudly here.

    CR-02: ``sys.meta_path`` finders are consulted ONLY on a ``sys.modules`` cache MISS. In the
    full suite, earlier tests have already cached ``weatherbot``/``weatherbot.*``, so a real
    leak would resolve straight from cache and never reach the blocker (a test-ordering
    false-negative). We therefore EVICT the app namespace before walking and restore it in
    ``finally:`` (mirroring the self-proof), so the blocker is genuinely consulted. The
    ``finally:`` also purges ``sys.modules`` keys starting with ``yahir_reusable_bot`` and drops
    any partial app entry the blocked import may have left, then restores the saved app modules
    so other tests re-import the real app cleanly.
    """
    blocker = _AppBlocker()
    saved_app = {
        k: sys.modules[k]
        for k in list(sys.modules)
        if k == APP or k.startswith(APP + ".")
    }
    for key in saved_app:
        del sys.modules[key]
    sys.meta_path.insert(0, blocker)
    try:
        pkg = importlib.import_module(MODULE)
        for info in pkgutil.walk_packages(pkg.__path__, prefix=MODULE + "."):
            importlib.import_module(info.name)  # raises if the module reaches app code
    finally:
        sys.meta_path.remove(blocker)
        for key in [k for k in sys.modules if k.startswith(MODULE)]:
            del sys.modules[key]
        for key in [k for k in sys.modules if k == APP or k.startswith(APP + ".")]:
            del sys.modules[key]
        sys.modules.update(saved_app)


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


def test_selfproof_isolated_import_catches_real_app_edge():
    """Prove the REAL isolated-import gate reddens on a genuine app import (CR-02).

    Injects a real module-level ``import weatherbot.config.models`` and runs the FULL gate —
    eviction + blocker + ``walk_packages`` import. Without the CR-02 eviction this would
    false-pass under a polluted cache (the bug); with it the blocked import raises loudly. The
    ``finally:`` restores the evicted app modules so the suite is left byte-identical.
    """
    with _injected_app_leak():
        saved_app = {
            k: sys.modules[k]
            for k in list(sys.modules)
            if k == APP or k.startswith(APP + ".")
        }
        for key in saved_app:
            del sys.modules[key]
        blocker = _AppBlocker()
        sys.meta_path.insert(0, blocker)
        try:
            with pytest.raises(ImportError):
                pkg = importlib.import_module(MODULE)
                for info in pkgutil.walk_packages(pkg.__path__, prefix=MODULE + "."):
                    importlib.import_module(info.name)
        finally:
            sys.meta_path.remove(blocker)
            for key in [k for k in sys.modules if k.startswith(MODULE)]:
                del sys.modules[key]
            for key in [k for k in sys.modules if k == APP or k.startswith(APP + ".")]:
                del sys.modules[key]
            sys.modules.update(saved_app)


# ---------------------------------------------------------------------------
# Gate 3: AST signature-only litmus — no weather noun in the public name surface.
# ---------------------------------------------------------------------------


def test_litmus_clean():
    """No ``def``/``class``/param/annotation NAME under the module matches a weather noun.

    Walks every ``.py`` under ``yahir_reusable_bot/``, AST-extracts the public signature
    surface via ``_public_names`` (NOT docstrings/comments), and asserts none matches the
    D-13 litmus pattern. Prose is ignored by construction. On the clean scaffold → zero hits.

    Phase-25 scope note: the ``rglob("*.py")`` walk auto-scales to the new
    ``yahir_reusable_bot/lifecycle/`` package (ReadyGate / SystemdNotifier / HealthResult /
    LifecycleIdentity + the generalized ``is_running_process`` proc guard) with NO per-module
    edit — exactly like the grimp + isolated-import gates' ``startswith(MODULE)`` /
    ``walk_packages`` auto-scaling. This gate is the tripwire that would catch any weather
    noun that accidentally moved into the lifecycle seam (a ``weatherbot online`` event key
    surfacing as a NAME, an ``is_weatherbot_pid`` helper name, or an ``auth_failed``-named
    parameter) — if it reddens here, that is a real defect to fix in 25-01/25-02, never a test
    to weaken (D-13 term set is LOCKED — generic seam names ``health``/``ready``/``identity``
    are exactly what the module is meant to expose).
    """
    # Assert the new lifecycle package is genuinely in the scanned tree (so a future
    # refactor that relocates it cannot silently drop it from litmus coverage).
    scanned = {path.name for path in _MODULE_ROOT.rglob("*.py")}
    assert {"ready_gate.py", "sdnotify.py", "health.py", "identity.py"} <= scanned, (
        f"lifecycle package not in the litmus scan tree (coverage gap): {sorted(scanned)}"
    )
    # Phase-26: assert the relocated registry/dispatcher package is in the scanned tree
    # too, so a future relocation cannot silently drop it from litmus coverage. These are
    # the registry package's own files (spec/registry/match/dispatch) — scoped to the
    # registry subtree so the proof is unambiguous even if a flat filename were shared.
    registry_scanned = {
        path.name for path in (_MODULE_ROOT / "registry").rglob("*.py")
    }
    assert {"spec.py", "registry.py", "match.py", "dispatch.py"} <= registry_scanned, (
        "registry/dispatcher package not in the litmus scan tree (coverage gap): "
        f"{sorted(registry_scanned)}"
    )
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
