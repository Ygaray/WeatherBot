# Phase 9: Reload Engine & Explicit Trigger - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 9-Reload Engine & Explicit Trigger
**Areas discussed:** Exactly-once policy (Pitfall #8), Reload trigger plumbing, check-config shape, Reload outcome reporting & scope

---

## Exactly-once policy (Pitfall #8) — location identity

| Option | Description | Selected |
|--------|-------------|----------|
| Add stable `id`/slug to config | Immutable `id` separate from display `name`; sent-log keys on `id` so renames don't reset sent-state. Config schema change + migration story. | ✓ |
| Keep keying on name + guard | No schema change; heuristic rename-detection / already-sent-today guard. Fragile — the exact Pitfall #8 failure. | |
| You decide (research-backed) | Leave identity mechanism to plan-phase research; lock only the behavioral guarantee. | |

**User's choice:** Add stable `id`/slug to config (D-01).
**Notes:** Followed up on migration — chose `id` **optional, defaults to name** (casefolded slug) so existing config.toml works with zero migration and the key is byte-identical for un-`id`'d configs. (Rejected: `id` required = breaking change.)

## Exactly-once policy (Pitfall #8) — re-fire rule for changed already-sent slots

| Option | Description | Selected |
|--------|-------------|----------|
| Never re-fire if sent today (by id) | A reload changing tz/send_time/name of an already-delivered slot does NOT re-fire that morning; new schedule applies next day. Safest; matches "no duplicate, no skip". | ✓ |
| Apply new schedule immediately | Honor new tz/send_time same day even for already-sent slots — risks a second briefing the morning of an edit. | |
| You decide | Leave the cross-midnight/tz-shift edge to research. | |

**User's choice:** Never re-fire if sent today, by id (D-02).
**Notes:** Mandatory explicit test (SC#4): tz/name change on an already-sent slot → no re-send, no skip.

---

## Reload trigger plumbing — how `weatherbot reload` reaches the daemon

| Option | Description | Selected |
|--------|-------------|----------|
| PID file + SIGHUP | Daemon writes PID on startup; `weatherbot reload` reads it and sends SIGHUP. Self-contained, works on/off systemd. | ✓ |
| systemd only (systemctl reload) | Rely on `systemctl reload` → ExecReload=kill -HUP $MAINPID. No PID-file management, but systemd-only. | |
| You decide | Leave discovery mechanism to research. | |

**User's choice:** PID file + SIGHUP (D-03).
**Notes:** User asked for the cons of the PID-file approach before deciding. Discussed: stale-PID files after hard kills (mitigated by `/proc/<pid>/cmdline` verification), file location/perms, accidental double-start; ~30 lines of management hooking the existing clean-shutdown teardown. Key point surfaced: choosing "no ExecReload" (next question) means `weatherbot reload` must discover the PID itself, so a PID file is the natural fit and also the only option that works off-systemd (dev box, bare Pi, container). User: "lock that in."

## Reload trigger plumbing — systemd integration depth

| Option | Description | Selected |
|--------|-------------|----------|
| Stay-ready, no ExecReload (Pitfall #13) | Reload never touches systemd ready/health state (always old-good or new-good); no ExecReload, no RELOADING=1→READY=1. Only restart re-runs the health gate. | ✓ |
| Full sd_notify handshake + ExecReload | Wire ExecReload + emit RELOADING=1→READY=1 so `systemctl reload` reflects true state. More moving parts. | |
| You decide | Leave systemd-integration depth to research. | |

**User's choice:** Stay-ready, no ExecReload (D-04).

---

## check-config shape — relationship to existing `check`

| Option | Description | Selected |
|--------|-------------|----------|
| New offline-only validation, no network | Pure parse + pydantic + unique id/name + template-token check; zero network. Distinct from `check` (which probes). Shares ONE validation function with reload-validate. | ✓ |
| Reuse `check`, just skip sending | Extend existing `check` but keep the network probe. Not a pure offline check; wouldn't share reload's offline path. | |
| You decide | Leave to research. | |

**User's choice:** New offline-only validation, no network (D-05).

## check-config shape — command surface

| Option | Description | Selected |
|--------|-------------|----------|
| `weatherbot check-config` subcommand | New subparser alongside Phase 7 weather/check/run/send-now — consistent with add_subparsers grammar. | ✓ |
| `weatherbot --check-config` global flag | Matches roadmap literal wording; slightly inconsistent with the all-subcommand CLI. | |
| You decide | Leave naming to planning. | |

**User's choice:** `weatherbot check-config` subcommand (D-06).

---

## Reporting & scope — CFG-06 success log detail

| Option | Description | Selected |
|--------|-------------|----------|
| Job diff summary | Log added/removed/changed/unchanged slots (e.g. `+1 -0 ~2 =3`); rejection logs the reason. Pairs with the diff-reconcile already computed. | ✓ |
| Applied/rejected + reason only | Minimal 'config reloaded' / 'reload rejected: reason'. Operator can't see WHAT changed. | |
| You decide | Leave verbosity to planning. | |

**User's choice:** Job diff summary (D-07).

## Reporting & scope — template-file reload scope

| Option | Description | Selected |
|--------|-------------|----------|
| Reload re-reads templates too | Re-reads config.toml AND referenced template files, validating tokens before swap. A template-only edit is picked up on next trigger. Matches the phase goal. | ✓ |
| config.toml only | Template content changes need a restart. Contradicts the stated goal. | |
| You decide | Leave to planning. | |

**User's choice:** Reload re-reads templates too (D-08).

---

## Claude's Discretion

Deferred to research/planning (roadmap flags `--research-phase 9`):
- Two-phase build-then-commit apply + rollback-on-job-registration-failure mechanics (Pitfall #6).
- Job diff/reconcile mechanics (`replace_existing=True`, the add/update/remove delta, "changed" definition) (Pitfall #7).
- PID file location/path and atomic write mechanics.
- SIGHUP handoff: handler sets a flag/Event rather than doing reload work re-entrantly (mirror the SIGTERM pattern).
- Units-change handling within the swap.

## Deferred Ideas

- File-watch auto-reload + debounce — Phase 10 (CFG-03).
- Discord posting of reload outcome — Phase 11 (CFG-07).
- `.env`/secrets hot-reload — permanently out of scope; restart boundary (Pitfall #12).
- systemd ExecReload / sd_notify handshake — considered and declined (D-04); revisit only if a future requirement needs `systemctl reload`.
