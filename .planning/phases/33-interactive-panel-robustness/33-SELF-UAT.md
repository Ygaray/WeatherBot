---
status: complete
result: all_pass
gate: 1
phase: 33-interactive-panel-robustness
source: [33-ROADMAP success criteria]
device: CLI/dispatch surface (headless, ephemeral local invocation — NO live daemon, NO Discord gateway)
apk: interactive-modules md5 454b467eadf59bd6d97ed8ad220b54d6 @ b4d72af
run: 2026-07-12T23:05:00-04:00
---

<!--
Gate-1 autonomous behavioral self-UAT for Phase 33 (Interactive & Panel Robustness).
Driver playbook: AGENT-CLI-TESTING.md (CLI/dispatch is the drivable surface; the Discord
command dispatch routes through the SAME weatherbot/interactive/dispatch.py dispatch_spec,
so driving the real on_message -> dispatch_spec -> ForecastCache -> lookup_weather ->
render_embed path exercises the real Discord command path).
SAFETY: the live production daemon weatherbot.service stayed ACTIVE and untouched — verified
read-only (`systemctl is-active` only). All drives ran from ephemeral in-memory / tempdir
harnesses with the OpenWeather HTTP boundary (`weather.client.fetch_onecall`) patched to
recorded fixtures — NO network, NO Discord post.
-->

# Self-UAT Log — Phase 33 (Interactive & Panel Robustness)

**Surface:** WeatherBot CLI/dispatch (headless; gateway-free `on_message` + real `ForecastCache`/`lookup_weather`/`render_embed`)   **Build:** driven-modules md5 `454b467eadf59bd6d97ed8ad220b54d6` @ git `b4d72af`   **Run:** 2026-07-12T23:05-04:00
**Working tree:** only `.planning/` modified — ZERO production-code changes (`git status --porcelain` clean of `weatherbot/`), so the run is against HEAD, not a stale/dirty build.
**Pre-flight:** `import weatherbot.cli, .interactive.{dispatch,bot,cache,panel}, .scheduler.wiring, .weather.models` → IMPORT OK.
**Unit suite:** `.venv/bin/python3 -m pytest -q` → **869 passed, exit 0** (the "2 snapshots failed" banner is the known syrupy quirk — exit code 0; trust exit + .ambr). 11 named phase-33 regression tests → 11 passed.
**Coverage/Nyquist:** goal-backward code verification already PASSED (`33-VERIFICATION.md`, 18/18 must-haves) — this log is the behavioral layer on top, re-derived from the ROADMAP criteria and re-observed first-hand (not trusting the prior verdict).
**Seed/fixture integrity:** all drives seed a real `Config` via the production `load_config()` loader from an ephemeral TOML (default `Toronto`/America-Toronto, named `London`/Europe-London metric). OpenWeather boundary patched to recorded fixtures `onecall_{imperial,metric}_clear.json` / `_dtskew.json` / `_8day_*.json` (byte-faithful recorded payloads). Heartbeat seeded via the production `store._connect` UPDATE. Seeding is programmatic (config loader + store); only the SUT is driven.

## Criteria

### 1. HARD-UI-01 (F02) — bare location command resolves the default and returns a correct reply (not "AttributeError → something went wrong")
result: passed
- **Rung:** 3 (headless data-level drive of the real `on_message` path) + adversarial crash-first proof.
- **Expected (from ROADMAP SC1):** a bare `!weather`/`!sun`/`!wind`/`!alerts`/`!uv`/`!next-cloudy` (no location arg) resolves the DEFAULT location (`config.locations[0]`, matching the CLI's `resolve_location(None)`) and returns a real forecast reply — never the generic error.
- **Arranged (seeded):** real `Config` (default `Toronto`) via production `load_config()`; `fetch_onecall` patched to recorded fixtures; fresh real `ForecastCache` per drive (starts from a genuine miss → real fetch path).
- **Did (drove):** built the REAL `bot.build_on_message(holder, operator_id, cache)` and invoked the returned `on_message` coroutine with a fake operator `Message` whose `content="!weather"` (then `!sun`/`!wind`/`!alerts`/`!uv`/`!next-cloudy`). This drives the real guard ladder → `dispatch_spec` (the F02 branch) → `ForecastCache.lookup` → `lookup_weather` → `render_embed`.
- **Observed:** every one of the six bare commands sent a REAL embed (`channel.send(embed=…)`), NOT `_ERROR_REPLY`; the default fetch ran for `Toronto`; the 📍 header rendered `📍 Toronto (default)`. Named `!weather London` rendered `📍 London` unmarked (no `(default)`). **Crash-first falsification:** with the app-side F02 default-resolution branch bypassed in-memory (no source edit — monkeypatched `bot.dispatch_spec` to call the module dispatcher with `arg=None` unchanged), the SAME bare `!weather` reproduced the exact documented defect — `AttributeError: 'NoneType' object has no attribute 'forecast'` at `weather_views.py:111` → `on_message` envelope → generic `_ERROR_REPLY` — and restoring the real branch immediately produced `📍 Toronto (default)`. This proves the fix is load-bearing and the criterion genuinely holds, not incidentally.
- **Evidence:** live drives + crash-first monkeypatch script output (transcript); `dispatch.py:133-141` (app-side branch); `bot.py:516,555-558` (`was_bare`, `_location_label`, `render_embed(location=)`); `tests/test_bot.py::{test_bare_weather_no_longer_crashes,test_bare_weather_default}` PASS.

### 2. HARD-UI-02 — hot-reload mid-fetch no longer serves a stale cached result for the TTL (F13 generation guard); panel cache bounded so heavy forecast/flag use can't evict the plain `!weather` entry (`_PinnedTTLCache`); plus F17/F22/F23/F24
result: passed
- **Rung:** 3 (direct behavioral drive of the real `ForecastCache` invariants) + 1 (named harness tests for the reload/panel-ordering items).
- **Expected (from ROADMAP SC2):** an off-loop fetch that started before an `invalidate()` must NOT re-populate a pre-reload result to TTL; the plain `!weather` (suffix=None) entry must never be the evicted one under bounded churn; invalidate-before-send (F17), selection reconcile (F22), empty-locations recovery (F23), ack rollback (F24) hold.
- **Arranged (seeded):** real `ForecastCache` instances; `lookup_weather` stubbed at the cache module (the fetch is the road TO the SUT, not the SUT — the generation guard and eviction ARE the SUT and are driven live); real `Config` with 1 location.
- **Did (drove):** (F13) drove `cache.lookup("home", cfg)` where the stubbed fetch fires `cache.invalidate()` mid-flight (config reloaded while the fetch was in flight), then a follow-up `lookup`. (bounding) seeded the plain entry then drove 20 distinct suffixed `lookup(..., "forecast|variant-i")` past `maxsize=4`, then re-`lookup`ed the plain key. Ran the F17/F22/F23/F24 named harness tests.
- **Observed:** (F13) the stale mid-flight result was REFUSED — the follow-up lookup REFETCHED (fetch count = 2), i.e. no stale pre-reload snapshot survived to TTL; a negative control WITHOUT the mid-flight invalidate served a cached HIT (fetch count = 1), proving the guard fires ONLY on the race, not always. (bounding) the plain `!weather` entry survived all 20 suffixed churns and was served by object identity (never refetched) — the plain entry is never the evicted one. (F17/F22/F23/F24) `test_invalidate_before_send`, `test_selection_reconcile_on_reload`, `test_empty_locations_recover`, `test_ack_failure_rollback` all PASS.
- **Evidence:** direct-drive script output (F13 guard 2-fetch + negative-control 1-fetch; pinned-eviction identity check); `cache.py:154-176` (gen captured in get-lock, store-guard), `cache.py:69-87` (`_PinnedTTLCache.popitem` protects suffix=None), `cache.py:194-196` (invalidate bumps generation under lock); `wiring.py` invalidate-before-send + `_reconcile_selection`; `panel.py` non-raising empty-locations + ack rollback.

### 3. HARD-UI-03 — clean render: no duplicated header, no empty-token trailing blanks, human-formatted LOCAL timestamps (incl. `!status` Last briefing), dt-paired imperial/metric temps (F11/F107), dated out-of-today labels (`Thu Jul 17`), default location marked (📍 … (default))
result: passed
- **Rung:** 3 (live embed/status render inspection) + 1 (forecast goldens for dated labels) + direct model drive for dt-pairing.
- **Expected (from ROADMAP SC3):** the forecast header appears exactly once; no trailing/interior blank lines from empty tokens; timestamps human-formatted local (not raw ISO), including the `!status` "Last briefing" clock in LOCAL time not UTC; imperial/metric daily temps paired by their own `dt` not positionally; out-of-today buckets dated `Www Mmm D`; the bare/default location marked.
- **Arranged (seeded):** real `Config`; recorded fixtures; heartbeat seeded at a KNOWN UTC epoch (`1718874000` = 2024-06-20 09:00 UTC = 05:00 America/New_York) via `store._connect`; dt-skew fixtures whose metric bucket carries a distinctive WRONG 100°C at a shifted `dt`.
- **Did (drove):** drove the real `on_message` for `!weekday-forecast` and `!weather` and inspected the rendered `Embed` title/description/fields; drove the real `status` command and read the "Last briefing" line; drove `Forecast.from_payloads` directly with the dt-skew fixtures; ran the forecast golden tests.
- **Observed:** **header dedup** — the title text (`Weekday forecast — Toronto`) appeared 0 times inside the body; no interior `\n\n\n` and no trailing blank line. **timestamps** — the daily embed carries NO raw ISO (`\d{4}-\d{2}-\d{2}T…`) string; it uses Discord `<t:unix:t> (<t:unix:R>)` relative markdown (intended; D-07 targets the template/CLI/status paths). **`!status` Last briefing** — rendered `05:00` (LOCAL America/New_York), NOT `09:00` (UTC); the old UTC code would have shown `09:00` — the HR-01/D-07 fix confirmed first-hand. **dt-pairing (F107)** — the dt-skewed metric 100°C bucket was NOT mispaired; render degraded to imperial-only `76°F` / `58°F` (a positional pairing would have produced `76°F (100°C)`). **dated labels (D-06)** — the committed forecast goldens render `Mon Jun 22 → Fri Jun 26`, `Thu Jun 25`, etc. (weekday + abbrev month + day); the 8 forecast golden snapshots PASS. **marker (D-05)** — bare renders `📍 Toronto (default)`, named renders `📍 London` (confirmed under SC1).
- **Evidence:** live render inspection transcript (title-in-body count 0; no ISO; `!status` `05:00`); direct dt-skew drive (`76°F`/`58°F`, no `100°C`); `test_golden_embeds/test_golden_cli` forecast snapshots (8 passed); `tests/test_status.py::test_last_briefing_renders_local_not_utc`, `tests/test_models.py::{test_dt_paired_briefing,test_metric_missing_keeps_imperial}` PASS.

## Summary

total: 3
passed: 3
partial: 0
failed: 0
infra: 0

## Notes / anomalies (for the Gate-2 reviewer)

- **Live-Discord visual render is NOT part of this Gate-1** (safety: no post to the production gateway/webhook). The mechanism (real `render_embed`/`dispatch_spec`/`on_message` path) and the RESULT (the embed title/description/fields and status lines the operator would see) were both verified headless first-hand. What remains unverified is only the physical rendered appearance of the embed in a real Discord client and a real panel-button tap — registered as a Gate-2 obligation in HUMAN-UAT-PENDING.md, NOT a phase blocker.
- **Dated-label live-render caveat:** the shipped `onecall_8day_*.json` fixtures carry 2025-era daily dates, so driving `!weekday-forecast` through `on_message` at today's clock (2026-07-12) renders "beyond the 7-day horizon" rather than fresh `Www Mmm D` labels. The dated-label render is therefore verified via the frozen-clock forecast GOLDEN snapshots (which pin the exact `Mon Jun 22`/`Thu Jun 25` output) rather than a live inbound drive — an Arrange-fixture limitation, not a code defect.
- **The daily embed intentionally keeps Discord `<t:unix:t>` relative markdown** (truth #22 in 33-VERIFICATION.md): the D-07 ISO→human fix is scoped to the template/CLI/`!status` paths, not the embed's native relative-time markdown. Confirmed no raw ISO leaks into the embed.
- "2 snapshots failed" pytest banner is the known syrupy report quirk (exit code 0); full suite is green.
- Live production daemon `weatherbot.service` stayed ACTIVE and was only queried read-only — never stopped/reloaded/posted-to.

## Findings routed to gap-closure (if any)

- None. All three criteria PASS.

## Verdict

All 3 criteria PASS → Gate-1 complete; human Gate-2 (live-Discord embed/panel visual) deferred to milestone completion (registered in HUMAN-UAT-PENDING.md).
