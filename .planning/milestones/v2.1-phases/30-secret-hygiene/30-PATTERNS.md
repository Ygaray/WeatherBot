# Phase 30: Secret Hygiene - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 5 (2 new, 3 modified)
**Analogs found:** 5 / 5

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/_redact.py` (NEW) | utility (pure fn) | transform | `weatherbot/weather/client.py` header comment (redaction intent) + stdlib `re` idiom | role-match |
| `weatherbot/weather/client.py` (MODIFY) | service (API client) | request-response | itself — both raise sites are siblings | exact (in-file) |
| `weatherbot/__init__.py` (MODIFY) | config (logging infra) | transform / stream I/O | itself — `_LiveStderr.write` (`:33-34`) | exact (in-file) |
| `weatherbot/cli.py` (MODIFY/CONFIRM) | config (logging infra) | transform / stream I/O | `weatherbot/__init__.py` `structlog.configure` | exact |
| `tests/test_redact_hygiene.py` (NEW) | test | request-response + event-driven | `tests/test_client.py` (`_install_mock`) + `tests/test_bot.py` (`_run` / `build_on_message`) | exact |

## Pattern Assignments

### `weatherbot/_redact.py` (NEW — utility, transform)

**Analog:** No prior pure-util module in the package; the *intent* analog is the redaction header comment in `weatherbot/weather/client.py:35-39`. Follow the package module conventions (module docstring citing the requirement ID, `from __future__ import annotations`, stdlib-only import).

**Module-header convention to copy** (from `client.py:1-19`): docstring naming the requirement (`HARD-SEC-01`), then `from __future__ import annotations`, then imports. `_redact.py` imports **only** `re` (no weatherbot imports → no import cycle, confirmed RESEARCH Open Q2).

**Verified implementation** (RESEARCH Pattern 3 — regex + boundaries verified against the real message):
```python
"""Redact the OpenWeather appid (API key) from any surfaced text (HARD-SEC-01)."""
from __future__ import annotations
import re

# Hub-promotion candidate (OpenWeather-specific for now; see Deferred Ideas).
_APPID_RX = re.compile(r"(appid=)[^&\s\"'<>\\]+", re.IGNORECASE)

def redact_appid(text: str) -> str:
    """Replace every `appid=<value>` with `appid=***`, preserving endpoint + status."""
    return _APPID_RX.sub(r"\1***", text)
```
Do **not** create a `_promotable/` dir for this (RESEARCH Open Q1 — keep app-local, one-line flag comment only).

---

### `weatherbot/weather/client.py` (MODIFY — service, request-response)

**Analog:** In-file. Both raise sites are structurally identical; apply the same wrapper to both.

**Current raise sites to wrap:**

`fetch_onecall` (lines 52-68), raise at **:67**:
```python
    with httpx.Client(timeout=_TIMEOUT) as c:
        response = c.get(ONECALL, params={... "appid": key, ...})
        response.raise_for_status()   # ◄── :67 leaks appid via message URL
        return response.json()
```

`geocode` (lines 79-85), raise at **:84**:
```python
    with httpx.Client(timeout=_TIMEOUT) as c:
        response = c.get(GEOCODE, params={"q": query, "limit": limit, "appid": key})
        response.raise_for_status()   # ◄── :84 same leak
        return response.json()
```

**Pattern to apply at BOTH sites** (RESEARCH Pattern 1 — constructor + `from None` verified against httpx 0.28.1):
```python
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise httpx.HTTPStatusError(
                redact_appid(str(exc)),
                request=exc.request,
                response=exc.response,
            ) from None  # ◄── LOAD-BEARING: drops key-bearing __context__ (Pitfall 1)
```

**Imports:** add `from weatherbot._redact import redact_appid` alongside the existing `import httpx` (client.py:24). Update the header comment at `:35-39` — it currently claims the module "never logs the URL or the key" but omits the `raise_for_status` message gap; note the redacted re-raise now closes it.

**Hard constraint (LOCKED):** re-raised type stays `httpx.HTTPStatusError`; `.response`/`.response.status_code` preserved. 6+ downstream branch sites depend on this (`cli.py:291/367/421/692`, `selfcheck.py:127`, `daemon.py:263`). Never swap the type.

---

### `weatherbot/__init__.py` (MODIFY — config, stream I/O)

**Analog:** In-file `_LiveStderr` (`:24-37`). Single stderr choke point shared by both `structlog.configure` sites.

**Current write (lines 33-34):**
```python
    def write(self, data: str) -> int:
        return sys.stderr.write(data)
```

**Backstop pattern (RESEARCH Pattern 2 — verified single-write, renderer-agnostic):**
```python
    def write(self, data: str) -> int:
        return sys.stderr.write(redact_appid(data))
```

**Imports:** add `from weatherbot._redact import redact_appid` at module top (safe — `_redact` has zero weatherbot deps, RESEARCH Open Q2). If any ordering concern surfaces, inline the compiled regex instead. Leave `structlog.configure` (`:40-44`) unchanged — the backstop lives in `_LiveStderr.write`, not the processor chain.

---

### `weatherbot/cli.py` (MODIFY/CONFIRM — config, stream I/O)

**Analog:** identical to `__init__.py`'s configure. The second `structlog.configure` (`:779-783`) already routes through `PrintLoggerFactory(file=_LiveStderr())` importing the SAME `_LiveStderr` (`:776 from weatherbot import _LiveStderr`).

**Action:** CONFIRM only — because both configure sites share the one `_LiveStderr` class, wrapping `_LiveStderr.write` in `__init__.py` covers this site automatically. No edit expected here; verify the import at `:776` still points at the package `_LiveStderr` (not a divergent local factory).

---

### `tests/test_redact_hygiene.py` (NEW — test, request-response + event-driven)

**Analog A — offline httpx mock** (`tests/test_client.py:25-35`), copy verbatim (or extract to `conftest.py` if cross-file import is awkward — RESEARCH Wave 0 note):
```python
def _install_mock(monkeypatch, handler, capture: dict | None = None):
    real_init = httpx.Client.__init__
    def fake_init(self, *args, **kwargs):
        if capture is not None:
            capture["init_kwargs"] = kwargs
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.Client, "__init__", fake_init)
```

**Analog B — async on_message driving** (`tests/test_bot.py:22,46-48,75`). NOTE: the repo drives coroutines with a plain `asyncio.run` helper, **NOT** `@pytest.mark.asyncio` (RESEARCH Wave 0 — confirm the mechanism, don't assume the marker):
```python
import asyncio
def _run(coro):
    """Drive a coroutine to completion on a fresh event loop (no live gateway)."""
    return asyncio.run(coro)
# handler = bot.build_on_message(...); _run(handler(msg))
```
Use the `fake_discord_message` fixture (conftest) exactly as `test_bot.py` does; `_log` in `bot.py` routes through the package-default `_LiveStderr`, so read `capsys.readouterr().err`.

**Test shape (RESEARCH Code Examples):** sentinel key `"SENTINELKEY_do_not_leak_123"`, a 401 `MockTransport` handler, four tests — onecall / geocode / Discord `on_message` / `redact_appid` boundaries. Assert sentinel absent from `str(exc)`, from `"".join(traceback.format_exception(...))`, and from `capsys.readouterr().err`; assert `.response.status_code == 401` (type-contract canary).

**CRITICAL — capture mechanism:** use `capsys`, NOT `caplog`. `caplog` captures 0 records because `PrintLoggerFactory` bypasses stdlib logging (RESEARCH Pitfall 2). Note the existing `test_client.py::test_appid_not_logged` (`:164`) uses `caplog` — do NOT copy that fixture choice for the traceback assertions; it works there only because it checks a different (httpx-logger) surface.

## Shared Patterns

### Redaction helper (single source of truth)
**Source:** `weatherbot/_redact.py` `redact_appid` (new)
**Apply to:** `client.py` (both raise sites) AND `__init__.py` `_LiveStderr.write`. One import, one function — belt-and-suspenders (D-01 source scrub + D-02 backstop) both call it.

### Module-header convention
**Source:** `weatherbot/weather/client.py:1-24`
**Apply to:** `weatherbot/_redact.py` — docstring citing the requirement ID (`HARD-SEC-01`), `from __future__ import annotations`, then stdlib-only imports.

### Exception type contract (do NOT regress)
**Source:** `httpx.HTTPStatusError` used across `cli.py:291/367/421/692`, `daemon.py:263`, `selfcheck.py:127`
**Apply to:** `client.py` re-raise — keep the type and `.response` intact. Redact the message, never reconstruct/replace the exception type.

### Offline test wiring
**Source:** `tests/test_client.py:25-35` (`_install_mock`) + `tests/test_bot.py:46-48` (`_run`) + `fake_discord_message` conftest fixture
**Apply to:** `tests/test_redact_hygiene.py` — no live network, no live gateway.

## No Analog Found

None — every file has a strong in-repo analog.

## Metadata

**Analog search scope:** `weatherbot/weather/`, `weatherbot/` package root, `weatherbot/cli.py`, `weatherbot/interactive/`, `tests/`
**Files scanned:** 5 source/test analogs read (client.py, __init__.py, cli.py §764-783, bot.py §495-513, test_client.py, test_bot.py)
**Pattern extraction date:** 2026-07-09
