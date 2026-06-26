# Phase 18: Persistence + Summon/Lifecycle (Restart Durability) - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Give the pinned Discord control panel a **lifecycle** and make it **survive a
bot restart/deploy**. Two requirements:

- **PANEL-09** — the already-pinned panel's buttons/dropdown keep working after a
  restart (persistent views: `timeout=None` + static `custom_id`s + `add_view` in
  `setup_hook`). The `timeout=None`/`custom_id`s already shipped in Phase 17;
  this phase adds the `add_view` registration.
- **PANEL-01** — an idempotent `!panel` summon that **finds-or-creates exactly
  one** pinned panel, cleans up stray panels it owns, and checks the channel
  permissions it needs (clear CRITICAL if missing, never a silent mid-operation
  failure).

This phase resolves the milestone's one genuinely-open design decision —
**how the panel is located after a restart** (the answer: scan, don't persist;
see D-01) — and is verified by a live `systemctl restart weatherbot` UAT on host
`yahir-mint`.

**In scope:** `add_view` persistent-view registration via `setup_hook`; the
`!panel` operator command (find-or-create-one + pin + stray cleanup); a new
`[bot] panel_channel_id` config key; channel-permission preflight + `Forbidden`
backstop; default-on-restart selected location (already settled — D-08).

**Out of scope:** Forecast button + two-tier sub-options (Phase 19); briefing
failure-isolation re-proof for the interaction path, selected-location *visual
indicator*, emoji labels, "updated <time>" stamp (Phase 20). Persisting the
panel `message_id` or the selected location across restart (explicitly rejected
— D-01/D-08). Per-user/multi-user panel state, config editing via the panel,
new-message-per-result, modals, auto-refresh, new deps/intents,
`commands.Bot`/slash migration (milestone Out of Scope).

</domain>

<decisions>
## Implementation Decisions

### Panel-find mechanism — scan, do not persist (the headline open decision)
- **D-01 [LOCKED]:** **Find the panel by scanning the channel's pinned messages
  for a bot-owned panel — NO persisted `message_id`.** On `!panel`, scan
  `channel.pins()`, identify the panel by `author == bot.user` AND a static
  component `custom_id` marker (see D-05), reuse the first match, recreate if
  none. Rationale: persistent views already re-bind callbacks purely by
  `custom_id` via `add_view`, and the panel message itself persists server-side
  in Discord — so a durable `message_id` buys almost nothing and adds an entire
  stale/deleted-id (404) failure class that would force a scan fallback anyway.
  Scanning makes Discord the single source of truth: a deleted/unpinned panel is
  auto-detected and recreated. Matches the milestone's "no new deps, minimal
  persisted state" ethos.
- **D-02 [LOCKED]:** **No new persisted state of any kind** for the panel
  (no JSON file, no SQLite table). The SQLite-store option (a `panel` table) was
  rejected because it crosses the milestone constraint that the read-only
  dispatch path "writes nothing to the store/sent-log/scheduler," and still
  carries the stale-id problem. The hybrid (persist + scan fallback) was rejected
  as more code than a single-operator/one-panel bot warrants.
- **D-03 [LOCKED]:** **Scope the scan to pinned messages only** (`channel.pins()`),
  not full channel history. The panel is always pinned; Discord caps pins at 50
  so the scan is trivial and needs no history pagination — and it avoids
  misclassifying older non-pinned messages.

### Panel channel — configured `[bot] panel_channel_id` (coupled to D-01)
- **D-04 [LOCKED]:** **Add a `panel_channel_id: int` field to `BotConfig`
  (`[bot]` table in `config.toml`), beside `operator_id`.** A scan-based find
  (D-01) needs a *known* channel id at `on_ready`/summon time; the invoked-channel
  (zero-config) option can't re-find autonomously after a cold start (it degrades
  PANEL-09 to "operator must re-`!panel`"), and the remember-the-channel hybrid
  reintroduces the persistence D-01/D-02 deliberately avoided. The configured key
  is the coherent partner to the scan choice.
  - The morning briefing rides a **separate incoming webhook**
    (`channels/discord.py`), so `panel_channel_id` is fully decoupled from
    briefing delivery — no coupling risk.
  - `[bot]` keys are **read once at startup** (the project's already-accepted
    restart-boundary tech debt) — changing `panel_channel_id` needs a restart.
    Document this; it is not a new *kind* of debt.
  - **Channel missing/misconfigured at startup** (key unset, or points to a
    deleted/inaccessible channel): log a clear message and **skip the re-find /
    add_view-against-channel path — do NOT crash the bot thread**. Treat exactly
    like the existing fail-loud-not-silently-dead precedent.

### Idempotent summon & stray cleanup — marker-strict, reuse-in-place, delete extras
- **D-05 [LOCKED]:** **Identity = `author == bot.user` AND a static component
  `custom_id` marker** (e.g. presence of `wb:loc:select` / `wb:cmd:*` in
  `message.components`). Author-alone was rejected — it would risk deleting an
  unrelated pinned bot message (e.g. a future alert post), violating "only touch
  panels it owns." The static `custom_id`s are an unforgeable bot-owned marker.
- **D-06 [LOCKED]:** **Reuse the survivor in place; delete the extras.** When ≥1
  valid panel exists, reuse the first via `message.edit(embed=..., view=...)`
  (keeps its pin position + history, and stays live because `add_view` binds by
  `custom_id`), and **delete** any *additional* bot-owned panels. Delete (not
  unpin-only / tombstone): an unpinned-but-live View still responds to clicks
  unless its components are also stripped, so unpin-only is a correctness trap;
  delete-extras is what actually guarantees "exactly one." Recreate only if the
  scan finds none.
- **D-07 [LOCKED]:** **`!panel` is a lifecycle/write command, NOT a read-only
  registry command** — it does not route through `dispatch_spec`/the registry. It
  is handled in the operator-gated `on_message` path (or an equivalent
  operator-only branch) and is the one panel surface allowed to post/pin/edit/
  delete messages. Keep it off the read-only dispatch seam.

### Selected-location default on restart (carried forward — settled)
- **D-08 [carried from Phase 17 D-01..D-05, LOCKED]:** Selected location stays an
  **in-memory attribute on the `PanelView`**, defaulting to `locations[0].name`
  (mirrors `resolve_location(config, None)`). **Persisting the selection across
  restart is Out of Scope** — after a restart the panel defaults to
  `locations[0]`. SC#3's "sensible default-on-restart" is satisfied by this
  existing behavior; this phase adds nothing here beyond confirming a freshly
  constructed `PanelView` (built at `add_view` time) reflects current config.

### Permission preflight — hybrid (eager check + Forbidden backstop)
- **D-09 [LOCKED]:** **Eager `channel.permissions_for(guild.me)` preflight at
  summon, BEFORE posting**, plus a per-action `discord.Forbidden` catch around
  each write (post/pin/edit/delete). Preflight prevents partial state (e.g.
  posted-but-unpinned orphan) and lets us emit one precise CRITICAL naming the
  missing permission; the `Forbidden` catch closes the TOCTOU gap (a perm revoked
  between check and act) so a slipped 403 still logs CRITICAL instead of bubbling
  as a traceback. Attempt-and-catch alone was rejected (mid-sequence 403 →
  orphan message = the exact silent partial-failure SC#4 forbids); eager-only was
  rejected (TOCTOU).
- **D-10 [LOCKED]:** **Exact permission set to preflight** (in the panel channel):
  `view_channel`, `send_messages`, `embed_links`, `read_message_history`, and
  **`pin_messages`**.
  - ⚠️ **`pin_messages`, NOT `manage_messages`** — discord.py 2.7+ exposes
    `Permissions.pin_messages` because Discord split `PIN_MESSAGES` out of
    `MANAGE_MESSAGES` (effective 2026-01-12). The project is pinned
    `discord.py >=2.7.1,<3`, so check the new split bit; checking
    `manage_messages` would falsely pass on a server that granted only the new
    "Pin Messages" permission. This resolves the roadmap's MEDIUM-confidence
    "exact pin/embed permission set."
  - In-place `Message.edit()` of the bot's own message needs no extra perm beyond
    channel access; `embed_links` (already listed) covers the edited embed
    rendering.
- **D-11:** **On missing perms:** log a clear **CRITICAL** (mirroring the existing
  `on_ready` missing-`message_content`-intent precedent) naming the missing
  permission, AND send the operator an ephemeral message naming the gap, then
  **refuse to summon** (don't post a half-broken panel). An optional cheap
  boot-time sanity check at `on_ready` may log the same gap early.

### Startup behavior — passive at boot, reconcile only on `!panel`
- **D-12 [LOCKED]:** **On process startup the bot is PASSIVE: register the
  persistent view via `add_view` in `setup_hook` and nothing more.** The full
  find-or-create / re-pin / stray-cleanup reconciliation runs ONLY on an explicit
  `!panel`. `add_view` re-binds the existing pinned panel's buttons so SC#1
  (buttons work after restart) holds without any boot-time scan. If the operator
  deleted the panel while the bot was down, they re-run `!panel`. Chosen over
  active boot-reconcile to minimize bot-thread startup I/O and keep "summon is the
  `!panel` path" — the panel message persists server-side anyway.

### `setup_hook` registration (implementation note, locked direction)
- **D-13 [LOCKED direction; mechanics = Claude's discretion]:** Use
  **`setup_hook`, NOT `on_ready`**, for `add_view` — `on_ready` re-fires on every
  gateway reconnect → duplicate persistent-view registrations. Today
  `build_client` constructs a plain `discord.Client` with `@client.event`
  handlers; reaching `setup_hook` cleanly (subclass `discord.Client` and override
  `setup_hook`, vs. another wiring) is the planner/researcher's call, but the
  registration MUST land in `setup_hook` and MUST be idempotent across reconnects.

### Claude's Discretion
- Exact `!panel` command token/parse location and the operator-gate reuse from
  the `on_message` ladder; the scan/cleanup helper's module home and signature;
  the `BotConfig.panel_channel_id` validator details; the precise `setup_hook`
  wiring mechanics (D-13); exact CRITICAL/ephemeral copy strings; whether the
  optional `on_ready` perm sanity-check is included.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **PANEL-01** (idempotent summon, exactly one,
  stray cleanup) + **PANEL-09** (persistent views survive restart); the Out of
  Scope table (single-operator boundary, no new messages, no new deps/intents,
  no slash migration).
- `.planning/ROADMAP.md` §"Phase 18" — goal + 4 success criteria + the
  Research-flag note (open design decision + MEDIUM-confidence perm set, both now
  resolved here). §"Phase 19/20" for what is deliberately deferred.

### Prior phase context (the panel this phase registers & summons)
- `.planning/phases/17-minimal-persistent-panel-core-wiring/17-CONTEXT.md` —
  the `PanelView` design: `timeout=None`, static `custom_id`s (`wb:cmd:<name>`,
  `wb:loc:select`), in-memory selected location + `locations[0]` default (D-03..
  D-05 there), the operator-guard `interaction_check`, the single-ack
  defer-then-edit + per-callback isolation envelope. D-08 here carries those
  forward.
- `.planning/phases/16-extract-shared-dispatch-spec/16-CONTEXT.md` /
  `16-PATTERNS.md` — the `dispatch_spec` seam + `interactive/` import-acyclicity
  discipline (a scan/lifecycle helper should follow it). NOTE: `!panel` does NOT
  route through `dispatch_spec` (D-07) — it is a lifecycle command.

### Existing code this phase modifies / mirrors
- `weatherbot/interactive/panel.py` — `PanelView`, `CmdButton`, `LocationSelect`;
  static `custom_id`s are the D-05 marker; the build-time layout guard. This is
  the view `add_view` registers and `!panel` posts/edits/reuses.
- `weatherbot/interactive/bot.py` — `build_client` (plain `discord.Client` +
  `@client.event on_ready`/`on_message`; where `setup_hook`/`add_view` lands,
  D-12/D-13), `build_on_message` (operator-gate ladder `!panel` reuses, D-07),
  `render_embed` (panel embed render), `BotThread`/`BotConfig` dep flow
  (`operator_id`/`holder`/`cache`/`daemon_state` already wired).
- `weatherbot/config/models.py` §`BotConfig` (line 357) — add `panel_channel_id`
  (D-04); `extra="forbid"`/fail-loud-at-load posture to mirror.
- `weatherbot/scheduler/daemon.py` (~line 1559–1597) — where the bot is
  constructed with `config.bot.operator_id`; the new channel id threads alongside.
- `weatherbot/config/loader.py` — `resolve_location(config, None) → locations[0]`
  (the D-08 default precedent).

### discord.py reality (verified during research, 2.7.1)
- Persistent views re-bind callbacks by `custom_id` via `Client.add_view` — no
  `message_id` needed for buttons to survive restart (the basis for D-01).
- `channel.pins()` is an async iterator in discord.py 2.6+ (awaited form
  deprecated); Discord caps pins at 50 (D-03 scan is trivial).
- `Permissions.pin_messages` exists in 2.7+ (Discord split `PIN_MESSAGES` from
  `MANAGE_MESSAGES`, effective 2026-01-12) — preflight `pin_messages`, not
  `manage_messages` (D-10).
- `channel.permissions_for(guild.me) -> discord.Permissions` for the eager
  preflight (D-09); `discord.Forbidden` (403) on a write is the backstop.

### Live UAT
- STATE.md → Pending Todos → "[Phase 18] Live persistent-view restart UAT on host
  `yahir-mint`" — deploy `panel.py` + `setup_hook` `add_view`, `sudo systemctl
  restart weatherbot`, tap every button + dropdown (no "interaction failed"),
  select→restart→tap (correct location or documented `locations[0]` default),
  re-`!panel` → exactly one panel. New module + `setup_hook` load only on next
  process start (config hot-reload does NOT load new code).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PanelView` (`interactive/panel.py`) — already persistent-ready
  (`timeout=None`, static `custom_id`s, build-time layout guard, empty-locations
  guard). This phase registers it (`add_view`) and posts/reuses it; the static
  `custom_id`s double as the D-05 stray-cleanup marker.
- `build_client` / `BotThread` (`interactive/bot.py`) — the four panel deps
  (`operator_id`, `holder`, `cache`, `daemon_state`) already flow in; no new
  constructor args needed for the view itself, only the new `panel_channel_id`.
- `BotConfig` (`config/models.py`) — extend with `panel_channel_id` following the
  existing `operator_id` pattern (single int, `[bot]` table, fail-loud).
- `render_embed` — renders the panel's result embeds; the summon posts the panel
  message with the view attached.
- `on_ready` missing-intent CRITICAL (`bot.py`) — the established "fail loud, not
  silently dead" precedent the permission-preflight CRITICAL (D-11) mirrors.

### Established Patterns
- **Operator-gate ladder** in `on_message` (`author.id != operator_id` drop) —
  `!panel` reuses it (D-07); the panel's component path is gated separately by
  `PanelView.interaction_check` (Phase 17).
- **`[bot]` keys read once at startup** — the restart-boundary debt
  `panel_channel_id` joins (D-04); document, don't try to hot-reload it.
- **`interactive/` import-acyclic discipline** — module-top light imports, heavy
  types under `TYPE_CHECKING` (mirror `dispatch.py`/`panel.py`).
- **Failure isolation** — the bot thread must never take down the scheduler; the
  `!panel` lifecycle path needs the same non-propagating discipline (full
  interaction-path re-proof is Phase 20, but don't regress it here).

### Integration Points
- `add_view(PanelView(...))` registered in `setup_hook` (D-12/D-13) — needs the
  panel deps available at construction (they already are via `build_client`).
- New `!panel` branch in the operator-gated `on_message` path (D-07) → scan
  `panel_channel_id` pins → preflight perms (D-09/D-10) → find-or-create-one +
  pin + delete strays (D-05/D-06).
- `BotConfig.panel_channel_id` threads from `config/models.py` through
  `daemon.py` (~1597) into the bot construction.

</code_context>

<specifics>
## Specific Ideas

- The user took the **recommended option in all four researched areas plus the
  startup-behavior follow-up**, yielding one coherent design: scan-by-`custom_id`
  (no persistence) + configured `panel_channel_id` + marker-strict reuse-in-place
  cleanup + hybrid permission preflight + passive boot. The four picks are
  mutually reinforcing (the scan needs the configured channel; the cleanup reuses
  the same `custom_id` marker the scan uses; the hybrid perm check guards every
  write in the summon sequence).
- **High-value research surprise, surfaced and accepted:** discord.py 2.7's
  `pin_messages`/`manage_messages` split (effective 2026-01-12) — the perm to
  preflight is `pin_messages`. Captured as D-10 so the planner can't regress to
  `manage_messages`.
- The user is deliberate-informed and asked for comparison tables before deciding
  (advisor mode) — every lock above traces to a presented table + rationale, not
  an inferred default.

</specifics>

<deferred>
## Deferred Ideas

- **Persist the panel `message_id` and/or selected location across restart** —
  explicitly rejected for this milestone (D-01/D-02/D-08). Revisit only if the
  panel ever moves to a busy/multi-user channel (then the hybrid persist+scan
  becomes worthwhile) — a v2 consideration, not a phase.
- **Active boot-reconcile** (ensure-one-pinned-panel at startup) — considered and
  rejected in favor of passive boot (D-12); a candidate if hands-off
  "always-there" durability is later wanted.
- **Forecast button + Weekday/Weekend × Detailed/Compact sub-tier** — Phase 19.
- **Briefing failure-isolation re-proof for the interaction/`!panel` path
  (PANEL-11), selected-location visual indicator (PANEL-12), emoji labels +
  "updated <time>" stamp (PANEL-13)** — Phase 20.
- **Hot-reloadable `[bot] panel_channel_id` / `operator_id`** — carry-forward
  restart-boundary tech debt (v1.1 audit); not addressed here.

None of the above were scope creep introduced this session — all are pre-existing
boundaries reaffirmed.

</deferred>

---

*Phase: 18-persistence-summon-lifecycle-restart-durability*
*Context gathered: 2026-06-26*
