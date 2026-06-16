---
phase: 10
slug: file-watch-auto-reload
status: secured
threats_open: 0
threats_closed: 10
asvs_level: 1
block_on: high
register_authored_at_plan_time: true
created: 2026-06-16
---

# Phase 10 — file-watch-auto-reload: Security Verification

**Phase:** 10 — file-watch-auto-reload
**ASVS Level:** 1
**block_on:** high
**Audited:** 2026-06-16
**Register authored at:** plan time (verification-only audit — no new-threat scan)
**Result:** SECURED — 10/10 threats CLOSED, 0 open

The threat register was authored at PLAN time; this audit verifies each declared
mitigation exists in the SHIPPED implementation. Code-review findings CR-01 (live
re-watch dead code) and WR-01 (recursive watch + basename collision) were resolved
before audit; the SHIPPED state (verified below) carries both fixes.

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence (shipped) |
|-----------|----------|-------------|--------|--------------------|
| T-10-01 | Tampering / DoS (half-written file parsed mid-save) | mitigate | CLOSED | `watch(step=WATCH_QUIET_MS=400, debounce=WATCH_DEBOUNCE_MS=1600, ...)` coalesces a save-storm into one settled yield — daemon.py:910-918, constants daemon.py:119-121. Phase-9 keep-old rejects any partial read (inherited, see T-10-08). Asserted: `tests/test_filewatch.py::test_editor_save_patterns_one_reload` (truncate-write / temp-then-rename / multi-event burst each → exactly ONE reload, line 268). |
| T-10-02 | Information disclosure (.env hot-reloaded) | mitigate | CLOSED | `_make_watch_filter` basename allow-list = `{config.toml} ∪ {referenced templates}`; `.env` never matches → `_watch_filter` returns False (daemon.py:858-866). `recursive=False` (daemon.py:918) narrows surface so a basename-colliding file in a subdir cannot trigger (WR-01 fix). Asserted: `test_env_save_never_reloads` (ZERO reloads, line 514-515) and `test_subdir_basename_collision_no_reload` (line 651-652). |
| T-10-03 | Tampering (unknown [reload] key) | mitigate | CLOSED | `ReloadConfig.model_config = ConfigDict(extra="forbid", frozen=True)` — models.py:243. An unknown `[reload]` key raises pydantic ValidationError at load. |
| T-10-04 | Tampering (secrets in [reload] toggle) | accept | CLOSED | `ReloadConfig` carries ONLY `watch: bool = True` (models.py:245); no secret field. Accepted-risk rationale (secrets stay in `.env`, restart boundary) holds in shipped code. |
| T-10-05 | DoS / resource (inotify-fd leak over uptime) | mitigate | CLOSED | ONE long-lived observer thread `weatherbot-filewatch` started in `run_daemon` (daemon.py:1091-1098, single `threading.Thread` construction), joined in the EXISTING `finally` with `stop.set(); watch_thread.join(timeout=2.0)` + is-alive warning (daemon.py:1186-1194, WR-04 fix). D-04 re-derive mutates only the shared cell; the single `watch()` generator re-enters on a watch-set change, releasing old fds on exhaustion (daemon.py:899-932, CR-01 fix). Asserted: `test_fd_stable_and_clean_teardown` (fd delta ≤ FD_SLACK over >=50 inode-swapping saves incl. a watch-set swap; clean join, `is_alive()` False — lines 322, 326). |
| T-10-06 | DoS (reload loop from write-back) | mitigate | CLOSED | Reload writes NOTHING to config/template dirs — grep for `.write_text`/`.write_bytes`/`os.replace`/`.bak`/`open(...,"w")` in daemon.py returns only the PID-file write (to `/run`, outside watched dirs). `_do_reload` is read-only against the config path (daemon.py:549-657). Config-read-only posture confirmed in shipped code. |
| T-10-07 | Tampering / DoS (re-entrant reload on observer thread) | mitigate | CLOSED | Observer is FLAG-SET ONLY: `request_reload` does `reload_requested.set()` only (daemon.py:1083-1089); `_run_watch_observer` calls `request_reload()` and never `_do_reload` (daemon.py:922-923; zero `_do_reload` in observer body). `_do_reload` runs only on the MAIN poll-loop thread (daemon.py:1152-1163). |
| T-10-08 | Elevation / Tampering (malformed save crashes daemon) | mitigate | CLOSED | Inherited Phase-9 keep-old: the poll-loop `except Exception` swallows a bad reload and leaves the live schedule intact (daemon.py:1164-1169). Asserted: `test_invalid_save_keeps_old_config` — real `_do_reload`/`holder`, `holder.current() is old` after an invalid save (line 386). |
| T-10-09 | Tampering, low/local (symlinked watched dir) | accept | CLOSED | `_derive_watch_dirs` resolves only operator-controlled `Path(config_path).resolve().parent` and `TEMPLATES_DIR` (daemon.py:841-844); no new external/network input. Single-user local-tool accepted-risk rationale holds in shipped code. |
| T-10-SC | Tampering, supply chain (uv add watchfiles) | mitigate | CLOSED | Blocking human-verify checkpoint (10-02-PLAN.md:65-75) verified watchfiles on pypi.org (author samuelcolvin, version 1.2.0, source github.com/samuelcolvin/watchfiles, non-typosquat) BEFORE install. Pinned `watchfiles>=1.2.0` in pyproject.toml:14; uv.lock resolves `watchfiles==1.2.0` from the pypi.org registry (uv.lock:526-528, 642). |

## Accepted Risks Log

- **T-10-04** (secrets leaking into the `[reload]` toggle) — ACCEPTED. `ReloadConfig`
  carries only `watch: bool`; no secret field. Secrets remain in `.env` behind a
  restart boundary (Pitfall #12). Rationale verified intact in models.py:230-245.
- **T-10-09** (symlinked watched dir pointing outside the project) — ACCEPTED.
  Single-user local tool; `_derive_watch_dirs` uses only operator-controlled paths,
  adds no external input surface. Rationale verified intact in daemon.py:823-844.

## Unregistered Flags

None. No `## Threat Flags` section appears in any Phase-10 SUMMARY
(10-01/10-02/10-03). No new attack surface emerged during implementation without a
mapped threat ID. (The code-review surfaced behavioral defects CR-01/WR-01/WR-04,
all of which map to existing threats T-10-05/T-10-02 and were resolved before this
audit — they are not new attack surface.)

## Audit Method Notes

- Implementation files were treated READ-ONLY; only this SECURITY.md was written.
- Each `mitigate` threat was grep-verified against the cited file:line in the SHIPPED
  daemon.py / models.py / pyproject.toml, not against intent or documentation.
- Each `accept` threat's rationale was re-confirmed against the shipped code.
- Grounding run: `uv run pytest tests/test_filewatch.py tests/test_reload.py
  tests/test_models.py` → 57 passed. The tests cited as evidence execute green in the
  shipped tree.
