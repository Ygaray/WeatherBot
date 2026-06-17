# Deploying WeatherBot (systemd, OPS-01)

WeatherBot runs as a single always-on, supervised process. systemd keeps it alive
(restart on crash, restart on reboot); the in-process APScheduler owns the briefing
schedule. This directory ships the systemd unit and the install / reboot-UAT steps.

> systemd is **only** the process supervisor — it does NOT schedule briefings
> (that's the in-process scheduler). `enable` is what gives you reboot survival.

---

## 1. Choose the `ExecStart` invocation (do this first)

systemd runs the unit with an **empty PATH and no active virtualenv**, so a bare
`ExecStart=weatherbot --run` will not find the interpreter. `ExecStart` **must be an
absolute, environment-independent command** (Pitfall 5). Two robust options — pick the
one that matches the target host:

```bash
# On the target host, from the repo root:
command -v uv                 # -> e.g. /usr/bin/uv  (uv present?)
ls .venv/bin/python           # -> .venv/bin/python  (project venv present?)
```

- **(a) uv (default in the shipped unit):**
  `ExecStart=/usr/bin/uv run weatherbot run`
  — uv resolves the project venv via `WorkingDirectory=`. Use the absolute path that
  `command -v uv` printed (it may be `/home/<user>/.local/bin/uv` rather than `/usr/bin/uv`).

- **(b) explicit venv interpreter (no uv at runtime):**
  `ExecStart=<REPO>/.venv/bin/python -m weatherbot run`
  — no uv needed; pin the absolute `.venv` python.

> **Open Question 1 (resolved at deploy time):** confirm uv-vs-venv on the *target*
> host before pinning `ExecStart`. Either is correct as long as it is absolute.

Then substitute the remaining placeholders in `deploy/weatherbot.service`:

- `<REPO>` → the absolute repo root (e.g. `/home/yahir/Projects/WeatherBot`) — used for
  both `WorkingDirectory=` and `EnvironmentFile=<REPO>/.env`.
- `<USER>` → the **non-root** user that owns the repo and `.env` (least privilege, V4).

---

## 2. Prepare the `.env` (secret hygiene + format)

Secrets are read **only** from the git-ignored `.env` via `EnvironmentFile=` — never
inlined into the unit file (`Environment=KEY=...`), never committed (CONF-02 / T-05-ID).

```bash
chmod 600 .env        # owner-only; not world-readable
```

**Required secrets (all three fail loud at startup if absent):**

| Env var | Source | Notes |
|---------|--------|-------|
| `OPENWEATHER_API_KEY` | https://openweathermap.org/api | New keys can take ~2h to activate. |
| `DISCORD_WEBHOOK_URL` | Server Settings -> Integrations -> Webhooks | Outbound briefing channel (bearer-style). |
| `DISCORD_BOT_TOKEN` | Developer Portal -> Applications -> (your app) -> Bot -> Reset Token | **NEW** — the inbound gateway bot token (D-14). Bearer-style; `.env` only, NEVER `config.toml`. |

> **Upgrading an existing deploy:** a `.env` that pre-dates the inbound bot will be
> **missing `DISCORD_BOT_TOKEN`**. That is now a **required** secret — the process
> fails loud at startup (pydantic `ValidationError`) rather than booting half-configured.
> Add the line to `.env` before redeploying. This is intended fail-loud behavior, not a bug.

### Enable the Message Content Intent (privileged) — mandatory for the bot

Before the bot token will let the gateway client read command text, you MUST enable the
**Message Content Intent** privileged intent (D-02). Without it, the bot connects but
sees empty message bodies and silently answers nothing:

1. Discord Developer Portal -> Applications -> **(your app)** -> **Bot**
2. Scroll to **Privileged Gateway Intents**
3. Toggle **Message Content Intent** ON, and **Save Changes**

(For a single-server personal bot under ~100 servers this needs no Discord verification.)

**`.env` format constraint (Pitfall 3):** systemd's `EnvironmentFile=` parser is **not**
a shell and **not** python-dotenv. Keep the file to the lowest-common-denominator form
so the daemon sees the exact same secret values it does interactively:

- `KEY=value`, one per line
- **no** `export ` prefix
- **no** inline `# comment` after a value (a trailing comment becomes part of the value)
- **no** shell expansion (`$VAR`, `~`) and avoid wrapping quotes unless intentional

A mis-parsed `OPENWEATHER_API_KEY` surfaces as a 401 that *looks* like a propagating /
bad key. Verify after install (step 4) — note that `systemctl show -p Environment`
shows an empty value for `EnvironmentFile=`-loaded vars; the startup self-check
reaching `active (running)` is the real confirmation the key loaded correctly.

---

## 3. Install + enable

```bash
sudo cp deploy/weatherbot.service /etc/systemd/system/weatherbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now weatherbot.service   # enable = survive reboot (OPS-01)
systemctl status weatherbot                       # reaches "active (running)" only AFTER READY=1
journalctl -u weatherbot -f                        # watch the self-check + online log
```

Under `Type=notify`, systemd holds the unit in `activating (start)` until the daemon
sends `READY=1` — which happens **only after the startup self-check first passes**
(OPS-02 SC#3). So `active (running)` is a genuine "config + key are good" signal, not
just "process spawned". (`TimeoutStartSec=infinity` lets a propagating key / slow-boot
network take as long as it legitimately needs without a crash-loop — Pitfall 1.)

---

## 3b. Redeploy after a CLI-surface change (subcommand migration)

When the CLI surface changes — notably the v1.1 clean break that replaced the old
`--run` flag with the `run` **subcommand** (and added `weather`/`check`/`send-now`/`geocode`
subcommands) — the **already-deployed** unit on the host still invokes the old surface and
its venv may predate the `weatherbot` console script. Redeploy on the host:

```bash
git pull                                   # pull the updated repo on the host
uv sync                                    # materialize .venv/bin/weatherbot (new console script)
sudo cp deploy/weatherbot.service /etc/systemd/system/weatherbot.service  # ExecStart now uses `run`
sudo systemctl daemon-reload               # pick up the new ExecStart
sudo systemctl restart weatherbot.service
systemctl status weatherbot.service        # confirm active (running)
uv run weatherbot weather home             # optional: one-shot briefing prints and exits 0
```

> The deployed `/etc/systemd/system/weatherbot.service` `ExecStart` must read
> `weatherbot run` (not `--run`) or the daemon fails to parse its arguments on start.
> `uv sync` is required so the `weatherbot` console script exists in `.venv/bin/` for the
> uv-form `ExecStart` (and for `uv run weatherbot ...`).

---

## 3c. Redeploy after the PID-runtime-dir fix (crash-loop on restart)

A `User=<USER>` (non-root) daemon could not write its PID file into root-owned bare
`/run`, so `systemctl restart` crash-looped with `PermissionError [Errno 13]` and
`Restart=always`. The fix is two coordinated changes already in the repo: the unit now
declares `RuntimeDirectory=weatherbot` (systemd creates `/run/weatherbot/` owned by
`User=<USER>` at start), and the daemon's `PID_FILE` default now points at
`/run/weatherbot/weatherbot.pid` inside that dir. The **already-deployed** unit at
`/etc/systemd/system/weatherbot.service` predates the `RuntimeDirectory=` line, so it
must be re-copied and reloaded on the host (root required):

```bash
git pull                                   # pull the updated repo on the host
sudo cp deploy/weatherbot.service /etc/systemd/system/weatherbot.service  # now has RuntimeDirectory=weatherbot
sudo systemctl daemon-reload               # pick up the new RuntimeDirectory=
sudo systemctl restart weatherbot.service
systemctl status weatherbot.service        # confirm active (running), no PermissionError crash-loop
ls -ld /run/weatherbot                      # optional: dir exists, owned by <USER>
cat /run/weatherbot/weatherbot.pid          # optional: holds the live daemon PID
```

> Without re-copying the unit + `daemon-reload`, systemd will NOT create
> `/run/weatherbot/`, and the daemon's PID-file write will still fail on the old
> deployed unit even though the repo code is correct.

---

## 4. Verify env vars reached the process

```bash
systemctl show -p Environment weatherbot
```

> **Expect this to print an empty `Environment=`.** `systemctl show -p Environment`
> ONLY reflects inline `Environment=KEY=...` directives — it does **not** expose the
> contents of `EnvironmentFile=`. Our unit loads secrets *exclusively* via
> `EnvironmentFile=`, so an empty `Environment=` here is **correct**, not a failure.
> (Treating that empty output as "the key didn't load" caused a false alarm during the
> host UAT — it isn't one.)

**The real proof the secrets loaded** is the startup self-check passing: under
`Type=notify` the daemon only logs `weatherbot online` / reaches `active (running)`
**after** `run_self_check` probes OpenWeather with the key. A bad/missing key would
classify as `auth_failed` and the unit would stay in `activating` (never `active`).
So:

```bash
systemctl is-active weatherbot                  # -> active  == secrets loaded + key good
journalctl -u weatherbot -b | grep "weatherbot online"
```

reaching `active (running)` with an `online` log **is** the confirmation the
`EnvironmentFile=` secrets reached the process.

**Direct (root-only) check**, if you want to eyeball the actual values in the running
process environment:

```bash
sudo systemctl show -p MainPID weatherbot                                  # -> MainPID=<pid>
sudo cat /proc/<MainPID>/environ | tr '\0' '\n' | grep -E 'OPENWEATHER|DISCORD'
```

Confirm `OPENWEATHER_API_KEY` and `DISCORD_WEBHOOK_URL` are present and **not mangled**
(no stray quotes / trailing comment text). If they look wrong, re-check the `.env`
format (step 2).

---

## 5. Reboot UAT (OPS-01 SC#1)

```bash
sudo reboot
# After the host comes back, WITHOUT touching anything:
systemctl is-active weatherbot        # -> active
journalctl -u weatherbot | tail        # the "weatherbot online" log + Discord ping reappear
```

The daemon restarts automatically and re-announces online — confirming reboot survival.

---

## 6. (Optional) Clean-stop check

```bash
systemctl stop weatherbot     # returns promptly; must NOT hang ~90s
```

A prompt stop confirms the SIGTERM handler is installed **before** the startup re-probe
loop (Pitfall 2): a `systemctl stop` during the loop sets the stop Event and shuts down
cleanly instead of waiting for systemd to escalate to SIGKILL after `TimeoutStopSec`.

---

## Reload behavior (inbound bot — known v1 limitation)

A config reload (SIGHUP, `weatherbot reload`, or the file-watch) reconciles the
**briefing schedule** immediately. The inbound `!weather` bot picks up most edits on
reload too — with ONE remaining v1 limitation (`operator_id`):

- **Forecast cache is invalidated on reload (no stale-forecast window).** The bot
  answers `!weather` from a per-location `ForecastCache` (default TTL ~10 min, D-12). A
  successful reload now **invalidates** that cache, so the next `!weather <loc>` after a
  reload **refetches** against the new config — there is no window in which a pre-reload
  forecast (edited coordinates / units / template) is served. Invalidation is
  best-effort: a cache error never aborts an otherwise-successful reload (CR-01 closed,
  quick task 260617-fua).

- **`[bot] operator_id` change requires a restart.** The allowed operator is BAKED at
  bot startup, not re-read per message. Changing `[bot] operator_id` (or adding/removing
  the `[bot]` section) is **not** honored by an already-running bot — the old operator
  keeps access and a new one is locked out **until you restart the process**. Live
  re-read is out of scope for v1.

To change `[bot] operator_id`, restart the service to apply it:

```bash
sudo systemctl restart weatherbot.service
```

---

## Notes

- **No watchdog in v1.** The unit sets no `WatchdogSec` (Pitfall 6). A future enhancement
  can add it with matching `WATCHDOG=1` keep-alives from the daemon's `SystemdNotifier`.
- **No Docker.** systemd is the chosen supervisor for the Pi/personal host (D-01).
- **wait-online service:** for `network-online.target` to actually wait on boot, the
  target host needs the correct wait-online service enabled
  (`NetworkManager-wait-online.service` *or* `systemd-networkd-wait-online.service`, not
  both). The in-process re-probe loop covers the gap regardless (Pitfall 4).
