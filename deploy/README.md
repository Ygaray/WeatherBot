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
  `ExecStart=/usr/bin/uv run weatherbot --run`
  — uv resolves the project venv via `WorkingDirectory=`. Use the absolute path that
  `command -v uv` printed (it may be `/home/<user>/.local/bin/uv` rather than `/usr/bin/uv`).

- **(b) explicit venv interpreter (no uv at runtime):**
  `ExecStart=<REPO>/.venv/bin/python -m weatherbot --run`
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

**`.env` format constraint (Pitfall 3):** systemd's `EnvironmentFile=` parser is **not**
a shell and **not** python-dotenv. Keep the file to the lowest-common-denominator form
so the daemon sees the exact same secret values it does interactively:

- `KEY=value`, one per line
- **no** `export ` prefix
- **no** inline `# comment` after a value (a trailing comment becomes part of the value)
- **no** shell expansion (`$VAR`, `~`) and avoid wrapping quotes unless intentional

A mis-parsed `OPENWEATHER_API_KEY` surfaces as a 401 that *looks* like a propagating /
bad key. Verify after install (step 4) with `systemctl show -p Environment weatherbot`.

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

## 4. Verify env vars reached the process

```bash
systemctl show -p Environment weatherbot
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

## Notes

- **No watchdog in v1.** The unit sets no `WatchdogSec` (Pitfall 6). A future enhancement
  can add it with matching `WATCHDOG=1` keep-alives from the daemon's `SystemdNotifier`.
- **No Docker.** systemd is the chosen supervisor for the Pi/personal host (D-01).
- **wait-online service:** for `network-online.target` to actually wait on boot, the
  target host needs the correct wait-online service enabled
  (`NetworkManager-wait-online.service` *or* `systemd-networkd-wait-online.service`, not
  both). The in-process re-probe loop covers the gap regardless (Pitfall 4).
