# Phase 9: Reload Engine & Explicit Trigger - Research

**Researched:** 2026-06-15
**Domain:** In-process config + template hot-reload on a long-running APScheduler 3.x daemon; exactly-once idempotency-key preservation across reload; SIGHUP/PID-file IPC; shared offline validation
**Confidence:** HIGH (all library/stdlib claims verified against the installed venv: APScheduler 3.11.2, pydantic 2.13.4, Python 3.12.3; all codebase claims verified by reading the actual files this phase touches)

## Summary

Phase 9 turns the Phase-8 `ConfigHolder.replace()` seam into a real reload engine. The
mechanical pieces are well-understood and the codebase is already shaped for them: the
holder is the swap point, jobs already read `holder.current()` per-fire (Pitfall #9 already
mitigated and verified in `08-SECURITY.md` T-08-08), and the stable job id `name|time|days`
already exists for diff-reconcile. The real work is (a) the **two-phase build-then-commit**
apply so a mid-reconcile failure leaves the OLD schedule fully intact, (b) the **exactly-once
key migration** to a stable `id` (Pitfall #8, HIGHEST RISK), (c) a **SIGHUP→main-loop handoff**
that does NOT do reload work re-entrantly in the handler, (d) a **PID-file + /proc cmdline
guard**, and (e) a **single shared offline-validation function** used by both `check-config`
and the reload engine.

**One assumption in the briefing is wrong and must be corrected:** this project does **NOT use
Jinja2**. There is no Jinja2 dependency installed (`import jinja2` → ModuleNotFoundError) and
none in `pyproject.toml`/`uv.lock`. Template rendering is a custom regex renderer in
`templates/renderer.py` (`render`, `load_template`, `validate_template`) with a fixed
`CANONICAL` allow-set of `{token}` placeholders. Template-token validation is therefore NOT a
Jinja2 `StrictUndefined`/`jinja2.meta` problem — it is a one-line call to the existing
`validate_template(load_template(config.template, templates_dir))`, which already does exactly
"detect unknown/typo'd placeholders with zero network and zero rendering." This dramatically
simplifies D-05/D-08 and removes a phantom dependency.

**Primary recommendation:** Build a single `validate_config_and_templates(path) -> Config`
function in `weatherbot/config/loader.py` (parse TOML → `Config.model_validate` → `assert_unique_names` extended to `id` → `validate_template` on each referenced template file), call it from BOTH `check-config` and the reload path; on the reload path follow it with a two-phase commit (build new job set off to the side → `holder.replace()` → diff-reconcile via `add_job(..., replace_existing=True)`/`remove_job`, snapshotting old jobs for rollback); move the sent-log key's first component from `location.name` to a new optional `Location.id` (defaulting to `casefold(name)` via a frozen-safe `model_validator(mode="after")`); and never re-fire a slot whose `id`-keyed row already exists for today.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Parse + validate new config/templates | Config layer (`config/loader.py`, `config/models.py`, `templates/renderer.py`) | — | Validation is pure, network-free, shared by `check-config` and reload — belongs with the loaders, not the scheduler |
| Atomic config swap | Config layer (`config/holder.py`) | — | The holder already owns the live reference; validate-before-swap hangs in front of `replace()` |
| Job diff/reconcile | Scheduler (`scheduler/daemon.py`) | — | Only the daemon owns the live `BackgroundScheduler` and its job set |
| Exactly-once key | Persistence (`weather/store.py`) + Scheduler (`fire_slot`/catchup callsites) | Config (the `id` field) | The key is computed at the daemon/catchup callsites and stored by the SQLite sent-log; the `id` it now uses originates in config |
| SIGHUP trigger → reload handoff | Scheduler/daemon lifecycle (`run_daemon`) | OS signal layer | Signal handlers run on the main thread; the daemon's main loop owns the safe handoff |
| `weatherbot reload` (sender side) | CLI (`cli.py`) | OS (`/proc`, `os.kill`) | A separate short-lived process that finds the PID and signals it |
| `check-config` subcommand | CLI (`cli.py`) | Config layer (shared validator) | A new offline subparser that calls the shared validator and reports pass/fail |

## Standard Stack

No new runtime dependencies. Everything Phase 9 needs is already in the pinned stack or the
Python 3.12 stdlib. (STATE.md confirms the only NEW v1.1 deps are `watchfiles` in Phase 10 and
`discord.py` in Phase 11 — NOT this phase.)

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| APScheduler | 3.11.2 (pinned `>=3.11.2,<4`) | Job add/remove/diff-reconcile on reload | Already the daemon's scheduler; `add_job(replace_existing=True)`, `get_jobs()`, `get_job()`, `remove_job()` are all present (verified) — this is the supported reconcile path, NOT `remove_all_jobs()`. [VERIFIED: installed venv 3.11.2] |
| pydantic | 2.13.4 (pinned `>=2.13.4`) | Add the optional `Location.id` with a name-derived default; full re-validation of the new config | Already the config validator; the frozen-model id-default pattern is verified working below. [VERIFIED: installed venv 2.13.4] |
| Python stdlib `signal` | 3.12.3 | SIGHUP handler install (mirrors the existing SIGTERM handler in `run_daemon`) | Stdlib; handlers always run on the main thread. [VERIFIED: Python 3.12.3] [CITED: docs.python.org/3/library/signal.html] |
| Python stdlib `threading` | 3.12.3 | `Event` for the SIGHUP→main-loop handoff (mirrors the existing `stop` Event) | Already the daemon's rendezvous primitive; safe to `.set()` from a signal handler. [VERIFIED] |
| Python stdlib `os` | 3.12.3 | `os.getpid`, `os.kill(pid, SIGHUP)`, atomic PID-file write (`os.replace`) | Stdlib; no PID-file library is warranted for a single-process personal daemon. [VERIFIED] |
| `templates/renderer.py` (in-repo) | — | `validate_template` / `load_template` for offline template-token validation | The project's OWN regex renderer — there is no Jinja2. `validate_template` already raises `ValueError` on any non-`CANONICAL` token with zero network/zero render. [VERIFIED: read templates/renderer.py] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tomllib` (stdlib) | 3.12.3 | Re-read `config.toml` on reload | Already used by `load_config`; raises `tomllib.TOMLDecodeError` on a half-written/bad TOML — the reload path must catch this and keep-old. [VERIFIED] |
| `structlog` | 26.x (pinned `>=26.1.0`) | The CFG-06 reload-outcome log line (`+a −r ~c =u` diff summary / rejection reason) | Already the daemon's logger; outcome-only, never secrets (T-04-01 convention). [VERIFIED: pyproject] |
| `SystemdNotifier` (in-repo, `weatherbot/ops`) | — | Confirm it is NOT called on reload (D-04: reload never touches READY) | The daemon already owns it for startup `emit_online`; reload must leave it untouched. [VERIFIED: read daemon.py] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PID file + SIGHUP (D-03) | systemd `ExecReload` + `MAINPID` | LOCKED OUT by D-04 (no ExecReload, reload stays always-ready); also wouldn't work on a bare dev box/Pi without systemd. |
| `os.replace` atomic PID write | a `python-pidfile`/`fasteners` lib | Unwarranted dependency; the daemon is single-instance and `os.replace` is atomic on POSIX. |
| `model_validator(mode="after")` for the id default | `default_factory` / `computed_field` | A `default_factory` can't see `name` (no cross-field access); a `computed_field` is read-only and can't be overridden by an explicit config `id`. The after-validator is the correct pattern (verified below). |
| New `Event` for reload handoff | reuse the existing `stop` Event | `stop` means "shut down" — overloading it would conflate reload with exit. Use a dedicated `reload_requested` Event (or a `select`/`signal.set_wakeup_fd`-style loop). |

**Installation:** No `uv add` required — zero new packages.

**Version verification (run 2026-06-15 against the project venv):**
- `apscheduler 3.11.2` — `add_job/get_job/get_jobs/remove_job/reschedule_job/modify_job` all present; `add_job` accepts `replace_existing`. [VERIFIED: installed venv]
- `pydantic 2.13.4` (pydantic-core 2.46.4) — frozen-model after-validator id-default verified working. [VERIFIED: installed venv]
- `python 3.12.3` — `tomllib`, `signal`, `threading`, `os.replace`, `zoneinfo` all stdlib. [VERIFIED]
- `jinja2` — **NOT installed, NOT a dependency.** [VERIFIED: import fails; absent from pyproject.toml/uv.lock]

## Package Legitimacy Audit

> Phase 9 installs **no external packages**. No audit table is required. All capabilities are met by already-pinned, already-audited deps (APScheduler 3.11.2, pydantic 2.13.4 — both vetted in prior phases, see `08-SECURITY.md` T-08-SC) and the Python 3.12 stdlib. slopcheck/registry verification is N/A because the package set is unchanged from Phase 8 (`tech-stack.added: []` expected).

## Architecture Patterns

### System Architecture Diagram

```
  OPERATOR EDITS                          TRIGGER (two equivalent paths)
  ┌──────────────┐                        ┌───────────────────────────────┐
  │ config.toml  │                        │ A) kill -HUP <pid>            │
  │ *.txt tmpl   │                        │ B) weatherbot reload          │
  └──────┬───────┘                        │    → read PID file            │
         │ (on disk; not yet live)        │    → /proc/<pid>/cmdline guard │
         │                                │    → os.kill(pid, SIGHUP)      │
         │                                └───────────────┬───────────────┘
         │                                                │ SIGHUP
         │                                                ▼
         │                              ┌─────────────────────────────────┐
         │                              │ SIGHUP handler (MAIN THREAD)     │
         │                              │  reload_requested.set()          │ ← no heavy work,
         │                              │  (returns immediately)           │   no lock, re-entrant-safe
         │                              └─────────────────┬───────────────┘
         │                                                │ main loop wakes
         │                                                ▼
         │                              ┌─────────────────────────────────┐
         └─────────────────────────────▶│ RELOAD ENGINE (main thread)      │
                                        │                                  │
   ┌────────────────────────────────────┤ PHASE 1 — BUILD & VALIDATE       │
   │ shared validate_config_and_templates│  off to the side, no live state  │
   │  1 tomllib.load(config.toml)        │  touched yet                     │
   │  2 Config.model_validate (+ id dflt)│                                  │
   │  3 assert_unique_names (name + id)  │  any failure ──┐                 │
   │  4 validate_template(each tmpl file)│                │                 │
   └────────────────────────────────────┤                ▼                 │
                                        │           REJECT: log reason,    │
                                        │           KEEP OLD config+jobs,  │
                                        │           return (CFG-04)        │
                                        │                                  │
                                        │ PHASE 2 — COMMIT (only if valid) │
                                        │  a) snapshot old job set         │ ← rollback anchor
                                        │  b) holder.replace(new_config)   │ ← atomic swap (Phase-8 seam)
                                        │  c) diff-reconcile jobs:         │
                                        │     + add new id                 │
                                        │     ~ add_job(replace_existing)  │
                                        │     - remove_job(deleted/disabled)│
                                        │     = unchanged → no-op          │
                                        │  d) on any reconcile throw →     │
                                        │     ROLLBACK to snapshot + old   │
                                        │     config (CFG-04 all-or-nothing)│
                                        │  e) log "+a −r ~c =u" (CFG-06)   │
                                        └─────────────────┬───────────────┘
                                                          │
                                                          ▼
                              ┌──────────────────────────────────────────┐
                              │ LIVE fire_slot jobs (APScheduler pool,     │
                              │ max_workers=10) — each fire:               │
                              │   snapshot = holder.current()  (once)      │ ← sees fully-old OR fully-new
                              │   local_date from location.timezone        │
                              │   claim_slot(db, location.ID, time, date)  │ ← KEY now uses id, not name
                              │   if already-claimed-today → SKIP (no dup) │ ← Pitfall #8 guard
                              └──────────────────────────────────────────┘

  NEVER TOUCHED ON RELOAD: Settings/.env secrets (restart boundary, Pitfall #12);
  systemd READY/RELOADING state (D-04); the SystemdNotifier.
```

### Recommended Code Touch-Map (not new folders — this phase edits existing files)
```
weatherbot/
├── config/
│   ├── models.py      # + Location.id (optional, defaults to casefold(name)) — D-01
│   └── loader.py      # + validate_config_and_templates() shared fn — D-05/D-08
│                      #   extend assert_unique_names to also enforce unique id
├── scheduler/
│   ├── daemon.py      # SIGHUP handler + reload engine (two-phase commit + diff-reconcile)
│   │                  #   PID-file write on start / unlink on clean shutdown
│   │                  #   fire_slot claim_slot/release_claim/record_alert → use location.id
│   └── catchup.py     # plan_catchup was_sent(loc.id, ...) — the OTHER exactly-once callsite
├── weather/
│   └── store.py       # NO schema change needed (column stays `location_name`); the VALUE
│                      #   written changes from name → id. (See "Schema decision" pitfall.)
└── cli.py             # + `reload` subparser (PID-file sender), + `check-config` subparser
templates/renderer.py  # UNCHANGED — validate_template already does token validation
```

### Pattern 1: Frozen-model optional `id` defaulting to the name slug (D-01)
**What:** Add `id: str | None = None` to `Location` (which is `frozen=True`). When omitted,
fill it with `casefold(name)` so the sent-log key is byte-identical to today's for any config
that doesn't set `id`. An explicit `id` in `config.toml` wins.
**When to use:** This is THE mechanism for rename-safety + zero-migration.
**Example (verified working against pydantic 2.13.4 in this project's venv):**
```python
# weatherbot/config/models.py — inside class Location(BaseModel)
# model_config already = ConfigDict(extra="forbid", frozen=True)
from pydantic import model_validator

    id: str | None = None   # OPTIONAL stable identity; defaults to casefold(name)

    @model_validator(mode="after")
    def _default_id_from_name(self) -> "Location":
        if self.id is None:
            # frozen=True forbids normal assignment, so use object.__setattr__
            # (the pydantic-blessed escape hatch inside an after-validator).
            object.__setattr__(self, "id", self.name.strip().casefold())
        return self
```
Verified: `Location(name="Home Base").id == "home base"`; an explicit `id="custom"` is kept;
post-construction rebind still raises `pydantic.ValidationError` (frozen invariant intact).
**Why `mode="after"` and not `default_factory`/`computed_field`:** `default_factory` cannot
read `name`; `computed_field` is read-only (can't be overridden by an explicit config value).
The after-validator is the only pattern that gives "explicit-wins, else derive-from-name."

### Pattern 2: Shared offline validation, one function, zero network (D-05/D-08)
**What:** A single function both `check-config` and the reload engine call. It performs parse +
full pydantic validate + unique name + unique id + template-token validation — and touches no
network and no live state.
**When to use:** Always — "a config that passes `check-config` is exactly a config reload will
accept" is a phase success criterion (SC#5 / the specifics block).
**Example:**
```python
# weatherbot/config/loader.py
from templates.renderer import load_template, validate_template

def validate_config_and_templates(
    path: str | Path,
    templates_dir: str | Path | None = None,
) -> Config:
    """Parse + fully validate config AND its referenced templates. Zero network.

    Shared by `check-config` (CFG-08) and the reload engine (CFG-04). Raises on any
    failure so callers do reject-and-keep-old (reload) or report-fail (check-config).
    """
    cfg = load_config(path)                 # tomllib + Config.model_validate (incl. id default)
    assert_unique_names(cfg)                 # extend below to also assert unique id
    # Template-token validation — NO Jinja2, NO render, NO network:
    if templates_dir is not None:
        text = load_template(cfg.template, templates_dir)
    else:
        text = load_template(cfg.template)   # default = templates/ package dir
    validate_template(text)                  # raises ValueError on any non-CANONICAL {token}
    return cfg
```
Extend `assert_unique_names` to also reject duplicate `id`s (two locations with the same id
would collide in the sent-log key — same failure mode the existing name-uniqueness check
guards). Note `config.template` is currently a single template; the loop "each referenced
template file" is a single file today but write it as a set so future per-location templates
don't break the contract.

### Pattern 3: Two-phase build-then-commit with rollback (Pitfall #6 / SC#2)
**What:** Validate the entire new world off to the side; only after it fully validates do you
swap the holder and reconcile jobs; if reconcile throws midway, restore the snapshot.
**When to use:** The reload commit path — "all-or-nothing apply" is SC#2.
**Example (sketch — planner turns into tasks):**
```python
def _do_reload(scheduler, holder, *, config_path, db_path, settings, client, channel, stop_event):
    # PHASE 1 — build & validate (no live mutation yet)
    try:
        new_cfg = validate_config_and_templates(config_path)
    except (FileNotFoundError, tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        _log.warning("reload rejected", reason=str(exc))   # CFG-04 + CFG-06 rejection line
        return  # KEEP OLD: holder and jobs untouched

    # PHASE 2 — commit (atomic-ish; rollback on reconcile failure)
    old_cfg = holder.current()
    old_jobs = {j.id: j for j in scheduler.get_jobs() if j.id != "__heartbeat__"}
    holder.replace(new_cfg)                # readers now see new whole config (Phase-8 seam)
    try:
        added, removed, changed, unchanged = _reconcile_jobs(scheduler, holder, ...)
    except Exception:
        # ROLLBACK: restore old config + old job set (Pitfall #6)
        holder.replace(old_cfg)
        _restore_jobs(scheduler, old_jobs)     # re-add snapshot, remove any partial new jobs
        _log.error("reload reconcile failed; rolled back to previous config")
        return
    _log.info("reload applied", added=added, removed=removed, changed=changed, unchanged=unchanged)
```

### Pattern 4: Diff-reconcile on the stable job id (Pitfall #7 / SC#3)
**What:** Compute desired job ids from the new config; compare to live job ids; add new,
`replace_existing=True` for present-but-changed, `remove_job` for deleted/disabled, no-op for
unchanged. Never `remove_all_jobs()`.
**When to use:** Inside Phase 2 commit.
**Key facts (verified APScheduler 3.11.2):** `scheduler.get_jobs()` returns the live `Job`s;
each `Job.id` is the stable `name|time|days` string already in use; `scheduler.add_job(...,
id=<id>, replace_existing=True)` is a no-op-or-update; `scheduler.remove_job(id)` deletes one.
**What counts as "changed":** With the id keyed on `name|time|days`, a change to the *time* or
*days* yields a NEW id (so it shows as one add + one remove, which is correct — it's a
different slot). A "changed" job under the SAME id is one whose trigger/cron is identical but
some *other* job kwarg differs (e.g. the job always carries the `holder`, so config-content
changes are invisible to the trigger and need NO job change — the per-fire `holder.current()`
read already picks them up). **Practical consequence:** for THIS codebase, "changed" in the
diff summary is mostly about enabled→disabled (remove) / disabled→enabled (add) and
time/days edits (remove old id + add new id). A pure content edit (units, lat/lon, template,
location display name) produces `=unchanged` job-wise and takes effect purely via the holder
swap — exactly Phase 8's design.

### Anti-Patterns to Avoid
- **`scheduler.remove_all_jobs()` then rebuild** — drops a briefing if a fire falls in the gap,
  and can double-fire (Pitfall #7). Use diff-reconcile.
- **Doing reload work inside the SIGHUP handler** — handlers run re-entrantly on the main
  thread; acquiring `holder._lock` (or any lock) there risks deadlock (`docs.python.org`:
  "synchronization primitives ... should not be used within signal handlers"). Set an Event,
  reload in the main loop.
- **Validating in `replace()`** — keep `ConfigHolder.replace()` a dumb swap (Phase-8 contract);
  the validate boundary lives in the reload engine, in front of `replace()`.
- **Changing the sent-log key column meaning without changing BOTH callsites in lockstep** —
  `fire_slot` (daemon: `claim_slot`/`release_claim`/`record_alert`) AND `plan_catchup`'s
  `was_sent` must use `location.id` together, or a reload desyncs claim vs check.
- **Touching systemd READY/RELOADING on reload** — D-04 forbids it; only restart re-gates.
- **Re-reading `.env`/Settings on reload** — Pitfall #12; secrets are a restart boundary; the
  holder owns `Config` only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic config swap | A custom double-buffer / copy-on-write | `ConfigHolder.replace()` (Phase 8) | Already built, lock-guarded, proven by `test_concurrent_read_swap_safe`; readers see whole-old or whole-new |
| Job reconciliation | `remove_all_jobs()`+rebuild, or manual job tracking dict | `get_jobs()` + `add_job(replace_existing=True)` + `remove_job()` | APScheduler's supported idempotent API; avoids the drop/double-fire of Pitfall #7 |
| Template-token validation | A Jinja2 environment with `StrictUndefined`/`jinja2.meta` | `templates.renderer.validate_template()` | **There is no Jinja2.** The existing regex validator already detects unknown tokens, zero network, zero render |
| TOML parse + schema validate | A hand-rolled validator | `load_config()` (`tomllib` + `Config.model_validate`) | Already fails-loud on bad TOML/missing fields; reuse it |
| IANA-tz-correct "today" | Manual offset math | `_local_date_iso` / `datetime.now(ZoneInfo(tz)).date()` | Already DST-correct and used by both fire_slot and catchup |
| Atomic PID-file write | Open-truncate-write (racy/partial) | write temp + `os.replace(tmp, pidfile)` | `os.replace` is atomic on POSIX; no partial PID file ever observed |
| PID-recycling guard | trust the PID blindly | read `/proc/<pid>/cmdline` and verify it's a weatherbot process | D-03 requirement; cheap stdlib file read; prevents SIGHUP to a recycled PID |
| Signal→work handoff | reload inside the handler | set a `threading.Event`, act in the main loop | Stdlib-blessed pattern; avoids re-entrancy/deadlock |

**Key insight:** Almost everything this phase needs already exists in the codebase or stdlib.
The genuinely new logic is small: the `id` field + default, the shared validate function (a
thin wrapper over existing calls), the two-phase reload orchestration, the diff-reconcile loop,
the SIGHUP handler + main-loop handoff, and the PID-file sender. No new dependency, no Jinja2.

## Runtime State Inventory

> This is a **feature** phase, not a rename/refactor — but D-01 migrates the exactly-once key,
> which has real runtime-state implications. Documented here because the sent-log is persisted
> runtime state that the key change interacts with.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | SQLite sent-log `sent_log(location_name, send_time, local_date)` UNIQUE key in the DB at `DEFAULT_DB_PATH`; `alerts(location_name, slot_time, local_date)` shares the same `location_name` value. Existing rows store `location.name`. | **Code edit only, ZERO data migration** — because `id` defaults to `casefold(name)`. NOTE: if `name` had different casing than `casefold(name)`, the stored row (raw name) and the new key (casefolded id) would differ. **See HIGHEST-RISK pitfall below** — the default must reproduce the *exact* string currently stored, or pre-existing rows for an un-`id`'d location won't match. |
| Live service config | None — no n8n/Datadog/external service holds this string. The daemon is self-contained. | None — verified by absence (single-process Python daemon; grep found no external registrations). |
| OS-registered state | A systemd unit (Phase 5) runs the process; reload does NOT re-register it (D-04 no ExecReload). The new PID file is OS-adjacent runtime state. | PID file: write on startup, unlink on clean shutdown (reuse the existing `finally` shutdown path in `run_daemon`). No systemd unit change required for SIGHUP delivery (D-03 sends it directly). |
| Secrets/env vars | `.env` (`OPENWEATHER_API_KEY`, `DISCORD_WEBHOOK_URL`) on `Settings` — **explicitly OUT** (Pitfall #12, restart boundary). | None — the holder owns `Config` only; reload must never read Settings. |
| Build artifacts | `weatherbot` console script (hatchling, `[project.scripts]`). Adding `reload`/`check-config` subcommands needs no reinstall (they're dispatched inside `main()`). | None — no new entry point; subcommands are added to the existing `add_subparsers` block. |

**The canonical question — after every file is updated, what runtime state still holds the old
key?** The persisted SQLite `sent_log`/`alerts` rows written before the change. Because `id`
defaults to `casefold(name)`, those rows remain matchable **iff** the code that currently writes
the row writes the *same* string the new id-keyed read will look up. **This is the single
sharpest implementation detail — see Pitfall 1.**

## Common Pitfalls

### Pitfall 1: The `id` default must reproduce the EXACT string the sent-log already stores (HIGHEST RISK — Pitfall #8)
**What goes wrong:** Today `claim_slot`/`was_sent` are called with `location.name` (the RAW
display string, e.g. `"Home Base"`). If D-01's `id` defaults to `casefold(name)` (e.g.
`"home base"`) and the callsites switch to `location.id`, then for a pre-existing row written
under `"Home Base"`, the new lookup under `"home base"` **misses** → the slot is treated as
un-sent → **duplicate briefing** on the first day after upgrade. This is exactly the Pitfall #8
failure, triggered not by a rename but by the migration itself.
**Why it happens:** "Defaults to the casefolded name slug" (D-01 wording) changes the stored
string's casing unless the current write path already casefolds — and it does NOT
(`claim_slot(db_path, location.name, ...)` passes the raw name; the schema stores it verbatim).
**How to avoid (decision the planner must lock):** Choose ONE and test it:
- **Option A (recommended, truly zero-migration):** Default `id = name` (the raw display
  string, NOT casefolded). Then for any un-`id`'d config the new id-keyed write/read is
  byte-identical to today's name-keyed rows — no migration, no first-day duplicate. Casefold
  only for the *uniqueness* check (`assert_unique_names` already casefolds names for collision
  detection), not for the stored key. This matches CONTEXT D-01's literal promise: "for any
  config where `id` is omitted, `id == name` so the key is byte-identical to today's."
- **Option B (casefolded id):** If a casefolded id is wanted, you MUST either (i) one-time
  migrate existing `sent_log`/`alerts` rows' `location_name` to casefolded form, or (ii)
  accept a possible one-time first-day duplicate. Strictly worse than A.

  **The CONTEXT.md D-01 text says both "casefolded name slug" AND "id == name ... byte-identical."
  These conflict for any name with uppercase letters. The planner/operator must resolve this:
  the byte-identical guarantee is only true under Option A (id defaults to the RAW name).**
  Tag this `[ASSUMED]` pending confirmation — recommend Option A.
**Warning signs:** A duplicate briefing the first morning after deploying Phase 9 for a config
whose location name contains uppercase letters.

### Pitfall 2: BOTH exactly-once callsites must change in lockstep (and there are THREE store functions, not one)
**What goes wrong:** The brief names `claim_slot` (daemon) and `was_sent` (catchup). But the
sent-log key's first component flows through **four** store calls that must ALL use the same
id: `claim_slot`, `release_claim`, `record_alert` (daemon `fire_slot`, plus its
`resolve_alert`), and `was_sent` (catchup). Miss one and a claim is taken under `id` but
released/alerted under `name` (or vice-versa) → orphaned claims or duplicate alerts.
**How to avoid:** Grep every `location.name`/`loc.name` passed to a `weather.store` function and
change them together to `location.id`/`loc.id`. The store functions' parameter is literally
named `location_name` — leave the SQL/column name alone (see Pitfall 3) and just pass the id
value. Add a test that exercises claim→release→re-claim and claim→alert all on the id key.
**Warning signs:** An alert recorded for a slot that did deliver; a released claim that doesn't
re-open the slot; `record_alert`/`resolve_alert` keyed differently than `claim_slot`.

### Pitfall 3: Don't rename the DB column — change the VALUE, not the schema
**What goes wrong:** Renaming the `location_name` column to `location_id` is a schema migration
on a live SQLite file with historical rows — gratuitous risk for zero benefit.
**How to avoid:** Keep the column named `location_name`; just write the `id` value into it. The
column is an opaque text identity; its name is an implementation detail. (This also keeps the
`alerts` table consistent for free.) No `ALTER TABLE`, no migration script.
**Warning signs:** A migration task appears in the plan touching `_SCHEMA` — it shouldn't.

### Pitfall 4: The already-sent-today guard is the existing claim, not new code (D-02)
**What goes wrong:** Over-engineering a separate "did this slot already send today?" check for
the reload path. The guarantee is already structural: `fire_slot` calls `claim_slot` (atomic
`INSERT OR IGNORE` on the UNIQUE key) BEFORE delivering; a LOST claim returns `None` (skip). A
reload changes only WHICH jobs exist and WHAT config they read — it does NOT delete sent-log
rows. So a slot already claimed today (under its `id`) cannot re-fire after a reload, because
the next fire's `claim_slot` loses. **The guard is "don't touch the sent-log on reload"** — and
the reload engine doesn't. **Caveat:** this holds only if the `id` is STABLE across the reload
(Option A above) — if the id changes for an already-sent slot, the new id's `claim_slot`
*wins* and re-fires (the duplicate). So D-02's "tz/name/send_time change takes effect next day"
is satisfied for tz/send_time/name changes **as long as the `id` itself is unchanged**. An
explicit `id` change in the same reload as a same-day re-fire is the one case that would
duplicate — document that an `id` is meant to be stable (it's the rename-safety anchor, not a
thing you change daily).
**How to test deterministically (SC#4, mandatory):** (1) seed a `sent_log` row for
`(id, time, today)`; (2) `holder.replace()` a config that changes that location's tz/name/
send_time but KEEPS its id; (3) call `fire_slot` for the old-and/or-new slot with a stubbed
channel; (4) assert `claim_slot` loses → returns `None` → channel.send NOT called (no
duplicate) AND no exception/skip of a different valid slot. No wall-clock waits needed — inject
`scheduled_dt`/seed the row directly (mirrors the existing catchup tests' clock injection).

### Pitfall 5: tz change recomputing `local_date` can shift the calendar day (Pitfall #8 sub-case)
**What goes wrong:** `local_date` is derived from `location.timezone`. A reload that changes the
tz makes a *future* fire compute a possibly-different `local_date`. Near midnight, the same
wall-clock instant can be `2026-06-15` under the old tz and `2026-06-16` under the new — so a
slot "already sent today" under the old date could re-claim under the new date (duplicate) or
skip.
**How to avoid:** This is bounded by D-02 + Pitfall 4: the already-sent row exists under the
OLD `(id, time, local_date_old)`. After a tz change, a re-fire computes
`(id, time, local_date_new)` — a DIFFERENT key — and `claim_slot` would WIN (duplicate). The
defense is that the schedule change "takes effect next day": the slot that already fired today
should not fire again today regardless of tz. Practically, since the `id` is stable, the
cleanest guard is: **on reload, do not immediately re-fire any slot for the current local day**
— let the new schedule's first fire be tomorrow. Because reload does NOT run a catch-up scan
(catch-up is startup-only), and the live cron jobs only fire at their future cron times, a
mid-day reload naturally won't re-fire a past time *unless* the new send_time is later today and
still ahead — that future fire under a new key is the risk. **Planner decision:** either (a)
accept that a tz/send_time change whose new fire-time is still ahead today WILL fire today (it's
a genuinely different slot id if time changed; arguably correct), or (b) add a guard that
suppresses same-local-day fires for a slot whose `id` already has a sent row today under ANY
date within ±1 day. Recommend (a) for time/days changes (new id = new slot = legitimately
fires) and rely on the stable-id claim for name/tz-only changes (same id, same time → same key
family → claim loses). Test both directions.
**Warning signs:** A duplicate or skipped send when a tz edit lands within a few hours of midnight.

### Pitfall 6: SIGHUP handoff must not block on `stop.wait()` (main-loop shape)
**What goes wrong:** The daemon's main thread currently blocks on `stop.wait()` forever until
SIGTERM. A SIGHUP handler that only sets `reload_requested` won't be *serviced* if the main
thread is parked in `stop.wait()` — the Event is set but nobody acts on it.
**How to avoid:** Two viable shapes (planner picks): (a) **loop-and-poll** — replace the single
`stop.wait()` with `while not stop.is_set(): if reload_requested.wait(timeout=...): do_reload()`
so the main thread wakes periodically (or immediately, since a signal interrupts the wait on
the main thread) and checks the reload flag; or (b) **handler does the (cheap) flag-set and the
reload runs on the scheduler thread** via a one-shot `scheduler.add_job(_do_reload, ...)` —
but that re-enters APScheduler from inside a job context, which is messier. Recommend (a): a
small main-loop change, reload work on the main thread (no APScheduler worker contention),
SIGTERM still wins (`stop.is_set()` checked first). Note: on the main thread, a delivered signal
interrupts `Event.wait()` so the wake is prompt; a short timeout is a belt-and-suspenders.
**Warning signs:** `kill -HUP` logs nothing / config doesn't change until the next SIGTERM.

### Pitfall 7: Rollback of a partial job reconcile (Pitfall #6, the hard half of all-or-nothing)
**What goes wrong:** Phase-1 validation passed, `holder.replace()` swapped, but the
diff-reconcile loop throws on job #3 of 5 — now the holder is NEW but the job set is half-old/
half-new (torn).
**How to avoid:** Before reconciling, snapshot the old jobs (`{id: job}` from `get_jobs()`,
excluding `__heartbeat__`). On any exception during reconcile: `holder.replace(old_cfg)` to
restore config, then restore the job set (remove every job whose id isn't in the old snapshot;
re-add via `add_job(replace_existing=True)` any old job that got removed/modified). APScheduler
`Job` objects from a memory jobstore can be re-added by reusing their `func`/`trigger`/`kwargs`
— simplest is to re-derive the old job set from `old_cfg` (call the same `_register_jobs` build
logic against `old_cfg`) rather than resurrecting `Job` instances. **Recommend: rebuild from
`old_cfg` on rollback** — deterministic and reuses existing code.
**Warning signs:** After a (simulated) reconcile failure, `get_jobs()` shows a mix; a briefing
fires on a schedule that was never fully applied.

### Pitfall 8: `check-config` must be the OFFLINE subset of `check` (D-05) — don't reuse `do_check`
**What goes wrong:** The existing `check` (`do_check`) runs `run_self_check`, which makes a LIVE
OpenWeather reachability probe. `check-config` must send/probe NOTHING (D-05). Reusing
`do_check` would hit the network.
**How to avoid:** `check-config` calls the new `validate_config_and_templates()` (offline) and
reports pass/fail — it does NOT call `run_self_check`/`do_check`. The two share the *validation*
(parse+schema+unique+template) but `check` adds the network probe on top. Be explicit that
`check-config` ⊂ `check`.
**Warning signs:** `check-config` fails with an auth/network error when offline; it makes an HTTP
call (assert zero `client.fetch_*` in its test).

## Code Examples

### Verify a PID and signal it (the `weatherbot reload` sender — D-03)
```python
# weatherbot/cli.py — do_reload (new)
import os, signal
from pathlib import Path

PID_FILE = Path("/run/weatherbot.pid")  # see "PID file location" open question

def do_reload(pid_file: Path = PID_FILE) -> int:
    try:
        pid = int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        _log.error("reload: no valid PID file", path=str(pid_file))
        return 1
    # /proc cmdline staleness guard against PID recycling (D-03):
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except FileNotFoundError:
        _log.error("reload: PID not running (stale PID file)", pid=pid)
        return 1
    if b"weatherbot" not in cmdline:   # not OUR process — recycled PID
        _log.error("reload: PID is not a weatherbot process (recycled)", pid=pid)
        return 1
    os.kill(pid, signal.SIGHUP)
    _log.info("reload signal sent", pid=pid)
    return 0
```

### Atomic PID-file write on startup / unlink on shutdown (in `run_daemon`)
```python
import os, tempfile
from pathlib import Path

def _write_pid_atomic(pid_file: Path) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(pid_file.parent), prefix=".wbpid-")
    try:
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        os.replace(tmp, pid_file)      # atomic on POSIX — never a partial PID file
    except BaseException:
        os.close(fd) if not fd_closed else None
        Path(tmp).unlink(missing_ok=True)
        raise
# ... in run_daemon: _write_pid_atomic(PID_FILE) near startup;
#     in the finally: PID_FILE.unlink(missing_ok=True)
```

### SIGHUP handler + main-loop handoff (mirrors the existing SIGTERM pattern)
```python
# in run_daemon, alongside the existing `stop = threading.Event()` and _handle:
reload_requested = threading.Event()

def _handle_hup(signum, frame):     # MAIN THREAD only; do NO heavy work, take NO lock
    reload_requested.set()

signal.signal(signal.SIGHUP, _handle_hup)   # install before scheduler.start(), like SIGTERM

# replace the single `stop.wait()` block with a poll loop:
while not stop.is_set():
    if reload_requested.wait(timeout=1.0):   # signal also interrupts the wait promptly
        reload_requested.clear()
        if stop.is_set():
            break
        _do_reload(scheduler, holder, config_path=config_path, db_path=db_path,
                   settings=settings, client=client, channel=channel, stop_event=stop)
```
Note: `config_path` must be threaded into `run_daemon` (today it receives a pre-loaded
`config`, not a path — the reload engine needs the PATH to re-read). Plan a small signature
addition (`config_path=`) or capture it where `run_daemon` is invoked in `cli.py`.

### Offline `check-config` dispatch (D-06)
```python
# in main(): new subparser
subparsers.add_parser("check-config", parents=[config_parent],
    help="Validate config + templates OFFLINE (no network); apply/send nothing (CFG-08).")
...
if args.command == "check-config":
    try:
        validate_config_and_templates(args.config)
    except (FileNotFoundError, tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        _log.error("check-config failed", error=str(exc))
        return 1
    _log.info("check-config passed")
    return 0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Config baked into each job's `kwargs={"config": config}` | Job carries `holder`; reads `holder.current()` per-fire | Phase 8 (shipped) | A reload's `holder.replace()` is now actually seen by unchanged jobs — Phase 9 reload works |
| Sent-log key on mutable display `name` | Key on stable `id` (defaults to name) | Phase 9 (this phase) | Renaming a location no longer resets its "already sent" state (Pitfall #8) |
| `check` (network probe) only | `check` (probe) + `check-config` (offline) | Phase 9 | Operators can validate edits without hitting OpenWeather; same validator the reload uses |
| (assumed) Jinja2 templating | **Custom regex renderer (always was)** | — | No Jinja2 dependency exists; token validation is `validate_template`, not `jinja2.meta` |

**Deprecated/outdated (from the briefing's assumptions, corrected):**
- **Jinja2 `StrictUndefined` / `jinja2.meta.find_undeclared_variables`** — NOT applicable; this
  project never used Jinja2. Use `templates.renderer.validate_template`.
- **APScheduler 4.x reconcile APIs** — do not use; pinned to `>=3.11.2,<4` (CLAUDE.md: 4.x is
  not for production). The 3.x `add_job(replace_existing=True)`/`remove_job` API is the target.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `id` default should be the RAW `name` (Option A), NOT casefolded, to keep the sent-log key byte-identical to existing rows | Pitfall 1 | If casefolded instead, configs with uppercase location names get a duplicate briefing the first day after upgrade unless rows are migrated. **Needs operator confirmation** — CONTEXT D-01 contains both wordings. |
| A2 | PID file lives at `/run/weatherbot.pid` (configurable) | Open Questions | `/run` may need root or a tmpfiles.d entry on the host; a non-writable path makes `reload` fail. Operator should confirm the host's writable runtime dir. |
| A3 | "Changed" slots whose `time`/`days` differ legitimately fire under their new (different) job id even same-day; only same-id (name/tz/units) edits rely on the stable-id claim to avoid same-day re-fire | Pitfall 5, Pattern 4 | If the operator expects time/days edits to also defer to next day, an extra same-local-day suppression guard is needed. Needs confirmation of the intended D-02 boundary for time-edits specifically. |
| A4 | Reload runs on the MAIN thread via a poll-loop replacing `stop.wait()` | Pitfall 6 | If the planner instead schedules reload as an APScheduler job, re-entrancy concerns differ. Low risk (recommendation, not a constraint). |
| A5 | Rollback rebuilds the old job set from `old_cfg` rather than resurrecting `Job` objects | Pitfall 7 | If `old_cfg` rebuild has any nondeterminism the rollback could differ from the pre-reload set; mitigated because `_register_jobs` is deterministic given a config. |

## Open Questions (RESOLVED)

> **All three resolved by operator during plan-phase (2026-06-15):**
> - **A1 → RESOLVED:** `id` defaults to the **raw `name`** (casefold only for the uniqueness check). Zero-migration, byte-identical key. CONTEXT D-01 amended.
> - **A2 → RESOLVED (planner discretion):** PID path defaults to `/run/weatherbot.pid`, systemd `RuntimeDirectory=weatherbot` preferred, config-relative fallback. Not a correctness fork.
> - **A3 → RESOLVED:** a `send_time`/`days` change IS a new slot and **fires today if its new time is still ahead** (operator-confirmed: "got 08:00, moved to 09:00 at 08:30 → I want 09:00 today, only 09:00 thereafter"). D-02's already-sent guard protects **name/tz** edits only. CONTEXT D-02 + ROADMAP SC#4 amended; a location-level guard was rejected to preserve multi-slot-per-day locations.

1. **`id` default: raw name vs casefolded (Pitfall 1 / A1).**
   - What we know: D-01 promises "byte-identical to today's" key when `id` is omitted; that is
     only true if the default is the RAW `name` (since the current write passes `location.name`
     verbatim and the column stores it verbatim).
   - What's unclear: D-01 also says "casefolded name slug," which contradicts byte-identical for
     any uppercase name.
   - Recommendation: Default `id = name` (raw); casefold ONLY for uniqueness comparison
     (matching the existing name-uniqueness check). Confirm with operator before locking.

2. **PID file path (A2).**
   - What we know: D-03 leaves path to discretion; `/run` is the FHS runtime dir.
   - What's unclear: whether the daemon runs as a user without `/run` write access on the host
     (`yahir-mint`); systemd `RuntimeDirectory=weatherbot` would provision `/run/weatherbot/`.
   - Recommendation: Make the path configurable (constant + optional override), default
     `/run/weatherbot.pid`; if the host runs as non-root, prefer `RuntimeDirectory=` (systemd
     creates `/run/weatherbot/` owned by the service user) or fall back to a config-relative
     path. Confirm host runtime dir with operator.

3. **Same-day re-fire policy for `time`/`days` edits specifically (A3 / Pitfall 5).**
   - What we know: a `time`/`days` edit yields a NEW job id (different slot) which would fire
     today if its new time is still ahead.
   - What's unclear: whether the operator considers "I moved today's 09:00 to 17:00, it's now
     14:00" as "should fire at 17:00 today" (new slot) or "takes effect tomorrow" (D-02 spirit).
   - Recommendation: treat a changed time as a new slot (fires today if ahead); document it.
     Only name/tz/units edits (same id, same time) defer via the stable-id claim.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python `signal.SIGHUP` | CFG-02 trigger | ✓ (POSIX/Linux) | stdlib 3.12.3 | — (Linux-only host, per CLAUDE.md Pi/server) |
| `/proc/<pid>/cmdline` | D-03 staleness guard | ✓ (Linux) | — | If `/proc` absent (non-Linux), skip the cmdline check and signal directly (degraded guard). Host is Linux, so available. |
| `os.kill`, `os.replace`, `os.getpid` | reload sender + PID file | ✓ | stdlib 3.12.3 | — |
| Writable PID dir (`/run` or config-relative) | PID file | ⚠ depends on host perms | — | config-relative path if `/run` not writable (see Open Q2) |
| APScheduler reconcile API | CFG-05 | ✓ | 3.11.2 | — (verified present) |
| pydantic frozen after-validator | D-01 | ✓ | 2.13.4 | — (verified working) |
| `templates.renderer.validate_template` | D-05/D-08 token check | ✓ | in-repo | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** PID-file directory writability (fall back to a
config-relative path if `/run` is not writable for the service user).

## Validation Architecture

> nyquist_validation is enabled (`config.json: workflow.nyquist_validation: true`). Section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pinned `>=9.0.3`); `[tool.pytest.ini_options] testpaths=["tests"]` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `.venv/bin/python -m pytest tests/test_scheduler.py tests/test_config.py -x -q` |
| Full suite command | `.venv/bin/python -m pytest -q` (current baseline: 226 passing per `08-SECURITY.md`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CFG-01 | Edit config + SIGHUP/`reload` → new send-time fires on new schedule, no restart | unit/integration | `pytest tests/test_reload.py::test_reload_applies_new_schedule -x` | ❌ Wave 0 |
| CFG-02 | SIGHUP sets reload flag → reload runs; `weatherbot reload` finds PID + signals | unit | `pytest tests/test_reload.py::test_sighup_triggers_reload -x` ; `::test_reload_cli_signals_pid` | ❌ Wave 0 |
| CFG-04 | Bad TOML / dup name / dup id / unknown token rejected → keep OLD config; reconcile failure rolls back | unit | `pytest tests/test_reload.py::test_invalid_reload_keeps_old -x` ; `::test_reconcile_failure_rolls_back` | ❌ Wave 0 |
| CFG-05 | Diff-reconcile add/remove/change; identical reload = 0 changes; **exactly-once across tz/name/send_time change on already-sent slot (SC#4)** | unit | `pytest tests/test_reload.py::test_reconcile_diff -x` ; `::test_identical_reload_zero_changes` ; `::test_already_sent_slot_not_refired_after_tz_name_change` | ❌ Wave 0 |
| CFG-06 | Successful reload logs `+a −r ~c =u`; rejection logs reason | unit | `pytest tests/test_reload.py::test_reload_logs_diff_summary -x` ; `::test_rejected_reload_logs_reason` | ❌ Wave 0 |
| CFG-08 | `check-config` validates offline (parse+schema+unique+token), reports pass/fail, ZERO network/send | unit | `pytest tests/test_cli.py::test_check_config_offline_pass -x` ; `::test_check_config_no_network` | ❌ Wave 0 |
| D-01 | `Location.id` optional, defaults to name; explicit id wins; frozen invariant intact | unit | `pytest tests/test_models.py::test_location_id_default -x` | ❌ Wave 0 (extend existing test_models.py) |
| D-05 | `check-config` and reload share ONE validator (config passing one is accepted by the other) | unit | `pytest tests/test_reload.py::test_check_config_and_reload_share_validation -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_reload.py tests/test_models.py -x -q`
- **Per wave merge:** `pytest -q` (full suite; must stay ≥226 + new tests green)
- **Phase gate:** Full suite green before `/gsd-verify-work`; the SC#4 exactly-once test
  (`test_already_sent_slot_not_refired_after_tz_name_change`) is the load-bearing gate.

### Wave 0 Gaps
- [ ] `tests/test_reload.py` — NEW; covers CFG-01/02/04/05/06, two-phase commit, rollback,
      diff-reconcile, SIGHUP handoff, and the mandatory SC#4 already-sent-not-refired test.
- [ ] `tests/test_models.py` — EXTEND with `test_location_id_default` (D-01).
- [ ] `tests/test_cli.py` — EXTEND with `check-config` offline + no-network tests (CFG-08).
- [ ] Shared fixtures: a sent-log-seeding helper (insert a `(id, time, today)` row) and a
      holder+scheduler harness — likely add to `tests/conftest.py` (reuse existing
      `test_config_holder.py` / `test_scheduler.py` fixtures where possible).
- [ ] Framework install: none — pytest already present.

## Security Domain

> security_enforcement is enabled (`config.json`), ASVS Level 1. Section included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surface; reload is local IPC (signal). |
| V3 Session Management | no | No sessions. |
| V4 Access Control | yes | The SIGHUP/PID path is local; `os.kill` requires the same UID (OS-enforced). The `/proc/cmdline` guard prevents signaling a recycled PID — a correctness+safety control. |
| V5 Input Validation | yes | The whole reload engine IS input validation: `validate_config_and_templates` (TOML parse, pydantic schema, unique id/name, token allow-list) rejects malformed input and keeps-old (CFG-04). Reuse existing validators — don't hand-roll. |
| V6 Cryptography | no | No crypto introduced. Secrets stay on `Settings`/`.env`, never enter the holder (Pitfall #12) — reload must not read them. |

### Known Threat Patterns for this phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/partial config applied → torn live state | Tampering / DoS | Two-phase validate-then-commit; keep-old on any failure; rollback on reconcile throw (CFG-04). |
| Exactly-once key break → duplicate/skipped briefing | Tampering (integrity of the delivery guarantee) | Stable `id` key (defaults to raw name = byte-identical); never touch sent-log on reload; SC#4 test. |
| SIGHUP to a recycled PID (signal hijack) | Spoofing / Tampering | `/proc/<pid>/cmdline` weatherbot-process verification before `os.kill` (D-03). |
| Reload re-reading `.env` and half-applying a secret rotation | Tampering / Info-disclosure | Holder owns `Config` only; reload path never constructs/reads `Settings` (Pitfall #12; restart boundary). |
| Template-token injection via edited template | Tampering | `validate_template` allow-list (no `str.format`/`eval`; unknown tokens rejected at validate, left literal at render) — already hardened (T-03-02/03). |
| Outcome log leaking secrets | Info-disclosure | Outcome-only logging convention (T-04-01): reload log line carries counts/location ids/reason — never key/URL. |

**Carry-over:** `08-SECURITY.md` T-08-07 (unvalidated `replace()`) is explicitly **closed by this
phase** — Phase 9 hangs `validate_config_and_templates` in front of every production
`replace()` call, so no production path ever swaps an unvalidated config.

## Sources

### Primary (HIGH confidence)
- Installed project venv (`.venv`) — APScheduler 3.11.2 reconcile API surface (`add_job`
  `replace_existing`, `get_jobs`, `get_job`, `remove_job`, `reschedule_job`, `modify_job`)
  verified present; pydantic 2.13.4 frozen after-validator id-default verified working; Python
  3.12.3; Jinja2 verified ABSENT. [VERIFIED]
- Codebase reads (this phase's touch-points): `weatherbot/config/holder.py`,
  `weatherbot/config/models.py`, `weatherbot/config/loader.py`, `weatherbot/scheduler/daemon.py`,
  `weatherbot/scheduler/catchup.py`, `weatherbot/weather/store.py` (sent_log/alerts schema +
  claim/release/was_sent/record_alert signatures), `weatherbot/cli.py` (subparsers, do_check),
  `templates/renderer.py` (regex renderer + validate_template). [VERIFIED]
- `pyproject.toml` / `uv.lock` — pinned versions; no Jinja2; APScheduler `<4`. [VERIFIED]
- `.planning/research/PITFALLS.md` — Pitfalls #6/#7/#8/#9/#12/#13 (project source of truth). [CITED]
- `.planning/phases/08-*/08-CONTEXT.md`, `08-SECURITY.md` — ConfigHolder seam, frozen snapshots,
  per-fire snapshot (T-08-08), T-08-07 deferral to Phase 9. [CITED]
- `09-CONTEXT.md` — LOCKED decisions D-01..D-08. [CITED]
- docs.python.org/3/library/signal.html — handlers run on the main thread; locks unsafe in
  handlers. [CITED]

### Secondary (MEDIUM confidence)
- Medium/Stackabuse/Python-docs SIGHUP-reload articles — confirm the "set a flag in the handler,
  reload in the main loop" pattern and "don't use Lock in a handler." Cross-verified with the
  official `signal` docs. [CITED: medium.com/@snnapys-devops, stackabuse.com]

### Tertiary (LOW confidence)
- None — all load-bearing claims verified against the venv or the codebase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new deps; every API verified present in the installed venv.
- Architecture (two-phase commit, diff-reconcile, SIGHUP handoff, PID file): HIGH — all
  primitives exist and are verified; the orchestration is straightforward composition.
- Exactly-once key migration (Pitfall #8): HIGH on mechanism, MEDIUM on the ONE open decision
  (raw-name vs casefolded id default, A1) — flagged for operator confirmation because CONTEXT
  D-01 is internally contradictory on this exact point.
- Template validation: HIGH — corrected a wrong premise (no Jinja2); the real validator exists
  and already does exactly what D-05/D-08 need.

**Research date:** 2026-06-15
**Valid until:** ~2026-07-15 (stable stack, pinned versions; the only live risk is a pydantic
2.x point-release changing frozen-after-validator semantics — unlikely within the window).

## Project Constraints (from CLAUDE.md)

- **Python 3.12+ / uv / pinned stack** — no new runtime deps this phase (reuse APScheduler
  3.11.x, pydantic 2.13.x, structlog, stdlib).
- **APScheduler 3.11.x only, NEVER 4.x** — diff-reconcile uses the 3.x `add_job`/`remove_job`
  API. [enforced]
- **In-process scheduler; systemd only keeps the process alive** — reload is in-process via
  SIGHUP; D-04 forbids `ExecReload`/sd_notify reload handshake.
- **Secrets in git-ignored `.env`, never in config / never logged** — reload never reads
  `Settings`; outcome logs are counts/ids/reasons only (T-04-01).
- **TOML config, hand-edited, comment-friendly** — reload re-reads `config.toml` via `tomllib`.
- **GSD workflow enforcement** — implementation must go through `/gsd-execute-phase`; this
  research feeds the planner only.
- **ruff lint+format, pytest** — new code lints clean; new tests under `tests/`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CFG-01 | Edit config.toml + templates → running daemon applies without restart | Holder swap (Phase 8 seam) + SIGHUP main-loop handoff (Pitfall 6) + diff-reconcile (Pattern 4); reload re-reads the config PATH (note `run_daemon` needs `config_path`) |
| CFG-02 | Explicit trigger via SIGHUP and/or `weatherbot reload` | SIGHUP handler mirrors existing SIGTERM install (Code Examples); `do_reload` sender = PID file + `/proc/cmdline` guard + `os.kill` (D-03) |
| CFG-04 | Invalid edit rejected, keep previous valid config, all-or-nothing | Two-phase build-then-commit (Pattern 3) + rollback on reconcile throw (Pitfall 7); shared validator raises → keep-old |
| CFG-05 | Re-register jobs (add/remove/change) without drop/double-fire; exactly-once preserved | Diff-reconcile on stable `name\|time\|days` id (Pattern 4); exactly-once via stable `id` key (Pitfalls 1–5) + structural claim guard (Pitfall 4); mandatory SC#4 test |
| CFG-06 | Per-reload outcome log line | structlog `+a −r ~c =u` on success / reason on rejection (Pattern 3, D-07) |
| CFG-08 | `weatherbot check-config` offline dry-run | New subparser → `validate_config_and_templates` (Pattern 2); offline subset of `check` (Pitfall 8); shares ONE validator with reload (D-05) |
</phase_requirements>
