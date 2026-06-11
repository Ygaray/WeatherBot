# Phase 4: Retry-then-Alert Reliability - Context

**Gathered:** 2026-06-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 wraps the Phase 3 daemon's per-slot delivery pipeline (`fire_slot` →
`send_now` → fetch/send) in **reliability machinery** so the always-on bot
recovers from transient failures, surfaces genuine failures, and never dies on
one bad run:

- **Bounded retry** on transient fetch/send failures with a deliberate
  two-burst schedule (RELY-01), honoring `Retry-After` and never retrying
  401/403 (RELY-02).
- An **out-of-band failure alert** — a `briefing_missed` signal on a path
  independent of the failing Discord channel — when delivery genuinely fails
  after retries (RELY-03/04).
- **Heartbeat / liveness** so a healthy-but-idle daemon is distinguishable from
  a crash (RELY-05).
- **Exception isolation** so one bad scheduled job logs a traceback and the
  scheduler keeps firing every other job (RELY-06).

Requirements covered: RELY-01, RELY-02, RELY-03, RELY-04, RELY-05, RELY-06.

**Design north-star (user-stated):** the alert + heartbeat artifacts are built to
be consumed by a **future log-monitoring bot** — so "best" everywhere means
*machine-detectable and durable*, not human-facing push in v1.

**Explicitly NOT this phase** (later / deferred): process supervision, reboot
survival, the startup self-check / "online" signal (Phase 5 — OPS-01/02); active
push/email/SMS alert delivery (deferred — see Deferred Ideas); SMS/Telegram
channels and weather-pattern analysis (v2). The daemon still runs in the
**foreground** (Phase 5 owns backgrounding/supervision). Phase 3's
mark-sent-only-on-success + claim/release idempotency (D-07) is the foundation
this phase hardens — it is NOT re-litigated.
</domain>

<decisions>
## Implementation Decisions

### Out-of-band alert path (RELY-03/04)
- **D-01:** The "briefing missed" alert is delivered via **log + a durable DB
  record**, NOT via a network notification channel. Two coordinated outputs:
  1. A **structured CRITICAL event** to stderr/journald with a stable event key
     (`briefing_missed`) and fields `location`, `slot` (the `"HH:MM"` time),
     `local_date`, `reason`, `severity` — **never any secret** (T-04-01 carries
     forward). This is the out-of-band path: it is independent of Discord, so a
     Discord outage cannot swallow it.
  2. A **durable row in the existing `data/weatherbot.db`** (new `alerts` table,
     alongside `weather_onecall` and `sent_log`) the monitoring bot can query.
- **D-02:** Rationale for log+DB over email/push/second-webhook: a **future
  log-monitoring bot** is the intended consumer. The DB row makes a missed
  briefing detectable even if the monitor wasn't tailing at that instant
  (started late, restarted, polls on an interval). A second Discord webhook was
  rejected as not truly independent of a Discord-wide outage.
- **D-03:** `alerts` table shape (planner finalizes column names): keyed by the
  **`(location, slot_time, local_date)`** tuple (parallels `sent_log`), plus
  `reason`, `severity`, `created_at`, and a **`resolved_at`/`resolved`** flag
  (see D-10). Reuse the store's parameterized-`?` + secret-hygiene discipline;
  additive `CREATE TABLE IF NOT EXISTS` schema only (no destructive migration).

### Heartbeat / liveness (RELY-05)
- **D-04:** Liveness is emitted on **two triggers**: a **periodic tick** from the
  daemon loop (fires on a fixed interval regardless of sends — proves "alive but
  idle" ≠ "crashed") AND a **per-send success** stamp (proves briefings are
  actually landing). The alert path (D-01) covers failures, so these two signals
  together let the monitor distinguish *crashed* (no tick) from *failing-to-send*
  (ticking but no recent success).
- **D-05:** Liveness is recorded as **both** a **DB heartbeat row** (`last_tick`
  and `last_success` timestamps, upserted in place — the authoritative state a
  polling monitor reads) **and** a **periodic structured `heartbeat` log event**
  (for a live tailer). Same dual shape as the alert (D-01), same store, same
  secret-hygiene rules.
- **D-06:** The periodic tick **interval** is **Claude's discretion** — carry a
  sensible default (~5–15 min). May be promoted into the config block (D-09) if
  convenient, but not required.

### Retry budget & policy (RELY-01/02)
- **D-07:** Retry uses a deliberate **two-burst schedule**, NOT a single
  exponential ramp:
  - **Burst 1:** 8 attempts spread across ~10 minutes (backoff + jitter so the
    attempts span the window).
  - **Wait ~45 minutes.**
  - **Burst 2:** 8 attempts spread across ~10 minutes.
  - Still failing after both bursts → fire the alert (D-01).
  - **Total ≈ 65 min**, intentionally **under Phase 3's 90-min catch-up grace
    window (D-04 there)**. A send that succeeds on burst 2 (~55–65 min late)
    lands within the grace window and renders Phase 3's `{schedule_note}`
    intended-vs-actual late annotation (re-fetched live weather per D-05 there).
- **D-08:** The two-burst schedule applies to **both** transient OpenWeather
  **fetch** failures and Discord **send** failures (RELY-01 covers both). A
  **401/403 auth failure short-circuits the whole schedule and alerts
  immediately** (RELY-02 "never retried") — the alert `reason` distinguishes
  `auth_failed` from `transient_exhausted`. `Retry-After` on 429 is honored
  (RELY-02), capped so an oversized value can't blow the ~65-min budget
  (cap = Claude's discretion).
- **D-09:** The retry timings (attempts-per-burst, ~10-min spread, ~45-min wait)
  are **exposed in `config.toml`** (a new reliability/retry section), **validated
  at load** in the Phase-2 fail-loud-at-load tradition, and surfaced by
  **`--check`**. Defaults match D-07 (8 / ~10 min / ~45 min / 8).
- **D-10 (manual vs daemon split):** The full patient schedule + alert +
  heartbeat is **daemon-only** (it exists because the daemon is unattended).
  Manual **`--send-now`** does a **tight/quick retry (or none)**, reports failure
  **immediately to the terminal**, and writes **no `alerts` or `heartbeat`
  rows** (those are daemon-liveness concerns). Tight-vs-none is Claude's
  discretion — lean to a short bounded retry for a transient blip.

### Alert behavior & anti-loop (RELY-03/04/06)
- **D-11 (dedup / anti-loop):** **At most one `briefing_missed` alert per
  `(location, slot, local_date)`.** A slot that exhausts retries alerts once; a
  daemon restart that re-attempts the same slot within the grace window writes
  **no duplicate** (INSERT-OR-IGNORE on the key, mirroring the Phase 3 `sent_log`
  idempotency pattern, D-06/D-08 there). This is the concrete RELY-04 "does not
  loop" guarantee.
- **D-12 (exception isolation → alert):** An **unexpected exception** caught by
  per-job isolation (RELY-06) **also writes a `briefing_missed` alert** with
  `reason=internal_error` (distinct from `transient_exhausted` / `auth_failed`),
  logs the **full traceback**, and the **scheduler keeps running**. From the
  user's seat a briefing was missed regardless of cause, so the monitor sees
  every miss uniformly. (This hardens `fire_slot`'s existing minimal try/except,
  T-03-07.)
- **D-13 (resolve on success):** The `alerts` row carries a
  **`resolved_at`/`resolved`** flag; if the slot later succeeds (e.g. a restart
  within the grace window finally delivers), the alert is **stamped resolved** so
  the monitor can query "currently-unresolved alerts" and not nag about a
  briefing that did eventually land.

### Claude's Discretion
- Heartbeat tick interval (~5–15 min default), D-06.
- `Retry-After` cap value, D-08.
- Exact transient-vs-permanent failure classification: retry timeouts /
  connection errors / 5xx / 429 (honor capped `Retry-After`); do NOT retry
  400/404 or 401/403 (auth, locked never-retry). Standard classification.
- `tenacity` vs hand-rolled retry — implementation choice (STACK.md recommends
  `tenacity`; the two-burst-with-45-min-pause shape needs a custom wait, which
  `tenacity` can express via a custom wait function, or a small hand-rolled
  loop). **Implementation note:** the ~45-min mid-pause sleep MUST stay
  SIGTERM/Ctrl-C-interruptible (clean shutdown, D-09 Phase 3) and MUST NOT block
  the other scheduled jobs (one slot's long retry ties up at most one
  APScheduler worker thread — confirm the threadpool/job design preserves
  per-job isolation). If `tenacity` is adopted, add it to `pyproject.toml`
  dependencies (per STACK.md 9.x).
- Exact `alerts`/`heartbeat` table names + column names (D-03/D-05) and the retry
  config section keys (D-09) — planner's call, follow store + config conventions.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 4: Retry-then-Alert Reliability" — goal, mode (mvp), the 4 success criteria
- `.planning/REQUIREMENTS.md` — RELY-01..06 (and the Phase 5 OPS-* boundary this phase must NOT cross: supervision, reboot survival, startup self-check / "online" signal)
- `.planning/PROJECT.md` — core value + locked decisions, esp. "Network/API calls can fail at send-time; must retry and then alert rather than silently miss a briefing" and "retry/alert wrapper lives at the orchestration layer around `Channel.send`"
- `.planning/STATE.md` — milestone status (Phase 4/5 pending; do not complete-milestone until both ship)

### Prior phase context (foundation this phase hardens)
- `.planning/phases/03-always-on-scheduler/03-CONTEXT.md` — **the direct foundation.** D-04 (90-min catch-up grace window this retry budget stays under), D-05 (re-fetch live weather on recovery), D-06 (`(location, send-time, local-date)` dedup key — `alerts` reuses this tuple), D-07 (mark-sent-only-on-success + claim/release), D-12/D-13 (`{sent_at}`/`{checked_at}`/`{schedule_note}` late annotation a recovered late send renders)
- `.planning/phases/02-real-config-locations-content-templates/02-CONTEXT.md` — fail-loud-at-load config validation (extended by the retry config block, D-09), `--check` surface (D-09)
- `.planning/phases/01-first-briefing-end-to-end/01-CONTEXT.md` — `send_now` composition root, `Channel.send(text)`/`send_briefing` seam + `DeliveryResult(ok, detail)` expected-failure contract (the orchestration layer "decides whether to retry/alert"), SQLite store + analysis-ready persistence (the `alerts`/`heartbeat` tables follow this)

### Research (technical grounding)
- `.planning/research/STACK.md` — **tenacity 9.x** (decorator/backoff retry, recommended; not yet a dependency), structlog logging, the retry/alert-at-orchestration-layer guidance; httpx timeout model
- `.planning/research/ARCHITECTURE.md` — orchestration-layer wrapper around fetch + `Channel.send`
- `.planning/research/PITFALLS.md` — OpenWeather 401/403 = subscription not active / not yet propagated (Pitfall 1, drives auth-no-retry); secret-in-URL logging hygiene (Pitfall 6)

### Key code touchpoints (read before planning)
- `weatherbot/scheduler/daemon.py` — `fire_slot` (existing minimal try/except to harden, D-12; wrap retry here or just inside it), `run_daemon` (add the periodic heartbeat tick, D-04; interruptible-sleep constraint), `_register_jobs`/`misfire_grace_time=None`
- `weatherbot/cli.py` — `send_now` composition root (retry/alert wraps fetch + `send_briefing`; daemon-only patient path vs manual tight path, D-10), `do_check` (validate new retry config, D-09)
- `weatherbot/weather/client.py` — `fetch_onecall` raises `httpx.HTTPStatusError` on non-2xx (the 401/403 short-circuit + transient classification surface, D-08)
- `weatherbot/channels/discord.py` / `weatherbot/channels/base.py` — `DeliveryResult(ok, detail)` is the retry/alert decision point; `rate_limit_retry=True` already honors Discord 429 internally (avoid double-retrying 429 at both layers — planner reconcile)
- `weatherbot/weather/store.py` — `_SCHEMA` + `claim_slot`/`release_claim`/`was_sent` (model the new `alerts` + `heartbeat` tables and helpers on these; reuse INSERT-OR-IGNORE for D-11 dedup)

No external ADRs/specs beyond the planning + research docs above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weatherbot/scheduler/daemon.py` (`fire_slot`, `run_daemon`) — `fire_slot`
  already has the try/except isolation skeleton (T-03-07) to extend for D-12 and
  to wrap with the two-burst retry (D-07/D-08). `run_daemon`'s
  `threading.Event`/SIGTERM lifecycle is where the periodic heartbeat tick
  (D-04) and the interruptible long-pause concern (D-07) live.
- `weatherbot/weather/store.py` (`_SCHEMA`, `claim_slot`, `release_claim`,
  `was_sent`) — the template for the new `alerts` + `heartbeat` tables/helpers.
  `claim_slot`'s atomic `INSERT OR IGNORE` + `rowcount==1` is exactly the dedup
  primitive for D-11 (one alert per slot/day).
- `weatherbot/cli.py` (`send_now`, `do_check`) — `send_now` is the wrap point for
  retry/alert around fetch + `send_briefing`; `do_check` validates the new retry
  config (D-09).
- `weatherbot/channels/base.py` (`DeliveryResult`) — `ok=False`/`detail`
  expected-failure contract is the existing seam the orchestration layer keys its
  retry/alert decision on (no exceptions for normal non-2xx).
- `weatherbot/weather/client.py` — `httpx.HTTPStatusError` carries `.response.status_code`
  for the 401/403 short-circuit and transient classification (D-08).

### Established Patterns (from Phases 1–3 — keep)
- **Mark-on-success + claim/release idempotency** (Phase 3 D-06/D-07) — retry sits
  *inside* the claim, before release; exhaustion releases the claim (slot stays
  re-fireable) AND writes the deduped alert (D-11).
- **Fail-loud-at-load config validation** (Phase 2) — extend to the new retry
  config block (D-09), surfaced by `--check`.
- **Secrets only on `Settings`; outcome-only logging** (T-02-01/T-04-01) — the
  alert/heartbeat events and rows carry `location`/`time`/`reason` etc., NEVER
  the key or webhook URL.
- **Additive SQLite schema** (`CREATE TABLE IF NOT EXISTS`) — `alerts`/`heartbeat`
  tables added with no destructive migration; analysis/monitor-ready like
  `weather_onecall`.
- **Per-job exception isolation** (T-03-07) — already in `fire_slot`; D-12 hardens
  it (traceback + alert + loop survives).

### Integration Points
- `data/weatherbot.db` — new `alerts` table (D-01/D-03) + `heartbeat` row/table
  (D-05); additive only.
- `config.toml` / `config.example.toml` — new retry/reliability config section
  (D-09) documenting attempts/spread/wait defaults; validated at load.
- `pyproject.toml` — add `tenacity` (9.x) IF the planner adopts it for the
  two-burst retry (D-07 implementation note).
- The `send_now` orchestration boundary — retry/alert wraps fetch + delivery;
  daemon path = patient + alert + heartbeat, manual path = tight + terminal-only
  (D-10).
- `run_daemon` loop — periodic heartbeat tick (D-04) + interruptible long-pause
  during retry (D-07).
</code_context>

<specifics>
## Specific Ideas

- **The user's exact retry schedule (verbatim intent):** "patient configuration —
  8 tries spread out in a 10 min range, wait 45 minutes, again 8 tries in a 10
  minute range." This is the literal source of D-07.
- **The "future monitoring bot" frame** is the design driver for D-01/D-02/D-05:
  the user is deliberately choosing log + queryable DB artifacts NOW so a separate
  monitoring bot they'll build later can watch the events / query the `alerts` and
  `heartbeat` tables and surface human-facing notifications. Every alert/heartbeat
  design choice should optimize for "easy for a bot to detect reliably."
- **Reason taxonomy** the user explicitly wants distinguished on alerts:
  `transient_exhausted` (both bursts failed), `auth_failed` (401/403
  short-circuit), `internal_error` (unexpected exception). Plus a `resolved`
  state for "eventually delivered."
</specifics>

<deferred>
## Deferred Ideas

- **Active push/email/SMS alert delivery** (SMTP, ntfy/Pushover, second Discord
  webhook) — explicitly NOT in v1; the alert path is log + DB consumed by a future
  monitoring bot. Revisit when/if a human-facing instant notification is wanted.
- **The future log-monitoring bot itself** — watches the structured
  `briefing_missed`/`heartbeat` events and/or polls the `alerts`/`heartbeat`
  tables and turns them into human-facing alerts. Out of scope for Phase 4
  (Phase 4 only produces the artifacts it will consume). Its own future project.
- **Promoting the heartbeat tick interval / `Retry-After` cap into config** —
  carried as discretion defaults now (D-06/D-08); expose later if they prove wrong
  (same posture as Phase 3's configurable-grace-window deferral).
- **Routing the structured log event to journald→email or external monitoring** —
  Phase 5 (deployment/supervision) territory, not Phase 4.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 4-Retry-then-Alert Reliability*
*Context gathered: 2026-06-10*
