# Requirements: WeatherBot — v2.0 Bot Module Extraction ("The Great Decoupling")

**Defined:** 2026-06-27
**Core Value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.

> **Milestone scope: a PURE EXTRACTION.** Carve WeatherBot's reusable, channel-agnostic bot
> infrastructure into a standalone module (`YahirReusableBot`, import root `yahir_reusable_bot`)
> that lives in its own repo and is consumed back via a uv git dependency. **Behavior stays
> byte-identical** — the pre-existing test suite plus new golden tests are the acceptance
> contract. No new user-facing weather feature. Sequence: clean internal package boundary
> **in place** first (tests green), **then** physical split.
>
> **The governing acceptance lens for every seam:** *"could a hypothetical reminder bot reuse
> this with zero weather assumptions?"* If a weather concept (`location`, `forecast`, `uv`,
> `openweather`) appears in the module, the seam is in the wrong place.

## v2.0 Requirements

### Behavior Preservation (the contract)

- [x] **BHV-01**: Every existing WeatherBot behavior remains byte-identical through the extraction — the full pre-existing test suite stays green at every phase boundary (no skips, no rewrites that weaken an assertion).
- [x] **BHV-02**: Golden/characterization tests pin the observable outputs that intent-level tests miss — briefing text, Discord embed fields + order, the per-location schedule plan, persisted DB rows, and panel `custom_id`s — and are re-run as the byte-identical oracle after each seam extraction and again after the physical split.

### Reusable Core Seams (the module — each governed by the reminder-bot litmus)

- [x] **SEAM-01**: A channel-agnostic `Channel` abstraction + the delivery-reliability wrapper (retry/backoff honoring `Retry-After`, never retrying 401/403, out-of-band alert, heartbeat) live in the module with zero weather coupling.
- [x] **SEAM-02**: The scheduler engine exposes `register(job_id, trigger, callback)` accepting arbitrary triggers (cron / interval / one-shot date), fires exactly-once keyed on a generic `(job_id, occurrence)`, is DST-safe, and performs restart catch-up — containing no location/weather concept.
- [x] **SEAM-03**: Job persistence is a serialization-clean `JobStore` Protocol seam (importable callbacks, picklable ids, look-up-at-fire-time); the in-memory / config-rederive implementation ships, shaped so a future bot can add a durable store without redesign (durable impl itself deferred — see Future).
- [x] **SEAM-04**: The config hot-reload engine (immutable `ConfigHolder[T]` snapshots, validate→atomic-swap→job-reconcile, file-watch + SIGHUP triggers, `check-config` dry-run, keep-old-on-failure) operates over an **app-defined** config schema via injected `validate` + `desired_jobs` hooks — knowing none of the app's field names.
- [x] **SEAM-05**: The process-lifecycle layer (systemd `Type=notify` READY-gate, supervised-restart contract, heartbeat) gates READY on an **app-provided** health-check callback; the weather/API probe stays app-side.
- [x] **SEAM-06**: The self-describing command registry + shared dispatcher live in the module; commands are registered by the app, and CLI + Discord + `help` all derive from that single registry with drift structurally impossible.
- [x] **SEAM-07**: The Discord adapter (isolated gateway `BotThread` + `PanelKit`) lives in the module; `PanelKit` builds the control surface from the registry, exposes a generic `SelectedContext`, and takes the result `render` as an **injected** callable — resolving the `render_embed`↔`PanelView` cycle by ownership (not a deferred import). The operator gate, per-callback failure-isolation envelope, frozen `custom_id`s, and `discord.py==2.7.1` pin are preserved.

### WeatherBot as Consumer (app adaptation)

- [x] **APP-01**: WeatherBot wires the module at a single composition root — registering its weather commands, its config schema (`locations` / `[uv]` / templates), its health probe, its `render_embed`, and its selected-*location* context — keeping zero duplicated copy of any module mechanism.
- [x] **APP-02**: The four "secretly app-coupled" leak points are injected, not baked into the module — `SelectedContext` (location), the config id-deriver (exactly-once key), the health-check, and panel cosmetics — verified by a litmus check that no weather term appears in the module package.

### Packaging & Repo Split

- [x] **PKG-01**: The reusable code is first carved into a clean internal package boundary **in place** — the module subpackage imports zero app code (one-way dependency, enforced by an import-lint/grep gate) — with the full suite green, before any physical move.
- [x] **PKG-02**: The module is extracted to its own repo `YahirReusableBot` as an installable package (import root `yahir_reusable_bot`) shipping **no** console script; WeatherBot depends on it via a uv **git dependency** (tag-pinned for deploy) with an editable path override for local co-development, a reproducible `uv.lock`, and a `uv build --no-sources` leak gate. A clean-venv install + live `yahir-mint` `systemctl restart` UAT confirm the deployed bot runs against the pinned module.

### Extensibility & Docs

- [x] **DOCS-01**: The module ships an `EXTENSION-GUIDE` documenting each plug point (`JobStore`, command registration, config-schema extension, `Channel`, panel `SelectedContext`, health-check) with implemented-vs-deferred status; the module is initialized as its own GSD project recording the durable-`JobStore` impl and a second `Channel` adapter as deferred extension points.

## Future Requirements

Deferred beyond v2.0 — built in the consuming bot first, promoted to the module when a second consumer needs them (rule of three).

### Module extension points (designed in v2.0, built later)

- **JOBSTORE-V2-01**: Durable/dynamic `JobStore` implementation (runtime add/remove jobs that survive restart) — the headline deferred extension point; built when a reminder-style bot makes it real.
- **CHAN-V2-01**: Telegram delivery channel (validates the `Channel` abstraction with a second free channel).
- **CHAN-V2-02**: SMS delivery via Twilio.
- **CHAN-V2-03**: Slack delivery channel (Block Kit UI surface).

### WeatherBot app features (carried forward, unchanged — now post-extraction)

- **CMD-V2-02**: On-demand lookup for arbitrary / geocoded-anywhere locations (would extend the panel with a modal text-input flow).
- **ANLY-V2-01**: Weather-pattern analysis over the v1-persisted SQLite store (trends, history queries).
- **ANLY-V2-02**: History query / export interface (e.g. CSV dump).
- **ENH-V2-03**: Real-time severe-weather push alerts (a panel auto-refresh / live-update would build on this).
- **PANEL-V2-01**: Grey out / disable command buttons until a location is selected.

## Out of Scope

Explicitly excluded for v2.0. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Durable `JobStore` **implementation** | Seam is designed now; impl has no consumer in v2.0 — building it blind risks guessing the reminder bot's needs wrong (YAGNI). Deferred to JOBSTORE-V2-01. |
| New channels (Telegram/SMS/Slack) | Pure extraction ships no new user-facing capability; channels validate the abstraction *later*, in their own milestones. |
| Weather-pattern analysis / history export | App-side feature work; belongs after the boundary is clean (ANLY-V2-01/02). |
| Async rewrite of the briefing spine | Would break the byte-identical contract and the 649-test oracle; the sync scheduler spine stays (v1.1 decision holds). |
| PyPI publishing / versioned release ceremony | Personal single-consumer module — lightweight git tags + uv git pin suffice; no public distribution. |
| Plugin discovery / dynamic module loading | Over-engineering for a single operator; a static registry dict is the documented pattern (anti-feature per research). |
| Multi-tenant / multi-operator config | This stays a personal single-operator tool; the operator-id model is preserved, not generalized. |
| Generic templating engine in the module core | Rendering is purely app-coupled; the core only passes text/payload to `Channel.send`. Templates stay WeatherBot-side. |
| Non-Discord control panel (buttons for SMS/Slack) | The panel is a Discord-adapter affordance; other channels bring their own UI surfaces when implemented. |

## Traceability

Which phases cover which requirements. Filled by the roadmapper.

| Requirement | Phase | Status |
|-------------|-------|--------|
| BHV-01 | Phase 21 | Complete |
| BHV-02 | Phase 21 | Complete |
| SEAM-01 | Phase 22 | Complete |
| SEAM-02 | Phase 23 | Complete |
| SEAM-03 | Phase 23 | Complete |
| SEAM-04 | Phase 24 | Complete |
| SEAM-05 | Phase 25 | Complete |
| SEAM-06 | Phase 26 | Complete |
| SEAM-07 | Phase 27 | Complete |
| APP-01 | Phase 25 | Complete |
| APP-02 | Phase 25 | Complete |
| PKG-01 | Phase 22 | Complete |
| PKG-02 | Phase 28 | In Progress (repo+v0.1.0 shipped 28-01; re-point/clean-venv/live UAT in 28-02..04) |
| DOCS-01 | Phase 28 | Complete |

**Coverage:**

- v2.0 requirements: 14 total
- Mapped to phases: 14 ✓ (each requirement maps to exactly one phase — no orphans, no duplicates)
- Unmapped: 0

**Cross-cutting acceptances** (anchored once, enforced on every seam phase):

- **BHV-01** (suite stays green at every boundary) anchored at Phase 21, re-run on Phases 22–28.
- **PKG-01** (clean in-place boundary, module imports zero app code; import-lint/litmus-grep gate) anchored at Phase 22, enforced on Phases 23–27 and re-verified across the package boundary at Phase 28.
- **APP-02** (litmus-grep: no weather term in the module) anchored at Phase 25 where the leak-points are wired, applied as a standing grep gate on every seam phase (22–27).

---
*Requirements defined: 2026-06-27*
*Last updated: 2026-06-27 — roadmap created (Phases 21–28); traceability mapped, 14/14 covered*
