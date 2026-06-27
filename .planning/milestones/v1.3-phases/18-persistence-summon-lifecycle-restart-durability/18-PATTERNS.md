# Phase 18: Persistence + Summon/Lifecycle (Restart Durability) - Pattern Map

**Mapped:** 2026-06-26
**Files analyzed:** 5 (1 created, 4 modified)
**Analogs found:** 5 / 5 (all in-repo, exact or strong role-matches)

> This phase is orchestration of existing discord.py primitives plus one config field,
> one `setup_hook` line, and one `on_message` branch. Every new artifact has a direct
> in-repo analog — there is no "no analog" tier. All 13 design decisions (D-01..D-13)
> are LOCKED in CONTEXT.md; this map cites the exact lines the planner/executor copies.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/interactive/bot.py` (MOD) — add `setup_hook`+`add_view`; add `!panel` summon branch; thread `panel_channel_id` | gateway client / message handler | event-driven (gateway) + request-response (write/pin/edit/delete) | itself (`build_client`/`build_on_message`/`render_embed`) | exact (in-place extension) |
| `weatherbot/interactive/panel.py` (MOD, optional) — host the `wb:` marker constant + scan/`_is_owned_panel` helper | component / utility | transform (message→bool match) | `panel.py` `CmdButton`/`LocationSelect` `custom_id`s + `_assert_layout` getattr-walk | exact (same module, same component model) |
| `weatherbot/config/models.py` (MOD) — add `panel_channel_id: int` to `BotConfig` | model / config | CRUD (load-time validate) | `BotConfig.operator_id` (`models.py:357-378`) | exact (sibling field, same table) |
| `weatherbot/scheduler/daemon.py` (MOD) — thread `panel_channel_id` into `BotThread` | wiring / config flow | request-response (construction) | the `BotThread(...)` construction block (`daemon.py:1594-1600`) | exact (same call site) |
| `tests/test_bot.py` / `tests/test_panel.py` / `tests/test_config.py` (MOD) — Wave-0 RED for setup_hook, summon, perms, Forbidden, channel-missing, config field | test | event-driven + CRUD assertions | `_make_fake_discord_message`/`_make_fake_interaction` (conftest) + `_patch_command_in_registry` | role-match (new async-iterator + Permissions mocks needed) |

---

## Pattern Assignments

### `weatherbot/interactive/bot.py` — `setup_hook` + `add_view` registration (PANEL-09, D-12/D-13)

**Analog:** `build_client` in the SAME file, `bot.py:308-347`.

**Imports pattern** (`bot.py:36-55`) — `from __future__`, light module-top imports, heavy types under `TYPE_CHECKING`. The new code adds a `PanelView` import. Because `panel.py` already imports `render_embed` FROM `bot.py` (`panel.py:53`), importing `PanelView` at `bot.py` module top would create a cycle — import `PanelView` **inside** `build_client`/`setup_hook` (deferred), or accept it as a constructor parameter. This acyclicity constraint is load-bearing (CONTEXT "interactive/ import-acyclic discipline").

**Existing handler-registration shape to mirror** (`bot.py:333-345`) — the decorator pattern `@client.event async def on_ready()`. RESEARCH VERIFIED `@client.event` registers `setup_hook` by coroutine name with NO subclassing (D-13):
```python
client = discord.Client(intents=intents)

@client.event
async def on_ready() -> None:
    if not client.intents.message_content:
        _log.critical("message_content intent missing — ...")   # ← the D-11 CRITICAL precedent
    else:
        _log.info("inbound bot ready", user=str(client.user))
```

**What to add** (D-12/D-13 — register, nothing more; idempotent across reconnects because `setup_hook` runs once per process, unlike `on_ready`):
```python
@client.event
async def setup_hook() -> None:                       # NOT on_ready (D-13)
    client.add_view(PanelView(holder=holder, operator_id=operator_id,
                              cache=cache, daemon_state=daemon_state))
    # add_view is purely-local (no network/await) → safe before gateway connect.
```
The four `PanelView` deps already flow into `build_client` (`bot.py:308-313`) — only the new `panel_channel_id` arg is added to the signature.

---

### `weatherbot/interactive/bot.py` — `!panel` summon branch (PANEL-01, D-07/D-09/D-10)

**Analog:** the `on_message` guard ladder + non-propagating envelope, `bot.py:247-305`.

**Operator-gate ladder to reuse** (`bot.py:247-264`) — the `!panel` branch lives INSIDE this existing ladder (steps 1-3) and is dispatched BEFORE/beside the registry parse (D-07: it does NOT route through `dispatch_spec`):
```python
async def on_message(message: discord.Message) -> None:
    if message.author.bot:                 # (1)
        return
    if message.author.id != operator_id:   # (2) operator gate — !panel reuses this
        return
    content = message.content or ""
    if not content.startswith("!"):        # (3)
        return
    parsed = parse_command(content[1:])    # (4) registry — !panel branches BEFORE/around this
    ...
```

**Non-propagating envelope to reuse** (`bot.py:271-303`) — the `!panel` branch rides the SAME `try/except Exception` (do NOT add a second envelope; RESEARCH Pitfall 6). The per-write `discord.Forbidden` catch is the precise inner case:
```python
try:
    ...
except Exception:  # noqa: BLE001 — non-propagating handler (CMD-08, D-11)
    _log.exception("inbound handler failed")
    try:
        await message.channel.send(_ERROR_REPLY)
    except Exception:  # noqa: BLE001 — best-effort reply; never re-raise
        _log.exception("inbound error reply failed")
```

**Channel resolve + abort-not-crash** (D-04; RESEARCH "Resolving the configured panel channel safely"):
```python
guild = message.guild
channel = guild.get_channel(config.bot.panel_channel_id) if guild else None
if channel is None:
    _log.error("panel summon: panel_channel_id unset or channel inaccessible",
               panel_channel_id=getattr(config.bot, "panel_channel_id", None))
    await message.channel.send("Panel channel is not configured or is inaccessible.")
    return   # do NOT crash the bot thread (D-04)
```

**Permission preflight + per-write Forbidden backstop** (D-09/D-10; RESEARCH Pattern 3). ⚠️ `pin_messages`, NOT `manage_messages`:
```python
_REQUIRED = ("view_channel", "send_messages", "embed_links",
             "read_message_history", "pin_messages")   # D-10
perms = channel.permissions_for(channel.guild.me)
missing = [n for n in _REQUIRED if not getattr(perms, n)]
if missing:
    _log.critical("panel summon blocked — missing channel permission(s)",
                  missing=missing, channel_id=channel.id)
    await message.channel.send(f"Cannot summon panel: missing {', '.join(missing)}.")
    return                                              # REFUSE (D-11)
# every write wrapped:
try:
    await panel_msg.pin()
except discord.Forbidden:
    _log.critical("panel pin forbidden (403) despite preflight", channel_id=channel.id)
    return
```

**Find-or-create-one scan + cleanup** (D-03/D-05/D-06; RESEARCH Pattern 2). Async iterator (`async for`), NOT `await channel.pins()`:
```python
matches = [m async for m in channel.pins() if _is_owned_panel(m, client.user)]  # ≤50
if not matches:                                  # recreate
    msg = await channel.send(embed=render_embed(...), view=PanelView(...))
    await msg.pin()
else:                                            # reuse survivor in place (keeps pin position)
    await matches[0].edit(embed=render_embed(...), view=PanelView(...))
    for extra in matches[1:]:
        await extra.delete()                     # DELETE strays, not unpin (D-06)
```

**Embed render reuse** (`render_embed`, `bot.py:124-191`) — the summon posts/edits with `render_embed(reply)`; `PanelView` already attaches via `add_view`.

---

### `weatherbot/interactive/panel.py` — `_is_owned_panel` marker matcher + `wb:` constant (D-05)

**Analog:** the `custom_id` definitions + the `_assert_layout` defensive `getattr` walk, SAME file.

**The marker the scan keys on already exists** (`panel.py:117` and `panel.py:142`):
```python
custom_id=f"wb:cmd:{name}",     # CmdButton — wb:cmd:weather, wb:cmd:uv, ...
custom_id="wb:loc:select",      # LocationSelect
```
So the D-05 marker constant is `_PANEL_MARKER = "wb:"`.

**Defensive component-walk pattern to mirror** (`panel.py:222-231`, `_assert_layout` uses `getattr(child, "custom_id", None)`) — the matcher walks `message.components` rows→children with the same `getattr` defensiveness (RESEARCH Open Q1 / A3):
```python
def _is_owned_panel(msg, bot_user) -> bool:
    if msg.author != bot_user:                          # author check (D-05)
        return False
    for row in msg.components:
        for child in getattr(row, "children", []):
            cid = getattr(child, "custom_id", None)
            if cid and cid.startswith("wb:"):           # unforgeable bot-owned marker
                return True
    return False
```

**`PanelView` persistence is already satisfied** (`panel.py:172` `super().__init__(timeout=None)` + all-`custom_id`'d children) — D-08 adds NOTHING here beyond confirming a freshly-built view defaults to `locations[0]` (`panel.py:193`, mirroring `resolve_location(config, None)` at `loader.py:52-53`). A new `is_persistent()` test is the only addition.

**Helper module home is Claude's discretion (D-13):** `panel.py` (co-located with the `wb:` ids it matches) or `bot.py` (co-located with the summon caller). Follow the same module-top-light / `TYPE_CHECKING` import discipline either way (`panel.py:44-60`).

---

### `weatherbot/config/models.py` — `BotConfig.panel_channel_id` (D-04)

**Analog:** `BotConfig.operator_id`, `models.py:357-378` (EXACT sibling).

**Pattern to copy** (`models.py:376-378`) — single `int`, `[bot]` table, frozen + `extra="forbid"` (an unknown `[bot]` key fails loud at load):
```python
class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operator_id: int
    panel_channel_id: int        # D-04 — non-secret channel id, [bot] table, read once at startup
```
`panel_channel_id` is a non-secret id like `operator_id` → `config.toml` `[bot]`, NOT `.env`. No `field_validator` is strictly required (a plain `int` mirrors `operator_id`); the loader already rejects unknown keys via `extra="forbid"`. The `[bot]` table itself stays optional on `Config` (`bot: BotConfig | None = None`, see `models.py:370-374`) — when present it now requires BOTH keys.

---

### `weatherbot/scheduler/daemon.py` — thread `panel_channel_id` into `BotThread` (D-04)

**Analog:** the `BotThread(...)` construction block, `daemon.py:1594-1600` (EXACT call site).

**Pattern to extend** (`daemon.py:1594-1600`, guarded by `if config.bot is not None and settings is not None:` at `daemon.py:1565`):
```python
bot = BotThread(
    settings.discord_bot_token,
    holder=holder,
    operator_id=config.bot.operator_id,
    panel_channel_id=config.bot.panel_channel_id,   # NEW — threads to build_client/setup_hook
    cache=cache,
    daemon_state=daemon_state,
)
```
`BotThread.__init__` (`bot.py:360-375`) forwards its kwargs into `build_client` — add `panel_channel_id` to BOTH signatures. The construction already rides a non-propagating `try/except` (`daemon.py:1603-1605`: "bot failure must NOT stop the briefing path"), so a missing-field crash here still can't take down the scheduler.

---

### Tests — Wave-0 RED (mirror existing gateway-free harness)

**Analog:** `tests/conftest.py` fixtures + `tests/test_bot.py:795` `_patch_command_in_registry`.

- **Message/Interaction stand-ins exist** — `_make_fake_discord_message` (`conftest.py:120-153`, `channel.send`=`AsyncMock`, `channel.typing()` async-CM) and `_make_fake_interaction` (`conftest.py:178-227`). Reuse `fake_discord_message` for the `!panel` author-gate + reply assertions.
- **New harness needed (none exists yet):** an async-iterator fake for `channel.pins()` yielding `Message`-shaped mocks; `channel.permissions_for` returning a `Permissions`-shaped object (attrs `view_channel`/`send_messages`/`embed_links`/`read_message_history`/`pin_messages`); `message.edit`/`pin`/`delete` as `AsyncMock`. Add to `conftest.py` or the test module (RESEARCH Wave-0 Gaps).
- **Assertion seam** (`test_bot.py:812-822` `_sent_text`) — reads positional-or-`content=` so reply-call shape isn't over-constrained; reuse for the CRITICAL/refuse-message assertions.
- **Config tests** mirror the existing `operator_id` required-int + `extra="forbid"` fail-loud cases in `test_config.py`/`test_models.py`.

---

## Shared Patterns

### Failure isolation (non-propagating envelope)
**Source:** `bot.py:271-303` (the `on_message` `try/except Exception` + best-effort error reply).
**Apply to:** the `!panel` branch (ride the SAME envelope — do not nest a second one; RESEARCH Pitfall 6), every Discord write inside it (per-write `discord.Forbidden` inner catch, D-09).
The discipline: a raising write logs and never re-raises into the bot thread / scheduler. Cross-reference the panel's own per-callback + `View.on_error` backstop (`panel.py:329-351`) — the same posture, different surface.

### Fail-loud CRITICAL on a startup/permission gap
**Source:** `bot.py:334-339` — the `on_ready` `message_content`-intent-missing CRITICAL ("fail loud, not silently dead", D-02).
**Apply to:** the D-11 missing-permission CRITICAL (name the missing perm) and the per-write `Forbidden` CRITICAL. Optionally an `on_ready` perm sanity log (D-11, Claude's discretion). Never leak the bot token; `channel_id` is a non-secret structured field (Security V7).

### Operator gate
**Source:** `bot.py:253` (`if message.author.id != operator_id: return`) for the `!panel` command path; `panel.py:233-267` (`PanelView.interaction_check`) for the component path (unchanged this phase).
**Apply to:** `!panel` reuses the `on_message` operator rung (D-07). The two gates are independent surfaces — do not route `!panel` through the component gate or vice versa.

### Config field: frozen + `extra="forbid"` fail-loud-at-load
**Source:** every model in `models.py` (e.g. `BotConfig` `model_config = ConfigDict(extra="forbid", frozen=True)`, `models.py:376`).
**Apply to:** `panel_channel_id` — immutable snapshot stays `ConfigHolder`-compatible; an unknown `[bot]` key still fails loud. `[bot]` keys are read once at startup (restart-boundary debt, D-04) — document, don't hot-reload.

### `interactive/` import-acyclic discipline
**Source:** `panel.py:44-60` / `bot.py:36-55` — `from __future__ import annotations`, light module-top imports, heavy types under `TYPE_CHECKING`, no in-handler lazy import (except the deliberate cycle-break like `loader.py:62`).
**Apply to:** the new `PanelView` reference in `bot.py` (cycle risk: `panel.py` imports `render_embed` from `bot.py`) and the scan-helper module wherever it lands. Resolve via deferred import or constructor injection.

### Selected-location default-on-restart
**Source:** `panel.py:193` (`self._selected_location = locations[0]`) mirroring `loader.py:52-53` (`resolve_location(config, None) → config.locations[0]`).
**Apply to:** confirmation only (D-08) — a freshly-built `PanelView` at `add_view` time reflects current config and defaults to `locations[0]`. Persisting the selection across restart is OUT OF SCOPE.

---

## No Analog Found

None. Every new artifact extends an existing in-repo pattern (the config sibling field, the
client-handler decorator, the `on_message` ladder/envelope, the `wb:` `custom_id` model, the
gateway-free test fixtures). The only genuinely-new mechanics — `Client.add_view`,
`channel.pins()` async iteration, `Permissions.pin_messages`, `discord.Forbidden` — are
discord.py 2.7.1 library primitives (VERIFIED against installed source in 18-RESEARCH
Patterns 1-3), not project-local patterns to discover.

---

## Metadata

**Analog search scope:** `weatherbot/interactive/` (bot.py, panel.py, __init__.py),
`weatherbot/config/` (models.py, loader.py), `weatherbot/scheduler/daemon.py`,
`tests/` (conftest.py, test_bot.py, test_panel.py).
**Files scanned:** 8 source/test files (targeted reads on the cited line ranges).
**Pattern extraction date:** 2026-06-26
