# Phase 24 — SEAM-04 Config Hot-Reload Engine — Autonomous Self-UAT Log (Gate 1)

**Requirement:** SEAM-04
**Phase:** 24-config-hot-reload-engine
**Plan:** 24-03 (autonomous Gate-1 self-UAT)
**Gate:** Gate 1 — autonomous agent self-UAT (per CLAUDE.md Two-Gate UAT policy)
**Driven:** 2026-06-28
**Git anchors:** HEAD `b66d38c` (Wave-2 wiring) vs pre-Phase-24 baseline `3567e48`
**Environment:** local dev tree, `uv run pytest`, Python 3.12, stable ordering (`-p no:randomly`)

> **Policy framing.** This is the autonomous Gate-1 self-UAT. Per the project's Two-Gate UAT
> policy, the five real reload paths are **driven** with recorded command + output evidence
> (not inferred from code), and the byte-level golden + DB-row oracles are shown byte-identical
> to the pre-Phase-24 baseline. A fully-passing Gate 1 is sufficient to complete the phase and
> proceed automatically — **no per-phase human pause**. Human UAT (the live `yahir-mint`
> `systemctl restart`) is a **deferred Gate-2 milestone obligation** (Phase 28 / PKG-02),
> tracked below, NOT a per-phase blocker.

---

## Suite-green datapoint (the necessary-but-not-sufficient floor)

```
$ uv run pytest -p no:randomly
... 762 passed, 1 warning in 34.95s
--------------------------- snapshot report summary ----------------------------
2 snapshots failed. 27 snapshots passed.
```

- **762 passed, 0 hard failures** under stable ordering.
- The `2 snapshots failed.` tally is **PRE-EXISTING and not this phase's** — it is identical at
  the pre-Phase-24 baseline `3567e48` (verified in Wave-1 `24-01-SUMMARY.md` §Issues and Wave-2
  `24-02-SUMMARY.md` §Issues, both in a throwaway worktree). It is a whole-suite syrupy
  session-reporting artifact (no `FAILED` test node); the four golden files pass byte-identical
  in isolation at BOTH refs (see Criterion 1 evidence). A 1-test env-ordering flake
  (`test_load_settings_no_env_file_uses_default`) likewise pre-exists on `main` and passes under
  stable ordering — recorded as a known pre-existing item, **not chased here**.
- Plan named selection (engine + reload + filewatch + holder + hygiene):
  `uv run pytest tests/test_reload.py tests/test_filewatch.py tests/test_reload_engine.py tests/test_config_holder.py tests/test_import_hygiene.py -p no:randomly -q` → **60 passed**.

**Holder/engine identity (the seam is live, not a parallel copy):**
```
$ uv run python -c "import weatherbot.config.holder as h, yahir_reusable_bot.config as m; print(h.ConfigHolder is m.ConfigHolder)"
weatherbot.config.holder.ConfigHolder IS yahir_reusable_bot.config.ConfigHolder: True
daemon imports module ReloadEngine: True
```
The daemon drives the **module** `ReloadEngine` / `ConfigHolder` (identical objects), so every
path below exercises the extracted seam, not a shim leftover.

---

## The five reload paths (each driven, with recorded output)

### Path 1 — SIGHUP reload + reconcile-diff `+a -r ~c =u`

```
$ uv run pytest -p no:randomly -v \
    tests/test_reload.py::test_sighup_triggers_reload \
    tests/test_reload.py::test_reconcile_diff \
    tests/test_reload.py::test_identical_reload_zero_changes \
    tests/test_reload.py::test_reload_logs_diff_summary \
    tests/test_reload_engine.py::test_request_reload_then_service_pending_runs_reload_once \
    tests/test_reload_engine.py::test_reload_excluded_id_never_removed_even_when_not_desired
test_sighup_triggers_reload PASSED
test_reconcile_diff PASSED
test_identical_reload_zero_changes PASSED
test_reload_logs_diff_summary PASSED
test_request_reload_then_service_pending_runs_reload_once PASSED
test_reload_excluded_id_never_removed_even_when_not_desired PASSED
6 passed in 0.21s
```

**Byte-level proof (from `test_reconcile_diff`, tests/test_reload.py L328-362):** old job set
`{Home|07:00|mon-fri, Home|12:00|daily}` → after reload `{Home|08:00|mon-fri, Home|18:00|daily}`:
- `+a` ADD: `Home|08:00|mon-fri` (time-changed → new id), `Home|18:00|daily` (added)
- `-r` REMOVE: `Home|07:00|mon-fri` (old id), `Home|12:00|daily` (disabled)
- `~c` CHANGE expressed as the +1/-1 id pair (no `remove_all_jobs()` churn)
- `=u` UNCHANGED ride the holder swap; `__heartbeat__` / `__uvmonitor__` are **never in the
  asserted set** (no extra `-2`) — proven by `test_reload_excluded_id_never_removed_even_when_not_desired`
  driving the injected `excluded_ids` frozenset.
- SIGHUP mechanism: `test_sighup_triggers_reload` installs the handler and confirms it flips the
  engine's reload flag (`request_reload()` → `service_pending()` runs exactly one reload).

### Path 2 — File-watch reload (observer thread)

```
$ uv run pytest -p no:randomly -v \
    tests/test_filewatch.py::test_save_triggers_reload \
    tests/test_filewatch.py::test_editor_save_patterns_one_reload \
    tests/test_filewatch.py::test_env_save_never_reloads \
    tests/test_filewatch.py::test_invalid_save_keeps_old_config \
    tests/test_filewatch.py::test_watch_set_rederived_on_reload \
    tests/test_filewatch.py::test_live_observer_picks_up_rederived_dir \
    tests/test_filewatch.py::test_fd_stable_and_clean_teardown
test_save_triggers_reload PASSED
test_editor_save_patterns_one_reload PASSED
test_env_save_never_reloads PASSED
test_invalid_save_keeps_old_config PASSED
test_watch_set_rederived_on_reload PASSED
test_live_observer_picks_up_rederived_dir PASSED
test_fd_stable_and_clean_teardown PASSED
7 passed in 13.03s
```

Drives the real engine-owned watchfiles observer: config save → **one** reload; editor
save-patterns (atomic-rename/temp) coalesce to one; `.env` save → **zero** reloads (secret-file
filter); keep-old-through-watch (invalid save leaves old live); watch-set **re-derived** on
reload and the **live** observer picks up the re-derived dir; FDs stable + clean teardown
(`stop()`/join). 13s wall time = real observer threads, not mocks.

### Path 3 — `check-config` dry-run (validate-only, no swap)

```
$ uv run pytest -p no:randomly -v \
    tests/test_reload.py::test_check_config_and_reload_share_validation \
    tests/test_reload_engine.py::test_check_is_validate_only
test_check_config_and_reload_share_validation PASSED
test_check_is_validate_only PASSED
2 passed in 0.20s
```

**Drove the REAL `weatherbot check` CLI** (not just the unit test):
```
$ uv run weatherbot check --config config.example.toml
2026-06-27 23:37:41 [info     ] config check passed            locations=2
VALID exit=0

$ printf 'this is = not = valid toml\n' > $BAD; uv run weatherbot check --config $BAD
2026-06-27 23:37:42 [error    ] config TOML syntax error  error="Expected '=' ..." path=...
INVALID exit=1
```
Valid → `config check passed locations=2`, exit **0**. Invalid → `config TOML syntax error`,
exit **1**. `engine.check(path)` runs the injected `validate` only — no swap, no reconcile, no
scheduler touch (`test_check_is_validate_only`).

### Path 4 — Bad-edit keep-old (holder + jobs untouched, reject post BEFORE re-raise)

```
$ uv run pytest -p no:randomly -v \
    tests/test_reload.py::test_invalid_reload_keeps_old \
    tests/test_reload.py::test_rejected_reload_logs_reason \
    tests/test_reload.py::test_cfg07_rejection_posts_reason \
    tests/test_reload_engine.py::test_reload_keeps_old_on_validator_raise_and_posts_rejected_first \
    tests/test_reload_engine.py::test_on_rejected_raise_is_swallowed_original_error_still_raised
test_invalid_reload_keeps_old[bad_toml] PASSED
test_invalid_reload_keeps_old[duplicate_name] PASSED
test_invalid_reload_keeps_old[duplicate_id] PASSED
test_invalid_reload_keeps_old[unknown_template_token] PASSED
test_rejected_reload_logs_reason PASSED
test_cfg07_rejection_posts_reason PASSED
test_reload_keeps_old_on_validator_raise_and_posts_rejected_first PASSED
test_on_rejected_raise_is_swallowed_original_error_still_raised PASSED
8 passed in 0.26s
```

Four malformed-config kinds (bad TOML / dup name / dup id / unknown template token) each →
validate-raise leaves `holder.current()` + the job set **unchanged** (keep-old). The CFG-07
`⛔ config reload rejected` post fires **before** the re-raise
(`test_reload_keeps_old_on_validator_raise_and_posts_rejected_first` asserts post-then-raise
ordering); a raising `on_rejected` hook is swallowed and the **original** error still propagates
(daemon does not crash — the DoS mitigation T-24-10 / D-08 / SC-3, driven end-to-end).

### Path 5 — Reconcile-failure rollback (all-or-nothing)

```
$ uv run pytest -p no:randomly -v \
    tests/test_reload.py::test_reconcile_failure_rolls_back \
    tests/test_reload_engine.py::test_reload_reconcile_throw_rolls_back_and_reraises \
    tests/test_reload_engine.py::test_reload_restore_raise_is_swallowed_and_does_not_mask_cause
test_reconcile_failure_rolls_back PASSED
test_reload_reconcile_throw_rolls_back_and_reraises PASSED
test_reload_restore_raise_is_swallowed_and_does_not_mask_cause PASSED
3 passed in 0.20s
```

A forced reconcile throw rolls **both** holder and jobs back to the old set (all-or-nothing) and
re-raises the original error; a raising restore step is swallowed and does **not** mask the
original cause. Combined with the byte-identical `sent_log` DB-row golden (below) this proves the
half-applies-nothing contract at the data level.

---

## Byte-level golden / DB-row oracle (prove the value, don't infer it)

```
$ uv run pytest -p no:randomly -v \
    tests/test_golden_db.py::test_sent_log_rows_golden \
    tests/test_golden_schedule.py \
    tests/test_reload.py::test_already_sent_slot_not_refired_after_tz_name_change \
    tests/test_reload.py::test_send_time_change_is_new_slot_fires_today_if_ahead
test_sent_log_rows_golden PASSED
test_schedule_plan_golden PASSED
test_already_sent_slot_not_refired_after_tz_name_change PASSED
test_send_time_change_is_new_slot_fires_today_if_ahead PASSED
--------------------------- snapshot report summary ----------------------------
2 snapshots passed.
4 passed in 0.70s
```

- **`sent_log` DB-row golden** byte-identical (snapshot passed) — read straight from the SQLite
  `sent_log` table (`tests/test_golden_db.py` `_sent_log_rows_golden`, explicit `ORDER BY`, rowid
  scrubbed, clock frozen). Data-level, not code-inferred.
- **schedule-plan golden** byte-identical (`(job_id, trigger spec, next_run_time)`).
- **exactly-once-across-reload:** `test_already_sent_slot_not_refired_after_tz_name_change`
  (seeds a real `sent_log` row, reloads through a tz/name change, asserts no re-fire) +
  `test_send_time_change_is_new_slot_fires_today_if_ahead` (new id fires today if ahead).
- **keep-old-rollback golden** covered by Path 4/5 above (the reconcile-diff + keep-old + rollback
  tests are the Phase-21 reload oracles).

**Baseline byte-identical anchor (auditable):**
```
$ git worktree add --detach $WT 3567e48
$ (cd $WT && uv run pytest -p no:randomly tests/test_golden_db.py tests/test_golden_schedule.py \
      tests/test_golden_embeds.py tests/test_golden_custom_ids.py)
16 snapshots passed.  / 17 passed
```
The four golden files pass **16 snapshots / 17 tests** at the pre-Phase-24 baseline `3567e48` AND
identically on HEAD `b66d38c` — **zero NEW diff** introduced by the extraction. No golden was
`--snapshot-update`'d.

---

## SEAM-04 success criteria — per-criterion verdict (ROADMAP L322-327)

### Criterion 1 — Reload drives validate→swap→reconcile + watch + SIGHUP + check-config through injected callables; Phase-21 goldens + reconcile-diff / keep-old / exactly-once-across-reload stay green (byte-identical)

- **Tested:** all five reload paths (above) + committed-success side effects (CFG-07 applied post,
  CR-01 cache invalidation, D-04 watch re-derive) + the reconcile-diff / keep-old / exactly-once /
  schedule / sent_log goldens.
- **Commands:** Path 1-5 selections + golden block above, plus:
  ```
  $ uv run pytest -p no:randomly -v \
      tests/test_reload.py::test_cfg07_success_posts_summary \
      tests/test_reload.py::test_cfg07_channel_send_failure_does_not_abort_reload \
      tests/test_reload.py::test_reload_invalidates_forecast_cache_so_next_lookup_refetches \
      tests/test_reload.py::test_reload_applies_new_schedule \
      tests/test_reload_engine.py::test_on_applied_raise_is_swallowed_reload_still_succeeds
  5 passed in 0.41s
  ```
- **Evidence:** all green; goldens byte-identical (2 snapshots passed in isolation, zero diff vs
  baseline `3567e48`); `on_applied` fires the applied post + cache-invalidate only on a committed
  swap and is best-effort (a raising hook is swallowed, reload still succeeds).
- **Verdict:** **PASS**

### Criterion 2 — Module config seam knows no app field names; validation goes through the app validator callable (subclass fields never dropped); litmus grep clean

- **Tested:** import-hygiene + litmus + pydantic-isolation gates; manual litmus grep over the seam.
- **Commands:**
  ```
  $ uv run pytest -p no:randomly -v tests/test_import_hygiene.py    → 9 passed
  $ grep -nE 'Location|send_time|local_date|forecast|UvConfig|\[uv\]|weather' \
       yahir_reusable_bot/config/holder.py yahir_reusable_bot/config/reload.py
    CLEAN: no weather noun in module config seam
  $ grep -nE 'import pydantic|from pydantic' yahir_reusable_bot/config/*.py
    CLEAN: module config seam never imports pydantic
  ```
- **Evidence:** `test_module_imports_zero_app_code`, `test_config_module_never_imports_pydantic`,
  `test_litmus_clean` (+ 6 self-proof gates) all green; litmus + pydantic greps both empty.
  Validation routes through the injected `validate_config_and_templates(path) → Config`
  (concrete-class, `extra="forbid"`, all `locations`/`[uv]` subfields preserved — D-03); the
  module never calls pydantic, so the subclass-field-drop pitfall cannot occur. Holder identity
  check confirms the daemon drives the module seam.
- **Verdict:** **PASS**

### Criterion 3 — A bad config edit half-applies nothing: validate-raise keeps old, reconcile-fail rolls back all-or-nothing

- **Tested:** Path 4 (validate-raise keep-old, 4 malformed kinds + reject-before-raise) and Path 5
  (reconcile-throw all-or-nothing rollback + restore-swallow), plus the byte-identical `sent_log`
  DB-row golden proving no half-applied data.
- **Commands:** Path 4 (8 passed) + Path 5 (3 passed) selections above.
- **Evidence:** holder + job set unchanged on validate-raise; both rolled back on reconcile-throw;
  original error re-raised in both; daemon does not crash; `sent_log` rows byte-identical.
- **Verdict:** **PASS**

### Criterion 4 — `[uv]` / `Location` / templates + restart-policy stay entirely app-side; no weather schema or restart-policy list in the module holder

- **Tested:** same litmus + pydantic-isolation gates as Criterion 2, focused on the holder.
- **Commands:** `tests/test_import_hygiene.py` (9 passed) + the two greps (both CLEAN).
- **Evidence:** the module `ConfigHolder[T]` is an unbound-`TypeVar` storage cell — no `Config` /
  `Location` / `UvConfig` / `[uv]` / template / restart-key list anywhere in
  `yahir_reusable_bot/config/`. The `{__heartbeat__, __uvmonitor__}` exclusion and the
  restart-boundary policy stay app-side (injected `excluded_ids` frozenset; restart-key policy
  never enters the holder). Grep confirms zero weather noun in the seam.
- **Verdict:** **PASS**

---

## Deferred Gate-2 obligations (NOT skipped — mechanism + result verified, only the physical step deferred)

| Item | Mechanism verified | Result verified | Physical step deferred | Verdict |
|------|--------------------|-----------------|------------------------|---------|
| Live `yahir-mint` `sudo systemctl restart weatherbot` + edit-config/SIGHUP/save against the **running daemon** | The SIGHUP handler, file-watch observer, `check-config`, keep-old, and reconcile-rollback mechanisms are each driven here (Paths 1-5) and confirmed in source (`run_daemon` wires the module `ReloadEngine`; daemon imports the module objects — identity check) | The reload reconcile-diff, keep-old, exactly-once-across-reload, schedule, and `sent_log` goldens are byte-identical; `weatherbot check` driven live (exit 0/1) | Only the host `systemctl restart` + on-host live-edit smoke is deferred — that touches the live production daemon and is **Phase 28 / PKG-02** | **PARTIAL** (deferred to Gate-2 milestone close, per CLAUDE.md; NOT a per-phase blocker) |

**Pre-existing items recorded (not this phase's, not chased):**
- Whole-suite `2 snapshots failed.` syrupy session artifact — identical at baseline `3567e48`;
  the golden files pass byte-identical in isolation at both refs.
- `test_load_settings_no_env_file_uses_default` 1-test env-ordering flake — pre-exists on `main`,
  passes under stable ordering.

---

## Overall Gate-1 verdict

**PASS.** All four SEAM-04 success criteria PASS with driven command + output evidence. All five
reload paths (SIGHUP, file-watch, check-config dry-run, bad-edit keep-old, reconcile-rollback) were
exercised against the wired module `ReloadEngine` / `ConfigHolder[T]`, and the reconcile-diff
`+a -r ~c =u`, keep-old-rollback, exactly-once-across-reload, schedule-plan, and `sent_log` DB-row
goldens are byte-identical to the pre-Phase-24 baseline `3567e48` (zero new diff; no golden
blind-updated). Suite 762 passed / 0 hard failures.

Gate 1 is **discharged** — the phase completes and proceeds automatically with no per-phase human
pause. The single deferred Gate-2 obligation (the live `yahir-mint` `systemctl restart` UAT) is
verdict PARTIAL (mechanism + result verified; only the physical host step deferred) and is batched
to the **v2.0 milestone close — Phase 28 / PKG-02**, NOT a per-phase blocker.

---
*Phase: 24-config-hot-reload-engine — Plan 24-03 — Gate-1 autonomous self-UAT*
*Driven: 2026-06-28*
