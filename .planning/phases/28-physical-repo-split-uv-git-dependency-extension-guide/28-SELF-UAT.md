# Phase 28 — Gate-1 Self-UAT Log (autonomous; gates the phase)

**Policy:** Two-Gate UAT (`$HOME/.claude/CLAUDE.md`). Gate-1 is the autonomous agent
self-UAT: build/install the real artifact, drive it, and prove each success criterion with
exact commands + evidence + a PASS/FAIL/PARTIAL verdict — *prove the value at the data
level, don't infer from code*. A fully-passing Gate-1 completes the phase autonomously, **no
per-phase human pause**. The live `yahir-mint` restart + Discord tap-through is a **deferred
Gate-2** milestone-close obligation (recorded below, verdict PARTIAL — its mechanism +
data-level checks are proven here; only the secure-host restart + live Discord interaction
defer).

- **Driven:** 2026-06-29
- **Module under test:** `yahir-reusable-bot==0.1.0` @ git tag `v0.1.0` → sha
  `138a907d57ac1d1d8499399b019f1509e43d02f1` (`file://` fallback URL, per 28-01/28-02)
- **Consuming app:** WeatherBot `0.1.0`
- **Environment:** fresh `.venv` (CPython 3.12.3), installed strictly from `uv.lock` via
  `uv sync --frozen` — no dev overlay.

---

## Success criteria → Gate-1 verdicts

| # | Criterion | Verdict |
|---|-----------|---------|
| 1 | Clean-venv `uv sync --frozen` installs the module from the git pin | **PASS** |
| 2 | `weatherbot check` / `--help` resolve through stable public names | **PASS** |
| 3 | Full suite + Phase-21 goldens byte-identical against the pinned module | **PASS** |
| 4 | `uv build --no-sources` raises no leak; wheel carries only `weatherbot/` | **PASS** |
| 5 | `direct_url.json` deployed sha (data-level) == `uv.lock` sha == provenance line | **PASS** |
| — | Live `yahir-mint` restart + panel tap-through | **PARTIAL — deferred to Gate-2** |

**Gate-1 result: FULLY PASSING.** Phase completes autonomously per the Two-Gate UAT policy.

---

## Criterion 1 — Clean-venv frozen install (SC#1)

**What was tested:** that the pinned module installs off a *fresh* checkout (the "works
locally → works on host" conversion), purely from the lock, with no dev overlay.

**Exact commands:**
```bash
cd /home/yahir/Projects/WeatherBot
rm -rf .venv
uv venv
uv sync --frozen
```

**Evidence (tail of install log, exit 0):**
```
 + weatherbot==0.1.0 (from file:///home/yahir/Projects/WeatherBot)
 + yahir-reusable-bot==0.1.0 (from git+file:///home/yahir/Projects/YahirReusableBot@138a907d57ac1d1d8499399b019f1509e43d02f1)
EXIT=0
```
The module resolved from the **git pin** at sha `138a907d…` — not a path/editable source.
`discord.py` inherited transitively (confirmed installed in the same sync run).

**Verdict: PASS**

---

## Criterion 2 — Console-script resolution through stable public names (SC#1)

**What was tested:** that the `weatherbot` entry point crosses into the now-external module
through stable public names only (no in-tree copy).

**Exact commands:**
```bash
uv run weatherbot --help
uv run weatherbot check
```

**Evidence:**
- `--help` → exit 0; lists the full command set
  (`weather,run,check,check-config,reload,send-now,geocode,alerts,sun,wind,next-cloudy,uv,weekday-forecast,weekend-forecast,help,locations,status`).
- `check` → exit 0:
  ```
  [info     ] config check passed            locations=2
  retry budget: attempts_per_burst=8 burst_spread_seconds=600 mid_pause_seconds=2700 (approx total ~75 min)
  ```
  The command path crosses into the installed module (scheduler/wiring/reliability) and
  returns clean — the public-name boundary holds across the repo split.

**Verdict: PASS**

---

## Criterion 3 — Full suite + Phase-21 goldens byte-identical (SC#1; BHV-01/BHV-02)

**What was tested:** the entire test suite + the Phase-21 byte-identical golden oracle
(embeds, CLI stdout/exit, schedule plan, DB rows, `custom_id` byte snapshots,
exception-identity) re-run from the consuming app **against the pinned module**.

**Exact commands:**
```bash
uv run pytest -q
uv run pytest -q -k 'custom_id or customid'   # the live-panel wire-contract golden
git status --short '*.ambr'                    # byte-identical oracle: any diff = fail
```

**Evidence:**
- Full suite: **`776 passed`, exit 0** (in 40.62s).
- Snapshot report prints `2 snapshots failed. 27 snapshots passed.` — this is the **known
  syrupy report-noise quirk** (pre-existing; the suite exits 0 and no `.ambr` golden
  changed). Per the project `pytest-snapshot-report` memory: **trust the exit code + the
  `.ambr` diff**, not the printed snapshot count.
- `custom_id` golden (the live-panel `wb:` wire contract): **4 passed, exit 0** — the frozen
  `custom_id` byte snapshots match against the pinned module (the persistent-view re-bind
  contract the live panel depends on is intact).
- `git status --short '*.ambr'` → **empty** (no golden file updated/regenerated) → the
  byte-identical oracle holds with zero diff.

**Verdict: PASS** (byte-identical against the pinned module; the snapshot-count print is
known noise, not a golden diff).

---

## Criterion 4 — `uv build --no-sources` leak gate + wheel inspection (SC#2)

**What was tested:** that no path/dev source leaked into the deploy artifact, and the app
wheel collapsed to a single `weatherbot/` package (the module is external, not baked in).

**Exact commands:**
```bash
rm -rf dist
uv build --no-sources
WHL=$(ls dist/*.whl | head -1)
uv run python -m zipfile -l "$WHL" | grep -oE '^[a-z_]+/' | sort -u
# entry counts:
uv run python -m zipfile -l "$WHL" | grep -c '^weatherbot/'
uv run python -m zipfile -l "$WHL" | grep -c 'yahir_reusable_bot/'
```

**Evidence:**
- `uv build --no-sources` → exit 0; `Successfully built dist/weatherbot-0.1.0-py3-none-any.whl`
  (+ sdist). With `[tool.uv.sources]` disabled the build still resolves → **no path source
  leaked** into the committed artifact.
- Top-level package dirs in the wheel: **`weatherbot/` only**.
- `weatherbot/` entries: **46**; `yahir_reusable_bot/` entries: **0** (Pitfall 7 clean — the
  module is not baked into the app wheel).

**Verdict: PASS**

---

## Criterion 5 — Deployed-sha data-level proof (SC#3 mechanism)

**What was tested (prove the value, don't infer it):** that the startup-version-log
mechanism reports the **deployed** sha, by reading the installed package's PEP 610
`direct_url.json` directly and cross-checking it against the `uv.lock` frozen sha and the
`_module_provenance()` return.

**Exact commands:**
```bash
DU=$(find .venv -path '*yahir_reusable_bot*dist-info/direct_url.json' | head -1)
python -m json.tool "$DU"
# extract + cross-check:
python -c "import json; print(json.load(open('$DU'))['vcs_info']['commit_id'])"   # installed
grep 'name = \"yahir-reusable-bot\"' -A2 uv.lock | grep -oE '[0-9a-f]{40}' | head -1  # lock
python -c "from weatherbot.cli import _module_provenance; import json; print(json.dumps(_module_provenance()))"
```

**Evidence — installed `direct_url.json` (raw, data-level):**
```json
{
    "url": "file:///home/yahir/Projects/YahirReusableBot",
    "vcs_info": {
        "vcs": "git",
        "commit_id": "138a907d57ac1d1d8499399b019f1509e43d02f1",
        "requested_revision": "v0.1.0"
    }
}
```

**Cross-check (all three agree):**
- installed `direct_url.json` `commit_id` = `138a907d57ac1d1d8499399b019f1509e43d02f1`
- `uv.lock` frozen sha = `138a907d57ac1d1d8499399b019f1509e43d02f1` → **MATCH**
- `_module_provenance()` (the startup-version-log source) returns:
  ```json
  {"module_version": "0.1.0", "module_sha": "138a907d57ac1d1d8499399b019f1509e43d02f1", "module_ref": "v0.1.0", "editable": "False"}
  ```
  → `module_sha` MATCHES, `editable: "False"` confirms a real git deploy (not a dev overlay).

This is the SC#3 mechanism proven at the data level: the line the live host will display
reads its sha from `direct_url.json`, and that sha is byte-identical to the promoted ledger
sha. Only the *live-host display* of this line (over journald, post-`systemctl restart`)
defers to Gate-2.

**Verdict: PASS**

---

## Deferred Gate-2 obligation — live `yahir-mint` restart + panel tap-through

**Verdict: PARTIAL (mechanism + data-level checks proven in Gate-1; only the secure-host
restart + live Discord tap-through defer).**

Per the Two-Gate UAT policy, the live device-verifiable step is a **deferred milestone-close
obligation — it does NOT block this phase** and there is **no per-phase blocking
human-verify checkpoint**. It is recorded here (the persistent log the human verifies
against) and flagged for carry-forward into STATE.md Deferred Items + the v2.0 milestone
audit.

**Why deferred (not skipped):** it requires a secure-host action (`sudo systemctl restart`
on `yahir-mint`) plus a live Discord gateway tap-through that the tooling cannot synthesize.
The automatable parts — the startup-version-log line, the `custom_id`/persistent-view re-bind
contract, the clean-venv install, the byte-identical suite/goldens, and the `direct_url.json`
sha — are ALL proven PASS above.

**Outstanding prerequisite (standing Gate-2 blocker):** the committed `[tool.uv.sources]`
URL is a local `file://` fallback (`YahirReusableBot` has no fetchable remote yet). The host
cannot `git`-resolve a `file://` path that does not exist there. **A fetchable remote for
`YahirReusableBot` must be created and the `git = …` URL swapped** (then
`uv lock --upgrade-package yahir-reusable-bot` to re-resolve the same `v0.1.0` tag → same
sha) **before** the live host deploy.

**Exact replay instructions for the eventual live Gate-2 run:**

1. **Prerequisite — fetchable remote.** Create a network remote for `YahirReusableBot`, push
   `v0.1.0` to it, swap the `[tool.uv.sources]` `git = …` URL from the `file://` fallback to
   the real remote, then in WeatherBot:
   ```bash
   uv lock --upgrade-package yahir-reusable-bot   # re-resolves v0.1.0 -> same sha 138a907d
   git add pyproject.toml uv.lock && git commit -m "chore(deploy): point yahir-reusable-bot at fetchable remote" && git push
   ```
2. **On `yahir-mint` (the live host):**
   ```bash
   cd ~/Projects/WeatherBot
   git pull
   uv sync --frozen
   sudo systemctl restart weatherbot
   ```
3. **Confirm the deployed sha (cross-check the ledger):**
   ```bash
   journalctl -u weatherbot -n 30 --no-pager
   ```
   - Find the once-per-boot **`module provenance`** line. Confirm `module_sha` ==
     `138a907d57ac1d1d8499399b019f1509e43d02f1` (== the `deploy/PROMOTION-LEDGER.md`
     `v0.1.0` row). Confirm `editable: False` (a real git deploy, not a dev overlay).
4. **Tap-through the live panel:** tap every button/dropdown on the already-pinned live
   Discord panel — confirm each routes (no "interaction failed" → the `custom_id` contract +
   persistent-view re-bind survived the split byte-identically) and that the **correct
   default location** is selected.

**Carry-forward:** flagged for STATE.md Deferred Items + the v2.0 milestone audit so the
milestone-close gate picks it up.

---

## Gate-1 sign-off

All five autonomous success criteria **PASS** with per-criterion evidence (clean-venv
install, console-script resolution, byte-identical suite/goldens, `--no-sources` leak gate +
wheel inspection, and the `direct_url.json` deployed-sha data-level cross-check). Per the
Two-Gate UAT policy, **a fully-passing Gate-1 completes Phase 28 autonomously** — no
per-phase human pause. The live `yahir-mint` restart + panel tap-through is recorded above as
a deferred Gate-2 milestone-close obligation (verdict PARTIAL).

*Phase: 28-physical-repo-split-uv-git-dependency-extension-guide — D-08 Gate-1 self-UAT.*
