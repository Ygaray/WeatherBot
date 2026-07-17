# Phase 31: Send Atomicity, Exactly-Once & Persistence Robustness - Pattern Map

**Mapped:** 2026-07-10
**Files analyzed:** 4 source + 4 test files (all MODIFY — no greenfield)
**Analogs found:** 8 / 8 (every fix has an in-repo analog; this phase re-wires existing primitives)

## File Classification

| Modified File | Role | Data Flow | Closest Analog (in-repo) | Match Quality |
|---------------|------|-----------|--------------------------|---------------|
| `weatherbot/scheduler/daemon.py` (F01 `fire_slot` tail) | scheduler orchestration | request-response (send + bookkeeping) | `daemon.py:1032-1036` swallow-on-committed idiom | exact (same-file idiom) |
| `weatherbot/scheduler/daemon.py` (F08 `fire_forecast_slot`) | scheduler orchestration | request-response | `daemon.py:314` sibling `fire_slot` `result.ok` inspection | exact (sibling fn, same file) |
| `weatherbot/scheduler/daemon.py` (DELIV-03 fetch/deliver split) | scheduler orchestration | request-response + fetch | `daemon.py:525` `fire_forecast_slot` payload reuse (FCAST-07) | role-match (sibling reuse pattern) |
| `weatherbot/scheduler/daemon.py` (DELIV-04 consumer) | scheduler orchestration | request-response | `daemon.py:263` existing `except httpx.HTTPStatusError` → auth mapping | exact (reuse existing arm, zero new code) |
| `weatherbot/channels/discord.py` (DELIV-04 carrier) | channel adapter | request-response (HTTP) | `discord.py:94` existing raise-vs-`ok=False` split in `_post` | exact (same fn, extend the branch) |
| `weatherbot/cli.py` (DELIV-03 deliver-tail extract) | pipeline composition root | fetch + deliver | `cli.py:196` fetch / `cli.py:208` deliver / `cli.py:217` persist boundary | exact (split existing body) |
| `weatherbot/weather/store.py` (`_connect` helper + `init_db` split) | store / persistence | CRUD | `store.py:202-226` `persist` single-`with` transaction | exact (same-file transaction idiom) |
| `weatherbot/weather/store.py` (read-only reads, D-07) | store / persistence | read | `store.py:241` `was_sent` connect-and-read shape | exact (same fn class) |
| `tests/test_scheduler.py` (F01/F08/DELIV-04) | test | unit | existing `_StubChannel(DeliveryResult(...))` fixtures in `tests/` | role-match |
| `tests/test_send_now.py` (DELIV-03) | test | unit | existing send_now contract tests | exact (contract gate) |
| `tests/test_store.py` (HARD-STORE-01/02) | test | unit | existing store tests | role-match |
| `tests/test_reliability.py` (Retry-After regression gate) | test | unit | existing two-burst Retry-After tests | exact (regression gate) |

---

## Pattern Assignments

### F01 — `daemon.py` `fire_slot` success tail (HARD-DELIV-01)

**Analog:** `daemon.py:1032-1036` — the swallow-on-committed idiom. CONTEXT/RESEARCH both name this the literal precedent.

**Analog excerpt** (`daemon.py:1032-1036`, best-effort post-commit swallow):
```python
if cache is not None:
    try:
        cache.invalidate()
    except Exception:  # noqa: BLE001 — best-effort; reload already committed
        _log.warning("forecast cache invalidate failed; reload unaffected")
```

**Current defect site** (`daemon.py:335-348`): `resolve_alert` + `stamp_success` run bare inside the outer `try` opened at `:182`; a raise here falls to `except Exception:` at `:349`, which (because `claimed=True`) calls `release_claim` at `:356` and records a false `internal_error`:
```python
# daemon.py:339-340 — the two bare bookkeeping calls that must become best-effort
resolve_alert(db_path, location.id, slot.time, local_date)
stamp_success(db_path)
```

**Fix shape:** wrap `:339-340` in a local `try/except Exception: _log.warning(...)` mirroring `:1032-1036`. The invariant: **no code path after `result.ok` can reach `release_claim` (`:356`).** Preferred = the local swallow (minimal diff, keeps `return result` in place). Do NOT touch the pre-delivery release arms (`:266`, `:289`, `:315`) or the outer isolation envelope (`:349-379`).

**Reproduce-first (D-01a, mandatory):** inject `sqlite3.OperationalError("database is locked")` into `stamp_success`/`resolve_alert` after a successful send; assert `was_sent(...) is True` and alert reason != `internal_error`. Must FAIL against current code first. Test example at RESEARCH.md §Code Examples lines 332-352.

---

### F08 — `daemon.py` `fire_forecast_slot` delivery detection (HARD-DELIV-02)

**Analog:** `daemon.py:314` — `fire_slot`'s own `result.ok` inspection (the sibling this path must mirror).

**Analog excerpt** (`daemon.py:314`, sibling branches on `ok`):
```python
if not result.ok:
    release_claim(db_path, location.id, slot.time, local_date)
    ...  # record_alert + critical
    return None
```

**Current defect site** (`daemon.py:538-543`): the returned `DeliveryResult` is discarded, then `_note_forecast_success` runs unconditionally:
```python
if channel is not None:
    channel.send(reply.text)          # ← return value DISCARDED (F08)
_note_forecast_success(location, fc)  # ← runs even on ok=False
```

**Reuse analog for the failure branch:** `daemon.py:570-573` already guards `_note_forecast_failure` (WR-05 dead-slot escalation). Route `ok=False` to that same helper — do NOT duplicate escalation logic:
```python
try:
    _note_forecast_failure(location, fc, channel=channel)
except Exception:  # noqa: BLE001 — dead-slot bookkeeping must never re-raise
    _log.warning("forecast dead-slot bookkeeping failed")
```

**Fix shape:** capture `fc_result = channel.send(reply.text)`; if `fc_result is not None and not fc_result.ok` → call `_note_forecast_failure` + warn + `return None` (never raise — Pitfall 4 isolation). Only a clean delivery reaches `_note_forecast_success`. Keep the outer `except Exception: ... return None` envelope (`:552-574`) intact.

---

### DELIV-03 — `daemon.py`/`cli.py` fetch once, retry only delivery (HARD-DELIV-03)

**Analog:** `daemon.py:525` — `fire_forecast_slot` already reuses the fetched dual One Call payload (FCAST-07: "no extra OpenWeather call"). Same principle applied to the briefing send-retry.

**Current defect site:** `_attempt` (`daemon.py:247-259`) calls `send_now`, and `send_now` does BOTH fetch and deliver:
```python
# cli.py:196 — FETCH (re-runs on every retry today)
result_lr = lookup_weather(location_name, config=config, ...)
# cli.py:208 — DELIVER
result = channel.send_briefing(result_lr.text, result_lr.forecast)
# cli.py:217 — PERSIST on ok only (WR-04)
if result.ok:
    persist(db_path, result_lr.location, result_lr.forecast)
```
Because `retrying(_attempt)` (`daemon.py:262`) re-invokes `_attempt` per retry, `lookup_weather` re-fetches each attempt.

**Fix shape:** extract the deliver+persist tail (`cli.py:205-218`) into a `deliver(lookup)` callable; fetch ONCE outside the retry, wrap ONLY delivery in `retrying`. Recommended shape at RESEARCH.md §Pattern 3 lines 189-196.

**Constraints that MUST hold (do not regress):**
- `cli.py:211-216` deliberately keeps the fetch inside the retry today so a fetch-429 `httpx.HTTPStatusError` (Retry-After) reaches the two-burst wait callable (RELY-02). The hoist must decide fetch-retry disposition explicitly — **flag as a plan checkpoint** (Open Question 1 / Pitfall 1). Keep `tests/test_send_now.py` + `tests/test_reliability.py` Retry-After tests green.
- A Discord `ok=False` is ONE transient unit — `retry_if_result(lambda r: not r.ok)` already handles it (hub `retry.py:238`); the channel owns its within-attempt 429 wait (`discord.py:83` `rate_limit_retry=True`). Do NOT add a second retry layer (Pitfall/anti-pattern).

---

### DELIV-04 — Discord 401/403 → auth (HARD-DELIV-04)

**Carrier analog (discord.py):** `discord.py:94` — `_post` already has a raise-path-vs-`ok=False` split (it catches `RequestException` and returns `ok=False`; on 2xx returns `ok=True`; on other non-2xx returns `ok=False` at `:115`). DELIV-04 adds a raise arm for 401/403.

**Consumer analog (daemon.py):** `daemon.py:263-272` — the EXISTING `except httpx.HTTPStatusError` arm that already maps `is_auth_failure(exc)` → `REASON_AUTH_FAILED`. **Zero new daemon code** — the raised error lands here:
```python
except httpx.HTTPStatusError as exc:
    release_claim(db_path, location.id, slot.time, local_date)
    claimed = False
    reason = (
        REASON_AUTH_FAILED
        if is_auth_failure(exc)
        else REASON_TRANSIENT_EXHAUSTED
    )
    ...
```

**Current defect site** (`discord.py:106-115`): ALL non-2xx (incl. 401/403) → `DeliveryResult(ok=False)`, never raises → retried as transient for the full ~65-min schedule → recorded as `transient_exhausted`.

**Fix shape (recommended carrier — no hub change, preserves Phase-30 type contract):** in `_post`, before the generic `:115` return, add:
```python
if status in (401, 403):
    resp = httpx.Response(status, request=httpx.Request("POST", "https://discord/redacted"))
    raise httpx.HTTPStatusError(f"discord auth {status}", request=resp.request, response=resp)
# all OTHER non-2xx stay as today (return DeliveryResult(ok=False, detail=f"{status} {snippet}"))
```
Verified (RESEARCH §Pattern 4): `is_transient` returns False for a 401/403 `HTTPStatusError` (`PERMANENT={400,401,403,404}`), so `build_retrying` short-circuits in exactly 1 attempt with `.response` intact.

**Security (Pitfall 2 / ASVS V7):** the synthesized request URL MUST be a redacted placeholder — never the real webhook URL. `HTTPStatusError`'s default message embeds the request URL; construct the message with status only. Classifiers read only `.response.status_code`. Keep the never-raise contract for all *transient* non-2xx (429/5xx/network stay `ok=False`).

**Do NOT:** extend `DeliveryResult` with a classification field or change the hub retry predicate (`is_transient`/`is_auth_failure`/`DeliveryResult` are hub-owned → human-gated → out of scope).

---

### HARD-STORE — `store.py` WAL + busy_timeout + `_connect()` + schema split (HARD-STORE-01/02, D-05..D-08)

**Atomic-write analog:** `store.py:202-226` — `persist` is ALREADY a single `with sqlite3.connect(...)` transaction: `executescript(_SCHEMA)` + two `INSERT` + one `commit()`, NO truncate-then-write. HARD-STORE-01 is "confirm atomicity + drop the redundant per-connect `executescript`," NOT a truncate-bug rewrite (note this in the plan so the checker doesn't hunt a non-existent bug).

**Analog excerpt** (`store.py:202-226`, the atomic multi-step write to preserve):
```python
with sqlite3.connect(db_path) as conn:
    conn.executescript(_SCHEMA)          # ← drop this per-write; init_db owns it now
    for units, payload in onecall_variants:
        conn.execute("INSERT INTO weather_onecall (...) VALUES (?, ?, ?, ?, ?, ?, ?)", (...))
    conn.commit()
```

**Current defect:** all 14 connect sites open with default rollback journal + `busy_timeout=0` and run `conn.executescript(_SCHEMA)`, whose trailing `INSERT OR IGNORE INTO heartbeat/health` (`store.py:143-144,152-153`) takes a WRITE lock — so a read (F10) can raise `database is locked` during a daemon write. Live DB confirmed `journal_mode=delete`, `busy_timeout=0`.

**Connect sites (all 14, confirmed):** `init_db`:164, `persist`:202, `was_sent`:241, `claim_slot`:279, `release_claim`:308, `record_alert`:339, `claim_uv_alert`:377, `claimed_uv_kinds`:402, `resolve_alert`:425, `stamp_tick`:444, `stamp_success`:459, `stamp_health`:481, `read_heartbeat`:499, `read_health`:517.

**Read fns (D-07 — open read-only, must NOT `executescript`):** `was_sent`:241, `claimed_uv_kinds`:402, `read_heartbeat`:499, `read_health`:517.

**Fix shape (RESEARCH §Pattern 5, all idioms live-verified):**
```python
def _connect(db_path, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")   # D-06 per-connection (~5s; planner may re-pin)
    return conn

def init_db(db_path) -> None:                  # one-time bootstrap (D-05/D-07)
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # D-05 persistent, set once
        conn.executescript(_SCHEMA)              # ONLY place executescript should remain
        conn.commit()
```
- Route every write fn through `_connect(db_path)`, drop the per-connect `executescript(_SCHEMA)`.
- Route the 4 read fns through `_connect(db_path, read_only=True)`; drop `executescript`; make "READ-ONLY: writes nothing" docstrings TRUE.
- After refactor, `grep executescript(_SCHEMA)` should match ONLY `init_db` (Pitfall 3 gate).

**Live-service caveat:** WAL is a journal-mode switch (no schema/data migration). The plan must sequence a clean `systemctl restart` on `yahir-mint` so the daemon reconnects and applies WAL; `-wal`/`-shm` sidecars appear (verify `data/` is git-ignored).

---

## Shared Patterns

### Best-effort log-and-swallow (post-commit)
**Source:** `daemon.py:1032-1036` (also `:1019-1022`, `:570-573`).
**Apply to:** F01 bookkeeping tail; F08 dead-slot bookkeeping (already applied there — reuse verbatim).
```python
try:
    <post-commit op>
except Exception:  # noqa: BLE001 — best-effort; already committed
    _log.warning("<outcome-only, no secret>")
```

### `result.ok` inspection on `DeliveryResult`
**Source:** `daemon.py:314` (`fire_slot`).
**Apply to:** F08 `fire_forecast_slot` (mirror the sibling), DELIV-03 `_deliver()` return.
Non-2xx is an expected `ok=False`, not an exception (hub `Channel.send` never-raise contract) — DELIV-04's 401/403 raise is the ONLY narrowing, and it is intentional and fetch-path-parity.

### `httpx.HTTPStatusError` as auth-classification currency (Phase-30 LOCKED contract)
**Source:** `daemon.py:263` consumer + `discord.py:94` carrier split; classifiers `is_transient`/`is_auth_failure` are hub-owned.
**Apply to:** DELIV-04 only. `.response.status_code` must stay a plain int; message/URL must be redacted (no webhook URL leak — ASVS V7 / Pitfall 2).

### Single-`with` connection = one atomic transaction
**Source:** `store.py:202-226` (`persist`).
**Apply to:** all `store.py` writes via `_connect()`; parameterized `?` SQL preserved everywhere (SQLi — ASVS V5).

---

## No Analog Found

None. Every fix maps to an existing in-repo idiom (same file or sibling function). This phase is re-wiring existing primitives, not new machinery.

## Metadata

**Analog search scope:** `weatherbot/scheduler/daemon.py`, `weatherbot/weather/store.py`, `weatherbot/channels/discord.py`, `weatherbot/cli.py`, `tests/`.
**Files scanned:** 4 source files (targeted line ranges) + store.py connect-site grep.
**Hub boundary (do NOT modify — human-gated):** `DeliveryResult`, `Channel`, `is_transient`, `is_auth_failure`, `build_retrying` (all in `yahir_reusable_bot`). F94/F04 route upstream, out of scope.
**Pattern extraction date:** 2026-07-10
