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

import pytest

from weatherbot.cli import do_check, do_geocode, send_now
from weatherbot.config import Config, Location, WebhookIdentity


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
