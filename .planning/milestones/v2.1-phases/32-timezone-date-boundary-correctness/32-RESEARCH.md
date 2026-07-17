# Phase 32: Timezone & Date-Boundary Correctness - Research

**Researched:** 2026-07-11
**Domain:** Python stdlib `zoneinfo`/`datetime` DST/date-boundary correctness in an existing bot codebase; APScheduler 3.x CronTrigger fold semantics; UV-lifecycle state machine
**Confidence:** HIGH — all findings verified against the actual source files and against a live `apscheduler 3.11.2` probe in this repo's `uv` env. No new dependencies; every fix is stdlib on already-present code.

## Summary

This is an audit-driven correctness phase. The "correct" behavior is already pinned by the ROADMAP success criteria and the CONFIRMED findings (F14 catch-up-across-midnight loss, F15 UV all-clear latch) plus the folded sibling findings (F31/F32/F33/F35/F69/F91). The four requirements are surgical edits to five source files — `scheduler/catchup.py`, `scheduler/uvmonitor.py`, `weather/models.py`, `weather/uv.py`, `weather/store.py` — reusing patterns that ALREADY exist in the codebase (`uvmonitor._daily0_matches_today` WR-05 guard, `multiday._date_index_map` "no positional math" precedent, `scheduler/days.py` acyclic-pure-helper shape, and the `catchup.py` gap/fold roundtrip compose).

The most important research finding, from a live probe of the installed `apscheduler 3.11.2` in this repo: **the live `CronTrigger` fires a DST fall-back repeated-hour slot at `fold=0` (the FIRST/earlier occurrence, the pre-transition offset)**, and `catchup.py`'s existing `.replace(tzinfo=tz)` ALSO defaults to `fold=0`. They already agree. This reframes F91: the risk is not that catch-up is currently wrong on fold, but that the D-01 prior-day work must NOT introduce a `fold=1` divergence, and the phase should lock the alignment with a regression test (and optionally a both-folds-union belt-and-suspenders). This is verified below with concrete UTC instants.

**Primary recommendation:** Extract ONE pure, dependency-free `weatherbot/weather/dates.py` helper (core `(now_utc, tz)` primitive + thin `(Location, now_utc)` wrapper, naive-`now_utc`→UTC hardening baked in) that `models.py`, `store.py`, and `uvmonitor.py` import (D-08/D-06 in one place). Add a shared "today's daily entry by its own local date" selector reusing the `_daily0_matches_today` + `_date_index_map` pattern, and apply it in both `models.from_payloads` and `uv.compute_uv` (D-05). Give catch-up a `{today, yesterday-local}` candidate loop keyed on the candidate day (D-01), keep `fold=0` compose (aligned with CronTrigger) and add a both-folds-union grace check as the F91 guard (D-02). Replace the UV all-clear one-tick latch with a predicted-window-end gate + a consecutive-sub-threshold persistence fallback (D-03), and audit the lifecycle for the never-fire gap (D-04). Every fix lands with a failing-first regression test in the existing injected-`now_utc` style.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**HARD-TZ-01 — Catch-up survives local midnight (D-01, D-02)**
- **D-01 — Also test the PRIOR local day's instant.** `plan_catchup` must, per slot, evaluate candidate dates `{today, yesterday-local}` — compose each candidate's naive wall-clock instant, attach the location zone, and run the SAME gates (gap-skip, `scheduled <= now_utc`, `now_utc - scheduled <= GRACE`, `was_sent` dedup). Dedupe so a single slot never emits twice; keep the "bounded to slots within GRACE / recovery burst is a quota rounding error" guarantee. The `local_date` recorded for `was_sent`/`MissedSlot` MUST be the candidate day's local date (yesterday's), NOT `now_local.date()`, so exactly-once keying stays correct.
- **D-02 — Fold-correct grace math on DST fall-back (F91).** The dueness/grace comparison must not be inflated by the `fold=0` default across a fall-back repeated hour. Align catch-up's fold choice with what the live `CronTrigger` actually fires, OR evaluate both folds and keep the slot due if EITHER lands within GRACE. **Mechanism is planner/researcher discretion**; invariant: a slot only minutes late inside the repeated hour is NOT dropped by a spurious 60-min inflation, and the existing spring-forward GAP skip (`:161-168`) is preserved unchanged.

**HARD-TZ-02 — UV all-clear hysteresis + lifecycle (D-03, D-04)**
- **D-03 — All-clear needs persistence, not a single instantaneous dip.** Replace the "current < threshold" one-tick latch with a hysteresis gate. **Recommended primary:** anchor all-clear to the PREDICTED end-of-window (`compute_uv` already computes peak/window — reuse it): declare "protect window over" only once the forecast curve shows UV has passed its peak and will not climb back above threshold today. **Fallback:** a persistence counter (N consecutive sub-threshold ticks and/or a sub-threshold margin). Exact N / margin / primary-vs-fallback is planner discretion; invariant: a single passing-cloud dip while UV is still at/above threshold must NOT end the window.
- **D-04 — No never-fire gap in the pre-warn↔crossing↔all-clear lifecycle.** Enumerate the branch state machine (in_daylight × current-vs-threshold × prior-claims) and prove every state has a reachable transition for the day. The moot-pre-warn suppression (WR-02) must never orphan a state or block a legitimate later crossing/all-clear. Ship a full-day-tick test asserting each expected post fires exactly once.

**HARD-TZ-03 — daily[0] anchored to configured-tz today (D-05, D-06, D-07)**
- **D-05 — Select today's daily entry by its OWN local date, never by position.** Both `models.from_payloads` (`:302 daily[0]`) and `uv.compute_uv` (`:133`) must verify the chosen `daily[i]`'s local date (from its `dt`/`sunrise` in the CONFIGURED tz) equals today's configured-tz local date — reusing `uvmonitor._daily0_matches_today` (WR-05) and the `multiday._date_index_map`/`_resolve_tz` "no positional math" pattern. If NO entry matches today, degrade defensively down the existing empty/`stays_below`/`None` high-low path — NEVER ship a non-today entry labelled as today. `compute_uv` gains the same guard the monitor already has (closes F31's morning-briefing false `stays_below`).
- **D-06 — `now_utc` must be treated as UTC-aware (F33).** The unified helper and its callers must not let a naive `now_utc` be interpreted in the HOST tz by `astimezone()`. Attach `timezone.utc` when naive (or assert aware). Reconcile the now-dead UTC-fallback branches (Location.timezone is required/IANA-validated at load) — keep as an explicit invariant or assert; planner discretion, but don't let dead fallback silently store a WRONG date.
- **D-07 — Sort today's hourly points before interpolation (F32).** `uv._today_daytime_points` (`:159`) appends in raw payload order; crossing/window interpolation assumes time-sorted points. Sort by timestamp before interpolating.

**HARD-TZ-04 — One `_local_date_iso` implementation (D-08)**
- **D-08 — Unify into ONE tz-correct helper — THREE copies, not two.** `models.py:69`, `store.py:210` (verbatim twins), and `uvmonitor.py:84` (`(now_utc, tz)` variant). **Recommended home:** a small pure, dependency-free tz helper module (mirroring `scheduler/days.py` and `weather/multiday.py` — no config/apscheduler/store imports) imported by all three. Reconcile the two signatures (`(Location, now_utc)` vs `(now_utc, tz)`) — e.g. core `(now_utc, tz)` primitive + thin `Location`-resolving wrapper. Fold D-06 naive-`now_utc` hardening into this single helper.

### Claude's Discretion (mechanism-level)
- **D-02 fold mechanism** — which fold to compose for grace math, or union-of-both; match the live CronTrigger.
- **D-03 hysteresis shape** — predicted-window-end vs consecutive-tick persistence vs sub-threshold margin (or combination), and exact N / margin.
- **D-05 shared "today entry" selector** — one shared helper across `models`/`compute_uv`/multiday, or apply the WR-05 guard at each site. Lean toward one shared selector.
- **D-08 helper home & signature** — new `weatherbot/weather/dates.py` (or promote into existing pure module); core-primitive-plus-wrapper vs single fn.
- **Defensive-degrade wording** — reuse the existing empty/`stays_below` collapse; don't invent a new user-facing string.

### Deferred Ideas (OUT OF SCOPE)
- **F02 bare-command crash & F13 cache race** — Phase 33 (depends on this phase's render/tz fixes).
- **Full regression-test backfill** (F109 daily[0]-is-today assertion, F106 concurrency) — Phase 34. Fixes here are test-shaped but the comprehensive suite is Phase 34.
- **F36 / F37 persistence data-model** (`weather_onecall` rename-safety / missing UNIQUE) — store/analysis data-model, not tz; not this phase.
- **All HUB findings** — route UPSTREAM to `yahir_reusable_bot`, human-gated. Do NOT fix here.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-TZ-01 | Catch-up composes the correct local date across a local-midnight boundary (F14, `catchup.py:155`) + fold-correct grace (F91, `catchup.py:170`) | §HARD-TZ-01 below: `{today, yesterday}` candidate loop reusing existing gap/fold compose `:156-168`; keying on candidate day; live CronTrigger fires `fold=0` (verified) so keep `fold=0` compose + both-folds-union grace guard. Concrete UTC math in Verification. |
| HARD-TZ-02 | UV all-clear has hysteresis; pre-warn↔crossing leave no never-fire gap (F15, `uvmonitor.py:318`) | §HARD-TZ-02 below: `UvSummary.peak_time`/`window_end`/`hourly_points` already computed by `compute_uv` — anchor all-clear to predicted window-end; persistence-counter fallback (tick=900s default). Full state-machine enumeration + never-fire-gap analysis. |
| HARD-TZ-03 | `daily[0]`/positional indexing anchored to configured IANA tz across DST/midnight (F31, F35, F91, F109 + siblings) | §HARD-TZ-03 below: reuse `_daily0_matches_today` + `_date_index_map`; shared "today entry" selector for `models.from_payloads` + `compute_uv`; F33 naive-`now_utc`→UTC; F32 sort `_today_daytime_points` before interpolation. |
| HARD-TZ-04 | ONE `_local_date_iso` shared by models.py + store.py (+ third copy in uvmonitor.py) | §HARD-TZ-04 below: new pure `weatherbot/weather/dates.py`; core `(now_utc, tz)` + `(Location, now_utc)` wrapper; no import cycle (verified imports). |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| "Which local day is today" | Pure helper (`weather/dates.py`, new) | Callers (`models`/`store`/`uvmonitor`) | One tz-correct primitive; callers pass `(now_utc, tz)`/`(Location, now_utc)`. Acyclic-pure like `days.py`/`multiday.py`. |
| "Is `daily[i]` actually today" | Pure helper (shared selector) | `models.from_payloads`, `uv.compute_uv` | Currently three sites do date-vs-position reasoning; unify into one selector (D-05). |
| Missed-send recovery across midnight | `scheduler/catchup.py` (pure planner) | sent-log (`was_sent`), CronTrigger (agreement) | `plan_catchup` is the SCHD-06 recovery mechanism; APScheduler misfire is deliberately NOT trusted across restart. |
| UV lifecycle decision (pre-warn/crossing/all-clear) | `scheduler/uvmonitor._decide` | `weather/uv.compute_uv` (window math), `store.claim_uv_alert` (durable dedup) | Decision branches gate on `compute_uv`'s summary + the durable claim set. |
| Persisted `local_date` keying | `weather/store.persist` + `sent_log`/`uv_alerts` | shared `dates.py` helper | Rendered `{date}` and stored `local_date` must derive from the SAME helper (D-08). |

## Standard Stack

No new dependencies. Everything is stdlib on already-present code.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `zoneinfo` (stdlib) | Python 3.11+ | IANA tz resolution + DST/fold semantics | Already the repo's tz authority (D-03). `ZoneInfo` + `fold=0/1` is the correct fall-back-hour primitive. `[VERIFIED: source grep — every tz path uses ZoneInfo]` |
| `datetime` (stdlib) | Python 3.11+ | aware instants, `.astimezone`, `.replace(tzinfo=,fold=)` | The existing compose idiom (`catchup.py:155-168`). `[VERIFIED: source]` |
| `apscheduler` | 3.11.2 (installed) | live `CronTrigger` — the fold the planner must agree with | Confirmed installed + fires fall-back at `fold=0`. `[VERIFIED: apscheduler 3.11.2 live probe in repo uv env]` |
| `pytest` | (installed) | injected-`now_utc` regression tests | Existing convention in `test_scheduler.py`/`test_uv_monitor.py`. `[VERIFIED: tests/ present]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `fold` roundtrip gap-detection | `dateutil.tz` | Adds a dependency for something stdlib `zoneinfo` already does correctly here. The existing code already solves it stdlib-only. Do NOT add. |
| Reusing `compute_uv`'s window for all-clear | Recompute a separate curve in `_decide` | Duplicates the same interpolation the phase is trying to harden — reuse `UvSummary`, don't fork. |

**Installation:** None. No `uv add`.

## Package Legitimacy Audit

Not applicable — this phase installs no external packages. All code uses Python stdlib (`zoneinfo`, `datetime`) and packages already pinned in `pyproject.toml` (`apscheduler 3.11.x`, `pytest`). No `uv add` in scope.

## Architecture Patterns

### System Architecture Diagram

```
                       ┌─────────────────────────────────────────────┐
   now_utc (injected)  │  weatherbot/weather/dates.py  (NEW, pure)    │
   ───────────────────▶│  local_date_iso(now_utc, tz)   ← core prim   │
                       │  local_date_for(location, now_utc) ← wrapper │
                       │  (naive now_utc → attach timezone.utc, D-06) │
                       └───────┬───────────────┬──────────────┬───────┘
                               │ import         │ import        │ import
                    ┌──────────▼─────┐  ┌───────▼──────┐  ┌─────▼────────┐
                    │ models.py      │  │ store.py     │  │ uvmonitor.py │
                    │ from_payloads  │  │ persist →    │  │ _decide /    │
                    │ {date} render  │  │ target_local │  │ _evaluate    │
                    └──────┬─────────┘  │ _date        │  └──────┬───────┘
                           │            └──────────────┘         │
                           │ D-05 shared "today daily entry" selector
                           │  (reuse _daily0_matches_today + _date_index_map)
                    ┌──────▼───────────────────────────────────┐
                    │ weather/uv.py  compute_uv                 │
                    │  - daily0 anchored to today (D-05, F31)   │
                    │  - _today_daytime_points SORTED (D-07,F32)│
                    │  → UvSummary{current,peak_time,window_end,│
                    │              crossing_time,hourly_points} │
                    └──────┬────────────────────────────────────┘
                           │ (window/peak facts)
                    ┌──────▼───────────────────────────────────┐
                    │ uvmonitor._decide (D-03/D-04)             │
                    │  all-clear ← window_end reached / N ticks │
                    │  never-fire-gap audit                     │
                    └───────────────────────────────────────────┘

   scheduler/catchup.py  plan_catchup (D-01/D-02):
     for slot: for candidate in {today_local, yesterday_local}:
        compose naive @ candidate date → attach tz (fold=0, aligns CronTrigger)
        gap-skip (:161-168 unchanged) → due? → within-GRACE (both-folds union)?
        → was_sent(loc.id, slot.time, candidate_local_date)? → MissedSlot
     dedup so a slot never emits twice.
```

### Recommended Project Structure
```
weatherbot/
├── weather/
│   ├── dates.py       # NEW: pure tz helper — local_date_iso + Location wrapper (D-08/D-06)
│   ├── models.py      # imports dates; from_payloads uses shared today-entry selector (D-05)
│   ├── store.py       # imports dates (replaces local _local_date_iso)
│   ├── uv.py          # compute_uv: daily0-today guard + sorted points (D-05/D-07)
│   └── multiday.py    # existing _date_index_map — the reuse precedent (unchanged, or share)
└── scheduler/
    ├── catchup.py     # plan_catchup: {today, yesterday} candidate loop + fold grace (D-01/D-02)
    ├── uvmonitor.py   # imports dates (replaces local _local_date_iso); _decide hysteresis (D-03/D-04)
    └── days.py        # the acyclic-pure-helper precedent (unchanged)
```

### Pattern 1: Prior-local-day candidate loop (D-01)
**What:** Evaluate `{today, yesterday-local}` per slot, reusing the existing gap/fold compose verbatim, keyed on the candidate day.
**When to use:** `plan_catchup`, replacing the single-`now_local.date()` compose at `:155`.
**Example:**
```python
# Source: derived from catchup.py:151-177 (existing compose) + D-01
for slot in loc.schedule:
    if not slot.enabled or not fires_on(slot, now_local):
        continue
    hh, mm = slot.parsed_time()
    emitted_dates: set[str] = set()          # dedup guard (a slot never twice)
    for cand_date in (now_local.date(), now_local.date() - timedelta(days=1)):
        naive = datetime(cand_date.year, cand_date.month, cand_date.day, hh, mm)
        # --- existing gap/fold roundtrip, UNCHANGED (:161-168) ---
        off0 = naive.replace(tzinfo=tz, fold=0).utcoffset()
        off1 = naive.replace(tzinfo=tz, fold=1).utcoffset()
        scheduled = naive.replace(tzinfo=tz)          # fold=0 — aligns CronTrigger (verified)
        roundtrip = scheduled.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
        if off0 != off1 and roundtrip != naive:
            continue                                   # spring-forward gap — never existed
        if scheduled > now_utc:
            continue                                   # not due yet
        # D-02 fold-union grace: due within GRACE for EITHER fold's instant
        due_within = min(                              # smallest lateness across folds
            now_utc - naive.replace(tzinfo=tz, fold=0).astimezone(timezone.utc),
            now_utc - naive.replace(tzinfo=tz, fold=1).astimezone(timezone.utc),
        )
        if due_within > GRACE:
            continue
        local_date = cand_date.isoformat()             # CANDIDATE day, not now (D-01 keying)
        if local_date in emitted_dates:
            continue
        if was_sent(loc.id, slot.time, local_date):
            continue
        missed.append(MissedSlot(loc, slot, scheduled, local_date))
        emitted_dates.add(local_date)
```
Note: the both-folds `min()` is only meaningful inside the repeated fall-back hour; for all normal times `off0 == off1` so both folds resolve to the same instant and `due_within` is exact. This closes F91 without changing the compose fold that agrees with CronTrigger.

### Pattern 2: Shared "today's daily entry" selector (D-05)
**What:** Given `daily[]` + configured tz + today's local_date, return the entry whose OWN local date == today (or `None`). Reuses the `_daily0_matches_today` derive-date-from-sunrise idea and the `_date_index_map` no-positional-math idea.
**When to use:** `models.from_payloads` (replaces `daily[0]` hard-index at `:302`) and `uv.compute_uv` (adds the guard it lacks — F31).
**Example:**
```python
# Source: synthesis of uvmonitor._daily0_matches_today (:93-110) + multiday._date_index_map (:50)
def select_today_daily(daily: list[dict], tz, local_date: str) -> dict | None:
    """The daily[] entry whose own local date == local_date (by dt/sunrise), else None."""
    for entry in daily or []:
        entry = entry or {}
        stamp = entry.get("dt") or entry.get("sunrise")   # sunrise unambiguously on its own day
        if stamp is None:
            continue
        try:
            entry_date = datetime.fromtimestamp(int(stamp), tz=tz).date().isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if entry_date == local_date:
            return entry
    return None
```
In `from_payloads`: if `select_today_daily(...)` is `None`, take the EXISTING degrade path (`high_imp=None`, rain from empty, UV → `stays_below` via `compute_uv`'s empty-points path) — never ship a non-today entry as today (Fail-safe degrade pattern already in the file).

### Pattern 3: All-clear anchored to predicted window-end (D-03 primary)
**What:** Gate all-clear on "past the day's peak AND `current < threshold` AND we are at/after `window_end`" instead of a bare instantaneous dip.
**When to use:** `uvmonitor._decide` branch 3 (`:318`).
**Example:**
```python
# Source: uvmonitor._decide branch 3 (:317-323) + reuse compute_uv's UvSummary
# summary already carries: current, peak_time, window_end, crossing_time (weather/uv.py)
past_peak = summary.peak_time is not None and now_local >= summary.peak_time
window_over = summary.window_end is not None and now_local >= summary.window_end
below = summary.current < threshold
# Primary: predicted-window-end. Fallback: persistence counter when window unavailable.
allclear_ready = below and "crossing" in prior and "allclear" not in prior and (
    (window_over and past_peak)                      # primary: forecast says done
    or _sub_threshold_streak(...) >= N               # fallback: N consecutive dips
)
if allclear_ready and claim_uv_alert(db_path, location.id, local_date, "allclear"):
    _post(channel, f"✅ UV back below {t} in {name} — protect window over.")
```
**Persistence-counter N (fallback):** the UV monitor tick default is `interval_seconds = 900` (15 min) `[VERIFIED: config/models.py:430]`. A momentary passing cloud is a single tick; `N = 2` (two consecutive sub-threshold ticks = ~30 min) already defeats the one-cloud dip while keeping the window closing promptly near sunset. The persistence counter needs durable state — options: (a) a new `uv_alerts` kind row `subthreshold` claimed per tick is wrong (INSERT OR IGNORE dedups), so use a small dedicated counter table or reconstruct from the forecast (prefer the primary window-end gate, which is stateless and needs NO new table). **Recommendation: ship the primary (window-end) gate as the mechanism; use the sub-threshold margin only when `window_end`/`peak_time` are `None` (empty hourly), and prefer degrading to "don't post all-clear yet" over a premature latch.** Avoid a new persistence table this phase (keeps store data-model out of scope, per F36/F37 deferral).

### Anti-Patterns to Avoid
- **Positional `daily[0]` as "today":** the whole point of D-05/F35 — never index `[0]` and trust it. Match by the entry's own local date.
- **Naive `now_utc` through `astimezone()`:** silently reinterprets in HOST tz (F33). Attach `timezone.utc` (or assert aware) in ONE place (the shared helper).
- **Keying a yesterday recovery on `now_local.date()`:** breaks exactly-once — the recovered slot would key on today, not the day it was scheduled (D-01).
- **Choosing `fold=1` for the fall-back compose:** would diverge from the live CronTrigger (which fires `fold=0`, verified) and inflate grace by 60 min. Keep `fold=0`; use the both-folds `min()` only for the grace comparison.
- **Latching all-clear on one instantaneous `current.uvi` dip:** the F15 bug. Require window-end/persistence.
- **Interpolating over unsorted hourly points:** F32 — a DST fall-back duplicate hour or out-of-order payload straddles the wrong pair. Sort first.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DST fall-back "which offset did the slot fire at" | A manual offset table | `apscheduler.CronTrigger.get_next_fire_time` semantics (fires `fold=0`) + stdlib `.replace(fold=)` | Verified against live 3.11.2; hand-rolling re-derives what the trigger already decides. |
| "Is this wall-clock time a spring-forward gap" | A custom transition detector | The EXISTING roundtrip check `off0!=off1 and roundtrip!=naive` (`catchup.py:161-168`) | Already correct and tested (`test_dst_transition_band_exactly_once`). Reuse verbatim for the prior-day candidate. |
| "Which `daily[i]` is today" | Day-of-week index math | `_date_index_map`/`_daily0_matches_today` local-date match | The `multiday.py` precedent exists precisely to avoid positional math (Pitfall 1). |
| UV crossing/window/peak | Recompute a curve in `_decide` | `compute_uv`'s `UvSummary` (already returns `peak_time`, `window_end`, `hourly_points`) | Reuse the single seam the three consumers share; don't fork the interpolation the phase is hardening. |
| local-date-from-tz in 3 files | Three `_local_date_iso` copies | ONE pure `dates.py` helper | The exact F69 defect — divergent copies mis-key rows vs render. |

**Key insight:** Every fix in this phase has an in-repo precedent to reuse. The phase is consolidation and correctness-tightening, not new mechanism.

## Runtime State Inventory

This is a code-correctness phase (no rename/rebrand), but it touches date-keying, so the durable-state audit matters for exactly-once.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `sent_log.local_date`, `alerts.local_date`, `uv_alerts.local_date`, `weather_onecall.target_local_date` are all `YYYY-MM-DD` strings keyed by the current (possibly divergent) `_local_date_iso` copies. **Unifying the helper (D-08) must NOT change the string value for existing correct cases** — it produces the SAME `now.astimezone(tz).date().isoformat()`, so historical rows stay compatible. | Code edit only. NO data migration: the helper output is byte-identical for the common (aware `now_utc`, valid tz) case; only the naive/edge cases change (which were BUGS producing wrong dates). Verify no existing row's key format changes. |
| Live service config | None — no external service stores these strings. The daemon reads config TOML + the SQLite store, both on-host. | None. |
| OS-registered state | systemd unit `weatherbot.service` on `yahir-mint` (Restart policy). The catch-up path runs at boot; a clean `systemctl restart weatherbot` re-exercises `plan_catchup`. | None (no unit change). Note in plan: a restart is how the live daemon re-runs catch-up. |
| Secrets/env vars | None touched. `OPENWEATHER_API_KEY`/`DISCORD_WEBHOOK_URL` unaffected. | None. |
| Build artifacts | Editable install on host (`uv pip install -e` / `uv sync --frozen`). After landing, the live daemon needs a reinstall+restart to pick up the new `dates.py` module and edits. | Deploy step: reinstall + `systemctl restart` on `yahir-mint`; verify via injected-`now_utc` unit tests first (deterministic), then a live restart. |

**The canonical question — after every file is updated, what still has an old value cached/registered?** Only the SQLite `local_date` columns, and those keep the SAME format for correct cases (no migration). The naive-`now_utc`/wrong-tz cases that D-06 fixes were producing WRONG keys — but those are bugs, not data to preserve.

## Common Pitfalls

### Pitfall 1: Breaking exactly-once on the yesterday recovery
**What goes wrong:** D-01 emits a MissedSlot for yesterday's slot but keys `was_sent`/`MissedSlot.local_date` on `now_local.date()` (today), so the dedup guard checks the wrong day and the slot can re-fire (or a genuinely-sent yesterday slot re-delivers).
**Why it happens:** the existing code derives `local_date = now_local.date().isoformat()` at `:174`; naively looping candidate dates without moving that line inside the loop keys everything on today.
**How to avoid:** compute `local_date` from the CANDIDATE date, inside the candidate loop (Pattern 1). Add a dedup set so a slot never emits for both days.
**Warning signs:** a test where the yesterday slot is `was_sent`-true but still appears in the plan; a duplicate briefing after a just-past-midnight restart.

### Pitfall 2: Diverging from CronTrigger on the DST fall-back fold
**What goes wrong:** catch-up composes the fall-back slot at a different fold than the live CronTrigger fires, so either grace inflates 60 min (slot dropped) or the planner and trigger double-count.
**Why it happens:** `.replace(tzinfo=tz)` defaults to `fold=0`; a "fix" that switches to `fold=1` or compares against a `fold=1` instant silently disagrees.
**How to avoid:** KEEP `fold=0` for the composed `scheduled` (verified to match CronTrigger 3.11.2). Use a both-folds `min()` ONLY for the grace lateness comparison so a slot minutes-late in the repeated hour is never dropped. Preserve the spring-forward gap skip unchanged.
**Warning signs:** `test_dst_transition_band_exactly_once` regresses; a fall-back-hour slot at 60-min-late is dropped.

### Pitfall 3: All-clear latch on a momentary dip (F15, the CONFIRMED bug)
**What goes wrong:** a single passing cloud at solar noon (UV 5.8 vs 6.0) claims `allclear` once/day durably; UV climbs back to 8 minutes later but the window can never re-open — "protect window over" posted while UV is still peaking.
**Why it happens:** branch 3 gates only on instantaneous `summary.current < threshold` with no persistence/window-end check.
**How to avoid:** anchor on `window_end`/`peak_time` from the SAME `UvSummary` (Pattern 3); require past-peak + past-predicted-window-end (primary), sub-threshold persistence as fallback.
**Warning signs:** the momentary-dip regression test (below) still posts all-clear.

### Pitfall 4: `daily[0]` is yesterday near a tz/DST/midnight boundary (F31/F35)
**What goes wrong:** `models.from_payloads` and `compute_uv` trust `daily[0]`; near midnight/DST the payload's `daily[0]` can be YESTERDAY, so the briefing ships yesterday's high/low/rain/UV as today's, or `compute_uv` filters out every "today" hourly bucket against a stale sunset and falsely reports `stays_below`.
**Why it happens:** positional `[0]` indexing without a local-date match.
**How to avoid:** the shared today-entry selector (Pattern 2), degrading to the existing empty/`stays_below`/`None` path when no entry matches.
**Warning signs:** a payload whose `daily[0]` is dated yesterday still drives the briefing; F109's missing test.

### Pitfall 5: Naive `now_utc` reinterpreted in host tz (F33)
**What goes wrong:** a naive injected `now_utc` near midnight passes through `.astimezone(tz)` which first assumes the HOST local tz, shifting the computed `local_date` by a day.
**Why it happens:** `datetime.astimezone()` on a naive datetime treats it as system-local.
**How to avoid:** in the ONE shared helper, `if now_utc.tzinfo is None: now_utc = now_utc.replace(tzinfo=timezone.utc)` (or assert aware). Fix once, benefits all three callers.
**Warning signs:** a test injecting a naive `datetime(...)` gets a date off by one on a non-UTC host.

## Code Examples

### D-08 unified helper (new `weatherbot/weather/dates.py`)
```python
# Source: consolidation of models.py:69, store.py:210, uvmonitor.py:84 (+ D-06)
"""One tz-correct local-date helper (D-08). Pure, dependency-free (no config/
apscheduler/store import) — mirrors scheduler/days.py so it stays acyclic."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from weatherbot.config.models import Location

def _as_utc_aware(now_utc: datetime) -> datetime:
    """D-06/F33: treat a naive instant as UTC — never host-local via astimezone()."""
    return now_utc.replace(tzinfo=timezone.utc) if now_utc.tzinfo is None else now_utc

def local_date_iso(now_utc: datetime, tz: ZoneInfo | timezone) -> str:
    """Core primitive: local YYYY-MM-DD for now in tz (uvmonitor signature)."""
    return _as_utc_aware(now_utc).astimezone(tz).date().isoformat()

def _resolve_tz(tz_name: str | None) -> ZoneInfo | timezone:
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            return timezone.utc          # dead post-Plan-03 (tz required); explicit invariant
    return timezone.utc

def local_date_for(location: Location, now_utc: datetime) -> str:
    """Location-resolving wrapper (models/store signature)."""
    return local_date_iso(now_utc, _resolve_tz(getattr(location, "timezone", None)))
```
Then `models.py`/`store.py` replace their local `_local_date_iso(loc, now_utc)` with `local_date_for(loc, now_utc)`; `uvmonitor.py` replaces its `_local_date_iso(now_utc, tz)` with `local_date_iso(now_utc, tz)`. **Import-cycle check (verified):** `dates.py` imports only stdlib + a `TYPE_CHECKING`-only `Location`; `models`/`store`/`uvmonitor` already import from `weather.uv`, `weather.store`, `scheduler.catchup` — none import `weather.dates`, so adding it is a leaf, no cycle.

### D-07 sort points (F32) in `uv._today_daytime_points`
```python
# Source: uv.py:145 — one line before `return tuple(points)`
    points.sort(key=lambda p: p[0])   # D-07/F32: time-sorted before interpolation
    return tuple(points)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 2.5 `weather`/`forecast` bucket aggregation for high/low | One Call 3.0 `daily[0]` ready aggregates | v2 migration (Plan 02-01) | This phase cleans the residue: `daily[0]` must be verified-today, not positional. |
| Per-file `_local_date_iso` copies | ONE shared pure helper | This phase (D-08) | Rendered `{date}` and stored `local_date` can no longer diverge. |
| All-clear on instantaneous dip | Window-end/persistence hysteresis | This phase (D-03) | No premature "protect window over". |

**Deprecated/outdated:** none introduced. The dead UTC-fallback branches (`Location.timezone` is required/IANA-validated at load) are reconciled by D-06 — kept as an explicit belt-and-suspenders invariant in the one helper rather than three silent copies.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Location.timezone` is required + IANA-validated at config load, so the UTC-fallback branch is dead in production | D-06 reconciliation | LOW — even if a blank tz slipped through, the helper falls back to UTC (same as today); no new failure. Verified indirectly: `config/models.py` imports `ZoneInfo` + validators; CONTEXT D-06 states it as fact. |
| A2 | Persistence-counter durable state is undesirable this phase (would add a store table, brushing F36/F37 deferral) | D-03 fallback | LOW — mitigated by recommending the STATELESS window-end primary gate; the counter is fallback-only for empty-hourly, where degrading to "don't post yet" is acceptable. |
| A3 | Unifying `_local_date_iso` produces byte-identical `local_date` strings for existing correct rows (no migration) | Runtime State Inventory | LOW — all three copies compute `now.astimezone(tz).date().isoformat()`; only naive/invalid-tz edge cases (bugs) change. Confirmed by reading all three. |

**All three assumptions are LOW-risk and self-mitigating; none require a user checkpoint before planning.** The DST-fold, prior-day-compose, daily-selector, and import-cycle claims are all VERIFIED (live probe / source read), not assumed.

## Open Questions (RESOLVED)

1. **Persistence-counter durable state (D-03 fallback only)**
   - What we know: primary window-end gate is stateless and sufficient for the CONFIRMED F15 scenario; the tick default is 900s.
   - What's unclear: whether ANY sub-threshold-persistence path needs durable cross-tick state, or whether degrading to "don't post all-clear until window_end" fully covers the empty-hourly edge.
   - Recommendation: ship the stateless primary; for empty-hourly, do NOT post all-clear (defer to next-day reset) rather than add a counter table. Planner picks; researcher recommends no new table this phase.
   - **RESOLVED (planner discretion):** in plan **32-05** as the STATELESS all-clear gate reading `UvSummary.window_end`/`peak_time` from the same `compute_uv` result (`below AND past_peak AND window_over`); empty/missing `hourly[]` (window_end/peak_time None) degrades to "don't post all-clear yet" (defer to next-day reset). NO new counter/store table added (F36/F37 stay deferred).

2. **Whether to extract ONE shared today-entry selector vs apply the WR-05 guard at each site (D-05)**
   - What we know: three sites now do date-vs-position reasoning (`models`, `compute_uv`, and the monitor's existing `_daily0_matches_today`).
   - What's unclear: whether the selector lives in the new `dates.py`, in `uv.py`, or a small shared module.
   - Recommendation: put `select_today_daily` alongside the tz helper (pure, dependency-free) or in `uv.py` (where `compute_uv` already lives). Lean toward one shared selector per CONTEXT D-05 discretion.
   - **RESOLVED (planner discretion):** ONE shared `select_today_daily(daily, tz, local_date)` selector lives in the pure, dependency-free `weatherbot/weather/dates.py` (plan **32-02**), imported by `models.from_payloads`, `uv._today_daytime_points` (the F31 window bound), and `uv.compute_uv` (plan **32-04**) — no per-site duplicated guard.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python `zoneinfo`/`datetime` | all tz math | ✓ (stdlib) | 3.12+ | — |
| `apscheduler` | CronTrigger fold agreement (verify only) | ✓ | 3.11.2 | — |
| `pytest` + fixtures | regression tests | ✓ | installed | — |
| tzdata (IANA `America/New_York`, `America/Los_Angeles`) | DST tests | ✓ (probe succeeded) | system | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — this is a stdlib/existing-package phase.

## Validation Architecture

Nyquist validation is enabled (no `workflow.nyquist_validation: false` in config).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (installed via uv) |
| Config file | `pyproject.toml` (pytest config) / `tests/conftest.py` (fixtures: `tmp_db`, `load_fixture`) |
| Quick run command | `uv run pytest tests/test_scheduler.py tests/test_uv_monitor.py tests/test_models.py tests/test_uv.py -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HARD-TZ-01 | 23:45 slot recovered at 00:15 next local day → exactly ONE MissedSlot keyed on YESTERDAY | unit | `uv run pytest tests/test_scheduler.py::test_catchup_prior_local_day -x` | ❌ Wave 0 (new) |
| HARD-TZ-01/F91 | fall-back 01:30 slot minutes-late inside repeated hour → still due (grace not inflated), agrees with CronTrigger fold=0 | unit | `uv run pytest tests/test_scheduler.py::test_catchup_fold_grace_not_inflated -x` | ❌ Wave 0 (new; extends `test_dst_transition_band_exactly_once`) |
| HARD-TZ-02 | momentary UV dip at solar noon (5.8<6.0) then climb back → all-clear NOT posted | unit | `uv run pytest tests/test_uv_monitor.py::test_allclear_not_latched_on_momentary_dip -x` | ❌ Wave 0 (new) |
| HARD-TZ-02/D-04 | full-day tick sequence → prewarn/crossing/all-clear each post exactly once, no never-fire state | unit | `uv run pytest tests/test_uv_monitor.py::test_lifecycle_full_day_no_never_fire_gap -x` | ❌ Wave 0 (new) |
| HARD-TZ-03 | payload whose `daily[0]` is dated YESTERDAY → briefing degrades (no yesterday numbers as today) | unit | `uv run pytest tests/test_models.py::test_daily0_not_today_degrades -x` | ❌ Wave 0 (new; F109) |
| HARD-TZ-03/F31 | `compute_uv` with `daily[0]`=yesterday → does not falsely report stays_below for a real today crossing | unit | `uv run pytest tests/test_uv.py::test_compute_uv_daily0_today_guard -x` | ❌ Wave 0 (new) |
| HARD-TZ-03/F32 | out-of-order hourly buckets → crossing/window computed on time-sorted points | unit | `uv run pytest tests/test_uv.py::test_hourly_points_sorted_before_interpolation -x` | ❌ Wave 0 (new) |
| HARD-TZ-03/F33 | naive `now_utc` near midnight on a non-UTC assumption → local_date not shifted a day | unit | `uv run pytest tests/test_models.py::test_naive_now_utc_treated_as_utc -x` | ❌ Wave 0 (new) |
| HARD-TZ-04 | `models`, `store`, `uvmonitor` all call the ONE `dates` helper; identical output for same `(now,tz)` | unit + import-hygiene | `uv run pytest tests/test_import_hygiene.py -k dates -x` + a same-output test | ❌ Wave 0 (new) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_scheduler.py tests/test_uv_monitor.py tests/test_models.py tests/test_uv.py -x -q`
- **Per wave merge:** `uv run pytest -q` (full suite)
- **Phase gate:** full suite green before `/gsd-verify-work`; plus a live-daemon Gate-1 note (below).

### Wave 0 Gaps
- [ ] `tests/test_scheduler.py::test_catchup_prior_local_day` — HARD-TZ-01 (F14), failing-first: 23:45→00:15 recovery keyed on yesterday.
- [ ] `tests/test_scheduler.py::test_catchup_fold_grace_not_inflated` — HARD-TZ-01/F91, fall-back-hour grace, CronTrigger fold=0 agreement.
- [ ] `tests/test_uv_monitor.py::test_allclear_not_latched_on_momentary_dip` — HARD-TZ-02 (F15), failing-first.
- [ ] `tests/test_uv_monitor.py::test_lifecycle_full_day_no_never_fire_gap` — HARD-TZ-02/D-04 state-machine walk.
- [ ] `tests/test_models.py::test_daily0_not_today_degrades` + `::test_naive_now_utc_treated_as_utc` — HARD-TZ-03 (F109/F35/F33).
- [ ] `tests/test_uv.py::test_compute_uv_daily0_today_guard` + `::test_hourly_points_sorted_before_interpolation` — HARD-TZ-03 (F31/F32).
- [ ] Shared-helper same-output test + import-hygiene assertion for `weather/dates.py` — HARD-TZ-04.
- Framework install: none — pytest + `tmp_db`/`load_fixture` fixtures already exist.

**Live-daemon Gate-1 note:** WeatherBot runs as a live systemd service (editable install on `yahir-mint`). The midnight/DST/all-clear paths are NOT deterministically drivable on a wall clock — verify them via injected-`now_utc` unit tests (Gate-1 mechanism proof), then do a clean `systemctl restart weatherbot` to confirm the new `dates.py` module loads and catch-up runs without error at boot. A true midnight-boundary live observation is a deferred Gate-2 milestone item (mark PARTIAL, not skipped), consistent with the two-gate policy.

## Security Domain

`security_enforcement` is not disabled in config (absent = enabled), but this phase's blast radius is date/time correctness on already-fetched data with no new inputs, sinks, or auth surface.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth code touched. |
| V3 Session Management | no | N/A (no sessions). |
| V4 Access Control | no | N/A. |
| V5 Input Validation | yes (defensive-degrade) | Existing `.get() or {}` / try-except coercion on payload timestamps (`int(ts)`, `_coerce_uvi`) — the daily-selector and hourly-sort MUST keep the same "malformed bucket → skip, never raise" posture (T-14-04 briefing-spine isolation). |
| V6 Cryptography | no | No crypto. |
| V7 Error Handling / Logging | yes | All new paths swallow-and-degrade like the existing UV/briefing spine; the OpenWeather `appid` redaction (Phase 30) is upstream and untouched — do not add a log line that could echo a payload URL. |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/adversarial One Call payload (`dt`/`sunrise`/`uvi` non-numeric, out-of-order, missing) | Tampering / DoS-via-crash | Keep the existing defensive coercion + skip-never-raise; the new selector/sort must not `int()`/subscript blind. |
| Wrong `local_date` key mis-routing dedup (duplicate briefing / re-spam) | Tampering (of exactly-once invariant) | D-01 candidate-day keying + D-08 single helper so render and store never diverge. |
| Secret leakage via a payload-bearing log line | Information Disclosure | No new logging of payloads/URLs; rely on Phase-30 redaction upstream. |

## Sources

### Primary (HIGH confidence)
- `weatherbot/scheduler/catchup.py` (read in full) — plan_catchup compose/gates `:139-178`. `[VERIFIED: source]`
- `weatherbot/scheduler/uvmonitor.py` (read in full) — `_daily0_matches_today` `:93-110`, `_decide` branches `:256-323`, tick `:326-393`. `[VERIFIED: source]`
- `weatherbot/weather/models.py` (read in full) — `_local_date_iso` `:69`, `from_payloads` `:266-392`, `daily[0]` hard-index `:302-303`. `[VERIFIED: source]`
- `weatherbot/weather/uv.py` (read in full) — `compute_uv` `:193`, `_today_daytime_points` `:98-146`, interpolation `:149-190`, `UvSummary` fields `:34-53`. `[VERIFIED: source]`
- `weatherbot/weather/store.py` (read in full) — `_local_date_iso` `:210`, `persist` `:227-264`, `claim_uv_alert`/`claimed_uv_kinds`. `[VERIFIED: source]`
- `weatherbot/weather/multiday.py` (read in full) — `_date_index_map` `:49-58`, `_resolve_tz` `:39-46`. `[VERIFIED: source]`
- `weatherbot/scheduler/days.py` (read in full) — acyclic-pure-helper precedent. `[VERIFIED: source]`
- `tests/test_scheduler.py:147-303` — injected-`now_utc` catch-up/DST test conventions. `[VERIFIED: source]`
- `tests/test_uv_monitor.py` (grep) — UV monitor test conventions (fixtures, `_run`, injected `now_utc`). `[VERIFIED: source]`
- Live `apscheduler 3.11.2` probe in repo `uv` env — CronTrigger fires fall-back 01:30 at `fold=0` (05:30 UTC, UTC-4). `[VERIFIED: live probe]`
- Live stdlib probe — prior-day compose UTC math + fold grace inflation scenario. `[VERIFIED: live probe]`
- `weatherbot/config/models.py:430` — `uv.interval_seconds` default 900 (tick cadence for persistence-N). `[VERIFIED: source]`

### Secondary (MEDIUM confidence)
- `.planning/phases/32-.../32-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` — locked decisions + acceptance criteria. `[CITED]`
- `CLAUDE.md` — One Call 3.0, APScheduler 3.x, "configured IANA tz authoritative" (D-03). `[CITED]`

### Tertiary (LOW confidence)
- None — no WebSearch-only claims. Every technical claim is source-read or live-probed.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; stdlib + installed packages verified present.
- Architecture: HIGH — every fix reuses an in-repo precedent read in full; import-cycle checked via grep.
- Pitfalls: HIGH — F14/F15 reproduction mechanics + F91 fold behavior verified with live probes.

**Research date:** 2026-07-11
**Valid until:** 2026-08-10 (stable — stdlib + pinned apscheduler 3.11.x; the codebase is the source of truth and is mature).
