# Phase 7: CLI `weather [location]` One-Shot - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 7-CLI `weather [location]` One-Shot
**Areas discussed:** CLI surface & invocation, Errors & exit codes, Transient fetch retry, Output cleanliness

---

## CLI surface & invocation

### Dispatch structure

| Option | Description | Selected |
|--------|-------------|----------|
| Additive verb dispatch | If first arg is `weather`, route to new handler; existing flag parser untouched. Lowest risk. | |
| Full argparse subparsers | Restructure main() into proper subparsers; migrate flags into subcommands. | ✓ |

### Console entry point

| Option | Description | Selected |
|--------|-------------|----------|
| Add console script | `[project.scripts] weatherbot = "weatherbot.cli:main"` so `weatherbot weather home` works verbatim. | ✓ |
| Keep `python -m weatherbot` | No console script; invoke as `python -m weatherbot weather home`. | |

### Back-compat for existing v1.0 flags

| Option | Description | Selected |
|--------|-------------|----------|
| Keep flags as aliases | Add subparsers but keep --run/--check/--send-now/--geocode working; zero host change. | |
| Clean break + update deploy | Migrate fully to subcommands, DROP old flags, update systemd unit + deploy/README. | ✓ |
| Subcommands + aliases, deprecate later | No regression now, clear path to clean CLI later. | |

**User's choice:** Full argparse subparsers + console script + clean break (drop old flags, update deploy artifacts).
**Notes:** Operator accepted the larger blast radius. Deployed host `yahir-mint` (ExecStart `/usr/bin/uv run weatherbot --run`, `deploy/weatherbot.service:29`) must be redeployed (daemon-reload + restart) — flagged as ops/UAT item. Adding the console script also fixes the existing `uv run weatherbot` template line, which currently relies on a non-existent entry point.

---

## Errors & exit codes

### Exit-code scheme

| Option | Description | Selected |
|--------|-------------|----------|
| Flat exit 1 on any error | 0 ok / 1 any failure. Matches existing convention. | |
| Distinct codes per failure | 0 ok / 1 unknown location / 2 config error / 3 fetch-API error. | ✓ |

### Output streams & error text

| Option | Description | Selected |
|--------|-------------|----------|
| Briefing→stdout, errors→stderr | Pipeable stdout; reuse UnknownLocationError's existing message. | ✓ |
| Let me refine the error text | Tweak unknown-location wording / add a hint. | |

**User's choice:** Distinct exit codes (0/1/2/3); briefing→stdout, errors→stderr; reuse existing UnknownLocationError message.
**Notes:** Flagged to planner that argparse exits 2 on usage errors, overlapping "config invalid = 2" — acceptable or renumber deliberately.

---

## Transient fetch retry

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse run_send_now's short retry | Short bounded retry (~3x, transient-only via is_transient, never 401/403). | ✓ |
| Fail-fast, single attempt | One attempt; on failure stderr + exit 3; user re-runs. | |

**User's choice:** Reuse run_send_now's short retry policy.
**Notes:** Read-only → no DeliveryResult arm; only `retry_if_exception(is_transient)` applies. Exhausted/permanent → stderr (outcome only) + exit 3.

---

## Output cleanliness

| Option | Description | Selected |
|--------|-------------|----------|
| Quiet by default + --verbose | `weather` raises log level to WARNING; -v/--verbose restores INFO. | ✓ |
| Leave logging as-is (INFO) | Keep basicConfig(INFO); stderr shows 'lookup complete' lines. | |

**User's choice:** Quiet by default + `--verbose`/`-v`.
**Notes:** Quieting scoped to the user-facing `weather` command; other subcommands keep INFO.

---

## Claude's Discretion

- Exact subcommand names where ambiguous (`send-now` vs `send`); `--config` global vs per-subcommand placement under subparsers.
- Where the `weather` handler lives; how `--verbose` is wired.
- Whether the CLI invokes `parse_weather_command` at all (argparse already supplies the positional) or it stays reserved for P11.
- Final exit-code numbering if the argparse-2 overlap is renumbered.

## Deferred Ideas

- Discord bot reply (CMD-02) + short-TTL cache (CMD-06) — Phase 11.
- `weatherbot reload` + `check-config` (CFG-02/08) — Phase 9 (extends this phase's subparser structure).
- Geocoded / arbitrary-city lookup (CMD-V2-02) — v2.
- Flag deprecation window (vs clean break) — not taken; noted for a future operator.
