# Phase 10: File-Watch Auto-Reload - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-16
**Phase:** 10-File-Watch Auto-Reload
**Areas discussed:** Watcher library, Funnel mechanism, Enable/default + toggle, Watch scope, Debounce timing

---

## Watcher library

| Option | Description | Selected |
|--------|-------------|----------|
| watchfiles | Roadmap's pick. Built-in debounce (debounce/step); Rust 'notify' backend; tiny watch()/awatch() API; directory-watch + inode-swap handled natively. Adds one dep. | ✓ |
| watchdog | PITFALLS.md's 'mature watcher' pick. Battle-tested but Observer+FileSystemEventHandler boilerplate; hand-rolled debounce; contradicts roadmap. | |

**User's choice:** watchfiles
**Notes:** Resolves the ROADMAP-vs-PITFALLS.md conflict in favor of the roadmap's explicit wording. Built-in debounce was the deciding factor (no hand-rolled save-storm logic).

---

## Funnel mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Set reload_requested Event | Watcher thread (post-debounce) calls request_reload() closure that .set()s the existing reload_requested Event run_daemon polls. In-process, no signal round-trip, unit-testable; _do_reload runs on main thread as SIGHUP does. | ✓ |
| Self-SIGHUP os.kill(getpid, SIGHUP) | Watcher sends SIGHUP to own PID — literally the same path as `weatherbot reload`. Maximally 'provably identical' but signal indirection, fiddlier to test. | |

**User's choice:** Set reload_requested Event
**Notes:** Both funnel to the same _do_reload, so the in-process Event already gives the "identical path" guarantee without signal indirection.

---

## Enable / default + toggle

| Option | Description | Selected |
|--------|-------------|----------|
| On by default + config disable toggle | Watch runs whenever the daemon runs; config toggle ([reload] watch = false) turns it off. Matches CFG-03 'auto-detects'. Explicit SIGHUP always works regardless (Pitfall #11 'keep it optional'). | ✓ |
| Opt-in (off by default) | Operator must explicitly enable; explicit trigger is the only default. More conservative but reads against CFG-03. | |

**User's choice:** On by default + config disable toggle
**Notes:** Toggle surface decided separately (below) — config toggle only, no CLI flag.

---

## Toggle surface

| Option | Description | Selected |
|--------|-------------|----------|
| Config toggle only | Single source of truth in config.toml ([reload] watch = true, default true). Consistent with CLAUDE.md 'all settings editable without code changes'. | ✓ |
| Config toggle + CLI override flag | Add `--no-watch` on the daemon command overriding config per-invocation. Handy for debugging, but two places control the same behavior. | |

**User's choice:** Config toggle only

---

## Watch scope

| Option | Description | Selected |
|--------|-------------|----------|
| Re-derive watch set on each reload | Watch dirs of config.toml + currently-referenced templates; after a reload that changes referenced templates, update watched dirs. Correct for config pointing at a new template dir. | ✓ |
| Static watch set at startup | Compute config-dir + template-dirs once, never change. Simpler, but a reload introducing a template in a new dir wouldn't be auto-watched (explicit trigger still catches it). | |

**User's choice:** Re-derive watch set on each reload

---

## Debounce timing

| Option | Description | Selected |
|--------|-------------|----------|
| ~400ms, fixed constant | Tuned quiet-window coalescing truncate-then-write / temp-then-rename / multi-event saves into ONE reload (SC#2); module constant, not user-tunable. | ✓ |
| ~400ms, but configurable | Same default exposed in config.toml (e.g. [reload] debounce_ms). More config surface for a rarely-changed knob. | |
| watchfiles default (~1.6s / 50ms step) | Library defaults unchanged. Simplest, but 50ms step risks firing mid-save on slower temp-then-rename — weaker SC#2. | |

**User's choice:** ~400ms, fixed constant

---

## Claude's Discretion

- watchfiles API surface (threaded `watch()` vs `awatch()`) given the sync/threaded daemon.
- Exact mapping of the ~400ms quiet-window onto watchfiles' `debounce`/`step` params.
- Where the `request_reload()` seam lives and how the observer thread gets the Event reference.
- Exact Config field name/section for the `watch` toggle.
- How the watcher derives template directories from the live config (re-derive on reload).
- SC#3 fd-stability soak verification approach within the test suite's constraints.
- Behavior when a watched directory is deleted/recreated.

## Deferred Ideas

- Discord posting of reload outcome — Phase 11 (CFG-07).
- `.env` / secrets hot-reload — permanently out (restart boundary, Pitfall #12).
- systemd ExecReload / `systemctl reload` — declined in Phase 9 (D-04).
- A configurable debounce window — deferred as unnecessary config surface.
- ROADMAP checkbox reconciliation: Phase 10 is prematurely marked `[x] completed 2026-06-16` with no artifacts; reconcile when the phase actually verifies.
