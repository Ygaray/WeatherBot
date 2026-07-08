---
phase: 25
slug: lifecycle-ready-gate-composition-root
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-07
---

# Phase 25 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Verified retroactively by gsd-security-auditor. Config: `asvs_level: 1`, `block_on: high`.
> Register authored at plan time across the three plans (25-01, 25-02, 25-03) — every declared
> mitigation was verified PRESENT in implemented code, not accepted from documentation or intent.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| systemd ↔ daemon | READY=1 datagram over `$NOTIFY_SOCKET`; readiness must not be load-bearing for liveness | `b"READY=1"` control datagram (non-secret) |
| app ↔ module wiring | `build_runtime` injects app closures (health_check / on_fail / on_online / identity) into the module engines; the module invokes them opaquely | injected callables + a neutral `HealthResult` DTO |
| client → daemon control | `weatherbot reload` sender signals the daemon PID; `/proc` guard defends against PID recycling | SIGHUP to a PID gated by an argv-marker match |
| install-time substitution | sed placeholders (`<NAME>`/`<RUNTIME_DIR>`/`<REPO>`/`<USER>`) in the `.service` template are operator-supplied at install | systemd unit identity/least-privilege fields |
| test harness ↔ NOTIFY_SOCKET | the Gate-1 self-UAT binds a captured `AF_UNIX`/`SOCK_DGRAM` socket to observe READY=1 ordering | captured datagram bytes |
| module surface ↔ litmus gate | the standing negative litmus + the new positive injection-registry proof guard the module boundary | AST/signature introspection only |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-25-01 | Tampering | injected hooks (on_online/on_fail) | medium | mitigate | `ReadyGate._best_effort_hook` swallows + logs a raising hook, never masks the gate result; both `on_online` and `on_fail` route through it | closed |
| T-25-02 | Denial of Service | re-probe loop | high | mitigate | interruptible `stop.wait(interval)` in the `while not stop.is_set()` loop — no `time.sleep`; a `systemctl stop` mid-probe breaks promptly (Pitfall 2) | closed |
| T-25-03 | Information disclosure | `HealthResult.detail` logging | low | accept | `detail` is outcome-only (status code / exception class name), never a secret — contract preserved verbatim from `CheckResult` (T-04-01) | closed |
| T-25-04 | Spoofing | reload sender PID guard | high | mitigate | generalized `is_running_process` keeps the argv0-basename + `-m` module match (byte-identical); SIGHUP never reaches a recycled/unrelated PID | closed |
| T-25-05 | Elevation of privilege | `.service` template | high | mitigate | template keeps `User=<USER>` (non-root, "never run the daemon as root") + `RuntimeDirectory=<RUNTIME_DIR>` ownership rationale; least-privilege preserved | closed |
| T-25-06 | Tampering | online ping string | low | accept | fixed literal, no user/template interpolation, no `@everyone`/`@here` (markdown-injection-safe, T-05-T) — preserved verbatim in the `on_online` hook | closed |
| T-25-07 | Repudiation | self-UAT evidence | low | mitigate | persistent auditable log (`25-SELF-UAT.md`) records exact commands + byte-level output per criterion (mirrors 24-03) | closed |
| T-25-08 | Tampering | golden snapshots | medium | mitigate | diff-against-baseline only; no golden file edited (`git status` clean, no `--snapshot-update`); any non-empty diff investigated, never rubber-stamped | closed |
| T-25-SC | Tampering | dependency installs (pip/uv) | high | mitigate | NO new dependencies — pure move/re-point within existing stdlib + module surface; verified no phase-25 commit touched `pyproject.toml`/`uv.lock` | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `high` count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

### Evidence detail (verified present in code — L1 grep-level)

| Threat ID | Evidence location |
|-----------|-------------------|
| T-25-01 | `../Reusable/YahirReusableBot/yahir_reusable_bot/lifecycle/ready_gate.py` — `_best_effort_hook` L125-139 (None=no-op, raise caught L138 + logged L139); routed at L96 (`on_online`) and L101 (`on_fail`) |
| T-25-02 | `.../lifecycle/ready_gate.py` L90 (`while not stop.is_set()`), L117 (`stop.wait(self._re_probe_interval)`); `grep time.sleep` returns only docstring/comment prose (L12/L80/L116), no code call |
| T-25-03 | `.../lifecycle/health.py` L19-21 + L52-57 — `detail` documented outcome-only, opaque passthrough the gate logs but never inspects (accept rationale corroborated; logged in Accepted Risks below) |
| T-25-04 | `.../lifecycle/identity.py` `is_running_process` L102-127 + `_argv_matches_marker` L130-149 (argv0-basename L146 + `-m` form L149); app wrapper `weatherbot/ops/pidfile.py:is_weatherbot_pid` L90-121 delegates with `proc_marker=b"weatherbot"` (byte-identical) |
| T-25-05 | `weatherbot/deploy/bot.service.template` L36 (`User=<USER>` — "Least privilege: never run the daemon as root"), L44 (`RuntimeDirectory=<RUNTIME_DIR>`) + ownership rationale L37-43 |
| T-25-06 | `weatherbot/scheduler/wiring.py` L306-307 — fixed literal `"WeatherBot online — startup self-check passed."`, no interpolation, no `@everyone` (accept rationale corroborated; logged in Accepted Risks below) |
| T-25-07 | `.planning/phases/25-lifecycle-ready-gate-composition-root/25-SELF-UAT.md` — per-criterion log with exact commands + byte-level datagram capture (C1 L38-64) |
| T-25-08 | `25-SELF-UAT.md` C4 L137-151 — diff-against-baseline, `git status --short` clean, no `--snapshot-update`; pre-existing syrupy artifact explicitly disambiguated L13-18 |
| T-25-SC | `git show --stat` over all 8 phase-25 commits (`5ff73e3`/`3592666`/`4873c14`/`ef004ef`/`2bfb6ae`/`2d77154`/`cc9cdea`/`2db533e`) — zero `pyproject.toml`/`uv.lock` changes; all three SUMMARY `tech-stack.added: []` |

*Note on file paths: Phase 25 predates the v2.0 physical repo split (Phase 28). The lifecycle module,
cited in the plans under `yahir_reusable_bot/lifecycle/`, now physically resides in the sibling hub
repo `../Reusable/YahirReusableBot/yahir_reusable_bot/lifecycle/` (consumed via a git-pinned uv
dependency). All module-side mitigations were verified there; app-side wiring/guard/template
mitigations were verified in this repo under `weatherbot/`.*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-25-01 | T-25-03 | `HealthResult.detail` is outcome-only (an HTTP status code or exception class name), never a secret or credential. The contract is preserved verbatim from the app-side `CheckResult` (originally accepted as T-04-01). The gate logs `reason`/`detail` as opaque passthrough and never emits request bodies, keys, or webhook URLs. Personal single-user bot; startup-failure logs are read only by the operator on the host. Risk tolerated. | gsd-security-auditor (retroactive, L1) | 2026-07-07 |
| AR-25-02 | T-25-06 | The online ping is a fixed string literal (`weatherbot/scheduler/wiring.py:306`) with zero user/config/template interpolation and no `@everyone`/`@here` mention, so it is markdown/mention-injection-safe by construction. Preserved verbatim in the `on_online` hook (originally accepted as T-05-T). Risk tolerated. | gsd-security-auditor (retroactive, L1) | 2026-07-07 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-07 | 9 | 9 | 0 | gsd-security-auditor (Opus 4.8) |

*Unregistered flags: none. All three plan SUMMARYs report `## Threat Flags: None` (25-01 has no new attack surface; 25-02 and 25-03 explicitly "None"). No new network endpoint, auth path, file-access pattern, schema change, or dependency was introduced — pure move/re-point + additive tests.*

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-07
