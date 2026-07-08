# Phase 22: Channel + Delivery-Reliability Seam (+ in-place boundary) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-27
**Phase:** 22-channel-delivery-reliability-seam-in-place-boundary
**Areas discussed:** Boundary name & layout, Channel seam placement, Reliability scope, Hygiene gate mechanism (import-lint), Litmus-grep scope
**Mode:** Advisor (research-backed comparison tables; calibration tier `full_maturity` — profile vendor philosophy = `thorough-evaluator`)

---

## Boundary name & layout

| Option | Description | Selected |
|--------|-------------|----------|
| Flat sibling pkg | `yahir_reusable_bot/` at repo root next to `weatherbot/`, final import root from day 1; Phase 28 = pure `git mv`, zero churn; adds explicit hatch packages list | ✓ |
| uv workspace member | Own pyproject.toml as a workspace member; heavier; worth it only if repo hosts multiple bots before split | |
| src-layout | Migrate to `src/yahir_reusable_bot/` + `src/weatherbot/`; full-repo migration touching every tooling path | |
| nested `weatherbot/_reusable/` | (Rejected pre-question) forces the rename the strategy exists to avoid | |

**User's choice:** Flat sibling pkg (recommended)
**Notes:** Only layout that makes Phase 28 a literal `git mv` with provable zero import churn; leaves the Phase-21 coverage paths + test config undisturbed. Cost: explicit `[tool.hatch.build.targets.wheel] packages=[...]` since hatchling stops auto-discovering a second top-level package.

---

## Channel seam placement

| Option | Description | Selected |
|--------|-------------|----------|
| Clean abstraction now, Discord at P27 | Move text-only `Channel`+`DeliveryResult` to module (delete Forecast import); drop `send_briefing` from the abstraction; concrete Discord channel + embed stays app-side until Phase 27 | ✓ |
| Re-home Discord embed now too | Same but also move embed-building app-side this phase; pulls Phase-27 work forward | |
| Generalize to send_rich(text, payload) | Opaque payload the module never inspects; `object`/Any only renames the coupling | |
| Dual Protocol | `Channel` Protocol in module + app-side `BriefingChannel`; breaks isinstance tests; over-built for 1 channel | |

**User's choice:** Clean abstraction now, Discord at P27 (recommended)
**Notes:** `send_briefing(text, forecast: Forecast)` is the only real weather coupling in the abstraction; dropping it + deleting the `Forecast` import clears it. Phase 27 ("Discord Adapter + PanelKit") is the named home for relocating the Discord transport — avoids moving the embed (and risking the goldens) twice. Temporary two-home split documented as a Phase-27 hand-off.

---

## Reliability scope

| Option | Description | Selected |
|--------|-------------|----------|
| Retry + AlertSink port; heartbeat OUT | Move retry primitives + define AlertSink port (weather alert impl stays app-side as adapter); heartbeat deferred to Phase 25 | ✓ |
| Retry primitives only | Move only retry/classifiers/parse_retry_after/REASON; defer both alert and heartbeat ports | |
| Retry + both alert & heartbeat ports | Define heartbeat hook now too; speculative — no consumer until Phase 25 | |
| Full DeliveryGuard wrapper | Pull retry+alert+heartbeat orchestration into a generic wrapper, refactor fire_slot; highest byte-identical risk | |

**User's choice:** Retry + AlertSink port; heartbeat OUT (recommended)
**Notes:** Alert is Phase-22-natural delivery work → define the port now (Ports & Adapters), keep the weather-coupled `record_alert`/`briefing_missed` SQLite impl app-side as the adapter, adapt (not rewrite) `fire_slot`. Heartbeat is a lifecycle concern (APScheduler `__heartbeat__` job + systemd `Type=notify`) → belongs to Phase 25; defining its hook now is speculative (YAGNI).

---

## Hygiene gate mechanism (import-lint)

| Option | Description | Selected |
|--------|-------------|----------|
| grimp in a pytest test | In-process assert on the import graph + isolated-import smoke test; native pytest, 1 dep, direct TYPE_CHECKING control, auto-scales | ✓ |
| import-linter (declarative) | `[tool.importlinter]` contracts shelled from pytest; counts TYPE_CHECKING imports by default; 2 deps + exit-code parsing | |
| Hand-rolled ast walk | Zero new deps but re-implements import resolution; failure mode is a silent false-negative | |

**User's choice:** grimp in a pytest test (recommended)
**Notes:** No CI exists (the suite is the regression guard), so an in-process assert fits better than shelling a CLI. Paired with the isolated-import smoke test (PKG-01 asks for both). import-linter kept as a viable runner-up.

---

## Litmus-grep scope

| Option | Description | Selected |
|--------|-------------|----------|
| Signature/identifier-only | Check AST-extracted public names (def/class/params/annotations), not docstrings/comments; ignores ~19 incidental prose mentions; flags only real surface leaks | ✓ |
| Whole-text + allowlist | Grep all text; allowlist file of known-incidental lines; ongoing upkeep + drift; can rubber-stamp a real leak | |
| Whole-text + scrub | Grep all text and rewrite every weather noun out of docstrings now; high churn + forced signature rename | |

**User's choice:** Signature/identifier-only (recommended)
**Notes:** A leak that matters is a name in the public surface, not prose. The one real hit today (`send_briefing`'s `forecast` param) is already fixed by the channel-seam decision — three gates, one fix. Full docstring scrub deferred to the repo-extraction milestone (Phase 28 / DOCS-01).

---

## Claude's Discretion

- Exact module sub-layout inside `yahir_reusable_bot/` and file naming.
- The precise `AlertSink` Protocol method signature(s) — minimal, weather-clean, shaped by `fire_slot`'s existing alert calls.
- The exact `grimp`-graph assertion form (edge allowlist, TYPE_CHECKING include/exclude) and the isolated-import smoke-test harness shape.
- How "public surface" is extracted for the litmus check (AST walk vs def/class-line scan).
- Confirm the actual build backend in `pyproject.toml` before writing the `packages = [...]` block.

## Deferred Ideas

- Relocate concrete `DiscordWebhookChannel` transport + embed → Phase 27 (its named home).
- Heartbeat hook/port in the module → Phase 25 (lifecycle + systemd `Type=notify`).
- Full docstring/comment weather-noun scrub → Phase 28 / DOCS-01 (standalone repo).
- Switch the import gate to declarative `import-linter` → viable runner-up if contract-as-docs is later preferred.
- uv workspace / multi-package arrangement → only if a second in-repo bot consumer appears before the split.
