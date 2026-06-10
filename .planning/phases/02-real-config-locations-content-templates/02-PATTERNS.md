# Phase 2: Real Config — Locations, Content & Templates - Pattern Map

**Mapped:** 2026-06-09
**Files analyzed:** 14 (8 modified, 1 new source, 1 retired source, 1 new test, 1 modified test set, fixtures)
**Analogs found:** 14 / 14 (every new/modified file extends an existing Phase 1 file — this is a brownfield rewrite, not greenfield)

> **Key framing:** Phase 2 has **no greenfield files with "no analog."** Every change repoints, extends, or wraps an existing Phase 1 seam. The richest source of patterns is the Phase 1 code itself — copy its docstring discipline, its defensive `.get() or {}` access, its secret-safe logging, its injectable-collaborator testing, and its `extra="forbid"` + `field_validator` config style. The two genuinely new artifacts (`validate_template`, `--geocode`/`--check`) still have close in-repo analogs (the `_TOKEN` regex; `resolve_location` + the argparse block + the channel factory registry).

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/weather/client.py` | service (API client) | request-response | itself (Phase 1 2.5 client) | exact (repoint) |
| `weatherbot/weather/models.py` | model (domain) | transform | itself (`Forecast.from_payloads`) | exact (rewrite mapping) |
| `weatherbot/weather/store.py` | service (persistence) | CRUD / file-I/O | itself (Phase 1 store) | exact (schema migrate) |
| `weatherbot/weather/aggregate.py` | utility | transform | — (RETIRE) | n/a — delete |
| `weatherbot/config/models.py` | model (config) | request-response (validate-at-load) | itself (`Location`, `Config`) | exact (extend) |
| `weatherbot/config/loader.py` | utility (loader) | request-response | itself (`load_config`, `resolve_location`) | exact (extend) |
| `templates/renderer.py` | utility (render + validate) | transform | itself (`render`, `_TOKEN`) | exact (add `validate_template`) |
| `weatherbot/cli.py` | controller (composition root) | request-response | itself (`main`, `send_now`) | exact (add subcommands) |
| `weatherbot/config/__init__.py` | config (barrel) | — | itself | exact (re-export) |
| `templates/*.txt` | config (content) | — | `briefing-sectioned.txt` | exact (add placeholders) |
| `tests/test_cli.py` (NEW) | test | request-response | `tests/test_send_now.py` + `tests/test_client.py` | role-match (compose) |
| `tests/test_models.py` (extend) | test | transform | itself + `tests/test_renderer.py` | exact (extend) |
| `tests/test_config.py` (extend) | test | request-response | itself | exact (extend) |
| `tests/test_renderer.py` (extend) | test | transform | itself | exact (extend) |
| `tests/test_store.py` (rewrite) | test | CRUD | itself | exact (rewrite) |
| `tests/fixtures/onecall_*.json` (NEW) | test fixture | — | `tests/fixtures/current_imperial_clear.json` | role-match |
| `tests/test_aggregate.py` | test | — | — (RETIRE) | n/a — delete |

---

## Pattern Assignments

### `weatherbot/weather/client.py` (service, request-response) — REPOINT 2.5 → One Call 3.0 + ADD geocode

**Analog:** itself (Phase 1 2.5 client) — **the secret-safe HTTP discipline is the load-bearing pattern to preserve verbatim.**

**Module-level secret-safe logging pin** (`client.py:33`) — copy this line unchanged; it also protects the new geocode call (Pitfall 6 / D-08 security):
```python
logging.getLogger("httpx").setLevel(logging.WARNING)
```

**Existing `_get` shape to repoint** (`client.py:36-54`) — keep the `httpx.Client(timeout=_TIMEOUT)` context manager, the `params={... "appid": key ...}` (key in params, never in a logged URL), and `response.raise_for_status()` (surfaces the One Call 401/403 subscription-not-active case clearly, Pitfall 1):
```python
def _get(path: str, lat: float, lon: float, key: str, units: str) -> dict:
    with httpx.Client(timeout=_TIMEOUT) as c:
        response = c.get(
            f"{BASE}/{path}",
            params={"lat": lat, "lon": lon, "appid": key, "units": units, "lang": "en"},
        )
        response.raise_for_status()
        return response.json()
```

**Repoint deltas (from RESEARCH §Code Examples):**
- `BASE = "https://api.openweathermap.org/data/2.5"` (line 24) → split into `ONECALL = ".../data/3.0/onecall"` and `GEOCODE = ".../geo/1.0/direct"`.
- Collapse `fetch_current` + `fetch_forecast` (lines 57-64) into ONE `fetch_onecall(loc, key, units)` that adds `"exclude": "minutely,hourly"` to params (keep `current`, `daily`, `alerts`).
- ADD `geocode(query, key, limit=5)` — same `httpx.Client(timeout=_TIMEOUT)` + `raise_for_status()` shape, but `params={"q": query, "limit": limit, "appid": key}`, returns a `list[dict]` (LOC-03 — setup-time only, never on the send path).
- Update the module docstring (lines 1-12) to describe One Call 3.0; keep the "never logs the URL or the key" sentence — it now also covers `geocode`.

**Test analog:** `tests/test_client.py` — its `_install_mock` (`monkeypatch` swaps `httpx.Client.__init__` to inject `httpx.MockTransport`) and the `test_appid_not_logged`/`test_401_raises_not_retried`/`test_explicit_timeout_set` tests transfer directly; assert `path == "/data/3.0/onecall"` and the geocode path.

---

### `weatherbot/weather/models.py` (model, transform) — REWRITE `from_payloads` + ADD hints/alert/feels_like

**Analog:** itself (`Forecast` dataclass + `from_payloads` + `placeholders`).

**Defensive payload access pattern to keep** (`models.py:92-99`) — the `or {}` / `or [{}]` discipline is the exact pattern to extend to `daily[0]`/`alerts[]` (Pitfall 2 — `alerts` key may be ABSENT, not `[]`):
```python
imp_main = current_imp.get("main") or {}
weather = current_imp.get("weather") or [{}]
first = weather[0] if weather else {}
conditions = (first or {}).get("main", "")
```
New One Call mapping (RESEARCH §Mapping One Call → normalized Forecast): `cur_i = payload_imp.get("current") or {}`, `day_i = (payload_imp.get("daily") or [{}])[0]`, `alerts = payload_imp.get("alerts") or []`, `rain_chance = round((day_i.get("pop") or 0.0) * 100)`, `uvi_max = day_i.get("uvi") or 0.0`.

**Dataclass + classmethod-constructor shape to keep** (`models.py:38-121`) — keep `@dataclass Forecast`, the `now_utc: datetime | None = None` injectable arg, and the retained-raw-payloads fields (rename `raw_current_imp/...` → e.g. `raw_onecall_imp/raw_onecall_met` for the 2-call DATA-03 reuse). **Change `from_payloads` signature** from the four 2.5 payloads (lines 71-79) to two One Call payloads: `from_payloads(loc, onecall_imp, onecall_met, now_utc=None)`.

**Display-property pattern to copy for `{feels_like}`** (`models.py:125-135`) — the imperial-primary `_temp_str` is the exact template for the new `feels_like_display`:
```python
@staticmethod
def _temp_str(imp: float, met: float) -> str:
    return f"{round(imp)}°F ({round(met)}°C)"
@property
def temp_display(self) -> str:
    return self._temp_str(self.temp_imp, self.temp_met)
```
ADD `feels_imp`/`feels_met` fields + a `feels_like_display` property reusing `_temp_str` (D-05).

**`placeholders()` map to EXTEND** (`models.py:150-162`) — add the three new keys; this flat `str→str` map is the stable D-04 renderer seam:
```python
def placeholders(self) -> dict[str, str]:
    return {
        "temp": self.temp_display,
        "feels_like": self.feels_like_display,   # NEW (D-05)
        "high": self.high_display, "low": self.low_display,
        "rain": f"{self.rain_chance}%", "wind": self.wind_display,
        "humidity": f"{self.humidity}%", "conditions": self.conditions,
        "location": self.location, "date": self.local_date,
        "hint": self._hint_text,                 # NEW (D-06/07) — "\n".join or ""
        "alert": self._alert_text,               # NEW (D-08) — summary or ""
    }
```

**New derived-field helpers** (code-computed, never template logic — RESEARCH §Code Examples) — five hardcoded-threshold hints joined `"\n".join(lines)` (empty → `{hint}` collapses) and the alert summary `"⚠️ " + "; ".join(events)` (empty `alerts` → `""`). Cold/heat read **feels-like (imperial)**, sunscreen reads `daily[0].uvi`.

**Drop the aggregate import** (`models.py:25` `from weatherbot.weather.aggregate import today_aggregate`) and `_local_date_iso(forecast_payload, ...)` (lines 31-35); compute `local_date` from the **configured** `loc.timezone` via `zoneinfo` (D-03 — config tz is authoritative, NOT the API `timezone`, Pitfall 3).

**Test analog:** `tests/test_models.py` + `tests/test_renderer.py:_forecast` helper (lines 31-38) — update the helper to call `from_payloads(LOC, onecall_imp, onecall_met)`; add `-k hints`/`-k alert`/`-k from_payloads` cases driven by the new fixtures.

---

### `weatherbot/weather/store.py` (service, CRUD/file-I/O) — MIGRATE schema to One Call

**Analog:** itself (Phase 1 store).

**`raw_json` + GENERATED VIRTUAL column pattern to keep** (`store.py:33-49`) — this is the DATA-02 "no-backfill analysis column" pattern; reuse it verbatim for a NEW `weather_onecall` table with One Call JSON paths (`$.current.temp`, `$.current.feels_like`, `$.current.uvi`, `$.daily[0].temp.max`, `$.daily[0].temp.min`, `$.daily[0].pop`, `$.daily[0].uvi`):
```python
raw_json   TEXT NOT NULL,
temp       REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp')) VIRTUAL,
humidity   REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.humidity')) VIRTUAL,
```

**Inline idempotent-schema + parameterized-insert pattern to keep** (`store.py:121-148`) — `conn.executescript(_SCHEMA)` then parameterized `?` inserts in the SAME connection/transaction (WR-03; SQLi-safe, RESEARCH §Security):
```python
with sqlite3.connect(db_path) as conn:
    conn.executescript(_SCHEMA)          # idempotent CREATE TABLE IF NOT EXISTS
    conn.execute(
        "INSERT INTO weather_current (...) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (location.name, location.lat, location.lon, fetched_at, observed_at,
         tz_offset, _local_date_iso(observed_at, tz_offset), units, json.dumps(payload)),
    )
    conn.commit()
```

**Migration deltas (RESEARCH §Runtime State Inventory, A3):**
- ADD a new `weather_onecall` table (keep the OLD `weather_current`/`weather_forecast` tables in `_SCHEMA` untouched as retained history — NO destructive backfill).
- Persist BOTH unit variants of the One Call payload (mirror `current_variants`/`forecast_variants` tuple loop, lines 112-119) — `(("imperial", forecast.raw_onecall_imp), ("metric", forecast.raw_onecall_met))`.
- Compute `target_local_date` from the **configured** `Location.timezone` (zoneinfo), not the payload's `timezone` offset (D-03) — preserves the forecast-vs-actual join key cleanly.
- Keep `init_db` (lines 83-92) and the secret-hygiene rule (docstring lines 19-20): store only response payloads, never the request URL.

**Test analog:** `tests/test_store.py` (rewrite) — keep `_build` (build a `Forecast` from fixtures), `_connect` with `row_factory = sqlite3.Row`, and the `sqlite_master` table/index assertions (lines 40-58); target the new table + new `json_extract` columns (`-k onecall`).

---

### `weatherbot/config/models.py` (model, validate-at-load) — EXTEND `Location` with `timezone` + `units`

**Analog:** itself (`Location`, `WebhookIdentity`, `Config`).

**`extra="forbid"` model pattern to keep** (`models.py:17-27`) — this is the fail-loud-at-load seam (CONF-03); add the two new fields under the same `ConfigDict(extra="forbid")`:
```python
class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    lat: float
    lon: float
    timezone: str            # NEW — required IANA zone (D-03)
    units: str | None = None # NEW — optional per-location override (D-03)
```

**New validators (RESEARCH §Code Examples — IANA tz + units)** — add `@field_validator("timezone")` doing `ZoneInfo(v)` in a try/except (raise on `ZoneInfoNotFoundError`, ValueError) and `@field_validator("units")` checking membership in `{"imperial", "metric"}`. `zoneinfo` is stdlib — no new dep (Don't Hand-Roll: don't keep a manual zone list).

**`Config` is unchanged in shape** (`models.py:42-53`) — `locations: list[Location]` already supports ≥2 entries (D-06); only the per-`Location` fields grow.

**Test analog:** `tests/test_config.py` — extend with `-k location_fields` (timezone parsed), `-k bad_timezone` (`pytest.raises(ValidationError)` on a fake zone), `-k multi_location`, `-k invalid` (bad units enum). Reuse the `_write(tmp_path, "config.toml", """...""")` + `load_config` helper (lines 27-31) and the existing `test_malformed_location_missing_lat_fails_loud` (lines 123-136) as the template for the new fail-loud cases.

---

### `weatherbot/config/loader.py` (utility, request-response) — ADD unique-name helper for `--check`

**Analog:** itself (`load_config`, `resolve_location`).

**`load_config` is unchanged** (`loader.py:18-27`) — `tomllib.load` (binary mode) + `Config.model_validate` already fails loud; the new `Location` validators fire here automatically.

**`resolve_location` is the reusable matcher for `--check`** (`loader.py:40-56`) — its case-insensitive `casefold()` match + "configured locations: {known}" error message is exactly what the `--check` "locations resolve / names unique" step (D-12.4) reuses:
```python
target = name.strip().casefold()
for loc in config.locations:
    if loc.name.casefold() == target:
        return loc
known = ", ".join(loc.name for loc in config.locations)
raise ValueError(f"No location named {name!r}; configured locations: {known}")
```
ADD a small `assert_unique_names(config)` helper (casefold the names, raise `ValueError` on a duplicate) following the same raise-with-clear-message style.

---

### `templates/renderer.py` (utility, transform) — ADD `validate_template` wrapping the `{token}` scan

**Analog:** itself — **the existing `_TOKEN` regex IS the validator's grammar** (D-10: wrap `render`, do not replace it).

**Reuse the SAME token regex** (`renderer.py:31`) — the validator scans with the identical grammar the renderer substitutes with, so they can never disagree:
```python
_TOKEN = re.compile(r"\{(\w+)\}")
```

**`render` stays unchanged** (`renderer.py:34-46`) — the "unknown token stays VISIBLE" guard remains as defense-in-depth (T-03-02/03); validation is a NEW sibling function that fires FIRST and aborts (D-11):
```python
def _sub(match: re.Match) -> str:
    key = match.group(1)
    return str(values[key]) if key in values else match.group(0)
return _TOKEN.sub(_sub, template_text)
```

**ADD `validate_template` (RESEARCH §Code Examples)** — scan `{m.group(1) for m in _TOKEN.finditer(text)} - CANONICAL` and raise `ValueError` listing unknown placeholders. Define `CANONICAL` = the 12-key D-09 set (must match `Forecast.placeholders()` keys exactly):
```python
CANONICAL = {"temp", "feels_like", "high", "low", "rain", "wind",
             "humidity", "conditions", "location", "date", "hint", "alert"}
def validate_template(template_text: str, allowed: set[str] = CANONICAL) -> None:
    unknown = {m.group(1) for m in _TOKEN.finditer(template_text)} - allowed
    if unknown:
        raise ValueError(f"Template uses unknown placeholder(s): {sorted(unknown)}. "
                         f"Allowed: {sorted(allowed)}")
```

**Test analog:** `tests/test_renderer.py` — extend with `-k validate` cases; the file already asserts the security guard (`test_renderer_uses_no_dangerous_substitution`, lines 78-83) — keep it.

---

### `weatherbot/cli.py` (controller, request-response) — ADD `--check` + `--geocode`; wire template validation

**Analog:** itself (`main` argparse block + `send_now` composition root) + `channels/factory.py` (registry pattern).

**`send_now` shape to preserve** (`cli.py:68-125`) — keep the injectable `client`/`channel` collaborators (testability), the single-fetch→persist→render→deliver flow, and outcome-only logging. The fetch block (lines 97-109) collapses from 4 calls to 2 (RESEARCH Pattern 1):
```python
# BEFORE (4 calls): current_imp/current_met/forecast_imp/forecast_met
# AFTER (2 calls):
onecall_imp = client.fetch_onecall(location, "imperial")
onecall_met = client.fetch_onecall(location, "metric")
forecast = Forecast.from_payloads(location, onecall_imp, onecall_met)
persist(db_path, location, forecast)                       # same object, DATA-03
text = render(load_template(config.template), forecast.placeholders())
```

**ADD template validation at the load boundary (D-10/11)** — call `validate_template(load_template(config.template))` BEFORE rendering / before the send so a typo aborts loudly on EVERY path (`--send-now` included). Put it where `load_config`/`load_settings` are called in `main` (lines 155-156), or at the top of `send_now`, so all paths share it.

**`_WeatherClient` seam to update** (`cli.py:44-65`) — keep the thin key-holding wrapper (`client`/`channel` injectability is what every test relies on); replace `fetch_current`/`fetch_forecast` methods with `fetch_onecall(location, units)` and ADD a `geocode(query)` method for the `--geocode` subcommand.

**argparse pattern to extend** (`cli.py:132-149`) — add `--check` (flag) and `--geocode "QUERY"` arguments alongside `--send-now`, following the existing `add_argument` style; dispatch in `main` (the `if not hasattr(args, "send_now")` branch, lines 151-153, is the model for "which subcommand was given").

**`--geocode` handler (D-04, LOC-03)** — calls `client.geocode(query)` and PRINTS the paste-ready `Name, ST, CC -> lat=..  lon=..` block (RESEARCH §`--geocode` output). NEVER writes config; NEVER runs on the send path.

**`--check` handler (D-12)** orchestrates, delivering nothing: (1) `load_config` (schema + IANA tz + units validators fire), (2) `validate_template` on the selected template, (3) ONE `client.fetch_onecall(first_location, "imperial")` reachability probe — `raise_for_status` surfaces the subscription-not-active 401/403 with a message distinguishing "not yet propagated — wait and retry" (Pitfall 1), (4) `assert_unique_names` + `resolve_location` for each location.

**Test analog:** NEW `tests/test_cli.py` — model it on `tests/test_send_now.py` (`_FakeClient`/`_FakeChannel` injectables, `tmp_db`/`load_fixture` fixtures) for `--check`/send-path tests, and on `tests/test_client.py`'s `httpx.MockTransport` install for the `--check` reachability call. Cases: `-k geocode` (send path never geocodes; `--geocode` prints coords), `-k check`, `-k check_reachability` (ONE call, no delivery), `-k send_now_bad_template` (typo aborts).

---

### `weatherbot/config/__init__.py` (barrel) — re-export new symbols if needed

**Analog:** itself (lines 1-16) — if a unique-name helper is added to `loader.py`, add it to the `from .loader import (...)` line and `__all__`, matching the existing re-export style.

---

### `templates/*.txt` (content) — may reference `{feels_like}` / `{hint}` / `{alert}`

**Analog:** `templates/briefing-sectioned.txt` (the default, lines 1-9) — its `Now: {temp}, {conditions}` line is where `{feels_like}` slots in (`Now: {temp}, feels {feels_like}`); `{hint}` and `{alert}` go on their own lines so they collapse cleanly when empty (D-07/08). The `compact` template must stay emoji-free (asserted by `test_renderer.py:test_compact_template_has_no_emoji`).

---

### `tests/fixtures/onecall_*.json` (NEW) — recorded One Call payloads

**Analog:** `tests/fixtures/current_imperial_clear.json` — copy its real-OpenWeather field shape (`weather[]`, `main`, `wind`, `dt`, `timezone`) and the New-York `-14400` offset convention, restructured into the One Call 3.0 shape (`current{temp,feels_like,wind_speed,humidity,uvi,weather[]}`, `daily[0]{temp{max,min},pop,uvi}`, optional `alerts[]`). Required variants (RESEARCH §Required Test Fixtures): `onecall_{imperial,metric}_clear` (no `alerts` key, low uvi), `onecall_{imperial,metric}_rainy` (`daily[0].pop > 0.4`), `onecall_imperial_alert` (+ multi-alert variant), `onecall_imperial_highuv` (`uvi >= 6`), `onecall_imperial_extreme` (feels_like <40 or >90, wind >25), `geocode_austin.json` (single + ambiguous-multi). Loaded via the existing `conftest.py:load_fixture` fixture (lines 13-23) — no conftest change needed.

---

## Shared Patterns

### Secret-safe HTTP logging
**Source:** `weatherbot/weather/client.py:33`
**Apply to:** `client.py` (One Call + geocode), `cli.py` `--check`/`--geocode` (never echo the key in error messages)
```python
logging.getLogger("httpx").setLevel(logging.WARNING)  # appid lives in params, never a logged URL
```

### Fail-loud-at-load validation (pydantic `extra="forbid"` + `field_validator`)
**Source:** `weatherbot/config/models.py:17-27`, `weatherbot/config/settings.py:14-29`
**Apply to:** every config model; the new IANA-tz and units validators on `Location`
```python
model_config = ConfigDict(extra="forbid")  # unexpected keys fail loud (CONF-03)
```

### Defensive untrusted-payload access
**Source:** `weatherbot/weather/models.py:92-99` and `store.py:128-157`
**Apply to:** the One Call mapping in `from_payloads` and the store — `payload.get(k) or {}` / `or []` (Pitfall 2: `alerts`/`rain` keys may be ABSENT, not empty)
```python
imp_main = current_imp.get("main") or {}
weather  = current_imp.get("weather") or [{}]
alerts   = payload_imp.get("alerts") or []   # absent on a clear day
```

### Parameterized-SQL + idempotent inline schema
**Source:** `weatherbot/weather/store.py:121-148`
**Apply to:** the new `weather_onecall` writes — `?` placeholders only, `CREATE TABLE IF NOT EXISTS`, `json.dumps(payload)` as `raw_json` (no string-built SQL; no request URL persisted)

### Configured-tz-is-authoritative (zoneinfo)
**Source:** NEW pattern, grounded by `models.py:_local_date_iso` (lines 31-35, being replaced) and D-03
**Apply to:** `models.py` (`{date}` + `daily[0]` "today") and `store.py` (`target_local_date`) — derive "today" from `Location.timezone` via `zoneinfo`, NOT the API `timezone` field (Pitfall 3)

### Injectable-collaborator testing (offline, no network/Discord)
**Source:** `tests/test_send_now.py:23-54` (`_FakeClient`/`_FakeChannel`) + `tests/test_client.py:24-34` (`httpx.MockTransport` via `monkeypatch`)
**Apply to:** all new/extended tests — `send_now`/`--check` accept injected `client`/`channel`; the `--check` reachability call is mocked with `MockTransport`. Fixtures `tmp_db`, `load_fixture` come from `tests/conftest.py`.

### Code-computed derived content → flat string (never template logic)
**Source:** RESEARCH §Code Examples; consumed via `models.py:placeholders()` (lines 150-162)
**Apply to:** `{hint}` (5 hardcoded thresholds, `"\n".join`) and `{alert}` (`alerts[]` summary) — computed in Python, exposed as plain strings; the template only substitutes (FEATURES anti-feature: no Jinja2/conditionals)

---

## No Analog Found

**None.** Every Phase 2 file extends, repoints, or wraps an existing Phase 1 file. The two most "new" surfaces both have tight in-repo analogs:

| File / Feature | Why it still has an analog |
|----------------|----------------------------|
| `validate_template` (new function) | Reuses `renderer.py:_TOKEN` regex grammar verbatim; sibling to `render`. |
| `--geocode` / `--check` (new subcommands) | argparse block + `send_now` composition in `cli.py`; `resolve_location` matcher; `channels/factory.py` registry-dispatch style. |
| `weather_onecall` table (new schema) | Copies the `raw_json` + `json_extract` GENERATED-column pattern from `store.py`. |
| `tests/test_cli.py` (new file) | Composes `test_send_now.py` fakes + `test_client.py` `MockTransport`. |
| `onecall_*.json` (new fixtures) | Same recorded-payload + NY-offset convention as `current_imperial_clear.json`. |

**Retired (deleted, no replacement):** `weatherbot/weather/aggregate.py`, `tests/test_aggregate.py`, and the 2.5 bucket-offset fixtures (`forecast_imperial_offset_plus.json`, `forecast_imperial_offset_minus.json`, and the other 2.5 `current_*`/`forecast_*` fixtures once `from_payloads` no longer reads them). `daily[0]` replaces bucket aggregation (D-01) — ensure nothing imports `weatherbot.weather.aggregate` after the change.

---

## Metadata

**Analog search scope:** `weatherbot/weather/`, `weatherbot/config/`, `weatherbot/channels/`, `weatherbot/cli.py`, `templates/`, `tests/`, `tests/fixtures/`
**Files scanned (read this session):** `client.py`, `models.py`, `store.py`, `aggregate.py` (head), `config/models.py`, `config/loader.py`, `config/settings.py`, `config/__init__.py`, `cli.py`, `channels/factory.py`, `templates/renderer.py`, `templates/briefing-sectioned.txt`, `tests/test_send_now.py`, `tests/test_client.py`, `tests/test_config.py`, `tests/test_renderer.py`, `tests/test_store.py` (head), `tests/conftest.py`, `tests/fixtures/current_imperial_clear.json`
**Pattern extraction date:** 2026-06-09
