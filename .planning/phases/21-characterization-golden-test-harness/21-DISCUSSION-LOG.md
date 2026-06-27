# Phase 21: Characterization / Golden-Test Harness - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-27
**Phase:** 21-characterization-golden-test-harness
**Areas discussed:** Snapshot storage mechanism, Coverage audit tooling & gate, Granularity & determinism, Oracle self-proof + exception pin

**Mode:** advisor (research-backed comparison tables; 4 parallel `gsd-advisor-researcher` agents, one per selected area). Calibration tier: standard. NON_TECHNICAL_OWNER: false (USER-PROFILE.md shows a technical, deliberate-informed, code-example-first developer — no product-outcome reframing applied).

---

## Snapshot storage mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| syrupy + few inline pins | Add syrupy (JSON ext for structured payloads, SingleFile/raw for custom_ids+CLI); keep a couple inline literals for tiny pins. ~zero real dep weight (only needs pytest). | ✓ |
| Hand-rolled golden dir | tests/golden/*.json\|.txt with a write-on-missing helper. Zero new dep, but you build the regen + overwrite-safety rails yourself. | |
| Inline literals only | Extend the existing test_weather_spec_byte_identical pattern everywhere. Zero dep, but laborious/error-prone across dozens of cases. | |
| (researched) inline-snapshot lib | Pre-1.0, 4–5 transitive deps, rewrites test source on update. | |

**User's choice:** syrupy + few inline pins
**Notes:** syrupy's only dependency is pytest (already pinned 9.0.3), so the dep weight is one line. JSONSnapshotExtension is order-preserving (catches embed field reorder); SingleFileSnapshotExtension pins raw bytes (catches custom_id flips). Discipline rule recorded: any non-empty snapshot diff during an extraction phase is a failure to investigate, never a rubber-stamp `--snapshot-update`.

---

## Coverage audit tooling & gate

| Option | Description | Selected |
|--------|-------------|----------|
| pytest-cov branch, one-time audit | pytest-cov + branch=true, scoped to the 6 move-path packages, run once in Phase 21, fill gaps with characterization tests. No standing fail_under. | ✓ |
| pytest-cov branch, standing 100% gate | Same, plus fail_under=100 in addopts so any later phase dropping a seam branch fails loud. Per-phase friction. | |
| raw coverage.py out-of-band | Two-step coverage run as a separate deliberate ritual. | |

**User's choice:** pytest-cov branch, one-time audit
**Notes:** Branch mode is mandatory — the extraction risk is the *untaken* side of an if/except, which goldens (observable-output only) cannot see. Scope = `weatherbot/{channels,scheduler,config,reliability,ops,interactive}`. No CI exists, and the 628-suite + goldens are the standing guard, so a standing fail_under isn't worth the friction. Existing `# pragma: no cover - <reason>` convention carried forward (reason mandatory).

---

## Granularity & determinism

| Option | Description | Selected |
|--------|-------------|----------|
| Representative-subset parametrized | One golden per (command,state) cell covering each command + each Phase-20 state + each forecast variant ≥ once. Drift-localizable, no cartesian explosion. | ✓ |
| Coarse per-surface | One golden per surface. Tiny matrix, but failure points at 'the embed' not which command/state. | |
| Full cartesian | Every command × 📍 × Updated × forecast-variant. Maximal localization, dozens-to-hundreds of goldens. | |

**User's choice:** Representative-subset parametrized
**Notes:** Determinism strategy locked as the default (freeze-clock + targeted-scrub): freeze the `Updated <t:…>` epoch + APScheduler `next_run_time` via time-machine, keeping the format string in the golden so a format regression still fails; scrub only non-clock bytes (rowids, non-clock created_at); pin DB query order with explicit ORDER BY, not a sort-scrub. Over-scrubbing flagged as an explicit anti-goal.

---

## Oracle self-proof + exception pin

| Option | Description | Selected |
|--------|-------------|----------|
| Meta-test + identity&FQN pin | Self-proof = perturb-then-pytest.raises(AssertionError) meta-test. Exception pin = is-identity via caller import path + frozen (__module__,__qualname__) tuple. No new deps. | ✓ |
| xfail-strict + identity&FQN pin | Same exception pin; self-proof encoded as @pytest.mark.xfail(strict=True). Functionally equal, reads inverted. | |
| Add mutation testing too | Above, plus a mutmut pass scoped to render fns. New dev dep, out-of-band. | |

**User's choice:** Meta-test + identity&FQN pin
**Notes:** Self-proof meta-test will itself fail if the comparison is ever loosened. Exception pin combines `is`-identity through the caller's import path (tightest guard against a broadened except) with a frozen (__module__, __qualname__) assert (a re-home/rename fails with a crisp name diff). `isinstance` explicitly avoided as the pin.

## Claude's Discretion

- Exact golden file/case naming and `tests/__snapshots__/` layout.
- Enumerating the specific "move-path" exception types (from reliability / Discord-adapter / scheduler caught-error types).
- The precise frozen instant + timezone (reuse the existing recorded-forecast fixtures' assumption).
- Whether to include the optional behavioral except-catch end-to-end backstop.

## Deferred Ideas

- Standing `fail_under=100` branch gate — declined (no CI; friction > benefit). Revisit if CI is added.
- Mutation testing (mutmut/cosmic-ray) scoped to render fns — declined as out-of-band; future option.
- Behavioral except-catch end-to-end backstop — optional, left to planner/executor discretion.
