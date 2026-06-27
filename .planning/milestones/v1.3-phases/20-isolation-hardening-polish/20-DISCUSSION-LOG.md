# Phase 20: Isolation Hardening + Polish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-26
**Phase:** 20-isolation-hardening-polish
**Areas discussed:** Location indicator placement, Emoji labels, "Updated <time>" stamp form, Hanging-callback isolation scope

(Advisor mode — each area backed by a parallel research agent; calibration tier: full_maturity / thorough-evaluator.)

---

## Location indicator placement (PANEL-12)

| Option | Description | Selected |
|--------|-------------|----------|
| Embed line + dropdown highlight | Authoritative `📍 Home` line in the result embed (restart-safe, zero row cost), PLUS mark dropdown's current option as cosmetic reinforcement | ✓ |
| Embed line only | Just the embed line; dropdown control stays neutral | |
| Dropdown highlight only | Rely on `SelectOption(default=True)` alone — fragile, reverts to placeholder if a render path forgets to re-mark | |

**User's choice:** Embed line + dropdown highlight
**Notes:** Disabled "pill" button rejected up front (panel is at 5/5 rows when forecast revealed — no spare component slot). Dropdown highlight is decorative reinforcement only; `_selected_location` stays the source of truth (never read `Select.values` — discord.py #7284), and the `default=True` mark must be re-applied from `_selected_location` on every rebuild/restart.

---

## Emoji labels (PANEL-13a)

| Option | Description | Selected |
|--------|-------------|----------|
| emoji= + keep text, proposed set | discord.py `emoji=` param + Title-Case label; adopt proposed mapping | ✓ (set kept) |
| emoji= + text, I'll tweak | Same structure, user adjusts several emoji | (initially picked, then "keep all") |
| Emoji-only labels | Icon-only buttons; most compact but loses names/accessibility | |

**User's choice:** `emoji=` param + keep text label; proposed emoji set kept as-is ("keep all").
**Notes:** Structure chosen over emoji-baked-into-label (fights API) and emoji-only (kept as a narrow fallback for forecast sub-buttons only if truncation ever appears). User reviewed the researcher's flagged-debatable picks (weather 🌡️, uv 🧴, status 🟢, weekend 🏖️/🌴) and confirmed all. Final set: weather 🌡️, uv 🧴, next-cloudy ☁️, sun ☀️, wind 💨, status 🟢, alerts ⚠️, Forecast 📅, Weekday Detailed/Compact 📋/📝, Weekend Detailed/Compact 🏖️/🌴.

---

## "Updated <time>" stamp form (PANEL-13b)

| Option | Description | Selected |
|--------|-------------|----------|
| Dynamic `<t:>` token in description | `Updated <t:unix:t> (<t:unix:R>)` in embed body — auto local-tz, self-ages, snaps to "now" on edit; keep native timestamp too | ✓ |
| Explicit static footer text | Hardcoded `Updated 9:42 AM` in a fixed local tz — manual tz/DST, no self-refresh | |
| Keep native timestamp only | No change; rely on existing grey footer `embed.timestamp` — correct but subtle | |

**User's choice:** Dynamic `<t:>` token in the embed description.
**Notes:** Native `embed.timestamp` already renders local-tz and updates each edit, but is too subtle (no "Updated" word). The `<t:…:R>` relative clause self-ages and resets on in-place edit — the tightest fit to "visibly distinct from the prior render." Keep the native timestamp as a free second signal. `<t:>` markdown can't go in the embed title — body only.

---

## Hanging-callback isolation scope (PANEL-11)

| Option | Description | Selected |
|--------|-------------|----------|
| Test-only proof + executor audit | Fire a briefing while a callback await-hangs, assert it still fires; audit briefing path doesn't share the default executor. No prod change. | ✓ |
| Test + callback timeout/watchdog | Also wrap callbacks in `asyncio.wait_for` — self-heals frozen gateway loop but can't interrupt sync/CPU hangs + adds tunable code to the load-bearing path | |
| Test + dedicated panel executor | Also route panel fetches through a bounded ThreadPoolExecutor — only worth it if audit shows real default-pool sharing | |

**User's choice:** Test-only thread-isolation proof + executor-sharing audit.
**Notes:** Briefing runs on APScheduler's own `BackgroundScheduler` thread, independent of the asyncio gateway loop. Of the three hang shapes, an `await`-hang and a sync-blocking call (GIL released) both leave the briefing untouched; only a pure-CPU spin could throttle it — and `asyncio.wait_for` can't interrupt that anyway. PANEL-11's guarantee is about the *briefing*, not gateway responsiveness, so a callback timeout is scope creep (deferred to v2). The test must hang via a loop-yielding `await` (the realistic shape). The one real check: verify the briefing path doesn't borrow the asyncio default executor `dispatch.py` uses (`run_in_executor(None, …)`) — expected clean.

---

## Claude's Discretion

- Exact embed insertion points/wording for the `📍 {location}` line and `Updated <t:…>` line (must be description/field/footer-text, never title); whether they share one block.
- The helper that re-applies `SelectOption(default=True)` from `_selected_location` on rebuild, and its placement (keep `interactive/` import-acyclic).
- Test structure/placement for the hanging-callback live-scheduler proof; whether the executor-sharing audit is a test assertion or a documented code-path verification.
- Whether emoji are applied via a parallel `_EMOJI` dict (keyed like `_LABELS`) or inline at button construction.

## Deferred Ideas

- Defensive callback timeout/watchdog (`asyncio.wait_for`) — v2 candidate if panel *responsiveness* ever becomes a requirement (D-09).
- Dedicated bounded `ThreadPoolExecutor` for panel fetches (Option C) — only if the D-08b audit unexpectedly finds default-pool sharing.
- Grey-out command buttons until a location is selected (PANEL-V2-01) — v2.
- Emoji-only forecast sub-buttons — narrow fallback only if label truncation appears.
