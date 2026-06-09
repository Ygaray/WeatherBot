---
phase: 01
slug: first-briefing-end-to-end
status: verified
threats_open: 0
threats_total: 13
threats_closed: 13
asvs_level: 1
created: 2026-06-09
---

# SECURITY.md — Phase 1: First Briefing End-to-End

**Audit date:** 2026-06-09
**Scope:** Threat register authored at plan time (register_authored_at_plan_time: true). This audit
VERIFIES that each declared mitigation is present in the implemented code — it does not scan for new,
unrelated vulnerabilities.
**ASVS level:** unset at config (no level declared); recorded as 1 by template default.
**block_on:** high
**Result:** SECURED — 13/13 plan-time threats closed (12 mitigate verified in code + 1 accept documented below).

> Note: the auditor counted 16 sub-evidence rows; the canonical plan-time register is 13 threat IDs
> (T-01-01/02/SC, T-02-01/02/03, T-03-01/02/03, T-04-01/02/03/SC). All resolved.

---

## Threat Verification Record

| Threat ID | Category | Disposition | Status | Evidence (file:line) |
|-----------|----------|-------------|--------|----------------------|
| T-01-01 | Information Disclosure | mitigate | CLOSED | `weatherbot/config/models.py:42-53` Config has NO secret field (locations/template/webhook only); secrets confined to `weatherbot/config/settings.py:28-29` (`openweather_api_key`, `discord_webhook_url`); `.gitignore:4` (`.env`) and `.gitignore:10` (`data/`). Asserted: `tests/test_config.py:61-65` (`test_config_model_has_no_secret_fields`). |
| T-01-02 | Tampering | mitigate | CLOSED | `weatherbot/config/loader.py:27` `Config.model_validate(raw)` + `model_config = ConfigDict(extra="forbid")` on all models (`models.py:23,36,49`) → fail-loud `ValidationError`. Asserted: `tests/test_config.py:123-135` (`test_malformed_location_missing_lat_fails_loud`). |
| T-01-SC | Tampering (supply chain) | mitigate | CLOSED | Blocking human-verify package-legitimacy gate executed and APPROVED — `01-01-SUMMARY.md:76,99` (Task 4: all 7 locked deps verified against canonical PyPI/repo sources; uv via Astral's official installer). |
| T-02-01 | Information Disclosure | mitigate | CLOSED | `weatherbot/weather/client.py:33` `logging.getLogger("httpx").setLevel(logging.WARNING)` suppresses the URL-bearing INFO line; `appid` passed only as a query param (`client.py:47`), never logged. Asserted: `tests/test_client.py:102-111` (`test_appid_not_logged`). |
| T-02-02 | Denial of Service | mitigate | CLOSED | Defensive `.get()` / `or {}` / `or []` parsing throughout `weatherbot/weather/aggregate.py:44-67` and `weatherbot/weather/models.py:93-116`; clear-sky `pop` defaulted to 0.0 (`aggregate.py:66-67`), empty-bucket → high/low `None` (`aggregate.py:69-71`). Asserted: `tests/test_aggregate.py:32` (clear sky), `:69` (late-day no buckets); `tests/test_models.py:66,75,92`. |
| T-02-03 | Denial of Service | mitigate | CLOSED | `weatherbot/weather/client.py:27,41` `httpx.Client(timeout=_TIMEOUT)` with explicit finite `_TIMEOUT = 10.0`. Asserted: `tests/test_client.py:75-85` (`test_explicit_timeout_set`). |
| T-03-01 | Information Disclosure | mitigate | CLOSED | `weatherbot/weather/store.py` persists ONLY response payloads as `raw_json` (`store.py:146,173` `json.dumps(payload)`/`json.dumps(bucket)`); no `httpx`/`appid`/request-URL reference anywhere in the module (grep: only docstring mention at line 17). Asserted: `tests/test_store.py:167-183` (`test_no_secret_in_stored_json` — no `appid`, no `api.openweathermap.org` in any stored blob). |
| T-03-02 | Tampering | mitigate | CLOSED | `templates/renderer.py:31,42-46` substitution is a regex `_TOKEN = re.compile(r"\{(\w+)\}")` + `_TOKEN.sub` over a flat str→str whitelist (`values[key]`); `{x.attr}`/`{x[0]}`/`{0}` are NOT matched, no `str.format`/`Formatter`/`eval` in source (grep clean — line 9 is docstring only). Asserted: `tests/test_renderer.py:78-82` (`test_renderer_uses_no_dangerous_substitution`). NOTE: implementation uses a regex-substitution guard, which is stronger than the `Formatter().vformat` approach described in 01-03-SUMMARY; the mitigation intent (no format-string injection, no eval) is fully satisfied. |
| T-03-03 | Denial of Service | mitigate | CLOSED | `templates/renderer.py:44` unknown token returns `match.group(0)` (the literal `{key}`) rather than raising. Asserted: `tests/test_renderer.py:61-65` (`test_missing_placeholder_stays_visible_and_does_not_raise`). |
| T-04-01 | Information Disclosure | mitigate | CLOSED | `weatherbot/channels/discord.py:34` `logging.getLogger("discord_webhook").setLevel(logging.WARNING)`; `_url` kept private (`:46`); logs carry status / exception-class-name only (`:95-116`); `DeliveryResult.detail` never includes the URL (status + body snippet only, `:115,117`). `weatherbot/cli.py:120-124` logs outcome only. Asserted: `tests/test_channel.py:177-184` (`test_failure_detail_does_not_leak_webhook_url`), `:187-196` (`test_no_log_record_contains_the_webhook_url`), `:218-235` (network-error detail carries no secret). |
| T-04-02 | Spoofing | accept | CLOSED | Accepted risk — see "Accepted Risks Log" below. |
| T-04-03 | Tampering | mitigate | CLOSED | `weatherbot/channels/base.py` `Channel.send(self, text: str)` is text-only (`:48`); module has ZERO `DiscordEmbed` reference (grep: only docstring mentions). Embed built inside `DiscordWebhookChannel.send_briefing` (`discord.py:54-70`) and never crosses `send(text)`. Asserted: `tests/test_channel.py:69-75` (text-only ABC signature), `:93-99` (no embed param), `:102-107` (send attaches no embed), `:140-144` (`test_base_module_has_no_embed_reference`). |
| T-04-SC | Tampering (supply chain) | mitigate | CLOSED | `discord-webhook` covered by the Plan 01 blocking legitimacy checkpoint (verified release, `01-01-SUMMARY.md:76`); no new/unlisted installs in Plan 04 (`01-04-SUMMARY.md` tech-stack added: `[discord-webhook]` only). |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-04-02 | Discord webhook URL is a bearer credential, gitignored via `.env`, never on `Config`/`config.toml`, kept private in the channel and never logged. No in-code mitigation for a stolen valid credential — by design. User remedy: rotate the webhook in Discord and update `.env`. | Plan-time threat model (disposition: accept); confirmed valid by this audit | 2026-06-09 |

### T-04-02 — Leaked Discord webhook URL permits posting as WeatherBot (Spoofing)

**Disposition:** accept (declared at plan time).
**Rationale verified:** The Discord webhook URL is a bearer-style credential, treated identically to a
secret in this codebase:
- It lives ONLY on `Settings` (`weatherbot/config/settings.py:29`), loaded from the environment / `.env`,
  and never on the non-secret `Config` model or in `config.toml` (CONF-02 boundary verified under T-01-01).
- `.env` is gitignored (`.gitignore:4`), so the URL is never committed.
- It is kept private in the channel (`weatherbot/channels/discord.py:46`) and never logged or echoed
  into a `DeliveryResult.detail` (verified under T-04-01).

**Residual risk:** If the host environment or `.env` file is compromised, an attacker can post messages
impersonating WeatherBot to the configured Discord channel. There is no in-code mitigation for a stolen
valid credential — by design.
**User remedy:** Rotate the webhook URL in Discord (delete + recreate the webhook) and update `.env`.

---

## Unregistered Flags

None. No `## Threat Flags` section was declared in any Phase 1 SUMMARY. Each SUMMARY's
"Threat Model Coverage" section explicitly states "No new threat surface introduced beyond the plan's
`<threat_model>`" (`01-02-SUMMARY.md:135`, `01-03-SUMMARY.md:146`). No new attack surface appeared
during implementation without a threat mapping.

---

## Verification Method

- Full test suite re-run at audit time: `uv run pytest -q` → **67 passed** — confirming each mitigation
  is actively enforced, not merely present in comments.
- Each `mitigate` threat verified by locating the actual mitigation call/guard in the cited file AND a
  test that asserts it (not by code structure or docstring intent).
- The single `accept` threat (T-04-02) verified by confirming the accepted-risk rationale holds (URL is
  gitignored, treated as a credential, never logged) and recording it in the Accepted Risks Log above.
- Supply-chain threats (T-01-SC, T-04-SC) verified against the human-approved blocking checkpoints
  recorded in the plan SUMMARYs.
- Implementation files were NOT modified during this audit (read-only).

---

## Audit Trail

### Security Audit 2026-06-09
| Metric | Count |
|--------|-------|
| Threats found | 13 |
| Closed | 13 |
| Open | 0 |
