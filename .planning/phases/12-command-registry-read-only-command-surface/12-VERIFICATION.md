---
phase: 12-command-registry-read-only-command-surface
verified: 2026-06-19T15:59:48Z
status: human_needed
score: 5/5 must-haves verified (code); live-surface confirmation pending
overrides_applied: 0
human_verification:
  - test: "Discord: send !help, !locations, !status, !sun, !sun <other loc>, !wind <loc>, !alerts <loc>, !next-cloudy <loc>, and !sun bogusplace as the operator on the live yahir-mint daemon (after `sudo systemctl restart weatherbot`)."
    expected: "Each command answers correctly: help shows the grouped registry list; locations lists configured names; status shows alive+uptime, next send per location, bot active, UV monitor 'not running', last briefing; sun gives local sunrise/sunset; wind gives speed+compass; alerts gives active alerts or 'no active alerts'; next-cloudy gives the next cloudy day at 60% or 'no cloudy day'; bogusplace gives the corrective-hint with valid names."
    why_human: "Requires the live Discord gateway + a real operator account + a restarted daemon loading the new modules and the live One Call payload — cannot be exercised by the gateway-free unit tests."
  - test: "CLI on host: run `weatherbot locations`, `weatherbot status`, `weatherbot sun <loc>`, `weatherbot wind <loc>`, `weatherbot alerts <loc>`, `weatherbot next-cloudy <loc>` against the live config/API."
    expected: "Each prints plain-text content matching the Discord embed content (D-04) and exits 0; unknown location prints the hint and exits non-zero."
    why_human: "Requires the live OpenWeather API key + the host's real config.toml; the test suite uses fake lookups/fixtures."
  - test: "Confirm the morning briefing still fires normally after the restart (check the journal / !status last-briefing after the next scheduled send)."
    expected: "A scheduled briefing is delivered on time; the command surface never gates, delays, or drops it (CMD-16 isolation on the live daemon)."
    why_human: "Real-time scheduled behavior on the live daemon over a day boundary; the unit isolation test proves no in-process propagation but cannot prove the live send."
---

# Phase 12: Command Registry & Read-Only Command Surface Verification Report

**Phase Goal:** A single self-describing command registry feeds both the CLI and Discord bot, expanding the on-demand command surface to a full set of read-only views over already-available One Call 3.0 data — all routed through the shared lookup core and the existing operator-id / command-only guard ladder, fully isolated from the briefing path.
**Verified:** 2026-06-19T15:59:48Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

The phase declares 5 roadmap Success Criteria plus per-plan must_haves. All code-verifiable truths are VERIFIED; the live-surface confirmation (SC#2 end-to-end on the running daemon) is routed to human verification per the operator's explicit deferral of the Task 4 LIVE-OPERATOR checkpoint.

| # | Truth (roadmap SC + plan must-haves) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | SC#1 — `help` is auto-generated from one registry and updates when commands are added (CLI + Discord) | ✓ VERIFIED | `registry.py` has a single immutable `COMMANDS` tuple (7 specs) + `render_help()`; `info.help_cmd()` delegates to `registry.render_help` (no duplicate grouping). `weatherbot help` printed the grouped list (Weather/Info) at runtime. Test `help contains all summaries: True`. CLI subparsers AND Discord dispatch both derive from `registry.COMMANDS`. |
| 2 | SC#2 — `alerts`/`locations`/`status`/`sun`/`wind`/`next-cloudy` answer correctly on BOTH CLI and Discord for configured locations | ✓ VERIFIED (code) / ? human (live) | All 7 handlers exist and are wired (`registry.COMMANDS`, all handlers callable). bot.py step (4) dispatches via `parse_command`; cli.py generates one subparser per spec + `_run_registry_command`. Location-taking commands route through the shared lookup core (`cache.lookup` on Discord, `lookup_weather` on CLI). Live end-to-end answers on the running daemon → human verification. |
| 3 | SC#3 — `status` confirms the daemon is alive and reports next scheduled send time(s) | ✓ VERIFIED | `status.py` reports next-send per location (via `DaemonState.next_fires`, mirroring `_announce_schedule`), alive+uptime, bot/UV-monitor liveness, last-briefing via `read_heartbeat`. `tests/test_status.py` green. |
| 4 | SC#4 / CMD-16 — every command uses the same operator-id / command-only guard ladder; failure stays isolated from the briefing path | ✓ VERIFIED | bot.py guard ladder steps (1) author.bot, (2) operator_id, (3) `!` prefix are unchanged; only step (4) became `parse_command`. The WHOLE registry dispatch lives inside the single existing non-propagating `try/except` (no second envelope). Handlers run off-loop via `run_in_executor`. Isolation test in `tests/test_bot.py` proves a raising handler does not propagate out of `on_message`. Daemon-level: bot construction is itself inside a try/except so bot failure can't stop briefings. |
| 5 | SC#5 / D-06 — new commands read only already-available data and never write the SQLite time series | ✓ VERIFIED | `weather_views.py` has NO `weatherbot.weather.store` import (only a docstring mention) and reads `result.forecast.raw_onecall_imp` only (no second fetch). `info.py` has no store/fetch import. `state.py`/`status.py` have zero write-call code (`add_job`/`remove_job`/`holder.replace`/`stamp_*`/`persist` — only docstring references). `status` uses only the read-only `read_heartbeat` reader. Zero-store-writes spy extended in `tests/test_command_views.py`. |

**Score:** 5/5 truths verified in code. SC#2's live end-to-end answer on the running daemon is the single human-verification item (operator-deferred Task 4).

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `weatherbot/interactive/registry.py` | CommandSpec frozen dataclass + COMMANDS + BY_NAME + longest-first + render_help | ✓ VERIFIED | Frozen `CommandSpec`, immutable `_SPECS`/`COMMANDS` (7), `BY_NAME`, `COMMANDS_BY_KEYWORD_LEN_DESC`, `render_help`. Handlers wired via lazy `_wire_handlers` (acyclic imports). |
| `weatherbot/interactive/command.py` | parse_command + ParsedCommand, pure, word-boundary guard | ✓ VERIFIED | Pure parser (strip/casefold/slicing only; no format/eval/exec), longest-first iteration, word-boundary guard preserved. Behavioral check: "sunny"→None, "next-cloudy here"→matched, "SUN home"→sun/'home'. |
| `weatherbot/weather/client.py` | exclude keeps hourly[] | ✓ VERIFIED | `exclude": "minutely"` (line 62); docstring corrected. Canary test in `tests/test_client.py`. |
| `weatherbot/weather/store.py` | read_heartbeat/read_health read-only | ✓ VERIFIED | Both functions present, parameterized `WHERE id=?` (lines 421/433/439/451), zero writes. |
| `weatherbot/config/models.py` | cloud_threshold knob default 60 range 0-100 | ✓ VERIFIED | `cloud_threshold: int = 60` (line 296) + `@field_validator` enforcing 0-100 (lines 298-302). |
| `weatherbot/interactive/commands/weather_views.py` | alerts/sun/wind/next_cloudy + compass + _is_daytime | ✓ VERIFIED | All 5 functions present; store-free; reads `raw_onecall_imp`. |
| `weatherbot/interactive/commands/info.py` | help_cmd/locations | ✓ VERIFIED | help delegates to render_help; locations reads config only. |
| `weatherbot/interactive/commands/status.py` | status consuming read-only DaemonState | ✓ VERIFIED | Four D-02 sections; only `read_heartbeat` store call. |
| `weatherbot/interactive/state.py` | DaemonState read-only accessor | ✓ VERIFIED | Frozen DaemonState; next_fires/uptime; no mutation API. |
| `weatherbot/interactive/bot.py` | registry-driven dispatch inside unchanged ladder + envelope | ✓ VERIFIED | step (4) → parse_command; dispatch inside the single try/except; render_embed; daemon_state threaded. |
| `weatherbot/cli.py` | registry-generated subparsers + dispatch | ✓ VERIFIED | Loop over `registry.COMMANDS` builds subparsers; `_run_registry_command` + `render_text`. |
| `weatherbot/scheduler/daemon.py` | DaemonState construction + started_at, threaded into bot | ✓ VERIFIED | `started_at` captured (line 1054); read-only `DaemonState` built (line 1227) and passed to `BotThread`. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| command.py | registry.py | parse_command iterates `registry.COMMANDS_BY_KEYWORD_LEN_DESC` | ✓ WIRED | Confirmed in source + behavioral run. |
| client.py | One Call payload hourly[] | exclude=minutely only | ✓ WIRED | line 62. |
| weather_views.py | result.forecast.raw_onecall_imp | reads current/alerts/hourly/daily | ✓ WIRED | All handlers read `raw_onecall_imp`. |
| status.py | state.py + store.read_heartbeat | DaemonState next-fire + heartbeat read | ✓ WIRED | Confirmed. |
| bot.py | registry handlers | parse_command → spec.handler via run_in_executor inside existing try/except | ✓ WIRED | lines 156-198. |
| daemon.py | state.py DaemonState | constructed in run_daemon, threaded into bot | ✓ WIRED | lines 1227-1240. |
| cli.py | registry.COMMANDS | one subparser per spec | ✓ WIRED | lines 772-781; `BY_NAME` dispatch line 867. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| weather_views handlers | `result.forecast.raw_onecall_imp` | shared lookup core (`cache.lookup` / `lookup_weather`) → live One Call fetch | Yes (live fetch; hourly[] now retained) | ✓ FLOWING (code path); live data confirmation in human-verify |
| status | `read_heartbeat(db_path).last_success_utc` | daemon SQLite heartbeat row | Yes (real reader, defensive "none yet") | ✓ FLOWING |
| next_fires | scheduler jobs by `name|time|days` | live APScheduler | Yes (running next_run_time + trigger fallback) | ✓ FLOWING (live scheduler only populated on the running daemon) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Parser longest-first + word-boundary + case | `parse_command(...)` | sun home→sun/'home'; sunny day→None; next-cloudy here→matched; SUN home→sun/'home'; nonsense→None | ✓ PASS |
| All handlers wired | `all(callable(s.handler))` | True (7 specs) | ✓ PASS |
| help auto-generation | `render_help()` | contains every summary | ✓ PASS |
| compass 16-point | `compass(0/90/180/270/360)` | N E S W N | ✓ PASS |
| CLI help one-shot | `weatherbot help` | grouped Weather/Info list, exit 0 | ✓ PASS |
| Full suite | `uv run pytest` | 358 passed, 1 pre-existing audioop warning | ✓ PASS |

### Probe Execution

No conventional `scripts/*/tests/probe-*.sh` and no probe declarations in the PLANs. The phase's verification gate is the pytest suite (run above: 358 passed). N/A.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| CMD-09 | 12-01, 12-03 | `help` auto-generated from the command registry | ✓ SATISFIED | Single COMMANDS list; render_help; CLI+Discord derive from it. |
| CMD-10 | 12-02, 12-03 | `alerts <loc>` on demand | ✓ SATISFIED | `weather_views.alerts` reads raw_onecall_imp["alerts"]; wired both surfaces. |
| CMD-11 | 12-02, 12-03 | `locations` lists configured names | ✓ SATISFIED | `info.locations` reads config.locations, fetch/store-free. |
| CMD-12 | 12-02, 12-03 | `status` — alive + next scheduled send | ✓ SATISFIED | `status` via read-only DaemonState (next_fires/uptime/liveness/heartbeat). |
| CMD-13 | 12-02, 12-03 | `sun <loc>` sunrise/sunset | ✓ SATISFIED | `weather_views.sun` local-time conversion via ZoneInfo. |
| CMD-14 | 12-02, 12-03 | `wind <loc>` speed + direction | ✓ SATISFIED | `weather_views.wind` + pure compass helper. |
| CMD-15 | 12-01, 12-02, 12-03 | `next-cloudy <loc>` with configurable threshold | ✓ SATISFIED | `next_cloudy` hybrid hourly→daily; `config.cloud_threshold` (default 60, 0-100 validated); hourly[] retained in client. |
| CMD-16 | 12-01, 12-02, 12-03 | same guard ladder + failure isolation | ✓ SATISFIED | Guard ladder (1)-(3) unchanged; single non-propagating envelope; isolation test green; pure parser. |

All 8 declared requirement IDs are present in PLAN frontmatter and map to Phase 12 in REQUIREMENTS.md. No orphaned requirements. (Note: REQUIREMENTS.md still shows CMD-09 as `[ ]`/Pending and Phase 12 unchecked in ROADMAP — bookkeeping the orchestrator closes on phase completion; not a code gap.)

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| (none) | — | No TBD/FIXME/XXX in any phase-12 file | — | Clean |

The "store" string in `weather_views.py:6` and the `add_job`/`stamp_` strings in `state.py:8-9` are docstrings documenting the read-only constraint, not code — confirmed by import/call-line greps (no real imports or write calls).

### Human Verification Required

The operator explicitly DEFERRED the blocking LIVE-OPERATOR checkpoint (Plan 12-03 Task 4) on host `yahir-mint`. The code is built and the full suite passes (358). The live-surface behaviors can only be confirmed on the restarted live daemon:

1. **Discord live surface** — restart `weatherbot` on yahir-mint, then exercise every command + the bogus-location path as the operator (see frontmatter `human_verification[0]`).
2. **CLI live surface** — run the same commands as subcommands against the live config/API and confirm matching plain-text content + exit codes (`human_verification[1]`).
3. **Briefing isolation on the live daemon** — confirm a scheduled briefing still fires after the restart (`human_verification[2]`).

### Gaps Summary

No code gaps. Every must-have is verified against the actual codebase: the single self-describing registry is the one source of truth for help, the CLI subparsers, and the Discord dispatch; the parser is registry-driven, longest-first, word-boundary-guarded and pure; all 7 handlers exist, are wired, store-free, and read off the retained One Call payload (hourly[] now retained for next-cloudy); `status` reports via a read-only DaemonState; the guard ladder steps (1)-(3) and the single non-propagating isolation envelope are unchanged; CMD-09..16 are all accounted for. The only outstanding work is the operator-deferred live confirmation on yahir-mint, surfaced above as human-verification items rather than gaps.

---

_Verified: 2026-06-19T15:59:48Z_
_Verifier: Claude (gsd-verifier)_
