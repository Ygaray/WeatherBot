---
phase: 30-secret-hygiene
reviewed: 2026-07-09T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - tests/test_redact_hygiene.py
  - weatherbot/__init__.py
  - weatherbot/_redact.py
  - weatherbot/weather/client.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 30: Code Review Report

**Reviewed:** 2026-07-09T00:00:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Adversarial review of HARD-SEC-01 secret-hygiene work: prevent the OpenWeather
`appid` from leaking into logs and tracebacks. I verified the redaction regex,
the `from None` re-raise, the type contract of the re-raised exception, the
`_LiveStderr` stderr backstop, and the test assertions by executing each against
real `httpx` objects.

**Core mechanism is sound.** The regex `(appid=)[^&\s"'<>\\]+` correctly redacts
every form the key surfaces in `str(exc)` — mid-query (`&`-terminated),
trailing (quote-terminated), URL-encoded values (`%2F`), uppercase `APPID=`, and
repeated occurrences (`re.sub` is global). I confirmed `str(HTTPStatusError)`
from both the One Call fetch (appid mid-query) and geocode (appid trailing)
redacts to `appid=***` with the sentinel absent. The `from None` correctly drops
the key-bearing `__context__`, so the full `traceback.format_exception` output is
clean — I reproduced this and confirmed `SENTINEL not in tb`. The re-raised
exception preserves `type == HTTPStatusError` and `.response.status_code`, so the
6+ downstream call sites are unaffected. Both `structlog.configure` sites
(`__init__.py` and `cli.py:779`) route through `_LiveStderr`, so the backstop is
not bypassed by CLI reconfiguration. All 4 tests pass and assert absence of the
sentinel (non-tautological), using `capsys` not caplog as required.

Two Warnings below flag a **latent** leak channel (the re-raised exception still
carries `.request`, whose `repr`/`.url` hold the raw key) and a backstop edge
case. Neither is currently reachable through an existing code path, so neither is
Critical — but the `.request` residue is the kind of thing a future logging change
would silently turn into a leak.

## Warnings

### WR-01: Re-raised `HTTPStatusError` still carries the raw key on `.request` / `.request.url`

**File:** `weatherbot/weather/client.py:80-84` and `107-111`
**Issue:** The redaction fixes the exception *message* (`str(exc)`), but the fresh
`HTTPStatusError` is constructed with `request=exc.request` — the original
`httpx.Request` whose URL still contains `appid=<key>` verbatim. I confirmed:

```
repr(e2.request)      -> <Request('GET', '...?lat=40.7&appid=SENTINELKEY_do_not_leak_123&units=imperial')>
str(e2.request.url)   -> contains the raw key
```

The current test suite passes only because Python's default
`traceback.format_exception` does not `repr()` exception attributes, and no
existing downstream handler logs `exc.request` / `exc.request.url`. So this is
**not currently reachable** (hence Warning, not Blocker). But it is a live
foot-gun: any future `_log.exception(..., request=exc.request)`,
`logger.error(str(exc.request.url))`, a richer traceback formatter (e.g.
`rich`/`better-exceptions` that render locals/attrs), or an APM/Sentry integration
that captures request context would surface the key — and the `_LiveStderr`
backstop only scrubs `appid=<value>` textual patterns, which `repr(request)`
happens to still match (`appid=...`), but `.url` accessed and reformatted might
not.

**Fix:** Redact the URL on the request object too, so the exception carries no raw
key on any attribute. Build a scrubbed request and pass it:

```python
except httpx.HTTPStatusError as exc:
    scrubbed_url = httpx.URL(redact_appid(str(exc.request.url)))
    scrubbed_req = exc.request.copy_with(url=scrubbed_url)
    raise httpx.HTTPStatusError(
        redact_appid(str(exc)),
        request=scrubbed_req,
        response=exc.response,
    ) from None
```

Note `exc.response.request` (via `exc.response.request.url`) is a second copy of
the same URL and is left intact by the above — audit whether any downstream reads
`exc.response.request.url`; if so, scrub that too or reconstruct the response.
At minimum, add a test asserting `SENTINEL not in repr(exc.request)` and
`SENTINEL not in str(exc.request.url)` to lock the contract, since the current
suite would not catch a regression here.

### WR-02: `_LiveStderr.write` assumes `str`; raises `TypeError` on non-`str` input

**File:** `weatherbot/__init__.py:35-43`
**Issue:** `redact_appid` calls `re.sub` with a `str` pattern. If `write` is ever
handed `bytes`, it raises `TypeError: cannot use a string pattern on a bytes-like
object` (I reproduced this). Today `structlog.PrintLogger` only ever writes `str`,
so this is not reachable — but `_LiveStderr` presents itself as a generic
file-like object bound as the structlog logger factory's `file`, and a future
renderer, a `logging.StreamHandler` accidentally pointed at it, or a
`sys.stderr`-swap that forwards bytes would crash the log write. A crash inside the
logging path during exception handling is worse than a slightly-degraded scrub,
because it can mask the original error.

**Fix:** Guard the type so the backstop degrades gracefully instead of throwing:

```python
def write(self, data) -> int:
    if isinstance(data, str):
        return sys.stderr.write(redact_appid(data))
    return sys.stderr.write(data)  # non-str: pass through, never crash the log path
```

(Or decode/re-encode bytes through `redact_appid` if bytes should also be scrubbed.)
This is defense-in-depth to match the stated "belt-and-suspenders" intent.

## Info

### IN-01: `appid=` (empty value) and URL-encoded `appid%3D` are not redacted — acceptable, but undocumented

**File:** `weatherbot/_redact.py:23`
**Issue:** The regex requires at least one value character (`+`), so a bare
`appid=` (no value) is left as-is — correct, there is no secret to hide. Separately,
a URL-encoded *key name* `appid%3DKEY123` (where the `=` itself is percent-encoded)
is not matched, so the key would survive. httpx does not encode the `=` in a query
string, so this form does not occur on the real leak paths — but it is worth a
one-line comment noting the regex assumes a literal `=` separator, so a future
caller passing an already-percent-encoded string does not silently bypass it.
**Fix:** Add a comment documenting the literal-`=` assumption; no code change needed
for the current call sites.

### IN-02: Redaction is duplicated inline at two call sites in `client.py`

**File:** `weatherbot/weather/client.py:79-84` and `104-111`
**Issue:** The `except httpx.HTTPStatusError` → redact-and-re-raise-`from None`
block is copy-pasted verbatim in `fetch_onecall` and `geocode`. It is only two
copies today, but if WR-01's request-scrubbing fix lands, the block grows to ~4
lines and drifting between the two copies becomes a real risk (one gets the
request-scrub, the other does not — a silent partial leak).
**Fix:** Extract a small private helper, e.g.
`_reraise_redacted(exc: httpx.HTTPStatusError) -> NoReturn` that performs the scrub
+ `raise ... from None`, and call it from both sites so the two paths cannot drift.

---

_Reviewed: 2026-07-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
