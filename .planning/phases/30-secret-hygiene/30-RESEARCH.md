# Phase 30: Secret Hygiene - Research

**Researched:** 2026-07-09
**Domain:** Python exception hygiene / httpx error surfacing / structlog log redaction / pytest capture
**Confidence:** HIGH (all key claims verified against the installed httpx 0.28.1 and the live structlog config in this repo)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 — Fix at the root + a global backstop (belt-and-suspenders).** Primary fix at the source in `client.py`: catch `httpx.HTTPStatusError` in `fetch_onecall` AND `geocode`, redact the `appid` value from the surfaced message, and re-raise so the exception object is clean everywhere it is later logged. Makes the leak unreachable rather than patching each logging site.
- **D-02 — Add a global logging backstop** that scrubs any `appid=<value>` from rendered log output (event fields AND tracebacks) as a safety net for future code. Chosen because HARD-SEC-01 is a security requirement and the milestone posture is correctness-first / no-backlog.
- **D-03 — Placeholder, not deletion.** Replace only the key value with a placeholder: `appid=***` (or `appid=REDACTED`). Keep the failing endpoint URL and HTTP status visible so the live daemon stays diagnosable. Do NOT strip the whole query string.
- **HARD CONSTRAINT — exception type is LOCKED.** The re-raised error MUST stay `httpx.HTTPStatusError` with `.response` (and thus `.response.status_code`) intact. 6+ call sites branch on this (`cli.py:291/367/421/692`, `selfcheck.py:127`, `daemon.py:263`). The fix redacts the **message**, never the type.

### Claude's Discretion
- **Backstop insertion point.** (a) `_LiveStderr.write` choke point (both configure sites route through `PrintLoggerFactory(file=_LiveStderr())`) — renderer-agnostic, catches everything. (b) A custom structlog processor — but configs pass no explicit `processors=`, so this means re-declaring the default chain. **Lean toward (a).** → Research VALIDATES (a): see Pattern 2.
- **Redaction helper shape** — a small pure function `redact_appid(text) -> text`. Candidate home: `weatherbot/weather/client.py` or a tiny `weatherbot/_redact.py`.
- **Regression test shape** — fake sentinel key, mock a 401/403, assert the sentinel never appears in `str(exc)` NOR captured stderr, for: onecall, geocode, Discord end-to-end (`bot.py:507`). Also assert `.response.status_code` still readable (type-contract canary).

### Deferred Ideas (OUT OF SCOPE)
- **Promote the redaction backstop to the `yahir_reusable_bot` hub.** Build it app-local now (optionally under `_promotable/` if the seam is clean); flag as a hub-promotion candidate. Do NOT cut a hub tag (human-gated).
- **Broader secret-scanning of other params (lat/lon/location names)** — not secrets, out of scope for HARD-SEC-01.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-SEC-01 | The OpenWeather `appid` (API key) must never escape into an exception message, traceback, or log line on the fetch-failure paths (onecall + geocode) or the Discord inbound error path. | Root fix = redacted `HTTPStatusError` re-raise with `from None` (Pattern 1 — verified preserves `.response`/`.response.status_code` and suppresses the key-bearing `__context__`). Backstop = regex scrub in `_LiveStderr.write` (Pattern 2 — verified sees fully-rendered traceback in one write). Regression test = `capsys`, NOT `caplog` (Pitfall 2 — verified caplog captures 0 records). |
</phase_requirements>

## Summary

The leak is fully understood and reproduced at the source. `httpx.Response.raise_for_status()` (httpx 0.28.1, `_models.py:809-829`) builds its message as `"{error_type} '{status} {reason}' for url '{0.url}'\n..."` where `{0.url}` is `response.url` — the **full request URL including the query string**, which carries `appid=<key>` in the clear. That message becomes `str(HTTPStatusError)`. When `bot.py:507`'s `_log.exception(...)` renders the traceback, the key hits stderr.

The root fix is a **redacted re-raise** at both `client.py` raise sites: catch the `HTTPStatusError`, scrub `appid=<value>` → `appid=***` in the message, and re-raise a *new* `httpx.HTTPStatusError(scrubbed_message, request=exc.request, response=exc.response)` **`from None`**. Verified against installed httpx: the constructor signature is `HTTPStatusError(message, *, request, response)` (both keyword-only, required); the new exception preserves `.request`, `.response`, and `.response.status_code` exactly (type contract intact). The **`from None`** is load-bearing and non-obvious: without it, the original key-bearing exception still prints through the `__context__` chain ("During handling of the above exception, another exception occurred:") in the full traceback that `_log.exception` emits — so `str(exc)` would be clean but the traceback would still leak. Verified empirically both ways.

The backstop (D-Discretion option a) is validated: under the current `PrintLoggerFactory(file=_LiveStderr())` config (no explicit `processors=`), structlog renders the **entire event line plus the fully-formatted traceback in a single `write()` call** to the proxy stream. Wrapping `_LiveStderr.write` with a regex scrub therefore sees the complete `appid=...` token intact (never split across writes) and is renderer-agnostic. The regression test must use **`capsys`, not `caplog`** — verified that `caplog` captures 0 records because `PrintLoggerFactory` bypasses stdlib logging entirely.

**Primary recommendation:** Add `weatherbot/_redact.py` with a pure `redact_appid(text: str) -> str` (regex `(appid=)[^&\s"'<>\\]+` → `\1***`, case-insensitive). Wrap both `client.py` raise sites with a redacted `HTTPStatusError(...) from None` re-raise using that helper. Wrap `_LiveStderr.write` in `__init__.py` to pass its argument through `redact_appid` before forwarding to `sys.stderr`. Add a `tests/test_redact_hygiene.py` regression suite driving onecall/geocode/`on_message` via the existing `MockTransport` + `fake_discord_message` patterns, asserting the sentinel is absent from `str(exc)` and from `capsys.readouterr().err`, plus a `.response.status_code` canary.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Redact key from surfaced fetch errors | API-client layer (`weatherbot/weather/client.py`) | — | The exception object is minted here (`raise_for_status`); cleaning it at the source makes it clean at every downstream logging site. |
| Global log-output backstop | Logging infrastructure (`weatherbot/__init__.py` `_LiveStderr`) | — | Single stderr choke point shared by both `structlog.configure` sites; renderer-agnostic last line of defense. |
| Pure redaction helper | Shared util (`weatherbot/_redact.py`) | `_promotable/` (hub candidate, deferred) | One obvious pure function reused by both the source fix and the backstop; app-local per Deferred Ideas. |
| Regression assertion | Test tier (`tests/`) | — | Proves the leak stays closed on all three paths + the type contract. |

## Standard Stack

No new dependencies. This phase is code + config only, using libraries already pinned.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 (pinned in `uv.lock`) | The `HTTPStatusError` type being redacted/re-raised | Already the app-wide HTTP client; `.response.status_code` is the app's fetch-failure currency. `[VERIFIED: uv.lock + .venv source inspection]` |
| structlog | 26.x (pinned) | Log rendering through `PrintLoggerFactory(file=_LiveStderr())` | Already the project's logging layer; the backstop hooks its output stream, not its processor chain. `[VERIFIED: __init__.py:40-44]` |
| `re` (stdlib) | built-in | The redaction regex | Standard, no dependency; regex boundary behavior verified. `[VERIFIED]` |
| pytest | 9.0.3 (pinned) | Regression test | Existing framework; `capsys` fixture is the correct capture mechanism (see Pitfall 2). `[VERIFIED: pyproject.toml]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Fresh `HTTPStatusError(...)` re-raise | Mutate `exc.args` in place then `raise exc` | In-place mutation keeps the identical object (no re-raise cost) BUT the original traceback still points at `raise_for_status` and, critically, `exc.args[0]` is the only carrier of the message — you must also ensure no other attribute echoes the URL. Re-raising a fresh object with `from None` is cleaner and provably drops the key-bearing `__context__`. **Recommend the fresh re-raise.** |
| `_LiveStderr.write` backstop | Custom structlog processor in the chain | Processor requires re-declaring the full default processor chain at BOTH configure sites (configs currently pass no `processors=`), and only sees the event dict — not necessarily the formatted traceback the same way. The `write` choke point is renderer-agnostic and single-point. **Recommend the `write` wrapper (matches D-Discretion lean).** |

**Installation:** none — no `uv add`.

## Package Legitimacy Audit

Not applicable — this phase installs no external packages. All libraries touched (`httpx`, `structlog`, `pytest`) are already pinned in `uv.lock`.

## Architecture Patterns

### System Architecture Diagram

```
                       OpenWeather API (401/403/5xx)
                                  │
                                  ▼
        ┌─────────────────────────────────────────────┐
        │ client.py  fetch_onecall / geocode           │
        │   response.raise_for_status()                │
        │     └─ raises HTTPStatusError                 │
        │        message = "...for url '<URL w/ appid>'"│  ◄── LEAK ORIGIN
        │                                               │
        │  ┌── ROOT FIX (D-01) ──────────────────────┐ │
        │  │ except HTTPStatusError as exc:          │ │
        │  │   scrubbed = redact_appid(str(exc))     │ │
        │  │   raise HTTPStatusError(                 │ │
        │  │     scrubbed, request=exc.request,       │ │
        │  │     response=exc.response) from None     │ │  ◄── clean object, type intact
        │  └──────────────────────────────────────────┘ │
        └───────────────┬───────────────────────────────┘
                        │ clean HTTPStatusError (.response.status_code intact)
      ┌─────────────────┼──────────────────────────────────────┐
      ▼                 ▼                                        ▼
 cli.py fetch      daemon.py retry                     bot.py on_message (F12)
 (status= only)    classification                      except Exception:
      │            (.response)                            _log.exception(...)
      │                 │                                      │
      │                 │                                      ▼
      │                 │                          structlog PrintLogger renders
      │                 │                          event + FULL traceback
      │                 │                                      │
      └─────────────────┴──────────────────────────────────────┤
                                                                ▼
                                          ┌──────────────────────────────────┐
                                          │ _LiveStderr.write(data)          │
                                          │  ┌── BACKSTOP (D-02) ──────────┐ │
                                          │  │ data = redact_appid(data)   │ │  ◄── renderer-agnostic
                                          │  └──────────────────────────────┘ │
                                          │  sys.stderr.write(data)          │
                                          └──────────────────────────────────┘
                                                          │
                                                          ▼
                                                       STDERR (clean)
```

### Component Responsibilities
| File | Responsibility | Change |
|------|----------------|--------|
| `weatherbot/_redact.py` (new) | Pure `redact_appid(text) -> text` | Add. One regex, no imports beyond `re`. |
| `weatherbot/weather/client.py` | Mint clean `HTTPStatusError` at both raise sites | Wrap `fetch_onecall` (`:52-68`) and `geocode` (`:79-85`) raises with a try/except that redacts + re-raises `from None`. |
| `weatherbot/__init__.py` | Backstop scrub of rendered stderr | Wrap `_LiveStderr.write` (`:33-34`) to `redact_appid(data)` before forwarding. |
| `tests/test_redact_hygiene.py` (new) | Regression: sentinel absent, status_code readable | Add, following `test_client.py` MockTransport + `test_bot.py` fixture patterns. |

### Pattern 1: Redacted `HTTPStatusError` re-raise (root fix, D-01)

**What:** Catch the key-bearing `HTTPStatusError`, scrub its message, and re-raise a *fresh* one that preserves the type contract, using `from None` to drop the chained original.

**When to use:** At every `response.raise_for_status()` whose URL carries the secret — here `fetch_onecall` and `geocode`.

**Verified constructor** (`.venv/.../httpx/_exceptions.py:265`):
```python
class HTTPStatusError(HTTPError):
    def __init__(self, message: str, *, request: Request, response: Response) -> None:
        super().__init__(message)
        self.request = request
        self.response = response
```
`request` and `response` are **keyword-only and required**. `.response.status_code` remains readable on the re-raised object. `[VERIFIED: source inspection]`

**Example (the recommended shape):**
```python
# Source: verified against httpx 0.28.1 in this repo's .venv
import httpx
from weatherbot._redact import redact_appid

def fetch_onecall(loc, key, units="imperial"):
    with httpx.Client(timeout=_TIMEOUT) as c:
        response = c.get(ONECALL, params={..., "appid": key, ...})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Redact the key from the message; keep type + .response intact (D-03, hard constraint).
            raise httpx.HTTPStatusError(
                redact_appid(str(exc)),
                request=exc.request,
                response=exc.response,
            ) from None  # ◄── suppresses the key-bearing __context__ (see Pitfall 1)
        return response.json()
```

**Verified behavior** (empirical, this repo's httpx):
- `type(reraised).__name__ == "HTTPStatusError"` ✓
- `reraised.response.status_code == 401` ✓ (readable)
- `"SENTINELKEY123" in str(reraised)` → `False` ✓
- With `from None`: `reraised.__cause__ is None`, `reraised.__suppress_context__ is True`, and the FULL `traceback.format_exception(...)` does NOT contain the sentinel ✓
- WITHOUT `from None`: the full traceback DOES contain the sentinel via `__context__` ✗ (this is the trap)

### Pattern 2: `_LiveStderr.write` regex backstop (D-02, Discretion option a)

**What:** Scrub `appid=<value>` from every string written to stderr, at the single proxy choke point shared by both `structlog.configure` sites.

**When to use:** As a renderer-agnostic safety net so a future call site that forgets `from None` (or a different renderer) still can't leak.

**Verified:** Under `PrintLoggerFactory(file=_LiveStderr())` with no explicit `processors=`, `log.exception("...")` produces the event line **and** the full formatted traceback in a **single `write()` call** (only the trailing `"\n"` is a separate 2nd write). So the `appid=...` token is never split across writes — a per-`write` regex is complete. `[VERIFIED: reproduced with the exact repo config]`

**Example:**
```python
# weatherbot/__init__.py
from weatherbot._redact import redact_appid  # (or inline the regex if you prefer zero import cycle)

class _LiveStderr:
    def write(self, data: str) -> int:
        scrubbed = redact_appid(data)
        return sys.stderr.write(scrubbed)
    def flush(self) -> None:
        sys.stderr.flush()
```
Note: `write` should return an int (bytes/chars written). Returning `sys.stderr.write(scrubbed)` (the scrubbed length) is consistent with the current contract; callers of `write` here (structlog's PrintLogger) ignore the return, so exact-length fidelity is not load-bearing.

### Pattern 3: The redaction helper + regex

**Verified regex:** `(appid=)[^&\s"'<>\\]+` with `re.IGNORECASE`, substitute `\1***`.

```python
# weatherbot/_redact.py
"""Redact the OpenWeather appid (API key) from any surfaced text (HARD-SEC-01)."""
from __future__ import annotations
import re

# Match `appid=` then the value up to the first delimiter (&, whitespace, quote,
# angle bracket, backslash) or end-of-string. Stops at the value boundary so it
# never eats following query params or trailing text; handles URL-encoded values
# (e.g. `appid=A%2Fb`) since %/letters before the delimiter are part of the value.
_APPID_RX = re.compile(r"(appid=)[^&\s\"'<>\\]+", re.IGNORECASE)

def redact_appid(text: str) -> str:
    """Replace every `appid=<value>` with `appid=***`, preserving endpoint + status."""
    return _APPID_RX.sub(r"\1***", text)
```

**Verified boundary cases** (all produce the expected scrub, param/endpoint/status preserved):
| Input | Output |
|-------|--------|
| `...onecall?lat=1&lon=2&appid=KEY&units=imperial` (the real message) | `...&appid=***&units=imperial` ✓ |
| `appid=KEY&next=1` | `appid=***&next=1` ✓ (stops at `&`) |
| `appid=A%2Fdef&units=x` (URL-encoded) | `appid=***&units=x` ✓ |
| `...appid=KEY'` (quote-terminated, as in the raise_for_status message) | `...appid=***'` ✓ |
| `appid=KEY end of line` | `appid=*** end of line` ✓ |

### Anti-Patterns to Avoid
- **Re-raise WITHOUT `from None`.** Leaks the key through the `__context__` chain in the full traceback even when `str(exc)` is clean. This is the single most likely mistake. (Verified.)
- **Stripping the whole query string.** Violates D-03 — the endpoint + status must stay visible for the live daemon's diagnosability.
- **Swapping to a custom exception type.** Breaks 6+ downstream `.response.status_code` branches (hard constraint).
- **Testing with `caplog`.** Captures nothing (0 records) — structlog's `PrintLoggerFactory` bypasses stdlib logging. Use `capsys`. (Verified.)
- **Custom structlog processor for the backstop.** Requires re-declaring the default processor chain at both configure sites and only sees the event dict; the `write` choke point is strictly simpler and catches more.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Preserving the exception type contract | A custom `WeatherFetchError` wrapper | Re-raise `httpx.HTTPStatusError` with `request=`/`response=` | 6+ downstream sites branch on `.response.status_code`; a custom type breaks them. |
| Suppressing the chained original | Manually deleting `exc.__context__` / `exc.__traceback__` | `raise ... from None` | Standard Python; sets `__suppress_context__` correctly and drops `__cause__`. |
| Reconstructing the message | Rebuilding the `"Client error '401...'"` string from parts | `redact_appid(str(exc))` | Keeps httpx's exact wording (status, reason, MDN link) minus the key; robust to httpx message changes. |

**Key insight:** The only thing that must change is the *value* of `appid` inside the message text. Everything else — type, `.response`, `.request`, status, endpoint, reason phrase — is preserved verbatim. Redact, don't reconstruct.

## Runtime State Inventory

> Not a rename/refactor/migration phase (pure code + config redaction). Section abbreviated.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore stores the appid; the key lives only in `.env` / env var, read at call time. | None. |
| Live service config | The live systemd service on `yahir-mint` runs the editable install; after the fix, a **service restart is required** for the redaction to take effect (see `[[weatherbot-live-systemd-service]]`). | Restart the daemon at deploy (Gate-2 / ops step, not a code task). |
| OS-registered state | None. | None. |
| Secrets/env vars | `OPENWEATHER_API_KEY` (→ `appid` query param) — name unchanged; only its exposure in error text is fixed. No key rotation implied by this phase (though a real prior leak to logs would warrant human-gated rotation — flag as an ops consideration, not a code task). | None (code); consider rotation as an ops decision. |
| Build artifacts | None — no packaging/name change. | None. |

## Common Pitfalls

### Pitfall 1: The `__context__` chain leaks the key even when `str(exc)` is clean
**What goes wrong:** You redact the message and re-raise a fresh `HTTPStatusError`, but omit `from None`. `str(exc)` is clean, so a quick check passes — but `bot.py:507`'s `_log.exception` renders the FULL traceback, which includes the original key-bearing exception under "During handling of the above exception, another exception occurred:".
**Why it happens:** Python auto-chains the in-flight exception as `__context__`. `_log.exception`/`traceback.format_exception` print the whole chain.
**How to avoid:** Always `raise HTTPStatusError(...) from None`. Verified: this sets `__suppress_context__ = True` and `__cause__ = None`, and the sentinel disappears from the full traceback.
**Warning signs:** A test that only asserts on `str(exc)` passes, but a `capsys`-based traceback test fails.

### Pitfall 2: `caplog` sees nothing — structlog bypasses stdlib logging
**What goes wrong:** You write the regression test with `caplog` and assert the sentinel is absent; it "passes" trivially because `caplog.records == []` — the test proves nothing.
**Why it happens:** The project uses `structlog.PrintLoggerFactory(file=_LiveStderr())`, which writes directly to the stream and never emits stdlib `LogRecord`s. Verified: `caplog` captures 0 records; `caplog.text` does not contain the sentinel *because it contains nothing*.
**How to avoid:** Use `capsys` and read `capsys.readouterr().err`. Verified: `capsys` captures the full rendered event + traceback including the sentinel (pre-fix) and its absence (post-fix). The `_LiveStderr` proxy resolves `sys.stderr` lazily on each write, which is exactly what makes it visible to `capsys`'s per-test stream swap.
**Warning signs:** `assert len(caplog.records) == 0` would pass; the test never exercised the real path.

### Pitfall 3: A regex that eats the following query params or trailing text
**What goes wrong:** A greedy or over-broad regex (`appid=.*`) redacts everything after `appid=`, destroying `units=`, the MDN link, and the status the daemon needs (violates D-03).
**Why it happens:** `.*` doesn't stop at the `&`/quote/whitespace boundary.
**How to avoid:** Use the verified `(appid=)[^&\s"'<>\\]+` character-class-negation form that stops at the first delimiter. Verified across the real message and 5 boundary cases.
**Warning signs:** Redacted output loses `&units=imperial` or the trailing `'`/MDN URL.

## Code Examples

### The exact leak (pre-fix), reproduced
```python
# Source: httpx 0.28.1 _models.py:809-829 (verified) + this repo's client.py
# raise_for_status builds:
#   "Client error '401 Unauthorized' for url
#    'https://api.openweathermap.org/data/3.0/onecall?lat=..&lon=..&appid=<KEY>&units=imperial'
#    \nFor more information check: https://developer.mozilla.org/.../401"
# {0.url} == response.url == the full URL with appid in the clear.
```

### Regression test skeleton (follows existing repo patterns)
```python
# tests/test_redact_hygiene.py
# Mirrors tests/test_client.py (_install_mock via httpx.MockTransport) and
# tests/test_bot.py (fake_discord_message fixture).
import httpx
import pytest
from weatherbot.weather import client
from weatherbot._redact import redact_appid

SENTINEL = "SENTINELKEY_do_not_leak_123"

def _401_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, request=request, json={"cod": 401, "message": "Invalid API key"})

def test_onecall_failure_redacts_key_and_keeps_status(monkeypatch, capsys, some_location):
    _install_mock(monkeypatch, _401_handler)  # from test_client.py helper
    with pytest.raises(httpx.HTTPStatusError) as ei:
        client.fetch_onecall(some_location, key=SENTINEL)
    exc = ei.value
    assert exc.response.status_code == 401          # type-contract canary
    assert SENTINEL not in str(exc)                  # message clean
    assert type(exc).__name__ == "HTTPStatusError"   # type preserved
    # full traceback (as _log.exception would render) is clean:
    import traceback
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert SENTINEL not in tb

def test_geocode_failure_redacts_key(monkeypatch):
    _install_mock(monkeypatch, _401_handler)
    with pytest.raises(httpx.HTTPStatusError) as ei:
        client.geocode("Paris", key=SENTINEL)
    assert SENTINEL not in str(ei.value)
    assert ei.value.response.status_code == 401

@pytest.mark.asyncio
async def test_discord_on_message_does_not_dump_key(fake_discord_message, monkeypatch, capsys):
    # Force dispatch_spec to raise the (already-redacted) HTTPStatusError, then
    # let on_message's `except Exception: _log.exception(...)` run.
    ... # build_on_message(...); await handler(message)
    err = capsys.readouterr().err
    assert SENTINEL not in err                       # traceback on stderr is clean

def test_redact_helper_boundaries():
    msg = "for url 'x?lat=1&appid=%s&units=imperial'" % SENTINEL
    out = redact_appid(msg)
    assert SENTINEL not in out
    assert "units=imperial" in out and "appid=***" in out
```
For the Discord path, ensure the configured logger routes through `_LiveStderr` (the package default already does), so `capsys.readouterr().err` sees the rendered traceback. If the test needs the backstop specifically, assert the sentinel is absent from `err` even when a *raw* (un-redacted) exception is logged, to prove option-(a) catches it.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| httpx `raise_for_status` embeds full URL in message (incl. secrets) | Still true in 0.28.1 — no upstream redaction | current | You must redact yourself; httpx will not do it for you. `[VERIFIED: source]` |
| `raise NewError(...)` (implicit chaining) | `raise NewError(...) from None` for secret hygiene | Python 3 standard | Suppresses the `__context__` chain that would otherwise re-expose the original. |

**Deprecated/outdated:** none relevant to this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | OpenWeather appids are alphanumeric/hex and appear **bare** (not URL-encoded) in `response.url`. | Pattern 3 | Low — the regex also handles URL-encoded values (`%XX` is part of the captured value); verified. |
| A2 | The Discord `on_message` handler's `_log` routes through the package-default `_LiveStderr` at test time (so `capsys` sees it). | Code Examples / Pitfall 2 | Low — `structlog.get_logger(__name__)` uses the global config; the package sets it at import. The planner should confirm the test doesn't call `cli._configure_logging` with a divergent factory. |

*Both assumptions are low-risk and independently verified where testable.*

## Open Questions

1. **Should the backstop live in `_promotable/`?**
   - What we know: CONTEXT Deferred Ideas says "optionally under `_promotable/` if the seam is clean." The seam IS clean (a pure `redact_appid`), BUT the `appid` pattern is OpenWeather-specific.
   - What's unclear: whether the tiny helper is worth the quarantine ceremony now.
   - Recommendation: keep it at `weatherbot/_redact.py` (app-local, one obvious place), add a one-line comment flagging it as a hub-promotion candidate. Do NOT create `_promotable/` for a 4-line regex. (Aligns with the phase's "cheap, high-value" mandate.)

2. **Does `_redact` importing into `__init__.py` risk an import cycle?**
   - What we know: `__init__.py` imports `structlog`, `logging`, `sys` today. `_redact.py` imports only `re`.
   - What's unclear: nothing material — `_redact` has no weatherbot imports, so `from weatherbot._redact import redact_appid` inside `__init__.py` is safe (no cycle).
   - Recommendation: import at module top of `__init__.py`; if any ordering concern arises, inline the compiled regex in `_LiveStderr` instead. Verified `_redact` has zero internal deps.

## Environment Availability

> Skipped — this phase is code + config only with no new external tools, services, or runtimes. All libraries (httpx, structlog, pytest) are already installed and pinned.

## Validation Architecture

> `nyquist_validation: true` in `.planning/config.json` — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (+ pytest-cov 7.1.0, syrupy 5.3.4) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `addopts="-ra"`) |
| Quick run command | `uv run pytest tests/test_redact_hygiene.py -q` (or `.venv/bin/python -m pytest tests/test_redact_hygiene.py -q`) |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HARD-SEC-01 | onecall 401 → key absent from `str(exc)` + traceback; `.status_code` readable | unit | `uv run pytest tests/test_redact_hygiene.py::test_onecall_failure_redacts_key_and_keeps_status -x` | ❌ Wave 0 |
| HARD-SEC-01 | geocode 401 → key absent; `.status_code` readable | unit | `uv run pytest tests/test_redact_hygiene.py::test_geocode_failure_redacts_key -x` | ❌ Wave 0 |
| HARD-SEC-01 | Discord `on_message` failure → key absent from `capsys.err` | integration | `uv run pytest tests/test_redact_hygiene.py::test_discord_on_message_does_not_dump_key -x` | ❌ Wave 0 |
| HARD-SEC-01 | `redact_appid` boundary correctness (keeps params/status, handles URL-encoded) | unit | `uv run pytest tests/test_redact_hygiene.py::test_redact_helper_boundaries -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_redact_hygiene.py tests/test_client.py -q`
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** Full suite green before `/gsd-verify-work-agentic` (Gate-1). Note the pre-existing syrupy "N snapshots failed" noise at exit 0 — trust the exit code, not the snapshot line (see `[[pytest-snapshot-report-quirk]]`).

### Wave 0 Gaps
- [ ] `tests/test_redact_hygiene.py` — the 4 tests above (covers HARD-SEC-01 on all three paths + helper). May reuse `test_client.py`'s `_install_mock` helper (consider extracting it to `conftest.py` if importing across test files is awkward).
- [ ] `weatherbot/_redact.py` must exist before its tests (implementation task, not a test task).
- [ ] Confirm `pytest-asyncio` (or the repo's existing async-test mechanism) is available for the `on_message` coroutine test — `tests/test_bot.py` already drives `on_message`, so the mechanism exists; reuse it (check `test_bot.py`'s async pattern rather than assuming `@pytest.mark.asyncio`).

*(No new framework install needed — existing pytest infra covers all phase requirements.)*

## Security Domain

> `security_enforcement: true` — section included. This phase IS a security fix (HARD-SEC-01).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth flow changes. |
| V3 Session Management | no | N/A. |
| V4 Access Control | no | N/A. |
| V5 Input Validation | no | Not an injection surface; the fix is output sanitization. |
| V6 Cryptography | no (but adjacent) | The appid is a bearer-style secret; the phase governs its exposure, not its crypto. Never hand-roll — use the pinned httpx / stdlib `re`. |
| **V7 Error Handling & Logging** | **yes** | **Redact secrets from error messages, tracebacks, and log output** — exactly this phase. Root fix (redacted re-raise) + backstop (log-output scrub). |
| V8 Data Protection (secrets in logs) | yes | Ensure the API key is never persisted to logs/stderr. Both the source fix and the `_LiveStderr` backstop enforce this. |

### Known Threat Patterns for {Python bot + httpx + structlog}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret in exception message (`raise_for_status` embeds full URL) | Information Disclosure | Redact `appid=<value>` → `appid=***` in the re-raised message (Pattern 1). |
| Secret re-exposed via chained `__context__` in tracebacks | Information Disclosure | `raise ... from None` to suppress the original key-bearing exception (Pitfall 1). |
| Secret leaked by a future/forgotten call site | Information Disclosure | Renderer-agnostic `_LiveStderr.write` regex backstop (Pattern 2, D-02 defense-in-depth). |
| Prior real leak to persisted logs on the live daemon | Information Disclosure | **Ops/human consideration:** if the key already leaked to on-disk logs, consider key rotation — human-gated, out of code scope. Flag at Gate-2. |

## Sources

### Primary (HIGH confidence)
- `.venv/lib/python3.12/site-packages/httpx/_exceptions.py:258-268` — `HTTPStatusError(message, *, request, response)` constructor signature. `[VERIFIED: source inspection]`
- `.venv/lib/python3.12/site-packages/httpx/_models.py:794-829` — `raise_for_status` message format `"...for url '{0.url}'..."`; `{0.url}` = full URL with `appid`. `[VERIFIED: source inspection]`
- `weatherbot/__init__.py:24-44` + `weatherbot/cli.py:764-783` — both `structlog.configure` sites use `PrintLoggerFactory(file=_LiveStderr())`, no explicit `processors=`. `[VERIFIED: source]`
- Empirical repro (this session, this repo's `.venv`): `from None` suppresses the key-bearing `__context__` in the full traceback; without it, the sentinel leaks. `[VERIFIED: executed]`
- Empirical repro: `capsys` captures the rendered traceback (sentinel visible); `caplog` captures 0 records (bypassed). `[VERIFIED: executed pytest]`
- Empirical repro: structlog `PrintLogger` emits the event + full traceback in a single `write()` call (secret not split). `[VERIFIED: executed]`
- Regex boundary verification across the real message + 5 edge cases. `[VERIFIED: executed]`
- `uv.lock` — httpx pinned at 0.28.1. `[VERIFIED]`

### Secondary (MEDIUM confidence)
- `tests/test_client.py` (MockTransport `_install_mock` pattern) and `tests/test_bot.py` (`fake_discord_message`, `on_message` driving) — the regression test should reuse these. `[VERIFIED: source]`

### Tertiary (LOW confidence)
- None. All load-bearing claims verified against installed code.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all touched libs pinned and inspected.
- Architecture (root fix + backstop): HIGH — both patterns executed against the real httpx/structlog in this repo.
- Pitfalls: HIGH — the `from None` chain-leak and the `caplog`-blindness were each reproduced empirically.

**Research date:** 2026-07-09
**Valid until:** 2026-08-08 (stable; re-verify only if httpx is bumped past 0.28.x or the structlog logger factory changes).
