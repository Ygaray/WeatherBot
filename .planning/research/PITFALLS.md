# Pitfalls Research

**Domain:** Personal always-on weather-briefing bot (scheduled job runner → OpenWeather API → templated message delivery to Discord, later SMS/Telegram)
**Researched:** 2026-06-09
**Confidence:** HIGH (OpenWeather subscription model, DST scheduling behavior, Discord rate limits, and APScheduler misfire semantics all verified against official docs / vendor sources)

## Critical Pitfalls

### Pitfall 1: Scheduling in UTC or naive local time — wrong send-time, missed/duplicate fires across DST

**What goes wrong:**
The user wants "8:00 AM in the city I'll be in." A bot that schedules in UTC, server-local time, or a single fixed timezone delivers at the wrong wall-clock hour, and breaks twice a year:
- **Spring forward:** a job scheduled for a time inside the skipped hour (e.g. 2:00–2:59 AM in US zones) never fires that day, or fires "immediately" at an unexpected moment depending on the scheduler.
- **Fall back:** a job scheduled inside the repeated hour (1:00–1:59 AM) can fire **twice** — the user gets two briefings.
- Worse for this project: the home city and the travel city may be in **different timezones / different DST rules entirely**. A single global clock makes one of them permanently wrong.

**Why it happens:**
Developers reach for `datetime.now()` (naive), schedule against the host's local time, or store schedule times as UTC and convert once at startup. Cron-style and naive APScheduler triggers compute "next run" against a clock that shifts under them. The bug is invisible in testing because DST transitions only happen on two specific nights a year.

**How to avoid:**
- Store each location's schedule as **(local wall-clock time + that location's IANA timezone name)**, e.g. `"08:00"` + `"America/New_York"`. Never store the offset (`-05:00`) — offsets are wrong half the year.
- Use a **timezone-aware scheduler trigger** (APScheduler `CronTrigger`/`IntervalTrigger` with an explicit `timezone=` per job, or compute next-fire with `zoneinfo`). Let the library recompute next-fire from the IANA zone every time, so it tracks DST automatically.
- **Pin schedules out of the DST danger window.** Morning briefings (e.g. 07:00–08:00) are naturally safe — the 1–3 AM gap/overlap window is the dangerous one. Document this so nobody "helpfully" adds a 2:00 AM send.
- After any fire, record a **dedup key of (location, schedule-slot, local-calendar-date)**. Refuse to send if that key already fired today. This kills fall-back double-fires and restart-replays in one mechanism (see Pitfall 4).

**Warning signs:**
- Schedule config stores times as UTC or as a numeric offset rather than a zone name.
- Code calls `datetime.now()` / `date.today()` without a tz argument anywhere in the scheduling path.
- No test that simulates a DST transition or a different-timezone location.
- Briefing arrives an hour off after a clock change, or two briefings arrive on a fall-back morning.

**Phase to address:**
Scheduling phase (foundational). Timezone model must be in the config schema from day one — retrofitting tz-awareness after schedules are stored as UTC is a data migration.

---

### Pitfall 2: Assuming the free `/data/2.5/` endpoints still give you the daily forecast — One Call 3.0 is a separate paid-tier subscription

**What goes wrong:**
The briefing needs **today's high/low + daily summary**, which historically came from One Call 2.5 (`/data/2.5/onecall`). One Call 2.5 is deprecated/being retired, and **One Call API 3.0 requires a separate "One Call by Call" subscription** — you must subscribe to it specifically (and provide a card, even though there's a free daily allowance) before the key returns data. A key minted only for the basic free plan returns **401/403 on the 3.0 endpoint**, so the bot ships, looks done, and then silently fails to ever produce a real forecast. Conversely, hardcoding deprecated 2.5 URLs means the integration dies on OpenWeather's retirement schedule.

**Why it happens:**
Tutorials and training data predate the 3.0 split and still show `/data/2.5/onecall` working with a plain free key. Developers test the simple `/data/2.5/weather` (current conditions — still free) endpoint, see it work, and assume the daily-forecast call works too.

**How to avoid:**
- Decide the data source explicitly: **One Call API 3.0** (`/data/3.0/onecall`) for current + 8-day daily in one call. Subscribe to the "One Call by Call" plan and confirm the key is activated (new keys can take up to a couple of hours to go live — see Pitfall 8).
- If you want to stay strictly on the free, no-card tier, accept the constraint: the free `/data/2.5/weather` (current) + `/data/2.5/forecast` (5-day / 3-hour) endpoints exist, but you must **derive today's high/low/rain-chance yourself** by aggregating the 3-hour buckets for the local calendar day. Pick one path and write it down.
- Wrap the API in a thin client with the endpoint/version in **one place** so a future migration is a one-line change, not a grep.
- On startup, do a **single live probe call** and fail loudly with a clear message ("One Call 3.0 returned 401 — is the One Call subscription active for this key?") rather than discovering it at 8 AM.

**Warning signs:**
- 401/403/429 from the forecast endpoint while the basic current-weather endpoint works.
- Briefing fields like `{high}`/`{low}` render empty or as placeholders.
- Code references `/data/2.5/onecall` (the deprecated path).

**Phase to address:**
OpenWeather integration phase. Resolve the subscription/endpoint decision before building the briefing template, because available fields depend on which product you're calling.

---

### Pitfall 3: The long-running loop dies on one unhandled exception and stays dead

**What goes wrong:**
A single uncaught exception (malformed API payload, transient DNS failure, a `KeyError` on a field OpenWeather omitted today) propagates out of the job and **kills the scheduler thread or the whole process**. On an always-on Pi/server with no supervision, the bot is now silently dead and the user just stops getting briefings — the worst failure mode for a "set and forget" tool, because there's no error, just silence.

**Why it happens:**
The happy-path job function does `fetch → format → send` with no try/except. Schedulers differ in whether a raised exception kills only that run or the whole scheduler, and developers rarely test the failing case. There's also no process supervisor, so a crash is permanent until manual restart.

**How to avoid:**
- **Every scheduled job runs inside a top-level try/except** that logs the full traceback and continues. A bad fetch should fail *that briefing* (and trigger retry-then-alert), never the loop.
- Run under a **process supervisor that auto-restarts**: `systemd` unit with `Restart=always` (and `WantedBy=multi-user.target` so it survives reboot), or Docker with `restart: unless-stopped`. This is the single most important reliability decision for an always-on personal bot.
- Add a **heartbeat / liveness signal** the user can notice (e.g. a startup "WeatherBot online" message, or a daily/weekly "still alive" ping) so silence is detectable.
- Treat OpenWeather responses as **untrusted shape** — every field access is defensive (`.get()` with defaults), because the API legitimately omits fields (e.g. `rain` only present when it's raining).

**Warning signs:**
- Job function has no try/except wrapping fetch + send.
- No systemd/docker restart policy; bot started with a bare `python main.py &` or `nohup`.
- Field access uses `payload["rain"]["1h"]` rather than guarded lookups.
- "It worked for a week then just stopped."

**Phase to address:**
Scheduler/runtime phase for the loop hardening; deployment phase for supervision and reboot survival.

---

### Pitfall 4: Restart and reboot replay — duplicate or missed briefings around process lifecycle

**What goes wrong:**
The in-process scheduler holds next-fire times in memory. When the host reboots (or the process restarts after a crash/deploy):
- If schedules live only in memory and the bot was down across a send-time, **the briefing is silently missed** (no recovery).
- If a persistent jobstore is used naively, on restart the scheduler sees a "missed" run and **fires it late** — delivering yesterday-evening's 8 AM briefing at noon, or, with misfire grace + coalescing misconfigured, firing several queued runs in a burst.

**Why it happens:**
APScheduler (and similar) distinguish persistent vs in-memory jobstores and apply a `misfire_grace_time` to missed runs; the defaults aren't tuned for "a daily message is useless if it's hours late." Coalescing of stacked missed runs is off/on in ways developers don't reason about until it misbehaves.

**How to avoid:**
- **Don't rely on scheduler replay for correctness.** Make the schedule **declarative and recomputed from config on every startup** (re-derive next-fire from each location's local time + zone), rather than depending on a persisted queue of past jobs.
- Enforce the **(location, slot, local-date) dedup key** from Pitfall 1 as the source of truth for "did this briefing already go out today." Persist it (a tiny JSON/SQLite file). On startup, the bot checks: for each slot whose time has already passed today, was it sent? If not and it's still "reasonably" the same morning, send once; otherwise skip.
- Keep `misfire_grace_time` **short and deliberate** (a stale morning briefing delivered at dinner is worse than a skipped one), and enable **coalescing** so stacked misses collapse to a single send.
- Decide the policy explicitly and document it: *"If the bot was down across a send-time, do we backfill or skip?"* For a morning briefing, a short grace window (e.g. send if <90 min late, else skip) is sensible.

**Warning signs:**
- Schedules stored only in process memory with no persisted "already sent today" record.
- Restarting the bot mid-day triggers an immediate briefing.
- A briefing arrives hours after its scheduled time following a reboot/deploy.

**Phase to address:**
Scheduler phase (dedup/idempotency model + restart recomputation). Deployment phase verifies reboot behavior end-to-end.

---

### Pitfall 5: Retry storm and alert-loop — the failure-handling path is itself the failure

**What goes wrong:**
The requirement is "on OpenWeather or send failure: retry, then alert." Naive implementations turn this into outages:
- **Tight retry loop** with no backoff hammers OpenWeather on a transient 5xx/timeout, **burning the daily quota** and possibly getting rate-limited (429), turning a 30-second blip into a day-long outage.
- **The alert channel is the same channel that's failing.** If Discord is down or the webhook is revoked, "alert the user via Discord" can't work — and if the alert itself retries, you get an infinite alert loop, or just silence (the one case where the user most needs to know is the one case the design can't deliver).

**Why it happens:**
Retry is added as a `for i in range(5): try send` with no delay, and "alert the user" is wired to the same delivery channel because it's the only one built in v1. The recursive case (alerting about a delivery failure over the failing delivery path) isn't considered.

**How to avoid:**
- **Bounded retries with exponential backoff + jitter**, and a hard cap (e.g. 3 attempts over a couple of minutes), not an unbounded loop. Distinguish **retryable** (timeout, 5xx, 429-with-retry-after) from **non-retryable** (401/403 bad key, 400 bad request) — never retry a 401, fix the config.
- **Honor `Retry-After`.** Both OpenWeather (429) and Discord (429) return retry-after timing — respect it instead of guessing. Discord webhooks cap at ~30 messages/min per webhook; a retry storm trivially trips this.
- **The alert path must be independent of, or degrade gracefully from, the primary delivery path.** Options: alert to a *different* channel/webhook, write a conspicuous local log + non-zero process health signal, and make the alert itself **fire-and-forget with no retry** (one best-effort attempt). Accept that if everything is down, the recovery is the supervisor + the user noticing missing briefings — don't build an infinite escalation.
- **Circuit-breaker mindset:** after N consecutive failures, stop retrying for a cooldown window rather than retrying every cycle.

**Warning signs:**
- Retry code with no `sleep`/backoff, or no maximum attempt count.
- 401/403 errors being retried.
- The alert mechanism calls the same `send()` that just failed.
- Quota exhausted early in the day; logs full of repeated identical failed calls.

**Phase to address:**
Reliability / retry-then-alert phase. The alert-channel-independence decision is an explicit design point of this phase, not an afterthought.

---

### Pitfall 6: Quota exhaustion from polling design (not just retries)

**What goes wrong:**
OpenWeather's One Call 3.0 free allowance is **1,000 calls/day** (then billed; a daily cap can be set). The free 2.5 tier is ~**60 calls/minute / 1,000,000/month** but the practical risk here is the *per-day* One Call allowance. A handful of locations × a few send-times is tiny — but careless design blows it: calling the API on every scheduler tick (e.g. once a minute "to check"), re-fetching per template-render, polling for "live" data, or the retry storm in Pitfall 5. Exhausting the quota means **no briefing for the rest of the day** or surprise charges.

**Why it happens:**
Treating the weather API like a cheap local function — fetching eagerly, fetching in loops, or fetching to "keep data fresh" rather than fetching exactly once per scheduled briefing.

**How to avoid:**
- **Fetch lazily and exactly once per briefing send** (per location, per fire). Don't fetch on idle ticks.
- **Cache within a send** so multiple template placeholders reuse one response.
- Optionally **set a daily call cap** in the OpenWeather dashboard to convert "runaway charges" into "loud failure," which is the safer mode for a personal project.
- Count expected daily calls on paper: `locations × send-times-per-day × (1 + retry budget)` should be comfortably under the allowance with large headroom.

**Warning signs:**
- API called from the scheduler tick loop rather than from the job body.
- Call count scales with template complexity or scheduler frequency, not with number of briefings.
- Quota dashboard climbing far faster than `briefings/day` would imply.

**Phase to address:**
OpenWeather integration phase (call discipline + caching). Reliability phase (retry budget capped).

---

### Pitfall 7: Secrets committed, world-readable, or logged

**What goes wrong:**
API key, Discord webhook URL (which is itself a secret — anyone with it can post to the channel), and later Twilio/Telegram tokens get committed to git, baked into a config that's checked in, printed in logs/tracebacks, or left world-readable on the Pi. The webhook URL leaking is especially easy because it "feels like a URL, not a password."

**Why it happens:**
"Config-driven, file-based" (a stated project requirement) tempts putting secrets in the same checked-in config file as locations/schedules. Error logging that dumps the full request URL leaks the key (OpenWeather keys travel in the query string) and the webhook.

**How to avoid:**
- **Separate secrets from non-secret config.** Non-secret config (locations, schedules, templates) can be a checked-in file; secrets come from a **`.env` / environment variables** or a separate uncommitted secrets file. Add the secrets path to `.gitignore` before writing the first key.
- Provide a **`.env.example` / sample config** with placeholders so setup is documented without leaking real values.
- **Never log full request URLs or response bodies** that contain the key; redact the webhook URL and API key in logs and error messages.
- Set restrictive file perms on the Pi (`chmod 600`) for the secrets file.
- Treat the **Discord webhook URL as a credential** — rotate it if it ever appears in a log paste or screenshot.

**Warning signs:**
- API key or `discord.com/api/webhooks/...` string visible in `git log`, committed config, or log output.
- No `.gitignore` entry for the secrets file before first commit.
- Tracebacks that print the outbound URL.

**Phase to address:**
Config/foundation phase (secrets separation + .gitignore), before any real key is introduced.

---

### Pitfall 8: New-key activation delay misdiagnosed as broken code

**What goes wrong:**
Freshly created OpenWeather API keys (and newly activated One Call subscriptions) can take **up to a couple of hours** to become active, returning 401 in the meantime. Developers assume their request/signing/endpoint is wrong, rewrite working code, and churn — or conclude the API is unusable.

**Why it happens:**
The 401 is indistinguishable from a genuinely bad request without reading the docs/FAQ note about activation latency.

**How to avoid:**
- Document the activation-delay caveat in setup notes. On a fresh-key 401, **wait and retry later** before debugging code.
- The startup probe (Pitfall 2) should print a message distinguishing "key not yet active / not subscribed" from other failures.

**Warning signs:**
- Brand-new key returns 401 on every endpoint including the basic free one.

**Phase to address:**
OpenWeather integration phase (setup docs + startup probe messaging).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Over-abstract the channel interface up front (queues, plugin registry, async delivery framework) for SMS/Telegram that aren't built yet | Feels "future-proof" | Slows v1 dramatically; you design the abstraction blind to SMS/Telegram's real constraints (Twilio segments/cost, Telegram chat IDs/Markdown), so it's wrong anyway and gets reworked when channel #2 lands | **Never** build the elaborate version in v1. Define a **minimal interface** (one `send(message) -> result` method + a way to surface failures) and implement only Discord behind it. Two concrete channels reveal the right abstraction; one channel + imagination does not. |
| Hardcode the two locations / single timezone instead of a config schema | Ships the demo faster | The weekday-home/weekend-travel split is the *entire point*; hardcoding it means rewriting the scheduling core | Only as a throwaway spike; the config schema is core scope, not deferrable |
| Store schedule times as UTC "to keep it simple" | Avoids tz library now | Wrong by an hour for half the year, breaks across two timezones and DST (Pitfall 1) | Never — tz-aware from day one |
| `print()`-based logging | Zero setup | Can't diagnose a 3 AM silent failure on a headless Pi after the fact; no rotation fills the disk | MVP only if writing to a real (rotating) logfile; structured logging needed for the always-on case |
| String `.format()`/f-string templating on user-editable templates | Trivial to implement | Template-injection / crash on bad placeholder (see Integration Gotchas) | Acceptable with a guarded renderer (whitelist placeholders, catch KeyError); never raw `.format(**dict)` on free-form user templates without guards |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| OpenWeather One Call 3.0 | Using a free-tier key without the separate One Call subscription; hardcoding deprecated `/data/2.5/onecall` | Subscribe to One Call by Call, call `/data/3.0/onecall`, isolate endpoint/version in one client module, probe on startup |
| OpenWeather field shape | Accessing `rain.1h` / `snow` unconditionally — they're **absent when not raining/snowing** | Guarded `.get()` access with sensible defaults; never assume optional weather fields exist |
| OpenWeather units | Assuming Celsius/Fahrenheit; default response is **Kelvin** unless `units=metric`/`imperial` is passed | Always pass `units` explicitly; pick one and reflect it in templates (and in `{wind}` — m/s vs mph follows the units param) |
| Discord webhook | Ignoring 429 / blasting messages; assuming a webhook never disappears | Honor `Retry-After`; stay under ~30 msg/min per webhook; handle 404 (webhook deleted) as a config error, not a transient retry |
| Discord message format | Pasting raw template text that contains Discord markdown/mention syntax (`@everyone`, backticks) | Sanitize/escape output; be deliberate about whether mentions are allowed |
| Twilio/Telegram (future) | Designing the v1 interface around Discord's webhook-fire-and-forget model | Keep interface minimal so Twilio (auth, phone numbers, message segments, cost) and Telegram (bot token, chat_id, parse_mode) can each bring their own config without reshaping the core |

## Performance Traps

This is a single-user, low-volume bot — classic scaling traps mostly don't apply. The real "traps" are call-rate and process-longevity, not throughput.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Polling the API on every scheduler tick | Quota climbs independent of briefing count | Fetch only inside the job body, once per send | Within a day or two — quota exhausted |
| Retry storm without backoff | Burst of identical failed calls; 429s | Bounded exponential backoff + jitter, honor Retry-After | On the first transient OpenWeather/Discord hiccup |
| Unbounded logfile on the Pi | Disk fills, process or whole host stalls | Rotating logs (size/time-based) | Weeks-to-months of always-on runtime |
| Memory leak / fd leak in a never-restarting loop | Gradual RSS growth over days | Reuse a single HTTP session/client; rely on supervisor restart as backstop | Long uptime (the always-on requirement guarantees you reach it) |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Committing API key / webhook URL / tokens to git | Quota theft, unauthorized posting to the Discord channel, leaked Twilio credit | Secrets in env/.env, `.gitignore` before first key, treat webhook URL as a credential |
| Logging full request URLs or response bodies | Key/webhook leak via log paste, screenshot, or shared traceback | Redact secrets in all log/error output |
| World-readable secrets file on the Pi | Local-account or backup exfiltration | `chmod 600`, keep out of synced/backed-up dirs unless encrypted |
| `eval`/unguarded `.format` on user-editable templates | A crafted template can crash the bot or access object internals (`{0.__class__...}` style format-string abuse) | Whitelist allowed placeholders; render with a guarded substitution, never expose object attribute access |
| Trusting OpenWeather payload as well-formed | Crash/loop-kill on missing/changed fields (also a reliability issue) | Defensive parsing with defaults |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Silent failure (no briefing, no alert) | User shows up unprepared for weather; trust in "set and forget" tool is destroyed by one silent miss | Retry-then-alert with an *independent* alert path; startup "online" ping so silence is detectable |
| Wrong-location briefing (sends home weather on a travel day) | The single worst outcome — actively misleading; defeats the core value | Per-location + day-of-week schedule modeled correctly; show the location name *in the message* so a misroute is obvious |
| Briefing an hour off after DST | Erodes "reliably every morning" promise | Tz-aware scheduling (Pitfall 1) |
| Unreadable/garbled message from a bad template placeholder | User gets `{high}` literal or a Python error dump | Guarded renderer that leaves unknown placeholders visible-but-safe and never crashes the send |
| Kelvin / wrong units in the message | "It's 291 degrees" | Always set `units`; show the unit symbol in the template |

## "Looks Done But Isn't" Checklist

- [ ] **Daily forecast fields:** Often missing the One Call 3.0 subscription — verify `{high}`/`{low}`/rain-chance actually populate from a live call, not just current temp from the free endpoint.
- [ ] **Timezone scheduling:** Often "works in my zone" — verify a second location in a *different* timezone fires at *its* local time, and simulate a DST transition.
- [ ] **Reboot survival:** Often only tested by manual run — verify the bot auto-starts on host reboot (systemd `WantedBy`/Docker `restart`) and doesn't replay a stale briefing.
- [ ] **Crash recovery:** Often only happy-path — verify a forced exception in the job body logs and continues (loop survives), and the supervisor restarts a hard crash.
- [ ] **Alert path independence:** Often wired to the failing channel — verify that with Discord deliberately broken (bad webhook), the user is still alerted somehow and the bot doesn't infinite-loop.
- [ ] **Retry discipline:** Verify retries are bounded, backed off, honor Retry-After, and do **not** retry 401/403.
- [ ] **Dedup:** Verify restarting the process mid-morning, or a fall-back DST night, produces exactly one briefing per slot.
- [ ] **Secrets:** Verify nothing secret is in git history or logs before first real key is used.
- [ ] **Optional weather fields:** Verify a clear-sky day (no `rain` field) renders without error.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Schedules stored as UTC/offset (Pitfall 1) | MEDIUM | Add tz column to config schema, migrate existing times, switch trigger to tz-aware — touches stored config |
| Wrong/deprecated OpenWeather endpoint (Pitfall 2) | LOW | If client is isolated, change endpoint/version + ensure subscription; if grepped everywhere, higher |
| No supervisor, bot died (Pitfall 3) | LOW | Add systemd unit / Docker restart policy; one-time setup |
| Restart replay / dup briefings (Pitfall 4) | LOW–MEDIUM | Add persisted (location,slot,date) dedup file + short misfire grace + coalescing |
| Retry storm / alert loop (Pitfall 5) | MEDIUM | Introduce backoff + attempt cap + Retry-After handling; rewire alert to independent/no-retry path |
| Quota exhausted (Pitfall 6) | LOW | Move fetch into job body, cache per send, set dashboard daily cap; quota resets next day |
| Leaked secret (Pitfall 7) | MEDIUM–HIGH | Rotate API key + regenerate Discord webhook; scrub git history (`git filter-repo`) if committed |
| Over-built channel abstraction (debt) | MEDIUM | Collapse to minimal interface; usually a refactor, painful if delivery framework is load-bearing |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Secrets handling (P7) | Foundation / config | No secrets in git or logs; `.gitignore` present before first key |
| Tz/DST scheduling (P1) | Scheduling (core) | Second-timezone location fires at its local time; simulated DST transition fires once |
| Restart/reboot replay & dedup (P4) | Scheduling + Deployment | Mid-day restart and fall-back night each yield exactly one briefing per slot |
| OpenWeather subscription/endpoint, units, optional fields, key activation (P2, P6, P8) | OpenWeather integration | Live call populates daily high/low; startup probe distinguishes auth vs other errors; clear-sky day renders |
| Loop survives exceptions (P3) | Scheduler/runtime | Injected exception logs + continues; bot keeps running |
| Supervision & reboot survival (P3) | Deployment | Host reboot brings bot back automatically |
| Retry storm / alert-loop independence (P5) | Reliability (retry-then-alert) | Bounded backoff verified; broken-Discord test still alerts without looping |
| Template injection/formatting (security/UX) | Templating | Bad/malicious placeholder renders safely, never crashes send |
| Over-abstracted channel layer (debt) | Channel/delivery | v1 ships Discord behind a minimal interface; no unused plugin machinery |

## Sources

- OpenWeather One Call API 3.0 — product page & pricing (separate subscription, 1,000 free calls/day, daily cap option): https://openweathermap.org/api/one-call-3 , https://openweathermap.org/price , https://openweathermap.org/full-price (HIGH)
- OpenWeather 2.5 → 3.0 transfer / deprecation guidance: https://openweathermap.org/api/one-call-transfer (HIGH)
- OpenWeather FAQ (new-key activation delay, units default Kelvin): https://openweathermap.org/faq (HIGH)
- APScheduler user guide — misfire_grace_time, coalescing, persistent vs in-memory jobstores, restart misfires: https://apscheduler.readthedocs.io/en/3.x/userguide.html (HIGH)
- Cron/scheduler DST behavior — spring-forward skip, fall-back double-run, UTC recommendation: https://cronjob.live/docs/dst-pitfalls , https://blog.healthchecks.io/2021/10/how-debian-cron-handles-dst-transitions/ , https://cronmonitor.app/blog/handling-timezone-issues-in-cron-jobs (HIGH — multiple sources agree)
- Discord webhook rate limits — ~30 msg/min per webhook, 429 + Retry-After: https://docs.discord.com/developers/topics/rate-limits , https://github.com/discord/discord-api-docs/issues/1454 (HIGH)
- Domain experience: long-running process supervision (systemd/Docker restart), retry-then-alert independence, format-string injection — corroborated across the above + general practice (MEDIUM)

---
*Pitfalls research for: personal always-on weather-briefing bot*
*Researched: 2026-06-09*
