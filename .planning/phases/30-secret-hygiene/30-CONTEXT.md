# Phase 30: Secret Hygiene - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

The OpenWeather `appid` (API key) must never escape into an exception message,
traceback, or log line. Two contaminated surfaces are in scope:

1. **`client.py:67/84`** — `response.raise_for_status()` raises an
   `httpx.HTTPStatusError` whose message embeds the full request URL, which
   carries `appid=<key>` (for BOTH `fetch_onecall` and `geocode`).
2. **`bot.py:507`** — the Discord inbound `on_message` envelope calls
   `_log.exception("inbound handler failed")`, which dumps the **full traceback**
   (including the key-bearing `HTTPStatusError` message) to stderr. This is the
   reproduced F12 end-to-end leak: a failing `!weather <loc>` over Discord.

Delivers HARD-SEC-01. Cheap, high-value, no behavior change beyond redaction.

**In scope:** redact the key from surfaced errors on the fetch-failure paths
(onecall + geocode), stop the Discord path dumping the key-bearing traceback, add
a global log backstop, and a regression test asserting the key never appears.

**Out of scope:** retry/classification logic (Phase 31), any change to the
exception *type* or status-code contract, non-secret param handling.
</domain>

<decisions>
## Implementation Decisions

### Redaction strategy (D-01, D-02)
- **D-01 — Fix at the root + a global backstop (belt-and-suspenders).** Primary
  fix is at the source in `client.py`: catch `httpx.HTTPStatusError` in
  `fetch_onecall` AND `geocode`, redact the `appid` value from the surfaced
  message, and re-raise so the exception object is clean everywhere it is later
  logged (Discord traceback, and any future call site). This makes the leak
  unreachable rather than patching each logging site.
- **D-02 — Add a global logging backstop** that scrubs any `appid=<value>` from
  rendered log output (event fields AND tracebacks) as a safety net for future
  code. Chosen because HARD-SEC-01 is a security requirement and this milestone's
  posture is correctness-first / no-backlog (fold the defense-in-depth in now,
  don't defer it). See `[[no-backlog-fold-cleanup-in]]`.

### Redacted representation (D-03)
- **D-03 — Placeholder, not deletion.** Replace only the key value with a
  placeholder: `appid=***` (or `appid=REDACTED`). Keep the failing endpoint URL
  and HTTP status visible so the live daemon stays diagnosable — you can still
  see which endpoint/status failed. Do NOT strip the whole query string.

### Hard constraint — exception type is LOCKED (not negotiable)
- The re-raised error MUST stay `httpx.HTTPStatusError` with `.response` (and thus
  `.response.status_code`) intact. **6+ call sites branch on this:**
  `cli.py:291/367/421/692`, `selfcheck.py:127` (auth-vs-transient classification),
  `daemon.py:263` (retry classification carrying `.response`). Phase 31 will also
  classify auth-vs-transient off this exception. Swapping to a custom exception
  type would break retry-classification, alerting, and exit codes across the app.
  → The fix redacts the **message**, never the type. Preferred mechanism: re-raise
  a new `httpx.HTTPStatusError(scrubbed_message, request=..., response=exc.response)`
  (or scrub in place) — planner/researcher to confirm the cleanest httpx-idiomatic
  form that preserves `.response`.

### Claude's Discretion
- **Backstop insertion point.** Two viable mechanisms; researcher/planner picks:
  (a) **`_LiveStderr.write` choke point** — both `structlog.configure` sites
  (`__init__.py:40`, `cli.py:779`) route through `PrintLoggerFactory(file=_LiveStderr())`.
  Wrapping `_LiveStderr.write` to regex-scrub `appid=…` catches EVERYTHING (event
  dict, any renderer, formatted traceback) at one point, independent of the
  structlog processor chain — elegant and renderer-agnostic. (b) A custom structlog
  **processor** added to the chain — but the configs pass no explicit `processors=`,
  so this means re-declaring the default chain. Lean toward (a).
- **Redaction helper shape** — a small pure function (e.g. `redact_appid(text) ->
  text` and/or a scrub for an httpx URL/exception). Keep it one obvious place
  (candidate: `weatherbot/weather/client.py` or a tiny `weatherbot/_redact.py`).
- **Regression test shape** — use a fake sentinel key, mock a 401/403 response,
  assert the sentinel never appears in `str(exc)` NOR in captured stderr/caplog,
  for: onecall fetch-failure, geocode fetch-failure, and the Discord end-to-end
  path (the `_log.exception` at `bot.py:507`). Also assert `.response.status_code`
  still readable (type-contract canary).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirement & roadmap
- `.planning/REQUIREMENTS.md` §Secret Hygiene — HARD-SEC-01 (the single requirement).
- `.planning/ROADMAP.md` §"Phase 30: Secret Hygiene" — goal + 3 success criteria.

### Leak sites (source of truth)
- `weatherbot/weather/client.py` — `fetch_onecall` (`:52-68`) + `geocode` (`:79-85`);
  `raise_for_status()` at `:67` and `:84` are the contaminated raises. Note the
  existing header comment already claims "never logs the URL or the key" — the
  `raise_for_status` message is the gap that comment misses.
- `weatherbot/interactive/bot.py:506-511` — the `on_message` `except Exception` →
  `_log.exception("inbound handler failed")` that dumps the traceback (F12).

### Logging architecture (for the backstop)
- `weatherbot/__init__.py:40-44` — package-level `structlog.configure` +
  `_LiveStderr` proxy (`:24-37`).
- `weatherbot/cli.py:778-783` — per-run `_configure_logging` (second configure site).

### Already-safe call sites (do NOT regress — confirm they stay outcome-only)
- `weatherbot/cli.py:291/367/421/692`, `weatherbot/scheduler/daemon.py:263/553`,
  `weatherbot/ops/selfcheck.py:127`, `weatherbot/scheduler/uvmonitor.py:145` —
  these already log `status=`/`type(exc).__name__` only, never `str(exc)`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_LiveStderr` (`weatherbot/__init__.py:24`) — single stderr write choke point
  shared by both configure sites; the natural home for a renderer-agnostic backstop.
- Existing outcome-only logging idiom (`status=exc.response.status_code`) already
  used across CLI/daemon/selfcheck — the fix should keep this pattern intact.

### Established Patterns
- Non-propagating envelope pattern (Discord `on_message` D-11, CLI WR-05) — the
  fix must preserve "never a raw traceback / never re-raise" behavior; it only
  changes WHAT gets logged, not the envelope structure.
- `httpx.HTTPStatusError` with `.response.status_code` is the app-wide currency for
  fetch failures — the type contract is load-bearing (see D-hard-constraint).

### Integration Points
- Redaction at `client.py` raise sites (both functions).
- Backstop at the `structlog`/`_LiveStderr` layer (both configure sites).
- Regression test lands alongside existing client tests + a bot on_message test.

</code_context>

<specifics>
## Specific Ideas

- Placeholder token: `appid=***` (keep it short/obvious). Preserve endpoint + status.
- Belt-and-suspenders explicitly requested: source scrub AS WELL AS the log backstop
  — neither alone; the source fix satisfies the criteria, the backstop hardens future code.
</specifics>

<deferred>
## Deferred Ideas

- **Promote the redaction backstop to the `yahir_reusable_bot` hub.** A generic
  "scrub secrets from log output" filter is a plausible reusable mechanism, but the
  `appid` pattern is OpenWeather-specific and cutting a hub tag is a human-gated
  step that contradicts this phase's "cheap, high-value" mandate. Build it
  app-local now (optionally structured under `_promotable/` if the seam is clean),
  flag as a hub-promotion candidate for a future ecosystem cycle. See
  `[[multi-bot-ecosystem-extraction]]`.
- Broader secret-scanning of other params (lat/lon/location names) — not secrets,
  out of scope for HARD-SEC-01.

</deferred>

---

*Phase: 30-secret-hygiene*
*Context gathered: 2026-07-09*
