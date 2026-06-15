# Phase 7: CLI `weather [location]` One-Shot - Research

**Researched:** 2026-06-15
**Domain:** Python CLI architecture (argparse subparsers), uv console-script packaging, systemd/uv deploy interaction, tenacity read-only retry, offline CLI testing
**Confidence:** HIGH (codebase-grounded; external idioms verified against uv docs + Python packaging guide)

## Summary

This phase is well-trodden Python CLI territory, and nearly every building block already
exists in the codebase. The Phase 6 read-only core (`lookup_weather` → `LookupResult.text`,
`UnknownLocationError` carrying `.requested`/`.valid_names`) is the entire fetch→render engine;
the `weather` subcommand is a thin handler that resolves a name, calls the core, prints `.text`,
and maps exceptions to exit codes. The retry pattern to mirror (`run_send_now`) is already
written and tested — the only adaptation is dropping the `retry_if_result(not r.ok)` arm because
a read-only lookup returns a `LookupResult`, never a `DeliveryResult`.

The two genuinely load-bearing risks are not in the `weather` command itself but in the
*restructure* around it. (1) **The clean-break flag→subparser migration breaks the existing test
suite directly:** `tests/test_cli.py` calls `main(["--check", ...])`, `main(["--send-now", ...])`
verbatim (lines 295, 308, 314, 322). Those calls become invalid CLI usage once the flags are
removed, so argparse will `SystemExit(2)` instead of returning 1 — those four tests MUST be
rewritten to subcommand form (`main(["check", ...])`, `main(["send-now", ...])`) as part of this
phase, or "206 tests green" is impossible. (2) **`[project.scripts]` requires a `[build-system]`
that pyproject.toml does not currently have** — uv will not synthesize a `weatherbot` console
script (and `uv run weatherbot` / the deployed `ExecStart` will fail) until either a
`[build-system]` table or `[tool.uv] package = true` is added. This is the most likely silent
failure in the phase.

**Primary recommendation:** Build the subparser skeleton in `main()` with a shared parent parser
carrying `--config`; give each subcommand its own handler function returning `int`; map the four
exit codes by catching `UnknownLocationError` (→1), config-load failure via `_load_config_reporting`
(→2), and exhausted/permanent fetch errors (→3) around a `lookup_weather` wrapped in a 3-attempt
`Retrying(retry=retry_if_exception(is_transient))`. Add `[build-system] requires=["hatchling"]`
+ `[project.scripts] weatherbot = "weatherbot.cli:main"`, then `uv sync` so the script installs.
Update `deploy/weatherbot.service` and `deploy/README.md` to `run` subcommand form and flag the
`yahir-mint` redeploy as a UAT/ops step.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CLI arg parsing / dispatch | CLI (`weatherbot/cli.py` `main()`) | — | Single dispatch point; argparse owns usage/exit-2 |
| Location resolution | Config (`resolve_location`) | — | Already case-insensitive, `None`→default; raises `UnknownLocationError` |
| Fetch → render | Interactive core (`lookup_weather`) | Weather client | Phase 6 read-only core; CLI must not re-fetch or re-render |
| Transient retry | CLI handler (`weather` wrapper) | reliability (`is_transient`) | Retry locus is the attended terminal handler, mirroring `run_send_now` |
| Error → exit-code mapping | CLI handler | — | stdout/stderr split + exit codes are a CLI-surface concern |
| Console-script exposure | Packaging (`pyproject.toml`) | uv build backend | `[project.scripts]` + build-system; resolved by `uv run`/install |
| Process supervision | systemd unit (`deploy/`) | uv | Out-of-process; only the `ExecStart` invocation string changes |

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01: Restructure `main()` to argparse subparsers.** Subcommands `weather`, `run`, `check`,
  `send-now`, `geocode`. The `weather` subcommand is the deliverable; the others are migrations
  of today's flags. Replaces the flat `--flag` + `hasattr`-dispatch shape.
- **D-02: Clean break — drop the old flags.** `--run` / `--check` / `--send-now` / `--geocode`
  are REMOVED, not kept as aliases. Mandatory consequence this phase: update
  `deploy/weatherbot.service` (`ExecStart` → `run` subcommand) and `deploy/README.md`. Live host
  `yahir-mint` must be redeployed (`systemctl daemon-reload` + restart) — an ops/UAT item, not code.
- **D-03: Add a real console-script entry point.** `[project.scripts] weatherbot = "weatherbot.cli:main"`
  in `pyproject.toml` so `weatherbot weather home` works verbatim.
- **D-04: Read-only command, reuses Phase 6 core.** `weather` may call `parse_weather_command`
  (optional — argparse already supplies the positional), then `lookup_weather(name, config=…,
  settings=…)` and prints `.text`. No send, no persist, no daemon. Bare `weather` → `name=None`.
- **D-05: Distinct exit codes:** 0 ok / 1 unknown location (CMD-04) / 2 config invalid or missing /
  3 fetch/API/network failure (incl. exhausted transient retry, 401/403 auth).
- **D-06: Briefing → stdout, all errors → stderr.** Unknown-location reuses `UnknownLocationError`'s
  existing message verbatim.
- **D-07 (planner note, not blocked):** argparse exits `2` on bad usage, colliding with D-05's
  "config invalid = 2". The overlap is acceptable ("your input was wrong"); planner may keep or
  renumber, just document the final mapping.
- **D-08: Mirror `run_send_now`'s short bounded retry, adapted for read-only.** ~3 attempts,
  `wait_exponential(max=10)`, `retry_if_exception(is_transient)` ONLY (no `retry_if_result` arm —
  no `DeliveryResult`). Never retry 401/403. Exhausted/permanent → stderr + exit 3.
- **D-09: `weather` quiet by default; `--verbose`/`-v` restores INFO.** Raise effective log level
  to WARNING for `weather` so stdout is just the briefing. Other subcommands keep INFO.

### Claude's Discretion
- Exact subcommand names where ambiguous (`send-now` vs `send`); whether `--config` is a
  global/parent-parser option vs per-subcommand (global today).
- Where the `weather` handler lives (`weatherbot/cli.py` vs a small `interactive/cli.py`); how
  `--verbose` is wired (per-subcommand flag vs a global one applied selectively).
- Whether `parse_weather_command` is invoked by the CLI at all or reserved for P11.
- The precise final exit-code numbering if D-07's argparse-2 overlap is renumbered.

### Deferred Ideas (OUT OF SCOPE)
- Discord bot `weather <loc>` reply (CMD-02) + short-TTL cache (CMD-06) — Phase 11.
- `weatherbot reload` + `check-config` subcommand (CFG-02/08) — Phase 9.
- Geocoded / arbitrary-city `weather <any city>` (CMD-V2-02) — v2; CLI stays configured-only.
- Deprecating-vs-removing old flags — operator chose clean break (D-02); no deprecation window.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CMD-01 | Standalone CLI prints a configured location's briefing, **no daemon required** | `weather` handler calls `lookup_weather` (read-only Phase 6 core) and prints `.text`; no daemon import, no `send_now`/`persist`. Console script (D-03) makes `weatherbot weather home` work verbatim. |
| CMD-03 | Bare `weather` → default/primary configured location | argparse positional `location` with `nargs="?"`, default `None`; `lookup_weather(None, …)` → `resolve_location(config, None)` → `config.locations[0]`. Verified in `loader.py:resolve_location`. |
| CMD-04 | Unknown location → clear error listing valid names, no geocoding fallback, non-zero exit | `lookup_weather` raises `UnknownLocationError(requested, valid_names)` (subclass of `ValueError`) whose message is `"No location named 'X'; configured locations: a, b"`. Handler catches → stderr + exit 1. No geocode path is reachable from `weather`. |
| CMD-05 | Printed briefing uses the exact v1 template/format | `lookup_weather` renders via `templates.renderer.render` with the canonical token set — the identical render path `send_now` uses (Phase 6 D-06, byte-identical bar). CLI prints `.text` unchanged. |
</phase_requirements>

## Standard Stack

All dependencies already present in `pyproject.toml` — **no new runtime dependencies**.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| argparse | stdlib (3.12) | Subparser CLI dispatch | Already used in `main()`; `add_subparsers()` is the canonical stdlib pattern. [VERIFIED: codebase cli.py] |
| tenacity | >=9.1.4 | Bounded transient retry around `lookup_weather` | Exact `Retrying` pattern already in `run_send_now`. [VERIFIED: codebase pyproject.toml] |
| structlog | >=26.1.0 | Outcome-only logging; level control for D-09 quiet mode | Already the project logger. [VERIFIED: codebase] |
| (Phase 6) `weatherbot.interactive` | in-repo | `lookup_weather`, `LookupResult`, `UnknownLocationError` | The read-only fetch→render core this phase consumes. [VERIFIED: codebase interactive/lookup.py] |

### Supporting (build/packaging — NEW additions to pyproject.toml)
| Item | Value | Purpose | When to Use |
|------|-------|---------|-------------|
| `[build-system]` | `requires=["hatchling"]`, `build-backend="hatchling.build"` | Makes the project installable so `[project.scripts]` produces a console script | REQUIRED for D-03 — see Pitfall 1 |
| `[project.scripts]` | `weatherbot = "weatherbot.cli:main"` | The `weatherbot` console command (D-03) | Required deliverable |

> Alternative to a full build-system: `[tool.uv] package = true` forces uv to build/install the
> project even without `[build-system]`. Hatchling is the more conventional, portable choice
> (works under `pip install .` too); `[tool.uv] package = true` is uv-specific. Either satisfies D-03.
> [CITED: docs.astral.sh/uv/concepts/projects/config]

**Installation / verification (no new PyPI deps to add for runtime):**
```bash
# After editing pyproject.toml to add [build-system] + [project.scripts]:
uv sync                       # builds + installs weatherbot into the project venv
uv run weatherbot weather home  # the console script now resolves
uv run weatherbot --help        # confirm subparser help renders
```

**Version verification (2026-06-15):** Python 3.12.3, uv 0.11.19 confirmed on host via
`python3 --version` / `uv --version`. tenacity/structlog versions read from pyproject.toml.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| hatchling | PyPI | mature (PyPA) | very high | github.com/pypa/hatch | not run (env) | Approved — canonical PyPA build backend |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

> `hatchling` is the PyPA-maintained build backend (part of `hatch`), a HIGH-trust, ubiquitous
> package — not a hand-picked or obscure dependency. slopcheck was not run in this offline session;
> because hatchling is unambiguously the official PyPA backend (cited from packaging.python.org),
> the planner may treat it as approved, but may still gate the install behind a routine
> `uv sync` verification task. No other external packages are introduced this phase.

## Architecture Patterns

### System Architecture Diagram

```
                        argv  (e.g. ["weather", "home", "-v"])
                          │
                          ▼
                  ┌───────────────┐
                  │   main(argv)  │  argparse: parent(--config) + subparsers
                  └───────┬───────┘  bad usage ─────────► SystemExit(2)  [argparse]
              ┌───────────┼────────────┬──────────┬───────────┐
              ▼           ▼            ▼          ▼           ▼
          weather       run         check      send-now    geocode
              │      (daemon)    (do_check)  (run_send_now)(do_geocode)
              │       MIGRATED    MIGRATED     MIGRATED     MIGRATED
              ▼      (behavior unchanged — only the invocation surface changes)
   ┌──────────────────────────────────────────┐
   │ weather handler (NEW)                      │
   │  1. set log level (WARNING unless -v)      │ D-09
   │  2. config = _load_config_reporting(path)  │ None ─► exit 2
   │  3. settings = load_settings()             │
   │  4. Retrying(is_transient, 3x) wrapping:   │ D-08
   │       lookup_weather(name, config=…,       │
   │                      settings=…/client=…)  │
   └───────────┬───────────────┬────────────────┘
               │ ok            │ raises
               ▼               ▼
        print(text)→stdout   UnknownLocationError ─► stderr, exit 1   [CMD-04]
        exit 0               httpx auth/exhausted  ─► stderr, exit 3  [D-05/D-08]
```

### Recommended Project Structure
```
weatherbot/
├── cli.py            # main() restructured to subparsers; weather handler lives here
│                     #   (Discretion: a small interactive/cli.py is allowed, but cli.py
│                     #    already holds run_send_now/do_check/do_geocode — keeping the
│                     #    weather handler here avoids a new import edge and is simplest)
├── __main__.py       # unchanged routing (delegates to cli.main); docstring example updated
└── interactive/
    ├── lookup.py     # lookup_weather, LookupResult, UnknownLocationError  (consumed, untouched)
    └── command.py    # parse_weather_command  (OPTIONAL for CLI; reserved for P11)
```

### Pattern 1: argparse subparsers with a shared parent for `--config`
**What:** Define a parent parser holding the options every subcommand needs (`--config`), then
attach it to each subparser via `parents=[...]`. This keeps `--config` available *after* the
subcommand (`weatherbot weather --config X home`) which is the natural place once flags become
subcommands.
**When to use:** Always here — `--config` is global today and four of five subcommands need it.
**Example:**
```python
# Source: stdlib argparse pattern (https://docs.python.org/3/library/argparse.html#parents)
import argparse

def main(argv: list[str] | None = None) -> int:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--config", default="config.toml",
                        help="Path to the non-secret TOML config (default: config.toml).")

    parser = argparse.ArgumentParser(prog="weatherbot", description="…")
    sub = parser.add_subparsers(dest="command")          # dest lets us dispatch

    p_weather = sub.add_parser("weather", parents=[parent],
                               help="Print a configured location's briefing and exit.")
    p_weather.add_argument("location", nargs="?", default=None,
                           help="Configured location name (omit for the default location).")
    p_weather.add_argument("-v", "--verbose", action="store_true",
                           help="Show INFO logs (default: only the briefing + errors).")

    p_run     = sub.add_parser("run",      parents=[parent], help="Run the always-on scheduler.")
    p_check   = sub.add_parser("check",    parents=[parent], help="Validate config + one probe.")
    p_send    = sub.add_parser("send-now", parents=[parent], help="Send a briefing now.")
    p_send.add_argument("location", nargs="?", default=None)
    p_geo     = sub.add_parser("geocode",  help='Resolve "City, ST" to lat/lon.')
    p_geo.add_argument("query")

    args = parser.parse_args(argv)
    if args.command is None:        # bare `weatherbot` with no subcommand
        parser.print_help()
        return 0
    # dispatch on args.command → the handler functions (each returns int)
```
**Note on `dest=`:** Using `add_subparsers(dest="command")` gives a clean `args.command` string to
dispatch on — far cleaner than the current `hasattr(args, …)` probing, and it composes with
Phase 9 adding `reload`/`check-config` subparsers later.

### Pattern 2: The `weather` handler (the deliverable)
**What:** A function that owns log-level (D-09), config load (→exit 2), the bounded read-only
retry (D-08), and the stdout/stderr + exit-code mapping (D-05/D-06).
**Example:**
```python
# Mirrors run_send_now's Retrying but DROPS the retry_if_result arm (no DeliveryResult — D-08).
import logging, time, httpx
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential
from weatherbot.interactive import lookup_weather, UnknownLocationError
from weatherbot.reliability import is_transient

def run_weather(location_name, *, config, settings=None, client=None,
                templates_dir=None, verbose=False) -> int:
    retrying = Retrying(
        stop=stop_after_attempt(_MANUAL_MAX_ATTEMPTS),        # reuse =3
        wait=wait_exponential(multiplier=1, max=10),
        retry=retry_if_exception(is_transient),               # ONLY this arm (D-08)
        reraise=True,                                         # exhausted/permanent re-raised
        sleep=time.sleep,                                     # patchable seam for tests
    )
    try:
        result = retrying(lookup_weather, location_name,
                          config=config, settings=settings,
                          client=client, templates_dir=templates_dir)
    except UnknownLocationError as exc:                       # CMD-04 → exit 1
        print(str(exc), file=sys.stderr)                      # reuse message verbatim (D-06)
        return 1
    except httpx.HTTPStatusError as exc:                      # 401/403 or exhausted 5xx/429 → exit 3
        _log.error("weather lookup failed", status=exc.response.status_code)  # outcome only (T-04-01)
        return 3
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
        _log.error("weather lookup failed", error=type(exc).__name__)
        return 3
    print(result.text)                                        # briefing → stdout (D-06)
    return 0
```
**Critical ordering subtlety (NOT in `run_send_now`):** `UnknownLocationError` IS-A `ValueError`,
not an `httpx` error, and `is_transient` returns `False` for it — so it is re-raised on the first
attempt (never retried) and must be caught by an `except UnknownLocationError` arm placed **before**
any broad `except ValueError`. Because `resolve_location` runs inside `lookup_weather` before any
fetch, the unknown-location path never reaches the network. [VERIFIED: codebase loader.py + lookup.py]

### Pattern 3: Per-subcommand quiet logging (D-09)
**What:** `main()` currently calls `logging.basicConfig(level=logging.INFO)` unconditionally
(cli.py L390). To make `weather` quiet, do NOT call `basicConfig(INFO)` before knowing the
subcommand; instead set the root level based on the parsed command and `--verbose`.
**Example:**
```python
# After parse_args, before dispatch:
level = logging.INFO
if args.command == "weather" and not getattr(args, "verbose", False):
    level = logging.WARNING          # suppress lookup_weather's "lookup complete" INFO line
logging.basicConfig(level=level)
```
**Why this works:** `lookup_weather` emits its completion line via `_log.info("lookup complete", …)`
(lookup.py L146). structlog is configured to defer to stdlib logging levels in this project, so
raising the stdlib root level to WARNING suppresses that INFO line while leaving `_log.error(...)`
on the failure path visible. The other subcommands fall through to INFO unchanged — preserving
their existing behavior and tests. [VERIFIED: codebase lookup.py, cli.py]

### Anti-Patterns to Avoid
- **Calling `logging.basicConfig(INFO)` before parsing the subcommand.** It defeats D-09 because
  `basicConfig` is a no-op on its second call — once INFO is set you cannot quiet it cleanly.
  Decide the level *after* parsing.
- **Re-fetching or re-rendering in the `weather` handler.** CMD-05 demands the exact v1 template;
  `lookup_weather` already renders it. The handler prints `.text` and nothing else.
- **Adding `--run`/`--send-now` back as hidden aliases.** D-02 is an explicit clean break; aliases
  reintroduce the dual-surface the operator chose to remove.
- **Putting the retry inside `lookup_weather`.** The retry locus is the attended handler (mirrors
  `run_send_now` keeping `send_now` single-attempt). Keeping `lookup_weather` single-attempt also
  preserves Phase 6's read-only-core contract and its tests.
- **Letting a raw traceback escape on a bad `--config`.** Reuse `_load_config_reporting` so a
  config error logs cleanly and the handler returns exit 2 (no traceback) — same bar as CONF-05.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Subcommand parsing | Manual `sys.argv[1]` switch | `argparse.add_subparsers(dest=…)` | Free `--help` per subcommand, usage errors, exit-2 semantics |
| Transient retry/backoff | Hand-rolled loop + sleep | `tenacity.Retrying` (copy `run_send_now`) | Already tested; jitter/cap/predicate composition is subtle |
| Transient-vs-permanent classification | New status-code set | `weatherbot.reliability.is_transient` | Single source of truth; 401/403 never retried already encoded |
| Unknown-location message + valid-names list | Re-derive from config | `UnknownLocationError` (`.requested`/`.valid_names`, formatted message) | Phase 6 already carries it; CMD-04 message is verbatim |
| Fetch→render | New lookup path | `lookup_weather` → `LookupResult.text` | Phase 6 read-only core; guarantees CMD-05 byte-identical template |
| Console-script shim | A bash wrapper / `if __name__` hack | `[project.scripts]` + build-system | Standard packaging; resolves under `uv run` and plain installs |

**Key insight:** The deliverable is ~40 lines of glue. Almost all complexity (fetch, render,
retry classification, error typing) was deliberately pushed into Phase 6 and the reliability layer.
The phase's real work is the *restructure* (subparsers + packaging + deploy artifacts) and not
regressing 206 tests while doing it.

## Runtime State Inventory

> This phase is partly a **refactor** (flag→subparser clean break) + a **packaging/deploy change**,
> so the inventory applies.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `weather` is read-only (D-04); writes nothing to SQLite. Verified: handler calls only `lookup_weather`, which imports no store function (lookup.py). | none |
| Live service config | **systemd unit on `yahir-mint`** runs `ExecStart=/usr/bin/uv run weatherbot --run`. After the clean break, `--run` no longer parses → the daemon would fail to start. The unit file on the host is NOT in git in its substituted form (placeholders are; the deployed copy lives in `/etc/systemd/system/`). | **Ops/UAT:** edit deployed unit to `… weatherbot run`, `systemctl daemon-reload`, restart, confirm `active (running)`. Surface as explicit UAT step (D-02). |
| OS-registered state | systemd service name `weatherbot.service` unchanged — only the `ExecStart` command string changes. No task/unit rename. | daemon-reload only |
| Secrets/env vars | None renamed. `OPENWEATHER_API_KEY` / `DISCORD_WEBHOOK_URL` via `.env`/`EnvironmentFile=` unchanged. | none |
| Build artifacts / installed packages | **Adding `[build-system]` + `[project.scripts]` changes the project from "not installed" to "installed package".** `uv sync` must run to materialize the `weatherbot` console script in `.venv/bin/`. On the host, the redeploy must re-sync (or the venv must already contain the script) for `uv run weatherbot` to resolve. | `uv sync` locally AND on host as part of redeploy. |

**The canonical question — after every repo file is updated, what runtime systems still have the
old invocation?** The deployed systemd unit on `yahir-mint` (its `ExecStart` still says `--run`).
That is the single runtime-state item requiring an out-of-repo action, and it is an ops/UAT step,
not a code change (D-02).

## Common Pitfalls

### Pitfall 1: `[project.scripts]` silently does nothing without a build-system
**What goes wrong:** You add `[project.scripts] weatherbot = "weatherbot.cli:main"`, run `uv run
weatherbot weather home`, and get "command not found" / uv treats the project as a non-package.
The deployed `ExecStart=/usr/bin/uv run weatherbot run` then also fails on the host.
**Why it happens:** Entry-point tables require a build backend. The current `pyproject.toml` has
**no `[build-system]` section** (verified via grep). Without it (or `[tool.uv] package = true`),
uv does not install the project, so no console script is generated.
[CITED: packaging.python.org/en/latest/guides/writing-pyproject-toml; docs.astral.sh/uv/concepts/projects/config]
**How to avoid:** Add `[build-system]` with `requires=["hatchling"]`,
`build-backend="hatchling.build"` (or `[tool.uv] package = true`), then `uv sync` so the script
materializes. Add a verification task: `uv run weatherbot --help` exits 0.
**Warning signs:** `uv run weatherbot ...` errors; `.venv/bin/weatherbot` absent; `uv sync` logs
"project is marked as not a package".

### Pitfall 2: The existing CLI tests call removed flags and will fail
**What goes wrong:** After the clean break, `tests/test_cli.py` still calls
`main(["--check", "--config", str(bad)])` (L295/308/314) and `main(["--send-now", "--config",
str(bad)])` (L322). argparse no longer recognizes `--check`/`--send-now` → it prints usage to
stderr and raises `SystemExit(2)`. Those tests expect `rc == 1` and will error, not just fail.
**Why it happens:** D-02 removes the flags but the tests encode the old surface.
**How to avoid:** Rewrite those four calls to subcommand form (`main(["check", "--config", …])`,
`main(["send-now", "--config", …])`) *in this phase*. This is mandatory to keep "206 green," and
it is legitimately part of the migration, not scope creep. Audit the whole suite for any other
`main([...])` call using a removed flag. [VERIFIED: codebase tests/test_cli.py L295-322]
**Warning signs:** `SystemExit: 2` in pytest output; tests under `test_check_*`/`test_send_now_*`
that drive `main()` failing.

### Pitfall 3: argparse exit-2 collides with D-05's "config invalid = 2"
**What goes wrong:** Both a usage error (unknown subcommand, bad flag) and an invalid config map to
exit 2, so a test asserting "exit 2 means config invalid" can be satisfied by an unrelated usage
error, masking a real bug.
**Why it happens:** argparse hardcodes `SystemExit(2)` for usage errors; D-05 also chose 2.
**How to avoid (per D-07):** The overlap is acceptable since both mean "your input was wrong."
Document the final mapping explicitly in the plan. If the planner wants disambiguation, override
`parser.error` or catch `SystemExit` in `main()` and remap — but the simplest correct choice is to
*keep* the overlap and ensure config-invalid tests drive a *valid* subcommand with a *bad config
file* (so the exit-2 they observe is genuinely from `_load_config_reporting`, not argparse). Note:
`main()` returns an int; argparse's `SystemExit(2)` is raised *inside* `parse_args`, so a test
calling `main([...])` with a bad subcommand sees a raised `SystemExit`, whereas a bad config file
returns `2`. Tests can therefore distinguish them (`pytest.raises(SystemExit)` vs `== 2`).
**Warning signs:** A config-error test passing for the wrong reason; ambiguous failure triage.

### Pitfall 4: Quiet-mode set too early or via the wrong logger
**What goes wrong:** `weather` still prints `[info] lookup complete location=home`, polluting
pipeable stdout/stderr (fails the D-09 UX target).
**Why it happens:** `logging.basicConfig(INFO)` was already called (no-op on second call), or the
level was set on the wrong logger.
**How to avoid:** Set the level *after* parsing, based on `args.command`/`--verbose`, on the root
via `basicConfig(level=…)` exactly once. Verify the suppressed line is the one in `lookup.py`
(`_log.info("lookup complete", …)`). [VERIFIED: codebase lookup.py L146]
**Warning signs:** INFO lines on a bare `weatherbot weather home`; `-v` showing no extra output.

### Pitfall 5: A read-only retry that accidentally retries an auth failure
**What goes wrong:** A 401/403 (bad/propagating key) gets retried 3× and only then surfaced —
slow and against D-08.
**Why it happens:** Wrong predicate, or copying `run_send_now`'s `retry_if_result` arm.
**How to avoid:** Use `retry=retry_if_exception(is_transient)` ONLY. `is_transient` returns
`False` for 401/403 (they are in `PERMANENT`), so `reraise=True` re-raises on the first attempt →
caught by the `except httpx.HTTPStatusError` arm → exit 3 immediately. [VERIFIED: codebase
reliability/retry.py: `PERMANENT = {400,401,403,404}`]
**Warning signs:** A 401 test taking 3 attempts; `retry_if_result` present in the `weather` retry.

## Code Examples

### Mapping the four exit codes (the full handler control flow)
```python
# Source: synthesized from codebase run_send_now (cli.py) + lookup_weather (interactive/lookup.py)
def _cmd_weather(args) -> int:
    # log level (D-09) is set in main() before this is called
    config = _load_config_reporting(args.config)
    if config is None:
        return 2                       # config invalid/missing (D-05) — was exit 1 for old flags
    settings = load_settings()
    return run_weather(args.location, config=config, settings=settings,
                       verbose=args.verbose)
    # run_weather returns 0 / 1 (UnknownLocationError) / 3 (fetch/auth) as in Pattern 2
```
> **Migration note:** the *migrated* `check`/`run`/`send-now`/`geocode` handlers should keep their
> **existing** return codes (they return 0/1 today). Only the new `weather` command uses the
> richer 0/1/2/3 scheme. Mixing is fine — D-05 scopes the 4-code contract to `weather`.

### Offline test of the `weather` command (exit-code + stream assertions)
```python
# Source: pattern from tests/test_cli.py + tests/test_lookup.py (_FakeClient, capsys)
def test_weather_unknown_location_exits_1(capsys):
    client = _FakeClient(onecall_imp=..., onecall_met=...)   # never reached
    rc = run_weather("nope", config=_config(), client=client)
    assert rc == 1
    err = capsys.readouterr().err
    assert "No location named 'nope'" in err                 # CMD-04 message verbatim
    assert "New York" in err                                 # valid names listed

def test_weather_prints_briefing_exit_0(capsys, load_fixture):
    client = _FakeClient(onecall_imp=load_fixture("onecall_imperial_clear.json"),
                         onecall_met=load_fixture("onecall_metric_clear.json"))
    rc = run_weather(None, config=_config(), client=client)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()                                       # briefing on stdout
```
> Inject `client=` (the `_FakeClient` from `test_lookup.py`/`test_cli.py`) so the lazy
> `build_client` import never runs and no network is touched — mirrors the established offline
> seam. For the retry-exhaustion exit-3 test, patch `sleep` (the `sleep=time.sleep` seam) and have
> the fake client raise `httpx.HTTPStatusError(429)` every call; assert `rc == 3` and bounded attempts.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat `--flag` + `argparse.SUPPRESS` + `hasattr` dispatch | `add_subparsers(dest=…)` + per-command handlers | This phase (D-01) | Cleaner dispatch; composes with Phase 9 subcommands |
| `python -m weatherbot --run` only | `weatherbot run` console script + `python -m weatherbot run` | This phase (D-02/D-03) | Verbatim `weatherbot weather home` works (ROADMAP SC#1) |
| No `[build-system]` (project not installed) | hatchling backend / `[tool.uv] package=true` | This phase (D-03) | Console scripts materialize on `uv sync` |

**Deprecated/outdated:**
- The `--run`/`--check`/`--send-now`/`--geocode` flags — removed by D-02 (clean break, no aliases).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | structlog defers to the stdlib root logging level, so raising root to WARNING suppresses `lookup_weather`'s `_log.info("lookup complete")` | Pattern 3 / Pitfall 4 | If structlog is configured with its own level filter independent of stdlib, D-09 quieting needs a structlog-level change instead. **Verify** the project's structlog config before locking the mechanism. |
| A2 | hatchling is the right build backend (vs `[tool.uv] package=true`) | Standard Stack | Low — both satisfy D-03; planner may choose either. Discretion. |
| A3 | No other test file beyond `test_cli.py` drives `main([...])` with a removed flag | Pitfall 2 | If another suite calls `main(["--send-now", …])`, it also breaks. **Verify** with a repo-wide grep during planning. |
| A4 | The host `.venv` will contain the `weatherbot` script after a redeploy `uv sync` | Runtime State Inventory | If the host runs option (b) `<REPO>/.venv/bin/python -m weatherbot run`, the console script is irrelevant there — `__main__.py` routing still works. Confirm which ExecStart form `yahir-mint` uses. |

## Open Questions (RESOLVED)

1. **structlog ↔ stdlib level coupling (A1).**
   - What we know: `lookup_weather` logs via `structlog.get_logger`; `main()` uses
     `logging.basicConfig(INFO)`; other subcommands rely on INFO output appearing.
   - What's unclear: exact structlog configuration (is there a `wrap_logger`/`make_filtering_bound_logger`
     pinning a level independent of stdlib?).
   - Recommendation: planner adds a Wave-0 check — grep for `structlog.configure`/`make_filtering_bound_logger`;
     if present, scope D-09 via structlog's level, else via `basicConfig(level=…)`. A test that asserts
     no INFO line on `weather` (and one appears with `-v`) pins the behavior either way.
   - **RESOLVED:** Use the stdlib root level (A1 confirmed in 07-02) — D-09 quieting is scoped via `basicConfig(level=…)`, and the quiet-vs-`-v` test in 07-03 Task 2 pins that no `lookup complete` INFO line appears without `-v` and one does with it.

2. **Does the `weather` handler invoke `parse_weather_command`? (Discretion)**
   - What we know: argparse already supplies the positional `location`; `parse_weather_command`
     exists primarily for P11's free-text Discord input.
   - Recommendation: the CLI does NOT need `parse_weather_command` — argparse tokenization already
     gives a clean location string. Reserve the parser for P11. (Either is consistent with Phase 6.)
   - **RESOLVED:** No — the `weather` handler does NOT use `parse_weather_command`; argparse already yields a clean positional `location`, and the parser stays reserved for P11's free-text Discord input.

3. **Final exit-code numbering given the argparse-2 overlap (Discretion / D-07).**
   - Recommendation: keep the overlap (both mean "bad input"), document the mapping in the plan, and
     write config-invalid tests so the observed `2` comes from `_load_config_reporting` returning,
     not from an argparse `SystemExit`.
   - **RESOLVED:** Keep the argparse-2 / config-invalid-2 overlap; both signal "bad input," the mapping is documented in 07-03, and config-invalid tests assert the `2` comes from `_load_config_reporting` returning (not an argparse `SystemExit`).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | runtime | ✓ | 3.12.3 | — |
| uv | console-script install, `uv run` | ✓ | 0.11.19 | `.venv/bin/python -m weatherbot` (no console script needed) |
| hatchling | build backend for `[project.scripts]` | resolved by uv at sync | (PyPA) | `[tool.uv] package = true` |
| Network / OpenWeather | live `weather` runs only | n/a offline | — | tests inject `_FakeClient` (no network) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none blocking — build backend is fetched by `uv sync`.

## Validation Architecture

> `workflow.nyquist_validation` not disabled in config → section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=9.0.3 (`[dependency-groups] dev`) |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| Quick run command | `uv run pytest tests/test_cli.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CMD-01 | `weather home` prints briefing, exit 0, no daemon/send/persist | unit | `uv run pytest tests/test_cli.py -k weather_prints` | ❌ Wave 0 |
| CMD-03 | bare `weather` → default location (`name=None`) | unit | `uv run pytest tests/test_cli.py -k weather_default` | ❌ Wave 0 |
| CMD-04 | unknown location → stderr lists valid names, exit 1, no geocode | unit | `uv run pytest tests/test_cli.py -k weather_unknown` | ❌ Wave 0 |
| CMD-05 | printed text == exact v1 template render | unit | `uv run pytest tests/test_cli.py -k weather_template` | ❌ Wave 0 |
| D-05 (cfg) | bad/missing `--config` → exit 2, no traceback | unit | `uv run pytest tests/test_cli.py -k weather_bad_config` | ❌ Wave 0 |
| D-05/D-08 | exhausted transient / 401 → exit 3, bounded attempts | unit | `uv run pytest tests/test_cli.py -k weather_fetch_fail` | ❌ Wave 0 |
| D-09 | quiet by default; `-v` shows INFO | unit | `uv run pytest tests/test_cli.py -k weather_quiet` | ❌ Wave 0 |
| migration | `check`/`run`/`send-now`/`geocode` subcommands preserve behavior | unit (rewrite) | `uv run pytest tests/test_cli.py` | ⚠️ exists, must be updated (Pitfall 2) |
| D-03 | console script resolves | smoke | `uv run weatherbot --help` (exit 0) | ❌ Wave 0 (manual/CI smoke) |
| regression | all v1 behavior intact | full | `uv run pytest` (206 → green) | ✅ |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_cli.py -x`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** full suite green (≥206 tests; new `weather` tests added) + `uv run weatherbot --help`
  exits 0 before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] New `weather`-subcommand tests in `tests/test_cli.py` (exit 0/1/2/3, stdout/stderr split,
      quiet-vs-`-v`, bounded retry) — covers CMD-01/03/04/05 + D-05/D-08/D-09.
- [ ] Rewrite existing `main(["--check"/"--send-now", …])` calls (L295/308/314/322) to subcommand
      form — covers the migration regression bar (Pitfall 2).
- [ ] Smoke check that `[build-system]`+`[project.scripts]` produce a resolvable `weatherbot`
      script (`uv run weatherbot --help`) — covers D-03 (Pitfall 1).
- [ ] No new fixtures needed — reuse `tests/fixtures/onecall_*.json` and the established
      `_FakeClient`/`load_fixture`/`capsys` seams.

## Security Domain

> `security_enforcement` not disabled → section included.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user auth surface; OpenWeather key is the only credential (env-only) |
| V3 Session Management | no | One-shot CLI, no sessions |
| V4 Access Control | partial | systemd unit runs as non-root `<USER>` (existing); `weather` is read-only — no privilege change |
| V5 Input Validation | yes | argparse tokenizes input; location matched via casefold equality against configured names only — no geocoding/arbitrary-city path (CMD-04). No `str.format`/`eval`/shell on user input. |
| V6 Cryptography | no | No crypto introduced |
| V7 Error/Logging hygiene | yes | T-04-01: errors are outcome-only; never log `appid`/webhook URL. `UnknownLocationError` carries only names, never secrets (verified in lookup.py docstring). |

### Known Threat Patterns for this stack (one-shot CLI)
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leakage via error/log on the failure path | Information Disclosure | Outcome-only logging (T-04-01); `_log.error(status=…)` / `error=type(exc).__name__`, never the key/URL — mirror `run_send_now`/`do_geocode` |
| Arbitrary-location / geocoding abuse | Tampering / Elevation | Configured-locations-only (CMD-04); no geocode reachable from `weather`; raw name passed only to a casefold equality match |
| Command-injection via location arg | Injection | Location is never interpolated into a shell/`format`/`eval` — passed as data to `resolve_location` (verified parser/lookup code) |
| Untrusted `Retry-After` blowing the retry budget | DoS (self-inflicted) | `weather`'s retry uses `wait_exponential(max=10)` + 3 attempts — bounded regardless of header; the daemon's capped parser is not on this path |

## Sources

### Primary (HIGH confidence)
- Codebase (verified by Read/grep, 2026-06-15): `weatherbot/cli.py` (`main` L388, `run_send_now`
  L181, `_load_config_reporting` L367, `build_client` L82), `weatherbot/interactive/lookup.py`
  (`lookup_weather`, `LookupResult`, `UnknownLocationError`), `weatherbot/interactive/command.py`,
  `weatherbot/reliability/retry.py` (`is_transient`, `PERMANENT`/`TRANSIENT`),
  `weatherbot/config/loader.py` (`resolve_location`), `weatherbot/__main__.py`,
  `pyproject.toml` (no `[build-system]`), `deploy/weatherbot.service` (L29 ExecStart),
  `deploy/README.md`, `tests/test_cli.py` (L295-322 flag calls), `tests/test_lookup.py`.
- packaging.python.org — entry-point tables require a `[build-system]`.
- Python `argparse` docs — `add_subparsers`, `parents=`.

### Secondary (MEDIUM confidence)
- docs.astral.sh/uv/concepts/projects/config — `[tool.uv] package = true` overrides build-system
  detection; `[project.scripts]` resolved by `uv run` only when the project is built/installed.

### Tertiary (LOW confidence)
- A1 (structlog↔stdlib level coupling) — inferred from project usage of `logging.basicConfig`;
  flagged for Wave-0 verification.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all runtime deps already present and verified; packaging requirement
  confirmed against two authoritative sources.
- Architecture: HIGH — handler/retry/error patterns are direct adaptations of tested codebase code.
- Pitfalls: HIGH — Pitfalls 1 (no build-system) and 2 (tests call removed flags) verified directly
  against pyproject.toml and tests/test_cli.py.
- D-09 mechanism: MEDIUM — depends on A1 (structlog config), flagged as Open Question 1.

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable stdlib + pinned deps; uv evolves faster — re-verify uv
packaging behavior if uv major version changes)
