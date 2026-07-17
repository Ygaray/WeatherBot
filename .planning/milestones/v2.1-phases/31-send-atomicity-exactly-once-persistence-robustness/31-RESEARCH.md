# Phase 31: Send Atomicity, Exactly-Once & Persistence Robustness - Research

**Researched:** 2026-07-10
**Domain:** Send-spine exactly-once semantics + SQLite concurrency/atomicity (Python `sqlite3`, tenacity retry, `DeliveryResult` never-raise contract)
**Confidence:** HIGH

## Summary

This is an audit-driven correctness phase with all decisions already locked in CONTEXT.md (D-01..D-08). The research target is therefore *"how to implement these cleanly against the real code"*, not *"which approach"*. Nearly all findings are **codebase-verified** (I read the exact source at every cited line) — the only external verification needed was the SQLite `sqlite3` WAL/`busy_timeout`/read-only idioms and the tenacity short-circuit behavior, both of which I ran against the live Python 3.12 interpreter in this project's `.venv` and confirmed. `[VERIFIED: codebase]` and `[VERIFIED: live interpreter]` tags below reflect that.

The five fixes are tightly coupled: **F01 (duplicate-send critical)** is the payoff, **HARD-STORE (WAL + busy_timeout + non-writing reads)** is its root de-risker (it removes the `database is locked`-after-delivery that makes F01 reachable), **F08** mirrors an existing `fire_slot` idiom onto `fire_forecast_slot`, **DELIV-03** hoists the fetch out of the retried unit, and **DELIV-04** classifies Discord 401/403 as auth. Two hard jurisdiction boundaries constrain the work: `DeliveryResult`, `Channel`, `is_transient`, `is_auth_failure`, and the entire `build_retrying` engine **live in the hub** (`yahir_reusable_bot`) — so the DELIV-04 auth carrier must be implemented **app-side** without a hub change, and F94/F04 (also hub-rooted) are explicitly out of scope.

**Primary recommendation:** Land HARD-STORE first (WAL + busy_timeout + a shared `_connect()` helper + a schema-init split so reads never write) as the structural de-risker, then the F01 restructure (with its reproduce-first regression), then F08/DELIV-03/DELIV-04. For DELIV-04, the cleanest no-hub-change carrier is: app-side `_post` **raises `httpx.HTTPStatusError` (with `.response` intact) on 401/403** so `fire_slot`'s *existing* `except httpx.HTTPStatusError` at `daemon.py:263` already maps it to `auth_failed` and the retry short-circuits in one attempt — this reuses the fetch-path contract exactly and preserves the Phase-30 `.response` type contract.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Move post-send bookkeeping OUT of the release-on-failure path.** Once `send` returns `result.ok`, the claim is the source of truth for "delivered" and MUST stay committed. `resolve_alert` / `stamp_success` become best-effort bookkeeping that can fail without releasing the claim — moved after/outside the `try` that guards `release_claim`, or wrapped in their own local `try/except` that logs-and-swallows (mirror `daemon.py:1029`). The `release_claim` + `internal_error` path must only be reachable for pre-delivery failures. A post-delivery bookkeeping error logs a warning and returns success; never re-fires, never alerts.
- **D-01a — Reproduce before fixing (roadmap mandate).** F01 is a SWEEP-NEW critical. Confirm first: a regression forcing a DB error in `resolve_alert`/`stamp_success` after a successful `send_now`, asserting the slot stays `was_sent()==True` (no duplicate, no false `internal_error`). Fix + failing-first test ship together.
- **D-02 — Mirror `fire_slot`: check `result.ok` from `channel.send()`.** In `fire_forecast_slot`, capture the `DeliveryResult` and branch on `ok`. On `ok=False`, route to `_note_forecast_failure` + the WR-05 dead-slot streak/CRITICAL/operator-alert escalation instead of `_note_forecast_success()`. Preserve isolation (a forecast failure never touches a briefing / never re-raises). Only a CLEAN delivery resets the streak.
- **D-03 — Fetch once, retry only the delivery.** A delivery-only failure must NOT trigger a fresh OpenWeather fetch on each retry. Structure the fire path so the fetch happens once and the retry/backoff wraps only the delivery step, reusing the in-memory payload.
- **D-04 — Discord 401/403 → auth reason, short-circuit the retry schedule.** Map a permanent send auth failure to `auth_failed`; must NOT burn the full two-burst schedule as transient. Carrier (extend `DeliveryResult` vs. raise an auth-classified error) is planner/researcher discretion — but the Phase-30 exception-TYPE contract (`httpx.HTTPStatusError` with `.response` intact) must not regress.
- **D-05 — Open SQLite in `WAL` mode** (`PRAGMA journal_mode=WAL`, persistent — set once at init/first connect).
- **D-06 — Set a `busy_timeout` on every connection** (`PRAGMA busy_timeout=<ms>`, a few seconds order-of-magnitude; planner pins the exact ms).
- **D-07 — Reads must not take a write lock (F10).** Separate schema bootstrap from the read path: `INSERT OR IGNORE` seed rows must not run on every read connect. One-time `init`/`ensure_schema`; read functions (`was_sent`, `read_heartbeat`, `read_health`, `claimed_uv_kinds`) open a read-only/no-write connection and do NOT `executescript` the seeding DDL.
- **D-08 — Multi-step writes are atomic/transactional.** No truncate-then-write, no force-commit-before-insert corruption window. Covers the `weather_onecall` store write specifically (HARD-STORE-01).

### Claude's Discretion

- **Shared connect helper** — centralize `WAL` + `busy_timeout` (+ read-only vs. read-write) behind one `_connect(...)` in `store.py` (lean toward one helper — 14 sites currently repeat `executescript(_SCHEMA)`).
- **Auth-classification carrier** for DELIV-04 (typed `DeliveryResult` field vs. raised auth-classified error) — pick the form that fits `fire_slot`'s classification switch most cleanly without regressing the Phase-30 type contract.
- **Exact `busy_timeout` value** and WAL-via-PRAGMA-on-connect vs. one-time migration — pick per SQLite idiom.
- **Retry-scope refactor shape** for D-03 (fetch/deliver boundary in `send_now`/`fire_slot`) — minimal restructure that keeps the two-burst schedule and the D-02/Pitfall-2 "one transient unit per Discord ok=False".

### Deferred Ideas (OUT OF SCOPE)

- **F94 `is_transient` gap (hub)** — `RemoteProtocolError`/`WriteError` not retried. Root is `yahir_reusable_bot/reliability/retry.py:87`; routes upstream, human-gated. Related to DELIV-04 but NOT fixed here.
- **F04 SIGTERM-drain (hub)** — tenacity ignoring `Event.wait()` return; root in hub `retry.py:241`. Routes upstream.
- **F91 DST fall-back fold math** in catch-up — Phase 32 (timezone/date-boundary).
- **F13 cache-invalidation race** and **F02 bare-command crash** — Phase 33 (interactive/panel).
- **Full regression-test backfill** (real concurrent double-fire, store data-loss path) — Phase 34. Fixes here must be test-shaped, but the comprehensive suite is Phase 34's job.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-DELIV-01 | Post-send bookkeeping cannot release an already-delivered claim (F01, verify first) | §Pattern 1 (F01 restructure) + §Code Examples (reproduce test) — exact try/except shape at `daemon.py:182-379` mapped; `daemon.py:1029` swallow analog cited |
| HARD-DELIV-02 | Forecast-slot delivery failures detected & alerted (F08) | §Pattern 2 — capture `DeliveryResult` from `daemon.py:539`, branch on `.ok`, route to `_note_forecast_failure` (`daemon.py:399`) |
| HARD-DELIV-03 | Retry reuses fetched payload, no re-fetch (F13-adjacent) | §Pattern 3 — fetch/deliver boundary is `cli.py:196` (fetch) vs `cli.py:208` (deliver), both inside the retried `_attempt` at `daemon.py:247-262` |
| HARD-DELIV-04 | Send failures classified auth vs transient (F48) | §Pattern 4 — app-side raise of `httpx.HTTPStatusError` on 401/403; `fire_slot` `except` at `daemon.py:263` already maps it; verified short-circuits in 1 attempt |
| HARD-STORE-01 | Atomic writes + guarded read/write races | §Pattern 5/6 — `persist` (`store.py:202-226`) already single-transaction INSERT (no truncate); the risk is the shared-schema re-exec, not `persist` itself |
| HARD-STORE-02 | WAL + busy_timeout so no `database is locked` (de-risks HARD-DELIV-01) | §Pattern 5 — verified idioms; live DB currently `journal_mode=delete`, `busy_timeout=0` |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Send atomicity / exactly-once claim lifecycle | App scheduler (`weatherbot/scheduler/daemon.py`) | App store (`weatherbot/weather/store.py`) | The claim/release/bookkeeping orchestration is app-specific weather-briefing logic; it lives in `fire_slot`. The store provides the atomic `claim_slot`/`release_claim` primitives it composes. |
| Retry / backoff / classification engine | **Hub** (`yahir_reusable_bot.reliability.retry`) | App (`weatherbot.reliability.retry` re-export shim) | `build_retrying`, `is_transient`, `is_auth_failure`, `DeliveryResult` are all hub-owned. DELIV-04's carrier must be app-side because changing the retry predicate or `DeliveryResult` shape is a hub change (human-gated). |
| Delivery channel (Discord webhook) | App (`weatherbot/channels/discord.py`) | Hub (`Channel`/`DeliveryResult` ABC) | The Discord `_post` HTTP→result mapping is app-side; the never-raise `Channel.send` contract is hub-defined. DELIV-04 adds auth classification *inside the app `_post`* without touching the hub ABC. |
| SQLite persistence / concurrency (WAL, busy_timeout, schema init) | App store (`weatherbot/weather/store.py`) | — | The store is entirely app-side. All 14 connect sites and `_SCHEMA` are here; a shared `_connect()` helper is a pure app-side consolidation. |
| Fetch/render pipeline (the payload D-03 must reuse once) | App CLI core (`weatherbot/cli.py:send_now` → `lookup_weather`) | App weather (`weatherbot/weather/*`) | The fetch (`lookup_weather`) and deliver (`send_briefing`) both live inside `send_now`; D-03 splits that boundary app-side. |

## Standard Stack

No new dependencies. This phase is entirely restructuring of existing app code plus SQLite PRAGMAs. The relevant installed stack (verified from `.venv/.../dist-info`):

### Core (already installed — no install step)
| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sqlite3` (stdlib) | Python 3.12 | The store engine; WAL + busy_timeout PRAGMAs, read-only URI connect | Stdlib; no dependency. WAL is the canonical SQLite concurrency mode. `[VERIFIED: live interpreter]` |
| `tenacity` | 9.1.4 | Retry engine primitives (via hub `build_retrying`) | Already the two-burst engine; DELIV-04 rides its existing short-circuit-on-non-transient behavior `[VERIFIED: codebase]` |
| `httpx` | 0.28.1 | HTTP + `HTTPStatusError` (the Phase-30 type contract DELIV-04 must preserve) | The `.response`-carrying exception is app-wide currency `[VERIFIED: codebase]` |
| `discord-webhook` | 1.4.1 | Discord delivery; `_post` maps its HTTP status | The 401/403 source F48/DELIV-04 classifies `[VERIFIED: codebase]` |
| `yahir_reusable_bot` (hub, pinned) | 0.1.0 (@ v0.1.1 tag) | `DeliveryResult`, `Channel`, `is_transient`, `is_auth_failure`, `build_retrying` | **Hub-owned — do not modify. DELIV-04 carrier stays app-side.** `[VERIFIED: codebase]` |

**Installation:** None. `PRAGMA journal_mode=WAL` on the live DB is a runtime/migration action (see Environment Availability + Pitfalls), not a package.

## Architecture Patterns

### System Architecture Diagram

```
                      APScheduler worker thread (one per fire)
                                   │
                   ┌───────────────┴───────────────┐
                   ▼                               ▼
            fire_slot(...)                 fire_forecast_slot(...)
         (daemon.py:150-379)              (daemon.py:464-579)
                   │                               │
   ┌───────────────┼──────────────────┐           │  (read-only, NO claim)
   ▼               ▼                  ▼            ▼
resolve config  claim_slot        build_retrying  lookup_forecast (reuse payload)
(:190)          (:210, ATOMIC)    (:240, HUB)          │
   │               │                  │                ▼
   │            [claimed=True]   ┌─────┴──────┐   channel.send(reply.text)
   │               │            _attempt (:247)     │  ◄── F08: DeliveryResult
   │               │             │                  │      currently IGNORED
   │               │      ┌──────┴───────┐          ▼
   │               │   FETCH (once)    DELIVER  branch on result.ok
   │               │  lookup_weather  send_briefing   │
   │               │  cli.py:196 ◄────┤ cli.py:208     ├── ok  → _note_forecast_success
   │               │  D-03: HOIST     │                └── !ok → _note_forecast_failure
   │               │  fetch OUT of    │                        (WR-05 dead-slot escalate)
   │               │  the retried unit│
   │               │                  ▼
   │               │            result = retrying(_attempt)  (:262)
   │               │                  │
   │      ┌────────┴──────────────────┼─────────────────────────────┐
   │      ▼ (pre-delivery failure)    ▼ (result.ok=True)             ▼ (except httpx)
   │   release_claim + alert    ═══ CLAIM IS TRUTH ═══         auth_failed vs
   │   (:266/:289/:315)          F01: resolve_alert (:339)     transient_exhausted
   │   internal_error (:349)     + stamp_success (:340)        (:263-271)
   │                             MUST NOT be able to           ◄── DELIV-04:
   │                             reach release_claim (:356)        _post raises
   │                             → wrap in log-and-swallow         HTTPStatusError
   │                                (mirror :1029)                 on 401/403
   ▼
 store.py  ── every fn opens sqlite3.connect + executescript(_SCHEMA)  (14 sites)
             _SCHEMA ends in INSERT OR IGNORE  ◄── F10: takes a WRITE lock on READS
             ── HARD-STORE: _connect() helper (WAL + busy_timeout),
                schema-init split so reads use mode=ro / skip DDL
```

### Pattern 1: F01 — post-delivery bookkeeping cannot release the claim (D-01)

**What:** The current `fire_slot` (`daemon.py:150-379`) wraps the ENTIRE lifecycle in one outer `try` opened at `:182`. After `result = retrying(_attempt)` succeeds with `result.ok=True`, `resolve_alert(...)` (`:339`) and `stamp_success(...)` (`:340`) run **inside that same outer try**. If either raises (a realistic `database is locked` OperationalError post-delivery), control falls to the broad `except Exception` at `:349`, which — because `claimed=True` — calls `release_claim` at `:356` (DELETEing the `sent_log` row) and records a false `internal_error` alert. The briefing was already delivered; the slot is now re-fireable → duplicate on catch-up/restart. `[VERIFIED: codebase — daemon.py:335-379]`

**When to use:** The success tail only.

**Minimal safe restructure:** After `result.ok` is confirmed, wrap the two bookkeeping calls in their own local `try/except` that logs-and-swallows and does NOT release — exactly the established idiom at `daemon.py:1029` ("SWALLOWED so it can NEVER abort an already-committed reload"). The `release_claim` at `:356` then remains reachable only for genuine pre-delivery failures.

```python
# Source: proposed shape, modeled on the VERIFIED daemon.py:1029 idiom
# ── success tail (currently daemon.py:339-348) ──
# result.ok is True here: the claim is now the source of truth for "delivered".
# Best-effort bookkeeping — a DB error here must NEVER release the claim (D-01).
try:
    resolve_alert(db_path, location.id, slot.time, local_date)
    stamp_success(db_path)
except Exception:  # noqa: BLE001 — best-effort; delivery already committed (F01/D-01)
    _log.warning(
        "post-send bookkeeping failed; briefing already delivered, claim kept",
        location=location.name, time=slot.time,
    )
_log.info("slot fired", location=location.name, time=slot.time,
          late=late, delivered=result.ok)
return result
```

Two equivalent shapes are acceptable (D-01 names both): (a) the local `try/except` above, still inside the outer try — simplest, smallest diff; or (b) move the bookkeeping to *after* the outer `try/except` so it structurally cannot reach `release_claim`. **Recommend (a)** — it is the minimal diff, mirrors the exact `:1029` precedent, and keeps the `return result` inside the function's existing control flow. Either way the invariant is: **no code path after `result.ok` can call `release_claim`.**

**Reproduce-first (D-01a mandate):** see §Code Examples for the injection test.

### Pattern 2: F08 — inspect the forecast `DeliveryResult` (D-02)

**What:** `fire_forecast_slot` (`daemon.py:464`) calls `channel.send(reply.text)` at `:539` but **discards the returned `DeliveryResult`**, then unconditionally calls `_note_forecast_success(location, fc)` at `:543`. A Discord `ok=False` (non-2xx) therefore resets the streak and the WR-05 dead-slot escalation (which lives only in the `except` branch at `:552-579`) never fires. `[VERIFIED: codebase — daemon.py:538-543]`

**When to use:** The forecast send path.

```python
# Source: proposed, mirroring fire_slot's own result.ok inspection (VERIFIED daemon.py:314)
if channel is not None:
    fc_result = channel.send(reply.text)
    if fc_result is not None and not fc_result.ok:
        # ok=False is a real (non-raising) delivery failure — route to the SAME
        # dead-slot escalation the except branch uses (WR-05), NOT success.
        _note_forecast_failure(location, fc, channel=channel)
        _log.warning("forecast slot delivery failed",
                     location=location.name, kind=fc.kind, variant=fc.variant,
                     time=fc.time, detail=getattr(fc_result, "detail", ""))
        return None
# Only a CLEAN delivery resets the streak (D-02).
_note_forecast_success(location, fc)
```

Note `_note_forecast_failure` already exists (`daemon.py:399-439`) and already self-guards its channel post — reuse it verbatim; do not duplicate the escalation logic. Preserve the "never re-raise out of the slot" isolation: the `ok=False` branch returns `None` normally, it does not raise.

### Pattern 3: DELIV-03 — fetch once, retry only the delivery (D-03)

**What:** In `fire_slot`, `_attempt` (`daemon.py:247-259`) calls `send_now(...)`, and `send_now` (`cli.py:142`) does **both** the fetch (`lookup_weather` at `cli.py:196`) **and** the deliver (`channel.send_briefing` at `cli.py:208`) in one call. Because `retrying(_attempt)` (`daemon.py:262`) re-invokes `_attempt` on each retry, **every retry re-runs `lookup_weather` = a fresh dual OpenWeather fetch** (2 calls per attempt, up to 16 attempts). `[VERIFIED: codebase — cli.py:196,208 inside daemon.py:247 _attempt]`

**Tension to preserve:** `cli.py:211-216` documents that the fetch is *deliberately* inside the retried callable today so a fetch-429 `httpx.HTTPStatusError` (carrying `Retry-After`) still propagates to the two-burst wait callable (RELY-02). Any hoist must keep the fetch-429 → Retry-After path working. The clean resolution: **the fetch is retried by its own concern (fetch failures ARE fetch failures), but a DELIVERY-only failure must not re-fetch.** The minimal restructure that satisfies both:

**Recommended shape:** Split `send_now`'s body so `fire_slot` fetches **once, outside** the delivery retry, then wraps **only** the delivery in `retrying`. A fetch exception still propagates (fetch happens once, before the retry loop, and its own transient handling can stay as-is or be retried separately). Concretely, extract the deliver+persist tail (`cli.py:205-224`) into a `deliver(forecast, text)` callable and have `fire_slot` do:

```python
# Source: proposed minimal restructure (fetch/deliver boundary at cli.py:196 vs :208)
lookup = lookup_weather(location.name, config=snapshot, ...)   # ONCE (D-03)
def _deliver() -> DeliveryResult:
    result = channel.send_briefing(lookup.text, lookup.forecast)
    if result.ok:
        persist(db_path, lookup.location, lookup.forecast)      # persist only on ok (WR-04, unchanged)
    return result
result = retrying(_deliver)   # retry wraps ONLY delivery — reuses the one fetched payload
```

**Pitfall to honor (D-02/Pitfall-2):** a Discord `ok=False` is ONE transient unit — the `retry_if_result(lambda r: not r.ok)` predicate already treats it that way (`retry.py:238`), and the Discord channel owns its own within-attempt 429 wait (`rate_limit_retry=True`, `discord.py:83`). Do not add a second retry layer. `[VERIFIED: codebase — retry.py:26-32,238]`

**Scope caution:** hoisting the fetch out of the retry changes the fetch-429 Retry-After honoring surface (that path currently rides the same two-burst loop). The planner should decide whether fetch-429 retries stay (a) inside a separate fetch-retry that still exists, or (b) are acceptable-to-drop for the DAEMON path given the ready-gate already validates the key. **This is the highest-subtlety part of the phase** — flag it for a plan checkpoint and keep the existing `tests/test_send_now.py` contract green. `[ASSUMED — the exact fetch-retry disposition is a design choice within D-03; A1 below]`

### Pattern 4: DELIV-04 — Discord 401/403 → auth, no hub change (D-04)

**What:** `discord.py:_post` (`:72-115`) maps ALL non-2xx (incl. 401/403) to `DeliveryResult(ok=False, detail=f"{status} {snippet}")` at `:115` and never raises. The hub retry predicate `retry_if_result(lambda r: not r.ok)` (`retry.py:238`) then retries it as a transient for the full ~65-min schedule, and `fire_slot`'s non-ok exhaustion branch (`daemon.py:314`) records `transient_exhausted`. `[VERIFIED: codebase — discord.py:106-115, retry.py:238, daemon.py:314]`

**Jurisdiction constraint:** `DeliveryResult` is defined in the **hub** (`yahir_reusable_bot/channels/base.py:19-30` — just `ok: bool` + `detail: str`). Adding a typed `classification` field, OR changing the retry predicate to skip auth results, is a **hub change → human-gated → out of scope.** So the carrier must be **app-side only.**

**Recommended carrier (no hub change, preserves Phase-30 contract):** app-side `_post` **raises `httpx.HTTPStatusError` with `.response` intact on 401/403**, and returns `DeliveryResult(ok=False)` for every *other* non-2xx as today. Rationale, all VERIFIED:
1. `is_transient(exc)` returns **False** for a 401/403 `HTTPStatusError` (`PERMANENT = {400,401,403,404}`, `retry.py:71,89-91`), so `build_retrying`'s `retry_if_exception(is_transient)` does not retry it → **short-circuits in exactly 1 attempt.** `[VERIFIED: live interpreter — 1 attempt, reraise intact]`
2. `fire_slot` **already** catches this: `except httpx.HTTPStatusError as exc:` at `daemon.py:263`, maps `is_auth_failure(exc)` → `REASON_AUTH_FAILED` at `:268-271`. **Zero new classification code in the daemon.** `[VERIFIED: codebase]`
3. The exception carries `.response.status_code` — identical to the fetch path — so the Phase-30 "`httpx.HTTPStatusError` with `.response` intact" type contract is **preserved, not regressed.** `[VERIFIED: live interpreter — resp.status_code==403 after raise-through-retry]`

**Contract caveat:** this *does* make `send` raise on a 401/403, which is a narrowing of the "never raises on non-2xx" docstring. That is acceptable and intended here: 401/403 is not a normal expected failure, it is a permanent misconfiguration, and the fetch path already treats it this way. Keep the never-raise contract for all *transient* non-2xx (429/5xx/network) — those still return `ok=False`. Construct the raised error from the `requests.Response` the webhook returns; map its `status_code` into an `httpx.Response`/`httpx.Request` pair so `.response.status_code` is a plain int (the classifiers only read `.response.status_code`). Verify `discord_webhook`'s `execute()` returns a `requests.Response` with `.status_code` (it does — `discord.py:101` already reads `getattr(response, "status_code", None)`). `[VERIFIED: codebase]`

**Alternative carrier (also app-side):** raise a small app-side `SendAuthError(status)` that `is_transient` returns False for (verified short-circuits in 1 attempt), and add ONE `except SendAuthError` arm in `fire_slot` mapping to `REASON_AUTH_FAILED`. This avoids synthesizing an `httpx.Response` but adds a new daemon `except` arm. **Prefer the `httpx.HTTPStatusError` carrier** — it reuses the *existing* `except` at `daemon.py:263` and is byte-identical to the fetch-path contract. `[VERIFIED: live interpreter — both carriers short-circuit in 1 attempt]`

### Pattern 5: HARD-STORE — WAL + busy_timeout + shared `_connect()` (D-05/D-06)

**What:** All 14 `sqlite3.connect(db_path)` sites in `store.py` open with the **default rollback journal** and **no busy_timeout override**, and every one runs `conn.executescript(_SCHEMA)`. `_SCHEMA` ends with two `INSERT OR IGNORE INTO heartbeat/health` (`store.py:143-144,152-153`), which `executescript` force-commits and which acquire a RESERVED/write lock. Live DB confirmed `journal_mode=delete`, `busy_timeout=0`. `[VERIFIED: live DB — data/weatherbot.db]`

**Verified idioms (all run against this project's Python 3.12 sqlite3):**
- `PRAGMA journal_mode=WAL` is **persistent** — set once, survives reopen (returns `'wal'` on a fresh connect). `[VERIFIED: live interpreter]`
- `PRAGMA busy_timeout=<ms>` is **per-connection** — must be set on every connect; returns the set value. `[VERIFIED: live interpreter]`
- WAL creates `-wal` and `-shm` sidecar files next to the db. `[VERIFIED: live interpreter]`
- `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` opens read-only; a write raises `OperationalError: attempt to write a readonly database`. `[VERIFIED: live interpreter]`

**Recommended `_connect()` helper (consolidates all 14 sites):**

```python
# Source: proposed; all idioms VERIFIED against this project's sqlite3
def _connect(db_path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")   # D-06: per-connection, ~5s (see below)
    return conn

def init_db(db_path) -> None:
    """One-time schema bootstrap + WAL (D-05/D-07). Owns _SCHEMA + seed rows."""
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")   # D-05: persistent, set once
        conn.executescript(_SCHEMA)               # CREATE ... + INSERT OR IGNORE seeds
        conn.commit()
```

**`busy_timeout` value (D-06):** the contention profile is ~10 briefing workers + the heartbeat tick + the UV monitor. With WAL, readers never block the single writer and vice-versa, so the *only* residual contention is writer-vs-writer (two fires committing at once). A **5000 ms (5s)** timeout is the recommended order-of-magnitude: it comfortably absorbs any writer-vs-writer wait (a commit is sub-millisecond) while staying well under the two-burst schedule's per-attempt spacing, and it matches SQLite's own historical 5s default so it is a conservative, well-understood value. Under WAL, in practice contention essentially disappears; the timeout is belt-and-suspenders. `[VERIFIED: live interpreter for the mechanism; 5000ms is a reasoned recommendation — planner may pin lower/higher]`

**Read-only vs. read-write split (D-07):** the four read fns (`was_sent` `:229`, `read_heartbeat` `:490`, `read_health` `:508`, `claimed_uv_kinds` `:389`) should open with `read_only=True` and **must not** `executescript(_SCHEMA)`. Because `init_db` now owns the schema + seed rows and runs once at startup, the seed rows (`heartbeat`/`health` `id=1`) already exist by the time any read runs, so the reads' current "tolerate a never-initialized db" behavior is replaced by "startup guarantees the schema exists." Update the docstrings so "READ-ONLY: writes nothing" is TRUE. `[VERIFIED: codebase — 4 read fns identified]`

### Pattern 6: HARD-STORE-01 — atomic multi-step writes (D-08)

**What / important nuance:** I inspected the `weather_onecall` write (`persist`, `store.py:186-226`). It is **already** a single `with sqlite3.connect(...)` block that does `executescript(_SCHEMA)` then two `INSERT INTO weather_onecall ... VALUES(?)` and one `conn.commit()` — **no truncate-then-write, no force-commit-before-insert.** The two inserts already commit as one transaction. `[VERIFIED: codebase — store.py:202-226]`

So HARD-STORE-01's "no truncate-then-write / no corruption window" is **largely already satisfied** for `weather_onecall`. The residual work is:
1. Route `persist` through `_connect()` (drop the per-write `executescript(_SCHEMA)` now that `init_db` owns it), keeping the two inserts + commit atomic.
2. Audit the *other* write fns (`claim_slot` `:251`, `release_claim` `:291`, `record_alert` `:317`, `claim_uv_alert` `:351`, `resolve_alert` `:411`, `stamp_tick` `:436`, `stamp_success` `:453`, `stamp_health` `:468`) — each is a single statement + commit, so each is already atomic; the change is purely dropping the per-connect `executescript` and using `_connect()`.

**Recommendation:** treat HARD-STORE-01 as "confirm atomicity + remove the redundant per-connect schema re-exec," not "rewrite a truncate-then-write" (there is none). Note this explicitly in the plan so the checker doesn't hunt for a non-existent truncate bug.

### Anti-Patterns to Avoid

- **Do NOT extend `DeliveryResult` with a classification field** — it lives in the hub; that's a human-gated hub change. Keep DELIV-04 app-side.
- **Do NOT change the hub `retry` predicate** to skip auth results — same reason.
- **Do NOT touch `is_transient`/`is_auth_failure`** — hub-owned (F94 is the deferred hub fix; do not "helpfully" fix it here).
- **Do NOT move the whole outer `try` body after the send** — only the bookkeeping tail moves/wraps; the pre-delivery release path must stay intact.
- **Do NOT add a second retry layer** around the Discord `ok=False` — it's one transient unit (`rate_limit_retry=True` owns within-attempt 429s).
- **Do NOT leave reads calling `executescript(_SCHEMA)`** — that's the F10 write-lock-on-read defect itself.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Concurrent read/write locking | A Python-level mutex around store calls | SQLite `WAL` + `busy_timeout` | WAL makes readers non-blocking to the writer at the engine level; a Python lock can't coordinate across the daemon + status-command + future processes. `[VERIFIED: live interpreter]` |
| Auth-vs-transient classification | A new status-code table in the app | Existing hub `is_auth_failure`/`is_transient` + `PERMANENT`/`TRANSIENT` frozensets | Already the app-wide taxonomy; DELIV-04 just feeds a `.response`-carrying exception into it. `[VERIFIED: codebase]` |
| Log-and-swallow bookkeeping | A bespoke error wrapper | The existing `daemon.py:1029` idiom (`try/except` + `_log.warning`) | D-01 explicitly names it as the analog; consistency + proven shape. `[VERIFIED: codebase]` |
| Dead-slot escalation for forecasts | New alert logic in the ok=False branch | Existing `_note_forecast_failure` (`daemon.py:399`) | It already does the WR-05 streak/CRITICAL/throttled-operator-alert with its own self-guarded post. `[VERIFIED: codebase]` |
| Retry-on-fetch-failure | A new backoff loop | The existing two-burst `build_retrying` | Already handles fetch transients + Retry-After; D-03 just changes *what* is inside the retried unit. `[VERIFIED: codebase]` |

**Key insight:** almost every mechanism this phase needs already exists in the codebase — the work is *re-wiring existing primitives* (moving the bookkeeping, capturing an already-returned result, hoisting a fetch, feeding an exception to an existing classifier, consolidating connect sites), not building new machinery.

## Runtime State Inventory

> This phase changes the SQLite journal mode on a **live, systemd-managed** DB. Runtime state matters.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `data/weatherbot.db` (1.25 MB) — currently `journal_mode=delete`, `busy_timeout=0` `[VERIFIED: live DB]`. Tables: `weather_onecall`, `sent_log`, `alerts`, `uv_alerts`, `heartbeat`, `health` (+ retained legacy `weather_current`/`weather_forecast`). No data schema change — only journal mode + connect discipline. | **No data migration.** WAL is a journal-mode switch, not a schema change. `PRAGMA journal_mode=WAL` on first connect after deploy converts it persistently. Existing rows are untouched. |
| Live service config | WeatherBot runs as a **live systemd service on host `yahir-mint`** (editable install) per `[[weatherbot-live-systemd-service]]`. | The plan must sequence a **clean restart** after deploy so the daemon reconnects and applies WAL. No config-file change. |
| OS-registered state | systemd unit (`Restart=always`, `EnvironmentFile=.env` per CLAUDE.md). No string embeds this phase touches. | None — the unit is unaffected. Just a `systemctl restart`. |
| Secrets/env vars | None touched. DELIV-04 handles the Discord webhook *credential* only via status codes; the URL/appid never enters a `DeliveryResult` or exception (T-04-01 hygiene preserved). | None. Verify DELIV-04's raised `HTTPStatusError.detail`/message carries only the status code + body snippet, never the webhook URL (the current `_post` already snippets safely). |
| Build artifacts | Editable install (`_editable_impl_weatherbot.pth`); hub pinned at `v0.1.1` in `.venv`. | None — no package rename. Do NOT repin/rebuild the hub (F94/F04 are the only hub-rooted items and they're deferred). |

**WAL sidecar note:** after the switch, `data/weatherbot.db-wal` and `data/weatherbot.db-shm` appear alongside the db `[VERIFIED: live interpreter]`. These are normal, are managed by SQLite (auto-checkpointed), and should be added to `.gitignore` if the data dir is ever tracked (verify: the db itself is already git-ignored per `data/`). A clean shutdown checkpoints the WAL back into the main db.

## Common Pitfalls

### Pitfall 1: Hoisting the fetch breaks fetch-429 Retry-After honoring
**What goes wrong:** DELIV-03 moves the fetch out of the retried unit; if done naively, a fetch-429 no longer reaches the two-burst `Retry-After` wait callable (RELY-02), silently dropping the capped-Retry-After behavior.
**Why it happens:** `cli.py:211-216` deliberately kept the fetch inside the retried callable *for exactly this reason*.
**How to avoid:** Decide the fetch-retry disposition explicitly (Pattern 3): either keep a separate fetch-side retry, or accept that the ready-gate already validated the key for the daemon path. Keep `tests/test_send_now.py` green as the contract gate.
**Warning signs:** a fetch-429 no longer waits the honored value; `test_reliability.py` Retry-After tests regress.

### Pitfall 2: DELIV-04 carrier leaks the webhook URL
**What goes wrong:** synthesizing an `httpx.HTTPStatusError` from the Discord response could embed the request URL (the webhook credential) in `str(exc)` — the exact F12-class leak.
**Why it happens:** `HTTPStatusError`'s default message includes the request URL.
**How to avoid:** construct the raised error with a message that carries only the status code (no URL), and set `.response`/`.request` to synthesized objects whose URL is a placeholder — the classifiers read only `.response.status_code`. Never pass the real webhook URL into the request/response. `[VERIFIED: classifiers read only .response.status_code]`
**Warning signs:** a webhook URL fragment appears in an alert `detail` or a logged traceback.

### Pitfall 3: Reads still write after the split
**What goes wrong:** a read fn left calling `executescript(_SCHEMA)` (or a non-`mode=ro` connect) still takes a write lock — F10 unfixed.
**Why it happens:** 14 near-identical sites; easy to miss one.
**How to avoid:** grep for `executescript(_SCHEMA)` after the refactor — it should appear only in `init_db`. Open the 4 read fns with `read_only=True`.
**Warning signs:** a status read raises `database is locked` under concurrent write; `mode=ro` connect would have raised on any accidental write.

### Pitfall 4: One bad slot kills the APScheduler thread
**What goes wrong:** the F01 restructure or the F08 branch re-raises out of the slot, killing the worker thread (violates SCHD/T-03-07 isolation).
**Why it happens:** removing/reshaping the broad `except` at `daemon.py:349` or `:552`.
**How to avoid:** keep the outer `except Exception: ... return None` isolation envelope intact in both `fire_slot` and `fire_forecast_slot`. The bookkeeping swallow (Pattern 1) is *inside* that envelope; the F08 `ok=False` branch `return None`s, never raises.
**Warning signs:** a single slot exception stops subsequent fires.

### Pitfall 5: F01 fix lands without the reproduce-first test
**What goes wrong:** the fix ships but the duplicate-send scenario was never demonstrated to fail first (violates the D-01a / roadmap mandate).
**Why it happens:** the fix is "obvious" so the failing test is skipped.
**How to avoid:** write the injection test (see §Code Examples), confirm it FAILS against current `daemon.py` (asserts a duplicate / false `internal_error`), then apply the fix and confirm it PASSES.
**Warning signs:** no test that injects an OperationalError into `resolve_alert`/`stamp_success`.

## Code Examples

### Reproduce F01 (D-01a — must fail against current code, then pass)
```python
# Source: proposed regression, per D-01a. Inject a DB error into post-send bookkeeping
# AFTER a successful send, assert the slot stays delivered (no re-fire, no false alert).
def test_post_send_db_error_keeps_claim(monkeypatch, tmp_path):
    db = tmp_path / "wb.db"
    init_db(db)
    # channel that reports a successful delivery
    ok_channel = _StubChannel(result=DeliveryResult(ok=True))
    # force stamp_success to raise a realistic post-delivery "database is locked"
    import weatherbot.scheduler.daemon as d
    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(d, "stamp_success", boom)   # (or resolve_alert)

    fire_slot(location, slot, config=cfg, db_path=db, channel=ok_channel, ...)

    # The briefing WAS delivered → the slot must remain claimed (exactly-once).
    assert was_sent(db, location.name, slot.time, local_date) is True   # FAILS today (F01)
    # ...and no false internal_error alert was recorded.
    assert read_alert_reason(db, location.name, slot.time, local_date) != "internal_error"
```

### WAL + busy_timeout + read-only connect (verified idioms)
```python
# Source: VERIFIED against this project's Python 3.12 sqlite3 (live interpreter)
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA journal_mode=WAL")     # -> 'wal', PERSISTENT across reopen
conn.execute("PRAGMA busy_timeout=5000")    # per-connection, ~5s
# read-only path (D-07): reads take no write lock
ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)   # write -> OperationalError
```

### DELIV-04 short-circuit (verified 1-attempt behavior)
```python
# Source: VERIFIED — a non-transient raised exception short-circuits build_retrying
# in exactly 1 attempt (reraise=True keeps .response intact), so fire_slot's existing
# `except httpx.HTTPStatusError` at daemon.py:263 maps it to REASON_AUTH_FAILED.
# app-side _post, 401/403 branch:
if status in (401, 403):
    resp = httpx.Response(status, request=httpx.Request("POST", "https://discord/redacted"))
    raise httpx.HTTPStatusError(f"discord auth {status}", request=resp.request, response=resp)
# all OTHER non-2xx stay as today: return DeliveryResult(ok=False, detail=f"{status} {snippet}")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SQLite default rollback journal (`journal_mode=delete`), readers block writers | `WAL` mode — readers and the single writer proceed concurrently | SQLite 3.7 (2010); default-recommended for concurrent access | This is the standard fix for `database is locked` under a writer + readers; it is the D-05 target. `[CITED: sqlite.org/wal.html]` |
| `busy_timeout=0` (raise immediately on contention) | `busy_timeout=<few seconds>` (wait-and-retry) | Long-standing SQLite guidance | Turns a rare contention into a brief wait instead of an OperationalError — the D-06 target. `[CITED: sqlite.org/pragma.html#pragma_busy_timeout]` |

**Deprecated/outdated:** nothing in this phase depends on deprecated APIs. (The legacy `weather_current`/`weather_forecast` tables are retained-not-written by design — out of scope.)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The exact fetch-retry disposition under D-03 (keep a separate fetch retry vs. drop fetch-429 retry for the daemon path) is a design choice, not dictated | Pattern 3, Pitfall 1 | If the phase must preserve fetch-429 Retry-After honoring exactly, a naive hoist regresses RELY-02; needs a plan checkpoint. Low risk — flagged loudly. |
| A2 | `busy_timeout=5000ms` is an appropriate value for the ~10-worker + heartbeat + UV profile under WAL | Pattern 5 | Too low → rare spurious lock errors; too high → a stuck writer delays a fire. Mechanism verified; the specific ms is a reasoned default the planner may re-pin. Low risk. |
| A3 | Synthesizing an `httpx.HTTPStatusError` from the Discord `requests.Response` with a redacted URL cleanly feeds `is_auth_failure` without leaking the webhook | Pattern 4, Pitfall 2 | If `discord_webhook`'s response object differs from expectation, the construction needs adjustment; classifiers only read `.response.status_code` (verified), so risk is low. |

## Open Questions

1. **Fetch-retry disposition under D-03 (A1)**
   - What we know: the fetch is currently inside the retried unit specifically to propagate fetch-429 Retry-After (`cli.py:211-216`).
   - What's unclear: whether the daemon path must retain fetch-429 retries after the hoist, or whether the ready-gate makes that redundant.
   - Recommendation: add a plan checkpoint; keep `tests/test_send_now.py` + `test_reliability.py` Retry-After tests green as the gate. Prefer keeping a fetch-side transient retry so no reliability behavior is lost.

2. **DELIV-04 carrier choice (Pattern 4 vs. alternative)**
   - What we know: both the `httpx.HTTPStatusError` raise and an app-side `SendAuthError` short-circuit the retry in 1 attempt (verified).
   - What's unclear: purely a style/coupling preference.
   - Recommendation: use the `httpx.HTTPStatusError` carrier — it reuses `fire_slot`'s existing `except` at `daemon.py:263` with zero new daemon code and is byte-identical to the fetch-path contract.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python `sqlite3` (WAL, busy_timeout, `mode=ro` URI) | HARD-STORE-01/02 | ✓ | Python 3.12 stdlib | — |
| `tenacity` (short-circuit on non-transient) | DELIV-04 | ✓ | 9.1.4 | — |
| `httpx.HTTPStatusError` with `.response` | DELIV-04 | ✓ | 0.28.1 | — |
| `discord-webhook` (`_post` status source) | DELIV-04 | ✓ | 1.4.1 | — |
| `yahir_reusable_bot` hub (`build_retrying`, classifiers, `DeliveryResult`) | all send-path fixes | ✓ (pinned @ v0.1.1) | 0.1.0 | **do not modify — hub changes are human-gated** |
| Live `data/weatherbot.db` (WAL migration target) | HARD-STORE-02 | ✓ | `journal_mode=delete` today | clean systemd restart applies WAL |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none. Only operational note: the WAL switch on the live systemd host needs a clean restart (§Runtime State Inventory).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (+ pytest-cov 7.1.0, syrupy 5.3.4, time-machine 3.2.0) `[VERIFIED: .venv dist-info]` |
| Config file | `pyproject.toml` (uv-managed); tests in `tests/` |
| Quick run command | `uv run pytest tests/test_scheduler.py tests/test_store.py -x -q` |
| Full suite command | `uv run pytest -q` |

> **Phase 34 owns the comprehensive backfill.** Fixes here must be *test-shaped* (D-01a mandates the F01 reproduce-first test lands with the fix). Note `[[pytest-snapshot-report-quirk]]`: syrupy may print "N snapshots failed" while exit code is 0 — trust the exit code + `.ambr` diff, not the printed line.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HARD-DELIV-01 | Post-send DB error keeps the claim (no duplicate, no false internal_error) | unit (inject OperationalError) | `uv run pytest tests/test_scheduler.py -k post_send_db_error -x` | ❌ Wave 0 (D-01a reproduce-first) |
| HARD-DELIV-02 | Forecast `ok=False` → `_note_forecast_failure`, streak NOT reset | unit | `uv run pytest tests/test_scheduler.py -k forecast_delivery_failure -x` | ❌ Wave 0 |
| HARD-DELIV-03 | Retry on delivery-only failure does NOT re-fetch (assert `lookup_weather` called once) | unit (spy on fetch) | `uv run pytest tests/test_send_now.py -k retry_reuses_payload -x` | ❌ Wave 0 |
| HARD-DELIV-04 | Discord 401/403 → `auth_failed`, ~1 attempt (not `transient_exhausted`) | unit | `uv run pytest tests/test_scheduler.py -k discord_auth_short_circuit -x` | ❌ Wave 0 |
| HARD-STORE-01 | `weather_onecall` write atomic (both variants or neither); reads take no write lock | unit | `uv run pytest tests/test_store.py -k atomic -x` | ❌ Wave 0 (partial: atomicity already holds — assert no truncate window) |
| HARD-STORE-02 | WAL set + persistent; `busy_timeout` non-zero; a read during a write does not raise | unit | `uv run pytest tests/test_store.py -k wal_busy_timeout -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_scheduler.py tests/test_store.py tests/test_send_now.py -x -q`
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** full suite green before `/gsd-verify-work`; F01 reproduce-first test demonstrably failed against pre-fix code (record in the verification log).

### Highest-Risk Uncovered Paths
1. **F01 duplicate-send** — the critical; currently no test injects a post-delivery DB error. Reproduce-first is mandatory.
2. **Store atomicity under real concurrency** — `test_concurrent_double_fire_delivers_once` runs SEQUENTIALLY today (F106), so the store race is unproven; a genuinely-concurrent test is Phase-34 scope but this phase's WAL/busy_timeout change should not regress it.
3. **Retry-reuse (DELIV-03)** — assert fetch-call count under retry (spy on `lookup_weather`); no such assertion exists.
4. **Auth classification (DELIV-04)** — assert reason == `auth_failed` AND attempt count ≈ 1 (not the full ~65-min schedule).

### Wave 0 Gaps
- [ ] `tests/test_scheduler.py::test_post_send_db_error_keeps_claim` — HARD-DELIV-01 (reproduce-first)
- [ ] `tests/test_scheduler.py::test_forecast_delivery_failure_escalates` — HARD-DELIV-02
- [ ] `tests/test_send_now.py::test_retry_reuses_payload` — HARD-DELIV-03 (fetch-count spy)
- [ ] `tests/test_scheduler.py::test_discord_auth_short_circuit` — HARD-DELIV-04
- [ ] `tests/test_store.py::test_wal_busy_timeout_and_readonly_reads` — HARD-STORE-02 + F10
- [ ] `tests/test_store.py::test_onecall_write_atomic` — HARD-STORE-01
- [ ] Shared test fixture: an in-tmp `init_db`'d DB helper + a `_StubChannel(DeliveryResult(...))` (likely already in `tests/`; confirm/reuse)

## Security Domain

> `security_enforcement: true`, ASVS L1. This phase touches credential-adjacent code (the Discord webhook status handling) and persistence.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user auth surface; the "auth" here is a webhook credential, covered under V6/V7 hygiene. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no | Single-user personal bot. |
| V5 Input Validation | partial | `Retry-After` is already treated as untrusted + capped (`retry.py:parse_retry_after`); no new external input added. Parameterized `?` SQL is preserved (all store writes already SQLi-safe). |
| V6 Cryptography | no | No new crypto. |
| V7 Error/Logging hygiene | **yes** | The DELIV-04 carrier and F01 swallow logs must never emit the webhook URL or `appid` (T-04-01). Verified the existing `_post` snippets safely; the synthesized `HTTPStatusError` must carry a redacted URL (Pitfall 2). |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Webhook URL / `appid` leak into an alert `detail` or traceback (F12 class) | Information Disclosure | Redact the URL in the synthesized `HTTPStatusError`; `detail` carries status + body-snippet only; classifiers read only `.response.status_code`. `[VERIFIED: codebase]` |
| Duplicate briefing (exactly-once break) as an integrity defect | Tampering (of delivery state) | F01 fix: claim-as-truth after `result.ok`; bookkeeping cannot release. |
| SQL injection via store writes | Tampering | Preserved: all inserts remain parameterized `?` (no f-string into SQL) after the `_connect()` refactor. `[VERIFIED: codebase — every store fn]` |

## Sources

### Primary (HIGH confidence)
- Codebase (read at cited lines): `weatherbot/scheduler/daemon.py` (fire_slot 150-379, fire_forecast_slot 464-579, swallow idiom 1029), `weatherbot/weather/store.py` (all 14 connect sites, `_SCHEMA`, read/write fns), `weatherbot/channels/discord.py` (_post 72-115), `weatherbot/cli.py` (send_now 142-225), `weatherbot/reliability/retry.py` (shim), `.venv/.../yahir_reusable_bot/channels/base.py` (DeliveryResult/Channel), `.venv/.../yahir_reusable_bot/reliability/retry.py` (build_retrying, is_transient, is_auth_failure, PERMANENT/TRANSIENT).
- Live Python 3.12 interpreter (this project's `.venv`): WAL persistence, per-connection busy_timeout, `-wal`/`-shm` sidecars, `mode=ro` write-block, tenacity 1-attempt short-circuit on non-transient exception (both carriers).
- Live DB `data/weatherbot.db`: `journal_mode=delete`, `busy_timeout=0` confirmed.
- `.planning/WHOLE-PROJECT-REVIEW.md` §Critical/High/Medium: F01, F08, F10, F48 exact scenarios; F94/F04 upstream markers.
- `.planning/REQUIREMENTS.md`: HARD-DELIV-01..04, HARD-STORE-01/02 exact text.

### Secondary (MEDIUM confidence)
- SQLite official docs (WAL, `busy_timeout` PRAGMA) — corroborate the verified idioms (`sqlite.org/wal.html`, `sqlite.org/pragma.html`).

### Tertiary (LOW confidence)
- None. All load-bearing claims are codebase- or interpreter-verified.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all versions read from installed dist-info.
- Architecture (F01/F08/DELIV-03/DELIV-04 restructures): HIGH — exact current code shapes read at cited lines; carriers verified against the live retry engine.
- Store hardening (WAL/busy_timeout/read-only/atomicity): HIGH — every idiom run against the live interpreter; `persist` atomicity confirmed by reading the code (no truncate exists).
- Pitfalls: HIGH — each derived from a verified code fact.

**Research date:** 2026-07-10
**Valid until:** 2026-08-09 (30 days — stable; the only external facts are stdlib SQLite idioms and pinned-version behavior).
