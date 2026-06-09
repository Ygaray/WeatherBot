# Phase 1: First Briefing End-to-End - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-09
**Phase:** 1-First Briefing End-to-End
**Areas discussed:** Briefing format / templating, Location setup, Analysis intent, Discord styling

---

## Briefing format / templating

Initial layout/emoji/header questions were paused — the user reframed the area: they want templates for **all three layouts** (multi-line, compact, sectioned) because they have distinct use cases (scheduled messages, alerts, weekly briefings) across **multiple platforms, some character-constrained**, all **editable**, living in **their own directory**.

Scope line drawn: Phase 1 establishes the `templates/` directory + file-based editable rendering + the three daily-briefing layout variants. Other message *types* (alerts, weekly) and channel-specific (SMS/Telegram) variants deferred to their phases.

| Question | Options | Selected |
|----------|---------|----------|
| Directory + format | `templates/` + plain text ✓ / different location / different format | **`templates/` + plain text `.txt`, `{placeholder}`** |
| Naming convention | Flat `{type}-{style}.txt` ✓ / subdirs by type / subdirs by platform | **Flat `{type}-{style}.txt`** |
| Default layout | Multi-line / Sectioned w/ header ✓ / Compact | **Sectioned w/ header (emoji + sections)** |

**Notes:** Starter set = `briefing-sectioned.txt` (default), `briefing-multiline.txt`, `briefing-compact.txt` (plain, char-constrained-friendly). Pulls the templating foundation into Phase 1; Phase 2 TMPL deepens it.

---

## Location setup

| Question | Options | Selected |
|----------|---------|----------|
| Location spec | Lat/lon directly ✓ / city name now / either-both | **Lat/lon + display name (geocoding → Phase 2)** |
| Config shape | List with one entry ✓ / single location | **List of locations, one entry now** |
| `--send-now` target | Optional arg, default first ✓ / require name | **Optional arg; bare = default/first** |

---

## Analysis intent (SQLite schema)

| Question | Options | Selected |
|----------|---------|----------|
| Analyses wanted | Temperature trends / Rain frequency / Wind & humidity / Forecast accuracy (multiSelect) | **ALL FOUR** |
| Granularity | Every fetch ✓ / daily roll-up | **Every fetch (raw + normalized, UTC+local)** |
| Forecast storage | Current + forecast ✓ / current only | **Current + forecast buckets (keyed by target time)** |

**Notes:** Forecast-accuracy is the primary schema-shaping constraint (predicted-keyed-by-target-time + later actuals join). Flagged research-worthy to avoid a v2 migration.

---

## Discord styling

| Question | Options | Selected |
|----------|---------|----------|
| Styling | Plain text only / Plain text + basic embed ✓ | **Plain text (canonical) + basic Discord embed (Discord-only)** |
| Webhook identity | Custom name + avatar ✓ / name only / webhook default | **Custom "WeatherBot ☀️" name + configurable avatar** |

**Notes:** Plain-text body stays the canonical channel-agnostic path; embed is a Discord channel implementation detail and must not leak into the `Channel` interface.

---

## Claude's Discretion

- Exact wording/spacing inside the three starter templates.
- Internal module/package layout, library wiring, SQLite table/column specifics (grounded by research docs).
- Displayed-value rounding/precision.

## Deferred Ideas

- Weekly-briefing message type → roadmap backlog (new capability, not in v1).
- Alert templates → Phase 4 (failure) / Phase 2 (severe-weather).
- SMS/Telegram channel-specific templates & delivery → v2 (CHAN-V2).
- Per-platform template selection / character-budget enforcement → v2.
- On-demand `weather <location>` command → v2 (CMD-V2-01).
- Weather-pattern analysis/query/export → v2 (ANLY-V2).
