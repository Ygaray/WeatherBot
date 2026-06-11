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

import httpx
import pytest

from weatherbot.cli import do_check, do_geocode, main, run_send_now, send_now
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
    rc = main(["--check", "--config", str(bad)])
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
    rc = main(["--check", "--config", str(bad)])
    assert rc == 1


def test_check_missing_config_file_returns_1_no_traceback(tmp_path):
    """--check on a nonexistent config path exits 1 cleanly (no traceback)."""
    rc = main(["--check", "--config", str(tmp_path / "nope.toml")])
    assert rc == 1


def test_send_now_malformed_toml_returns_1_no_traceback(tmp_path):
    """--send-now on a malformed config exits 1 cleanly rather than crashing."""
    bad = tmp_path / "config.toml"
    bad.write_text('this is = not = valid toml\n', encoding="utf-8")
    rc = main(["--send-now", "--config", str(bad)])
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
    return httpx.HTTPStatusError("Too Many Requests", request=request, response=response)


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


def test_send_now_retry_eventually_succeeds_persists_one_round(tmp_db, monkeypatch, load_fixture):
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
    out = capsys.readouterr().out + capsys.readouterr().err
    # The resolved budget values appear so a mis-tune is visible without sending.
    assert "8" in out  # attempts_per_burst default
    assert "600" in out  # burst_spread_seconds default
    assert "2700" in out  # mid_pause_seconds default
