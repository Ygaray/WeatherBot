---
phase: 13
slug: multi-day-forecast-templates
status: secured
threats_open: 0
threats_total: 20
threats_closed: 20
asvs_level: 1
block_on: high
created: 2026-06-23
---

# SECURITY.md — Phase 13: Multi-Day Forecast Templates

**Audit type:** Threat-mitigation verification (register authored at PLAN time; each declared mitigation verified against implemented code — not against documentation or intent).
**ASVS Level:** 1
**block_on:** high
**Threats:** 20 total — 18 `mitigate`, 2 `accept`
**Result:** SECURED — 20/20 CLOSED, 0 OPEN.

---

## Threat Verification (mitigate)

| Threat ID | Category | Evidence (file:line) |
|-----------|----------|----------------------|
| T-13-01 | Tampering | `weatherbot/weather/models.py:488-547` — `ForecastDay.from_daily` uses `.get(...) or default` on every field; feels-high/low derived via `max()/min()` over `feels_like` daypart `.values()` (l.519-525), never `feels_like.max`; `day_imp = day_imp or {}` / `day_met = day_met or {}` coalesce null dicts. Malformed/null fields degrade, never raise. |
| T-13-02 | DoS | `weatherbot/weather/multiday.py:49-58,119-134` — `_date_index_map` builds a local-date→index map from each `daily[i].dt`; `select_days` maps desired dates via `by_date.get(d)` (l.126), and an unmatched (beyond-horizon) date becomes a notice string (l.127-130), never positional indexing / `IndexError`. |
| T-13-03 | Tampering | `weatherbot/weather/multiday.py:83-90` — `select_days` raises `ValueError` on any `kind` not in {weekday, weekend} (fail-loud). |
| T-13-04 | Tampering/EoP | `templates/renderer.py:171-196` — `render_forecast` routes the per-day `line_fmt` AND the whole-message `template_text` through the existing guarded `validate_template`/`render`; `render` uses regex `_TOKEN = \{(\w+)\}` whitelist substitution (l.31,164-168) — no `str.format`/`Formatter`/`eval`. Per-day loop lives in code (l.194). |
| T-13-05 | Tampering | `templates/renderer.py:193,195` — `validate_template(line_fmt, allowed=day_allowed)` and `validate_template(template_text, allowed=FORECAST_TOKENS)` both fire BEFORE any render; `validate_template` raises `ValueError` on any unknown token (l.139-153). |
| T-13-07 | Tampering/EoP | `weatherbot/interactive/command.py:138-209` — `parse_forecast_flags` uses only `str.split`/`str.casefold`/slicing; `_day_token` (l.203-209) raises `ValueError` listing `sorted(_DAYS)` on an unknown day token. CLI entry `weatherbot/cli.py:580-589` is the only parse path and exits 1 on the `ValueError`. No `str.format`/`eval`/`exec`/shell on the path. |
| T-13-08 | Tampering/DoS | `weatherbot/config/models.py:118-155` — `ForecastSchedule` field_validators: `_hhmm` (time), `_days_valid` (parse_days), `_kind_valid` ({weekday,weekend}), `_variant_valid` ({detailed,compact}) all raise at load. `frozen=True` + reload keep-old (loader) means a rejected config never swaps. |
| T-13-09 | Tampering | `weatherbot/config/models.py:110` — `ForecastSchedule.model_config = ConfigDict(extra="forbid", frozen=True)` rejects any unknown key in `[[locations.forecast]]` at load. |
| T-13-10 | EoP/Access Control | `weatherbot/interactive/bot.py:246-339` — forecast dispatch (l.313-314) sits INSIDE the existing guard ladder: `author.bot` (l.249) → `author.id != operator_id` (l.252) → `!`-prefix (l.256) → registry parse (l.260) → single non-propagating try/except (l.270-337). No new bypass path. |
| T-13-11 | Tampering | `weatherbot/interactive/commands/forecast.py:1-206` — module imports nothing from `weatherbot.weather.store`; reads `result.forecast.raw_onecall_imp/met` only; takes no write `db_path`; returns a read-only `CommandReply`. (Per SUMMARY, proven by an AST-scanning zero-store-writes spy in `tests/test_forecast_lookup.py`.) |
| T-13-12 | DoS | `weatherbot/interactive/bot.py:332-337` — handler runs inside a single non-propagating try/except; a raised error is logged via `_log.exception` (no channel traceback) and yields `_ERROR_REPLY` (generic reply); never re-raised, never crashes dispatch. CLI mirror at `cli.py:634-637`. |
| T-13-13 | Info Disclosure | `weatherbot/interactive/commands/forecast.py` — no One Call URL constructed/logged on this path; content is config-sourced names + weather data + fixed labels. Scheduled-fire log is outcome-only (see T-13-19). |
| T-13-14 | Tampering | `weatherbot/interactive/commands/forecast.py:152-167` — `header_values` carries only `location` (config name), `title`/`range_label`/`footer_note` (fixed labels), and `{notice}` (code-built horizon strings). No free user text is echoed into the post; mentions/`@everyone` cannot be injected. |
| T-13-15 | DoS | `weatherbot/scheduler/daemon.py:475-548` — entire `fire_forecast_slot` body wrapped in `try/except` that logs and `return None`; registered as an independent cron job (l.655-680); never calls `claim_slot`. A forecast failure cannot crash the APScheduler thread or gate a briefing. |
| T-13-16 | Tampering | `weatherbot/scheduler/daemon.py:438-548` — `fire_forecast_slot` body calls no `claim_slot`/`release_claim`/`record_alert`/store function (grep over the body returns only the docstring mention at l.465); imports nothing from the store. (Per SUMMARY, proven by zero-store-writes spy.) |
| T-13-17 | Tampering/DoS | `weatherbot/config/loader.py:143-164` — `validate_config_and_templates` validates every referenced forecast template: whole-message against `FORECAST_TOKENS`, sibling `.line.txt` against `forecast_day_allowed(fc.variant)`, deduped by `(kind, variant)`. Fires at load AND reload (keep-old). |
| T-13-18 | Tampering/DoS | `weatherbot/config/models.py:118-155` — `ForecastSchedule` fail-loud validators (same as T-13-08) reject a malformed slot at load/reload before `_register_jobs` (`daemon.py:655`) ever enumerates it. |
| T-13-19 | Info Disclosure | `weatherbot/scheduler/daemon.py:518-536` — both success (`_log.info`) and failure (`_log.exception`) logs carry only `location`/`kind`/`variant`/`time`; no appid/webhook/token constructed or logged on this path. |

## Accepted Risks (accept)

| Threat ID | Category | Disposition | Accepted-Risk Rationale (verified) |
|-----------|----------|-------------|------------------------------------|
| T-13-06 | Info Disclosure | accept | Forecast token scopes (`templates/renderer.py:75-101`: `FORECAST_TOKENS`, `FORECAST_DAY_TOKENS_DETAILED/COMPACT`) contain only weather/label tokens — no `appid`/`webhook`/`token` token exists, so a user-editable forecast template cannot reference a secret. Accepted: no secret token is exposed to the template surface. |
| T-13-SC | Tampering | accept | Phase 13 installs ZERO packages — no `uv add`/`pip install` task in any of plans 13-01..13-05 (all SUMMARY `tech-stack.added: []`). Supply-chain surface unchanged from prior phases. Accepted: no new dependency introduced. |

## Unregistered Flags

None. The `## Threat Flags` / `## Threat Surface` section of every Phase 13 SUMMARY (13-02 through 13-05) reports "None" / "No new threat surface beyond the plan's `<threat_model>`." No new attack surface appeared during implementation without a threat mapping.

## Notes

- Implementation files were treated as READ-ONLY; this audit created only this SECURITY.md.
- One adjacent in-code mitigation observed while verifying (not a Phase-13 threat, recorded for completeness): `weatherbot/config/models.py:210-225` `_no_pipe_in_identity` forbids `|` in `name`/`id` so a crafted name cannot collide a forecast job-id (`name|fc|...`) with a briefing job-id. Reinforces T-13-15/T-13-18 robustness; no action needed.
