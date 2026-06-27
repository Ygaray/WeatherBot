# Phase 16: Extract Shared `dispatch_spec` - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-23
**Phase:** 16-extract-shared-dispatch-spec
**Areas discussed:** Extraction scope, Seam (fetch + async shape), Drift-proof binding, Module placement

> Process note: pure codebase-internal refactor (no vendor/framework choice).
> Advisor-mode web-research agents were skipped; trade-offs were grounded directly
> in the project's own code (`bot.py`, `cli.py`, `registry.py`, `command.py`,
> `cache.py`, `lookup.py`), which were read in full before presenting options.
> User requested a plain-language re-framing of the dispatcher-shape options
> before deciding.

---

## Dispatcher shape (Areas 1 + 2: scope + seam, decided together)

| Option | Description | Selected |
|--------|-------------|----------|
| B — two-layer, unify all | Sync `dispatch_reply(...)` = the single ladder; async `dispatch_spec(...)` = fetch + `dispatch_reply` for bot/panel; CLI calls `dispatch_reply` directly, keeps its own retry/exit codes. One ladder in the whole codebase; CLI byte-identical. | ✓ |
| A — async, on_message-only | Research's literal proposal: async `dispatch_spec` owns fetch+ladder for bot + panel; `cli.py` untouched. Simplest, but leaves cli.py's identical ladder (violates criterion #3). | |
| C — single sync fetch-owner | One function, fetch injected; bot wraps in executor, CLI calls direct. Folds handler into the CLI's retried fetch scope — risks retry boundary + dual error messages. | |

**User's choice:** B — fix everywhere, two layers.
**Notes:** Chosen after a plain-language explanation. Core mental model: the
copy-pasted "who-needs-what" if/elif ladder becomes a single shared piece; each
surface keeps its own (legitimately different) fetch/retry style. Rendering
(`render_embed`/`render_text`) and surface-specific error handling stay at the
call site — locked, not asked (research is unambiguous on the `CommandReply` seam).

---

## Drift-proof binding (Area 3)

| Option | Description | Selected |
|--------|-------------|----------|
| Keep if/elif, one place | Shared ladder branches on command name in a single location. Behavior-preserving; existing-shape commands need zero edits, a new shape needs one line. | ✓ |
| Declarative on each command | Each registry entry carries its own arg-binding callable; ladder disappears. Most future-proof but redefines `CommandSpec` and moves dispatch into the registry — more than this groundwork phase needs. | |

**User's choice:** Keep if/elif, one place.
**Notes:** Fully-declarative noted as a deferred refinement (revisit if handler
arg-shapes proliferate).

---

## Module placement (Area 4)

| Option | Description | Selected |
|--------|-------------|----------|
| New `dispatch.py` | `weatherbot/interactive/dispatch.py`. Keeps registry/command lean, avoids import cycle, one-job-per-file. | ✓ |
| Fold into `registry.py` | Co-locate with the source of truth, but drags cache/lookup/daemon_state imports into the lean registry and risks a circular import. | |

**User's choice:** New `dispatch.py`.
**Notes:** Acyclic — nothing imports `dispatch`, so it may freely import
`registry`/`command`; heavy types via `TYPE_CHECKING`.

---

## Claude's Discretion

- Exact parameter names/ordering and whether `dispatch_spec` takes `cache`+`loop`
  vs a small fetch closure — planner/executor's call, as long as the two-layer
  split holds.
- Whether the forecast-flags parse lives inside `dispatch_spec` (recommended,
  keeps bot + panel DRY) or is threaded in by the caller.

## Deferred Ideas

- Fully-declarative arg-binding on `CommandSpec` (ladder-free dispatch).
- All panel UI/behavior — Phases 17-20.
