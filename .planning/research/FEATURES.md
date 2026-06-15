# Feature Research

**Domain:** Personal always-on weather-briefing daemon — v1.1 "Interactive & Live-Config" (on-demand command + full-config hot-reload)
**Researched:** 2026-06-15
**Confidence:** HIGH (single-user personal-tool scope; patterns converge across Discord-bot guides + daemon-reload conventions; existing v1 components are known, not assumed)

> Scope note: This research covers ONLY the two new v1.1 features (CMD-V2-01 on-demand command, ENH-V2-01 config hot-reload). Existing v1.0 capabilities (scheduling, OpenWeather One Call 3.0 fetch, render, SQLite, webhook delivery, retry-then-alert, systemd survival) are treated as fixed dependencies, not re-researched. The prior v1.0 feature landscape lived in this file; it has been superseded by the v1.1 scope below.

## Feature Landscape

### Table Stakes (Users Expect These)

Features that, if missing, make v1.1 feel broken or half-built. For a single-user tool "users expect" = "the operator will be annoyed/surprised if absent."

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| On-demand lookup of a **configured** location by name (`weather home`, `weather travel`) | The headline v1.1 feature; mirrors how every personal weather bot answers "what's the weather" | MEDIUM | Reuse v1 OpenWeather client + render path; resolve name → existing location config; this is the core deliverable |
| Same lookup available **both** as a one-shot CLI subcommand AND as a Discord in-channel reply | PROJECT.md explicitly requires both surfaces; CLI must work with no daemon running | MEDIUM | Two entry points calling one shared "fetch + render for location X" function. CLI = synchronous one-shot; Discord = inside the daemon |
| Default location when no arg given (`weather` → a sensible default) | Personal bots almost universally answer a bare command; forcing a name every time is friction | LOW | Default to a configured "primary"/first location (or today's expected location). Pick a deterministic rule and document it |
| Clear error on unknown/unconfigured location name | v1.1 is configured-locations-only by design; the user WILL typo or try an unconfigured city | LOW | Reply must say it's unknown AND list the valid configured names so the user self-corrects. No silent failure, no geocode attempt |
| On-demand reply **reuses the existing briefing template/format** | Consistency — the operator already tuned the template; a divergent format is surprising and doubles maintenance | LOW | Same renderer + same template. The on-demand reply IS a briefing for "now", just triggered manually instead of by schedule |
| Hot-reload picks up edits to the **full** config (schedules, locations, units, templates) without restart | ENH-V2-01 core promise; a partial reload (only some fields) would surprise the operator who edits any of them | MEDIUM | Re-read config → validate → atomically swap the in-memory config + re-register scheduler jobs |
| **Validate-and-keep-old on failure** — a bad edit never takes down the live daemon | The whole reason hot-reload is safe to use; matches v1's existing "validate-on-load, fail-loud" ethos | MEDIUM | Build/validate the new config object fully BEFORE swapping. On any validation error, discard it and keep running on the old one |
| Explicit reload feedback: success vs rejection is visible | Operator must know whether their edit took effect; a silent reload is worse than no reload | LOW | At minimum a structured log line ("reload OK, 4 jobs registered" / "reload REJECTED: locations[1].schedule[0].time invalid, keeping previous config"). Richer feedback in differentiators |
| Reload is **atomic / all-or-nothing** | A half-applied config (new locations but old schedules) is a correctness hazard; the daemon could double-send or mis-route | MEDIUM | Swap a single immutable config snapshot under a lock; never mutate the live config field-by-field |
| On-demand fetch respects OpenWeather quota (no unbounded fetch-per-keystroke) | One Call 3.0 is a card-on-file metered subscription; command spam = real cost / quota burn | LOW | Per-command cooldown / short-TTL cache (see below). Table-stakes because the daemon is metered, not free |

### Differentiators (Competitive Advantage)

Features that make v1.1 noticeably nicer than a bare "it works" implementation, and align with the Core Value (reliable, hands-off, correct-location briefings).

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Short-TTL response cache for on-demand fetches (reuse a fetch < ~5–10 min old for the same location) | Makes "spam the command" cost ~nothing AND feels instant; better UX than a hard cooldown that just rejects | LOW–MEDIUM | A small per-location `{location: (timestamp, rendered_result)}` cache. Doubles as the rate-limit mechanism — repeated calls hit cache, not the API |
| File-watch auto-reload (edit + save → applied) **plus** an explicit trigger | PROJECT.md asks for both; file-watch is the "no friction" path, explicit trigger (SIGHUP / CLI `--reload` / Discord command) is the deterministic "apply now" path | MEDIUM | Debounce the watcher (editors write multiple times / temp-file swaps). Watch the directory, not just the inode. Both paths funnel into one validate-and-swap function |
| Discord reply confirming reload outcome in-channel | Operator edits config, sees "config reloaded — 2 locations, 4 schedules" (or the rejection reason) in Discord without tailing logs | LOW | Reuses the existing outbound webhook for the message; the *trigger* may be file-watch or a bot command. High value, low cost |
| `weather` reply reports which location/day it answered for | Reinforces the project's central "correct location for where you'll actually be" value, especially with the weekday/weekend split | LOW | Include the resolved location name + local time in the reply header (likely already in the template) |
| Reload diff summary in the log ("schedules changed: travel 08:00→08:30; units unchanged") | Makes it obvious WHAT changed; aids the multi-day-unattended debugging story | MEDIUM | Compare old vs new snapshot; nice-to-have, defer if it adds risk |
| Dry-run / validate-only mode for config (`weatherbot --check-config`) | Lets the operator validate an edit before the daemon applies it; pairs with v1's existing `--check` | LOW | Likely already partly exists via v1 validate-on-load; expose as an explicit subcommand with a meaningful exit code (like `nginx -t`) |

### Anti-Features (Commonly Requested, Often Problematic)

Things that look reasonable for "a Discord weather bot" but are wrong for THIS single-user, configured-locations-only, metered-API tool. Documented to prevent scope creep.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Arbitrary / geocoded "weather in <any city>" lookups | Feels like the obvious generalization of the command | Explicitly deferred (CMD-V2-02); needs runtime geocoding, unknown-input handling, and blows the configured-only scope + quota assumptions | Configured locations only in v1.1; reject unknown names with the valid-names list |
| Full interactive Discord bot (many slash commands, settings UI, buttons, persistent menus) | "Since we're adding a bot anyway, add more commands" | Out of Scope per PROJECT.md — the config file is the interface; a command surface invites multi-user/permission complexity for a 1-person tool | One command (`weather [location]`) + optionally one reload command. Nothing else |
| Slash commands w/ global registration + app-command sync | The "modern" Discord default | Slash commands require global/guild registration + a sync lifecycle, heavier than needed for a private single-guild personal bot, and can respond slower | A simple prefix/message command (single guild, `message_content` intent) OR a hybrid command if trivial. Keep it minimal |
| Per-user cooldown tracking / multi-user rate-limit tables | Standard Discord-bot anti-spam guidance assumes many users | Single user — there are no "other users" to fence off. A per-user table is dead complexity | One global short-TTL cache + (optional) a single global min-interval. Protects the quota, not "users" |
| Persisting on-demand fetches into the analysis SQLite store like scheduled briefings | "Store every fetch for history" symmetry | v1's store is gated on **successful scheduled delivery** = one clean per-location daily time series for ANLY-V2-01. Injecting ad-hoc, possibly-bursty, manually-triggered fetches pollutes that series (duplicate timestamps, non-schedule rows) and complicates future trend analysis | Do NOT persist on-demand fetches to `weather_onecall` by default. If any record is wanted, use a separate table / flag so analysis can exclude them. Keep the scheduled series clean |
| Hot-reloading **secrets** (API key, webhook URL, bot token) from `.env` at runtime | "Reload everything live" | Secret rotation mid-process is fiddly (clients/gateway hold the credential), rarely needed, and a wrong key should fail loud at startup (v1 already does this via the systemd health gate) | Hot-reload the config file (locations/schedules/units/templates) only; secret changes = restart. Document this boundary |
| Reload-on-every-file-event with no debounce | "Just watch the file" | Editors emit multiple write/rename events per save; naive watching triggers several reloads (and validations / job re-registrations) per edit, racing against a half-written file | Debounce (coalesce events within a short window) + read-then-validate; ignore partial files |
| Two-way Discord config editing (set schedules via chat) | "Configure from my phone" | Reintroduces the config-as-UI complexity that's explicitly Out of Scope; risks invalid state from a chat field | Edit the file (hot-reload makes that painless); chat is read-only (`weather`) + reload trigger/confirmation only |

## Feature Dependencies

```
On-demand command (CMD-V2-01)
    ├──requires──> v1 OpenWeather One Call client (fetch for a location)
    ├──requires──> v1 template renderer (reuse briefing format)
    ├──requires──> location-name → config resolution (new, small)
    └──requires──> short-TTL cache / cooldown (quota guard)
            └──enhances──> on-demand command (instant repeats, cheap spam)

Discord bot reply surface
    ├──requires──> NEW inbound gateway connection + bot token (discord.py / py-cord)
    │                 [distinct from v1 outbound webhook — flips v1 "no discord.py" guidance]
    └──enhances──> on-demand command (in-channel access from phone)

CLI subcommand (`weather [location]`)
    └──requires──> shared "fetch+render for location X" function
                      (same function the Discord path calls; must run with NO daemon)

Config hot-reload (ENH-V2-01)
    ├──requires──> v1 config loader + validate-on-load (already fail-loud)
    ├──requires──> atomic in-memory config swap (single snapshot under lock)
    ├──requires──> scheduler job re-registration (APScheduler add/remove/replace jobs)
    ├──requires──> file-watch (watchdog) WITH debounce  ──and/or──  explicit trigger (SIGHUP / CLI / Discord)
    └──enhances──> reload-outcome feedback (log line; optional Discord confirmation)

reload feedback (Discord confirmation) ──requires──> v1 outbound webhook (reuse)

On-demand persistence to weather_onecall ──conflicts──> clean scheduled time series (ANLY-V2-01)  [ANTI-FEATURE]
```

### Dependency Notes

- **On-demand command requires location-name resolution:** v1 stores locations with name/lat/lon/tz/units. The command maps the arg (or default) to one of those entries; an unmatched arg is the "unknown location" error path.
- **Discord reply requires a NEW inbound connection:** Receiving commands needs a gateway connection + bot token (discord.py or py-cord). This is genuinely new infrastructure, distinct from the v1 fire-and-forget webhook, and lives inside/alongside the daemon. The outbound briefing path stays on the existing webhook. This is the single biggest new dependency in v1.1.
- **CLI path must NOT depend on the daemon:** PROJECT.md requires a standalone one-shot lookup. The fetch+render core must be callable without the scheduler/gateway running, so factor it as a pure function both surfaces call.
- **Hot-reload requires atomic swap + scheduler re-registration:** Changing schedules/locations means the in-process APScheduler jobs must be rebuilt to match the new config. Do this from a validated snapshot, all-or-nothing, so the daemon never runs jobs that disagree with the live config (correctness / exactly-once hazard).
- **File-watch requires debounce; explicit trigger does not:** Both feed one validate-and-swap function, but the watcher needs debounce + partial-file tolerance. The explicit trigger (SIGHUP/CLI/Discord) is the deterministic "apply now" escape hatch if the watcher misbehaves.
- **Persisting on-demand fetches conflicts with the analysis store:** v1 keeps a clean per-location scheduled-delivery time series. On-demand rows would pollute it — keep them out (or in a separate table).

## MVP Definition

### Launch With (v1.1 core)

The minimum that satisfies CMD-V2-01 + ENH-V2-01 honestly.

- [ ] Shared "fetch + render briefing for configured location X" core function — both surfaces depend on it
- [ ] CLI subcommand `weather [location]` (one-shot, no daemon required) — standalone path
- [ ] Discord inbound bot (gateway + token) with a single `weather [location]` command replying in-channel — interactive surface
- [ ] Default-location behavior when no arg; clear "unknown location — valid names: …" error — UX correctness
- [ ] Reuse the existing template/format for the on-demand reply — consistency, no second format
- [ ] Short-TTL response cache (doubles as quota guard) so repeated commands don't burn metered API calls — protects One Call 3.0 spend
- [ ] Do NOT persist on-demand fetches to the scheduled `weather_onecall` series — keeps analysis data clean
- [ ] Full-config reload: re-read → validate → atomic swap → re-register scheduler jobs — ENH-V2-01 core
- [ ] Validate-and-keep-old-config on any failure; never crash the live daemon — safety guarantee
- [ ] At least the explicit reload trigger (SIGHUP or CLI `--reload` or Discord command) — deterministic apply
- [ ] Reload-outcome log line (success summary / rejection reason) — visible feedback

### Add After Validation (v1.1 polish)

- [ ] File-watch auto-reload with debounce — trigger: explicit reload works and is trusted
- [ ] Discord in-channel reload confirmation (success / rejection reason) — trigger: operator wants feedback without log access
- [ ] `--check-config` dry-run validate-only subcommand — trigger: operator wants to test edits before applying
- [ ] Reload diff summary in logs — trigger: harder-to-debug reloads emerge

### Future Consideration (v2+ — already deferred in PROJECT.md)

- [ ] Arbitrary/geocoded-anywhere lookups (CMD-V2-02) — defer: out of v1.1 configured-only scope, needs geocoding + quota rethink
- [ ] Telegram / SMS inbound command surfaces (CHAN-V2-*) — defer: validate the abstraction with one inbound channel first
- [ ] History/trend query commands over the SQLite store (ANLY-V2-*) — defer: depends on the clean scheduled series
- [ ] Hot-reloading secrets — defer/decline: restart is the right boundary for key/webhook/token changes

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Shared fetch+render core function | HIGH | LOW | P1 |
| CLI `weather [location]` one-shot | HIGH | LOW | P1 |
| Discord inbound bot + `weather` command | HIGH | MEDIUM | P1 |
| Default location + unknown-name error UX | HIGH | LOW | P1 |
| Reuse existing template for reply | MEDIUM | LOW | P1 |
| Short-TTL cache / quota guard | HIGH | LOW | P1 |
| Full-config validate → atomic swap | HIGH | MEDIUM | P1 |
| Keep-old-config-on-failure | HIGH | MEDIUM | P1 |
| Scheduler job re-registration on reload | HIGH | MEDIUM | P1 |
| Explicit reload trigger (SIGHUP/CLI/Discord) | HIGH | LOW | P1 |
| Reload-outcome log line | MEDIUM | LOW | P1 |
| File-watch auto-reload + debounce | MEDIUM | MEDIUM | P2 |
| Discord reload confirmation message | MEDIUM | LOW | P2 |
| `--check-config` dry-run | MEDIUM | LOW | P2 |
| Reload diff summary in logs | LOW | MEDIUM | P3 |
| Per-user cooldown tables | LOW | MEDIUM | Anti-feature — skip |
| Persist on-demand fetches to store | LOW | LOW | Anti-feature — skip |

**Priority key:**
- P1: Must have for v1.1 launch
- P2: Should have, add when core is trusted
- P3: Nice to have, future

## Competitor Feature Analysis

Patterns observed across personal Discord weather/utility bots and OSS daemons (no single "competitor" — these are ecosystem conventions).

| Feature | Typical personal Discord bots | OSS daemons (nginx/sshd/etc.) | Our Approach |
|---------|-------------------------------|-------------------------------|--------------|
| Command syntax | `!weather`, `/weather <city>`; bare command defaults to a saved/home location | n/a | `weather [location]` over a configured-name set; bare = default location |
| Slash vs prefix | Public bots favor slash (discoverable); private/personal bots often keep prefix (lighter, needs `message_content` intent) | n/a | Minimal prefix or hybrid command, single guild — avoid slash-registration overhead |
| Reply format | Same embed/format as their richer outputs; on-demand == scheduled output | n/a | Reuse the v1 briefing template verbatim |
| Unknown input | Error + suggestion / "try one of …" | n/a | Reject + list valid configured names; no geocode fallback |
| Rate-limit | Per-user cooldown decorator (for many users) | n/a | Global short-TTL cache (single user) — guards quota, not users |
| Config reload | n/a (most read config once at start) | SIGHUP → validate → apply, keep old on failure; some fields need restart | SIGHUP/CLI/Discord trigger + file-watch; validate → atomic swap → keep old on failure; secrets need restart |
| Reload feedback | n/a | Log line; exit code on validate-only (`nginx -t`) | Log line always; optional Discord confirmation; `--check-config` for dry-run exit code |

## Sources

- [discord.py — combining slash + prefix (hybrid commands)](https://github.com/Rapptz/discord.py/discussions/8242) — hybrid_command and the message_content intent requirement. MEDIUM
- [Pycord Guide — prefixed commands](https://guide.pycord.dev/extensions/commands/prefixed-commands) — prefix command tradeoffs for lightweight bots. MEDIUM
- [StudyRaid — implementing cooldowns and rate limiting (discord.py)](https://app.studyraid.com/en/read/7183/176806/implementing-cooldowns-and-rate-limiting) — per-user cooldown decorators; dictionary-based custom limiter. MEDIUM
- [StudyRaid — rate limiting and anti-spam measures](https://app.studyraid.com/en/read/7183/176818/rate-limiting-and-anti-spam-measures) — anti-spam assumes multi-user; informs the anti-feature call. MEDIUM
- [SIGHUP for configuration reload — is it standard? (linuxvox)](https://linuxvox.com/blog/sighup-for-reloading-configuration/) — SIGHUP de-facto reload convention, validate-then-apply, revert on failure, some fields need full restart. MEDIUM
- [How to implement configuration hot-reload (oneuptime)](https://oneuptime.com/blog/post/2025-12-11-configuration-hot-reload/view) — validate before apply, atomic updates, rollback/keep-old, log changes. MEDIUM
- [Build a config system with hot reload in Python (oneuptime)](https://oneuptime.com/blog/post/2026-01-22-config-hot-reload-python/view) — watchdog file-watch, debounced watching, watch dir not file, stabilization delay. MEDIUM
- WeatherBot PROJECT.md (v1.1 milestone definition, Out of Scope, v1 component inventory, persistence-gated-on-delivery note) — HIGH (authoritative project context)

---
*Feature research for: personal weather-briefing daemon — v1.1 interactive command + config hot-reload*
*Researched: 2026-06-15*
