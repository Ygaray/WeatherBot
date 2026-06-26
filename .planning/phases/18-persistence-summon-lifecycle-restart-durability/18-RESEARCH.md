# Phase 18: Persistence + Summon/Lifecycle (Restart Durability) - Research

**Researched:** 2026-06-26
**Domain:** discord.py persistent views (`add_view`/`setup_hook`), idempotent message find-or-create + pin lifecycle, channel-permission preflight
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

CONTEXT.md is exhaustive: all 13 design decisions (D-01..D-13) are **LOCKED**. This phase
has no genuinely-open design space left — the research job here is to **verify the
discord.py 2.7.1 technical claims those locks rest on** and hand the planner verified,
copy-paste-ready API facts. Every lock below has been confirmed against the *installed*
library source (the strongest possible source — it is the exact code that will run).

### Locked Decisions

- **D-01 — Find the panel by SCANNING `channel.pins()`, NO persisted `message_id`.**
  Identify by `author == bot.user` AND a static component `custom_id` marker; reuse first
  match, recreate if none. Discord is the single source of truth.
- **D-02 — NO new persisted state of any kind** (no JSON file, no SQLite table). Crosses
  the read-only-dispatch constraint and re-adds the stale-id problem.
- **D-03 — Scope the scan to pinned messages only** (`channel.pins()`), not channel
  history. Discord caps pins at 50; no pagination needed.
- **D-04 — Add `panel_channel_id: int` to `BotConfig` (`[bot]` table), beside
  `operator_id`.** Read once at startup (existing restart-boundary debt). Missing/bad
  channel at startup → log clearly, skip the channel path, do NOT crash the bot thread.
- **D-05 — Identity = `author == bot.user` AND a static `custom_id` marker** (presence of
  `wb:loc:select` / `wb:cmd:*` in `message.components`). Author-alone rejected (would risk
  deleting unrelated bot pins).
- **D-06 — Reuse the survivor in place** (`message.edit(embed=…, view=…)`), **delete** any
  *additional* bot-owned panels (delete, not unpin-only — an unpinned-but-live View still
  responds). Recreate only if scan finds none.
- **D-07 — `!panel` is a lifecycle/WRITE command, NOT a registry command.** It does NOT
  route through `dispatch_spec`. Handled in the operator-gated `on_message` path; it is the
  one panel surface allowed to post/pin/edit/delete.
- **D-08 — Selected location stays in-memory on `PanelView`, default `locations[0]`.**
  Persisting selection across restart is OUT OF SCOPE. SC#3 satisfied by existing behavior.
- **D-09 — HYBRID permission check:** eager `channel.permissions_for(guild.me)` preflight
  BEFORE posting, PLUS a per-action `discord.Forbidden` catch around each write.
- **D-10 — Exact preflight set:** `view_channel`, `send_messages`, `embed_links`,
  `read_message_history`, **`pin_messages`** (NOT `manage_messages` — see VERIFIED below).
- **D-11 — On missing perms:** log CRITICAL naming the missing perm, send operator an
  ephemeral naming the gap, then REFUSE to summon. Optional cheap `on_ready` sanity check.
- **D-12 — PASSIVE at boot:** `add_view` in `setup_hook` and nothing more. Full
  reconcile (find-or-create / re-pin / cleanup) runs ONLY on explicit `!panel`.
- **D-13 — Use `setup_hook`, NOT `on_ready`, for `add_view`** (`on_ready` re-fires on
  reconnect → duplicate registrations). Mechanics = Claude's discretion; registration MUST
  land in `setup_hook` and be idempotent across reconnects.

### Claude's Discretion

Exact `!panel` token/parse location + operator-gate reuse; the scan/cleanup helper's module
home and signature; the `panel_channel_id` validator details; the precise `setup_hook`
wiring mechanics (D-13 — **see "setup_hook wiring" finding: `@client.event` works**); exact
CRITICAL/ephemeral copy strings; whether the optional `on_ready` perm sanity-check is
included.

### Deferred Ideas (OUT OF SCOPE)

- Persisting panel `message_id` and/or selected location across restart (D-01/D-02/D-08).
- Active boot-reconcile (rejected in favor of passive boot, D-12).
- Forecast button + sub-tier (Phase 19); briefing-isolation re-proof / visual selection
  indicator / emoji labels / "updated" stamp (Phase 20).
- Hot-reloadable `[bot] panel_channel_id` / `operator_id` (carry-forward restart-boundary
  debt).
- Per-user/multi-user panel state, config-editing-via-panel, new-message-per-result,
  modals, auto-refresh, new deps/intents, `commands.Bot`/slash migration (milestone OOS).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **PANEL-01** | Operator can summon a pinned control-panel message; summon is idempotent — exactly one panel, stray panels cleaned up | `channel.pins()` async-iterator scan (≤50 cap) + `author == bot.user`/`custom_id` marker match (D-05) + `message.edit` reuse / `message.delete` extras (D-06) + eager `permissions_for` preflight (D-09/D-10) — all VERIFIED in discord.py 2.7.1 below |
| **PANEL-09** | The pinned panel's buttons keep working after a bot restart/deploy (persistent views — `timeout=None`, stable `custom_id`s, re-registered on startup) | `Client.add_view(view)` re-binds callbacks by `custom_id` with NO `message_id` needed (VERIFIED: `message_id` param is optional, only used to propagate message-update events); `PanelView` already `is_persistent()` (timeout=None + all custom_id'd); registered in `setup_hook` (not `on_ready`) so reconnect can't duplicate |
</phase_requirements>

## Summary

This phase is **verification-dominated, not exploration-dominated**: the user front-loaded an
unusually complete discuss-phase, locking every decision (D-01..D-13) with rationale. The
research contribution is therefore to **confirm — against the actually-installed discord.py
2.7.1 source** — the five load-bearing API facts those locks depend on, so the planner can
write tasks with verified call signatures and no MEDIUM-confidence guesses.

All five checked out at HIGH confidence: (1) `Client.add_view(view, *, message_id=None)` —
`message_id` is **optional** and used only to refresh view state on message-update events, so
buttons survive a restart purely by `custom_id` (the basis for D-01); the call is **fully
local** (no network/await) so it's safe in `setup_hook`. (2) `TextChannel.pins()` returns an
**async iterator** (`_PinsIterator`), `limit=50` default, the old awaitable form deprecated —
consumed with `async for message in channel.pins():` (D-03). (3) `Permissions.pin_messages`
exists with `.. versionadded:: 2.7` — proving it is the **new split bit**; `Message.pin()`'s
own docstring says "You must have `pin_messages`" — so preflight `pin_messages`, **not**
`manage_messages` (D-10). (4) `channel.permissions_for(guild.me) -> Permissions` and
`discord.Forbidden` (a `HTTPException`, status 403) back the hybrid check (D-09). (5) The
existing `@client.event` decorator **can register `setup_hook`** (it just `setattr`s by
coroutine name) — so D-13 needs **no subclassing of `discord.Client`**; the plain-Client +
decorator shape of `build_client` is preserved.

**Primary recommendation:** Implement exactly as locked. Register `PanelView` via
`add_view` inside a `setup_hook` registered with the existing `@client.event` decorator (no
subclass). Build the `!panel` summon as a new operator-gated `on_message` branch that:
preflights `permissions_for` (D-10 set incl. `pin_messages`), `async for`-scans
`channel.pins()` for `author == bot.user` + a `wb:`-marker `custom_id`, edits-in-place the
first match (or posts+pins a fresh one), deletes extras, and wraps every write in
`try/except discord.Forbidden` → CRITICAL. No new deps, no new state, no `message_id` persisted.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Persistent-view re-bind after restart (`add_view`) | Bot gateway / `setup_hook` | — | discord.py re-binds component callbacks by `custom_id` at process start; belongs in the client lifecycle hook, not the message handler |
| `!panel` summon (find-or-create-one, pin, cleanup) | Bot gateway / operator `on_message` branch | Discord API (pins/edit/delete writes) | A lifecycle WRITE command (D-07); explicitly off the read-only `dispatch_spec` seam |
| Panel-find / stray-identity | Discord API (`channel.pins()` is server state) | Bot (marker match) | Discord is the single source of truth (D-01); no local persistence tier involved (D-02) |
| Permission preflight + `Forbidden` backstop | Bot (`permissions_for`) | Discord API (403 on write) | Eager local check prevents partial state; per-write catch closes the TOCTOU gap (D-09) |
| Selected-location default-on-restart | Bot (in-memory `PanelView` attr) | Config (`locations[0]` via `resolve_location`) | No persistence by design (D-08); a freshly-constructed view reflects current config |
| `panel_channel_id` config | Config (`BotConfig` `[bot]` table) | — | Read once at startup; the known channel id the scan needs (D-04) |

## Standard Stack

No new dependencies. This phase is 100% inside the already-pinned `discord.py>=2.7.1,<3`
plus the existing `structlog` / `pydantic` stack. The milestone's hard constraint is **zero
new deps / intents** (REQUIREMENTS.md Out of Scope).

### Core (already installed — versions VERIFIED on host 2026-06-26)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | **2.7.1** (`uv pip show` confirmed in `.venv`) | Persistent views (`add_view`/`setup_hook`), pins scan, permission model, write methods | The pinned gateway lib; all APIs this phase needs exist in 2.7.x `[VERIFIED: installed source]` |
| structlog | 26.x | CRITICAL log on missing perm (mirrors `on_ready` missing-intent precedent in `bot.py:336`) | Established project logging `[VERIFIED: codebase grep]` |
| pydantic | 2.13.x | `BotConfig.panel_channel_id: int` field (frozen, `extra="forbid"`) | Existing config model framework `[VERIFIED: codebase grep]` |

### Supporting (stdlib / existing — no install)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.0.3 (host) | Gateway-free callback/scan tests via `fake_*` mock factories | Wave-0 RED scaffold + GREEN, mirroring `test_panel.py`/`test_bot.py` `[VERIFIED: host]` |
| ruff | 0.15.16 (host) | Lint + format gate | Existing dev tool `[VERIFIED: host]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `@client.event` to register `setup_hook` | Subclass `discord.Client` + override `setup_hook` | Both work `[VERIFIED]`; the decorator preserves the existing plain-`Client` `build_client` shape with the least diff — recommended, but D-13 explicitly leaves mechanics to Claude's discretion |
| Scan `channel.pins()` | Persist `message_id` (JSON/SQLite) | Rejected by D-01/D-02 — adds a stale-id (404) failure class and crosses the read-only constraint |
| `discord.Forbidden` per-write catch + eager preflight | Attempt-and-catch only | Rejected by D-09 — a mid-sequence 403 leaves a posted-but-unpinned orphan (the SC#4 silent-partial-failure trap) |

**Installation:** None. (`discord.py>=2.7.1,<3` already in `pyproject.toml`.)

**Version verification (run on host 2026-06-26):**
```
uv pip show discord-py        # Version: 2.7.1  ✓
.venv/bin/python -c "import discord; print(discord.__version__)"  # 2.7.1  ✓
```

## Package Legitimacy Audit

> No external packages are installed in this phase. The package legitimacy gate is N/A.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| discord.py | PyPI (already pinned, already installed) | mature (8+ yrs) | very high | github.com/Rapptz/discord.py | OK | Already a dependency — no new install |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
PROCESS START (BotThread, on its own loop)
    │
    ├─ build_client() constructs discord.Client(intents)
    │     └─ @client.event setup_hook():            ◄── D-12/D-13 (PASSIVE boot)
    │           add_view(PanelView(holder, operator_id, cache, daemon_state))
    │           (local registration only — re-binds custom_id → callbacks;
    │            NO scan, NO network, NO message_id)        ──► PANEL-09 SC#1
    │
    └─ gateway connects → on_ready (optional cheap perm sanity log, D-11)

─────────────────────────────────────────────────────────────────────────────

OPERATOR TYPES "!panel"  (the ONE active reconcile trigger)
    │
on_message guard ladder ── author.bot? ─yes─► drop
    │ no
    ├─ author.id != operator_id? ─yes─► silent drop
    │ no
    ├─ content == "!panel"? ─yes─► [LIFECYCLE BRANCH, D-07 — NOT dispatch_spec]
    │                                   │
    │   resolve channel = guild.get_channel(config.bot.panel_channel_id)  (D-04)
    │     └─ None / inaccessible ─► log clear msg, abort (don't crash)
    │                                   │
    │   perms = channel.permissions_for(guild.me)          ◄── D-09 EAGER preflight
    │     └─ missing any of {view_channel, send_messages, embed_links,
    │         read_message_history, pin_messages}  ─► CRITICAL log + ephemeral
    │                                                    to operator + REFUSE   ──► SC#4
    │                                   │ all present
    │   SCAN:  async for m in channel.pins():             ◄── D-03 (≤50, async iter)
    │            keep m where m.author == bot.user
    │              AND any child.custom_id startswith "wb:"   ◄── D-05 marker
    │                                   │
    │   ┌──── matches == 0 ──► post fresh PanelView msg → m.pin()  (recreate)
    │   ├──── matches >= 1 ──► reuse matches[0]: m.edit(embed=…, view=PanelView)
    │   │                       (keeps pin position; live via add_view)  ──► D-06
    │   │                       then m.delete() for matches[1:]  (strays)
    │   │                                                          ──► PANEL-01 "exactly one"
    │   every write (post/pin/edit/delete) wrapped:
    │       try: … except discord.Forbidden: log CRITICAL (TOCTOU backstop, D-09)
    │   whole branch wrapped in non-propagating try/except (failure isolation)
    │
    └─ else ─► existing registry dispatch (unchanged)
```

### Recommended Project Structure
```
weatherbot/interactive/
├── bot.py        # build_client: add setup_hook(@client.event) → add_view; new !panel branch in on_message
├── panel.py      # PanelView (UNCHANGED for view itself); may host the wb: marker constant + the scan/summon helper
└── (summon helper) # Claude's discretion: a module-level async helper(channel, bot_user, view_factory) in bot.py or panel.py
weatherbot/config/
└── models.py     # BotConfig: add panel_channel_id: int  (line ~378, beside operator_id)
weatherbot/scheduler/
└── daemon.py     # ~line 1594: thread config.bot.panel_channel_id into BotThread/build_client
```

### Pattern 1: Persistent-view registration in `setup_hook` (via the existing decorator)
**What:** Register `PanelView` once at process start so its `custom_id`'d components re-bind to
their callbacks after a restart, without any boot-time scan or `message_id`.
**When to use:** Once, in `setup_hook` (NOT `on_ready` — `on_ready` re-fires on every gateway
reconnect → duplicate `add_view` registrations).
**Example:**
```python
# Source: VERIFIED against installed discord.py 2.7.1 — @client.event sets the attr by
# coroutine name, so setup_hook registers WITHOUT subclassing discord.Client. add_view is
# a purely-local call (no network/await), safe before gateway connect.
def build_client(*, holder, operator_id, cache, panel_channel_id, daemon_state=None):
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def setup_hook() -> None:               # D-13: NOT on_ready
        # Construct a fresh PanelView reflecting current config (D-08), register it.
        client.add_view(PanelView(
            holder=holder, operator_id=operator_id, cache=cache, daemon_state=daemon_state,
        ))
        # idempotent across reconnects because setup_hook runs once per process,
        # unlike on_ready. (PanelView.is_persistent() == True: timeout=None + all custom_id'd.)
    ...
```

### Pattern 2: Idempotent pins scan (find-or-create-one, marker-strict)
**What:** Locate the bot-owned panel among the channel's pins; reuse one, delete extras.
**When to use:** Inside the `!panel` lifecycle branch only, after the perm preflight passes.
**Example:**
```python
# Source: VERIFIED — TextChannel.pins() in 2.7.1 returns _PinsIterator (async iterator),
# default limit=50, yields discord.Message. Old awaited form is deprecated.
_PANEL_MARKER = "wb:"   # custom_ids are wb:loc:select / wb:cmd:<name> (D-05)

def _is_owned_panel(msg: "discord.Message", bot_user: "discord.ClientUser") -> bool:
    if msg.author != bot_user:                    # author check
        return False
    for row in msg.components:                     # static custom_id marker (unforgeable)
        for child in getattr(row, "children", []):
            cid = getattr(child, "custom_id", None)
            if cid and cid.startswith(_PANEL_MARKER):
                return True
    return False

async def _scan_panels(channel, bot_user):
    return [m async for m in channel.pins() if _is_owned_panel(m, bot_user)]  # ≤50 cap
```

### Pattern 3: Hybrid permission preflight + per-write Forbidden backstop (D-09/D-10)
```python
# Source: VERIFIED — channel.permissions_for(member) -> discord.Permissions;
# Permissions.pin_messages (versionadded 2.7) is the NEW split bit, NOT manage_messages;
# discord.Forbidden is an HTTPException (status 403) raised by a denied write.
_REQUIRED = ("view_channel", "send_messages", "embed_links",
             "read_message_history", "pin_messages")   # D-10 — pin_messages, NOT manage_messages

def _missing_perms(channel, me) -> list[str]:
    perms = channel.permissions_for(me)
    return [name for name in _REQUIRED if not getattr(perms, name)]

# at summon:
missing = _missing_perms(channel, channel.guild.me)
if missing:
    _log.critical("panel summon blocked — missing channel permission(s)", missing=missing,
                  channel_id=channel.id)
    await message.channel.send(f"Cannot summon panel: missing {', '.join(missing)}.")
    return                                            # REFUSE (D-11) — no half-broken panel
# every subsequent write:
try:
    await panel_msg.pin()
except discord.Forbidden:                             # TOCTOU: perm revoked after preflight
    _log.critical("panel pin forbidden (403) despite preflight", channel_id=channel.id)
    return
```

### Anti-Patterns to Avoid
- **`add_view` in `on_ready`:** re-fires on every reconnect → duplicate persistent-view
  registrations (D-13). Use `setup_hook`.
- **Persisting `message_id`:** adds a stale/deleted-id (404) failure class that forces a scan
  fallback anyway — so you'd carry both code paths (D-01/D-02).
- **Preflighting `manage_messages` for pinning:** would falsely PASS on a server that granted
  only the new "Pin Messages" permission (Discord split `PIN_MESSAGES` out of
  `MANAGE_MESSAGES` effective 2026-01-12). Preflight `pin_messages` (D-10).
- **Unpin-only stray cleanup:** an unpinned-but-still-live View keeps responding to clicks —
  `delete()` the extras, don't merely unpin (D-06).
- **Routing `!panel` through `dispatch_spec`:** it is a WRITE/lifecycle command and must stay
  off the read-only registry seam (D-07).
- **Awaiting `channel.pins()`** (the pre-2.6 form): deprecated; use `async for` (D-03).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Re-bind buttons after restart | A `message_id` store + on-startup `fetch_message` + manual re-attach | `client.add_view(view)` in `setup_hook` | discord.py re-binds by `custom_id` automatically; `message_id` is optional and only for update events `[VERIFIED]` |
| Permission check | Manual bitmask math on `channel.overwrites` | `channel.permissions_for(guild.me)` → attribute reads | Library resolves role + overwrite precedence correctly `[VERIFIED]` |
| Listing pinned messages | History pagination / `channel.history` filtering | `channel.pins()` async iterator (≤50) | Purpose-built, capped at 50, no pagination `[VERIFIED]` |
| Detecting a denied write | Pre-checking every perm before every call only | `try/except discord.Forbidden` around the write | Closes the TOCTOU gap the eager check can't (D-09) `[VERIFIED]` |

**Key insight:** discord.py already solves persistence-by-`custom_id`, permission resolution,
and pin listing. The entire phase is *orchestration* of existing primitives — the only new
artifacts are one config field, one `setup_hook` line, and one `on_message` branch.

## Runtime State Inventory

> This is a **feature-add** phase, not a rename/refactor. But it touches startup wiring and a
> config schema, so the relevant runtime-state questions are answered explicitly below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** — D-02 forbids any new persisted state (no JSON, no SQLite `panel` table). The pinned panel message lives **server-side in Discord** and is found by scan (D-01), not stored locally. | None |
| Live service config | **The pinned panel message itself is live Discord state** that survives a process restart (the basis for the scan). On host `yahir-mint`, an already-pinned Phase-17-era panel may exist — the live UAT must confirm `add_view` re-binds it (SC#1) and `!panel` reconciles to exactly one (SC#2). | Live UAT on `yahir-mint` (deploy + `systemctl restart`) |
| OS-registered state | **systemd unit `weatherbot`** on `yahir-mint` (`Restart=always`, editable install). New `panel.py`/`setup_hook` code + the new `panel_channel_id` config load **only on next process start** — config hot-reload does NOT load new modules. | `sudo systemctl restart weatherbot` after deploy (already a tracked Pending Todo) |
| Secrets/env vars | `panel_channel_id` is a **non-secret** channel id (like `operator_id`) → goes in `config.toml` `[bot]`, NOT `.env`. Bot token stays on `Settings.discord_bot_token`. No new secret. | Add `panel_channel_id` to the operator's `config.toml`; document it needs a restart |
| Build artifacts / installed packages | **None** — no new dependency, no version bump, no compiled artifact. `discord.py` 2.7.1 already installed. | None |

**The canonical restart question:** after deploy, the new `setup_hook`/`!panel` code and the
new `[bot] panel_channel_id` are inert until `systemctl restart weatherbot`. This is the
already-accepted restart-boundary debt (D-04) — document it; it is not a new *kind* of debt.

## Common Pitfalls

### Pitfall 1: `add_view` in `on_ready` → duplicate registrations
**What goes wrong:** Each gateway reconnect re-fires `on_ready`, calling `add_view` again →
multiple registrations of the same persistent view.
**Why it happens:** `on_ready` is a reconnect event, not a one-time startup event.
**How to avoid:** Register in `setup_hook` (runs once per process). D-13. `[VERIFIED: setup_hook
exists and runs pre-connect; @client.event registers it]`
**Warning signs:** Doubled callback log lines after a network blip; growing memory.

### Pitfall 2: Preflighting `manage_messages` instead of `pin_messages`
**What goes wrong:** On a guild that granted only the new "Pin Messages" permission, a
`manage_messages` check **passes falsely**, then `message.pin()` raises `Forbidden` 403
mid-summon → an orphaned posted-but-unpinned message (the exact SC#4 failure).
**Why it happens:** Discord split `PIN_MESSAGES` out of `MANAGE_MESSAGES` effective
2026-01-12; discord.py 2.7 exposes the new bit as `Permissions.pin_messages`.
**How to avoid:** Preflight `pin_messages` (D-10). `[VERIFIED: Permissions.pin_messages has
".. versionadded:: 2.7"; Message.pin() docstring: "You must have pin_messages"]`
**Warning signs:** A `Forbidden` on `.pin()` despite a "passing" preflight.

### Pitfall 3: `await channel.pins()` (the deprecated form)
**What goes wrong:** In 2.6+, `pins()` returns an async **iterator**, not an awaitable list;
`await`ing it is deprecated and will eventually break.
**How to avoid:** `[m async for m in channel.pins()]` or `async for m in channel.pins():`.
`[VERIFIED: signature returns _PinsIterator; docstring shows the async-for usage; "deprecat"
appears in the doc]`
**Warning signs:** DeprecationWarning at the scan call.

### Pitfall 4: Unpin-only stray cleanup leaves live, clickable panels
**What goes wrong:** Unpinning an extra panel removes it from the scan set but leaves a live
View whose buttons still fire callbacks → "more than one working panel."
**How to avoid:** `message.delete()` the extras (D-06). `[VERIFIED: Message.delete exists]`

### Pitfall 5: Missing `panel_channel_id` / deleted channel crashes the bot thread
**What goes wrong:** Resolving a `None`/deleted channel and calling `.pins()` on it raises,
and (if unguarded) could kill the bot thread mid-summon.
**How to avoid:** Resolve `guild.get_channel(panel_channel_id)`; if `None`/inaccessible, log a
clear message and abort the summon — mirror the existing fail-loud-not-silently-dead posture
(D-04). The whole `!panel` branch also rides the existing non-propagating `on_message`
envelope so nothing reaches the scheduler thread.

### Pitfall 6: Forgetting the failure-isolation envelope on the new write branch
**What goes wrong:** A write that raises something other than `Forbidden` (e.g. a transient
`HTTPException`) could propagate out of `on_message`.
**How to avoid:** The existing `on_message` body is already wrapped in a non-propagating
`try/except Exception` (`bot.py:298`). Place the `!panel` branch INSIDE that same envelope
(do not add a second one); the per-write `Forbidden` catch is the precise inner case. Full
interaction-path isolation re-proof is Phase 20 — but don't regress it here.

## Code Examples

### Resolving the configured panel channel safely (D-04)
```python
# Source: discord.py 2.7.1 — guild.get_channel returns None for an unknown/inaccessible id.
guild = message.guild
channel = guild.get_channel(config.bot.panel_channel_id) if guild else None
if channel is None:
    _log.error("panel summon: panel_channel_id unset or channel inaccessible",
               panel_channel_id=getattr(config.bot, "panel_channel_id", None))
    await message.channel.send("Panel channel is not configured or is inaccessible.")
    return   # do NOT crash the bot thread (D-04)
```

### `BotConfig` field (mirror the existing `operator_id` pattern)
```python
# Source: weatherbot/config/models.py:357 — BotConfig (frozen, extra="forbid").
class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operator_id: int
    panel_channel_id: int        # D-04 — non-secret channel id, [bot] table, read once at startup
```

### Threading the id into the bot (daemon.py ~line 1594)
```python
# Source: weatherbot/scheduler/daemon.py:1594 — BotThread construction site.
bot = BotThread(
    settings.discord_bot_token,
    holder=holder,
    operator_id=config.bot.operator_id,
    panel_channel_id=config.bot.panel_channel_id,   # NEW — threads through to build_client/setup_hook
    cache=cache,
    daemon_state=daemon_state,
)
```

### Selected-location default-on-restart (D-08 — already satisfied)
```python
# Source: weatherbot/config/loader.py:40 resolve_location(config, None) -> locations[0];
# weatherbot/interactive/panel.py:193 self._selected_location = locations[0].
# A freshly-constructed PanelView (built at add_view time) defaults to locations[0],
# reflecting current config. This phase adds NOTHING here beyond that confirmation.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `MANAGE_MESSAGES` covers pinning | Separate `PIN_MESSAGES` permission (`Permissions.pin_messages`) | Discord 2026-01-12; discord.py 2.7 | Preflight `pin_messages`, not `manage_messages` (D-10) — else false-pass + orphan |
| `await channel.pins()` → `List[Message]` | `async for m in channel.pins()` (async iterator, limit=50) | discord.py 2.6 | Old awaited form deprecated; use async iteration (D-03) |
| Persist `message_id` to rebind views | `add_view` rebinds by `custom_id`; `message_id` optional | discord.py 2.0+ | No store needed (D-01); `message_id` only refreshes view state on update events |

**Deprecated/outdated:**
- Awaiting `channel.pins()` — deprecated in favor of async iteration `[VERIFIED]`.
- Checking `manage_messages` for pin capability — stale post-2026-01-12 `[VERIFIED]`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | An already-pinned Phase-17-era panel exists in the configured channel on `yahir-mint` (so SC#1 "buttons still work after restart" is testable against a real pre-existing panel) | Runtime State Inventory | LOW — if none exists, the operator simply runs `!panel` once to create it, then restarts to test SC#1; the UAT still validates the path |
| A2 | The Discord `PIN_MESSAGES`/`MANAGE_MESSAGES` split is in effect on the operator's guild (a 2026-01-12 platform change) | Pitfall 2 / D-10 | LOW — preflighting `pin_messages` is correct on the split; on an un-split guild the bit still resolves. The CONTEXT.md already locked this as D-10 from prior research |
| A3 | `message.components` exposes child components with `.custom_id` for the marker scan (D-05) on messages returned by `pins()` | Pattern 2 | LOW — discord.py populates `Message.components` from gateway payloads; the helper defensively `getattr`s `children`/`custom_id`. Planner should add a test asserting the marker match against a fake pinned message |

**Note:** A2 and the `pin_messages`/`manage_messages` split were independently **VERIFIED**
against the installed library (`Permissions.pin_messages` has `versionadded:: 2.7`). A2's
residual risk is only about the *server-side platform rollout date*, not the library API.

## Open Questions (RESOLVED)

1. **Does `Message.components` reliably carry `.custom_id` children for the D-05 marker scan?**
   - **RESOLVED:** Closed by 18-01 Task 3 — the defensive `getattr(row, "children", [])` /
     `getattr(child, "custom_id", None)` matcher plus positive (`wb:cmd:weather` child) and
     negative (no `wb:` marker) gateway-free unit tests are incorporated into the plan's
     action + behavior + acceptance criteria. No execution dependency on the exact nesting.
   - What we know: discord.py builds `Message.components` from the gateway message payload;
     persistent components carry their `custom_id`. `[VERIFIED: Message.components exists]`
   - What's unclear: the exact nesting (ActionRow → children) the planner's matcher must walk
     can vary slightly by component type.
   - Recommendation: write the matcher defensively (`getattr(row, "children", [])`, then
     `getattr(child, "custom_id", None)`) as shown in Pattern 2, and add a gateway-free unit
     test that feeds a fake pinned `Message` with a `wb:cmd:weather` child and asserts a match
     (and a non-match for a bot message with no `wb:` marker). This is cheap insurance.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| discord.py | persistent views, pins scan, permission model | ✓ | 2.7.1 (`.venv`, `uv pip show`) | — |
| Python | runtime | ✓ | 3.12 (`.venv`) | — |
| pytest | gateway-free tests | ✓ | 9.0.3 | — |
| ruff | lint/format gate | ✓ | 0.15.16 | — |
| host `yahir-mint` + systemd `weatherbot` | live restart UAT (SC#1–SC#4) | ✓ (live production service per MEMORY) | — | deploy + `sudo systemctl restart weatherbot` |
| Discord guild with a configured panel channel + bot in it | live UAT | assumed ✓ (operator's private server) | — | operator configures `panel_channel_id`; restart |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none blocking — the live UAT requires a deploy +
restart on `yahir-mint` (an accepted, tracked obligation, not a blocker for planning/building).

## Validation Architecture

> `workflow.nyquist_validation` not explicitly false → section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (`[tool.pytest.ini_options]`, `testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| Config file | `pyproject.toml` |
| Quick run command | `.venv/bin/python -m pytest tests/test_panel.py tests/test_bot.py -q` |
| Full suite command | `.venv/bin/python -m pytest -q` (600 tests collected baseline, 2026-06-26) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PANEL-09 | `setup_hook` registers `add_view(PanelView)`; NOT in `on_ready`; idempotent | unit (gateway-free) | `.venv/bin/python -m pytest tests/test_bot.py -k setup_hook -x` | ❌ Wave 0 |
| PANEL-09 | A freshly-built `PanelView.is_persistent()` is True (timeout=None + all custom_id'd) — guards against a regression breaking re-bind | unit | `.venv/bin/python -m pytest tests/test_panel.py -k persistent -x` | ⚠️ partial (D-10 layout test exists; add `is_persistent`) |
| PANEL-01 | scan helper: matches `author==bot.user` + `wb:` marker; ignores bot msg w/o marker | unit | `.venv/bin/python -m pytest tests/test_panel.py -k scan -x` | ❌ Wave 0 |
| PANEL-01 | summon: 0 matches → post+pin; ≥1 → edit first + delete extras (exactly one) | unit (mocked channel/pins/edit/delete/pin AsyncMocks) | `.venv/bin/python -m pytest tests/test_bot.py -k panel_summon -x` | ❌ Wave 0 |
| PANEL-01 | preflight: missing `pin_messages` (or any D-10 perm) → CRITICAL + ephemeral + REFUSE (no post) | unit | `.venv/bin/python -m pytest tests/test_bot.py -k panel_perms -x` | ❌ Wave 0 |
| PANEL-01 | per-write `Forbidden` → CRITICAL, no propagation (TOCTOU) | unit | `.venv/bin/python -m pytest tests/test_bot.py -k panel_forbidden -x` | ❌ Wave 0 |
| PANEL-01 | unset/inaccessible `panel_channel_id` → clear log + abort, bot thread survives | unit | `.venv/bin/python -m pytest tests/test_bot.py -k panel_channel_missing -x` | ❌ Wave 0 |
| PANEL-09 SC#1 / PANEL-01 SC#2 | live: restart → buttons still route; re-`!panel` → exactly one | manual-only (live host) | `sudo systemctl restart weatherbot` then tap every button/dropdown; re-`!panel` | manual UAT (`yahir-mint`) |
| BotConfig | `panel_channel_id` required int; unknown `[bot]` key fails loud (`extra="forbid"`) | unit | `.venv/bin/python -m pytest tests/test_config.py tests/test_models.py -k panel_channel -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_panel.py tests/test_bot.py tests/test_config.py -q`
- **Per wave merge:** `.venv/bin/python -m pytest -q`
- **Phase gate:** Full suite green, then the live `systemctl restart` UAT on `yahir-mint`
  before `/gsd-verify-work 18`.

### Wave 0 Gaps
- [ ] `tests/test_bot.py` — new node IDs: `setup_hook` registers `add_view` (not `on_ready`);
  `!panel` summon find-or-create-one + delete-extras; perm preflight refuse; `Forbidden`
  backstop; missing/inaccessible channel abort-not-crash. Mock `channel.pins()` as an async
  iterator, `message.edit/pin/delete` as `AsyncMock`, `permissions_for` returning a
  `Permissions`-shaped object. Mirror `test_bot.py`'s `_patch_command_in_registry` +
  `fake_discord_message` patterns.
- [ ] `tests/test_panel.py` — `PanelView.is_persistent()` True; the `_is_owned_panel` marker
  matcher (positive + negative). Mirror the existing deferred-import `_panel()` pattern.
- [ ] `tests/test_config.py` / `tests/test_models.py` — `panel_channel_id` required-int +
  `extra="forbid"` fail-loud, mirroring the existing `operator_id` tests.
- [ ] Async-iterator test helper: a small fake yielding `Message`-shaped mocks for `pins()`
  (none exists yet — add to `conftest.py` or the test module).
- Framework install: none needed (pytest/ruff present).

## Security Domain

> `security_enforcement` not explicitly false → section included. This is a single-operator
> personal bot with no untrusted input surface beyond the operator gate; scope is narrow.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | Failure isolation: the `!panel` write branch must not propagate into the scheduler thread (existing non-propagating `on_message` envelope) |
| V2 Authentication | no | No new auth surface; operator identity via Discord user id |
| V4 Access Control | yes | **Operator gate** — `!panel` reuses the `author.id == operator_id` ladder (D-07); the panel's component path is gated by `PanelView.interaction_check` (Phase 17, unchanged here) |
| V5 Input Validation | minimal | `!panel` takes no args; `panel_channel_id` validated as `int` by pydantic at load (`extra="forbid"`) |
| V6 Cryptography | no | No secrets handled in this phase; `panel_channel_id` is a non-secret id, bot token unchanged on `Settings` |
| V7 Error Handling / Logging | yes | CRITICAL on missing perm / `Forbidden`; no token/id leaked in logs or operator-facing copy (mirror the existing identity-free reject discipline) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Non-operator summons/cleans up the panel | Elevation of Privilege | `author.id != operator_id` drop in the `on_message` ladder (D-07) — `!panel` never reaches a non-operator |
| Deleting an unrelated bot-owned pin (over-broad cleanup) | Tampering | Marker-strict identity: `author == bot.user` AND a `wb:` `custom_id` (D-05), never author-alone |
| Perm revoked between preflight and write → orphan message | Denial of Service / partial-state | Eager preflight + per-write `discord.Forbidden` catch (D-09) — refuse rather than orphan |
| Token / channel id leaking into a log or operator message | Information Disclosure | Log structured fields (channel_id is non-secret) but never the token; reuse identity-free copy discipline |
| A raising write crashing the bot thread / scheduler | Denial of Service | Non-propagating `on_message` envelope + abort-not-crash on bad channel (D-04) |

## Sources

### Primary (HIGH confidence)
- **Installed `discord.py` 2.7.1 source** (`.venv/lib/python3.12/site-packages/discord/`) —
  introspected `Client.add_view` (optional `message_id`, local-only), `Client.setup_hook`
  (exists, registrable via `@client.event`), `TextChannel.pins` (async iterator, limit=50,
  deprecation note, yields `Message`), `Permissions.pin_messages` (`versionadded:: 2.7`),
  `Message.pin/edit/delete/unpin/pinned`, `permissions_for`, `Forbidden` (HTTPException, 403).
  This is the exact code that will run on the host — the strongest possible source.
- **Codebase** (`weatherbot/interactive/bot.py`, `panel.py`, `config/models.py:357`,
  `scheduler/daemon.py:1594`, `config/loader.py:40`, `tests/test_panel.py`, `tests/test_bot.py`,
  `tests/conftest.py`) — existing patterns, integration points, test harness shape.
- **18-CONTEXT.md** — the 13 locked decisions and their rationale (prior discuss-phase research).

### Secondary (MEDIUM confidence)
- The Discord `PIN_MESSAGES`/`MANAGE_MESSAGES` split *rollout date* (2026-01-12) — carried
  from CONTEXT.md's prior research; the *library API* for it is VERIFIED HIGH above.

### Tertiary (LOW confidence)
- None. No external WebSearch/Context7 provider was available this session
  (`brave_search`/`firecrawl`/`exa_search` all false); the installed-source introspection
  fully covered every load-bearing claim, so no claim rests on un-cross-checked web content.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; `discord.py 2.7.1` confirmed installed.
- Architecture / API facts: HIGH — every load-bearing call verified against installed source.
- Pitfalls: HIGH — each pitfall maps to a VERIFIED API fact (deprecated `pins()`, the
  `pin_messages` split, `on_ready` reconnect duplication).
- Permission split (server-side rollout date only): MEDIUM — library API HIGH, platform date
  carried from prior research.

**Research date:** 2026-06-26
**Valid until:** 2026-07-26 (stable — pinned `discord.py<3`; revisit only on a discord.py bump).
