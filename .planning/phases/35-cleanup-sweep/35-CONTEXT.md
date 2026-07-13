# Phase 35: Cleanup Sweep - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

> Captured in `--auto` mode: all gray areas auto-selected, each decision auto-set to the
> recommended default. See the decision log in DISCUSSION-LOG.md.

<domain>
## Phase Boundary

Final phase of the **v2.1 Hardening** milestone. Sweep the residue the audit surfaced but the
correctness phases (29–34) left behind — in the same files those phases already opened — so the
milestone closes with **no silent debt**.

**In scope (WeatherBot only):**
- **Dead / divergent code** removal or correction: the dead second copy of the `-m` guard
  (`ops/pidfile.py`, F46), the dead result-discarding `is_transient` call (`ops/selfcheck.py`,
  F92), the unreachable UTC-fallback branches masking an invariant (`weather/store.py`
  `_local_date_iso`, F65), the dead `verbose` param (`cli.py`, F76), the dead
  `gate_until_healthy`/`emit_online`/`_do_reload` production copies (`scheduler/daemon.py`, F16).
- **Inaccurate docs / docstrings** correction on passthrough/routing helpers (`lookup_forecast`
  F104, single-source alerts doc-mismatch F66, and peers).
- **Remaining low-severity latent/quality findings** (config defaults, boundary `>=`/`<=` nits,
  rounding/peak-max disagreements, observability counter inconsistencies, resource/state-leak
  nits) — each either **fixed** or **explicitly annotated as accepted-with-rationale**.
- **Ledger reconciliation:** every in-scope WB finding ends FIXED / ACCEPTED / DEFERRED.

**Out of scope:**
- The **17 hub findings** (`yahir_reusable_bot/…`, tracked as H01–H17 in
  `.planning/HUB-FINDINGS-HANDOFF.md`). Confirmed routed upstream; human-gated per ECOSYSTEM.md.
  This phase only *confirms* they are out.
- New user features, new dependencies, behavior changes to the briefing spine.
- Re-fixing correctness bugs already closed in Phases 29–34 (verify + mark, don't re-touch).

**Anchor invariant (must not regress):** "the morning briefing always goes out, exactly once."

</domain>

<decisions>
## Implementation Decisions

### Fix-vs-Accept rule (governs every low-severity finding)
- **D-01:** Default to **fix** — these findings sit in files Phases 29–34 already opened, so the
  marginal cost is low. **Accept-with-rationale** only when (a) the fix would change observable
  behavior and isn't worth a regression risk this late in a hardening milestone, or (b) the
  finding is genuinely cosmetic/latent-only with a concrete reason it's safe to leave. No finding
  is silently skipped — every one lands as FIXED, ACCEPTED (annotated), or DEFERRED (ledger).

### Accepted-finding annotation format ("no silent debt")
- **D-02:** An accepted finding gets an **inline in-code annotation at the site**:
  `# ACCEPTED (F##, v2.1): <one-line rationale>`. The same disposition is mirrored in the ledger
  (D-03). The annotation is the durable record a future reader hits when editing that line —
  satisfies Success Criterion 2's "explicit in-code annotation recording it as accepted."

### Ledger reconciliation (Success Criterion 3)
- **D-03:** Reconcile in `.planning/WHOLE-PROJECT-REVIEW.md` by tagging each **WB** finding with a
  final disposition — `FIXED@<phase>`, `ACCEPTED`, or `DEFERRED` (+ where). The review currently
  tracks **no per-finding status**, so this reconciliation record is *created* by this phase.
  Confirm the **17 hub findings (H01–H17)** are present in `HUB-FINDINGS-HANDOFF.md` and marked
  out-of-milestone. (Note for planner: the handoff header says "17 findings" but its severity line
  totals 18 — reconcile/annotate that discrepancy rather than silently trusting one number.)

### Scope reconciliation — findings possibly already fixed in 29–34
- **D-04:** Some LOW/CLEANUP findings likely got fixed incidentally by the correctness phases
  (e.g. F65 dead UTC fallback ↔ Phase 32 `_local_date_iso` unification; F92 dead `is_transient`
  ↔ Phase 29/30 selfcheck work; F81 panel interaction-race ↔ Phase 33). For each: **verify the
  current code state first, then mark `FIXED@<phase>` — do not re-open or re-touch** already-clean
  code. Only genuinely-still-open findings get edited.

### Dead-code + orphaned tests
- **D-05:** Remove dead **production** code *and* the tests that exist **only** to exercise it
  (e.g. F16's `gate_until_healthy`/`emit_online`/`_do_reload` are "exercised only by tests" —
  those tests assert nothing about the live path and would rot into a divergence trap). Keep any
  test that also covers a live path.

### Behavior-preservation guard
- **D-06:** Cleanup is **behavior-preserving by default** — dead-code removal and doc fixes must
  not change runtime behavior. Any low-severity fix that *does* alter observable behavior (a
  boundary `>=`/`<=` flip, a rounding change, a config-default change) must land with a
  **regression test** proving the new behavior and the untouched briefing invariant. Reuse the
  Phase-34 test-backfill patterns.

### Claude's Discretion
- Grouping of findings into plans (recommend: **by file/subsystem** so each plan rides one
  already-opened file — `daemon.py`, `store.py`, `uv*.py`, `cli.py`, `interactive/*`,
  `weather/models.py`, `config/*`) — planner's call.
- The exact per-finding fix-or-accept verdict for each of the ~48 WB LOW/CLEANUP findings — apply
  the D-01 rule; researcher/planner enumerate from the ledger.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Finding ledger (the phase input — read first)
- `.planning/WHOLE-PROJECT-REVIEW.md` — the whole-project audit. Phase 35 sweeps the **LOW**
  (§Low) and **CLEANUP** (§Cleanup) **WB**-scoped findings plus any residual dead-code/doc items.
  ~48 WB findings in scope. This file is also where the D-03 reconciliation dispositions are
  written back.
- `.planning/HUB-FINDINGS-HANDOFF.md` — the 17 hub findings (H01–H17), **out of scope**; confirm
  routed, do not act on them here.

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §HARD-CLEAN-01, §HARD-CLEAN-02 — the two requirements this phase
  satisfies (dead/divergent code & docs; low-severity resolve-or-accept, no silent debt).
- `.planning/ROADMAP.md` §"Phase 35: Cleanup Sweep" — goal + 3 success criteria.

### Cross-repo boundary (jurisdiction)
- `../Reusable/YahirReusableBot/ECOSYSTEM.md` — confirms hub findings are human-gated and belong
  upstream; the boundary this phase must not cross.

### Prior-phase review reports (per-finding context / what 29–34 already touched)
- `.planning/phases/29-startup-validation-honest-alerting/29-REVIEW.md`
- `.planning/phases/30-secret-hygiene/30-REVIEW.md`
- `.planning/phases/31-send-atomicity-exactly-once-persistence-robustness/31-REVIEW.md` (+ `31-REVIEW-FIX.md`)
- `.planning/phases/32-timezone-date-boundary-correctness/32-REVIEW.md`
- `.planning/phases/33-interactive-panel-robustness/33-REVIEW.md`
- `.planning/phases/34-test-gap-backfill/34-REVIEW.md`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase-34 regression-test patterns** — reuse for any behavior-changing low fix (D-06). See
  `.planning/phases/34-test-gap-backfill/34-PATTERNS.md` and the tests added there
  (retry-exhaustion, midnight catch-up, rename-safe id, store atomicity).
- **The already-open files** — Phases 29–34 have touched `scheduler/daemon.py`,
  `scheduler/catchup.py`, `scheduler/uvmonitor.py`, `scheduler/wiring.py`, `weather/store.py`,
  `weather/models.py`, `weather/uv.py`, `ops/selfcheck.py`, `cli.py`, `interactive/*`. The sweep
  rides on top of these — minimal fresh surface.

### Established Patterns
- **Correctness-first, cleanup-last** milestone sequencing (per the `no-backlog-fold-cleanup-in`
  convention): don't defer low-impact findings to a backlog — resolve or explicitly accept them
  here.
- **Verify-then-classify** — the ledger has `CONFIRMED` / `PLAUSIBLE` / `SWEEP-NEW` verdicts;
  `PLAUSIBLE`/`SWEEP-NEW` findings must be verified against current code before fixing (some may
  already be moot).

### Integration Points
- **Ledger write-back** — `WHOLE-PROJECT-REVIEW.md` gains per-WB-finding disposition markers.
- **Milestone close** — this phase's ledger reconciliation is the evidence the v2.1 milestone
  audit (`/gsd-audit-milestone`) will check before archiving.

</code_context>

<specifics>
## Specific Ideas

- Concrete dead-code targets named by the roadmap goal: dead `-m` guard copy (F46), dead
  `is_transient` call (F92), unreachable UTC fallback (F65), dead `verbose` param (F76), dead
  `gate_until_healthy`/`emit_online`/`_do_reload` (F16), misleading `lookup_forecast` docstring
  (F104), single-source alerts doc-mismatch (F66).
- Example finding-category coverage for HARD-CLEAN-02: config defaults (F71, F74, F75), boundary
  comparisons (F59, F72), rounding/peak-max (F60, F73), observability counters (F61, F90),
  resource/state-leak (F57, F89 `_forecast_failure_streaks` unbounded growth).

</specifics>

<deferred>
## Deferred Ideas

- **17 hub findings (H01–H17)** — belong to `YahirReusableBot`; human-gated tag cut + repin.
  Already captured in `HUB-FINDINGS-HANDOFF.md`; this phase only confirms routing, does not fix.
- Any WB finding this phase deliberately **DEFERS** (rather than fixes/accepts) must be recorded
  in the D-03 ledger with a target — no silent drop.

None from scope creep — discussion stayed within the cleanup domain.

</deferred>

---

*Phase: 35-cleanup-sweep*
*Context gathered: 2026-07-13*
