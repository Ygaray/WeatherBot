# Requirements: WeatherBot — v1.3 Discord Control Panel

**Defined:** 2026-06-23
**Core Value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.

> Milestone scope: a **pure UI layer** — a tap-to-drive Discord control panel over the
> existing v1.2 command registry. No new weather capabilities, no new dependencies
> (everything is in the already-pinned `discord.py>=2.7.1,<3`). The panel becomes the
> operator's primary, typing-free way to access the bot. Text commands remain unchanged.

## v1.3 Requirements

### Control Panel (core)

- [x] **PANEL-01**: Operator can summon a pinned control-panel message (location dropdown + command-button grid); summon is idempotent — exactly one panel, stray panels cleaned up
- [x] **PANEL-02**: The panel's location dropdown is populated from the configured locations and re-derives its options when config is hot-reloaded
- [x] **PANEL-03**: Operator can tap a command button (weather / uv / next-cloudy / sun / wind) and get that command's result for the currently selected location
- [x] **PANEL-04**: Argless command buttons (status / alerts) work from the panel and ignore the selected location
- [x] **PANEL-05**: Every tap is acknowledged within Discord's 3-second window (defer-then-edit) so a slow fetch never shows "interaction failed"
- [x] **PANEL-06**: Command results render in-place — the panel message edits, with components reattached; no new-message spam
- [x] **PANEL-07**: Operator sees an always-visible 2×2 forecast grid (Weekday/Weekend × Detailed/Compact) and gets the chosen variant for the selected location
  - _Note: the two-tier Forecast-toggle reveal shipped in Phase 19 was superseded by an always-visible grid at v1.3 Gate-2 (quick task 260626-u8y)._

### Access & Safety

- [x] **PANEL-08**: Only the operator can drive the panel; a non-operator tap gets an ephemeral, leak-free reject that never echoes the user/command or clobbers the shared panel
- [x] **PANEL-09**: The pinned panel's buttons keep working after a bot restart/deploy (persistent views — `timeout=None`, stable `custom_id`s, re-registered on startup)
- [x] **PANEL-10**: The panel's command set is derived from the v1.2 command registry (single source of truth — no parallel hardcoded list; a new registry command surfaces on the panel without drift)
- [x] **PANEL-11**: A panel/interaction error never delays, drops, or stops a scheduled briefing (the v1.1/v1.2 failure-isolation guarantee re-proven for the new interaction-callback path)

### Polish

- [x] **PANEL-12**: The panel shows a visible "selected location" indicator with a sensible startup default (home/first), so the operator always knows which location the next tap will hit
- [x] **PANEL-13**: Command buttons use emoji-coded labels for at-a-glance scanning, and rendered results carry an "updated <time>" stamp so an in-place edit is visibly distinct from the prior one

## Future Requirements

Deferred to a later release. Tracked but not in the current roadmap.

### Control Panel polish

- **PANEL-V2-01**: Grey out / disable command buttons until a location is selected (likely unnecessary given a sensible startup default — revisit only if a no-location state proves reachable)

### Channels & Lookup (carried forward, unchanged)

- **CHAN-V2-01**: Telegram delivery channel (validates the channel abstraction with a second free channel)
- **CHAN-V2-02**: SMS delivery via Twilio
- **CMD-V2-02**: On-demand lookup for arbitrary / geocoded-anywhere locations (would extend the panel with a modal text-input flow)
- **ANLY-V2-01**: Weather-pattern analysis over the v1-persisted SQLite store
- **ANLY-V2-02**: History query / export interface (e.g. CSV dump)
- **ENH-V2-03**: Real-time severe-weather push alerts (a panel auto-refresh/live-update would build on this)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Per-user / multi-user panel state | Violates the locked single-operator boundary; one shared pinned panel, one owner (operator-guarded) |
| Config editing via the panel (add/rename locations, edit schedules/thresholds) | Config stays file-based; the bot reads weather and reports reload outcomes, it does not edit config (v1.1 decision) |
| One panel message per location (a wall of pinned panels) | Defeats the single-smart-panel decision; switch location via the dropdown instead |
| Posting each result as a NEW message | Rejected UX — creates spam and loses the cockpit feel; results edit the panel in place |
| Modal / free-text input for arbitrary cities | Arbitrary/geocoded lookup is deferred (CMD-V2-02); dropdown offers configured locations only |
| Auto-refreshing / live-polling panel | Burns OpenWeather quota and adds a loop; the panel is pull-on-tap by design (push is ENH-V2-03) |
| Persisting selected-location across restart via a new datastore | Discord won't persist select state; default-on-restart is the pragmatic answer (don't build a store for a cosmetic nicety) |
| Migrating prefix commands to slash/app commands | Orthogonal to the decided pinned-button-panel UX; the bot stays a prefix-command gateway bot, components ride the same gateway |
| New gateway intent / new dependency / discord.py bump | Not needed — components ride the existing gateway on the already-pinned discord.py 2.7.1 |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PANEL-01 | Phase 18 | Complete |
| PANEL-02 | Phase 17 | Complete |
| PANEL-03 | Phase 17 | Complete |
| PANEL-04 | Phase 17 | Complete |
| PANEL-05 | Phase 17 | Complete |
| PANEL-06 | Phase 17 | Complete |
| PANEL-07 | Phase 19 | Complete |
| PANEL-08 | Phase 17 | Complete |
| PANEL-09 | Phase 18 | Complete |
| PANEL-10 | Phase 16 | Complete |
| PANEL-11 | Phase 20 | Complete |
| PANEL-12 | Phase 20 | Complete |
| PANEL-13 | Phase 20 | Complete |

**Coverage:**

- v1.3 requirements: 13 total
- Mapped to phases: 13 ✓
- Unmapped: 0 ✓

**Per-phase mapping:**

- Phase 16 (Extract shared `dispatch_spec`): PANEL-10
- Phase 17 (Minimal persistent panel — core wiring): PANEL-02, PANEL-03, PANEL-04, PANEL-05, PANEL-06, PANEL-08
- Phase 18 (Persistence + summon/lifecycle): PANEL-01, PANEL-09
- Phase 19 (Forecast two-tier sub-options): PANEL-07
- Phase 20 (Isolation hardening + polish): PANEL-11, PANEL-12, PANEL-13

---
*Requirements defined: 2026-06-23*
*Last updated: 2026-06-23 after v1.3 roadmap creation (13/13 mapped, Phases 16–20)*
