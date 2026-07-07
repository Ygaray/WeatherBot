---
status: passed
phase: 28-physical-repo-split-uv-git-dependency-extension-guide
source: [28-VERIFICATION.md, 28-SELF-UAT.md]
started: 2026-06-29
updated: 2026-06-29
gate: 2
note: Deferred Gate-2 milestone-close obligation per project Two-Gate UAT policy — does NOT block this phase (Gate-1 fully passed in 28-SELF-UAT.md). Batched to v2.0 milestone close.
---

## Current Test

number: 1
name: Live yahir-mint deploy + restart against the pinned module, panel still routes
expected: |
  After replacing the `file://` git URL with a fetchable `YahirReusableBot` remote and
  repinning (see deploy/REPIN-RITUAL.md): on host yahir-mint, `sudo systemctl restart weatherbot`
  brings the daemon up against the pinned module sha (138a907 / tag v0.1.0), the journal shows
  the `module provenance` startup-version-log line announcing that sha with editable=False, and
  every button/dropdown on the already-pinned Discord control panel still routes (no "interaction
  failed"), with the correct default location.
awaiting: user response

## Tests

### 1. Live yahir-mint restart against pinned module + panel routing (SC#3)
expected: |
  Prerequisite: create a fetchable `YahirReusableBot` remote and swap the `file://` URL in
  WeatherBot pyproject `[tool.uv.sources]`, then `uv lock --upgrade-package yahir-reusable-bot`
  and commit/push (deploy/REPIN-RITUAL.md). Then on yahir-mint:
    1. Pull the new WeatherBot commit + `uv sync --frozen`.
    2. `sudo systemctl restart weatherbot`.
    3. `journalctl -u weatherbot -n 50` shows the `module provenance` line with the pinned sha
       (== uv.lock sha) and editable=False.
    4. In Discord, tap every panel button + the location dropdown → each routes correctly
       (custom_id contract + persistent-view re-bind intact), correct default location shown.
  Gate-1 already proved the mechanism + data-level checks (provenance sha cross-check, custom_id
  byte-identical golden, persistent-view re-bind) in 28-SELF-UAT.md — only the physical
  secure-host restart + live Discord interaction defer here.
result: PASS (2026-07-07) — live yahir-mint restart against the pinned module confirmed; panel/reload/briefing/CLI all verified. A live-only `on_message` RecursionError (broke `!panel`) was found DURING this UAT and fixed + shipped as module `v0.1.1` (sha 7f3cc00, repin 2f24003); re-summoning restored the panel. The 776 mocked-Discord tests never caught it — Gate-2 earned its keep.

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None blocking. Outstanding prerequisite for this deferred item: a fetchable `YahirReusableBot`
network remote must replace the local `file://` git URL before the host can resolve the pin
(tracked in STATE.md). This is the only step between the byte-identical, fully-Gate-1-verified
split and a live production cutover.
