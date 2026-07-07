---
phase: 27
slug: discord-adapter-panelkit-render-cycle-fix
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-07
---

# Phase 27 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Discord inbound-command surface (message_content intent, custom_id routing, persistent-view
> re-bind). The reusable adapter was relocated to the hub package
> `yahir_reusable_bot/discord/` (repo `../Reusable/YahirReusableBot`); mitigation-plan paths
> were authored pre-extraction, so each was verified against the post-extraction location.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Discord user/bot tap → `PanelKit.interaction_check` | Untrusted interaction author crosses the operator gate before any child callback runs | interaction author id, custom_id (untrusted) |
| Discord gateway callback → bot internals | A raising callback must not crash the gateway loop / scheduler thread | exception (contained) |
| Composition root → module adapter | App injects render/contributors/marker/operator_id; the module receives (never bakes) them | operator_id (int), marker, opaque callables |
| App contributor callbacks → `SelectedContext` | The selected-item state is set/read across the generic seam | selected item (str, non-secret) |
| Bot logs / user replies | Secrets (bot token, OpenWeather appid) must never cross into a log or reply | non-secret ids only (channel_id, user_id, custom_id) |
| uv/pip install surface | Dependency tree change | `discord.py==2.7.1` pin (no new install) |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-27-01 | Elevation of Privilege | `PanelKit.interaction_check` (operator gate) | high | mitigate | Operator gate present: `interaction.user.id != self._operator_id` → reject; identity-free ephemeral copy ("This panel is in use by someone else."), no interpolation of user/custom_id/command/operator; bot actor → reject with NO ephemeral (WR-03 asymmetry); reject log is the sole audit record. `operator_id` baked at construction. | closed |
| T-27-02 | Denial of Service | per-callback envelope + `View.on_error` + `BotThread._run` | high | mitigate | Non-propagating failure isolation present: `on_command` outer `try/except Exception` + `_safe_error_edit` (double-wrapped, never re-raises) + `View.on_error` backstop; `BotThread._run` catches `LoginFailure` and bare `Exception`, sets `_failed`, swallows — gateway thread + scheduler survive. | closed |
| T-27-03 | Information Disclosure | reject log + summon logs + embed copy | high | mitigate | Secret-free logging present: only non-secret ids reach logs (`user_id`, `custom_id`, `channel_id`); no `_log.*` call references token/appid/api_key; the bot token lives only in `BotThread._token` → `client.start(token)`, never threaded into `PanelKit`/views or logged. | closed |
| T-27-04 | Tampering | live panel `custom_id` routing | high | mitigate | `custom_id` byte strings frozen: `CmdButton` builds `f"{marker}cmd:{name}"` (marker injected), app `wb:loc:select`/`wb:fc:…` literals stay app-side; `test_golden_custom_ids.py` byte-golden passes zero-diff; `discord.py==2.7.1` pinned (relocated to hub `pyproject.toml` L10 per Phase-28 split), `uv.lock` resolves 2.7.1. | closed |
| T-27-05 | Tampering | panel ownership (`is_owned_panel`) | high | mitigate | Ownership test present (module `is_owned_panel`): requires BOTH bot-authored (`author.id == bot_user.id`) AND a child `custom_id.startswith(marker)`; marker is the app-supplied unforgeable `wb:` marker; defensive `getattr` walk. A foreign message cannot be mistaken for the panel. | closed |
| T-27-06 | Tampering | injection at the composition root | high | mitigate | `render`/`contributors`/`marker` are required (no-default) `PanelKit.__init__` params (verified in signature) and are wired ONLY at the single composition root (`wiring.py::_build_panelkit`); `test_injection_registry::test_panel_cosmetics_and_render_and_marker_are_app_supplied` passes (positive injection assertion). | closed |
| T-27-07 | Information Disclosure | what the root threads into the module | high | mitigate | Only `operator_id` (int), the marker, `panel_channel_id` (non-secret id, app-side summon), and opaque callables cross into `PanelKit`/`summon_panel`; no token/appid appears in the `PanelKit(...)` construction. Token passed separately to `BotThread(token, client=...)`. | closed |
| T-27-08 | Tampering | 📍 suppression drift across the render cut | medium | mitigate | Per-tap 📍 suppression preserved: `_dispatch` sets `render_arg = selection.value if spec.takes_location else None`; `_render_bridge(reply, render_arg)` forwards it to the UNCHANGED `render_embed(reply, location=render_arg)`, so `if location is not None` fires identically; embed golden + `test_render_embed_indicator_suppressed_when_argless` green. | closed |
| T-27-09 | Tampering | a silently re-baselined golden | medium | mitigate | Golden oracle intact: `test_golden_custom_ids.py`/`test_golden_embeds.py` pass byte-identical (snapshot passed, zero `.ambr` re-baseline). Self-UAT records the zero-diff evidence; the snapshot-report quirk handled via exit-code + `.ambr` diff. | closed |
| T-27-10 | Tampering | a reintroduced cycle import escaping the gate | high | mitigate | Cycle edges dead: `panel.py → bot render_embed` forward edge gone, `bot.py → panel PanelView` deferred back-edge gone; `test_import_hygiene.py` no-deferred-import + grimp isolation gates pass; `weatherbot --help` exits 0 (no cycle). Module `discord/` has no `weatherbot.*` import edge. | closed |
| T-27-11 | Repudiation | unverified completion claim | low | mitigate | Gate-1 self-UAT log present (`27-SELF-UAT.md`) recording exact commands + evidence per criterion; live `yahir-mint` restart panel re-bind explicitly tracked as the single deferred Gate-2 (Phase-28) obligation. | closed |
| T-27-12 | Tampering | a silently re-baselined panel/custom_id golden during the harness rewire | medium | mitigate | Harness rewired onto module `PanelKit` with `_make_panel` return shape (`children[0]` == `wb:loc:select`) preserved; `test_panel.py` + `test_golden_custom_ids.py` + `test_oracle_selfproof.py` pass byte-identical, zero `.ambr` diff. | closed |
| T-27-13 | Denial of Service | the harness consumers failing at COLLECTION | medium | mitigate | `_make_panel` signature held unchanged; `test_golden_custom_ids.py` + `test_oracle_selfproof.py` (which import `_make_panel`/`_FakeHolder`/`_SpyCache`) collect and pass. | closed |
| T-27-SC | Tampering | uv/pip installs | low | mitigate | No new package installed across the phase; the only dependency change tightens an already-present, already-locked constraint (`discord.py` range → `==2.7.1`). RESEARCH Package Legitimacy Audit: discord.py OK (mature, github.com/Rapptz/discord.py). Declared `accept` in Plans 02/03/04 (no install in those plans); verified as `mitigate` (the pin is real and present). | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `high` count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|

No accepted risks. (Every threat resolved to a verified CLOSED mitigation.)

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-07 | 14 | 14 | 0 | gsd-security-auditor (Claude Opus 4.8) |

*14 = 13 distinct STRIDE threats (T-27-01..13) + the shared supply-chain threat T-27-SC (registered once, appears across Plans 01–04 with mixed mitigate/accept dispositions; verified present as a real pin → CLOSED).*

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log (none)
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-07
