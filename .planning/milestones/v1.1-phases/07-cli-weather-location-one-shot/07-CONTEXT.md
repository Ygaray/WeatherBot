# Phase 7: CLI `weather [location]` One-Shot - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship the first user-facing surface of v1.1: a standalone, **daemon-free** CLI command
`weatherbot weather [location]` that prints a configured location's briefing to the
terminal and exits, reusing the Phase 6 read-only `lookup_weather` core and the exact
v1 briefing template. Closes **CMD-01, CMD-03, CMD-04, CMD-05**.

Concretely:
1. `weatherbot weather home` resolves the configured location `home`, fetches/renders via
   `lookup_weather`, prints `LookupResult.text` to **stdout**, exits 0 — no running daemon, no
   Discord send, no DB write (CMD-01, read-only per Phase 6 D-05/D-06).
2. Bare `weatherbot weather` (no arg) → `resolve_location(config, None)` → first/default
   configured location (CMD-03).
3. `weatherbot weather <unknown>` → clear stderr error listing valid configured names, no
   geocoding fallback, non-zero exit (CMD-04).
4. Output uses the exact v1 template — no separate on-demand format (CMD-05).

**Scope expansion accepted this phase (operator decision):** the CLI is being restructured
from flat flags to **argparse subcommands** with a real `weatherbot` console-script entry
point, and the deployment artifacts are updated to match. This is a deliberate clean break
done now (not deferred) — see D-01..D-04.

**Out of scope (own phases):** Discord bot reply surface (P11/CMD-02), short-TTL fetch cache
(P11/CMD-06), config hot-reload + `weatherbot reload` / `--check-config` (P8–10/CFG-*),
geocoded/arbitrary-city lookup (v2/CMD-V2-02). Phase 9 will *add* `reload` and `check-config`
subcommands on top of the subparser structure built here — but their logic is not this phase.
</domain>

<decisions>
## Implementation Decisions

### CLI surface & invocation
- **D-01: Restructure `main()` to argparse subparsers.** Introduce subcommands
  `weather`, `run`, `check`, `send-now`, `geocode`. The new `weather` subcommand is the
  deliverable; the others are migrations of today's flags. This replaces the current flat
  `--flag` + `hasattr`-dispatch shape in `weatherbot/cli.py`.
- **D-02: Clean break — drop the old flags.** `--run` / `--check` / `--send-now` / `--geocode`
  are REMOVED, not kept as aliases. The operator explicitly chose the clean CLI now over a
  back-compat-alias path. **Consequence (mandatory in this phase):** update
  `deploy/weatherbot.service` (`ExecStart` → the `run` subcommand form) and `deploy/README.md`
  so the deployed daemon invocation matches. The live host `yahir-mint` must be redeployed
  (`systemctl daemon-reload` + restart) — this is an **ops/UAT item**, not a code change.
- **D-03: Add a real console-script entry point.** Add `[project.scripts]
  weatherbot = "weatherbot.cli:main"` to `pyproject.toml` so `weatherbot weather home` works
  verbatim (ROADMAP SC#1). Today only `python -m weatherbot …` resolves; the deployed
  `ExecStart=/usr/bin/uv run weatherbot --run` template line currently relies on a console
  script that does not yet exist — this fixes that too.
- **D-04: Read-only command, reuses Phase 6 core.** `weather` calls `parse_weather_command`
  (optional — argparse already gives the positional location; the parser is more relevant to
  P11's free-text Discord input) then `lookup_weather(name, config=…, settings=…)` and prints
  `.text`. No `send`, no `persist`, no daemon. Bare `weather` → `name=None` → default location.

### Errors & exit codes
- **D-05: Distinct exit codes per failure class** (operator chose this over a flat exit 1):
  - `0` — briefing printed OK
  - `1` — unknown / unconfigured location (user error; CMD-04)
  - `2` — config invalid or missing (bad TOML, missing required field, bad `--config` path)
  - `3` — fetch / API / network failure (incl. exhausted transient retry, 401/403 auth)
- **D-06: Briefing → stdout, all errors → stderr.** stdout carries only the briefing text so
  it is cleanly pipeable. Unknown-location error reuses `UnknownLocationError`'s existing
  message verbatim (`"No location named 'X'; configured locations: a, b"`), printed to stderr.
- **D-07 (planner note, not a blocked decision): argparse usage-error overlap.** argparse
  exits `2` on bad CLI usage, which collides with D-05's "config invalid = 2". Both mean
  "your input was wrong," so the overlap is acceptable; the planner may keep it or renumber
  deliberately — just do so consciously and document the final mapping.

### Transient fetch retry
- **D-08: Mirror `run_send_now`'s short bounded retry, adapted for read-only.** Wrap the
  `lookup_weather` call in a thin tenacity `Retrying` (~3 attempts, exponential backoff cap
  ~10s) that retries **transient exceptions only** (reuse the existing `is_transient`
  predicate: timeout / connect / 5xx / 429-with-Retry-After). **Never** retry 401/403 (auth).
  Because `weather` is read-only there is NO `DeliveryResult`, so the `retry_if_result(not
  r.ok)` arm of `run_send_now` does NOT apply — only `retry_if_exception(is_transient)`.
  Exhausted transient or permanent auth error → stderr message (outcome only, never key/URL —
  T-04-01) + exit 3.

### Output cleanliness
- **D-09: `weather` is quiet by default; `--verbose`/`-v` restores INFO.** For the `weather`
  subcommand, raise the effective log level to WARNING so the terminal shows ONLY the briefing
  (stdout) and real errors (stderr) — suppressing `lookup_weather`'s `"lookup complete"` INFO
  line. A `--verbose`/`-v` flag drops the level back to INFO for debugging. (Other subcommands
  keep their existing INFO behavior; this quieting is scoped to the user-facing print command.)

### Claude's Discretion (planner/researcher decide)
- Exact subcommand names where ambiguous (`send-now` vs `send`), and whether `--config` is a
  global/parent-parser option vs per-subcommand (it is global today; subparsers usually attach
  shared options on the parent or via `parents=[…]`).
- Where the `weather` handler lives (`weatherbot/cli.py` vs a small `interactive/cli.py`),
  and how to wire `--verbose` (per-subcommand flag vs a global one applied selectively).
- Whether `parse_weather_command` is invoked by the CLI at all (argparse already supplies the
  positional location) or reserved for P11's free-text path — either is consistent with Phase 6.
- The precise final exit-code numbering if D-07's argparse-2 overlap is renumbered.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 7: CLI `weather [location]` One-Shot" — goal + the 4 success
  criteria (CMD-01/03/04/05) this phase is judged against.
- `.planning/REQUIREMENTS.md` — CMD-01 (standalone CLI, no daemon), CMD-03 (bare = default
  location), CMD-04 (unknown → error lists valid names, no geocoding), CMD-05 (reuse exact v1
  template).
- `.planning/phases/06-shared-lookup-core-command-parser/06-CONTEXT.md` — the read-only core
  contract this phase consumes (D-05 `LookupResult`, D-06 read-only, D-07 `UnknownLocationError`).
- `.planning/research/PITFALLS.md` — project pitfalls log; T-04-01 (never log key/URL on the
  error path), read-only-w.r.t.-scheduled-series constraint.

### v1.0 code seams this phase touches / reuses
- `weatherbot/cli.py` — `main()` (~L388, the flag parser being restructured to subparsers),
  `run_send_now` (~L181, the retry pattern to mirror — `_MANUAL_MAX_ATTEMPTS`, `is_transient`,
  `Retrying`), `do_check`/`do_geocode`/`--run` daemon dispatch (the flags being migrated),
  `_load_config_reporting` (~L367, clean config-error reporting → exit 2).
- `weatherbot/interactive/lookup.py` — `lookup_weather(name, *, config, settings, client, …)`
  → `LookupResult(.text/.forecast/.location)`; `UnknownLocationError(.requested, .valid_names)`.
- `weatherbot/interactive/command.py` — `parse_weather_command` / `Command` / `CommandKind`
  (optional for the CLI; primary consumer is P11).
- `weatherbot/__main__.py` — `python -m weatherbot` entry (delegates to `cli.main`).
- `weatherbot/reliability.py` — `is_transient` predicate (retry classification, D-08).
- `weatherbot/config/__init__.py` — `resolve_location`, `load_config`, `load_settings`.

### Deployment artifacts to update (D-02)
- `pyproject.toml` — add `[project.scripts] weatherbot = "weatherbot.cli:main"` (D-03).
- `deploy/weatherbot.service` — `ExecStart` line currently `… weatherbot --run` (L29) → `run`
  subcommand form.
- `deploy/README.md` — the invocation examples (`weatherbot --run`, `python -m weatherbot --run`)
  → subcommand form.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `lookup_weather` + `LookupResult` (Phase 6) — the entire fetch→render core; the CLI just
  resolves a name, calls it, and prints `.text`. No new fetch/render logic.
- `UnknownLocationError` — already carries `.requested` + `.valid_names` and formats the CMD-04
  message; the CLI catches it → stderr + exit 1.
- `run_send_now`'s `Retrying` block (`_MANUAL_MAX_ATTEMPTS=3`, `wait_exponential(max=10)`,
  `retry_if_exception(is_transient)`, `sleep=` patchable seam) — the exact retry template to
  copy for D-08, minus the `DeliveryResult` arm.
- `_load_config_reporting` — already turns load failures into clean (no-traceback) outcomes;
  reuse so config errors map cleanly to exit 2.

### Established Patterns
- v1.0 CLI dispatch is flag-based with `argparse.SUPPRESS` + `hasattr(args, …)`. D-01 replaces
  this with subparsers — verify all four existing flag behaviors survive the migration
  (`run`/`check`/`send-now`/`geocode`) with their existing exit semantics intact.
- Logging is `logging.basicConfig(level=INFO)` in `main()`; errors are outcome-only and never
  echo secrets (T-04-01). D-09 quiets `weather` to WARNING.
- Injectable seams (`client`, `settings`, `templates_dir`) on `lookup_weather`/`send_now` →
  the `weather` handler should accept the same so it's unit-testable offline against
  `tests/fixtures/onecall_*.json`.

### Integration Points
- `weatherbot/cli.py` `main()` is the single dispatch point being restructured.
- New `weatherbot` console entry point (pyproject) becomes the canonical invocation; `python -m
  weatherbot` continues to work via `__main__.py`.
- The deployed systemd unit is a downstream consumer of the CLI surface — D-02 makes updating
  it part of this phase's done-definition.
</code_context>

<specifics>
## Specific Ideas

- SC#1 must work verbatim: `weatherbot weather home` (console script), not only
  `python -m weatherbot weather home`.
- Quiet-by-default UX target (D-09): `weatherbot weather home` prints just the briefing;
  `weatherbot weather home -v` additionally shows `[info] lookup complete location=home`.
- Exit-code contract is testable: assert `0` on a configured name, `1` on an unknown name (and
  that valid names appear on stderr), `2` on a bad/missing config, `3` on a simulated fetch
  failure / exhausted transient retry.
- Migration regression bar: the existing `run`/`check`/`send-now`/`geocode` behaviors and the
  v1.0 test suite (206 tests) stay green after the subparser restructure.
</specifics>

<deferred>
## Deferred Ideas

- **Discord bot `weather <loc>` reply (CMD-02) + short-TTL cache (CMD-06)** — Phase 11; the CLI
  here does not cache and does not touch Discord.
- **`weatherbot reload` + `weatherbot --check-config` / `check-config` subcommand (CFG-02/08)** —
  Phases 9; they extend the subparser structure built here but are not implemented now.
- **Geocoded / arbitrary-city `weather <any city>` (CMD-V2-02)** — v2; CLI stays
  configured-locations-only.
- **Deprecating-vs-removing old flags** — operator chose a clean break (D-02), so no
  deprecation-window path; noted in case a future operator wants alias compatibility.

None of these were folded into Phase 7 scope.
</deferred>

---

*Phase: 7-CLI `weather [location]` One-Shot*
*Context gathered: 2026-06-15*
