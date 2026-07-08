# Phase 21: Characterization / Golden-Test Harness - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Pin every observable byte of WeatherBot's **current** behavior as golden/characterization
snapshots **before any code moves**, so "byte-identical" through the v2.0 extraction is
*provable* — not merely "628 tests still green." The harness captures, against a frozen
forecast + frozen clock:

- Full rendered Discord embeds — per command (weather / uv / next-cloudy / sun / wind /
  status / alerts / forecast variants) × 📍 selected-location indicator on/off × `Updated <t:…>`
  stamp present/absent
- CLI stdout + exit code per subcommand and per forecast variant (weekday/weekend ×
  detailed/compact)
- The registered-job **schedule plan** `(job_id, trigger spec, next_run_time)`
- The DB rows a briefing writes (`weather_onecall` / `alerts` / sent-log)
- The exact panel `custom_id` byte strings (incl. the `wb:` marker)
- An exception-identity pin for the move-path error types
- A coverage audit over the modules slated to move (any uncovered branch on a move path is
  filled with a characterization test first)

This golden suite becomes the **standing byte-identical oracle** re-run after every later
seam extraction (Phases 22–27) and again after the physical split (Phase 28).

**HOW is what we clarified here. The WHAT-to-capture list is LOCKED by the roadmap success
criteria — new capabilities belong in other phases.** No source behavior changes in this
phase: it is purely additive test infrastructure.

</domain>

<decisions>
## Implementation Decisions

### Snapshot storage & comparison
- **D-01:** Use **syrupy** as the workhorse snapshot library. It's effectively zero-weight —
  its only dependency is `pytest` (already pinned at 9.0.3); adding it is one line in the dev
  dependency group, not a transitive tree.
- **D-02:** Serializer choice by payload type, chosen for byte-order fidelity:
  - `JSONSnapshotExtension` (order-preserving `.json`) for **structured** payloads — embed
    dicts, the schedule plan, DB rows — so a **field reorder** during a code move surfaces as
    a real diff.
  - `SingleFileSnapshotExtension` (raw bytes) for the **`custom_id` strings and CLI stdout**,
    where a single byte flip must fail.
- **D-03:** Keep a **small number of inline literal pins** (extend the existing
  `test_weather_spec_byte_identical` pattern in `tests/test_panel.py`) for tiny,
  self-documenting assertions where a literal reads better than a snapshot file — e.g. a lone
  `custom_id` byte string, a CLI exit code.
- **D-04:** Goldens are **committed** under `tests/__snapshots__/` (clean PR line-diffs).
  Regeneration is a deliberate, auditable `--snapshot-update` gesture. **Discipline rule:**
  during an extraction phase (22–28) output is *supposed* to be byte-identical, so **any
  non-empty snapshot diff is a failure to investigate, never a rubber-stamp** — only run
  `--snapshot-update` when an intentional change is genuinely in scope.
- **Rejected:** `inline-snapshot` (pre-1.0, churny, pulls 4–5 transitive deps, rewrites test
  source on update — poor fit for an oracle that must stay stable across a whole milestone);
  a fully hand-rolled `tests/golden/` pattern (zero dep but re-implements the
  overwrite-safety + regen ergonomics syrupy already ships).

### Coverage audit (move-path de-risk)
- **D-05:** Add **`pytest-cov`** (wraps the same coverage.py core; runs inside the existing
  `pytest` invocation). **Not** raw coverage.py out-of-band.
- **D-06:** **Branch mode is mandatory** (`[tool.coverage.run] branch = true`). Line coverage
  would call an `if`/`except` "covered" after exercising only the *taken* side, but extraction
  risk lives in the *untaken* side — an unexercised `except`/`else` that behaves differently
  in the new package is exactly what the goldens (observable-output only) cannot see.
- **D-07:** Scope to the **move-path packages only** via
  `source = ["weatherbot/channels", "weatherbot/scheduler", "weatherbot/config",
  "weatherbot/reliability", "weatherbot/ops", "weatherbot/interactive"]`. The weather-content
  modules (`weatherbot/weather`, templates, branding) stay app-side and are **not** in scope.
- **D-08:** This is a **ONE-TIME Phase-21 audit**, not a standing `fail_under` gate: run once
  with `--cov-report=term-missing`, fill every reported uncovered move-path branch with a
  characterization test, record the clean audit in the phase log, move on. No CI exists to
  enforce a standing gate, and the 628-test suite + goldens already re-run every phase as the
  real regression guard. (Standing `fail_under=100` was considered and rejected — it trades
  real per-phase friction for marginal protection over what the goldens already cover.)
- **D-09:** Carry forward the codebase's existing **`# pragma: no cover - <reason>`**
  convention — a pragma must name *why* the branch is unreachable, never just to make the
  number green. Use `[tool.coverage.report] exclude_also` / `partial_also` for systematic
  defensive patterns so exclusions live in version-controlled config.

### Golden granularity & determinism
- **D-10:** **Granularity = representative-subset, parametrized one-per-cell.** Each command
  gets its own named case; each Phase-20 state is covered at least once (📍-on via a
  location-bearing reply, 📍-off via the argless status reply); each forecast variant
  (weekday/weekend × detailed/compact) once. A failure diff then names the **exact cell**
  without a cartesian explosion. The 📍 and `Updated` lines are *additive* lines orthogonal to
  the embed body, so cross-multiplying them buys ~zero coverage. (Coarse per-surface and full
  cartesian both rejected.)
- **D-11:** **Determinism = freeze what derives from "now," scrub only what doesn't.**
  - **Freeze** (via `time-machine`, already a dep, the suite's established pattern): the
    `Updated <t:{epoch}…>` stamp **and** APScheduler `next_run_time` → deterministic literal
    constants. **Crucially keep the format string itself in the golden** (`<t:…:t> (<t:…:R>)`)
    so a `:R`-dropped or line-reordered regression still fails — a blanket epoch-scrub would
    silently swallow it (the over-scrubbing trap).
  - **Scrub** strictly for what freezing can't stabilize: SQLite autoincrement **rowids**
    (ignore/normalize), non-clock `created_at` fields.
  - Kill query-order nondeterminism with an explicit **`ORDER BY` in the read path**, not a
    sort-scrub, so ordering drift stays visible.
  - Note: `embed.timestamp = utcnow()` is already excluded from the byte contract per the
    existing `test_weather_spec_byte_identical` docstring; freezing simply makes it a stable
    constant if included.

### Oracle self-proof & exception-identity pin
- **D-12:** **Oracle self-proof (SC2) = an inline meta-test** that deliberately perturbs a
  rendered embed (a **field reorder** + a **`custom_id` byte-flip**) and wraps the golden
  comparison in **`pytest.raises(AssertionError)`**. This ships as a standing test that proves
  the oracle's *teeth*, reads as living documentation of "what drift looks like," and will
  itself fail if the comparison is ever loosened (e.g. an order-insensitive compare). Rejected:
  `xfail(strict=True)` (functionally equal but reads inverted, easy to misread/"fix" away);
  mutation testing (out-of-band, fails the "ship as a test this phase" bar).
- **D-13:** **Exception-identity pin (SC3) = two asserts per move-path error type:**
  1. **`is`-identity through the caller's import path** —
     `from weatherbot.reliability import SomeError; assert excinfo.type is SomeError` —
     the tightest guard a later *broadened* `except` cannot swallow.
  2. **Frozen `(__module__, __qualname__)` tuple assert** — turns the fully-qualified name
     into the literal under test, so a re-home/rename fails with a crisp old-vs-new diff that
     names exactly what changed.
  **Explicitly avoid `isinstance` as the pin** — it permits the very `except`-broadening this
  guards against. (A thin behavioral "does the real `except` still catch a raised instance"
  test is acceptable as an optional end-to-end backstop, not the primary pin.)

### Claude's Discretion
- Exact file/case naming for goldens and the `tests/__snapshots__/` layout (planner/executor).
- Which specific exception types are "move-path" (enumerate during planning from the
  reliability / Discord-adapter / scheduler caught-error types).
- The precise frozen instant + timezone used for the freeze (reuse whatever the existing
  recorded-forecast fixtures assume).
- Whether the optional behavioral except-catch backstop (D-13) is worth including.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & milestone contract
- `.planning/ROADMAP.md` § "Phase 21: Characterization / Golden-Test Harness" — the 4 locked
  success criteria the harness must satisfy (full embeds, CLI, schedule plan, DB rows,
  `custom_id`s as byte-exact artifacts; trial-perturbation must FAIL; exception-identity pin;
  coverage audit with no uncovered move-path branch).
- `.planning/REQUIREMENTS.md` § BHV-01, BHV-02 — the byte-identical behavior-preservation
  contract this phase anchors; also the cross-cutting note that BHV-01/02 are re-run on
  Phases 22–28.

### Existing test infrastructure to build on
- `tests/conftest.py` — frozen-clock pattern, recorded-fixture loader (`_load_fixture` /
  `load_fixture`, `tests/fixtures/`), `fake_interaction` / `fake_discord_message` factories,
  `tmp_db`, `seed_sent_row`, `fake_pinned_message` / `fake_pins`. These are the gateway-free
  render/DB seams the goldens drive.
- `tests/test_panel.py` — existing `test_weather_spec_byte_identical` (the inline-literal
  byte-identical pattern to selectively keep per D-03; also its docstring on the
  `embed.timestamp` exclusion).

### Source surfaces being snapshotted (move-path packages)
- `weatherbot/interactive/bot.py` — `Updated <t:…>` stamp + embed render (the `📍`/`Updated`
  states).
- `weatherbot/interactive/state.py` — schedule-plan source (`next_run_time`).
- `weatherbot/interactive/panel.py` — panel `custom_id`s (incl. `wb:` marker).
- `weatherbot/interactive/registry.py`, `dispatch.py` — command surface driving CLI + Discord
  + `help`.
- `weatherbot/weather/store.py` — the DB rows a briefing writes.
- `weatherbot/reliability/retry.py` — caught error types for the exception-identity pin.
- `weatherbot/cli.py` — CLI stdout/exit per subcommand + forecast variant.

### Tooling docs (for the planner)
- syrupy — `JSONSnapshotExtension` (order-preserving) + `SingleFileSnapshotExtension` (raw
  bytes). https://syrupy-project.github.io/syrupy/
- coverage.py branch mode + `source`/`exclude_also`/`partial_also`.
  https://coverage.readthedocs.io/en/latest/branch.html
- pytest-cov config. https://pytest-cov.readthedocs.io/en/latest/config.html

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `time-machine>=2.16` (already a dev dep): the freeze mechanism for `Updated` epoch +
  `next_run_time` (D-11). Established suite pattern — no new tool.
- `tests/conftest.py` factories (`fake_interaction`, `fake_discord_message`, `tmp_db`,
  `seed_sent_row`): gateway-free seams to render embeds and exercise DB-writing paths without
  a live Discord/network.
- `tests/fixtures/` recorded OpenWeather JSON + `load_fixture`: the frozen-forecast input that
  makes embeds/CLI deterministic.
- `test_weather_spec_byte_identical` (`tests/test_panel.py`): the existing inline byte-pin
  pattern to keep for tiny cases (D-03).
- `# pragma: no cover - <reason>` is already an established convention across
  `tests/test_{registry,scheduler,cli,uv_monitor,reliability,command_views,bot}.py` (D-09).

### Established Patterns
- Frozen clock + recorded-forecast fixtures are how the suite already achieves determinism —
  the harness extends this, it doesn't invent a new approach.
- 628 existing tests already encode intent-level behavior; goldens add the *byte-level* layer
  intent tests miss.

### Integration Points
- Goldens are **purely additive** — new test files + `tests/__snapshots__/` + a `[tool.coverage.*]`
  block + two dev deps (`syrupy`, `pytest-cov`) in `pyproject.toml`. **No source/production
  code changes** in Phase 21.
- The 6 move-path packages (`channels`, `scheduler`, `config`, `reliability`, `ops`,
  `interactive`) are the coverage scope and the homes of every snapshotted surface — they are
  exactly what moves in Phases 22–27.

</code_context>

<specifics>
## Specific Ideas

- The harness must catch **field-ORDER changes**, not just value changes — hence
  order-preserving JSON serialization (D-02). This is the concrete failure mode the oracle
  exists to catch when code is re-homed.
- Over-scrubbing is an explicit anti-goal: the `Updated <t:…>` **format string stays in the
  golden** so a format regression is visible (D-11).
- Every later phase (22–28) re-runs this suite as the byte-identical oracle — so trustworthiness
  (zero flake) is as important as coverage. A flaky golden would destroy the oracle's value.

</specifics>

<deferred>
## Deferred Ideas

- **Standing `fail_under=100` branch gate** — considered for the coverage audit; deferred (no
  CI, and per-phase friction outweighs marginal benefit over the goldens). Could be revisited
  if a CI pipeline is ever added.
- **Mutation testing (mutmut / cosmic-ray)** scoped to render functions — a deeper drift-
  sensitivity proof; deferred as out-of-band (fails the "ship as a test this phase" bar). A
  future option if render logic grows complex.
- **Behavioral except-catch end-to-end backstop** — optional thin test alongside the
  exception-identity pin (D-13); left to planner/executor discretion.

None of these are scope creep into other phases — they are alternatives *within* this phase's
domain that were consciously declined.

</deferred>

---

*Phase: 21-characterization-golden-test-harness*
*Context gathered: 2026-06-27*
