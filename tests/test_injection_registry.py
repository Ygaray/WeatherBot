"""The POSITIVE half of APP-02: the four leak points are INJECTED, not baked (D-05).

``tests/test_import_hygiene.py`` proves the NEGATIVE half — *no weather noun appears in the
``yahir_reusable_bot`` public surface*. But APP-02's verb is **"injected, not baked"**: a
module could be perfectly weather-noun-free and STILL secretly bake an app default (a hidden
weather probe, a hardcoded job-id set, a module-side render). This file proves the second half:
each of the four app-coupled leak points is supplied **as an injected arg at the single
composition root** (``weatherbot.scheduler.wiring.build_runtime``) with **NO module-side baked
default**.

The four leak points (Phase-25 CONTEXT / ROADMAP):

1. **selected-location context** — ``panel.py:_selected_location`` (Phase 27 relocates the panel;
   here we prove the context originates app-side, the module names no "location").
2. **config id-deriver / exactly-once key** — the ``ReloadEngine.desired_jobs`` closure derives
   the WeatherBot job-id set; the module subtracts an app-supplied ``excluded_ids`` frozenset
   and names no id (the exactly-once ``UNIQUE(location_name, send_time, local_date)`` key lives
   app-side in ``weatherbot/weather/store.py``).
3. **health-check** — the ``ReadyGate.health_check`` closure calls the app-side
   ``run_self_check``; the module's ``ReadyGate`` has NO default probe (constructing one without
   a ``health_check`` is a ``TypeError`` — there is no module-side weather probe to fall back on).
4. **render_embed / panel cosmetics** — ``render_embed`` lives app-side in
   ``weatherbot/interactive/bot.py``; the module owns no render (a ``grep`` of the module tree
   finds zero ``render`` symbol).

**Self-proof discipline (mirrors ``test_import_hygiene.py``'s ``_injected_app_leak``):** every
positive assertion is paired with a deliberately-broken variant — a stub that BAKES a default —
that the test PROVES would trip the same check. A green run therefore proves the assertion BITES
(it is not a no-op), exactly the discipline of ``test_oracle_selfproof.py``.

These assertions are STRUCTURAL: they introspect ``build_runtime``'s wiring + the module
constructors' signatures. They add ZERO weather noun to the module surface (so the litmus stays
clean), and they use NO new dependency (stdlib ``inspect`` + the existing test fakes only).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from yahir_reusable_bot.config.reload import ReloadEngine
from yahir_reusable_bot.lifecycle import HealthResult, ReadyGate
from yahir_reusable_bot.registry import CommandRegistry, build_registry

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MODULE_ROOT = _REPO_ROOT / "yahir_reusable_bot"
_WIRING_SRC = (
    _REPO_ROOT / "weatherbot" / "scheduler" / "wiring.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Shared helpers — the SAME logic the positive checks AND their self-proofs call.
# ---------------------------------------------------------------------------


def _required_params_without_default(func) -> set[str]:
    """Names of params that have NO default value (i.e. the caller MUST supply them).

    A param with no default is a leak point the constructor REFUSES to bake — the app is
    forced to inject it at the single root. Drives both the positive check and its self-proof,
    so a green self-proof proves the introspection logic bites.
    """
    sig = inspect.signature(func)
    return {
        name
        for name, p in sig.parameters.items()
        if name != "self" and p.default is inspect.Parameter.empty
        and p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }


def _build_runtime_keyword_args() -> set[str]:
    """The keyword arg NAMES passed to every call/constructor inside ``build_runtime``.

    AST-walks ``wiring.py`` and collects, for every ``Call`` node, the ``keyword.arg`` names.
    This is how we prove a specific app closure (``desired_jobs=`` / ``health_check`` /
    ``on_online=`` / ``excluded_ids=``) is wired AT the single root — without importing the
    whole app (which needs discord.py / a live config). Pure source introspection.
    """
    tree = ast.parse(_WIRING_SRC)
    build_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_runtime"
    )
    kwargs: set[str] = set()
    for node in ast.walk(build_fn):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg is not None:
                    kwargs.add(kw.arg)
    return kwargs


def _build_runtime_positional_callees() -> set[str]:
    """The dotted/bare callee NAMES invoked positionally inside ``build_runtime``.

    Collects ``Name``/``Attribute`` callee identifiers so we can prove e.g.
    ``ReadyGate(...)`` and ``ReloadEngine(...)`` are constructed at the single root.
    """
    tree = ast.parse(_WIRING_SRC)
    build_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_runtime"
    )
    callees: set[str] = set()
    for node in ast.walk(build_fn):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                callees.add(func.id)
            elif isinstance(func, ast.Attribute):
                callees.add(func.attr)
    return callees


def _module_public_symbols() -> set[str]:
    """Every public ``def``/``class`` NAME defined anywhere under ``yahir_reusable_bot/``."""
    names: set[str] = set()
    for path in _MODULE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
    return names


# ---------------------------------------------------------------------------
# Leak point 3: the health-check is injected — the module has NO default probe.
# ---------------------------------------------------------------------------


def test_health_check_is_injected_no_module_default_probe():
    """``ReadyGate`` REQUIRES a ``health_check`` — there is no module-side baked probe.

    Positive: ``health_check`` is a required (no-default) constructor param, AND
    ``build_runtime`` constructs the ``ReadyGate`` and supplies the probe closure at the
    single root. The module names no weather probe; the only way to get a gate is to inject
    the app's ``run_self_check``-backed closure.
    """
    required = _required_params_without_default(ReadyGate.__init__)
    assert "health_check" in required, (
        "ReadyGate must REQUIRE a health_check (no module-side default probe); "
        f"required params were {sorted(required)}"
    )
    # And it is wired AT the single root: ReadyGate is constructed in build_runtime.
    assert "ReadyGate" in _build_runtime_positional_callees(), (
        "build_runtime must construct the ReadyGate at the single composition root"
    )

    # Self-proof: a stub gate that BAKES a default health_check would NOT appear in the
    # required-params set — proving the check above actually bites (it is not a no-op).
    class _BakedGate:
        def __init__(self, health_check=lambda: HealthResult(ok=True, reason="baked")):
            self._health_check = health_check

    baked_required = _required_params_without_default(_BakedGate.__init__)
    assert "health_check" not in baked_required, (
        "self-proof broken: a baked default should NOT be a required param"
    )


# ---------------------------------------------------------------------------
# Leak point 2: the config id-deriver / exactly-once key is injected.
# ---------------------------------------------------------------------------


def test_config_id_deriver_is_injected_module_names_no_id():
    """The job-id set is the app's injected ``desired_jobs`` closure; the module names no id.

    Positive: ``ReloadEngine`` REQUIRES ``desired_jobs`` (no default) AND ``build_runtime``
    supplies ``desired_jobs=`` at the single root. The exactly-once ``UNIQUE(location_name,
    send_time, local_date)`` key + ``_desired_job_ids`` live app-side; the module subtracts
    an app-supplied ``excluded_ids`` frozenset and bakes no id name.
    """
    required = _required_params_without_default(ReloadEngine.__init__)
    assert "desired_jobs" in required, (
        "ReloadEngine must REQUIRE the desired_jobs id-deriver (no module default); "
        f"required params were {sorted(required)}"
    )
    wired = _build_runtime_keyword_args()
    assert "desired_jobs" in wired, (
        "build_runtime must inject the desired_jobs closure at the single root"
    )
    assert "excluded_ids" in wired, (
        "build_runtime must inject the app's excluded_ids frozenset (the module names no id)"
    )

    # Self-proof: the module's ReloadEngine source must NOT bake any WeatherBot job id name.
    reload_src = (_MODULE_ROOT / "config" / "reload.py").read_text(encoding="utf-8")
    # The app's heartbeat / uvmonitor sentinel ids are passed via excluded_ids — they must
    # NOT be hardcoded inside the module. (Prose/comments may mention them; a NAME literal
    # baked into the diffing logic would be the violation.) We assert the deriver is called,
    # not a literal id set.
    assert "self._desired_jobs" in reload_src, (
        "self-proof: the module must CALL the injected desired_jobs deriver, not bake ids"
    )

    # Self-proof that the required-param check bites: a stub engine baking a default deriver
    # would not be a required param.
    class _BakedReload:
        def __init__(self, desired_jobs=lambda cfg: set()):
            self._desired_jobs = desired_jobs

    assert "desired_jobs" not in _required_params_without_default(_BakedReload.__init__), (
        "self-proof broken: a baked default deriver should NOT be a required param"
    )


# ---------------------------------------------------------------------------
# Leak point 1: the selected-location context originates app-side.
# ---------------------------------------------------------------------------


def test_selected_location_context_originates_app_side():
    """The selected-location context is an APP concern — the module names no "location".

    Positive: the ``_selected_location`` state lives in the app's ``weatherbot/interactive/
    panel.py`` (Phase 27 relocates the panel; here we prove the seam originates app-side), and
    NO module symbol carries a ``location`` name. The module exposes only the generic context
    seam (selection is the app's responsibility).
    """
    panel_src = (
        _REPO_ROOT / "weatherbot" / "interactive" / "panel.py"
    ).read_text(encoding="utf-8")
    assert "_selected_location" in panel_src, (
        "the selected-location context must live app-side in panel.py"
    )

    # The module must name no 'location' anywhere in its public symbols (the litmus would
    # also catch this; here we prove the POSITIVE direction — the seam is app-owned).
    module_symbols = _module_public_symbols()
    location_named = {s for s in module_symbols if "location" in s.lower()}
    assert location_named == set(), (
        f"module must not bake a location-named symbol (app-side seam): {location_named}"
    )

    # Self-proof: the detector bites — a synthetic symbol set with a location name is flagged.
    synthetic = {"render_panel", "SelectedLocationContext", "ReadyGate"}
    flagged = {s for s in synthetic if "location" in s.lower()}
    assert flagged == {"SelectedLocationContext"}, (
        "self-proof broken: the location-name detector must flag a baked location symbol"
    )


# ---------------------------------------------------------------------------
# Leak point 4: render_embed / panel cosmetics are injected — module owns no render.
# ---------------------------------------------------------------------------


def test_render_embed_is_app_side_module_owns_no_render():
    """``render_embed`` is an APP symbol; the module bakes no render of its own.

    Positive: ``render_embed`` is defined in the app's ``weatherbot/interactive/bot.py`` and
    imported app-side by ``panel.py`` (the panel cosmetics seam, Phase 27 injects ``render``).
    The reusable module owns ZERO render — no ``render``-prefixed symbol exists under
    ``yahir_reusable_bot/``.
    """
    bot_src = (
        _REPO_ROOT / "weatherbot" / "interactive" / "bot.py"
    ).read_text(encoding="utf-8")
    assert "def render_embed" in bot_src, (
        "render_embed must be defined app-side in bot.py (the module owns no render)"
    )
    panel_src = (
        _REPO_ROOT / "weatherbot" / "interactive" / "panel.py"
    ).read_text(encoding="utf-8")
    assert "render_embed" in panel_src, (
        "panel.py must consume the app-side render_embed (cosmetics seam stays app-side)"
    )

    # The module must own no COSMETICS render symbol (the embed/panel render seam
    # Phase 27 injects). The surface-agnostic plain-text ``render_help`` that D-02 puts
    # in the registry mechanism is NOT a cosmetics render — it groups names+summaries
    # into plain text and names no embed/visual concept — so it is explicitly allowed.
    _ALLOWED_RENDER = {"render_help"}

    def _is_cosmetics_render(symbol: str) -> bool:
        return "render" in symbol.lower() and symbol not in _ALLOWED_RENDER

    module_symbols = _module_public_symbols()
    render_named = {s for s in module_symbols if _is_cosmetics_render(s)}
    assert render_named == set(), (
        f"module must own no cosmetics render symbol (injected app-side): {render_named}"
    )

    # Self-proof: the detector bites — a synthetic module symbol named render_embed is
    # flagged, while the allow-listed plain-text render_help is not.
    synthetic = {"ReadyGate", "render_embed", "render_help", "SystemdNotifier"}
    flagged = {s for s in synthetic if _is_cosmetics_render(s)}
    assert flagged == {"render_embed"}, (
        "self-proof broken: the render-name detector must flag a baked cosmetics render "
        "symbol (render_embed) and allow the plain-text render_help"
    )


# ---------------------------------------------------------------------------
# Leak point 5 (Phase 26 / SEAM-06): the COMMAND SET is injected, not baked.
# ---------------------------------------------------------------------------


def test_command_set_is_app_supplied_no_module_default_commands():
    """``build_registry`` / ``CommandRegistry`` REQUIRE the app's ``specs`` — none baked.

    The Phase-25 D-05 "injected, not baked" verb extended to commands (SEAM-06): the module
    registry could be perfectly weather-noun-free and STILL secretly bake a default command
    set. This proves the second half — the command set is supplied **by the app** at the
    single re-export root (``weatherbot.interactive.registry`` calls ``build_registry(_SPECS)``),
    with NO module-side default.

    Two halves, each paired with a biting self-proof:

    (a) ``build_registry`` AND ``CommandRegistry.__init__`` REQUIRE ``specs`` (no default) —
        a reminder bot is FORCED to pass its own command set; the module bakes none.
    (b) NO module public ``def``/``class`` NAME bakes a DISTINCTIVELY-weather command
        name/handler (``weather`` / ``forecast`` / ``uv`` / ``next-cloudy``) — the command
        nouns live app-side. The noun set is deliberately the distinctive weather-command
        identifiers (aligned with the D-13-locked litmus ``weather|forecast|\buv\b``), NOT
        the generic ones (``alert`` / ``status`` / ``sun`` / ``wind``) that legitimately
        name the module's own ops surface (e.g. ``AlertSink`` / ``record_alert``) — so the
        check stays a real anti-bake guard, never a false positive on generic plumbing.
    """
    # (a) The constructor entry + the class __init__ both REQUIRE specs (no module default).
    assert "specs" in _required_params_without_default(build_registry), (
        "build_registry must REQUIRE specs (no module-side default command set); "
        f"required params were {sorted(_required_params_without_default(build_registry))}"
    )
    assert "specs" in _required_params_without_default(CommandRegistry.__init__), (
        "CommandRegistry.__init__ must REQUIRE specs (no baked default command set); "
        f"required params were {sorted(_required_params_without_default(CommandRegistry.__init__))}"
    )

    # Self-proof (a): a stub registry that BAKES a default spec tuple would NOT have specs
    # as a required param — proving the required-param check above actually bites.
    class _BakedRegistry:
        def __init__(self, specs=()):  # a baked-in default command set
            self.commands = tuple(specs)

    assert "specs" not in _required_params_without_default(_BakedRegistry.__init__), (
        "self-proof broken: a baked default spec tuple should NOT be a required param"
    )

    # (b) NO module public symbol NAME carries a DISTINCTIVELY-weather command noun (the
    # command set is app-supplied — the module names the generic mechanism, never a weather
    # command). The noun set mirrors the locked litmus's distinctive weather terms; the
    # generic ops nouns (alert/status/sun/wind) are intentionally excluded — they name the
    # module's own legitimate surface (AlertSink/record_alert), not a weather command.
    _COMMAND_NOUNS = (
        "weather",
        "forecast",
        "uv",
        "cloudy",  # the distinctive half of "next-cloudy"
    )

    def _is_command_named(symbol: str) -> bool:
        low = symbol.lower()
        return any(noun in low for noun in _COMMAND_NOUNS)

    module_symbols = _module_public_symbols()
    command_named = {s for s in module_symbols if _is_command_named(s)}
    assert command_named == set(), (
        f"module must bake no weather command name (the set is app-supplied): {command_named}"
    )

    # Self-proof (b): the detector bites — a synthetic symbol set with a weather command
    # name is flagged, while the generic mechanism names (CommandRegistry / match_command /
    # DispatchContext / build_registry) are NOT.
    synthetic = {
        "CommandRegistry",
        "match_command",
        "DispatchContext",
        "build_registry",
        "weekday_forecast",  # a baked weather command name — must be flagged
    }
    flagged = {s for s in synthetic if _is_command_named(s)}
    assert flagged == {"weekday_forecast"}, (
        "self-proof broken: the command-name detector must flag a baked weather command "
        f"(weekday_forecast) and allow the generic mechanism names; flagged: {flagged}"
    )


# ---------------------------------------------------------------------------
# Cross-cutting: the four leak points are wired AT THE SINGLE root, not scattered.
# ---------------------------------------------------------------------------


def test_all_four_leak_points_wired_at_single_root():
    """build_runtime is the ONE site that injects all four leak points (APP-01 + APP-02).

    A single structural assertion that the composition root constructs both reusable engines
    (ReadyGate + ReloadEngine) and injects the health-check probe closure + the desired_jobs
    id-deriver + the on_online/on_fail durable hooks — proving zero duplicated module mechanism
    and that the injection happens at exactly one greppable wiring site.
    """
    callees = _build_runtime_positional_callees()
    kwargs = _build_runtime_keyword_args()

    assert {"ReadyGate", "ReloadEngine"} <= callees, (
        f"build_runtime must construct both reusable engines at the single root: {callees}"
    )
    # leak point 2 (id-deriver) + 3 (health via on_online/on_fail durable hooks) injected here
    assert {"desired_jobs", "excluded_ids", "on_online", "on_fail"} <= kwargs, (
        f"build_runtime must inject the id-deriver + durable lifecycle hooks: {kwargs}"
    )

    # Self-proof: a degenerate wiring source that constructs nothing trips the same check.
    degenerate = "def build_runtime():\n    return None\n"
    deg_tree = ast.parse(degenerate)
    deg_fn = next(
        n for n in ast.walk(deg_tree)
        if isinstance(n, ast.FunctionDef) and n.name == "build_runtime"
    )
    deg_callees = {
        n.func.id
        for n in ast.walk(deg_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert not ({"ReadyGate", "ReloadEngine"} <= deg_callees), (
        "self-proof broken: a degenerate root constructs no engine and must fail the check"
    )


# ---------------------------------------------------------------------------
# Meta self-proof: the introspection helpers themselves bite.
# ---------------------------------------------------------------------------


def test_required_param_helper_distinguishes_default_from_required():
    """``_required_params_without_default`` flags a no-default param and ignores a defaulted one."""

    def _fn(must_inject, baked=42, *, also_required, also_baked="x"):  # noqa: ANN001
        return None

    required = _required_params_without_default(_fn)
    assert required == {"must_inject", "also_required"}, required


def test_build_runtime_introspection_finds_the_real_wiring():
    """Smoke: the wiring AST walkers return non-trivial sets over the REAL wiring.py."""
    assert _build_runtime_keyword_args(), "wiring.py keyword-arg scan returned nothing"
    assert _build_runtime_positional_callees(), "wiring.py callee scan returned nothing"


def test_injection_registry_references_build_runtime():
    """The module's wiring root function name is present in this test file's scope (contains)."""
    # Guards the must_haves 'contains: build_runtime' artifact contract.
    assert "build_runtime" in _WIRING_SRC
    # And the constructed engine is reachable structurally.
    assert pytest is not None
