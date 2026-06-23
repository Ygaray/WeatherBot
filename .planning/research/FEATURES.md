# Feature Research

**Domain:** Single-operator Discord button/select control panel over an existing command registry (v1.3 "Discord Control Panel")
**Researched:** 2026-06-23
**Confidence:** HIGH (Discord component limits, the 3-second ack rule, and persistent-view mechanics are all confirmed against discord.py docs/examples + Discord's own developer docs; per-user select-state limitation confirmed against the upstream discord.py issue.)

> Scope note: this is a **pure UI layer** over the v1.2 command registry. No new weather
> capabilities. Every "feature" below is an interaction behavior, and its data/answer comes
> from an already-shipped registry command. The UX decisions (one pinned smart panel,
> in-place editing, location dropdown + button grid, Forecast sub-options, operator-only)
> are **locked** from milestone questioning — this research validates the *behaviors users
> expect of such a panel* and the *constraints those decisions imply*, not the decisions.

---

## Hard Platform Constraints (drive everything below)

These are non-negotiable Discord/discord.py facts the panel must be designed around. They are
not "features" but they bound the table-stakes list, so they come first.

| Constraint | Value | Source confidence | Design impact |
|------------|-------|-------------------|---------------|
| Components per message | **5 action rows max**; each row is 5 "width units" | HIGH | The whole panel must fit in 5 rows. |
| Buttons per row | up to **5** (1 unit each) → 25 buttons max if all rows are buttons | HIGH | Plenty of room for the 7–8 read-only commands. |
| Select menu width | a select **consumes a full row** (all 5 units); one select per row | HIGH | The location dropdown eats one of the 5 rows by itself, leaving **4 rows / 20 button-slots** for commands + sub-options. |
| Select options | **1–25 options** per string-select | HIGH | Project has 2 configured locations — far under the cap; never a problem. |
| Interaction ack deadline | must acknowledge **within 3 seconds** or Discord shows "This interaction failed" and the token dies | HIGH | A weather command does a network fetch → **must `defer()` first**, then edit. |
| Post-ack window | once acked, token is valid **15 minutes** to edit / follow up | HIGH | After defer, editing the panel in-place is well within budget. |
| Persistent view | requires `timeout=None` **and** every component has a stable `custom_id`; bot must **re-`add_view()` on startup** | HIGH | Buttons survive restart only if the panel is rebuilt and re-registered in `setup_hook`/startup. |
| Select selection state | Discord does **not** persist a dropdown's chosen value server-side; selection is client-side only and lost on restart; `Select.values` is even empty for unchanged `default` options | HIGH | The "currently selected location" cannot be assumed to survive a restart for free — the bot must own that state if it wants to show it. |

---

## Feature Landscape

### Table Stakes (Users Expect These)

A panel that lacks any of these will feel broken or untrustworthy to the operator.

| Feature | Why Expected | Complexity | Notes / Dependency |
|---------|--------------|------------|--------------------|
| **Location dropdown (string select) populated from config** | The panel's whole premise is "pick where, then tap what." Options must be the *configured* locations, by name. | MEDIUM | Reads location list from the live `ConfigHolder` snapshot. Must re-derive options on config reload (locations are hot-reloadable per v1.1). 2 options today; built for N. |
| **One-tap command buttons for the read-only commands** | weather / uv / next-cloudy / sun / wind — each a single tap once a location is chosen. This is the core value. | MEDIUM | Each button's handler calls the **same registry command** the text path uses. No new fetch/render logic — reuse `interactive/lookup.py` core. |
| **Fast acknowledgement (defer-then-edit) so taps never show "interaction failed"** | A button that visibly "fails" destroys trust in the panel. Weather fetches exceed 3s sometimes. | MEDIUM | `interaction.response.defer()` immediately, then `edit_original_response`/`edit_message`. This is the single most important correctness behavior. |
| **In-place result rendering (panel message edits, no new-message spam)** | Explicitly decided UX; also what users expect of a "control panel" vs a chat bot. | MEDIUM | After defer, edit the panel message's content/embed with the result; keep the components attached so it stays interactive. |
| **Argless commands ignore the dropdown** | status / alerts have no location arg; tapping them with a location selected must still work and not error. | LOW | Registry already distinguishes argless vs location commands — branch on command metadata, don't pass the location. |
| **Operator-only enforcement on every interaction** | Single-operator tool; the panel is pinned in a public-ish channel; non-operator taps must be rejected. **Out-of-Scope: multi-user.** | LOW | Reuse the existing guard ladder on `interaction.user.id`. Reject **ephemerally** (see below) so the polite "not for you" is visible only to the tapper and never edits the shared panel. |
| **Polite reject is ephemeral, not a panel edit** | A non-operator tap must not clobber the operator's last result or spam the channel. | LOW | `interaction.response.send_message(..., ephemeral=True)`. Ephemeral is the *correct* tool specifically for "reply only the clicker sees." |
| **Persistent panel: buttons work after a bot restart/deploy** | The panel is pinned and meant to live forever; a deploy must not turn it into dead buttons. | MEDIUM-HIGH | `timeout=None` + stable `custom_id` per component + `add_view()` on startup. **This is the highest-risk table-stakes item** (see Pitfalls/Dependencies). |
| **Forecast button → sub-options (Weekday/Weekend × Detailed/Compact)** | Decided UX; mirrors the text command's 4 variants. A two-tier flow is the standard pattern when one command has modes. | MEDIUM | Tapping Forecast reveals a sub-row (or replaces the grid) with the 4 variants; each variant routes to the registry forecast command with the right flags. |
| **Readable, scannable button labels + styling** | Operators scan a grid; unlabeled or same-color buttons are unusable. | LOW | Short labels, an emoji per command for at-a-glance scanning, consistent `ButtonStyle` semantics (e.g. one accent color for the active action class, neutral for the rest). |

### Differentiators (Make the Panel Feel Polished)

Not required for the panel to function, but they're what separate a delightful personal cockpit
from a bare button wall. They align with the operator's stated **design-conscious** UX profile.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Visible "selected location" indicator** | The operator should always know *which* location the next tap will hit — the dropdown's own label may reset on restart. | MEDIUM | Render the active location into the panel header/embed. Requires the bot to **own** the selected-location state (Discord won't persist it). Pick a sane default (first configured / home) on startup. |
| **Sub-option flow that returns to the main grid** | After viewing a forecast variant, the operator wants to be back at the full command grid, not stuck in the forecast sub-menu. | MEDIUM | A "back" affordance or auto-restore of the main grid on the next non-forecast tap. Pure view-state management. |
| **Loading affordance during the fetch** | After defer, a brief "fetching <city> weather…" placeholder reassures during the 1–3s fetch. | LOW | The deferred state already shows "thinking" for ephemeral; for in-place edits, a transient header line is a nice touch. |
| **Emoji-coded command grid** | Weather, UV, wind, sun, forecast, alerts — turns scanning into pattern-recognition. | LOW | Cheap, high polish-per-effort. Keep consistent with any emoji already used in briefing templates. |
| **Timestamp / "as of" on rendered results** | In-place editing means old + new results look identical; a timestamp shows the tap actually refreshed. | LOW | Append a relative/absolute "updated <time>" to the result. Disambiguates "did my tap do anything?" |
| **Summon command to (re)create the panel** | If the panel is ever deleted/unpinned, the operator wants a one-liner (`!panel`) to recreate + pin it. | LOW-MEDIUM | A small command that posts a fresh panel message and (optionally) pins it. Complements persistence rather than replacing it. |
| **Disabled/greyed buttons when prerequisites unmet** | E.g. command buttons greyed until a location is selected, so a tap can't produce a confusing "no location" result. | MEDIUM | Optional; only worth it if a no-location-selected state is reachable. With a sensible default location it may be unnecessary. |

### Anti-Features (Tempting, but Wrong for This Project)

These either contradict the locked single-operator boundary, fight Discord's model, or add
disproportionate complexity for a personal tool.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Per-user panel state / multiple users driving it** | "What if a friend wants to tap it too?" | Directly violates the **single-operator / no multi-user** Out-of-Scope boundary. Per-user state needs a DB keyed by user id and breaks the "one shared pinned panel" model. | Operator-only guard; reject others ephemerally. One panel, one owner. |
| **Config editing via the panel (add/rename locations, edit schedules, set thresholds)** | "It's already a control panel — let me change settings too." | Explicitly Out-of-Scope: **config stays file-based; the bot reads weather and reports reload outcomes, it does not edit config** (v1.1 decision). Two-way editing reintroduces validation/secrets/atomicity concerns the file-reload path already solved. | Edit the TOML; hot-reload picks it up. Panel auto-refreshes its dropdown from the new config. |
| **One panel message per location (a wall of pinned panels)** | "Show both cities at once." | Defeats the single-smart-panel decision, doubles persistence/state surface, and clutters the channel. | One panel, switch context via the dropdown. |
| **Posting each result as a NEW message** | Simpler to code (just `send`). | Explicitly rejected — creates new-message spam and loses the cockpit feel. | In-place edit of the panel message. |
| **Modal pop-ups / free-text input for arbitrary locations** | "Type any city." | Arbitrary/geocoded-anywhere lookup is a **deferred v2 candidate (CMD-V2-02)**, not this milestone. Adds a whole input+validation path. | Dropdown of *configured* locations only. |
| **Auto-refreshing / live-updating panel (polls weather on a timer)** | "Always-current numbers." | Burns OpenWeather quota, adds a loop, and the panel is pull-not-push by design. Real-time push is deferred (ENH-V2-03). | Tap to fetch on demand (short-TTL cache already exists). |
| **Persisting the selected location across restarts via a new datastore** | "Remember where I left it." | Discord won't persist select state, so this means a new state store for a cosmetic nicety. Disproportionate for a personal tool. | Default to a sensible location (home/first) on startup; operator re-picks in one tap. Treat selected-location as **in-memory, best-effort**. |
| **Slash commands / app-command tree as the panel** | "Slash commands are the modern way." | Orthogonal to the decided UX (a *persistent pinned button panel*), and the existing bot is a prefix-command gateway bot. Mixing in an app-command tree is new surface for no decided benefit. | Keep prefix commands for text; the panel is buttons/selects over the same registry. |
| **Buttons that reply ephemerally instead of editing in-place** | Ephemeral feels "clean / private." | Ephemeral results can't be edited by the *next* tap into the same surface and don't give the persistent cockpit view; they're right only for the reject path. | Ephemeral **only** for the non-operator reject; operator results edit the panel in place. |

---

## Feature Dependencies

```
[Persistent pinned panel]
    └──requires──> [Stable custom_id per component] + [timeout=None] + [add_view() on startup]

[Location dropdown]
    └──requires──> [Live config snapshot of locations (ConfigHolder)]
    └──reload-coupled──> [Config hot-reload re-derives dropdown options]

[One-tap command buttons]
    └──requires──> [v1.2 command registry as single source of truth]
    └──requires──> [Fast ack: defer-then-edit]  (else fetch > 3s -> "interaction failed")
    └──requires──> [Selected-location state]  (for location commands; argless skip it)

[In-place result rendering]
    └──requires──> [Fast ack: defer-then-edit]

[Forecast sub-options]
    └──requires──> [One-tap command buttons] + [view-state to swap grid <-> sub-row]
    └──requires──> [registry forecast command + its weekday/weekend x detailed/compact flags]

[Operator-only enforcement]
    └──requires──> [existing guard ladder on interaction.user.id]
    └──pairs-with──> [ephemeral reject]

[Visible selected-location indicator] ──enhances──> [Location dropdown]
    └──requires──> [bot-owned selected-location state]  (Discord won't persist it)

[Per-user state] ──conflicts──> [Single-operator boundary]
[Panel config editing] ──conflicts──> [file-based config / read-only bot boundary]
[New-message-per-result] ──conflicts──> [In-place rendering decision]
```

### Dependency Notes

- **Persistence requires stable `custom_id`s re-registered on startup:** discord.py only routes a
  post-restart click if the bot re-adds the view (`add_view`) and the component's `custom_id`
  matches. Confirmed against discord.py persistent-view docs/examples. This is the single most
  important structural decision for the milestone, and it slots into the existing `BotThread`
  startup path (the bot already starts after the systemd READY signal).
- **Command buttons depend on the registry (not on duplicated logic):** the locked decision is
  "reuse the v1.2 registry as the single source of truth so the panel never drifts." Each button
  dispatches to a registry command via the shared `interactive/lookup.py` read-only core — same
  answers as CLI and `!weather`. The panel must read button metadata (label, argless vs
  location, forecast-variant flags) **from** the registry, not hardcode a parallel list.
- **Defer is a hard prerequisite for any fetching button:** without an immediate `defer()`, a
  >3s OpenWeather fetch trips Discord's "interaction failed." This couples every weather button
  to the defer-then-edit pattern; argless ones could respond immediately but should defer too for
  uniformity. The existing off-loop fetch (`run_in_executor`) + short-TTL `ForecastCache` already
  keep most fetches fast — defer covers the cold-cache case.
- **Dropdown options are reload-coupled:** locations are hot-reloadable (v1.1). The panel must
  re-derive its select options when config reloads, or it will offer stale/removed locations.
  Note: `[bot]` settings are read-once-at-startup tech debt — confirm the panel's channel/operator
  binding lives on the right side of that boundary (changing them needs a restart, which is
  acceptable but should be documented).
- **Selected-location state is bot-owned and best-effort:** Discord does not persist a select's
  chosen value, and `Select.values` is empty for unchanged `default` options. So any "remember my
  location" behavior is the bot's job; the pragmatic answer is an in-memory default that resets to
  home/first on restart (don't build a datastore for a cosmetic nicety).

---

## MVP Definition

### Launch With (v1.3 core)

The minimum panel that delivers tap-to-drive and survives the operator's real deploy cadence.

- [ ] **Persistent pinned panel** (`timeout=None`, stable `custom_id`s, `add_view()` on startup) — without this, every deploy bricks the buttons; non-negotiable for an always-on bot on `yahir-mint`.
- [ ] **Location dropdown** populated from configured locations (re-derived on reload) — the panel's organizing control.
- [ ] **One-tap command buttons** for weather / uv / next-cloudy / sun / wind, dispatching through the registry — the core value.
- [ ] **Argless command buttons** (status / alerts) that ignore the dropdown — completeness; cheap.
- [ ] **Defer-then-edit fast ack + in-place rendering** — correctness; prevents "interaction failed" and delivers the decided no-spam UX.
- [ ] **Forecast button → Weekday/Weekend × Detailed/Compact sub-options** — decided scope; the one two-tier flow.
- [ ] **Operator-only guard + ephemeral reject** — enforces the single-operator boundary on the pinned-in-public panel.

### Add After Validation (v1.3 polish, if time allows)

- [ ] **Summon/recreate command** (`!panel`) — add once the panel exists and you've accidentally deleted it once.
- [ ] **Visible selected-location indicator + sensible startup default** — add when the bare dropdown feels ambiguous after a restart.
- [ ] **Emoji-coded labels + "updated <time>" stamp** — pure polish; add when the grid is functionally complete.

### Future Consideration (defer — already on the v2 list or out of scope)

- [ ] **Arbitrary/geocoded location input via modal** — defer to CMD-V2-02.
- [ ] **Auto-refresh / live panel** — defer; pull-on-tap is the model, push is ENH-V2-03.
- [ ] **Per-user / multi-user panels, config editing via panel** — out of scope by project boundary; do not build.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Persistent pinned panel (custom_id + add_view) | HIGH | MEDIUM-HIGH | P1 |
| Location dropdown from config | HIGH | MEDIUM | P1 |
| One-tap command buttons (registry dispatch) | HIGH | MEDIUM | P1 |
| Defer-then-edit fast ack + in-place render | HIGH | MEDIUM | P1 |
| Operator guard + ephemeral reject | HIGH | LOW | P1 |
| Argless commands ignore dropdown | MEDIUM | LOW | P1 |
| Forecast button + sub-options | HIGH | MEDIUM | P1 |
| Summon/recreate command | MEDIUM | LOW-MEDIUM | P2 |
| Visible selected-location indicator | MEDIUM | MEDIUM | P2 |
| Emoji labels + updated-timestamp | MEDIUM | LOW | P2 |
| Disabled buttons until location chosen | LOW | MEDIUM | P3 |
| Arbitrary-location modal input | LOW (v1.3) | HIGH | P3 (defer) |

**Priority key:**
- P1: Must have for the v1.3 panel to be correct and usable
- P2: Should have, real polish, add when core is solid
- P3: Nice to have / deferred

## Competitor Feature Analysis

"Competitors" here = the common patterns of well-built Discord control/dashboard panels
(role-menu bots, ticket panels, reaction/role boards, music-control panels).

| Behavior | Typical role/ticket panel | Typical music/control panel | Our approach |
|----------|---------------------------|-----------------------------|--------------|
| Persistence | Persistent view, re-added on startup (standard) | Persistent or per-session view | Persistent view, re-added on startup — matches standard |
| Result surface | Ephemeral confirmations to clicker | Edits the now-playing message in place | **In-place edit** of the one panel (closest to music-control) |
| Selection control | Buttons or one role-select | Buttons | **String select (location) + button grid** |
| Multi-tier flows | Category → ticket-type sub-menu | Queue/volume sub-controls | **Forecast → 4 variants** sub-row |
| Access control | Often open to all / role-gated | Often open to all | **Single-operator id guard + ephemeral reject** (stricter, by design) |
| Ack pattern | defer for slow ops | defer for slow ops | **defer-then-edit** (required by network fetch) |

The notable deviation from "typical": this panel is deliberately **single-operator and
read-only**, where most public panels are multi-user and action-taking. That tightens, rather
than loosens, the design — the guard + ephemeral-reject pair is doing more work than in a
typical community panel.

## Sources

- [discord.py persistent views (Rapptz example)](https://github.com/Rapptz/discord.py/blob/master/examples/views/persistent.py) — `timeout=None` + `custom_id` + `add_view()` on startup. HIGH
- [Writing Persistent Views — thegamecracks](https://thegamecracks.github.io/discord.py/persistent_views.html) — re-registering views after restart. HIGH
- [Discord — Receiving and Responding to Interactions](https://discord.com/developers/docs/interactions/receiving-and-responding) — 3-second ack rule, 15-minute post-ack window. HIGH
- [discord.js Guide — Command response methods](https://discordjs.guide/slash-commands/response-methods) — defer vs immediate reply, edit/follow-up timing (same gateway interaction model as discord.py). HIGH
- [Discord Message Components cheatsheet (SelectMenu and Button)](https://gist.github.com/DarkStoorM/7491224767bab6fd03879a3846824d81) + [discord.js Action rows](https://discordjs.guide/interactive-components/action-rows.html) — 5 rows × 5 units, select consumes a full row, 25-button / 5-select max. HIGH
- [discord.py Interactions API Reference](https://discordpy.readthedocs.io/en/stable/interactions/api.html) — Select 1–25 options, placeholder, `interaction.response.edit_message`, `ephemeral=True`. HIGH
- [discord.py issue #7284 — default select options absent from Select.values](https://github.com/Rapptz/discord.py/issues/7284) + [Discord support: select menus don't save selection](https://support.discord.com/hc/en-us/community/posts/9581474718231) — selection state is client-side only, not persisted server-side. HIGH

---
*Feature research for: single-operator Discord button/select control panel (v1.3)*
*Researched: 2026-06-23*
