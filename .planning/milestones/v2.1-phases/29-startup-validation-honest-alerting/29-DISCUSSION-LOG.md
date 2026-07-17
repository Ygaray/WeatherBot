# Phase 29: Startup Validation & Honest Alerting - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-08
**Phase:** 29-startup-validation-honest-alerting
**Areas discussed:** Fatal-error behavior, Alert-spam / restart loop, Boot validation placement, STARTUP-03 scope, Probe-time fatal (cross-repo)

---

## Fatal-error behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Alert + exit (rec) | New CONFIG_INVALID reason; stamp health row fatal, best-effort Discord alert, then exit non-zero. Keep AUTH_FAILED re-probing. | ✓ |
| Exit only | Exit non-zero, no Discord alert — rely on systemd/journal on the host. | |
| Alert + stay alive fatal | Alert once, then stay up in a terminal fatal state that answers !status but never sends. | |

**User's choice:** Alert + exit (rec)
**Notes:** Health row stamped before exit keeps `!status` answerable across restarts without an inert process. AUTH_FAILED stays re-probing (key may be propagating, ~2h).

---

## Alert-spam / restart loop

| Option | Description | Selected |
|--------|-------------|----------|
| Once/boot + start-limit (rec) | Best-effort one ping per boot; bound restarts via systemd Restart=on-failure + StartLimitBurst on yahir-mint. | ✓ |
| DB-backed cooldown | Reuse alert-dedup spine so the same fatal config error only pings once per N hours across restarts. | |
| No Discord alert | Systemd/journal only. | |

**User's choice:** Once/boot + start-limit (rec)
**Notes:** Discovered `deploy/weatherbot.service` is `Restart=always` + `RestartSec=5` + `TimeoutStartSec=infinity`. The infinity timeout is deliberate (transient slow-key re-probe stays alive). The unit change (→ `Restart=on-failure` + start-limit) is therefore REQUIRED for bounded alerts, and is a deferred Gate-2 host redeploy.

---

## Boot validation placement

| Option | Description | Selected |
|--------|-------------|----------|
| Boot gate + backstop (rec) | Full offline validate_config_and_templates in run() before run_daemon; also fix selfcheck classification as defense-in-depth. | ✓ |
| Selfcheck-only | No boot gate; just fix selfcheck to classify config errors fatal. | |

**User's choice:** Boot gate + backstop (rec)
**Notes:** Boot gate runs before the hub ReadyGate, which is what keeps the fatal-exit fully app-side (no hub change) — this turned out to be the key to the cross-repo question below.

---

## STARTUP-03 scope

| Option | Description | Selected |
|--------|-------------|----------|
| Both, F89 to P35 (rec) | Fix F90 + F07; leave F89 streak-dict leak to Phase 35. | |
| Both + fold F89 | Also fix F89 reload leak now, since the file is already open. | ✓ |
| F90 only | Announce forecast slots; skip F07. | |

**User's choice:** Both + fold F89
**Notes:** File already open; folding the leak fix in is cheaper than a separate Phase 35 touch.

---

## Probe-time fatal (cross-repo jurisdiction)

| Option | Description | Selected |
|--------|-------------|----------|
| A — App-side stop hook (rec) | Fix classification AND make injected on_fail hook set stop + fatal marker + alert, so a probe-time config-fatal exits non-zero. No hub change. | ✓ |
| B — Classify only, defer stop | Fix reason/severity now; capture a ReadyGate fatal-outcome hub enhancement as HUB-HANDOFF. | |
| Let research decide | Capture both; researcher recommends. | |

**User's choice:** A — plus fix the hub itself (user: "we can run A and also fix it on the hub itself no?")
**Notes:** Correct — A and the hub fix are complementary. Ship A app-side in Phase 29 (uses the hub's existing on_fail hook + stop Event, zero hub change). The hub `ReadyGate` first-class fatal-outcome is the cleaner long-term design but is a human-gated tag cut → logged as a HUB-FINDINGS-HANDOFF item for the next YahirReusableBot tag; WeatherBot repins after and can de-hack A.

## Claude's Discretion

- Fatal reason constant name, concrete StartLimitIntervalSec/StartLimitBurst values, fatal-marker plumbing shape.
- Whether `wait_ready_gate`/`gate_until_healthy` (daemon.py:1108-1156) is dead code superseded by `ready_gate.run()` — confirm at planning; remove if dead (in-scope, same file).

## Deferred Ideas

- Hub `ReadyGate` first-class fatal outcome → `.planning/HUB-FINDINGS-HANDOFF.md` (human-gated hub tag).
- Gate-2: `deploy/weatherbot.service` restart-policy change effective only after redeploy + `systemctl daemon-reload` on host `yahir-mint`.
