# Phase 22: Channel + Delivery-Reliability Seam (+ in-place boundary) - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up the **clean in-place module boundary** — a real package, named now so the Phase-28
physical split is a pure `git mv` (not a rename) — and extract the **lowest-risk seam first**
into it: the channel-agnostic `Channel` abstraction + the delivery-reliability primitives,
with **zero weather coupling**. Also stand up the cross-cutting **import-hygiene gate**
(one-way dependency: the module imports zero app code) + the **litmus grep** (no weather noun
in the module's public surface) — wired as tests that fail loud and documented as standing
success criteria that every later seam phase (23–27) re-runs.

**HOW is what we clarified here. The WHAT is LOCKED by the roadmap + REQUIREMENTS (SEAM-01,
PKG-01) — and behavior must stay byte-identical** (the ~649-test suite + the Phase-21 golden
snapshots are the oracle; any non-empty snapshot diff is a failure to investigate, never
rubber-stamped). New capabilities (durable JobStore, new channels, weather analysis) stay
deferred and belong in other milestones.

**Governing acceptance lens (every seam):** *"could a hypothetical reminder bot reuse this
with zero weather assumptions?"*

</domain>

<decisions>
## Implementation Decisions

### In-place module boundary (name & layout)
- **D-01:** **Flat sibling top-level package** — create `yahir_reusable_bot/` at the repo root,
  a sibling to the existing `weatherbot/` package, with the **final import root
  (`yahir_reusable_bot`) in place from day one**. This is the only layout that makes Phase 28
  a literal `git mv yahir_reusable_bot/ …` with **provably zero import churn** (every
  `from yahir_reusable_bot…` is already correct) and leaves `templates/`, `tests/`, the
  `pythonpath=["."]` test config, and the Phase-21 coverage `source` paths byte-undisturbed —
  the dominant risk on a characterization-locked suite.
- **D-02:** Because a second top-level package whose name differs from the `weatherbot` project
  defeats hatchling auto-discovery, PKG-01 **must add an explicit build config** —
  `[tool.hatch.build.targets.wheel] packages = ["weatherbot", "yahir_reusable_bot"]` (verify
  the exact backend in `pyproject.toml` during planning). Forgetting this would silently drop
  the new package from the wheel; the Phase-28 `uv build --no-sources` leak gate is the eventual
  backstop, but the build config goes in now.
- **Rejected:** nested `weatherbot/_reusable/` (forces the rename the whole strategy exists to
  avoid); **src-layout** migration (full-repo move touching every tooling path for an
  isolation benefit irrelevant to an already-passing personal app); **uv workspace member**
  (heavier 2nd-`pyproject.toml` + workspace re-resolve + `uv.lock` churn — only worth it if the
  repo grows a *second* in-repo consumer before the split, which it won't this milestone).

### Channel seam placement (un-braiding the weather coupling)
- **D-03:** **Move a clean, text-only `Channel` abstraction + `DeliveryResult` into the module;
  drop `send_briefing` from the abstract contract; keep the concrete `DiscordWebhookChannel`
  (and its weather embed-building) app-side until its dedicated Phase 27.** The module's
  `Channel` becomes exactly `send(text: str) -> DeliveryResult` — the canonical text path SMS/
  Telegram reuse — and the **`TYPE_CHECKING` import of `Forecast` (the one real coupling) is
  deleted** from the abstraction.
- **D-04:** Phase 27 ("Discord Adapter + PanelKit + Render-Cycle Fix") is the *named* home for
  relocating the Discord transport; `interactive/bot.py:render_embed` already mirrors the embed
  field-for-field and is destined to consolidate there. Moving the embed app-side now and again
  in 27 would be wasted churn that risks the goldens twice — so it stays put this phase.
- **D-05 (hand-off obligation):** Document the **temporary two-home split** (clean `Channel`
  abstraction in the module; concrete `DiscordWebhookChannel` still app-side) as an explicit
  Phase-27 hand-off, so it is not misread as an incomplete extraction.
- **Rejected:** moving the Discord embed app-side *now* (pulls Phase-27 work forward against the
  stated risk ordering); a generalized `send_rich(text, payload: object)` (an `object`/`Any`
  escape hatch that only *renames* the coupling); a dual `Channel`/`BriefingChannel` Protocol
  pair (the ABC→Protocol shift breaks the existing `isinstance(ch, Channel)` tests; over-built
  for a single-channel v1).

### Reliability seam scope
- **D-06:** **Move the generic retry primitives into the module** — `build_retrying`, the
  `is_transient`/`is_auth_failure` classifiers, `parse_retry_after` (capped, honors
  `Retry-After`, never retries 401/403/permanent), and the `REASON_*` taxonomy. These are
  already weather-clean tenacity composition and move with low risk.
- **D-07:** **Define an `AlertSink` port (Protocol/callable) in the module now**; the
  weather-coupled implementation (`record_alert` / `resolve_alert` / `briefing_missed` →
  weather SQLite store) **stays app-side as the adapter**, wired behind the port. This is the
  textbook Ports & Adapters move and keeps `fire_slot` *adapted, not rewritten* (byte-identical
  safe). Out-of-band alert is genuinely Phase 22's delivery-lane concern.
- **D-08:** **Heartbeat is explicitly OUT of scope for Phase 22.** `_heartbeat_tick` is not a
  delivery concern — it stamps liveness independent of any send and is registered as an
  APScheduler `__heartbeat__` job in daemon lifecycle, which the roadmap assigns to **Phase 25**
  (Lifecycle READY-gate + composition root + systemd `Type=notify` heartbeat). Defining a
  heartbeat hook now would be a speculative interface with no consumer until 25 (the same YAGNI
  the milestone already invokes for the deferred durable JobStore) — and would risk guessing the
  hook signature before its real lifecycle caller exists.
- **Rejected:** retry-primitives-only with alert also deferred (alert is Phase-22-natural
  delivery work — don't push it later); defining the heartbeat port now (speculative); a full
  generic `DeliveryGuard` wrapper that refactors `fire_slot` (its retry is 3 lines inside
  irreducibly weather-coupled orchestration — high golden/test-break risk).

### Import-hygiene gate (mechanism)
- **D-09:** **Enforce the one-way dependency with `grimp` called in-process from a pytest test**
  — build the import graph and `assert` no module edge points at an app package (a prefix check
  like "no edge starts with the app namespace" auto-scales as the module grows across phases
  23–27). No CI exists here (the pytest suite *is* the regression guard), so a native pytest
  assert fits better than shelling a CLI; it costs one dependency (not two), gives direct
  control over the **TYPE_CHECKING question** (today's channel files import `Forecast`/`Config`/
  `Settings` under `TYPE_CHECKING`), and the `grimp` dep travels cleanly into the future
  `yahir_reusable_bot` repo.
- **D-10:** **Pair the graph check with the isolated-import smoke test** (import the module
  subpackage with app packages absent/blocked) — PKG-01 asks for *both* an import-lint contract
  AND a core-in-isolation test; the smoke test alone under-enforces (misses TYPE_CHECKING-only
  and lazy/function-local app imports).
- **Rejected:** `import-linter` (declarative, reads as architecture docs, but counts
  TYPE_CHECKING imports by default → today's `Forecast` guards would flag; adds 2 deps +
  exit-code parsing — a fine close runner-up if a declarative contract is later preferred);
  hand-rolled stdlib `ast` walk (re-implements a solved import-resolution problem; its failure
  mode is a *silent false-negative* — the worst outcome for a guard).

### Litmus-grep gate (scope & incidental-hit handling)
- **D-11:** **Signature/identifier-only scope** — the litmus check runs over the module's
  **public surface** (AST-extracted `def`/`class`/parameter/annotation names), NOT docstrings or
  comments. A leak that matters is a weather noun in a *name*, not in prose. Whole-text grep
  would flag ~19 incidental docstring mentions (e.g. `reliability/retry.py` says "OpenWeather",
  "Discord", "briefing") and force needless churn or an allowlist.
- **D-12:** The one **real** signature hit that exists today —
  `def send_briefing(self, text, forecast: Forecast) -> DeliveryResult` — is exactly what the
  gate should surface, and it is **resolved by D-03** (dropping `send_briefing` from the module
  abstraction + deleting the `Forecast` import), which simultaneously removes the cross-package
  `Forecast` type edge that the D-09 import gate flags. The two gates and the channel-seam
  decision reinforce each other.
- **D-13:** The gate is **documented as a standing success criterion** that phases 23–27 re-run
  (and it is re-verified across the package boundary at Phase 28). The litmus pattern is the
  roadmap's `weather|forecast|location|openweather|\buv\b|briefing` (over the public surface).
- **Rejected:** whole-text + allowlist file (upkeep + drift; can rubber-stamp a real leak);
  whole-text + scrub-all-docstrings (high churn + a forced signature rename for cosmetic
  compliance — defer any full docstring scrub to the actual repo-extraction milestone, Phase 28
  / DOCS-01).

### Claude's Discretion
- Exact module sub-layout *inside* `yahir_reusable_bot/` (e.g. `channels/`, `reliability/` vs a
  flatter shape) and file naming — planner/executor, guided by the existing package shapes.
- The precise `AlertSink` Protocol method signature(s) — keep minimal and weather-clean; shaped
  by what `fire_slot`'s existing `record_alert`/`resolve_alert` calls actually need.
- The exact `grimp`-graph assertion form (allowlist of genuinely-needed edges, how
  TYPE_CHECKING edges are included/excluded) and the isolated-import smoke-test harness shape.
- How "public surface" is extracted for the litmus check (AST module walk vs disciplined
  def/class-line scan) — as long as it ignores prose and catches names.
- Confirm the actual build backend in `pyproject.toml` before writing the `packages = [...]`
  block (D-02 assumes hatchling; verify).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & milestone contract
- `.planning/ROADMAP.md` § "Phase 22: Channel + Delivery-Reliability Seam (+ in-place
  boundary)" — the 4 locked success criteria (Channel + reliability in the boundary with
  byte-identical delivery; module imports zero app code; litmus grep clean; gate wired as a
  test + documented as standing criterion for 23–27).
- `.planning/ROADMAP.md` § "v2.0 Bot Module Extraction" milestone header + the **phase spine**
  paragraph (leaf-seams-first, split-last; Phase 27 = Discord adapter home; Phase 28 = physical
  split). Establishes why Discord transport defers to 27 (D-04) and heartbeat to 25 (D-08).
- `.planning/REQUIREMENTS.md` § **SEAM-01** (channel + reliability, zero weather coupling) and
  § **PKG-01** (clean in-place boundary, one-way dependency, import-lint/grep gate). Also the
  **Cross-cutting acceptances** note: PKG-01 anchored here + enforced on 23–27; APP-02 litmus
  grep applied as a standing gate on every seam phase; BHV-01/BHV-02 re-run every phase.

### Prior-phase contract this phase must honor
- `.planning/phases/21-characterization-golden-test-harness/21-CONTEXT.md` — the golden oracle
  this phase re-runs: syrupy `JSONSnapshotExtension` (order-preserving) for structured payloads
  + `SingleFileSnapshotExtension` for `custom_id`/CLI bytes (D-01/D-02 there), the
  `# pragma: no cover - <reason>` convention (D-09 there), and the **discipline rule** that any
  non-empty snapshot diff during an extraction phase is a failure to investigate (D-04 there).
- `.planning/phases/21-characterization-golden-test-harness/21-PATTERNS.md` — pattern map for
  the move-path packages (present in the working tree).

### Source surfaces this phase moves / touches
- `weatherbot/channels/base.py` — the `Channel` ABC + `DeliveryResult`; the load-bearing
  `TYPE_CHECKING` `Forecast` import (lines ~19–20) and the `send_briefing(text, forecast)`
  abstract method (~lines 52–61) that D-03 removes from the module abstraction.
- `weatherbot/channels/discord.py` — concrete `DiscordWebhookChannel.send_briefing` + embed
  build (~lines 54–70); stays app-side this phase (D-04).
- `weatherbot/channels/factory.py`, `weatherbot/channels/__init__.py` — the `build_channel`
  registry + re-exports; the public `channels` surface to keep stable.
- `weatherbot/reliability/retry.py` + `weatherbot/reliability/__init__.py` — the retry
  primitives that move (D-06) and the public re-export surface.
- `weatherbot/scheduler/daemon.py` — `fire_slot` (the retry-then-alert orchestration that
  consumes `build_retrying` + `record_alert`/`resolve_alert`; adapted, not rewritten, behind the
  D-07 `AlertSink` port) and `_heartbeat_tick` (out of scope, D-08).
- `weatherbot/cli.py` — the composition-root dispatch that calls `channel.send_briefing(...)`;
  keeps targeting the concrete app-side Discord channel (explicit, not duck-typed).
- `pyproject.toml` — the build-backend + `[tool.hatch.build.targets.wheel] packages` block
  (D-02); the `[tool.coverage.*]` source paths (Phase-21) that must keep covering the moved
  code; dev-dep group (add `grimp`, D-09).

### Tooling docs (for the planner)
- grimp `ImportGraph` API — https://grimp.readthedocs.io/en/stable/usage.html
- import-linter (the rejected-but-runner-up declarative option; TYPE_CHECKING default behavior)
  — https://import-linter.readthedocs.io/en/stable/usage.html and issue #198 on
  type-checking imports.
- uv project layout / `tool.uv.sources` git dependency + editable path override (Phase-28
  forward-context) — https://docs.astral.sh/uv/concepts/projects/dependencies/
- src-vs-flat layout (why flat is fine here) —
  https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weatherbot/channels/base.py`: the `Channel` ABC is *already* almost the clean seam — its
  `send(text) -> DeliveryResult` is the channel-agnostic path; only `send_briefing` + the
  `Forecast` import need to leave the abstraction (D-03).
- `weatherbot/reliability/retry.py`: `build_retrying` + classifiers + `parse_retry_after` +
  `REASON_*` are already generic tenacity composition with no weather *signatures* — a
  low-friction move (D-06). Docstrings mention weather nouns but those are incidental prose
  the signature-only litmus (D-11) ignores.
- `weatherbot/reliability/__init__.py` + `weatherbot/channels/__init__.py`: existing public
  re-export surfaces — keep the import paths other code (e.g. `daemon.py`) catches/consumes
  through, so the Phase-21 exception-identity pins stay green.
- The Phase-21 golden suite + ~649 tests: the standing byte-identical oracle re-run to prove
  this move changed no observable byte.

### Established Patterns
- **Ports & Adapters / dependency injection** is the milestone's recurring un-braiding move
  (injected `validate`/`desired_jobs`, `SelectedContext`, health-check, etc.) — the D-07
  `AlertSink` port is the first instance of it in the extraction.
- **Design-the-seam-now, build/wire-the-impl-later** (durable JobStore is the canonical example)
  — applied here to keep heartbeat out (D-08) and to keep the alert impl app-side (D-07).
- The 6 move-path packages (`channels`, `scheduler`, `config`, `reliability`, `ops`,
  `interactive`) from Phase 21 are exactly what move across 22–27; `channels` + `reliability`
  are this phase's two.

### Integration Points
- The new `yahir_reusable_bot/` package is the import target; `weatherbot` code re-points its
  imports of `Channel`/`DeliveryResult` + the retry primitives to it (one-way dependency —
  app → module, never module → app).
- `fire_slot` in `daemon.py` is the integration seam for the `AlertSink` port: it keeps its
  current behavior, calling alert through the injected port instead of importing the weather
  alert store directly inside the module.
- The import-hygiene + litmus gate (D-09..D-13) are new pytest tests + a `grimp` dev dep + the
  `pyproject.toml` build/packaging changes — additive test/config, no production behavior change
  beyond the relocation.

</code_context>

<specifics>
## Specific Ideas

- The single most important cross-area insight: **`send_briefing(text, forecast: Forecast)` is
  both the channel-seam crux (area 2) and the one real signature leak the litmus gate (area 4)
  would catch** — D-03 resolves both at once (drop it from the abstraction + delete the
  `Forecast` import), which also clears the cross-package type edge the D-09 import gate flags.
  Three gates, one fix.
- Name the package its **final** name (`yahir_reusable_bot`) NOW so Phase 28 is `git mv`, not a
  rename — this is the load-bearing reason flat-sibling beats nested.
- Heartbeat is *not* delivery — resist the roadmap-goal phrasing's pull to pull it in; it lands
  in Phase 25 with its real systemd `Type=notify` + APScheduler-job caller.
- The litmus check is meaning-bearing, not prose-policing: signatures only, so working
  docstrings aren't churned for cosmetic compliance.

</specifics>

<deferred>
## Deferred Ideas

- **Relocate the concrete `DiscordWebhookChannel` transport (+ embed build) into the module** —
  belongs to **Phase 27** (Discord Adapter + PanelKit + Render-Cycle Fix), its named home.
  Tracked as the D-05 hand-off obligation.
- **Heartbeat hook / port in the module** — belongs to **Phase 25** (Lifecycle READY-gate +
  composition root + systemd `Type=notify` heartbeat). Out of scope here per D-08.
- **Full docstring/comment scrub of weather nouns from the module** — cosmetic; defer to the
  actual repo extraction (**Phase 28** / DOCS-01) where domain-neutral prose matters for a
  standalone repo. Rejected as in-scope churn per D-13.
- **Switch the import gate to declarative `import-linter`** — viable runner-up if a
  contract-as-documentation style is later preferred over the grimp-in-pytest assert (D-09).
- **uv workspace / multi-package arrangement** — only if the repo grows a second in-repo bot
  consumer before the split; not this milestone (D-01 rejected list).

None of these are scope creep — they are alternatives within the extraction domain that were
consciously placed in their correct later phase.

</deferred>

---

*Phase: 22-channel-delivery-reliability-seam-in-place-boundary*
*Context gathered: 2026-06-27*
