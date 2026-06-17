---
phase: quick-260617-idm
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - deploy/weatherbot.service
  - weatherbot/ops/pidfile.py
  - tests/conftest.py
  - tests/test_reload.py
  - deploy/README.md
autonomous: true
requirements: [OPS-01, CFG-02]
user_setup: []

must_haves:
  truths:
    - "The default PID-file path lives inside a per-service runtime dir the non-root daemon can write (/run/weatherbot/weatherbot.pid)."
    - "The systemd unit declares RuntimeDirectory=weatherbot so /run/weatherbot/ is created owned by User=<USER> at start."
    - "The reload sender (cli.py) and the daemon writer agree on the PID path because both read the single PID_FILE module constant."
    - "The full pytest suite stays green; a test proves the default PID path is now under /run/weatherbot/."
  artifacts:
    - path: "weatherbot/ops/pidfile.py"
      provides: "PID_FILE default pointed at /run/weatherbot/weatherbot.pid"
      contains: "Path(\"/run/weatherbot/weatherbot.pid\")"
    - path: "deploy/weatherbot.service"
      provides: "RuntimeDirectory=weatherbot under [Service]"
      contains: "RuntimeDirectory=weatherbot"
  key_links:
    - from: "deploy/weatherbot.service"
      to: "weatherbot/ops/pidfile.py"
      via: "RuntimeDirectory creates /run/weatherbot/ that PID_FILE writes into"
      pattern: "RuntimeDirectory=weatherbot"
    - from: "weatherbot/cli.py reload sender"
      to: "weatherbot/ops/pidfile.py PID_FILE"
      via: "shared module constant (read_pid default)"
      pattern: "PID_FILE"
---

<objective>
Fix the Phase 11 UAT blocker: the daemon (User=yahir, non-root) crash-loops on
`systemctl restart` because it writes its PID file into root-owned `/run`.

Root cause (confirmed in UAT): `pidfile.py` hardcodes `PID_FILE=/run/weatherbot.pid`
and `write_pid_atomic` creates a temp file in `/run`; the systemd unit runs
`User=<USER>` with NO `RuntimeDirectory=`, so `/run` (root-owned 0755) rejects the
write → `PermissionError [Errno 13]` at daemon.py:1117 → `Restart=always` → crash-loop.
This is a latent regression: the PID-file feature (Phase 9) was never reconciled with
the Phase 5 systemd unit.

Fix = two coordinated changes: (1) add `RuntimeDirectory=weatherbot` to the unit so
systemd creates `/run/weatherbot/` owned by the service user at start; (2) point
`PID_FILE` at `/run/weatherbot/weatherbot.pid` inside that dir. Keep the override-param
API intact, keep the suite green, and document the root-only re-install follow-up.

Purpose: Restore reliable always-on operation — the daemon must survive restarts.
Output: Patched unit template, patched PID_FILE default, updated tests + docs.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/11-discord-inbound-gateway-bot/11-UAT.md
@weatherbot/ops/pidfile.py
@weatherbot/scheduler/daemon.py
@deploy/weatherbot.service
@deploy/README.md
@tests/conftest.py
@tests/test_reload.py
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Point PID_FILE at the systemd runtime dir and prove it via test</name>
  <files>weatherbot/ops/pidfile.py, tests/conftest.py, tests/test_reload.py</files>
  <behavior>
    - Default `weatherbot.ops.pidfile.PID_FILE` equals `Path("/run/weatherbot/weatherbot.pid")` (its parent is the per-service runtime dir, not bare /run).
    - `write_pid_atomic(pid_file=tmp_path/...)` and `read_pid(pid_file=...)` still honor the override argument unchanged (existing tests at test_reload.py:497-562 keep passing).
    - A new/updated test asserts the production default `PID_FILE` parent is `/run/weatherbot` (i.e. the writable per-service dir), not `/run`.
  </behavior>
  <action>
    In weatherbot/ops/pidfile.py change the PID_FILE constant from
    `Path("/run/weatherbot.pid")` to `Path("/run/weatherbot/weatherbot.pid")`. Update
    the constant's comment (currently "/run is the canonical runtime-state dir") to
    explain that the file now lives inside the systemd `RuntimeDirectory=weatherbot`
    dir (`/run/weatherbot/`), which systemd creates owned by the non-root service User
    at start; the existing `pid_file.parent.mkdir(parents=True, exist_ok=True)` in
    write_pid_atomic stays as a graceful fallback but is no longer the load-bearing
    mechanism. Do NOT change the `write_pid_atomic` / `read_pid` signatures or the
    override-parameter behavior — tests depend on `pid_file=` injection.
    Update the stale prose in tests/conftest.py (line ~32 docstring) that says
    `default /run/weatherbot.pid` to read `/run/weatherbot/weatherbot.pid` so the
    redirect-fixture comment stays accurate; the fixture logic itself is unchanged.
    Add a focused test in tests/test_reload.py (near the existing pidfile tests, ~497)
    that imports `weatherbot.ops.pidfile.PID_FILE` and asserts
    `PID_FILE == Path("/run/weatherbot/weatherbot.pid")` and that
    `PID_FILE.parent.name == "weatherbot"` — proving the default is under the writable
    runtime dir, not bare /run. Grep first to confirm no other source hardcodes the
    string "/run/weatherbot.pid" (the reload sender in cli.py reads the PID_FILE
    constant, so it tracks the change automatically — verify, do not edit, that path).
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot && grep -rn "/run/weatherbot.pid" --include="*.py" weatherbot/ | grep -v '^#' ; test -z "$(grep -rn '/run/weatherbot.pid' --include='*.py' weatherbot/)" && uv run pytest tests/test_reload.py -q</automated>
  </verify>
  <done>
    PID_FILE default is `/run/weatherbot/weatherbot.pid`; no `weatherbot/*.py` hardcodes
    the old `/run/weatherbot.pid` string; new default-path test passes; existing pidfile
    override tests (test_reload.py:497-562) still pass.
  </done>
</task>

<task type="auto">
  <name>Task 2: Add RuntimeDirectory to the unit and document the root-only re-install</name>
  <files>deploy/weatherbot.service, deploy/README.md</files>
  <action>
    In deploy/weatherbot.service add `RuntimeDirectory=weatherbot` under the [Service]
    section (place it near the User=/Restart= block). Add a comment in the unit's
    existing heavily-commented style explaining that systemd creates `/run/weatherbot/`
    owned by `User=<USER>` (mode 0755) at start and removes it on stop, which is what
    lets the non-root daemon write its PID file there (the Phase 11 UAT crash-loop fix)
    — and that this pairs with `PID_FILE=/run/weatherbot/weatherbot.pid`. Preserve the
    `<REPO>`/`<USER>` placeholder template convention (do not substitute real values).
    In deploy/README.md add a short follow-up note in the install/redeploy area (after
    section "3b. Redeploy after a CLI-surface change", ~line 128) titled e.g. "3c.
    Redeploy after the PID-runtime-dir fix" that states: this fix requires copying the
    updated unit to /etc/systemd/system/weatherbot.service and running
    `sudo systemctl daemon-reload` then `sudo systemctl restart weatherbot.service`
    (root required; the agent cannot do this). Use the same `sudo cp ... && sudo
    systemctl daemon-reload` shell-block style already used in sections 3 and 3b.
  </action>
  <verify>
    <automated>cd /home/yahir/Projects/WeatherBot && grep -q "RuntimeDirectory=weatherbot" deploy/weatherbot.service && grep -q "weatherbot/weatherbot.pid\|RuntimeDirectory\|daemon-reload" deploy/README.md && echo OK</automated>
  </verify>
  <done>
    deploy/weatherbot.service contains `RuntimeDirectory=weatherbot` with an explanatory
    comment and intact `<REPO>`/`<USER>` placeholders; deploy/README.md documents the
    root-only re-install + daemon-reload + restart follow-up.
  </done>
</task>

</tasks>

<verification>
- `uv run pytest -q` (full suite) is green.
- `grep -rn "/run/weatherbot.pid" weatherbot/` (excluding comments) returns nothing.
- `deploy/weatherbot.service` declares `RuntimeDirectory=weatherbot`.
- The reload sender (`weatherbot/cli.py`) is unchanged and still resolves `PID_FILE`,
  keeping writer and reader on the same path.
</verification>

<success_criteria>
- Default PID path is `/run/weatherbot/weatherbot.pid` (inside the systemd-created,
  user-owned runtime dir) — the non-root daemon can write it without PermissionError.
- systemd unit creates that dir via `RuntimeDirectory=weatherbot`.
- Override API (`write_pid_atomic(pid_file=...)`, `read_pid(pid_file=...)`) unchanged.
- Full test suite green; a test proves the new default path.
- SUMMARY.md surfaces the MANUAL root follow-up: `sudo cp deploy/weatherbot.service
  /etc/systemd/system/weatherbot.service && sudo systemctl daemon-reload && sudo
  systemctl restart weatherbot.service` (the agent cannot run sudo).
</success_criteria>

<output>
Create `.planning/quick/260617-idm-fix-daemon-startup-crash-loop-pid-file-w/260617-idm-SUMMARY.md` when done.
In the SUMMARY, prominently flag the MANUAL post-step: the installed unit at
`/etc/systemd/system/weatherbot.service` must be re-copied and `systemctl daemon-reload`
+ `restart` run AS ROOT by the user — the agent cannot and did not run sudo.
</output>
