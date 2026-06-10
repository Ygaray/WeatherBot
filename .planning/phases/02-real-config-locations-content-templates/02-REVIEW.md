---
phase: 02-real-config-locations-content-templates
reviewed: 2026-06-09T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - weatherbot/cli.py
  - weatherbot/config/__init__.py
  - weatherbot/config/loader.py
  - weatherbot/config/models.py
  - weatherbot/weather/client.py
  - weatherbot/weather/models.py
  - weatherbot/weather/store.py
  - templates/renderer.py
  - templates/briefing-compact.txt
  - templates/briefing-multiline.txt
  - templates/briefing-sectioned.txt
  - config.example.toml
  - tests/test_cli.py
  - tests/test_client.py
  - tests/test_config.py
  - tests/test_models.py
  - tests/test_renderer.py
  - tests/test_review_hardening.py
  - tests/test_send_now.py
  - tests/test_store.py
findings:
  blocker: 1
  warning: 6
  info: 3
  total: 10
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-09
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

This phase migrated the data source from OpenWeather 2.5 (weather + 3-hour bucket
aggregation) to a single One Call 3.0 fetch, added per-location IANA timezone +
units config, a `validate_template` send-boundary guard, and `--geocode` / `--check`
CLI subcommands. The secret-hygiene story is strong: the `appid` is kept out of
logs (httpx logger raised to WARNING), out of the stored payloads, and the
`--check` 401/403 probe distinguishes subscription-not-propagated from a generic
error without echoing the URL or key. The One Call payload→Forecast mapping is
defensive against present-but-null members (`or {}` / `or []`), and `--geocode`
correctly never writes config and never runs on the send path.

The dominant finding is a **dead config feature**: the per-location `units`
override that this phase added, validated, documented in `config.example.toml`,
and tested at the model layer is **never read by any send/check code path**. A
user who sets `units = "metric"` on a location gets an imperial-primary briefing
anyway — the setting silently does nothing, which directly violates the project's
core promise that "all user-facing settings must be editable" and behave as
configured. Several lower-severity robustness and ordering issues follow.

No structural findings block was provided.

## Critical Issues

### CR-01: Per-location `units` override is validated and documented but never consumed (dead config)

**File:** `weatherbot/cli.py:106-107`, `weatherbot/config/models.py:40`, `config.example.toml:38`
**Issue:**
`Location.units` is a first-class config field added this phase — it is validated
(`_units_valid`), advertised in `config.example.toml` (`units = "imperial"` on the
"Weekend" location, plus the commented hint on "Home"), and covered by model-layer
tests. But **nothing on the send path ever reads it.** `send_now` unconditionally
fetches both unit systems and renders imperial-primary:

```python
onecall_imp = client.fetch_onecall(location, "imperial")
onecall_met = client.fetch_onecall(location, "metric")
forecast = Forecast.from_payloads(location, onecall_imp, onecall_met)
```

`Forecast` always displays imperial-as-primary (`temp_display`, `wind_display`,
`high_display`, etc. all hardcode `°F`-then-`°C` / `mph`-then-`m/s`). A grep
confirms `loc.units` / `location.units` is referenced **nowhere** outside the
validator and tests.

Consequence: a user who configures `units = "metric"` for their travel city (a
documented, validated, example-file setting) still receives an imperial-primary
briefing. The setting is inert. This is a correctness/contract defect — a
user-facing setting that the project explicitly requires to be "editable without
code changes" silently has no effect, which is worse than not offering it (the
user believes they configured metric and will be misled every morning).

**Fix:** Either (a) honor the override — thread `location.units` into the display
choice so a `metric` location renders metric-primary (and adjust the hint
thresholds, which are hardcoded imperial in `_hints`, to read the correct unit),
or (b) if per-location primary-unit selection is genuinely deferred to a later
phase, REMOVE `units` from `Location`, from `config.example.toml`, and from the
docstrings so no user can set a no-op. Do not ship a validated, documented setting
that does nothing. Minimal honor-path sketch:

```python
primary = location.units or "imperial"
# pass `primary` into Forecast / placeholders so display picks primary unit,
# and into _hints so cold/heat/wind thresholds compare against the right scale.
```

## Warnings

### WR-01: `_hints` fires false "cold"/other hints on a null/partial `current` payload

**File:** `weatherbot/weather/models.py:167-170, 190`
**Issue:** When `current` is present-but-null (the very degraded case the CR-02
defenses target), `feels_imp` / `wind_imp` coalesce to `0.0`. `_hints` then
evaluates `feels_imp < 40` → True and appends "Bundle up, it's cold 🧥" even though
no real temperature was returned. The reliability constraint says "never silently
miss a briefing" — here the briefing is delivered but with a fabricated hint
("bundle up, it's cold") derived from a zero placeholder, which is silently wrong.
`test_forecast_from_payloads_tolerates_null_current_fields` only asserts
`isinstance(fc.hint, str)`, so it does not catch this.

**Fix:** Track availability separately from value. Coalesce missing numerics to
`None` (or a sentinel) and skip hint evaluation when the source field is absent,
e.g.:

```python
feels_imp_raw = cur_i.get("feels_like")
# only evaluate cold/heat hints when feels_like was actually present
if feels_imp_raw is not None and feels_imp_raw < 40:
    lines.append("Bundle up, it's cold 🧥")
```

### WR-02: `send_now` persists and double-fetches before the template guard runs

**File:** `weatherbot/cli.py:106-119`
**Issue:** The docstring and `validate_template` framing call this a "send-boundary
guard" that aborts a typo'd template "loudly here rather than shipping a literal
placeholder." But in `send_now` the two One Call fetches (lines 106-107) and the
DB `persist` (line 112) both execute **before** `validate_template` (line 119). A
config with a bad template token therefore burns two API calls and writes two DB
rows on every invocation before aborting. The cheap, deterministic validation
should gate the expensive network/IO. (`--check` validates the template early and
correctly, so the gap is only on the `--send-now` path.)

**Fix:** Validate the template immediately after resolving the location, before
the fetch:

```python
location = resolve_location(config, location_name)
template_text = load_template(config.template, ...)  # load + validate FIRST
validate_template(template_text)
# ...then fetch / persist / render / deliver
```

### WR-03: `do_geocode` only catches `HTTPStatusError`; a network error crashes with a traceback

**File:** `weatherbot/cli.py:155-160`
**Issue:** `do_geocode` wraps `client.geocode(query)` in `except httpx.HTTPStatusError`
only. A connection failure / timeout (`httpx.ConnectError`, `httpx.ConnectTimeout`,
`httpx.ReadTimeout` — all `httpx.RequestError`, NOT `HTTPStatusError`) propagates
uncaught and crashes the CLI with a Python traceback instead of a clean non-zero
exit. The OpenWeather note in CLAUDE.md explicitly warns new keys can take ~2h to
activate and the network can fail at request time, so this path is realistic. (The
`str()` of the error does not embed the URL, so this is a robustness/UX gap, not a
key leak.) `do_check`'s broad `except Exception` does not have this problem — only
`do_geocode` does.

**Fix:** Catch `httpx.RequestError` (or `httpx.HTTPError`, the common base of both)
and report outcome-only:

```python
except httpx.HTTPError as exc:
    _log.error("geocode failed", error=type(exc).__name__)
    return 1
```

### WR-04: `config.example.toml` ships `avatar_url = ""` — an empty string, not an omitted/None avatar

**File:** `config.example.toml:43`
**Issue:** The example sets `avatar_url = ""`. This flows
`WebhookIdentity(avatar_url="")` → `DiscordWebhookChannel(avatar_url="")` →
`DiscordWebhook(avatar_url="")`. An empty-string avatar URL is not the same as
"no avatar" (which is `None`, the model default when the key is omitted, as
`test_config_template_and_username_defaults` asserts). Posting an empty `avatar_url`
to Discord is at best ignored and at worst produces an unexpected/blank avatar.
The example file — the thing users copy to `config.toml` — teaches the wrong value.

**Fix:** Comment the line out so it falls back to the `None` default, or document
a real URL:

```toml
[webhook]
username = "WeatherBot ☀️"
# avatar_url = "https://example.com/avatar.png"   # optional
```

### WR-05: `--geocode` hardcodes `timezone = "America/Chicago"` in every paste snippet regardless of the resolved location

**File:** `weatherbot/cli.py:179`
**Issue:** The paste-ready `[[locations]]` snippet always prints
`timezone = "America/Chicago"` even when the user geocoded e.g. "New York" or
"London". Since `timezone` is a REQUIRED, IANA-validated field, a user who pastes
the snippet verbatim (the whole point of "paste-ready") gets a config whose
timezone is wrong for the place they just looked up — and it will validate fine,
so the error is silent: "today"/`daily[0]` selection (D-03) is computed for the
wrong zone. A geocode result carries `country`/`state` but not an IANA zone, so a
literal best-guess is misleading.

**Fix:** Make the timezone a visibly-unfilled placeholder the user MUST edit, e.g.
`#   timezone = "REPLACE_ME/IANA_zone"  # required: set the IANA zone for these coords`,
so a verbatim paste fails loud at `--check` rather than silently using Chicago.

### WR-06: `do_check` docstring claims step order (1)(2)(3)(4) but code runs (1)(2)(4)(3)

**File:** `weatherbot/cli.py:190-235`
**Issue:** The docstring describes "the four D-12 steps in order" with the live
reachability probe as step (3), but the code executes template validation (2),
`assert_unique_names` (4a), per-location `resolve_location` (4b), and only THEN the
probe (commented "(3)"). The probe is deliberately last so offline validation
fails before spending a network call — which is good — but the docstring's "in
order" claim is false and the inline `# (3)` / `# (4a)` markers are out of
sequence, which will mislead a future maintainer auditing the security-sensitive
probe placement.

**Fix:** Correct the docstring to state the actual order (cheap offline checks
first, single live probe last) and renumber the inline comments to match.

## Info

### IN-01: `_local_date_iso` is duplicated verbatim across two modules

**File:** `weatherbot/weather/models.py:34-49` and `weatherbot/weather/store.py:122-136`
**Issue:** The configured-IANA-tz "local date" helper is copy-pasted identically
into both `models.py` and `store.py` (same fallback-to-UTC logic, same docstring).
Two copies will drift; a fix to one (e.g. WR-01-style hardening) can silently miss
the other. Note also that `Location.timezone` is now REQUIRED and IANA-validated at
load, so the `getattr(loc, "timezone", None)` + invalid-zone fallback-to-UTC
branches are effectively dead defensive code (they can only fire for a
hand-constructed `Location` that bypassed validation).

**Fix:** Extract one shared helper (e.g. `weatherbot/weather/_localdate.py` or a
method on `Location`) and import it in both places.

### IN-02: `validate_template`'s `allowed` default is a mutable set shared across calls

**File:** `templates/renderer.py:52`
**Issue:** `def validate_template(template_text, allowed: set[str] = CANONICAL)`
uses the module-level mutable `CANONICAL` set as a default argument. It is only
ever read (set-difference), so there is no live bug today, but a future edit that
mutates `allowed` would corrupt the shared `CANONICAL` for every caller (and the
renderer relies on `CANONICAL` matching `Forecast.placeholders()` keys — a test
asserts this equality). This is the classic mutable-default footgun.

**Fix:** Default to `None` and bind inside, or annotate/treat as read-only:

```python
def validate_template(template_text: str, allowed: set[str] | None = None) -> None:
    allowed = CANONICAL if allowed is None else allowed
```

### IN-03: `do_check` post-hoc "nothing was delivered" guard is unreachable for the real channel

**File:** `weatherbot/cli.py:241-243`
**Issue:** After the validation block, `do_check` checks
`getattr(channel, "sent_text", None)` to assert nothing was delivered. The real
`DiscordWebhookChannel` has no `sent_text` attribute, so this guard only ever fires
for the test `_FakeChannel`. It is a test-only assertion living in production code;
`do_check` never calls `channel.send*`, so for any real channel the branch is dead.
Harmless, but it reads as a runtime safety check when it is really a test hook.

**Fix:** Either drop the production-side guard (the test already asserts
`channel.sent_text == []` directly), or document it explicitly as a test-only
invariant probe.

---

_Reviewed: 2026-06-09_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
