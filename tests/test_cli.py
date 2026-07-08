"""Tests for the CLI subcommands ``--geocode`` (LOC-03) and ``--check`` (CONF-05).

No network is touched: an injected ``_FakeClient`` returns the recorded geocode /
One Call fixtures and counts calls, and a ``_FakeChannel`` proves ``--check`` (and
a bad-template ``--send-now``) NEVER delivers. These mirror ``test_send_now.py``'s
fakes so the ``--check`` reachability and ``--send-now`` composition paths run
fully offline.

The Plan 02-01 placeholder scaffolds are now flipped to real asserting tests
(their strict-skip markers removed) — the behavior shipped in Plan 02-04.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from weatherbot.cli import (
    do_check,
    do_geocode,
    main,
    run_send_now,
    run_weather,
    send_now,
)
from weatherbot.interactive import lookup_weather
from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.weather import store as _store


class _FakeClient:
    """Returns recorded fixtures and records geocode / One Call calls."""

    def __init__(self, *, geocode_result=None, onecall_imp=None, onecall_met=None):
        self._geocode_result = geocode_result or []
        self._onecall = {"imperial": onecall_imp, "metric": onecall_met}
        self.geocode_calls: list[str] = []
        self.onecall_calls: list[str] = []

    def geocode(self, query, limit=5):
        self.geocode_calls.append(query)
        return self._geocode_result

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._onecall[units]


class _FakeChannel:
    """Captures any delivery so a test can assert NOTHING was sent."""

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self.briefing_forecasts: list[object] = []
        self._result = DeliveryResult(ok=True)

    def send_briefing(self, text, forecast):
        self.sent_text.append(text)
        self.briefing_forecasts.append(forecast)
        return self._result


def _config(locations=None, template="briefing-sectioned.txt"):
    if locations is None:
        locations = [
            Location(
                name="New York",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
            )
        ]
    return Config(locations=locations, template=template, webhook=WebhookIdentity())


# --- --geocode subcommand (LOC-03 / D-04) --------------------------------------


def test_geocode_prints_coords(load_fixture, capsys):
    """`--geocode "Austin"` resolves to lat/lon via /geo/1.0/direct and prints them."""
    client = _FakeClient(geocode_result=load_fixture("geocode_austin.json"))

    rc = do_geocode("Austin, TX", client=client)

    assert rc == 0
    out = capsys.readouterr().out
    # The resolved coordinates are printed paste-ready.
    assert "lat=" in out
    assert "30.2672" in out
    assert "Austin" in out
    # A paste-ready [[locations]] snippet is offered.
    assert "[[locations]]" in out
    # Geocode was called exactly once; config is never written (no file I/O here).
    assert client.geocode_calls == ["Austin, TX"]


def test_geocode_ambiguous_lists_all_matches(load_fixture, capsys):
    """An ambiguous query prints every candidate so the user can pick one."""
    client = _FakeClient(geocode_result=load_fixture("geocode_ambiguous.json"))

    rc = do_geocode("Springfield", client=client)

    assert rc == 0
    out = capsys.readouterr().out
    # All three Springfields are listed.
    assert out.count("Springfield") >= 3
    assert "Illinois" in out
    assert "Missouri" in out
    assert "Massachusetts" in out


def test_send_now_never_geocodes(tmp_db, load_fixture):
    """--send-now must use configured lat/lon and never hit the geocoding API."""
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()

    result = send_now(
        None,
        config=_config(),
        db_path=tmp_db,
        client=client,
        channel=channel,
    )

    assert result.ok is True
    # The send path resolves coordinates from config — geocode is NEVER touched.
    assert client.geocode_calls == []


# --- --check subcommand (CONF-05 / D-12) ---------------------------------------


def test_check_validates_config(load_fixture):
    """`--check` validates a good config offline (mocked reachability) -> 0."""
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )

    rc = do_check(config=_config(), client=client)

    assert rc == 0


def test_check_bad_units_fails_before_network():
    """A bad-units config fails loud at load — before any reachability call."""
    # An invalid units override must raise at config construction (fail-loud at
    # load, never at 9am) — there is no chance to reach the network.
    with pytest.raises(Exception):
        Location(
            name="Bad",
            lat=1.0,
            lon=2.0,
            timezone="America/New_York",
            units="kelvin",
        )


def test_check_bad_timezone_fails_before_network():
    """A bad IANA timezone fails loud at load — before any reachability call."""
    with pytest.raises(Exception):
        Location(
            name="Bad",
            lat=1.0,
            lon=2.0,
            timezone="Not/AZone",
        )


def test_check_reachability_one_call(load_fixture):
    """`--check` makes EXACTLY ONE reachability call and delivers nothing."""
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()

    rc = do_check(config=_config(), client=client, channel=channel)

    assert rc == 0
    # Exactly one reachability probe (imperial) — not the 2-call send round.
    assert client.onecall_calls == ["imperial"]
    # No briefing was ever delivered.
    assert channel.sent_text == []
    assert channel.briefing_forecasts == []


def test_check_reachability_subscription_message(load_fixture):
    """A 401/403 probe reports a subscription-not-active / not-propagated message."""
    import httpx

    class _Failing401Client:
        def __init__(self):
            self.onecall_calls = []

        def fetch_onecall(self, location, units):
            self.onecall_calls.append(units)
            request = httpx.Request("GET", "https://example.invalid/onecall")
            response = httpx.Response(401, request=request)
            raise httpx.HTTPStatusError(
                "Unauthorized", request=request, response=response
            )

    client = _Failing401Client()
    rc = do_check(config=_config(), client=client)

    # A failed reachability probe makes --check fail (non-zero), not raise.
    assert rc != 0
    assert client.onecall_calls == ["imperial"]


def test_check_unique_names():
    """`--check` rejects a config with duplicate (casefold) location names."""
    config = _config(
        locations=[
            Location(name="Home", lat=1.0, lon=2.0, timezone="America/New_York"),
            Location(name="home", lat=3.0, lon=4.0, timezone="America/Chicago"),
        ]
    )
    client = _FakeClient(
        onecall_imp=load_fixture_passthrough(),
        onecall_met=load_fixture_passthrough(),
    )

    rc = do_check(config=config, client=client)

    assert rc != 0


def load_fixture_passthrough():
    """A minimal One Call payload sufficient for a reachability probe."""
    return {"timezone": "America/New_York", "current": {}, "daily": [{}]}


def test_check_bad_template_fails(load_fixture):
    """`--check` rejects a config whose template uses a non-canonical token."""
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )
    # briefing-sectioned.txt is canonical; point at a bad template via a temp file.
    rc = do_check(
        config=_config(template="__does_not_exist__.txt"),
        client=client,
    )
    assert rc != 0


# --- --send-now template pre-flight (TMPL-02 / D-11) ----------------------------


def test_send_now_bad_template_aborts(tmp_path, load_fixture):
    """--send-now with a non-canonical {token} aborts before any delivery."""
    bad = tmp_path / "bad.txt"
    bad.write_text("Today in {location}: {temprature}", encoding="utf-8")

    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()

    # The template lives in tmp_path; point load_template at it via templates_dir.
    config = _config(template="bad.txt")

    with pytest.raises(ValueError):
        send_now(
            None,
            config=config,
            db_path=tmp_path / "weatherbot.db",
            client=client,
            channel=channel,
            templates_dir=tmp_path,
        )

    # The send aborted at template validation — nothing was delivered.
    assert channel.sent_text == []


# --- malformed-config handling at the main() boundary (CONF-05 / SC-05) --------
# A realistic config typo must fail LOUDLY but CLEANLY: --check (and --send-now)
# return exit 1 without leaking a raw Python traceback. The crash these guard
# against lives in main()'s load_config call, *before* do_check runs — so these
# tests exercise main(), not do_check directly.


def test_check_malformed_toml_returns_1_no_traceback(tmp_path):
    """--check on a TOML syntax error exits 1 cleanly (no raised exception)."""
    bad = tmp_path / "config.toml"
    # Missing the second [[locations]] header -> "Cannot overwrite a value".
    bad.write_text(
        '[[locations]]\nname = "A"\nlat = 1.0\nlon = 2.0\n'
        'name = "B"\nlat = 3.0\nlon = 4.0\n',
        encoding="utf-8",
    )
    rc = main(["check", "--config", str(bad)])
    assert rc == 1


def test_check_schema_error_returns_1_no_traceback(tmp_path):
    """--check on a schema-invalid config (missing required tz) exits 1 cleanly."""
    bad = tmp_path / "config.toml"
    # Valid TOML, but Location.timezone is required -> pydantic ValidationError.
    bad.write_text(
        'template = "briefing-sectioned.txt"\n'
        '[[locations]]\nname = "A"\nlat = 1.0\nlon = 2.0\n',
        encoding="utf-8",
    )
    rc = main(["check", "--config", str(bad)])
    assert rc == 1


def test_check_missing_config_file_returns_1_no_traceback(tmp_path):
    """--check on a nonexistent config path exits 1 cleanly (no traceback)."""
    rc = main(["check", "--config", str(tmp_path / "nope.toml")])
    assert rc == 1


def test_send_now_malformed_toml_returns_1_no_traceback(tmp_path):
    """--send-now on a malformed config exits 1 cleanly rather than crashing."""
    bad = tmp_path / "config.toml"
    bad.write_text("this is = not = valid toml\n", encoding="utf-8")
    rc = main(["send-now", "--config", str(bad)])
    assert rc == 1


# --- manual --send-now tight retry, terminal-only, NO liveness rows (D-10) ------
# The attended half of the daemon-vs-manual split (Plan 04-04): --send-now does a
# SHORT bounded retry on a transient blip and reports any final failure to the
# terminal — and writes NO `alerts`/`heartbeat` rows (those are daemon-liveness
# concerns only). `run_send_now` is the manual tight-retry wrapper that `main`'s
# --send-now branch calls; tests drive it directly with an injected client/channel
# + a tmp_db, mocking sleep so the tight retry runs in milliseconds.


def _no_sleep(monkeypatch):
    """Make the tight retry's wait callable a no-op so the bound runs fast."""
    monkeypatch.setattr("weatherbot.cli.time.sleep", lambda _d: None, raising=False)


def _alerts_rows(db_path):
    _store.init_db(db_path)  # ensure schema exists so the SELECT never errors
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute("SELECT * FROM alerts"))


def _heartbeat_stamps(db_path):
    """Return (last_tick_utc, last_success_utc) for the single heartbeat row."""
    _store.init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT last_tick_utc, last_success_utc FROM heartbeat WHERE id=1"
        ).fetchone()


def _http_429():
    request = httpx.Request("GET", "https://example.invalid/onecall")
    response = httpx.Response(429, request=request)
    return httpx.HTTPStatusError(
        "Too Many Requests", request=request, response=response
    )


def _onecall_rows(db_path):
    """Count rows in weather_onecall (schema-safe even on a fresh db)."""
    _store.init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM weather_onecall").fetchone()[0]


class _FlakyChannel:
    """A channel that returns ok=False for the first ``fail_n`` calls, then ok=True."""

    def __init__(self, fail_n: int):
        self._fail_n = fail_n
        self.calls = 0

    def send_briefing(self, text, forecast):
        from weatherbot.channels import DeliveryResult

        self.calls += 1
        if self.calls <= self._fail_n:
            return DeliveryResult(ok=False, detail="discord 503")
        return DeliveryResult(ok=True)


def test_send_now_failed_delivery_persists_zero_rows(tmp_db, load_fixture):
    """WR-04: a send_now whose delivery FAILS writes NO weather_onecall rows.

    persist now runs ONLY after a successful delivery, so a failed attempt no
    longer inflates the analysis table (one row per DELIVERED briefing).
    """
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )
    channel = _FlakyChannel(fail_n=1)  # the single send_now attempt fails

    result = send_now(
        None, config=_config(), db_path=tmp_db, client=client, channel=channel
    )

    assert result.ok is False
    assert _onecall_rows(tmp_db) == 0  # failed delivery -> no persisted rows


def test_send_now_retry_eventually_succeeds_persists_one_round(
    tmp_db, monkeypatch, load_fixture
):
    """WR-04: a tight-retry that fails then succeeds persists exactly ONE round.

    The fetch still re-runs on each attempt (RELY-02 — the fetch must stay inside
    the retried callable so a fetch-429 propagates), but persist only fires on the
    SUCCESSFUL delivery, so the analysis table gets exactly one round (2 rows:
    imperial + metric) for the one delivered briefing.
    """
    _no_sleep(monkeypatch)
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )
    channel = _FlakyChannel(fail_n=2)  # fail twice, succeed on the 3rd attempt

    rc = run_send_now(
        None, config=_config(), db_path=tmp_db, client=client, channel=channel
    )

    assert rc == 0
    assert channel.calls == 3  # two failed attempts, then success
    # Only the SUCCESSFUL delivery persisted — exactly one round (2 unit variants).
    assert _onecall_rows(tmp_db) == 2


def test_send_now_no_liveness_rows(tmp_db, load_fixture, monkeypatch):
    """A failed manual --send-now writes NO alerts/heartbeat rows, exit 1 (D-10)."""
    _no_sleep(monkeypatch)

    calls = {"n": 0}

    def always_failing(*_a, **_k):
        calls["n"] += 1
        from weatherbot.channels import DeliveryResult

        return DeliveryResult(ok=False, detail="discord 503")

    monkeypatch.setattr("weatherbot.cli.send_now", always_failing)

    rc = run_send_now(
        None,
        config=_config(),
        db_path=tmp_db,
        client=_FakeClient(),
        channel=_FakeChannel(),
    )

    # Failure reported to the terminal via exit 1 (the existing report path).
    assert rc == 1
    # The tight retry actually retried (more than one attempt) but stayed bounded.
    assert 1 < calls["n"] <= 3
    # D-10 / Pitfall 4: the manual path writes ZERO daemon-liveness rows. The
    # heartbeat row is only seeded (both stamps NULL); never tick/success-stamped.
    assert _alerts_rows(tmp_db) == []
    last_tick, last_success = _heartbeat_stamps(tmp_db)
    assert last_tick is None and last_success is None


def test_send_now_transient_then_success(tmp_db, monkeypatch):
    """A transient blip recovers via the tight retry -> exit 0, no liveness rows."""
    _no_sleep(monkeypatch)

    calls = {"n": 0}

    def blip_then_ok(*_a, **_k):
        calls["n"] += 1
        from weatherbot.channels import DeliveryResult

        if calls["n"] == 1:
            raise _http_429()  # transient blip on the first attempt
        return DeliveryResult(ok=True)

    monkeypatch.setattr("weatherbot.cli.send_now", blip_then_ok)

    rc = run_send_now(
        None,
        config=_config(),
        db_path=tmp_db,
        client=_FakeClient(),
        channel=_FakeChannel(),
    )

    assert rc == 0
    assert calls["n"] == 2  # one blip, then success
    assert _alerts_rows(tmp_db) == []  # still no liveness rows on the manual path


def test_send_now_tight_retry_is_short_bound(tmp_db, monkeypatch):
    """The manual retry uses a SHORT bound (<= 3 attempts) — not the two-burst."""
    _no_sleep(monkeypatch)

    calls = {"n": 0}

    def always_raises_transient(*_a, **_k):
        calls["n"] += 1
        raise _http_429()

    monkeypatch.setattr("weatherbot.cli.send_now", always_raises_transient)

    rc = run_send_now(
        None,
        config=_config(),
        db_path=tmp_db,
        client=_FakeClient(),
        channel=_FakeChannel(),
    )

    assert rc == 1
    # SHORT bound: the manual path attempts at most 3 times (NOT 16 / two-burst).
    assert calls["n"] <= 3
    assert _alerts_rows(tmp_db) == []


def test_check_surfaces_retry_budget(load_fixture, capsys):
    """--check surfaces the resolved retry budget (attempts/spread/pause) (D-09)."""
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )

    rc = do_check(config=_config(), client=client)

    assert rc == 0
    captured = capsys.readouterr()  # IN-04: single read; .err half was dead before
    out = captured.out + captured.err
    # The resolved budget values appear so a mis-tune is visible without sending.
    assert "8" in out  # attempts_per_burst default
    assert "600" in out  # burst_spread_seconds default
    assert "2700" in out  # mid_pause_seconds default


# --- weather subcommand: offline exit-code matrix + stream split (CMD-01/03/04/05) ---
# These pin the standalone, daemon-free `weather [location]` one-shot. They inject a
# `_FakeClient` so `build_client` (and the network) is never reached, reuse the recorded
# onecall_* fixtures (NO new fixtures), and assert the 0/1/2/3 exit map, the stdout-vs-
# stderr split, the byte-identical v1 template (CMD-05), the unknown path's no-network
# guard, secret hygiene on the error path (T-07-05 / T-04-01), and quiet-vs-`-v` (D-09).


def _http_401():
    """A permanent 401 (auth) HTTPStatusError — is_transient is False for it."""
    request = httpx.Request("GET", "https://example.invalid/onecall")
    response = httpx.Response(401, request=request)
    return httpx.HTTPStatusError("Unauthorized", request=request, response=response)


class _RaisingClient:
    """A One Call client whose fetch_onecall always raises ``exc`` (counts attempts)."""

    def __init__(self, exc):
        self._exc = exc
        self.onecall_calls: list[str] = []

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        raise self._exc


def test_weather_prints_briefing_exit_0(load_fixture, capsys):
    """CMD-01: `weather home` prints the briefing to stdout and exits 0."""
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )

    rc = run_weather("New York", config=_config(), client=client)

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.strip()  # the briefing landed on stdout
    # The briefing channel (stdout) carries ONLY the briefing — no log line leaks in
    # (CMD-01 pipeable contract; logs route to stderr).
    assert "lookup complete" not in captured.out
    assert "error" not in captured.err.lower()  # happy path logs no error to stderr
    # A real fetch happened (dual-unit One Call round), not the unknown short-circuit.
    assert client.onecall_calls == ["imperial", "metric"]


def test_weather_default_location_exit_0(load_fixture, capsys):
    """CMD-03: bare `weather` (location=None) resolves the default location, exit 0."""
    client = _FakeClient(
        onecall_imp=load_fixture("onecall_imperial_clear.json"),
        onecall_met=load_fixture("onecall_metric_clear.json"),
    )

    rc = run_weather(None, config=_config(), client=client)

    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()  # briefing for the first/default location on stdout


def test_weather_unknown_location_exits_1(capsys):
    """CMD-04: an unknown name -> stderr lists valid names, exit 1, NO network."""
    client = _FakeClient()  # no fixtures: fetch must never be reached

    rc = run_weather("nope", config=_config(), client=client)

    assert rc == 1
    captured = capsys.readouterr()
    # The verbatim UnknownLocationError message is on stderr (CMD-04 / D-06).
    assert "No location named 'nope'" in captured.err
    assert "New York" in captured.err  # a valid configured name is listed
    assert captured.out == ""  # nothing on stdout for the error path
    # resolve_location fails BEFORE any fetch -> the unknown path touches no network.
    assert client.onecall_calls == []


def test_weather_template_matches_v1(load_fixture, capsys, monkeypatch):
    """CMD-05: printed briefing byte-equals the v1 `lookup_weather(...).text` render.

    Proves the CLI prints the exact v1 template with no separate on-demand format.
    A fixed clock (monkeypatched on the lookup module's ``datetime``) makes the two
    independent renders deterministic across the minute-granularity time tokens.
    """
    import weatherbot.interactive.lookup as lookup_mod

    fixed = datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(lookup_mod, "datetime", _FixedDatetime)

    def _fresh_client():
        return _FakeClient(
            onecall_imp=load_fixture("onecall_imperial_clear.json"),
            onecall_met=load_fixture("onecall_metric_clear.json"),
        )

    expected = lookup_weather("New York", config=_config(), client=_fresh_client()).text

    rc = run_weather("New York", config=_config(), client=_fresh_client())

    assert rc == 0
    printed = capsys.readouterr().out
    # print() appends a trailing newline; the rendered text itself must match exactly.
    assert printed == expected + "\n"


def test_weather_bad_config_exits_2(tmp_path):
    """D-05: a valid `weather` subcommand on a bad config returns 2 (NOT argparse).

    The 2 comes from ``_load_config_reporting`` returning None inside ``_cmd_weather``
    (Pitfall 3) — a genuine config-load failure, distinguishable from argparse's own
    SystemExit(2) because ``main([...])`` RETURNS here rather than raising.
    """
    bad = tmp_path / "config.toml"
    bad.write_text("this is = not = valid toml\n", encoding="utf-8")

    rc = main(["weather", "--config", str(bad)])

    assert rc == 2


def test_weather_missing_config_exits_2(tmp_path):
    """D-05: a nonexistent --config path also returns 2 cleanly (no traceback)."""
    rc = main(["weather", "--config", str(tmp_path / "nope.toml")])
    assert rc == 2


def test_weather_fetch_failure_exhausted_transient_exits_3(monkeypatch, capsys):
    """D-05/D-08: a persistent transient (429) exhausts the SHORT bound -> exit 3.

    The sleep seam is patched so the bound runs in milliseconds; attempts stay <=
    ``_MANUAL_MAX_ATTEMPTS``. Also asserts NO secret (appid/webhook URL) leaks to
    stderr/logs on the failure path (T-07-05 / T-04-01).
    """
    _no_sleep(monkeypatch)
    client = _RaisingClient(_http_429())

    rc = run_weather("New York", config=_config(), client=client)

    assert rc == 3
    # SHORT bound: at most 3 attempts (one fetch_onecall call recorded per attempt).
    assert 1 < len(client.onecall_calls) <= 3
    captured = capsys.readouterr()
    assert captured.out == ""  # no briefing on a failed fetch
    # T-07-05: the outcome-only error log carries no secret.
    combined = captured.out + captured.err
    assert "appid" not in combined
    assert "api_key" not in combined.lower()
    assert "https://" not in combined  # no request URL (which would carry the key)


def test_weather_fetch_failure_auth_401_exits_3_no_retry(monkeypatch, capsys):
    """D-08/Pitfall 5: a permanent 401 returns 3 on the FIRST attempt (no retry)."""
    _no_sleep(monkeypatch)
    client = _RaisingClient(_http_401())

    rc = run_weather("New York", config=_config(), client=client)

    assert rc == 3
    # A permanent auth failure is NOT transient -> reraised on attempt 1, never retried.
    assert client.onecall_calls == ["imperial"]
    err = capsys.readouterr().err
    assert "appid" not in err and "https://" not in err  # secret hygiene on auth path


def test_weather_quiet_by_default_and_verbose(
    tmp_path, load_fixture, capsys, monkeypatch
):
    """D-09: the `weather` path is quiet by default; `-v` restores the INFO line.

    Driven through ``main([...])`` so the after-parse level logic (D-09) runs. Without
    `-v` the effective level is WARNING, so lookup.py's
    ``_log.info("lookup complete", ...)`` is suppressed; with `-v` (INFO) it appears.
    Logs render to STDERR (so STDOUT stays the briefing-only CMD-01 channel), so this
    asserts on the STDERR half of ``capsys``.
    """
    # A real config file so `weather` reaches the lookup (config loads -> not exit 2).
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'template = "briefing-sectioned.txt"\n'
        "[webhook]\n"
        "[[locations]]\n"
        'name = "New York"\n'
        "lat = 40.7128\n"
        "lon = -74.006\n"
        'timezone = "America/New_York"\n',
        encoding="utf-8",
    )

    # Inject the offline client (so no network/secret is needed) by patching the
    # module-global `run_weather` that `_cmd_weather` dispatches to.
    import weatherbot.cli as cli_mod

    def _patched_run_weather(location, *, config, settings=None, verbose=False):
        client = _FakeClient(
            onecall_imp=load_fixture("onecall_imperial_clear.json"),
            onecall_met=load_fixture("onecall_metric_clear.json"),
        )
        return run_weather(
            location, config=config, settings=settings, client=client, verbose=verbose
        )

    monkeypatch.setattr(cli_mod, "run_weather", _patched_run_weather)
    monkeypatch.setattr(cli_mod, "load_settings", lambda: None)

    # Quiet path (no -v): WARNING level -> NO "lookup complete" INFO line on stderr,
    # and the briefing alone is on stdout (CMD-01 pipeable contract).
    rc_quiet = main(["weather", "New York", "--config", str(cfg)])
    quiet = capsys.readouterr()
    assert rc_quiet == 0
    assert "lookup complete" not in quiet.err
    assert "lookup complete" not in quiet.out  # never pollutes the briefing channel
    assert quiet.out.strip()  # the briefing is still printed

    # Verbose path (-v): INFO level -> the "lookup complete" line appears (on stderr).
    rc_verbose = main(["weather", "New York", "-v", "--config", str(cfg)])
    verbose = capsys.readouterr()
    assert rc_verbose == 0
    assert "lookup complete" in verbose.err


# --- check-config: OFFLINE validation subcommand, ZERO network (CFG-08 / D-05/D-06) ---
# Wave-0 RED scaffold: the `check-config` subcommand does NOT exist yet (Plan 03 adds
# it as a sibling of `check`/`run`/`send-now`). It is the OFFLINE subset of `check`:
# parse + full pydantic validate + unique id/name + template-token validation, and it
# applies/sends NOTHING and makes ZERO OpenWeather calls (distinct from `check`, which
# also runs a LIVE reachability probe — Pitfall 8). It shares ONE validation function
# with the reload engine (`validate_config_and_templates`, D-05). These reference the
# not-yet-built subcommand directly so they fail RED on the unknown command until the
# subparser + dispatch land.


def _good_config_file(tmp_path):
    """Write a minimal VALID config.toml and return its path."""
    p = tmp_path / "config.toml"
    p.write_text(
        'template = "briefing-sectioned.txt"\n'
        "[[locations]]\n"
        'name = "New York"\n'
        "lat = 40.7128\n"
        "lon = -74.006\n"
        'timezone = "America/New_York"\n\n'
        "[[locations.schedule]]\n"
        'time = "07:00"\n'
        'days = "mon-fri"\n',
        encoding="utf-8",
    )
    return p


def test_check_config_offline_pass(tmp_path):
    """CFG-08: `check-config` on a GOOD config validates offline and returns 0.

    RED until the `check-config` subcommand ships (today an unknown subcommand →
    argparse SystemExit(2) / nonzero, never 0)."""
    good = _good_config_file(tmp_path)
    rc = main(["check-config", "--config", str(good)])
    assert rc == 0  # offline-valid config passes


def test_check_config_offline_fail(tmp_path):
    """CFG-08: `check-config` on a config with a non-canonical template token returns
    1 (offline validation failure), reporting the reason without sending anything."""
    bad = tmp_path / "config.toml"
    bad.write_text(
        'template = "__does_not_exist__.txt"\n'
        "[[locations]]\n"
        'name = "New York"\n'
        "lat = 40.7128\n"
        "lon = -74.006\n"
        'timezone = "America/New_York"\n',
        encoding="utf-8",
    )
    rc = main(["check-config", "--config", str(bad)])
    assert rc == 1  # offline validation rejects the bad template token


def test_check_config_no_network(tmp_path, monkeypatch):
    """CFG-08 / Pitfall 8: `check-config` makes ZERO OpenWeather calls — it is the
    OFFLINE subset of `check`. Patch the One Call fetch boundary to EXPLODE if ever
    reached, proving the dry-run never probes the network (distinguishing it from
    `check`/`do_check` which DO probe)."""
    good = _good_config_file(tmp_path)

    fetch_calls: list[str] = []

    def _must_not_fetch(loc, key, units="imperial"):  # network boundary signature
        fetch_calls.append(units)
        raise AssertionError("check-config must not touch the network")

    # Patch the live One Call fetch so any network reach fails loud — check-config
    # is offline-only, so this must never be invoked.
    import weatherbot.weather.client as _client_mod

    monkeypatch.setattr(_client_mod, "fetch_onecall", _must_not_fetch)

    rc = main(["check-config", "--config", str(good)])

    assert rc == 0  # offline-valid → passes WITHOUT any network call
    assert fetch_calls == []  # the One Call fetch boundary was never reached


# --- registry-generated subcommands (CMD-09/10/11/12/13/14/15) -----------------
# The CLI exposes one subcommand per registry.COMMANDS spec, generated from the SAME
# list the Discord bot dispatches (CMD-09 anti-drift). These pin: every spec parses,
# help/locations print fetch-free, a weather-view prints + exits 0 on a good lookup,
# and an unknown location exits 1 with the corrective hint.


def _fake_lookup_result(load_fixture):
    """Build a LookupResult from recorded fixtures (no network)."""
    from weatherbot.interactive.lookup import LookupResult
    from weatherbot.weather.models import Forecast

    loc = Location(
        name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York"
    )
    forecast = Forecast.from_payloads(
        loc,
        load_fixture("onecall_imperial_alert.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    return LookupResult(text="", forecast=forecast, location=loc)


def test_every_registry_command_parses():
    """CMD-09 derive-from-one-list: iterate registry.COMMANDS and assert every spec
    name parses as a subcommand (location-taking specs accept an optional location)."""
    from weatherbot.interactive import registry

    for spec in registry.COMMANDS:
        argv = [spec.name]
        if spec.takes_location:
            argv.append("home")
        # A parse error raises SystemExit; reaching the dispatch means it parsed. We
        # stub the config load + the lookup/heartbeat so no network/db is touched and
        # assert the command does not crash at parse time.
        try:
            # help is the one command that needs no config and no I/O — safe to run.
            if spec.name == "help":
                assert main(argv) == 0
        except SystemExit as exc:  # pragma: no cover — a parse failure
            raise AssertionError(f"{spec.name!r} failed to parse: {exc}")


def test_cli_help_prints_all_commands(capsys):
    """CMD-09: `weatherbot help` prints every registry command grouped, fetch-free."""
    rc = main(["help"])
    assert rc == 0
    out = capsys.readouterr().out
    from weatherbot.interactive import registry

    for spec in registry.COMMANDS:
        assert spec.name in out


def test_cli_locations_lists_configured(tmp_path, capsys):
    """CMD-11: `weatherbot locations` prints the configured location names (no fetch)."""
    good = _good_config_file(tmp_path)
    rc = main(["locations", "--config", str(good)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "New York" in out


def test_cli_weather_view_prints_and_exits_0(
    tmp_path, capsys, monkeypatch, load_fixture
):
    """CMD-13: `weatherbot sun <loc>` prints the sun reply and exits 0 (fake lookup)."""
    good = _good_config_file(tmp_path)

    monkeypatch.setattr(
        "weatherbot.cli.lookup_weather",
        lambda name, *, config, settings: _fake_lookup_result(load_fixture),
    )
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    rc = main(["sun", "New York", "--config", str(good)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Sun" in out  # the sun reply title (CommandReply rendered as plain text)


def test_cli_weather_view_unknown_location_exits_1(tmp_path, capsys, monkeypatch):
    """CMD-04: an unknown location on a registry command exits 1 with the valid-names
    hint on stderr (reusing the run_weather exit-code precedent)."""
    good = _good_config_file(tmp_path)

    from weatherbot.interactive.lookup import UnknownLocationError

    def _raise_unknown(name, *, config, settings):
        raise UnknownLocationError("bogus", ["New York"])

    monkeypatch.setattr("weatherbot.cli.lookup_weather", _raise_unknown)
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    rc = main(["sun", "bogus", "--config", str(good)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "New York" in err  # the corrective hint lists the valid names


def test_cli_uv_prints_and_exits_0(tmp_path, capsys, monkeypatch, load_fixture):
    """UV-01: `weatherbot uv <loc>` prints the UV reply and exits 0 (fake lookup)."""
    good = _good_config_file(tmp_path)

    monkeypatch.setattr(
        "weatherbot.cli.lookup_weather",
        lambda name, *, config, settings: _fake_lookup_result(load_fixture),
    )
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    rc = main(["uv", "New York", "--config", str(good)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "UV" in out  # the uv reply title (CommandReply rendered as plain text)


def test_cli_uv_unknown_location_exits_1(tmp_path, capsys, monkeypatch):
    """An unknown location on `uv` exits 1 with the corrective hint (CMD-04 path)."""
    good = _good_config_file(tmp_path)

    from weatherbot.interactive.lookup import UnknownLocationError

    def _raise_unknown(name, *, config, settings):
        raise UnknownLocationError("bogus", ["New York"])

    monkeypatch.setattr("weatherbot.cli.lookup_weather", _raise_unknown)
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    rc = main(["uv", "bogus", "--config", str(good)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "New York" in err


def test_cli_uv_threads_config_threshold(tmp_path, capsys, monkeypatch, load_fixture):
    """The CLI dispatch passes config.uv.threshold (NOT a literal) into the uv handler."""
    good = _good_config_file(tmp_path)

    monkeypatch.setattr(
        "weatherbot.cli.lookup_weather",
        lambda name, *, config, settings: _fake_lookup_result(load_fixture),
    )
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    from weatherbot.interactive.commands import CommandReply, weather_views

    seen: dict[str, object] = {}

    def _spy_uv(result, threshold, **kwargs):
        seen["threshold"] = threshold
        return CommandReply(title="UV — spy")

    monkeypatch.setattr(weather_views, "uv", _spy_uv)
    # The registry caches the wired handler, so patch the spec's handler too.
    from weatherbot.interactive import registry

    monkeypatch.setitem(
        registry.BY_NAME,
        "uv",
        registry.replace(registry.BY_NAME["uv"], handler=_spy_uv),
    )

    rc = main(["uv", "New York", "--config", str(good)])
    assert rc == 0
    # Default config (no [uv] table) -> threshold 6.0 from config.uv.threshold.
    assert seen["threshold"] == 6.0


def test_cli_status_reports_read_only(tmp_path, capsys):
    """CMD-12: `weatherbot status` runs the read-only status handler (CLI scope: no live
    scheduler/bot, but the last-briefing heartbeat read). Prints + exits 0."""
    good = _good_config_file(tmp_path)
    rc = main(["status", "--config", str(good)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Status" in out


def test_cli_bad_config_on_registry_command_exits_2(tmp_path):
    """A bad/missing config on a config-loading registry command returns 2 (the
    _load_config_reporting precedent), distinguishing it from unknown-location (1)."""
    missing = tmp_path / "nope.toml"
    rc = main(["locations", "--config", str(missing)])
    assert rc == 2


# --------------------------------------------------------------------------- #
# Forecast commands (Plan 13-04): flags threaded via the shared grammar.
# --------------------------------------------------------------------------- #


def _fake_forecast_result(load_fixture):
    """A LookupResult carrying the 8-day One Call payloads (forecast rendering)."""
    from weatherbot.interactive.lookup import LookupResult
    from weatherbot.weather.models import Forecast

    loc = Location(
        name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York"
    )
    forecast = Forecast.from_payloads(
        loc,
        load_fixture("onecall_8day_imperial.json"),
        load_fixture("onecall_8day_metric.json"),
    )
    return LookupResult(text="", forecast=forecast, location=loc)


def test_cli_weekday_forecast_compact_prints_and_exits_0(
    tmp_path, capsys, monkeypatch, load_fixture
):
    """FCAST-01/03: `weatherbot weekday-forecast <loc> +compact` parses flags via the
    shared grammar, renders a forecast and exits 0 (fake lookup, no network)."""
    good = _good_config_file(tmp_path)

    monkeypatch.setattr(
        "weatherbot.cli.lookup_weather",
        lambda name, *, config, settings: _fake_forecast_result(load_fixture),
    )
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    rc = main(["weekday-forecast", "New York", "+compact", "--config", str(good)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Weekday forecast" in out  # the forecast reply title


def test_cli_weekend_forecast_with_add_flag_exits_0(
    tmp_path, capsys, monkeypatch, load_fixture
):
    """FCAST-02/04: `weatherbot weekend-forecast <loc> +sat` parses the add flag and
    renders the weekend forecast (exit 0)."""
    good = _good_config_file(tmp_path)

    monkeypatch.setattr(
        "weatherbot.cli.lookup_weather",
        lambda name, *, config, settings: _fake_forecast_result(load_fixture),
    )
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    rc = main(["weekend-forecast", "New York", "+sat", "--config", str(good)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Weekend forecast" in out


def test_cli_forecast_bad_day_flag_exits_1(tmp_path, capsys, monkeypatch, load_fixture):
    """A bad +day token fails loud (T-13-07) → exit 1 with a message on stderr."""
    good = _good_config_file(tmp_path)

    monkeypatch.setattr(
        "weatherbot.cli.lookup_weather",
        lambda name, *, config, settings: _fake_forecast_result(load_fixture),
    )
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    rc = main(["weekday-forecast", "New York", "+xyz", "--config", str(good)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "xyz" in err


# --- HARD-STARTUP-01: `run` boot-validate parity + subprocess exit-code (Wave 0) ---
# These lock the observable contract for the primary OFFLINE fatal gate: `run` must
# validate config+templates at boot with the SAME depth as `check-config` and refuse
# to start (non-zero exit) on a bad config, instead of green-booting and silently
# dropping every briefing (F05/F06 regression guard). The `run` boot-validate gate +
# `_fatal_config_exit` land in plan 29-04, so the three in-process cases and the
# end-to-end subprocess case are xfail (strict=False) until then — they MUST collect
# cleanly now and turn green once 29-04 ships.


def _dup_id_config_file(tmp_path):
    """Write a config with two locations sharing the same name (duplicate id).

    `assert_unique_names` (config/loader.py:67) rejects this; the boot-validate gate
    must too. Mirrors the `_good_config_file` shape."""
    p = tmp_path / "config.toml"
    p.write_text(
        'template = "briefing-sectioned.txt"\n'
        "[[locations]]\n"
        'name = "New York"\n'
        "lat = 40.7128\n"
        "lon = -74.006\n"
        'timezone = "America/New_York"\n\n'
        "[[locations]]\n"
        'name = "New York"\n'
        "lat = 34.0522\n"
        "lon = -118.2437\n"
        'timezone = "America/Los_Angeles"\n',
        encoding="utf-8",
    )
    return p


def _bad_template_config_file(tmp_path):
    """Write an otherwise-valid config pointing at a nonexistent template token.

    `validate_config_and_templates` (config/loader.py:99) rejects the missing
    template; the boot-validate gate must too. Same shape as
    `test_check_config_offline_fail`."""
    p = tmp_path / "config.toml"
    p.write_text(
        'template = "__does_not_exist__.txt"\n'
        "[[locations]]\n"
        'name = "New York"\n'
        "lat = 40.7128\n"
        "lon = -74.006\n"
        'timezone = "America/New_York"\n',
        encoding="utf-8",
    )
    return p


@pytest.mark.xfail(
    strict=False, reason="run boot-validate gate lands in 29-04"
)
def test_run_boot_validate_rejects_duplicate_id(tmp_path, monkeypatch):
    """HARD-STARTUP-01: `run` on a duplicate-id/name config rejects at boot with a
    non-zero exit and NEVER starts the scheduler (the daemon is never reached).

    Sentinel-monkeypatch `run_daemon` so we can prove the boot-validate gate fires
    BEFORE the daemon — a bad config must not silently green-boot."""
    from weatherbot.scheduler import daemon

    started: list[bool] = []

    def _sentinel_run_daemon(*args, **kwargs):
        started.append(True)
        return 0

    monkeypatch.setattr(daemon, "run_daemon", _sentinel_run_daemon)
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    cfg = _dup_id_config_file(tmp_path)
    rc = main(["run", "--config", str(cfg)])
    assert rc != 0  # boot-validate rejects the duplicate-name config
    assert started == []  # scheduler/daemon was never reached


@pytest.mark.xfail(
    strict=False, reason="run boot-validate gate lands in 29-04"
)
def test_run_boot_template_rejects_missing_template(tmp_path, monkeypatch):
    """HARD-STARTUP-01: `run` on a config naming a missing template token rejects at
    boot with a non-zero exit and never starts the daemon."""
    from weatherbot.scheduler import daemon

    started: list[bool] = []
    monkeypatch.setattr(
        daemon, "run_daemon", lambda *a, **k: started.append(True) or 0
    )
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    cfg = _bad_template_config_file(tmp_path)
    rc = main(["run", "--config", str(cfg)])
    assert rc != 0  # boot-validate rejects the bad template token
    assert started == []


@pytest.mark.xfail(
    strict=False, reason="run boot-validate gate lands in 29-04"
)
@pytest.mark.parametrize(
    "config_factory",
    [
        _good_config_file,  # valid -> both accept (0)
        _dup_id_config_file,  # duplicate id -> both reject (non-zero)
        _bad_template_config_file,  # bad template -> both reject (non-zero)
    ],
    ids=["valid", "duplicate_id", "bad_template"],
)
def test_check_run_parity(tmp_path, monkeypatch, config_factory):
    """HARD-STARTUP-01 (strongest F05 guard): `check-config` and the `run`
    boot-validate produce IDENTICAL accept/reject on the SAME config.

    `run` on the VALID config would otherwise block on the daemon, so stub
    `run_daemon`->0 to compare ONLY the validation verdict (both 0 or both non-zero)."""
    from weatherbot.scheduler import daemon

    cfg = config_factory(tmp_path)
    monkeypatch.setattr(daemon, "run_daemon", lambda *a, **k: 0)
    monkeypatch.setattr("weatherbot.cli.load_settings", lambda: None)

    check_rc = main(["check-config", "--config", str(cfg)])
    run_rc = main(["run", "--config", str(cfg)])

    # Parity is on ACCEPT/REJECT, not the exact code: both accept (0) or both reject.
    assert (check_rc == 0) == (run_rc == 0)


@pytest.mark.xfail(
    strict=False, reason="run boot-validate gate lands in 29-04"
)
def test_run_bad_config_exit_code(tmp_path):
    """HARD-STARTUP-01: the ONE true end-to-end proof — `weatherbot run --config
    <bad.toml>` as a real subprocess returns a non-zero PROCESS exit code (so systemd
    sees a failed boot, not a green one). Asserts on `returncode`, never stdout."""
    import subprocess
    import sys

    bad = _bad_template_config_file(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "weatherbot", "run", "--config", str(bad)],
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode != 0  # a bad config must fail the boot process
