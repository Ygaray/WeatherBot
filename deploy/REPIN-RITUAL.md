# Repin Ritual — promoting a new `yahir-reusable-bot` sha to the WeatherBot deploy (D-06)

WeatherBot consumes the reusable bot module (`yahir-reusable-bot`, import root
`yahir_reusable_bot`) as a **uv git dependency, tag-pinned for deploy** (`[tool.uv.sources]`
git entry, `tag = "vX.Y.Z"`), with `uv.lock` freezing the exact resolved commit sha so
`uv sync --frozen` is byte-reproducible on the host. This document is the durable,
repeatable ritual for moving a new module sha into the live deploy — and the rules that keep
the deploy artifact honest.

> **Who owns this:** the *app* (WeatherBot) owns consume + deploy, so this ritual lives
> here (alongside the systemd unit), not in the module repo. The module repo owns only the
> tag.

---

## The repin loop, step by step

### A. In the module repo (`YahirReusableBot`) — cut an immutable tag

```bash
cd ~/Projects/YahirReusableBot
# 1. commit the module change(s)
git add -A
git commit -m "feat: <module change>"
# 2. push the branch
git push origin main
# 3. tag the new release — IMMUTABLE. Bump the version; never re-point an existing tag.
git tag v0.2.0
# 4. push the tag
git push origin v0.2.0
```

> **Immutable-tag discipline (Pitfall 2).** A deploy tag is a permanent promotion unit.
> **Never** `git tag -f` / force-push an existing deploy tag to a new sha — a mutable tag
> silently drifts what every consumer resolves. Always cut a **new** version tag. The
> `uv.lock` + `uv sync --frozen` pin the resolved sha regardless of tag movement, so even a
> mis-moved tag cannot change an already-locked deploy — but new tags are the contract.

### B. In WeatherBot — repin + re-resolve + commit the lock

```bash
cd ~/Projects/WeatherBot
# 1. bump the tag in [tool.uv.sources] in pyproject.toml:
#      yahir-reusable-bot = { git = "<url>", tag = "v0.2.0" }
$EDITOR pyproject.toml
# 2. re-resolve ONLY that package to the new tag's sha (leaves everything else untouched):
uv lock --upgrade-package yahir-reusable-bot
# 3. commit BOTH the pyproject tag bump and the regenerated lock together:
git add pyproject.toml uv.lock
git commit -m "chore(deploy): repin yahir-reusable-bot v0.2.0"
git push origin main
# 4. append a row to deploy/PROMOTION-LEDGER.md (see step D) — same commit or a follow-up.
```

> `uv lock --upgrade-package yahir-reusable-bot` re-resolves **only** the named package
> (the tag → its new commit sha), regenerating just that block of `uv.lock`. Do not run a
> bare `uv lock` for a repin — that re-resolves the whole graph and can pull unrelated
> drift into the deploy lock.

### C. On the live host (`yahir-mint`) — pull + frozen sync + restart

```bash
# (Gate-2 / deferred — performed on the secure host, not by tooling)
cd ~/Projects/WeatherBot
git pull
uv sync --frozen                     # installs the EXACT locked sha — no re-resolve
sudo systemctl restart weatherbot    # picks up the repin (the service runs supervised)
# confirm the deploy:
journalctl -u weatherbot -n 30 --no-pager
#   -> look for the once-per-boot "module provenance" startup-version-log line.
#      Its module_sha MUST equal the sha you just promoted (cross-check the ledger).
#      editable MUST be False (a real git deploy, not a dev overlay).
```

> `uv sync --frozen` installs strictly from `uv.lock` with no re-resolution — this is the
> "works locally → works on host" guarantee. If the lock and pyproject disagree, `--frozen`
> **fails loudly** rather than silently re-resolving; that is the intended safety, not an
> error to work around. (Fix by re-running step B.)

### D. Record the promotion — append a ledger row

After a successful host restart, append one row to `deploy/PROMOTION-LEDGER.md`:

| Date | Tag | Resolved SHA | Note |
|------|-----|--------------|------|

The resolved sha is the `module_sha` from the startup-version-log line (and is the sha
frozen in `uv.lock` for that tag). The ledger is the human record of *which sha is live*.

---

## Local co-development overlay (D-05) — edit both repos without a push→repin round-trip

Day-to-day, you often edit `YahirReusableBot` and WeatherBot together. You do **not** want
to push + tag + repin for every iteration. The sanctioned pattern is an **uncommitted venv
editable overlay** layered over the committed git pin:

```bash
cd ~/Projects/WeatherBot
# overlay the sibling checkout as an editable install INTO the venv only:
uv pip install -e /home/yahir/Projects/YahirReusableBot
#   -> now `yahir_reusable_bot` resolves to your live sibling tree; edits are picked up
#      immediately. The "module provenance" line will show editable: True (the tripwire).

# when done, REVERT to the committed pin — wipes the overlay, restores the frozen sha:
uv sync --frozen
```

### The one inviolable rule: NEVER commit a path source

- The overlay is a **venv-only** state (`uv pip install -e ...`). It is **not** written to
  `pyproject.toml` or `uv.lock`. Nothing about it is committed.
- **Never** add a `path = "../YahirReusableBot"` entry to `[tool.uv.sources]` in a committed
  `pyproject.toml`. A committed path source would ship a dev path into the deploy artifact —
  the exact "works locally, breaks on host" failure class this whole design eliminates.
- **Backstop (proven green in 28-02, re-proven in the Gate-1 self-UAT):** `uv build
  --no-sources` builds the wheel/sdist with `[tool.uv.sources]` disabled. If a path source
  ever leaked into the committed artifact, this gate fails. Run it before any deploy you are
  unsure about.
- The `editable: True` flag on the `module provenance` startup line is the *runtime*
  tripwire: if the host ever shows `editable: True`, a dev overlay leaked onto the host —
  `uv sync --frozen` to restore the pin.

---

## Quick reference

| Step | Repo | Command | Guard |
|------|------|---------|-------|
| commit + push module | YahirReusableBot | `git commit` / `git push` | — |
| tag (immutable) | YahirReusableBot | `git tag vX.Y.Z && git push origin vX.Y.Z` | never force-push a deploy tag (Pitfall 2) |
| repin | WeatherBot | edit `[tool.uv.sources]` tag | — |
| re-resolve | WeatherBot | `uv lock --upgrade-package yahir-reusable-bot` | only that package |
| commit lock | WeatherBot | `git commit pyproject.toml uv.lock` | tag + lock together |
| deploy | host | `git pull && uv sync --frozen` | `--frozen` fails loud on drift |
| restart | host | `sudo systemctl restart weatherbot` | — |
| verify | host | `journalctl -u weatherbot -n 30` | `module_sha` == ledger sha; `editable: False` |
| record | WeatherBot | append to `PROMOTION-LEDGER.md` | one row per promotion |
| local co-dev | WeatherBot | `uv pip install -e ../YahirReusableBot` | venv-only; revert via `uv sync --frozen`; never commit a path source |

---

## Outstanding prerequisite (Gate-2 / host deploy)

As of `v0.1.0`, the committed `[tool.uv.sources]` git URL is a **local `file://` fallback**
(`file:///home/yahir/Projects/YahirReusableBot`) — `YahirReusableBot` has no fetchable
network remote yet. The live `yahir-mint` host cannot `git`-resolve a `file://` path that
does not exist there. **Before the first host deploy:** create a fetchable remote for
`YahirReusableBot`, swap the `git = …` URL to it, then
`uv lock --upgrade-package yahir-reusable-bot` (re-resolves the same `v0.1.0` tag → same
sha). This is the standing Gate-2 blocker carried in STATE.md.

---

*Phase 28 (v2.0 Bot Module Extraction) — D-06 process artifact.*
