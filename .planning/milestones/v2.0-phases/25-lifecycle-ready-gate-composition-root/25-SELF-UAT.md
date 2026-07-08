# Phase 25 Plan 03 — Gate-1 Autonomous Self-UAT

**Policy:** CLAUDE.md Two-Gate UAT — Gate 1 (agent self-UAT) is autonomous and gates the
phase/PR; the live `yahir-mint` host reboot is a deferred Gate-2 (milestone-close) obligation,
NOT a per-phase blocker.

**Driven:** 2026-06-28
**Baseline for the byte-identical oracle:** Phase-21 golden snapshots committed at HEAD
(`tests/__snapshots__/`); no golden file edited during this UAT (verified via `git status`).
**Overall Gate-1 verdict:** **PASS** (criteria 1–4 at the mechanism level). One deferred
Gate-2 PARTIAL: the physical host reboot only.

> **Known pre-existing artifact (NOT a failure of this phase):** the whole-suite syrupy report
> prints `2 snapshots failed. 27 snapshots passed.` This is a standing syrupy *unused-snapshot*
> tally present at baseline (confirmed in 25-01-SUMMARY by running the suite with all lifecycle
> additions removed → identical tally). It is distinct from a real golden diff: zero test
> assertions fail, all 25 golden snapshots pass in isolation, and the full suite is green
> (777 passed). It is recorded here so it is never confused with a byte-identical regression.

---

## Criterion 1 — READY=1 reaches systemd ONLY after the app probe passes AND `scheduler.start()`

**What tested:** Drove the REAL `yahir_reusable_bot.lifecycle.ReadyGate` + the REAL
`SystemdNotifier` over a captured `AF_UNIX`/`SOCK_DGRAM` `NOTIFY_SOCKET` (the live sd_notify
wire), modeling `build_runtime`'s exact `on_online` wiring (where `scheduler.start()` is the
FIRST step of the hook, so the gate's post-hook `notifier.ready()` is strictly after start).
Two scenarios: (A) probe fails once then passes; (B) `stop` set mid-probe.

**Exact command:**
```bash
uv run python /tmp/wb_uat/ready_capture.py
```
(The driver binds a datagram socket, exports it as `$NOTIFY_SOCKET`, constructs
`SystemdNotifier()` AFTER the env is set — exactly as `build_runtime` does — drives
`ReadyGate.run(stop)`, then `sock.recv()`s the captured datagram bytes.)

**Evidence (byte-level + ordering):**

Scenario A (fail-then-pass) — captured step order:
```
[0] probe#1=FAIL
[1] on_fail(stamp_health)
[2] probe#2=PASS
[3] on_online:scheduler.start()
[4] on_online:stamp_health(online)+stamp_tick+log+ping
[5] gate.run -> True
[6] DATAGRAM RECEIVED: b'READY=1'
  received datagrams: [b'READY=1']
```
- Exactly ONE datagram, byte-identical `b'READY=1'`.
- Ordering proven: probe-pass (idx 2) **<** `scheduler.start()` (idx 3) **<** `READY=1`
  datagram (idx 6). READY never reaches systemd before the scheduler is up.

Scenario B (stop-preempt mid-probe) — captured:
```
[0] probe=FAIL
[1] on_fail
[2] gate.run -> False
  received datagrams: []
```
- ZERO datagrams sent on a clean stop; `on_online` never fired; gate returned `False`
  (→ `run_daemon` returns rc 0, the clean-shutdown path).

**Verdict:** **PASS.** READY=1 is byte-identical and strictly ordered after probe-pass +
`scheduler.start()`; a shutdown mid-probe emits no READY and exits cleanly. The only physical
step not exercised here is an actual systemd-supervised host reboot — recorded as deferred
Gate-2 (see below); the *mechanism* (real datagram on a real socket) and the *result*
(byte-level READY ordering) are PASS.

---

## Criterion 2 — Single composition root, zero duplicated module mechanism

**What tested:** That `build_runtime` is the ONE greppable wiring site (APP-01) and the full
suite is green driving it.

**Exact commands + evidence:**
```bash
$ grep -rn "def build_runtime" weatherbot/
weatherbot/scheduler/wiring.py:107:def build_runtime(

$ grep -rn "build_runtime(" weatherbot/ | grep -v "def build_runtime"
weatherbot/scheduler/daemon.py:1389:    parts = build_runtime(      # the single call site (run_daemon)

$ uv run pytest -q
777 passed, 1 warning in 40.97s
```
- `build_runtime` defined once, called from exactly one site (`run_daemon`).
- Full suite: **777 passed**, zero test failures/errors.

**Verdict:** **PASS.**

---

## Criterion 3 — The four leak points injected, not baked (litmus clean)

**What tested:** Both halves of APP-02 — the negative litmus (no weather noun in the module
surface, D-13 term set unchanged) over the grown lifecycle module, AND the new POSITIVE
injection-registry proof (each leak point injected-at-root with no module-side baked default).

**Exact command + evidence:**
```bash
$ uv run pytest -q tests/test_import_hygiene.py tests/test_injection_registry.py
17 passed in 0.29s
```
- Gate 1 (grimp import-graph), Gate 2 (isolated-import smoke), Gate 3 (AST signature litmus)
  all green over the new `yahir_reusable_bot/lifecycle/` edges — auto-scaled, no per-module
  edit; `_LITMUS` term set at L61 UNCHANGED.
- The four positive assertions each PASS with a paired self-proof that a baked default trips:
  - **health-check (leak 3):** `ReadyGate` REQUIRES `health_check` (no default → constructing
    without it is a `TypeError`; there is no module-side weather probe). Wired at `build_runtime`.
  - **config id-deriver / exactly-once key (leak 2):** `ReloadEngine` REQUIRES `desired_jobs`;
    `build_runtime` injects `desired_jobs=` + `excluded_ids=`; the module names no job id.
  - **selected-location context (leak 1):** `_selected_location` lives app-side in `panel.py`;
    no module symbol carries a `location` name.
  - **render_embed (leak 4):** `render_embed` defined app-side in `bot.py`, consumed by
    `panel.py`; the module owns zero `render` symbol.

Manual litmus grep over the lifecycle tree returns only PROSE hits (docstrings/comments),
which the AST signature-only litmus correctly ignores:
```bash
$ grep -rIcE 'weather|forecast|location|openweather|\buv\b|briefing' yahir_reusable_bot/lifecycle/*.py
identity.py:0  health.py:4  __init__.py:1  sdnotify.py:0  ready_gate.py:1   # all PROSE
```

**Verdict:** **PASS** (both halves — negative litmus clean + positive injection registry green).

---

## Criterion 4 — Byte-identical oracle (Phase-21 goldens, zero non-empty snapshot diff)

**What tested:** The full Phase-21 golden suite (embeds, CLI, schedule plan, DB rows,
custom_ids, harness) re-run, asserting zero non-empty snapshot diff against the committed
baseline, with NO golden file edited (mirrors 24-03's diff-against-baseline method).

**Exact command + evidence:**
```bash
$ uv run pytest -q tests/test_golden_embeds.py tests/test_golden_cli.py \
      tests/test_golden_schedule.py tests/test_golden_db.py \
      tests/test_golden_custom_ids.py tests/test_golden_harness.py
25 snapshots passed.
29 passed, 1 warning in 1.41s

$ git status --short tests/__snapshots__/ tests/test_golden_*.py | grep -v '^?? '
  (clean — no golden file modified)
```
- All Phase-21 goldens pass: 29 tests / 25 snapshots, zero diff.
- No `--snapshot-update` run; no golden snapshot file modified in the working tree.

**Verdict:** **PASS** (BHV-02 — byte-identical oracle intact, no golden rubber-stamped).

---

## Deferred Gate-2 obligation (PARTIAL — physical step only)

**Item:** Live `yahir-mint` host restart UAT — after deploy, `sudo systemctl restart weatherbot`
and confirm the bot reaches systemd `active` (READY=1 received by systemd over the real unit
socket) only after the startup self-check passes, against the live editable install.

**Status:** **PARTIAL — deferred to Gate-2 (milestone-close, Phase 28 / PKG-02).** The
*mechanism* (READY=1 over a real `AF_UNIX`/`SOCK_DGRAM` socket, correct ordering) and the
*result* (byte-level datagram capture) are PASS via Criterion 1's driven socket. The only
unexercised step is the physical systemd-supervised reboot on the production host — a true
device/host action, recorded as a deferred milestone obligation per the Two-Gate UAT policy,
NOT a per-phase blocker.

---

## Summary

| # | Criterion | Verdict | Key evidence |
|---|-----------|---------|--------------|
| 1 | READY=1 only after probe-pass + `scheduler.start()` | **PASS** | `b'READY=1'` captured on a real socket; order pass<start<ready; zero READY on stop-preempt |
| 2 | Single composition root, zero duplicated mechanism | **PASS** | `build_runtime` defined once / called once; 777 passed |
| 3 | Four leak points injected, not baked (litmus clean) | **PASS** | 17 passed (3 negative gates + positive injection registry); `_LITMUS` unchanged |
| 4 | Byte-identical oracle (Phase-21 goldens) | **PASS** | 29 golden tests / 25 snapshots, zero diff, no golden edited |
| — | Live host reboot (physical) | **PARTIAL (deferred Gate-2)** | mechanism+result PASS via driven socket; physical reboot → Phase 28 |

**Overall Gate-1: PASS.** Phase 25 completion is discharged on the autonomous self-UAT;
the live host reboot is the single deferred Gate-2 milestone obligation.
