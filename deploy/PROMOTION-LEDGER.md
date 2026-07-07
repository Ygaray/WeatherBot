# Promotion Ledger — `yahir-reusable-bot` sha promotions (D-06)

Append-only record of which `yahir-reusable-bot` module sha is **promoted to the WeatherBot
deploy**. One row per promotion. The resolved sha is what `uv.lock` freezes for the tag and
what the live host's `module provenance` startup-version-log line announces on boot.

> **How to read the deployed sha off the host:** `journalctl -u weatherbot -n 30 --no-pager`
> and find the once-per-boot **`module provenance`** structlog line (event key
> `"module provenance"`, emitted from `weatherbot/cli.py` in the `run` path). Its
> `module_sha` is the live deployed sha and **must equal the latest ledger row's Resolved
> SHA**; `editable` must be `False`. See `deploy/REPIN-RITUAL.md` for the full ritual.

| Date | Tag | Resolved SHA | Note |
|------|-----|--------------|------|
| 2026-06-29 | v0.1.0 | `138a907d57ac1d1d8499399b019f1509e43d02f1` | initial split — physical repo extraction (Phase 28). Resolved from `[tool.uv.sources]` `tag = "v0.1.0"`, frozen in `uv.lock`. NOT YET deployed to the live host — pending a fetchable `YahirReusableBot` remote (currently `file://` fallback); this row records the **promoted** sha, with the live `yahir-mint` restart deferred to Gate-2. |
| 2026-07-07 | v0.1.1 | `7f3cc001f814f6a7d37b5f18f254c8baaa7c1546` | Gate-2 hotfix: `on_message` infinite-recursion fix (live `!panel`/text-command RecursionError) + startup persistent-view custom_id diagnostic. Repinned via GitHub tag; `uv sync --frozen`. Pending live `yahir-mint` restart to confirm. |

---

## Conventions

- **Append-only** — never edit or delete a prior row. Each promotion is a permanent record.
- **Tag = promotion unit** — one row per `vX.Y.Z` tag promoted to deploy. Tags are immutable
  (see `deploy/REPIN-RITUAL.md`, Pitfall 2); a re-cut tag means a re-cut version number.
- **Resolved SHA = the auditable anchor** — the exact commit `uv.lock` froze for that tag.
  Cross-check it against the host's `module provenance` line after every restart.
- **Note** — what changed + deploy status (promoted vs live). Record when a promotion
  actually reaches the host vs. when it is merely pinned in the lock.

---

*Phase 28 (v2.0 Bot Module Extraction) — D-06 process artifact. The final step of the repin
ritual (`deploy/REPIN-RITUAL.md`) appends a row here.*
