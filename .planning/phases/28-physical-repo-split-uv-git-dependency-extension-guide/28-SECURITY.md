---
phase: 28
slug: physical-repo-split-uv-git-dependency-extension-guide
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-07
---

# Phase 28 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Milestone v2.0 "The Great Decoupling", FINAL phase — physical repo split of the reusable
> bot core into the sibling hub `YahirReusableBot`, repin via a uv git dependency, and the
> extension/deploy guides. Threats are supply-chain / deploy-integrity controls (T-28-*),
> not app-logic controls. Mitigations legitimately live in config, lockfiles, and deploy
> docs — verified present in the named artifact, not accepted on intent.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| WeatherBot repo → hub module repo | the `yahir_reusable_bot/` tree crosses into a standalone public repo | source code (must be secret-free) |
| build → installed wheel | hatchling `packages` config decides what code ships | packaged module tree |
| committed pyproject/lock → host deploy | a leaked dev path source would break the host install | dependency source + resolved sha |
| git tag → resolved sha | a mutable/re-pointed deploy tag could drift deployed code | `uv.lock` pinned sha |
| installed dist-info → startup log | provenance read crosses from PEP 610 `direct_url.json` to an audited log line | module version/sha/ref/editable (non-secret) |
| committed lock → host install | the promoted sha must equal what the host installs | promotion ledger row ↔ lock sha ↔ boot log sha |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-28-01 | Information Disclosure | secrets riding into the new module repo | high | mitigate | No `.env`/config/secret/key file tracked in hub; `grep` over `hub/yahir_reusable_bot/` finds only docstring prose ("never references the OpenWeather API key") + one "zero coupling to WeatherBot" statement — no secret values | closed |
| T-28-02 | Tampering | discord.py version drift breaks the live panel | high | mitigate | Hub `pyproject.toml:10` pins EXACT `discord.py==2.7.1` (not a range) | closed |
| T-28-03 | Tampering | hatchling silently drops a package on the wheel edit | medium | mitigate | Hub `pyproject.toml:23-24` `[tool.hatch.build.targets.wheel] packages = ["yahir_reusable_bot"]`; wheel-contents inspection executed in 28-01 SUMMARY | closed |
| T-28-SC | Tampering | discord.py / httpx / structlog / tenacity declarations | low | accept | Pre-existing production deps RELOCATED, not newly installed (28-RESEARCH Package Legitimacy Audit — SUS verdicts are PyPI-metadata-gap false positives). Logged in Accepted Risks | closed |
| T-28-04 | Tampering / DoS | dev path-source leaks into the committed deploy artifact | high | mitigate | Committed `pyproject.toml:32-36` `[tool.uv.sources]` is a git tag pin (public GitHub remote, tag `v0.1.1`), no path source; `uv build --no-sources` gate proven green (28-02 SUMMARY); no `path=`/`file://`/`editable=true` in any tracked toml/lock | closed |
| T-28-05 | Tampering | mutable git tag re-pointed to a different sha | high | mitigate | `uv.lock:1324` freezes resolved sha `7f3cc001…` in the source URL; `uv sync --frozen` reinstalls byte-identically with no re-resolve regardless of tag movement | closed |
| T-28-06 | Tampering | discord.py version drift breaking the live panel | high | mitigate | Hub EXACT `==2.7.1` flows transitively → `uv.lock:400-402` shows `discord-py 2.7.1` from PyPI registry | closed |
| T-28-07 | Spoofing | dependency confusion (slopsquat of `yahir-reusable-bot`) | medium | accept | Dep is a git URL pin, not a registry name — no PyPI package to confuse with; `--no-sources` would fail (no published metadata), which is expected and not a deploy path (28-RESEARCH Security Domain). Logged in Accepted Risks | closed |
| T-28-08 | Information Disclosure | startup-version-log line leaking a secret | high | mitigate | `weatherbot/cli.py:108-114` returns ONLY version/sha/ref/editable; `cli.py:995` `_log.info("module provenance", **_module_provenance())` spreads only that dict — no webhook/appid/token | closed |
| T-28-09 | Repudiation | a deploy running an unaudited sha | medium | mitigate | `weatherbot/cli.py:995` announces `module_sha` (checkable vs. ledger); `cli.py:113` `editable` flag is the dev-tree-overlay tripwire | closed |
| T-28-10 | DoS | malformed/missing direct_url.json crashing startup | medium | mitigate | `weatherbot/cli.py:97-113` guards the read (`PackageNotFoundError`→`None`; `json.loads(raw) if raw else {}`; `.get(...)` defaults) — missing record yields empty sha, never raises | closed |
| T-28-11 | Tampering | deployed sha drifting from the promoted/tested sha | high | mitigate | `deploy/PROMOTION-LEDGER.md` latest row (2026-07-07, v0.1.1) Resolved SHA `7f3cc001…` == `uv.lock:1324` pin == hub `v0.1.1` tag sha; ledger documents `module_sha`==row-sha & `editable`==False cross-check; REPIN-RITUAL mandates `uv lock --upgrade-package` + commit lock before deploy | closed |
| T-28-12 | Tampering | a re-pointed mutable deploy tag | high | mitigate | `deploy/REPIN-RITUAL.md:27,33-36,131` documents immutable-tag discipline ("never `git tag -f` / force-push a deploy tag"); `uv.lock`+`--frozen` pin the sha regardless of tag movement | closed |
| T-28-13 | Tampering / DoS | a dev path-override shipping to the host | high | mitigate | `deploy/REPIN-RITUAL.md:92-122,139` mandates venv-only editable overlay for co-dev ("NEVER commit a path source" inviolable rule) + `uv build --no-sources` backstop tripwire + `editable:True` host tripwire; verified no path source in any committed toml/lock | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*
*Severity assigned by auditor at L1 (registers carry no Severity column): deploy-integrity / secret-disclosure / panel-wire-contract threats = high; audit-trail and startup-robustness threats = medium; relocated-dep / no-registry-name threats = low.*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-28-01 | T-28-SC | `discord.py` / `httpx` / `structlog` / `tenacity` are pre-existing production deps being RELOCATED into the hub, not newly introduced. The 28-RESEARCH Package Legitimacy Audit "SUS" verdicts are PyPI-metadata-gap false positives. No new install checkpoint warranted. | Phase-28 plan (28-01) | 2026-06-29 |
| AR-28-02 | T-28-07 | The reusable-bot dependency is a git URL pin (`github.com/Ygaray/YahirReusableBot`), not a PyPI registry name — there is no published package a slopsquat could impersonate. `uv build --no-sources` failing on it is expected and is not a deploy path. | Phase-28 plan (28-02) | 2026-06-29 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-07 | 13 | 13 | 0 | gsd-security-auditor (ASVS L1) |

Notes:
- Cross-repo sha chain verified byte-identical across three independent artifacts: hub git tag
  `v0.1.1` = `7f3cc001f814f6a7d37b5f18f254c8baaa7c1546`, WeatherBot `uv.lock:1324` source pin, and
  the PROMOTION-LEDGER latest row. The v0.1.0 (`138a907d…`) → v0.1.1 (`7f3cc001…`) repin (the live
  `on_message` recursion hotfix) is reflected consistently in the lock and the append-only ledger.
- The 28-01 `file://` local-only fallback flagged as a Gate-2 blocker in the SUMMARYs has since been
  repointed (comment: 2026-07-02) to the fetchable public GitHub remote in the committed
  `pyproject.toml` — so the T-28-04/T-28-13 "no dev path in committed artifact" control is
  satisfied by the CURRENT committed state, not merely planned.
- Unregistered flags: NONE. All three SUMMARYs with a `## Threat Flags` section (28-02/03/04)
  declare "None — no new security surface"; 28-01 has no Threat Flags section and introduced no
  new surface. No `unregistered_flag` logged.
- Deferred (Gate-2, non-security-blocking): the live `yahir-mint` `systemctl restart` +
  journal cross-check of the `module provenance` line's `module_sha` against the ledger row is a
  deferred milestone-close UAT obligation (28-SELF-UAT verdict PARTIAL). The provenance MECHANISM
  is verified in source + unit-tested; only the physical live-host observation is deferred. This
  does not open any threat (all mechanisms are present and committed).

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-07
