# Phase 31: Send Atomicity, Exactly-Once & Persistence Robustness - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning
**Mode:** `--auto` — gray areas auto-selected, recommended defaults locked in a single pass. These are audit-driven correctness fixes with an established "correct" target, so the decisions below reflect the audit's diagnosis rather than open product choices. Planner/researcher retain the mechanism-level discretion flagged inline.

<domain>
## Phase Boundary

Close the send-spine edge seams and the persistence-concurrency defect that
feeds them. Four failure surfaces plus their SQLite root de-risker are in scope:

1. **F01 — send atomicity (`daemon.py:335`, SWEEP-NEW critical).** In `fire_slot`,
   post-send bookkeeping (`resolve_alert` / `stamp_success`) runs INSIDE the send
   `try`. If it raises (realistically a `database is locked` after delivery), the
   broad `except` at ~351 treats it like a pre-delivery failure and calls
   `release_claim`, DELETEing the `sent_log` row. The user already got the
   briefing, but the slot is now re-fireable → catch-up/restart delivers the SAME
   briefing again, plus a false `internal_error` alert. **Verify/reproduce first.**
2. **F08 — forecast-slot delivery not detected (`daemon.py:518`, SWEEP-NEW).**
   `fire_forecast_slot` ignores the `DeliveryResult` from `channel.send()`, so a
   Discord non-2xx (`ok=False`) falls through to `_note_forecast_success()` and
   resets the streak. The dead-slot CRITICAL + operator alert (WR-05) only fire in
   the `except` branch, so a chronically-dead forecast slot stays silent. Sibling
   `fire_slot` DOES inspect `result.ok`; this path does not.
3. **DELIV-03 — retry re-fetches on delivery-only failure (F13-adjacent).** A
   delivery-only failure must retry against the ALREADY-fetched payload, not
   trigger a fresh OpenWeather re-fetch on each retry attempt.
4. **DELIV-04 — auth misclassified as transient (F48, `channels/discord.py:115`).**
   `_post` maps ALL non-2xx (incl. 401/403 revoked/invalid webhook) to a generic
   `DeliveryResult(ok=False)` and never raises, so `is_auth_failure` never sees it.
   The retry burns the full ~65-min schedule then records `transient_exhausted`
   instead of `auth_failed`. The fetch path already short-circuits 401/403; the
   send path does not.
5. **HARD-STORE — SQLite concurrency/atomicity (F10 + store findings).** Every
   store function (reads INCLUDED) opens with default rollback journal, no
   `busy_timeout` override, and runs `executescript(_SCHEMA)` on connect — whose
   trailing `INSERT OR IGNORE` takes a write lock. So a status read during a
   daemon write can raise `database is locked`. This is the ROOT de-risker of F01:
   `WAL` + `busy_timeout` + read paths that don't write make the post-delivery
   lock contention that makes F01 reachable far less likely.

Delivers HARD-DELIV-01/02/03/04 + HARD-STORE-01/02. DELIV and STORE are paired
because the storage hardening is the root de-risker of the duplicate-send bug.

**In scope:** F01 send-atomicity restructure; F08 `ok=False` detection on the
forecast path; retry-reuses-payload (no re-fetch on delivery-only failure);
Discord auth (401/403) → auth reason; SQLite `WAL` + `busy_timeout`; reads that
don't take a write lock; transactional/atomic multi-step writes; regression-test
hooks for each (tests land in Phase 34, but fixes must be test-shaped).

**Out of scope:** timezone/date-boundary correctness and the `_local_date_iso`
unification (Phase 32); interactive/panel + cache-invalidation race F13 itself and
bare-command crash F02 (Phase 33); the full test backfill (Phase 34); the hub
`is_transient` gap F94 and SIGTERM-drain F04 (route UPSTREAM to
`yahir_reusable_bot`, human-gated — do NOT fix here). No new user features.
</domain>

<decisions>
## Implementation Decisions

### F01 — Send atomicity: never release a delivered claim (D-01)
- **D-01 — Move post-send bookkeeping OUT of the release-on-failure path.**
  Recommended structure: once the send returns `result.ok` (delivery succeeded),
  the claim is the source of truth for "delivered" and MUST stay committed no
  matter what happens next. `resolve_alert` / `stamp_success` become
  **best-effort bookkeeping that can fail without releasing the claim** — either
  moved after/outside the `try` that guards `release_claim`, or wrapped in their
  own local `try/except` that logs-and-swallows (mirroring the already-established
  `daemon.py:1029` pattern: "SWALLOWED so it can NEVER abort an already-committed
  …"). The `release_claim` + `internal_error` alert path must only be reachable
  for failures that happen BEFORE delivery success. A post-delivery bookkeeping
  error logs a warning (best-effort) and returns success; it never re-fires and
  never alerts.
- **D-01a — Reproduce before fixing (roadmap mandate).** F01 is a SWEEP-NEW
  critical. Confirm the finding first: a regression that forces a DB error in
  `resolve_alert`/`stamp_success` after a successful `send_now` and asserts the
  slot stays `was_sent()==True` (no duplicate, no false `internal_error`). The fix
  and its failing-first test ship together (Phase 34 pins it long-term).

### F08 — Forecast-slot delivery must be inspected (D-02)
- **D-02 — Mirror `fire_slot`: check `result.ok` from `channel.send()`.** In
  `fire_forecast_slot`, capture the `DeliveryResult` and branch on `ok`. On
  `ok=False`, route to `_note_forecast_failure` + the WR-05 dead-slot streak /
  CRITICAL / operator-alert escalation instead of `_note_forecast_success()`.
  Preserve the existing isolation guarantee (a forecast failure still never
  touches a briefing / never re-raises out of the slot). Only a CLEAN delivery
  resets the streak.

### DELIV-03 — Retry reuses the fetched payload (D-03)
- **D-03 — Fetch once, retry only the delivery.** A delivery-only failure (a
  send that failed but the weather payload was already fetched) must NOT trigger a
  fresh OpenWeather fetch on each retry attempt. Recommended: structure the fire
  path so the fetch happens once and the retry/backoff wraps only the
  `send`/`send_now` delivery step, reusing the in-memory payload. This keeps
  OpenWeather call volume correct under retry and avoids a re-fetch changing the
  briefing content mid-retry. (Note the sibling FCAST-07 already reuses the
  dual One Call payload on the forecast path — same principle applied to the
  briefing send-retry.)

### DELIV-04 — Auth vs transient classified correctly (D-04)
- **D-04 — Discord 401/403 → auth reason, short-circuit the retry schedule.**
  A permanent send auth failure (revoked/invalid webhook, 401/403) must be mapped
  to the auth reason (`auth_failed`) and must NOT burn the full two-burst retry
  schedule as transient. Recommended: teach the send path to distinguish auth
  from transient on the `DeliveryResult` — either `_post` surfaces an
  auth-classified signal on 401/403 (a typed result/flag or a raised
  auth-classified error the retry predicate treats as non-retryable), and
  `fire_slot`'s classification maps it to `auth_failed`. Keep parity with the
  fetch path, which already short-circuits 401/403. The exact carrier (extend
  `DeliveryResult` with a classification vs. raise an auth error) is
  **planner/researcher discretion** — but the exception-TYPE contract from
  Phase 30 (`httpx.HTTPStatusError` with `.response` intact on the fetch side)
  must not regress.

### HARD-STORE — WAL, busy_timeout, non-writing reads, atomic writes (D-05..D-08)
- **D-05 — Open SQLite in `WAL` mode.** Set `PRAGMA journal_mode=WAL` (persistent —
  set once at store init / first connect) so concurrent readers don't block the
  writer and vice-versa. This is the primary structural de-risker for the F01
  post-delivery lock contention.
- **D-06 — Set a `busy_timeout` on every connection.** Add `PRAGMA busy_timeout=<ms>`
  on connect so a brief lock contention waits-and-retries rather than raising
  `database is locked` immediately. Recommended value order-of-magnitude a few
  seconds (planner to pin the exact ms against the ~10-worker + heartbeat + UV
  contention profile).
- **D-07 — Reads must not take a write lock (F10).** Separate schema bootstrap
  from the read path: the `INSERT OR IGNORE` heartbeat/health seed rows must not
  run on every read connect. Recommended: a one-time `init`/`ensure_schema`
  (at startup / first write) that owns `_SCHEMA` + seed rows, and read functions
  (`was_sent`, `read_heartbeat`, `read_health`, `claimed_uv_kinds`) that open a
  read-only/no-write connection and do NOT `executescript` the seeding DDL. Make
  the "READ-ONLY: writes nothing" docstrings TRUE.
- **D-08 — Multi-step writes are atomic/transactional.** No truncate-then-write
  and no force-commit-before-insert corruption window — a multi-step write
  commits as one transaction (single connection, single `with`-scoped
  transaction) so a crash mid-write can't leave a half-written store. Covers the
  `weather_onecall` store write specifically (HARD-STORE-01).

### Claude's Discretion (mechanism-level, for researcher/planner)
- **Shared connect helper.** Whether to centralize `WAL` + `busy_timeout` (and the
  read-only vs. read-write distinction) behind one `_connect(...)` helper in
  `store.py` vs. applying pragmas at each site. Lean toward one helper — 15+
  `sqlite3.connect(...)` sites currently repeat `executescript(_SCHEMA)`.
- **Auth-classification carrier** for DELIV-04 (typed `DeliveryResult` field vs.
  a raised auth-classified error) — pick the form that fits the existing
  `fire_slot` classification switch most cleanly without regressing the Phase-30
  type contract.
- **Exact `busy_timeout` value** and whether WAL is set via PRAGMA-on-connect vs.
  a one-time migration — pick per SQLite idiom.
- **Retry-scope refactor shape** for D-03 (where the fetch/deliver boundary sits in
  `send_now`/`fire_slot`) — pick the minimal restructure that keeps the existing
  two-burst schedule and D-02/Pitfall-2 "one transient unit per Discord ok=False".
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirement & roadmap
- `.planning/REQUIREMENTS.md` §Send/Delivery (HARD-DELIV) — HARD-DELIV-01..04.
- `.planning/REQUIREMENTS.md` §Persistence/Store (HARD-STORE) — HARD-STORE-01/02.
- `.planning/ROADMAP.md` §"Phase 31: Send Atomicity, Exactly-Once & Persistence
  Robustness" — goal + 4 success criteria (F01 verify-first mandate).

### Findings (source of truth — reproduce F01 first)
- `.planning/WHOLE-PROJECT-REVIEW.md` §Critical → **F01** (`daemon.py:335`,
  send-atomicity/double-send) — the exact scenario to reproduce.
- `.planning/WHOLE-PROJECT-REVIEW.md` §High → **F08** (`daemon.py:518`,
  forecast send-failure not detected), **F10** (`store.py:143`, read takes a
  write lock).
- `.planning/WHOLE-PROJECT-REVIEW.md` §Medium → **F48** (`channels/discord.py:115`,
  auth misclassified as transient).
- `.planning/WHOLE-PROJECT-REVIEW.md` → **F94** (`yahir_reusable_bot/reliability/retry.py:87`,
  `is_transient` gap) — **ROUTES UPSTREAM, do NOT fix here**; note it as related
  to DELIV-04 classification but hub-jurisdiction/human-gated.

### Prior-phase constraints that bind this phase
- `.planning/phases/30-secret-hygiene/30-CONTEXT.md` §"exception type is LOCKED" —
  `httpx.HTTPStatusError` with `.response.status_code` is app-wide currency for
  fetch failures; DELIV-04 auth classification builds on it and must not regress it.
- `.planning/phases/29-startup-validation-honest-alerting/29-CONTEXT.md` — validated
  boot is the dependency; the ready-gate/catch-up ordering context.

### Source sites
- `weatherbot/scheduler/daemon.py` — `fire_slot` send + bookkeeping (~300–380,
  F01 at :335), `fire_forecast_slot` (~500–545, F08 at :518), the
  already-established swallow-on-committed pattern (~1029).
- `weatherbot/weather/store.py` — `_SCHEMA` (:36), the ~15 `sqlite3.connect` +
  `executescript(_SCHEMA)` sites, read fns (`was_sent` :229, `read_heartbeat`/
  `read_health`), claim/release (`claim_slot` :251, `release_claim` :291),
  `stamp_success` :453.
- `weatherbot/channels/discord.py` — `_post` (:72–115) status→`DeliveryResult`
  mapping (F48), `send`/`send_briefing`.
- `weatherbot/channels/base.py` — `Channel` / `DeliveryResult` contract.

### Ecosystem guardrail
- `../Reusable/YahirReusableBot/ECOSYSTEM.md` — cross-repo jurisdiction: any fix
  whose root is the hub (F94 `is_transient`, F04 SIGTERM-drain) is human-gated and
  does NOT land in this phase. See `[[multi-bot-ecosystem-extraction]]`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`daemon.py:1029` swallow-on-committed pattern** — an existing idiom where a
  post-commit operation is SWALLOWED "so it can NEVER abort an already-committed"
  write. D-01 should apply the same shape to `resolve_alert`/`stamp_success`.
- **`fire_slot`'s own `result.ok` inspection** — the F08 fix (D-02) is literally
  making `fire_forecast_slot` mirror what `fire_slot` already does with the
  `DeliveryResult`.
- **FCAST-07 payload reuse** on the forecast path — the same "reuse the fetched
  payload, don't re-fetch" principle D-03 applies to the briefing send-retry.
- **Fetch-path 401/403 short-circuit** — the send path (D-04) should reach parity
  with how the fetch path already classifies auth vs transient.

### Established Patterns
- **Claim-as-source-of-truth exactly-once** (`claim_slot` INSERT OR IGNORE on the
  UNIQUE key, SCHD-07). D-01's whole point: once delivered, the won claim must not
  be released by downstream bookkeeping errors.
- **`with sqlite3.connect(...)` = one transaction** — already used; D-08 extends
  it to guarantee multi-step writes commit atomically and reads stop seeding rows.
- **`DeliveryResult(ok=...)` never-raises channel contract** — non-2xx is an
  expected `ok=False`, not an exception. D-04 must add auth classification WITHOUT
  breaking this contract (a channel `send` still shouldn't throw on a normal
  non-2xx).

### Integration Points
- F01 fix: restructure `fire_slot`'s try/except so `release_claim` is unreachable
  after `result.ok`.
- F08 fix: `fire_forecast_slot` branches on the captured `DeliveryResult`.
- D-04: `_post`/`send` classification + `fire_slot` reason mapping.
- HARD-STORE: a shared `_connect` helper (WAL + busy_timeout) + a schema-init split
  so reads don't write, touching all `store.py` connect sites.

</code_context>

<specifics>
## Specific Ideas

- **F01 is verify-first.** Do not land the fix before reproducing the
  duplicate-briefing / false-`internal_error` scenario (roadmap + REQUIREMENTS
  both mark it).
- **No-backlog posture** (this milestone): fold the full store hardening
  (WAL + busy_timeout + non-writing reads + atomic writes) in now rather than
  deferring the read-lock cleanup. See `[[no-backlog-fold-cleanup-in]]`.
- **Live daemon caveat:** WeatherBot runs as a live systemd service on `yahir-mint`
  (editable install) — a WAL/journal-mode change touches a live SQLite file; the
  plan should account for a clean restart. See `[[weatherbot-live-systemd-service]]`.

</specifics>

<deferred>
## Deferred Ideas

- **F94 `is_transient` gap (hub)** — `RemoteProtocolError`/`WriteError` not
  retried. Root is `yahir_reusable_bot/reliability/retry.py`; routes upstream,
  human-gated. Related to DELIV-04 classification but NOT fixed in this phase.
- **F04 SIGTERM-drain (hub)** — tenacity ignoring `Event.wait()` return; root in
  hub `retry.py:241`. Routes upstream.
- **F91 DST fall-back fold math** in catch-up — timezone/date-boundary, belongs to
  Phase 32.
- **F13 cache-invalidation race** and **F02 bare-command crash** — interactive/panel
  surface, Phase 33.
- **Full regression-test backfill** (concurrent-double-fire that actually
  concurrency-tests, store atomicity/data-loss path) — Phase 34. Fixes here must
  be test-shaped, but the comprehensive suite is Phase 34's job.

None of the above are new capabilities — all are already-roadmapped later phases
or upstream/human-gated items. Discussion stayed within phase scope.

</deferred>

---

*Phase: 31-send-atomicity-exactly-once-persistence-robustness*
*Context gathered: 2026-07-10*
