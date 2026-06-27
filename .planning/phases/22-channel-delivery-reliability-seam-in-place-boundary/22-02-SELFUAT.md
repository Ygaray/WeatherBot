# 22-02 Self-UAT — Channel seam relocation (byte-identical oracle)

**Date:** 2026-06-27
**Plan:** 22-02 (Move text-only `Channel` + `DeliveryResult` into `yahir_reusable_bot.channels`)
**Policy:** Gate-1 agent self-UAT (autonomous; gates the phase/PR). Gate-2 host UAT deferred to milestone-close.

This is a BEHAVIOR-BYTE-IDENTICAL relocation: the oracle is the full 738-test suite
(732 Phase-21 baseline + 6 Wave-1 hygiene gates) plus the Phase-21 golden snapshots.
Acceptance = full suite green AND zero golden snapshot diff. `--snapshot-update` was
never run (Phase-21 D-04).

## Per-criterion evidence

| Criterion | What was checked | Exact command | Evidence | Verdict |
|-----------|------------------|---------------|----------|---------|
| **SEAM-01** — channel-agnostic `Channel` with zero weather coupling | Module `Channel` is abstract, `send`-only, no `send_briefing`, source has no `Forecast`/`weatherbot` token | `uv run python -c "from yahir_reusable_bot.channels import Channel; import inspect; assert not hasattr(Channel,'send_briefing'); assert inspect.isabstract(Channel); src=inspect.getsource(__import__('yahir_reusable_bot.channels.base',fromlist=['x'])); assert 'Forecast' not in src and 'weatherbot' not in src"` | `module Channel clean` | **PASS** |
| **PKG-01** — module imports zero app code | grimp import-graph gate reports zero `yahir_reusable_bot.channels.* -> weatherbot.*` edges; AST litmus reports zero weather noun in module surface | `uv run pytest tests/test_import_hygiene.py -q` | all import-hygiene gates green (within the 25-test focused run) | **PASS** |
| **BHV-01** — `weatherbot.channels` byte-identical for all importers | `from weatherbot.channels import Channel, DeliveryResult, DiscordWebhookChannel, build_channel` resolves; `isinstance(ch, Channel)`; exactly one module `Channel` underneath; `send_now` dispatch unchanged | `uv run pytest tests/test_channel.py tests/test_send_now.py -q` | 25 passed (combined with hygiene) | **PASS** |
| **BHV-02** — exactly ONE module `Channel`; app-side IS-A it | `issubclass(weatherbot.channels.Channel, yahir_reusable_bot.channels.Channel)` and `issubclass(DiscordWebhookChannel, yahir_reusable_bot.channels.Channel)`; app `Channel` carries `send_briefing`, module `Channel` does not; `base.py` has no embed reference | `uv run python -c "<invariants script>"` | `invariants OK` | **PASS** |
| **Oracle — full suite** | All 738 tests pass | `uv run pytest -q` | `738 passed, 1 warning in 38.46s` (exit 0) | **PASS** |
| **Oracle — zero golden diff** | No `tests/__snapshots__/` file changed or untracked | `git -c core.pager=cat status --porcelain tests/__snapshots__/` | empty output (`od -c` → `0000000`; `wc -l` → 0) | **PASS** |

### Note on the cosmetic "2 snapshots failed" line
`uv run pytest` prints `2 snapshots failed. 27 snapshots passed.` This is syrupy's
unused-snapshot accounting, NOT a test failure — the suite reports `738 passed`,
exits 0, and `git status --porcelain tests/__snapshots__/` is empty (no golden file
diff). Identical line is present on the 732/738 baseline (documented in 22-01-SUMMARY).
Not a regression; not a phase blocker.

## D-05 Phase-27 two-home hand-off (RECORDED)

The clean, text-only `Channel` ABC + `DeliveryResult` now live in
`yahir_reusable_bot.channels` (the reusable module). The concrete
`DiscordWebhookChannel` and its embed-building `send_briefing` override remain
**intentionally app-side** in `weatherbot/channels/discord.py`, and the app-side
`send_briefing` default lives in the `weatherbot/channels/base.py` shim.

**This two-home split is by design, not an incomplete extraction.** Phase 27 is the
named home for relocating the concrete Discord channel + embed. Until then:
- module surface = clean `Channel`/`DeliveryResult` (zero weather coupling, gate-enforced);
- app surface = briefing-capable `Channel` subclass + `DiscordWebhookChannel` + embed +
  `build_channel` factory.

The grimp/litmus/isolated-import gates stand guard so this split cannot silently drift
into a module → app leak.

## Deferred Gate-2 (milestone-close, not a phase blocker)
On host `yahir-mint`: `uv sync` → `systemctl restart weatherbot` → confirm the daemon
comes online and `from weatherbot.channels import build_channel` / `from
yahir_reusable_bot.channels import Channel` both resolve in the live process. The
channels move is byte-identical at the import level, so no behavioral change is
expected at runtime.

## Verdict: PASS (Gate-1 complete; safe to proceed autonomously)
