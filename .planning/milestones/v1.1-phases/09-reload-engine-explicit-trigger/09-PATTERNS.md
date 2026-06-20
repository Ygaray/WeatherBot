# Phase 9: Reload Engine & Explicit Trigger - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 8 (3 new logic units + 5 modified)
**Analogs found:** 8 / 8 (every new/modified file has a strong in-repo analog — zero new deps)

> All analogs are in-repo. This phase composes existing primitives (Phase-8 `ConfigHolder`,
> the `store.py` claim/release/alert family, the daemon SIGTERM/signal idiom, the argparse
> subparser grammar, the pydantic frozen-model validators, the regex `validate_template`).
> RESEARCH.md confirms **no new packages** and **no Jinja2** — token validation is the existing
> regex allow-list.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/config/loader.py` — NEW `validate_config_and_templates()` + extend `assert_unique_names` | utility (validator) | transform / batch-validate | `weatherbot/config/loader.py::load_config` + `::assert_unique_names` (same file) | exact |
| `weatherbot/config/models.py` — `Location.id` optional field | model | transform (validation) | `weatherbot/config/models.py::Reliability._budget_under_grace` (frozen `model_validator(mode="after")`) | exact |
| `weatherbot/scheduler/daemon.py` — NEW reload engine (`_do_reload` + `_reconcile_jobs` + `_restore_jobs`) | service (orchestration) | event-driven (SIGHUP) → CRUD-on-jobset | `daemon.py::_register_jobs` (job add/diff) + `holder.py::replace` (swap) | role-match (composition) |
| `weatherbot/scheduler/daemon.py` — `run_daemon` SIGHUP handler + poll loop + PID file | service (lifecycle) | event-driven / signal | `daemon.py::run_daemon` existing SIGTERM `_handle` + `stop.wait()` + `finally` (same fn) | exact |
| `weatherbot/scheduler/daemon.py` — `fire_slot` store callsites → `location.id` | service | CRUD (sent-log key) | `daemon.py::fire_slot` lines 168/224/230/246/248/269/271/290 (in place) | exact |
| `weatherbot/scheduler/catchup.py` — `was_sent(loc.id, …)` | utility (pure planner) | CRUD-read (idempotency) | `catchup.py::plan_catchup` line 170 (in place) | exact |
| `weatherbot/cli.py` — `reload` + `check-config` subcommands | controller (CLI) | request-response (subcommand dispatch) | `cli.py::main` subparser block (534–587) + dispatch (605–658) + `do_check` | exact |
| `weatherbot/cli.py` / `weatherbot/ops/` — PID-file helper (atomic write + `/proc` guard) | utility (ops helper) | file-I/O | `weatherbot/ops/sdnotify.py` (stdlib-only, never-raise ops helper) + `store.py` atomic-write posture | role-match |

> **Schema note (Pitfall 3):** `weatherbot/weather/store.py` is **NOT modified** — the
> `location_name` column stays; only the VALUE passed by callers changes (`location.name` →
> `location.id`). No `_SCHEMA` edit, no migration. The store functions' parameter is literally
> named `location_name` — leave the signature alone, change the argument at the callsite.

## Pattern Assignments

### `weatherbot/config/models.py` — `Location.id` (model, frozen after-validator)

**Analog:** `weatherbot/config/models.py::Reliability._budget_under_grace` (lines 197–209) and the
existing `Location` model (lines 82–117). `Location` is already `frozen=True` and already imports
`model_validator` is available in the module (line 12 imports `field_validator, model_validator`).

**Frozen-model default-from-name idiom** — the new field + after-validator goes on `Location`
(currently lines 82–117). The verified-working shape (RESEARCH Pattern 1; default = RAW `name`,
NOT casefolded — see "Shared Patterns / Exactly-once key" below):
```python
# class Location(BaseModel) — model_config = ConfigDict(extra="forbid", frozen=True)
    id: str | None = None   # OPTIONAL stable identity; defaults to the RAW name (zero-migration)

    @model_validator(mode="after")
    def _default_id_from_name(self) -> "Location":
        if self.id is None:
            # frozen=True forbids normal assignment → object.__setattr__ is the
            # pydantic-blessed escape hatch inside an after-validator.
            object.__setattr__(self, "id", self.name)
        return self
```

**Why `object.__setattr__` and `mode="after"`:** the existing `Reliability._budget_under_grace`
(line 197) shows the `@model_validator(mode="after")` returning `self`; a `default_factory`
cannot read `name`, and `computed_field` is read-only (can't be overridden by an explicit config
`id`). Mirror the existing frozen-model validators in this exact module.

---

### `weatherbot/config/loader.py` — `validate_config_and_templates()` + unique-`id` (utility, transform)

**Analog:** same file — `load_config` (lines 18–27), `assert_unique_names` (lines 67–83), and the
`templates/renderer.py` `validate_template`/`load_template` pair.

**Parse + validate idiom to wrap** (`load_config`, lines 18–27):
```python
def load_config(path: str | Path) -> Config:
    path = Path(path)
    with path.open("rb") as fh:  # tomllib requires binary mode
        raw = tomllib.load(fh)
    return Config.model_validate(raw)
```

**Unique-key check to EXTEND for `id`** (`assert_unique_names`, lines 67–83) — note it already
casefolds for collision detection; the new `id` uniqueness check copies this shape exactly
(casefold ONLY for the collision test, never for the stored value):
```python
def assert_unique_names(config: Config) -> None:
    seen: dict[str, str] = {}
    for loc in config.locations:
        key = loc.name.casefold()
        if key in seen:
            raise ValueError(f"Duplicate location name {loc.name!r} ...")
        seen[key] = loc.name
```
Add a parallel `seen_id: dict[str, str]` loop keyed on `loc.id.casefold()` (so `Home`/`home` ids
collide) raising the same fail-loud `ValueError`. Keep it in this function or a sibling
`assert_unique_ids` — either is consistent with the existing fail-loud-at-load posture.

**Template-token validation (NO Jinja2)** — `templates/renderer.py::validate_template` (lines
58–72) raises `ValueError` on any non-`CANONICAL` `{token}` with zero network/zero render;
`load_template` (lines 90–93) reads the file. The shared validator composes these:
```python
# weatherbot/config/loader.py — NEW
from templates.renderer import load_template, validate_template

def validate_config_and_templates(path, templates_dir=None) -> Config:
    """Parse + fully validate config AND its referenced templates. Zero network.
    Shared by `check-config` (CFG-08) and the reload engine (CFG-04). Raises on
    any failure so callers reject-and-keep-old / report-fail."""
    cfg = load_config(path)            # tomllib + Config.model_validate (incl. id default)
    assert_unique_names(cfg)           # extend to also assert unique id
    text = (load_template(cfg.template, templates_dir)
            if templates_dir is not None else load_template(cfg.template))
    validate_template(text)            # raises ValueError on any non-CANONICAL {token}
    return cfg
```
**Raise set the callers catch:** `FileNotFoundError`, `tomllib.TOMLDecodeError`,
`pydantic.ValidationError`, `ValueError` (see `_load_config_reporting`, cli.py 460–478, which
already catches exactly these three for the friendly-error path).

---

### `weatherbot/scheduler/daemon.py` — reload engine `_do_reload` / `_reconcile_jobs` (service, event→CRUD)

**Analog for the swap:** `weatherbot/config/holder.py::replace` (lines 59–66) — a dumb,
lock-guarded rebind. KEEP it dumb (Phase-8 contract); the validate boundary lives in front of it
in the reload engine, never inside `replace()`.

**Analog for job (re)registration / the reconcile loop:** `daemon.py::_register_jobs` (lines
346–399). This is the exact `add_job(...)` shape and the stable id the reconcile keys on:
```python
scheduler.add_job(
    fire_slot,
    trigger=CronTrigger(hour=hh, minute=mm, day_of_week=slot.day_of_week,
                        timezone=location.timezone),
    kwargs={"holder": holder, "db_path": db_path, "settings": settings,
            "client": client, "channel": channel, "stop_event": stop_event},
    args=[location, slot],
    id=f"{location.name}|{slot.time}|{slot.days}",   # ← the stable reconcile key
    misfire_grace_time=None,
    coalesce=True,
)
```
**Diff-reconcile mechanics (RESEARCH Pattern 4, verified APScheduler 3.11.2):** compute desired
ids from the new config; `scheduler.get_jobs()` gives live ids (exclude `"__heartbeat__"` — see
run_daemon line 634); `add_job(..., replace_existing=True)` for present/changed (no-op if
identical → satisfies the idempotent-reload SC#3), `remove_job(id)` for deleted/disabled. NEVER
`remove_all_jobs()`. A `time`/`days` edit yields a NEW id (one add + one remove); a pure content
edit (units/lat/lon/template/name) is `=unchanged` job-wise and takes effect purely via the
holder swap (Phase-8 per-fire `holder.current()` read).

**Two-phase build-then-commit + rollback (RESEARCH Pattern 3 / Pitfall 6/7):** the reload engine
calls `validate_config_and_templates(config_path)` first (Phase 1, no live mutation → on any raise,
log reason + return, KEEP OLD); then snapshots `old_cfg = holder.current()` and
`old_jobs = {j.id: j for j in scheduler.get_jobs() if j.id != "__heartbeat__"}`, calls
`holder.replace(new_cfg)`, reconciles, and on any reconcile exception restores via
`holder.replace(old_cfg)` + rebuild-from-`old_cfg` (rerun `_register_jobs` against the old config —
deterministic, reuses existing code). The outcome log (CFG-06/D-07) uses the daemon's structlog
`_log` (see `_log.info("daemon started", jobs=...)`, line 686) with `+a −r ~c =u` counts.

---

### `weatherbot/scheduler/daemon.py` — `run_daemon` SIGHUP handler + poll loop + PID file (service, lifecycle)

**Analog:** the existing SIGTERM install + park + clean-shutdown in the SAME function
(`run_daemon`, lines 605–700). Mirror it exactly:

**Existing signal-install idiom** (lines 648–657) — install BEFORE `scheduler.start()` (the
"LOAD-BEARING ORDERING" comment at 651 explains why):
```python
def _handle(signum, frame):  # noqa: ANN001 — signal handler signature
    stop.set()

signal.signal(signal.SIGTERM, _handle)   # installed before the gate / start()
```
Add a sibling `reload_requested = threading.Event()` and
`def _handle_hup(signum, frame): reload_requested.set()` then
`signal.signal(signal.SIGHUP, _handle_hup)` — the handler does ONLY the cheap `.set()`, takes NO
lock (re-entrancy/deadlock anti-pattern, RESEARCH).

**Existing park to REPLACE** (line 688) — the single `stop.wait()` must become a poll loop so the
SIGHUP-set flag is actually serviced (Pitfall 6):
```python
stop.wait()   # ← replace this single park
```
becomes the poll loop (RESEARCH Code Example); `stop.is_set()` is still checked first so SIGTERM
wins. `run_daemon` must also gain a `config_path=` parameter (today it receives a pre-loaded
`config`, not a path — the reload engine needs the PATH to re-read from disk); thread it from the
`cli.py` `run` dispatch (line 639: `daemon.run_daemon(config=config, settings=settings, db_path=db_path)`
→ add `config_path=args.config`).

**Existing clean-shutdown hook for the PID unlink** — the `finally` block (lines 691–699):
```python
finally:
    if getattr(scheduler, "running", True):
        scheduler.shutdown(wait=False)
    _log.info("daemon stopped")
```
Write the PID atomically near startup (after channel build, before/around `scheduler.start()`) and
`PID_FILE.unlink(missing_ok=True)` inside this existing `finally` — the same place the scheduler is
torn down.

---

### `weatherbot/scheduler/daemon.py::fire_slot` + `catchup.py` — exactly-once key → `location.id` (CRUD, lockstep)

**THE lockstep edit (Pitfall 2 — FOUR store calls, two files).** All must switch from
`location.name` / `loc.name` to `location.id` / `loc.id` TOGETHER. The store function signatures
do NOT change (param stays `location_name`); only the argument value changes.

`daemon.py::fire_slot` callsites (verified line numbers):
```python
168:  if not claim_slot(db_path, location.name, slot.time, local_date):     # → location.id
224:  release_claim(db_path, location.name, slot.time, local_date)          # → location.id
230:  self_first = record_alert(db_path, location.name, slot.time, local_date, reason)   # → location.id
246:  release_claim(db_path, location.name, slot.time, local_date)          # → location.id
248:  self_first = record_alert(db_path, location.name, slot.time, local_date, REASON_TRANSIENT_EXHAUSTED)  # → location.id
269:  release_claim(db_path, location.name, slot.time, local_date)          # → location.id
271:  self_first = record_alert(db_path, location.name, slot.time, local_date, REASON_TRANSIENT_EXHAUSTED)  # → location.id
290:  resolve_alert(db_path, location.name, slot.time, local_date)          # → location.id
```
> Note: the `_log.info(..., location=location.name, ...)` LOG fields (e.g. lines 171, 234, 293)
> stay `location.name` (human-readable display) — only the **store key argument** moves to `id`.

`catchup.py::plan_catchup` callsite (line 170):
```python
170:  if was_sent(loc.name, slot.time, local_date):  # already delivered (D-06)  → loc.id
```
The `was_sent` reader is injected into `plan_catchup` as a `Callable[[str, str, str], bool]`
(signature, line 103), wired in `daemon.py::_run_catchup` (line 464) as
`lambda name, time, date: was_sent(db_path, name, time, date)` — the `name` arg now receives
`loc.id`. Change line 170 (`was_sent(loc.name, ...)` → `was_sent(loc.id, ...)`); the lambda is
value-agnostic so it needs no change. **`claim_slot`/`release_claim`/`record_alert`/`resolve_alert`
(daemon) and `was_sent` (catchup) must move in the SAME change** or a claim taken under `id` is
released/checked under `name` (orphaned claims / duplicate alerts).

---

### `weatherbot/cli.py` — `reload` + `check-config` subcommands (controller, request-response)

**Analog — subparser grammar:** `cli.py::main` subparser block (lines 534–587). The new
subcommands are siblings of `run`/`check`/`send-now`:
```python
subparsers.add_parser("check", parents=[config_parent],
    help="Validate config + template + one reachability probe without sending.")
```
- `check-config`: `subparsers.add_parser("check-config", parents=[config_parent], help="Validate config + templates OFFLINE (no network); apply/send nothing (CFG-08).")`
- `reload`: a new subparser (config path optional — it only needs the PID file, not the config);
  may omit `config_parent` since it loads no config.

**Analog — dispatch:** the `if args.command == ...` ladder (lines 605–658). `check`'s branch
(618–623) is the template for `check-config`, but call the OFFLINE validator, NOT `do_check`
(Pitfall 8 — `do_check`/`run_self_check` makes a LIVE OpenWeather probe):
```python
# existing `check` dispatch (lines 618–623) — DO NOT reuse for check-config:
if args.command == "check":
    config = _load_config_reporting(args.config)
    if config is None:
        return 1
    settings = load_settings()
    return do_check(config=config, settings=settings)   # ← run_self_check → network
```
`check-config` instead (RESEARCH Code Example):
```python
if args.command == "check-config":
    try:
        validate_config_and_templates(args.config)
    except (FileNotFoundError, tomllib.TOMLDecodeError, ValidationError, ValueError) as exc:
        _log.error("check-config failed", error=str(exc))
        return 1
    _log.info("check-config passed")
    return 0
```
> `cli.py` already imports `tomllib`, `ValidationError`, and uses the module `_log` (see
> `_load_config_reporting`, 460–478) — the catch set and logger are already in scope.

**Analog — `do_reload` exit-code shape:** `do_check`/`do_geocode` return `int` (0 ok / 1 fail) and
log outcome-only via `_log` (do_check, 393–457). `do_reload` follows the same return-int +
outcome-log contract.

---

### PID-file helper — atomic write + `/proc/<pid>/cmdline` guard (utility, file-I/O)

**Analog — ops-helper posture:** `weatherbot/ops/sdnotify.py` (whole file). It is the established
pattern for a stdlib-only, never-raise-on-transport-error OS-adjacent helper: reads an env/OS fact
once, swallows `OSError` so the daemon can't crash on it. The PID helper lives either in `cli.py`
(sender `do_reload`) + `run_daemon` (writer), or a new `weatherbot/ops/pidfile.py` mirroring
`sdnotify.py`'s module shape.

**Analog — atomic-write posture:** `store.py` uses `INSERT OR IGNORE`/parameterized writes for
"never a partial/torn record"; the PID file uses the stdlib equivalent — write a temp file then
`os.replace(tmp, pidfile)` (atomic on POSIX), per RESEARCH "Don't Hand-Roll" (no `python-pidfile`
dependency). The `/proc/<pid>/cmdline` staleness guard (read bytes, check `b"weatherbot" in
cmdline` before `os.kill(pid, signal.SIGHUP)`) is the D-03 PID-recycling defense — see RESEARCH
Code Examples for the verified `do_reload` sender body.

> **Open question for the planner (RESEARCH A2/Open-Q2):** PID-file PATH. Default
> `/run/weatherbot.pid`; if the service user lacks `/run` write access, prefer systemd
> `RuntimeDirectory=weatherbot` or a config-relative fallback. Make the path a module constant /
> optional override (mirrors `store.py::DEFAULT_DB_PATH` and `renderer.py::TEMPLATES_DIR`).

## Shared Patterns

### Exactly-once key — `id` defaults to the RAW name (zero-migration)
**Source decision:** RESEARCH Pitfall 1 (A1) resolves the CONTEXT D-01 internal contradiction.
**Apply to:** `models.py` (`Location._default_id_from_name`) and BOTH callsite files.
The sent-log/alerts rows store `location.name` RAW today (store.py 207, 276, etc.). For the new
`id`-keyed read/write to be **byte-identical** to existing rows (D-01's literal "zero migration"
promise), `id` must default to the **RAW `name`**, NOT `casefold(name)`. Casefolding is used ONLY
in the uniqueness check (mirroring `assert_unique_names`'s existing `key = loc.name.casefold()`),
never in the stored key value. **The store column `_SCHEMA` is untouched (Pitfall 3).**

### Fail-loud-at-load validation (raise → caller decides)
**Source:** `loader.py::load_config`/`assert_unique_names`, `models.py` field/model validators,
`renderer.py::validate_template` — all raise `ValueError`/`ValidationError`/`TOMLDecodeError`.
**Apply to:** `validate_config_and_templates` (raises; reload catches → keep-old; check-config
catches → exit 1). The single catch set everywhere:
`(FileNotFoundError, tomllib.TOMLDecodeError, pydantic.ValidationError, ValueError)` — already the
exact set in `cli.py::_load_config_reporting` (460–478).

### Signal handler = flag-set only; act on the main loop
**Source:** `daemon.py::run_daemon` `_handle` (648–649) sets `stop` only; the loop acts.
**Apply to:** the new `_handle_hup` (set `reload_requested` only) + the poll loop replacing
`stop.wait()`. Install SIGHUP with the same `signal.signal(...)` call placed BEFORE
`scheduler.start()` (same ordering rationale as the SIGTERM comment at 651).

### Lock-guarded swap stays dumb; validate in front
**Source:** `holder.py::replace` (59–66) — documents it does NOT check (Phase-9 territory).
**Apply to:** the reload engine calls `validate_config_and_templates` BEFORE `holder.replace`;
never add validation inside `replace()`.

### Outcome-only structured logging (never secrets)
**Source:** `daemon.py` `_log.info/critical(...)` with field kwargs; `sdnotify`/`store` carry only
counts/ids/reasons (T-04-01).
**Apply to:** CFG-06 reload outcome (`+a −r ~c =u` / rejection reason) and `check-config` pass/fail
— counts, location ids, and reasons only; never the key or webhook URL.

### Lazy in-function imports to avoid the cli↔daemon cycle
**Source:** `daemon.py::fire_slot` `from weatherbot.cli import send_now` (181), `run_daemon`
`from weatherbot.channels import build_channel` (601), `cli.py::main` `from weatherbot.scheduler
import daemon` (637).
**Apply to:** any new cross-module reach (e.g. `cli.py` importing the reload engine, or the engine
importing `validate_config_and_templates`) — follow the established lazy-import-at-callsite idiom
where a top-level import would cycle.

## No Analog Found

None. Every new/modified unit has a strong in-repo analog (see table). The genuinely-new logic
(two-phase commit orchestration, diff-reconcile loop, SIGHUP→main-loop handoff, PID-file sender) is
small composition over existing primitives — RESEARCH confirms no new dependency and no Jinja2.

## Metadata

**Analog search scope:** `weatherbot/config/` (holder, models, loader, settings), `weatherbot/
scheduler/` (daemon, catchup), `weatherbot/weather/store.py`, `weatherbot/cli.py`,
`weatherbot/ops/` (sdnotify, selfcheck), `templates/renderer.py`.
**Files scanned:** 9 source files read in full or by targeted range.
**Pattern extraction date:** 2026-06-15
