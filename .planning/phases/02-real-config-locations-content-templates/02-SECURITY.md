---
phase: 2
slug: real-config-locations-content-templates
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-10
---

# Phase 2 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| client → OpenWeather One Call / Geocoding API | Request URL carries the secret `appid`; the API JSON is untrusted input. | Secret key (outbound), untrusted JSON (inbound) |
| Forecast payload → SQLite store | Untrusted API JSON persisted; SQL must be parameterized. | Untrusted JSON |
| config.toml → Config model | User-editable file; malformed input (bad tz/units, extra keys, syntax errors) must fail loud, never at send time. | Untrusted (non-secret) config |
| user-editable template → renderer | A user template is untrusted text; substitution must run no logic and reject unknown tokens. | Untrusted text |
| user CLI input (`--geocode "query"`) → Geocoding API | User-supplied text passed only as an httpx query param (no shell/SQL/eval). | Untrusted text |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-02-01 | Information disclosure | weather/client.py (One Call + geocode) | mitigate | httpx logger pinned WARNING (`client.py:39`, covers both calls); `appid` only in httpx params (`client.py:55,78`), never logged/persisted | closed |
| T-02-02 | Denial of service | weather/models.py `Forecast.from_payloads` | mitigate | Defensive `.get() or {}`/`or []` (`models.py:168-181`); `alerts` absent on clear day → `[]` (`:172`); `_alert_line` returns "" when empty (`:86-87`) | closed |
| T-02-03 | Information disclosure | weather/store.py | mitigate | Persists only response JSON via `json.dumps(payload)` (`store.py:175`); parameterized `?` inserts (`:163-177`); no appid/URL persisted | closed |
| T-02-04 | Denial of service | weather/client.py | mitigate | `_TIMEOUT = 10.0` (`:33`) on `httpx.Client` (`:49,75`); `raise_for_status()` surfaces 401/403 (`:63,80`); not retried here (retry is Phase 4) | closed |
| T-03-01 | Tampering | config/models.py + cli.py load boundary | mitigate | `extra="forbid"` on all models (`models.py:34,66,79`); IANA tz validator (`:42-50`); units validator (`:52-57`). Hardening: `_load_config_reporting` (`cli.py:259-277`) catches FileNotFoundError/TOMLDecodeError/ValidationError → clean exit 1, logs only `path`+`error` | closed |
| T-03-02 | Tampering / Info-disclosure | templates/renderer.py | mitigate | Guarded regex `_TOKEN` (`renderer.py:31`); `render` whitelist substitution (`:77-81`); `validate_template` canonical whitelist (`:52-66`); no `str.format(**obj)`/`Formatter`/`eval` | closed |
| T-03-03 | Tampering | weatherbot/cli.py (send path) | mitigate | `validate_template(template_text)` fires at the load boundary before `render` (`cli.py:129-130`); a typo'd `{token}` aborts the send loudly | closed |
| T-04-01 | Information disclosure | cli.py (`--check`/`--geocode`) | mitigate | httpx WARNING (`client.py:39`); `do_geocode` logs `status` only (`cli.py:169`); `do_check` outcome-only (`:247,252,255`) | closed |
| T-04-02 | Spoofing / Info-disclosure | `--check` reachability probe | mitigate | 401/403 → distinct "subscription not active / not yet propagated" message without leaking the key (`cli.py:236-244`); single best-effort probe (`:233`) | closed |
| T-04-03 | Tampering | `--geocode` handler | mitigate | `do_geocode` only `print`s, never writes config (`cli.py:176-190`); `geocode` invoked solely from the `--geocode` branch (`:323-325`), never on the send path | closed |
| T-04-04 | Input validation | `--geocode` query | accept | Query passed only as an httpx params value `{"q": query, ...}` (`client.py:78`); no shell/SQL/eval surface — safe by design | closed |
| T-0x-SC | Tampering (supply chain) | package installs | accept | No `pyproject.toml`/`uv.lock` changes in Phase 2 (last touched Phase 1); no new packages introduced | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-02-01 | T-04-04 | `--geocode` query reaches only the httpx Geocoding API as a `params` value — no shell, SQL, or eval interpolation, so there is no injection surface to mitigate in code. | Yahir | 2026-06-10 |
| AR-02-02 | T-0x-SC | No new dependencies were added this phase (verified against `git log` of `pyproject.toml`/`uv.lock`), so no supply-chain slopcheck gate is required. | Yahir | 2026-06-10 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-10 | 12 | 12 | 0 | gsd-security-auditor |

**Notes:** Register authored at plan time (02-01 through 02-04 PLAN threat models); verified against implementation (not docstring intent). Two post-plan changes re-checked for regression: the per-location `units` override (02-05) flips display order only and does not regress T-02-01/02/03/04 or FCST-04 dual-unit fetch; the `_load_config_reporting` UAT hardening logs only `path` + exception string (no secret/file-content echo) and reinforces T-03-01 fail-loud. Full suite at audit time: `uv run pytest -q` → 100 passed. No `## Threat Flags` in any Phase 2 SUMMARY; no unregistered attack surface.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-10
