# Phase 22: Channel + Delivery-Reliability Seam (+ in-place boundary) - Research

**Researched:** 2026-06-27
**Domain:** Python package-boundary extraction + import-hygiene gating (grimp / AST / isolated-import) for a characterization-locked suite
**Confidence:** HIGH (every claim grounded in the actual repo + a live grimp 3.14 probe against the real tree)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Flat sibling top-level package — create `yahir_reusable_bot/` at the repo root, sibling to `weatherbot/`, with the final import root in place from day one (so Phase 28 is a `git mv`, not a rename). Leaves `templates/`, `tests/`, `pythonpath=["."]`, and the Phase-21 coverage `source` paths byte-undisturbed.
- **D-02:** A second top-level package whose name differs from the `weatherbot` project defeats hatchling auto-discovery, so PKG-01 must add an explicit `[tool.hatch.build.targets.wheel] packages = ["weatherbot", "yahir_reusable_bot"]` block. (Verify backend — VERIFIED below: it IS hatchling.)
- **D-03:** Move a clean, text-only `Channel` + `DeliveryResult` into the module; **drop `send_briefing` from the abstract contract**; keep the concrete `DiscordWebhookChannel` app-side until Phase 27. The module's `Channel` becomes exactly `send(text: str) -> DeliveryResult`. The `TYPE_CHECKING` import of `Forecast` is **deleted** from the abstraction.
- **D-04:** Phase 27 is the named home for relocating the Discord transport; the embed stays put this phase.
- **D-05 (hand-off obligation):** Document the temporary two-home split (clean `Channel` in the module; concrete `DiscordWebhookChannel` still app-side) as an explicit Phase-27 hand-off.
- **D-06:** Move the generic retry primitives into the module — `build_retrying`, `is_transient`/`is_auth_failure`, `parse_retry_after` (capped, honors `Retry-After`, never retries 401/403), and the `REASON_*` taxonomy.
- **D-07:** Define an `AlertSink` port (Protocol/callable) in the module now; the weather-coupled implementation (`record_alert`/`resolve_alert`) **stays app-side as the adapter**, wired behind the port. Keep `fire_slot` adapted, not rewritten (byte-identical safe).
- **D-08:** Heartbeat is **explicitly OUT of scope** for Phase 22 (belongs to Phase 25). Do NOT define a heartbeat hook/port now.
- **D-09:** Enforce the one-way dependency with `grimp` called in-process from a pytest test — build the import graph and assert no module edge points at an app package (prefix check). Gives direct control over the TYPE_CHECKING question. Adds one dep (`grimp`).
- **D-10:** Pair the graph check with an isolated-import smoke test (import the module subpackage with app packages absent/blocked) — catches TYPE_CHECKING-only and lazy/function-local app imports.
- **D-11:** Litmus check is signature/identifier-only — runs over the module's public surface (AST-extracted `def`/`class`/parameter/annotation names), NOT docstrings or comments.
- **D-12:** The one real signature hit today — `def send_briefing(self, text, forecast: Forecast)` — is resolved by D-03 (drop it + delete the `Forecast` import), which simultaneously clears the cross-package `Forecast` import edge the D-09 gate flags. Three gates, one fix.
- **D-13:** The gate is documented as a standing success criterion that phases 23–27 re-run. The litmus pattern is `weather|forecast|location|openweather|\buv\b|briefing` over the public surface.

### Claude's Discretion
- Exact module sub-layout inside `yahir_reusable_bot/` (e.g. `channels/`, `reliability/` vs flatter) and file naming.
- The precise `AlertSink` Protocol method signature(s) — minimal, weather-clean, shaped by `fire_slot`'s `record_alert`/`resolve_alert` calls.
- The exact `grimp`-graph assertion form (allowlist of genuinely-needed edges; how TYPE_CHECKING edges are included/excluded) and the isolated-import smoke-test harness shape.
- How "public surface" is extracted for the litmus (AST module walk vs def/class-line scan) — must ignore prose, catch names.
- Confirm the actual build backend before writing `packages = [...]` (VERIFIED: hatchling).

### Deferred Ideas (OUT OF SCOPE)
- Relocate the concrete `DiscordWebhookChannel` transport (+ embed build) into the module → **Phase 27** (D-05 hand-off).
- Heartbeat hook/port in the module → **Phase 25** (D-08).
- Full docstring/comment scrub of weather nouns → **Phase 28 / DOCS-01** (D-13).
- Switch the import gate to declarative `import-linter` → viable runner-up only if a contract-as-documentation style is later preferred (D-09).
- uv workspace / multi-package arrangement → only if a second in-repo consumer appears (D-01 rejected list).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **SEAM-01** | A channel-agnostic `Channel` abstraction + the delivery-reliability wrapper (retry/backoff honoring `Retry-After`, never retrying 401/403, out-of-band alert, *heartbeat*) live in the module with zero weather coupling. | The `Channel` ABC (`weatherbot/channels/base.py`) is already `send(text)->DeliveryResult`; only `send_briefing` + the `Forecast` import leave (D-03). `reliability/retry.py` is **already app-clean** (VERIFIED: zero `weatherbot.*` edges). The out-of-band alert becomes the `AlertSink` port (D-07). **Scope note:** REQUIREMENTS lists "heartbeat" in SEAM-01, but **D-08 defers heartbeat to Phase 25** — Phase 22 ships Channel + reliability + alert-port only. The planner must NOT let the SEAM-01 wording pull heartbeat in (the requirement is satisfied incrementally across 22 + 25). |
| **PKG-01** | The reusable code is carved into a clean in-place package boundary; the module subpackage imports zero app code (one-way dependency, enforced by an import-lint/grep gate), full suite green, before any physical move. | The flat-sibling `yahir_reusable_bot/` boundary (D-01) + the explicit hatchling `packages` block (D-02) + the grimp import-graph pytest gate (D-09) + the isolated-import smoke test (D-10) + the AST litmus (D-11/D-13). Anchored here, re-run on 23–27. |
</phase_requirements>

## Summary

This is a **byte-identical relocation** phase, not a design phase. Two surfaces move from `weatherbot/` into a new flat-sibling `yahir_reusable_bot/` package: (1) the text-only `Channel` ABC + `DeliveryResult` from `channels/base.py` (minus `send_briefing` and minus the `Forecast` TYPE_CHECKING import, per D-03), and (2) the entire retry engine from `reliability/retry.py` (already 100% app-clean — VERIFIED). The concrete `DiscordWebhookChannel` and the channel factory **stay app-side** because they legitimately import app code (`branding`, `weather.models`, `config.models`, `config.settings`) — confirmed by a live grimp probe. The out-of-band alert is generalized into an `AlertSink` port defined in the module, with the weather-coupled `record_alert`/`resolve_alert` calls kept app-side behind it (D-07). Heartbeat is OUT (D-08).

Three new pytest gates lock the boundary: a **grimp import-graph assert** (no edge from `yahir_reusable_bot.*` to an app package), an **isolated-import smoke test** (import the module with the `weatherbot` namespace blocked), and an **AST signature-only litmus grep**. The single most load-bearing finding: **grimp 3.14 includes TYPE_CHECKING imports in the graph by default** (`exclude_type_checking_imports=False`), so the gate naturally catches the `Forecast` type edge — and D-03's deletion of that import is what makes the gate pass. The oracle is the full suite (now **732 tests**, up from the 649 v1.3 baseline cited in CONTEXT) + the Phase-21 goldens; any non-empty snapshot diff is a failure to investigate.

**Primary recommendation:** Add `grimp>=3.14` to the dev group. Create `yahir_reusable_bot/{channels,reliability}/` (Claude's-discretion layout), `git mv`-equivalent the clean code in, re-export through `weatherbot.channels`/`weatherbot.reliability` so the 732-test suite's import paths (incl. `isinstance(ch, Channel)`) stay green, add the explicit `[tool.hatch.build.targets.wheel] packages` block, extend `[tool.coverage.run] source`, and wire the three gates as standing pytest tests.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Channel abstraction (`Channel`, `DeliveryResult`, `send(text)`) | **Reusable module** (`yahir_reusable_bot`) | — | Text-only, zero weather coupling — the canonical SMS/Telegram path (D-03). |
| Concrete Discord transport (`DiscordWebhookChannel`, embed build) | **App** (`weatherbot.channels.discord`) | Module (Phase 27) | Imports `weatherbot.branding` + `weather.models` (VERIFIED) — legitimately app-coupled; relocates in Phase 27 (D-04/D-05). |
| Channel factory (`build_channel`, registry) | **App** (`weatherbot.channels.factory`) | — | Imports `config.models`/`config.settings` (VERIFIED) — wiring is composition-root concern, app-side. |
| Retry engine (`build_retrying`, classifiers, `parse_retry_after`, `REASON_*`) | **Reusable module** (`yahir_reusable_bot.reliability`) | — | Already zero `weatherbot.*` edges (VERIFIED); pure tenacity composition (D-06). |
| Out-of-band alert (the *port*) | **Reusable module** (`AlertSink` Protocol) | — | The delivery-lane alert seam (D-07). |
| Out-of-band alert (the *impl*) | **App** (`weatherbot.weather.store.record_alert`/`resolve_alert`, wired in `fire_slot`) | — | Writes the weather SQLite store — app adapter behind the port (D-07). |
| Retry-then-alert orchestration (`fire_slot`) | **App** (`weatherbot.scheduler.daemon`) | — | Irreducibly weather-coupled (claim/release/SCHD-07); *adapted* to consume module imports + the port, never rewritten (D-07). |
| Heartbeat (`_heartbeat_tick`, `__heartbeat__` job) | **App** (untouched this phase) | Module (Phase 25) | Not a delivery concern; deferred (D-08). |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| grimp | `>=3.14` | Build the in-process import graph for the D-09 hygiene gate | `[VERIFIED: PyPI/live import]` grimp 3.14 is the latest; it is the import-graph engine that `import-linter` itself is built on. Direct `ImportGraph` API, one dep, native TYPE_CHECKING control. |
| ast (stdlib) | built-in (3.12) | AST public-surface extraction for the D-11/D-13 litmus | `[VERIFIED]` Zero-dep; `FunctionDef`/`AsyncFunctionDef`/`ClassDef`/`arg`/annotations cover the signature surface and exclude docstrings/comments. |
| pytest | `>=9.0.3` (installed) | Host the three gates as standing tests | `[VERIFIED: pyproject.toml]` The suite IS the regression guard (no CI) — gates are pytest asserts (D-09). |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | `>=9.1.4` (installed) | The moved retry engine's composition primitives | `[VERIFIED: pyproject.toml]` Moves verbatim with `retry.py` — already a runtime dep, no change. |
| httpx | `>=0.28.1` (installed) | `is_transient`/`is_auth_failure`/`parse_retry_after` type against `httpx` exceptions/`Response` | `[VERIFIED]` Stays a runtime dep; the module imports it (third-party, not app — allowed). |
| structlog | `>=26.1.0` (installed) | `retry.py`'s `before_sleep` outcome log | `[VERIFIED]` Third-party — allowed in the module. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| grimp-in-pytest (D-09) | `import-linter` declarative contract | `[VERIFIED]` import-linter counts TYPE_CHECKING imports by default (see Pitfall 1) → today's `Forecast` guard would flag; adds 2 deps + exit-code parsing. Fine runner-up if a declarative contract is later preferred (deferred). |
| AST signature walk (D-11) | Whole-text grep + allowlist | `[CITED: CONTEXT D-11]` Whole-text flags ~19 incidental docstring mentions (`retry.py` says "OpenWeather"/"Discord"/"briefing") → needless churn / allowlist drift / rubber-stamp risk. |
| AST signature walk (D-11) | Hand-rolled stdlib import-resolution | `[CITED: CONTEXT D-09]` Re-implements a solved problem; its failure mode is a silent false-negative — the worst outcome for a guard. (grimp is used for *imports*; AST is only for the *litmus name* scan.) |

**Installation:**
```bash
uv add --dev grimp
```

**Version verification (this session):**
```
grimp 3.14   — VERIFIED via `uv run --with grimp python -c "import grimp; print(grimp.__version__)"` → 3.14
              `grimp.build_graph` signature confirmed (see Package Legitimacy Audit).
```

## Package Legitimacy Audit

> One new external package this phase: `grimp`.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| grimp | PyPI | mature (3.x line; v3.14 current) | high (transitive dep of `import-linter`, widely used) | `github.com/seddonym/grimp` | OK | Approved — add to `[dependency-groups] dev` |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

`grimp` is authored by David Seddon (same author as `import-linter`), is the import-graph engine import-linter is built on, and was importable + introspectable this session (the live `build_graph` probe below is the strongest possible legitimacy signal — the package not only exists but its documented API behaves as claimed). It is a **dev-only** dependency (the gate runs in tests; it never ships in the wheel or runs at app runtime), so it does not enter the `yahir_reusable_bot` package's own dependency surface for Phase 28.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────── weatherbot/ (APP) ───────────────────────────┐
   morning cron /        │                                                                          │
   catch-up / manual ───▶│  scheduler/daemon.py :: fire_slot   ◀── retry-then-alert orchestration   │
                         │        │                    │                                            │
                         │        │ build_retrying()   │ record_alert()/resolve_alert()             │
                         │        ▼                    ▼                                            │
                         │   (imports)            AlertSink adapter (app impl → weather SQLite)      │
                         │        │                    ▲                                            │
                         │        │                    │ injected behind the port                   │
                         │   channels/discord.py  ─────┘  (DiscordWebhookChannel + embed STAY here) │
                         │        │  send_briefing(text, forecast)  ── embed built app-side (D-04)   │
                         │        │  .send(text) ──┐                                                 │
                         └────────┼───────────────┼─────────────────────────────────────────────────┘
                                  │ (one-way: app → module, NEVER module → app)
                                  ▼               ▼
                         ┌────────────────── yahir_reusable_bot/ (MODULE) ───────────────────────────┐
                         │  channels/  :: Channel(ABC).send(text)->DeliveryResult   (NO send_briefing,│
                         │                DeliveryResult                              NO Forecast import)│
                         │  reliability/ :: build_retrying, two_burst_wait, is_transient,             │
                         │                 is_auth_failure, parse_retry_after, REASON_*               │
                         │  ports/     :: AlertSink (Protocol)  ◀── defined here, impl injected app-side│
                         │  (third-party deps OK: httpx, tenacity, structlog ; ZERO weatherbot.* edges)│
                         └───────────────────────────────────────────────────────────────────────────┘

      GATES (new pytest tests, standing for phases 23–27):
        ① grimp import-graph assert: no edge yahir_reusable_bot.* → weatherbot.*  (TYPE_CHECKING incl. by default)
        ② isolated-import smoke: import yahir_reusable_bot.* with `weatherbot` blocked in sys.meta_path → no ImportError
        ③ AST litmus: public def/class/arg/annotation names ∌ /weather|forecast|location|openweather|\buv\b|briefing/
```

### Recommended Project Structure (Claude's discretion — D-01 names the root; sub-layout is open)
```
yahir_reusable_bot/            # NEW flat sibling of weatherbot/ — final import root (D-01)
├── __init__.py                # re-exports nothing app-specific; module-public surface
├── channels/
│   ├── __init__.py            # exports Channel, DeliveryResult
│   └── base.py                # Channel ABC (send(text) only) + DeliveryResult  (from weatherbot/channels/base.py minus send_briefing + Forecast)
├── reliability/
│   ├── __init__.py            # exports build_retrying, is_transient, is_auth_failure, parse_retry_after, REASON_*
│   └── retry.py               # verbatim move of weatherbot/reliability/retry.py
└── ports/                     # (or alongside channels — discretion)
    └── alerts.py              # AlertSink Protocol (D-07)

weatherbot/                    # APP — re-points imports to yahir_reusable_bot, keeps re-export surface
├── channels/
│   ├── __init__.py            # re-export Channel, DeliveryResult FROM yahir_reusable_bot.channels; keep DiscordWebhookChannel, build_channel
│   ├── base.py                # GONE or thin shim (see Pitfall 3) — Channel/DeliveryResult now live in the module
│   ├── discord.py             # STAYS — concrete DiscordWebhookChannel (imports Channel/DeliveryResult from module or re-export)
│   └── factory.py             # STAYS — build_channel registry
└── reliability/
    └── __init__.py            # re-export the retry surface FROM yahir_reusable_bot.reliability
```

### Pattern 1: Re-export shim keeps the suite's import paths green
**What:** `weatherbot.channels` and `weatherbot.reliability` keep their existing public names by re-exporting from `yahir_reusable_bot`.
**When to use:** Always this phase — `tests/test_channel.py` does `from weatherbot.channels import (Channel, DeliveryResult, ...)` and `isinstance(ch, Channel)`; `daemon.py`/`cli.py` import `from weatherbot.reliability import build_retrying, is_transient, ...`. Re-exporting means **zero call-site churn** in app code or tests (byte-identical-safe).
```python
# weatherbot/channels/__init__.py
# Source: existing weatherbot/channels/__init__.py, re-pointed to the module
from yahir_reusable_bot.channels import Channel, DeliveryResult
from .discord import DiscordWebhookChannel   # STAYS app-side (D-04)
from .factory import build_channel           # STAYS app-side

__all__ = ["Channel", "DeliveryResult", "DiscordWebhookChannel", "build_channel"]
```
Note: `isinstance(ch, Channel)` stays valid because there is now exactly ONE `Channel` class (the module's), and `DiscordWebhookChannel` subclasses *that* one — there must be no second `Channel` definition left in `weatherbot` (avoid the dual-class trap, Pitfall 3).

### Pattern 2: The `send_briefing` relocation (D-03 + D-12, the "three gates, one fix")
**What:** `send_briefing` is removed from the module's abstract `Channel`; the concrete `DiscordWebhookChannel.send_briefing(text, forecast)` stays as a Discord-only method app-side.
**Why it's load-bearing:** `cli.py:send_now` calls `channel.send_briefing(result_lr.text, result_lr.forecast)` and the base default `send_briefing` delegates to `send(text)`. After D-03 the module `Channel` has no `send_briefing`. The app must keep `send_briefing` reachable for *every* channel the composition root dispatches.
**Resolution (planner must choose, byte-identical-safe):** Keep a `send_briefing` default on the **app-side** channel surface. Two viable shapes (Claude's discretion):
  - (a) a thin app-side `BriefingChannel(Channel)` intermediate base that re-adds the default `send_briefing(text, forecast) -> self.send(text)` and the `Forecast` TYPE_CHECKING import — `DiscordWebhookChannel` subclasses it; OR
  - (b) keep `send_briefing` only on `DiscordWebhookChannel` (the sole v1 channel) and have `send_now` call it — since Discord is the only channel, the base default is currently unused by any non-Discord path.
Shape (a) preserves the exact current dispatch contract (`send_now` calls `send_briefing` on whatever channel it gets) and is the lower-risk byte-identical choice. **This `Forecast` import lives APP-side, so it does not re-introduce a module→app edge** (the gate is satisfied).

### Pattern 3: `AlertSink` port (D-07) — minimal, weather-clean
**What:** A `Protocol` (or callable) in the module that `fire_slot` calls instead of importing `record_alert`/`resolve_alert` from `weatherbot.weather.store` *inside module code*. Note `fire_slot` itself is APP code, so it may still import the store directly — the port matters for what the *module's* reliability surface needs. **Shape it to what `fire_slot` actually calls:** `record_alert(db_path, location_id, slot_time, local_date, reason) -> bool` (returns "self_first") and `resolve_alert(db_path, location_id, slot_time, local_date)`.
**When to use:** Phase 22 *defines* the port + documents that `fire_slot` consumes alert through it. Because `fire_slot` stays app-side and is only *adapted*, the minimal Phase-22 move can be: define `AlertSink` in the module; have the app provide a trivial adapter wrapping the existing store calls. Keep it byte-identical (the calls and their args do not change).
**Discretion:** the exact method set — keep it to `record_alert`/`resolve_alert` (the two `fire_slot` uses); do NOT add `briefing_missed`/heartbeat (heartbeat is D-08-deferred).

### Pattern 4: grimp import-graph gate (D-09) — VERIFIED call shapes
**What:** A pytest test that builds the graph and asserts no `yahir_reusable_bot.*` module imports a `weatherbot.*` module.
**VERIFIED API (grimp 3.14, probed against the real tree this session):**
```python
# Source: grimp 3.14 — signature + behavior VERIFIED this session
import grimp

# build_graph(package_name, *additional, include_external_packages=False,
#             exclude_type_checking_imports=False, cache_dir=NotSupplied)
graph = grimp.build_graph("yahir_reusable_bot")        # build the module's own graph
#   ── CRITICAL: exclude_type_checking_imports defaults to False, so TYPE_CHECKING
#      edges ARE in the graph. KEEP the default → the gate catches a TYPE_CHECKING
#      app import (exactly the Forecast leak D-03 removes). Do NOT pass True.

APP = "weatherbot"
leaks = []
for module in graph.modules:                            # set[str] of every module in the graph
    for target in graph.find_modules_directly_imported_by(module):
        if target == APP or target.startswith(APP + "."):
            leaks.append((module, target))
assert leaks == [], f"module → app import leak(s): {leaks}"
```
**Auto-scaling (D-09):** the prefix check (`startswith("weatherbot.")`) needs no per-module edit as the module grows across phases 23–27 — every new file under `yahir_reusable_bot/` is graphed automatically.
**Allowlisting genuinely-needed edges (discretion):** there should be NONE this phase (the module imports only `httpx`/`tenacity`/`structlog`/stdlib). If a future phase needs a deliberate edge, allowlist by exact `(importer, imported)` tuple — never by a broad prefix.
**Line-number reporting for a useful failure message (VERIFIED):**
```python
# graph.get_import_details(importer=..., imported=...) → list of dicts with
# 'line_number' and 'line_contents' — VERIFIED to return e.g.
#   {'line_number': 20, 'line_contents': 'from weatherbot.weather.models import Forecast'}
```

### Pattern 5: isolated-import smoke test (D-10) — VERIFIED mechanism
**What:** Import every `yahir_reusable_bot.*` module with the `weatherbot` namespace **blocked**, so any lazy/function-local OR TYPE_CHECKING-realized app import fails loud. (The grimp gate is static; this is the dynamic backstop.)
**Recommended lowest-risk mechanism (VERIFIED working this session):** a `sys.meta_path` finder that raises `ImportError` for any `weatherbot`/`weatherbot.*` name, then `importlib.import_module` each module under the package:
```python
# Source: prototyped + VERIFIED this session against the real clean reliability.retry
import sys, importlib, pkgutil
import pytest

class _AppBlocker:
    def find_spec(self, name, path=None, target=None):
        if name == "weatherbot" or name.startswith("weatherbot."):
            raise ImportError(f"BLOCKED app import inside the reusable module: {name}")
        return None  # defer to the normal finders for everything else

def test_module_imports_with_app_blocked():
    blocker = _AppBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        import yahir_reusable_bot as pkg
        for info in pkgutil.walk_packages(pkg.__path__, prefix="yahir_reusable_bot."):
            importlib.import_module(info.name)   # raises if the module reaches app code
    finally:
        sys.meta_path.remove(blocker)
        # purge any half-imported module entries so other tests re-import cleanly
        for k in [k for k in sys.modules if k.startswith("yahir_reusable_bot")]:
            del sys.modules[k]
```
**Why a `meta_path` blocker over a subprocess-with-trimmed-path:** equally catches lazy/function-local imports (they execute the blocked `import` at call time only — so prefer ALSO importing-then-calling any lazy path, OR rely on the grimp static gate for lazy edges), is faster, deterministic, and needs no env wrangling. A subprocess is the heavier alternative if the planner wants total interpreter isolation; the `meta_path` blocker is the lower-risk default. **Caveat:** a purely *function-local* app import is only triggered if the function runs — the grimp gate (static, sees function-body imports) is the authority for those; the smoke test catches *module-import-time* and TYPE_CHECKING-realized leaks. The two gates are complementary (this is exactly why PKG-01 asks for both).

### Pattern 6: AST signature-only litmus (D-11/D-13) — VERIFIED prototype
**What:** Walk each public `.py` under `yahir_reusable_bot/`, collect identifier names from `def`/`class`/parameters/annotations/returns (NOT docstrings/comments), and assert none matches the litmus pattern.
**VERIFIED node coverage (prototyped this session):**
```python
# Source: prototyped + VERIFIED this session (retry.py → zero hits, as expected)
import ast, re, pathlib

PATTERN = re.compile(r"weather|forecast|location|openweather|\buv\b|briefing", re.IGNORECASE)

def public_names(py_path: pathlib.Path) -> list[str]:
    tree = ast.parse(py_path.read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        if isinstance(node, ast.arg):
            names.append(node.arg)
            if node.annotation is not None:
                names.append(ast.unparse(node.annotation))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            names.append(ast.unparse(node.returns))
    return names

def test_litmus_no_weather_noun_in_public_surface():
    root = pathlib.Path("yahir_reusable_bot")
    hits = {(p.name, n) for p in root.rglob("*.py") for n in public_names(p) if PATTERN.search(n)}
    assert hits == set(), f"weather noun in module public surface: {sorted(hits)}"
```
**VERIFIED token behavior** (this matters — note for the planner):
| Token | `\buv\b` matches? | Why |
|-------|-------------------|-----|
| `uv` | ✅ yes | standalone word |
| `uv_index` | ❌ **no** | `_` is a `\w` char → no word boundary after `uv` |
| `uvindex` | ❌ no | no boundary |
| `send_briefing` | ✅ yes | `briefing` matches (no boundary needed) |
| `forecast` | ✅ yes | bare substring |

So `\buv\b` catches a bare `uv` param/attr but would MISS a `uv_index`-style name. For THIS phase's moving code (Channel `send(text)` + retry primitives) there are zero `uv` names, so the gate is clean — but the planner should record this `\buv\b` underscore gap as a known limitation for the standing gate (a future phase adding a `uv`-prefixed-underscore name to the module would slip through). The pattern is the roadmap's locked literal (D-13), so do not "fix" it this phase — just document the gap.

### Anti-Patterns to Avoid
- **Dual `Channel` class (Pitfall 3):** leaving a second `Channel` definition in `weatherbot.channels.base` while the real one moves → `isinstance(ch, Channel)` in `test_channel.py` silently tests the wrong class. There must be exactly ONE `Channel`.
- **Passing `exclude_type_checking_imports=True` to grimp:** this would HIDE the very TYPE_CHECKING leak the gate exists to catch (D-09's whole rationale). Keep the default `False`.
- **Moving `discord.py`/`factory.py` into the module:** they import app code (VERIFIED leaks) — that is Phase 27's job (D-04). Moving them now re-introduces module→app edges and risks the goldens twice (D-04).
- **Rewriting `fire_slot`:** adapt it behind the port; do not refactor the 3-line retry inside the weather-coupled orchestration (D-08 rejected `DeliveryGuard`).
- **Editing a test to make the "pure" move pass:** the suite + goldens are the contract; a non-empty snapshot diff is investigated, never rubber-stamped (Phase-21 D-04).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detect module→app import edges (incl. TYPE_CHECKING & function-local) | A stdlib `ast` import-walker that resolves imports yourself | `grimp.build_graph` + `find_modules_directly_imported_by` | `[VERIFIED]` grimp resolves relative imports, re-exports, and TYPE_CHECKING edges correctly; a hand-rolled walker's failure mode is a silent false-negative (D-09) — fatal for a guard. |
| Block app imports during the isolation test | Monkeypatching `builtins.__import__` | A `sys.meta_path` finder that raises on the app prefix | `[VERIFIED]` meta_path is the blessed import-hook surface; `__import__` patching is fragile and misses `importlib` paths. |
| Capture the public name surface for the litmus | Regex over raw source (catches docstrings/comments) | stdlib `ast` walk of `def`/`class`/`arg`/annotations | `[VERIFIED: CONTEXT D-11]` AST ignores prose by construction — no allowlist, no docstring churn. |
| Reproducible cross-machine wheel contents | Rely on hatchling auto-discovery for a 2nd package | Explicit `[tool.hatch.build.targets.wheel] packages` | `[VERIFIED: hatchling docs]` auto-discovery only finds a package matching the project name; a differently-named 2nd package is silently dropped (D-02). |

**Key insight:** every "build it yourself" option here has a *silent* failure mode (a missed edge, a dropped package, a prose false-positive). The phase's whole point is a *loud* guard, so use the tools whose failures are loud/observable.

## Runtime State Inventory

> This is a code-relocation phase (rename-class). The grep audit finds files; runtime state is enumerated here explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None.** No datastore keys, collection names, or row values reference `Channel`/`reliability`/the package name. The SQLite store (`weather_onecall`/`sent_log`/`alerts`/`heartbeat`) keys on location/time/date, not on a class or package name — verified against `daemon.py` `fire_slot` calls and the Phase-21 `test_golden_db.py` schema. | none |
| Live service config | **None.** The systemd unit (`deploy/`) invokes the `weatherbot` console script (`weatherbot = "weatherbot.cli:main"`) which is UNCHANGED — `yahir_reusable_bot` ships NO console script (STATE.md). No n8n/Datadog/Tailscale config references these symbols. | none |
| OS-registered state | **None.** No Task Scheduler / launchd / pm2 names embed `Channel`/`reliability`. The systemd service name is `weatherbot` (untouched). | none — but see UAT below |
| Secrets/env vars | **None.** `DISCORD_WEBHOOK_URL`/`OPENWEATHER_API_KEY`/`DISCORD_BOT_TOKEN` are read via `pydantic-settings` by name; no secret key references the moved symbols. The webhook URL stays inside the app-side `DiscordWebhookChannel` (unmoved). | none |
| Build artifacts / installed packages | **`weatherbot.egg-info`/editable install.** The bot runs as a **live editable install** on host `yahir-mint` (MEMORY: weatherbot-live-systemd-service). Adding a 2nd top-level package + the `[tool.hatch...packages]` block changes the wheel/editable contents, so the host needs `uv sync` (or reinstall) + a `systemctl restart weatherbot` for the new `yahir_reusable_bot` package to be importable at runtime. | **Deferred Gate-2 UAT:** after merge, on `yahir-mint`: `uv sync` → `systemctl restart weatherbot` → confirm `import yahir_reusable_bot` resolves + the daemon comes online (`weatherbot online` log + READY). Pure relocation → no behavior change expected. |

**The canonical question — after every file is updated, what runtime systems still have the old layout cached?** Only the **editable install on `yahir-mint`** (it must re-sync to see the new package). Everything else is pure in-repo Python imports re-pointed via the re-export shims; no datastore, secret, or OS registration carries the moved names.

## Common Pitfalls

### Pitfall 1: grimp/import-linter count TYPE_CHECKING imports by default
**What goes wrong:** Assuming a TYPE_CHECKING-only app import is invisible to the gate, then being surprised the gate flags `channels.base → weather.models`.
**Why it happens:** `[VERIFIED]` `grimp.build_graph(..., exclude_type_checking_imports=False)` is the DEFAULT — TYPE_CHECKING edges are in the graph. (import-linter shares this default; that is precisely why D-09 rejected it as "would flag today's `Forecast` guards.")
**How to avoid:** This is a FEATURE here, not a bug — keep the default. The gate flags the `Forecast` edge; D-03 (delete the import) makes it pass. The planner sequences D-03 BEFORE turning the gate green.
**Warning signs:** A gate failure naming `weatherbot.weather.models` after the move = the `Forecast` import wasn't fully deleted from the moved `base.py`.

### Pitfall 2: The `send_briefing` call site breaks the move
**What goes wrong:** Dropping `send_briefing` from the module `Channel` (D-03) without re-providing it app-side breaks `cli.py:send_now` (`channel.send_briefing(text, forecast)`) and any non-Discord dispatch.
**Why it happens:** `send_now` dispatches `send_briefing` on whatever channel it gets; the base default currently lives in the abstraction being slimmed.
**How to avoid:** Re-add `send_briefing` on the **app-side** channel surface (Pattern 2, shape (a) or (b)). Keep `cli.py`/`send_now` byte-identical. The `Forecast` import that returns lives app-side (no module→app edge).
**Warning signs:** `test_channel.py::test_base_send_briefing_defaults_to_send_text` or `test_send_now.py` failing.

### Pitfall 3: Two `Channel` classes → `isinstance` tests the wrong one
**What goes wrong:** A leftover `Channel` definition in `weatherbot.channels.base` + the new one in the module → `isinstance(ch, Channel)` (test_channel.py:84) and `DiscordWebhookChannel(Channel)` reference different classes.
**Why it happens:** Incomplete move (file shimmed but old class not deleted).
**How to avoid:** Exactly ONE `Channel` definition (the module's). `weatherbot.channels` re-exports it; `DiscordWebhookChannel` subclasses the re-exported (= module) class.
**Warning signs:** A green `isinstance` test that should be red, or a mysterious `test_channel.py` import error.

### Pitfall 4: hatchling silently drops the 2nd package from the wheel
**What goes wrong:** Without `[tool.hatch.build.targets.wheel] packages = ["weatherbot", "yahir_reusable_bot"]`, the wheel contains only `weatherbot` (auto-discovery matches the project name) — `yahir_reusable_bot` is silently absent in a built/installed wheel.
**Why it happens:** `[VERIFIED: D-02 + hatchling docs]` hatchling auto-discovers a single package matching the dist name; a differently-named sibling needs explicit listing.
**How to avoid:** Add the explicit block (see Code Examples). The Phase-28 `uv build --no-sources` leak gate is the eventual backstop, but the config goes in NOW (D-02).
**Warning signs:** The host editable install resolving `import yahir_reusable_bot` is the local check; a clean `uv build` + inspecting the wheel `RECORD` is the definitive one.

### Pitfall 5: Coverage source paths stop covering the moved code
**What goes wrong:** `[tool.coverage.run] source` still lists `weatherbot/channels`, `weatherbot/reliability` but the real code now lives in `yahir_reusable_bot/` → the moved code shows 0% / is dropped from the audit.
**Why it happens:** The Phase-21 coverage block (verified present) enumerates app paths only.
**How to avoid:** Add the new package's paths to `source` (Code Examples). The Phase-21 coverage audit is a one-time audit (not a standing gate), but the source list must still point at where the code lives.
**Warning signs:** A coverage report omitting `Channel`/`retry` lines after the move.

### Pitfall 6: The test suite count drifted (649 → 732)
**What goes wrong:** Treating "649 tests" (CONTEXT/STATE v1.3 figure) as the oracle size; the working tree already has Phase-21 goldens → **732 tests collected** (VERIFIED this session). A "missing" count is just the Phase-21 additions.
**How to avoid:** Use `uv run pytest` and trust the live count; the byte-identical oracle is "every test green + every Phase-21 golden snapshot unchanged," not a fixed number.

## Code Examples

### grimp gate — full pytest test (VERIFIED API)
```python
# Source: grimp 3.14 (API VERIFIED this session against the real tree)
import grimp

MODULE = "yahir_reusable_bot"
APP = "weatherbot"

def test_module_imports_zero_app_code():
    graph = grimp.build_graph(MODULE)            # TYPE_CHECKING edges included (default)
    leaks = []
    for module in graph.modules:
        for target in graph.find_modules_directly_imported_by(module):
            if target == APP or target.startswith(APP + "."):
                detail = graph.get_import_details(importer=module, imported=target)
                lines = [(d["line_number"], d["line_contents"]) for d in detail]
                leaks.append((module, target, lines))
    assert leaks == [], f"reusable module imports app code: {leaks}"
```

### `pyproject.toml` additions (VERIFIED backend = hatchling; no existing `[tool.hatch]` block)
```toml
# build-system is already: requires=["hatchling"]; build-backend="hatchling.build" (VERIFIED)

[tool.hatch.build.targets.wheel]            # NEW — D-02 (without this the 2nd package is dropped)
packages = ["weatherbot", "yahir_reusable_bot"]

[dependency-groups]                          # add grimp to the EXISTING dev group
dev = [
    "pytest>=9.0.3",
    "pytest-cov>=7.1.0",
    "ruff>=0.15.16",
    "syrupy>=5.3.4",
    "time-machine>=2.16",
    "grimp>=3.14",                           # NEW — D-09 import-hygiene gate (dev-only)
]

[tool.coverage.run]
branch = true
source = [
    "weatherbot/channels",
    "weatherbot/scheduler",
    "weatherbot/config",
    "weatherbot/reliability",
    "weatherbot/ops",
    "weatherbot/interactive",
    "yahir_reusable_bot",                     # NEW — moved code lives here now (Pitfall 5)
]
```

### import-linter contrast (for the planner's record — NOT to be wired, D-09)
import-linter's `[importlinter]` `forbidden`/`independence`/`layers` contracts read `include-external-packages` and, like grimp, **count TYPE_CHECKING imports by default** (the `unmatched_ignore_imports_alerting` / type-checking handling is opt-out, mirroring grimp's `exclude_type_checking_imports`). That default is exactly why D-09 chose grimp-in-pytest: the same TYPE_CHECKING visibility, but as a native assert with one dep and no exit-code parsing. `[CITED: import-linter.readthedocs.io/en/stable/usage.html]` One paragraph only — do not author an import-linter contract this phase.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `import-linter` CLI in CI for contracts | grimp `ImportGraph` in-process from a unit test | this phase (no CI here) | The pytest suite IS the guard (D-09); native assert beats shelling a CLI. |
| Whole-text grep + allowlist for "no domain noun" | AST signature-only extraction | this phase (D-11) | No docstring churn, no allowlist drift, no rubber-stamp risk. |
| grimp `< 3.x` (no `exclude_type_checking_imports` param) | grimp 3.14 with explicit TYPE_CHECKING control | grimp 3.x line | The gate can *deliberately* include TYPE_CHECKING edges — the feature D-09 depends on. |

**Deprecated/outdated:** nothing relevant — the runtime stack (httpx/APScheduler 3.x/tenacity/structlog/discord.py 2.7.1/pydantic v2) is unchanged this milestone (STATE.md "runtime stack is unchanged").

## Validation Architecture

> Nyquist validation is enabled (no `workflow.nyquist_validation: false` in config). This section enumerates the sampling/edge cases a VALIDATION.md must cover for this relocation.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest `>=9.0.3` (+ syrupy `>=5.3.4` for goldens, time-machine `>=2.16`) — VERIFIED in pyproject.toml |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| Quick run command | `uv run pytest tests/test_channel.py tests/test_reliability.py -x` |
| Full suite command | `uv run pytest` (VERIFIED: **732 tests** collected) |
| Golden update (oracle) | `uv run pytest --snapshot-update` (only when a diff is INTENTIONAL — here it must NOT be) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEAM-01 | `Channel.send(text)->DeliveryResult` behaves identically after move | characterization | `uv run pytest tests/test_channel.py -x` | ✅ (269 lines) |
| SEAM-01 | retry bursts / `Retry-After` honoring / no-retry-401-403 identical | characterization | `uv run pytest tests/test_reliability.py -x` | ✅ (748 lines) |
| SEAM-01 | delivery byte-identical (embed fields/order, CLI bytes, schedule plan, DB rows) | golden oracle | `uv run pytest tests/test_golden_*.py` | ✅ (Phase 21) |
| SEAM-01 | out-of-band alert path intact (`record_alert`/`resolve_alert` via port) | characterization | `uv run pytest tests/test_reliability.py tests/test_scheduler.py -x` | ✅ |
| PKG-01 | module imports zero app code (one-way dependency) | **NEW** import-graph gate | `uv run pytest tests/test_import_hygiene.py::test_module_imports_zero_app_code` | ❌ Wave 0 |
| PKG-01 | module imports in isolation (app blocked) | **NEW** isolated-import smoke | `uv run pytest tests/test_import_hygiene.py::test_module_imports_with_app_blocked` | ❌ Wave 0 |
| PKG-01 / APP-02 | no weather noun in module public surface | **NEW** AST litmus | `uv run pytest tests/test_import_hygiene.py::test_litmus_clean` | ❌ Wave 0 |
| BHV-01 | whole suite green at the boundary | regression | `uv run pytest` | ✅ |
| BHV-02 | every Phase-21 golden snapshot byte-unchanged | golden oracle | `uv run pytest tests/test_golden_*.py tests/test_oracle_selfproof.py` | ✅ |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_channel.py tests/test_reliability.py tests/test_import_hygiene.py -x`
- **Per wave merge:** `uv run pytest` (full 732) + confirm zero golden diff
- **Phase gate:** full suite green + all three new gates green + zero snapshot diff, before `/gsd-verify-work`

### What "fully covered" means per new gate (the sampling/edge cases)
- **Import-graph gate:** must FAIL on a deliberately-introduced TYPE_CHECKING app import (e.g. a temporary `if TYPE_CHECKING: from weatherbot.weather.models import Forecast` in the moved `base.py`) — proven by the live probe that the `Forecast` edge IS visible by default. A passing gate after D-03 = the edge is gone. **Self-proof recommended:** a meta-test that monkeypatches/temporarily adds a leak edge and asserts the gate catches it (mirrors Phase-21 `test_oracle_selfproof.py`).
- **Isolated-import smoke:** must FAIL (raise `ImportError` through the blocker) if a module-import-time OR TYPE_CHECKING-realized app import exists; must PASS for the clean moved code (VERIFIED to pass for `reliability.retry` this session). Edge case: a purely *function-local* app import won't trip this (the function must run) — the static grimp gate is the authority there; document the complementarity.
- **AST litmus:** must catch a weather noun added to a `def`/`class`/param/annotation name (e.g. re-adding `send_briefing` or a `forecast:` param to the *module* surface); must IGNORE the same nouns in docstrings (`retry.py`'s "OpenWeather"/"Discord"/"briefing" prose → VERIFIED zero signature hits). Known gap: `\buv\b` misses `uv_index`-style names (underscore) — document, do not fix (D-13 locks the pattern).
- **Byte-identical oracle:** zero diff across ALL `tests/__snapshots__/` after the move. A non-empty diff is investigated, never `--snapshot-update`-ed away (Phase-21 D-04).

### Wave 0 Gaps
- [ ] `tests/test_import_hygiene.py` — the three new gates (import-graph, isolated-import, AST litmus) + an optional self-proof meta-test. Covers PKG-01 / APP-02.
- [ ] Dev-dep install: `uv add --dev grimp` (grimp `>=3.14`) — confirmed NOT yet installed this session.
- [ ] `pyproject.toml`: `[tool.hatch.build.targets.wheel] packages` block + `[tool.coverage.run] source` extension (no `[tool.hatch]` block exists today — VERIFIED).
- [ ] `yahir_reusable_bot/` package scaffold (`__init__.py` + `channels/`, `reliability/`, `ports/`).
- [ ] Re-export shims in `weatherbot/channels/__init__.py` and `weatherbot/reliability/__init__.py`.

*(Existing test infra — conftest fixtures, syrupy goldens, the 732-test suite — covers all behavior-preservation requirements; only the three import-hygiene gates are genuinely new.)*

## Security Domain

> `security_enforcement` is not disabled in config (= enabled). Assessed for this relocation.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface changes; the daemon's 401/403-never-retry classifier (`is_auth_failure`) moves verbatim. |
| V3 Session Management | no | n/a |
| V4 Access Control | no | n/a |
| V5 Input Validation | yes (preserved) | `parse_retry_after` treats the `Retry-After` header as untrusted (caps it, degrades malformed to `None`) — VERIFIED in `retry.py`; moves byte-identical. |
| V6 Cryptography | no | n/a |
| V7 Logging hygiene (secret-redaction) | yes (preserved) | The moved `retry.py` `before_sleep` logs outcome-only (attempt/burst, never a key/URL) — VERIFIED. The webhook URL stays inside the UN-moved app-side `DiscordWebhookChannel` (`_url` private, `discord_webhook` logger raised to WARNING) — the credential never enters the module. |

### Known Threat Patterns for this relocation
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Credential (webhook URL / `appid`) leaking into the moved module | Information Disclosure | The credential lives in `DiscordWebhookChannel._url` (app-side, UNMOVED) and the env-loaded settings — the module's `Channel`/`retry` surface never references it (VERIFIED: zero secret references in `base.py`/`retry.py`). The grimp gate also forbids the module importing `config.settings` (where secrets are typed). |
| Uncapped `Retry-After` exhausting the retry budget | Denial of Service | `parse_retry_after` caps at `RETRY_AFTER_CAP_S=120` and clamps `max(base, ra)` to the cap (VERIFIED) — moves verbatim. |
| A silent module→app coupling slipping in later | Tampering (architecture drift) | The standing grimp gate (TYPE_CHECKING-inclusive) + isolated-import smoke fail loud on any new edge — this IS the security control for boundary integrity. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Re-exporting `Channel`/`DeliveryResult` from `weatherbot.channels` keeps `isinstance(ch, Channel)` + all `test_channel.py` imports green | Pattern 1/3 | LOW — if a dual-class slips in, `test_channel.py` goes red loud (not silent); grounded in reading the actual test file. |
| A2 | `send_briefing` re-added app-side (Pattern 2) keeps `send_now`/`test_send_now.py` byte-identical | Pattern 2 / Pitfall 2 | MEDIUM — the exact shape (intermediate base vs Discord-only) is Claude's discretion; both preserve the call contract, but the planner must pick and the goldens/`test_send_now.py` arbitrate. |
| A3 | The `AlertSink` port can be defined + `fire_slot` adapted with zero behavior change | Pattern 3 / D-07 | MEDIUM — `fire_slot` is app code and may keep importing the store directly; the minimal port may end up thin. `test_scheduler.py`/`test_reliability.py` + the DB golden are the arbiter. The precise method set is discretion (D-07). |
| A4 | `yahir_reusable_bot` ships NO console script and is dev/runtime-importable via the editable install after `uv sync` | Runtime State Inventory | LOW — STATE.md states "ships NO console script"; the host re-sync is a deferred Gate-2 UAT, not a Phase-22 blocker. |

*All grimp API shapes, TYPE_CHECKING behavior, the current import leaks, the AST litmus result, the isolated-import mechanism, the hatchling backend, and the 732-test count were VERIFIED this session — they are not assumptions.*

## Open Questions

1. **Where exactly does the `AlertSink` adapter live, and how thin is it?**
   - What we know: `fire_slot` (app code) calls `record_alert(db_path, loc_id, slot_time, local_date, reason)->bool` and `resolve_alert(...)` from `weatherbot.weather.store`. D-07 wants the *port* in the module.
   - What's unclear: whether Phase 22's minimal move is "define the `AlertSink` Protocol in the module + document `fire_slot` consumes alert through it" (leaving `fire_slot`'s direct store import in place as the trivial adapter), or a more explicit injection at the daemon composition root.
   - Recommendation: ship the **minimal** version — define `AlertSink` in the module, provide a one-line app adapter wrapping the existing store calls, keep `fire_slot` byte-identical. The full composition-root wiring is Phase 25's job (APP-02 leak-points). Let the DB golden + `test_scheduler.py` gate it.

2. **`weatherbot/channels/base.py` — delete or thin-shim?**
   - What we know: the file currently defines `Channel`/`DeliveryResult`/`send_briefing` + the `Forecast` import.
   - What's unclear: whether to delete it (and re-export everything from the package `__init__`) or leave a thin shim re-exporting from the module.
   - Recommendation: delete the class definitions; let `weatherbot/channels/__init__.py` re-export the module's `Channel`/`DeliveryResult` and host the app-side `send_briefing` default (Pattern 2). Fewer files, one `Channel`. Discretion (D-01 layout).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | all build/test/run | ✓ | 0.11.19 | — |
| pytest | the suite + new gates | ✓ | (installed, >=9.0.3) | — |
| grimp | D-09 import-graph gate | ✗ (not installed) | needs `>=3.14` | none — `uv add --dev grimp` (Wave 0) |
| hatchling | wheel build (`packages` block) | ✓ (build-isolated) | current | — |
| syrupy / time-machine | Phase-21 goldens (oracle) | ✓ | 5.3.4 / 2.16 | — |

**Missing dependencies with no fallback:** `grimp` — the only new install; `uv add --dev grimp` is a Wave-0 task. No blocker (the package is OK-verified + introspected this session).
**Missing dependencies with fallback:** none.

## Sources

### Primary (HIGH confidence)
- **Live grimp 3.14 probe against the real `weatherbot` tree (this session):** `build_graph` signature (`exclude_type_checking_imports: bool = False`), the full `ImportGraph` method list, the default-included `channels.base → weather.models` TYPE_CHECKING edge, `get_import_details` line numbers, the `exclude=True` drop, and the complete current leak set (`channels.base/discord/factory → weather.models/branding/config.*`; `reliability` CLEAN).
- **Live AST + meta_path prototypes (this session):** litmus over `retry.py` (zero signature hits), `\buv\b` token-boundary behavior, isolated-import via `sys.meta_path` blocker (clean import of `reliability.retry` under app-block).
- **Repo source (read this session):** `weatherbot/channels/{base,discord,factory,__init__}.py`, `weatherbot/reliability/{retry,__init__}.py`, `weatherbot/scheduler/daemon.py` (`fire_slot`, `_heartbeat_tick`, `run_daemon`), `weatherbot/cli.py` (`send_now`, dispatch), `pyproject.toml` (backend=hatchling, no `[tool.hatch]`, coverage block, dev group), `tests/test_channel.py` structure (`isinstance(ch, Channel)`), 732-test collect count.
- **Planning artifacts:** `22-CONTEXT.md` (D-01..D-13), `REQUIREMENTS.md` (SEAM-01/PKG-01/APP-02/BHV-01/BHV-02), `ROADMAP.md` (Phase 22 success criteria + phase spine), `STATE.md` (module name, no console script, runtime stack unchanged), `21-PATTERNS.md` (golden oracle + `# pragma` + coverage conventions).

### Secondary (MEDIUM confidence)
- import-linter TYPE_CHECKING default behavior — `[CITED: import-linter.readthedocs.io/en/stable/usage.html]` (used only as the rejected-runner-up contrast, D-09).
- hatchling explicit `packages` requirement for a non-name-matching package — `[CITED: hatch.pypa.io build config]` (corroborates D-02; the live wheel-RECORD confirmation is deferred to a Wave-0/Phase-28 check).

### Tertiary (LOW confidence)
- none — all load-bearing claims were tool-verified this session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — grimp 3.14 + stdlib `ast` + pytest, all verified present/probed.
- Architecture (what moves vs stays): HIGH — the move/stay split is dictated by the VERIFIED leak set (only `base.py` minus `Forecast` + `retry.py` are app-clean; `discord.py`/`factory.py` import app code).
- Gate mechanics (grimp/isolated-import/AST): HIGH — every call shape verified against the real tree this session.
- `AlertSink` port + `send_briefing` re-home: MEDIUM — shapes are Claude's discretion (D-07/D-03); byte-identical-safe paths identified, goldens/`test_send_now.py`/`test_scheduler.py` arbitrate.

**Research date:** 2026-06-27
**Valid until:** 2026-07-27 (stable; grimp 3.x and the runtime stack are not fast-moving — re-verify grimp's `build_graph` signature only if bumping to a 4.x major).
