# Phase 16: Extract Shared `dispatch_spec` - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Lift the heterogeneous arg-adaptation ladder — the if/elif block that decides
"what does each registry command's handler need to be handed" — out of
`on_message` (`bot.py:313-329`) AND its identical twin in
`cli.py:_run_registry_command` (`cli.py:618-632`) into **one shared dispatcher**,
so the command set can never drift across surfaces (PANEL-10). Pure,
behavior-preserving groundwork laid BEFORE any panel callback exists, so the
panel (Phase 17) can only ever be a third caller of the same code.

**In scope:** extract the arg-binding ladder to a single location; route
`on_message` and the CLI through it; return a surface-agnostic `CommandReply`;
keep every existing reply byte-identical (proven by existing tests).

**Out of scope:** any panel code (Phase 17+), any new command, any new weather
data/dependency/intent, any change to fetch/cache/render/handler behavior, any
change to the briefing spine.
</domain>

<decisions>
## Implementation Decisions

### Dispatcher shape — two-layer, unify all surfaces (Areas 1 + 2)
- **D-01:** Adopt **two layers** so the genuinely-duplicated arg-adaptation
  ladder exists exactly **once** in the whole codebase (criterion #3), while the
  legitimately-different fetch/retry code per surface stays where it is:
  - **Inner (the single ladder, SYNC):** `dispatch_reply(spec, *, result, config, flags, daemon_state) -> CommandReply`.
    This is the if/elif "who-needs-what" ladder and nothing else — it receives an
    already-fetched `LookupResult` (`result`, `None` for argless specs), the
    parsed `ForecastFlags` (`flags`, `None` for non-forecast), the `Config`, and
    the read-only `DaemonState`, and returns the `CommandReply` the handler
    produces. No fetch, no render, no I/O.
  - **Outer (async convenience wrapper):** `dispatch_spec(...)` for the async
    surfaces (`on_message` now, panel in Phase 17) = off-loop fetch
    (`run_in_executor(cache.lookup, …)`, with the forecast cache-key `suffix`)
    **then** call `dispatch_reply`. Returns `CommandReply`. This is the function
    the v1.3 research/roadmap named; it owns "runs the off-loop fetch" while the
    shared ladder lives in `dispatch_reply`.
- **D-02:** **The CLI is unified too.** `cli.py:_run_registry_command` keeps its
  own `lookup_weather` + tenacity retry + exit-code (1/3) + `UnknownLocationError`
  → stderr + dual error-message wrapper, and only its if/elif block is replaced
  by a `dispatch_reply(...)` call. The CLI must NOT call the async `dispatch_spec`
  (different fetch path, no event loop). This preserves the CLI's exact behavior
  while removing the second parallel ladder.
- **D-03 (rejected — Option A):** "Fix only the Discord side, leave the CLI
  ladder" was rejected — it leaves a second identical ladder in `cli.py`, exactly
  the drift criterion #3 forbids.
- **D-04 (rejected — Option C):** "One big sync fetch-owning function shared by
  all (fetch injected)" was rejected — folding the handler call into the CLI's
  retried fetch scope would blur the CLI's 3× retry boundary and merge its two
  distinct error messages, risking CLI behavior.

### Rendering & error handling stay at the call site (Area 2, locked not asked)
- **D-05:** `dispatch_reply`/`dispatch_spec` return a `CommandReply`. Rendering
  stays surface-specific at the call site: `render_embed` (bot) / `render_text`
  (CLI) — the existing surface-agnostic `CommandReply` seam, unchanged.
- **D-06:** Surface-specific error handling stays at the call site too: the bot's
  non-propagating try/except → generic embed reply + `UnknownLocationError` →
  `channel.send(str(exc))`; the CLI's `UnknownLocationError` → stderr/exit 1,
  fetch failure → exit 3, handler failure → exit 3 with its own message. The
  shared code does NOT catch or translate these.

### Drift-proofing the binding — centralized if/elif (Area 3)
- **D-07:** Keep the binding as an **if/elif ladder in one place**
  (`dispatch_reply`). Behavior-preserving and minimal. Branches mirror today's:
  forecast (`spec.group == "Forecast"`) → `handler(result, flags)`;
  `next-cloudy` → `handler(result, config.cloud_threshold)`; `uv` →
  `handler(result, config.uv.threshold)`; other `takes_location` →
  `handler(result)`; `status` → `handler(daemon_state)`; `locations` →
  `handler(config)`; `help` → `handler()`. A new command of an existing shape
  needs zero edits (catch-all); a genuinely new arg-shape needs a one-line edit
  in this single ladder.
- **D-08 (deferred refinement):** Fully-declarative binding (each `CommandSpec`
  carries its own arg-binding callable so the ladder disappears entirely) was
  considered and deferred — it redefines `CommandSpec` and moves dispatch logic
  into the registry, which is more than this behavior-preserving phase needs.
  Revisit only if handler arg-shapes start multiplying.

### Module placement (Area 4)
- **D-09:** New module `weatherbot/interactive/dispatch.py` holds both
  `dispatch_reply` (sync) and `dispatch_spec` (async). Keeps `registry.py` and
  `command.py` lean and avoids an import cycle (`command.py` already imports
  `registry`; `dispatch.py` may import both `registry` and `command` for
  `parse_forecast_flags`/`forecast_cache_suffix` — acyclic, since nothing imports
  `dispatch`). `LookupResult`/`ForecastCache`/`Config`/`DaemonState` types come in
  under `TYPE_CHECKING` to keep module-top imports light.

### Claude's Discretion
- Exact parameter names/ordering, keyword-only vs positional, and whether
  `dispatch_spec` takes `cache` + `loop` directly or a small fetch closure —
  planner/executor's call, as long as D-01/D-02 layering holds.
- Whether the forecast-flags parse (`parse_forecast_flags`/`forecast_cache_suffix`)
  happens inside `dispatch_spec` (recommended, since both async callers need it)
  or is threaded in by the caller — keep it DRY across bot + panel.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The two call sites being unified (the actual refactor targets)
- `weatherbot/interactive/bot.py` §`build_on_message` (lines ~246-339) — the
  async ladder + off-loop `cache.lookup` + typing + embed + non-propagating
  envelope. Lines ~313-329 are the ladder to extract; `render_embed` (lines
  ~123-190) stays.
- `weatherbot/cli.py` §`_run_registry_command` (lines ~556-640) — the identical
  sync ladder (lines ~618-632) to replace with a `dispatch_reply` call; its
  retry/exit-code/`UnknownLocationError` wrapper and `render_text` (lines
  ~540-553) stay. Also `_cli_daemon_state` (lines ~643-675) for the CLI `status`.

### The shared pieces the dispatcher leans on
- `weatherbot/interactive/registry.py` — `CommandSpec` (name/group/summary/
  takes_location/handler), `COMMANDS`, `BY_NAME`. The single source of truth the
  dispatcher resolves against.
- `weatherbot/interactive/command.py` — `parse_command` → `ParsedCommand(spec, arg)`,
  `parse_forecast_flags` → `ForecastFlags`, `forecast_cache_suffix`. The shared
  arg/flag grammar the dispatcher threads.
- `weatherbot/interactive/cache.py` — `ForecastCache.lookup(name, config, suffix)`
  (always off-loop; bubbles `UnknownLocationError` un-cached). The bot/panel fetch.
- `weatherbot/interactive/lookup.py` — `lookup_weather` (sync core) +
  `UnknownLocationError`; the CLI fetch and the cache's underlying fetch.
- `weatherbot/interactive/commands/` + `CommandReply` — the heterogeneous handler
  signatures and the surface-agnostic reply object returned.
- `weatherbot/interactive/state.py` — read-only `DaemonState` (what `status` reads).

### Contractual test gate (criterion #2 — must stay green, byte-identical)
- `tests/test_bot.py`, `tests/test_cli.py`, `tests/test_registry.py`,
  `tests/test_command.py`, `tests/test_command_views.py` — the anti-drift /
  registry / per-surface tests that prove replies are unchanged after the refactor.

### Milestone-level decisions & rationale
- `.planning/research/ARCHITECTURE.md` §"Pattern 2" + lines ~100-105 — proposes
  the `dispatch_spec` extraction as the single most important anti-drift move
  (originated the async signature this phase refines into D-01).
- `.planning/research/SUMMARY.md` lines ~78-82 — Phase 1 (this phase) rationale:
  refactor-first, behavior-preserving, locked by existing tests.
- `.planning/research/PITFALLS.md` — failure-isolation note: panel/interaction
  callbacks do NOT flow through `on_message`'s try/except (relevant to Phase 20,
  noted so this phase's seam doesn't assume the bot envelope covers panel taps).
- `.planning/REQUIREMENTS.md` — PANEL-10 (the one requirement this phase satisfies).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ForecastCache.lookup(name, config, suffix)` — the off-loop, TTL, per-location
  fetch the async `dispatch_spec` wraps via `run_in_executor`. The forecast
  `suffix` (from `forecast_cache_suffix`) widens the cache key so a forecast
  result never collides with a plain weather result.
- `parse_command` / `parse_forecast_flags` / `forecast_cache_suffix` — the shared
  parse + flag grammar both async callers reuse; `dispatch_spec` should own the
  forecast-flags parse so bot + panel stay DRY.
- `CommandReply` + `render_embed` (bot) + `render_text` (CLI) — the existing
  surface-agnostic reply→render seam; the dispatcher returns `CommandReply`, the
  call site renders. Do not move rendering into the shared code.

### Established Patterns
- **Acyclic lazy imports (Pitfall 5):** `registry.py` lazy-wires handlers;
  `command.py` imports `registry`; `lookup.py`/`daemon.py` lazy-import to dodge
  cycles. New `dispatch.py` follows suit — `TYPE_CHECKING` for heavy types,
  import `command`/`registry` at module top (acyclic since nothing imports
  `dispatch`).
- **Failure isolation:** the bot's whole reply path is inside one
  non-propagating try/except (`bot.py:270-337`); the extraction must keep the
  entire `dispatch_spec` call INSIDE that existing envelope — no second envelope,
  nothing re-raised into the scheduler thread (criterion #4 / CMD-16).
- **Read-only discipline:** the dispatcher only ever drives the registry handler +
  `ForecastCache` + read-only `DaemonState`/`holder.current()`; it writes nothing
  to the store, sent-log, or scheduler (criterion #4).
- **The `status` daemon-state difference:** bot passes the live injected
  `DaemonState`; CLI builds a scoped one via `_cli_daemon_state(config)`. The
  shared `dispatch_reply` takes `daemon_state` as a parameter so each surface
  supplies its own — no special-casing inside the ladder.

### Integration Points
- `on_message` (`bot.py`) — replace lines ~270-330's inline fetch+ladder with an
  `await dispatch_spec(...)` call inside the existing typing/try-except; keep the
  `UnknownLocationError` → `channel.send` and the final `render_embed` + send.
- `_run_registry_command` (`cli.py`) — replace lines ~618-632's if/elif with a
  `dispatch_reply(...)` call inside the existing handler try/except; keep the
  fetch/retry, exit codes, and `render_text`.
- Phase 17's `PanelView` will be the third caller of `dispatch_spec` — design the
  signature so a panel callback (custom_id → spec, selected location → arg) drops
  in with no new dispatch logic.
</code_context>

<specifics>
## Specific Ideas

- The user asked for plain-language framing of the design options mid-discussion;
  the locked choice (two-layer, unify all) was confirmed against a non-jargon
  explanation — downstream agents should keep the "one shared ladder, each
  surface keeps its own fetch/retry" mental model intact and not collapse the two
  layers into one fetch-owning function (that was explicitly rejected as Option C).
</specifics>

<deferred>
## Deferred Ideas

- **Fully-declarative arg-binding on `CommandSpec`** (each spec carries its own
  bind callable; the if/elif ladder disappears entirely). Considered for
  drift-proofing; deferred because it redefines `CommandSpec` and exceeds this
  behavior-preserving phase. Revisit if handler arg-shapes proliferate.
- All panel UI/behavior (dropdown, buttons, defer-then-edit, persistence,
  forecast sub-options, isolation re-proof, polish) — Phases 17-20.

</deferred>

---

*Phase: 16-extract-shared-dispatch-spec*
*Context gathered: 2026-06-23*
