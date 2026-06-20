---
phase: 06-shared-lookup-core-command-parser
reviewed: 2026-06-15T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - weatherbot/interactive/command.py
  - weatherbot/interactive/lookup.py
  - weatherbot/interactive/__init__.py
  - weatherbot/cli.py
  - weatherbot/config/loader.py
  - tests/test_command.py
  - tests/test_lookup.py
  - tests/test_interactive_package.py
findings:
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-06-15T00:00:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

This phase extracts a shared read-only `lookup_weather` core and a pure
`parse_weather_command` parser, then re-wires `send_now` to delegate its
fetch→render HEAD to the new core. The full phase test suite (24 tests) and
`ruff` both pass, and the daemon/manual timing-placeholder behavior is preserved
across the refactor (verified: daemon builds `ScheduleContext(tz=ZoneInfo(location.timezone))`,
which matches the location tz `lookup_weather` falls back to on the manual path,
so the `extra_placeholders` override produces identical output to the old inline
render). The import-cycle break (lazy `build_client`/`UnknownLocationError`
imports) is correct.

No BLOCKER-class defects were proven. However, several real correctness and
contract problems exist: a docstring that promises load-time enforcement the
code does not perform, a too-narrow type annotation that the code's own tests
violate at runtime, a latent slicing assumption in the parser, and redundant
work / dead parameters. None are security issues — the parser and error types
correctly avoid leaking secrets (verified `UnknownLocationError` carries only
names, never `appid`/webhook).

No structural-findings substrate was provided with this review.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `assert_unique_names` docstring claims load-time enforcement that never happens

**File:** `weatherbot/config/loader.py:67-82` (docstring lines 73-74)
**Issue:** The docstring states this helper "is run at config load (and by
`--check`) so a duplicate is caught at setup, never at 9am." It is NOT run at
config load. `load_config` (lines 18-27) never calls it, and a codebase grep
shows the only caller is `weatherbot/ops/selfcheck.py:86` (the `--check` /
self-check path). Therefore `--send-now` and the always-on daemon never enforce
unique names. Because `resolve_location` matches case-insensitively and returns
the FIRST match (loader.py:55-57), a `config.toml` with two locations named
`"Home"` will silently send to whichever appears first — exactly the "ambiguous
at 9am" failure the docstring claims is prevented. The promise is load-bearing:
a reader trusts duplicates are impossible after load.
**Fix:** Either call it inside `load_config` so the contract holds for every
path:
```python
def load_config(path: str | Path) -> Config:
    path = Path(path)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    config = Config.model_validate(raw)
    assert_unique_names(config)  # enforce uniqueness for EVERY load path
    return config
```
or correct the docstring to say it is enforced only by `--check`/self-check and
NOT on the send/daemon path.

### WR-02: `lookup_weather` `templates_dir` annotation is `str | None` but a `Path` flows through it

**File:** `weatherbot/interactive/lookup.py:84` (and call site `weatherbot/cli.py:146`)
**Issue:** `lookup_weather` declares `templates_dir: str | None = None`, but
`send_now` declares `templates_dir: str | Path | None` (cli.py:95) and forwards
it unchanged to `lookup_weather` (cli.py:146). The project's own
`tests/test_send_now.py:138` calls `send_now(..., templates_dir=tmp_path)` where
`tmp_path` is a `pathlib.Path`, so a `Path` provably reaches `lookup_weather`
despite the `str`-only annotation. It works at runtime only because
`load_template(name, templates_dir)` accepts `str | Path`. This is a real
annotation defect: any type checker (mypy/pyright) configured strictly would
flag the call, and the narrowed type misleads future callers into thinking only
`str` is accepted.
**Fix:**
```python
from pathlib import Path  # already importable
...
def lookup_weather(
    name: str | None,
    *,
    config: Config,
    settings: Settings | None = None,
    client=None,
    templates_dir: str | Path | None = None,
    extra_placeholders: dict[str, str] | None = None,
) -> LookupResult:
```

### WR-03: `lookup_weather` computes on-demand timing placeholders that are then thrown away on the scheduled path

**File:** `weatherbot/interactive/lookup.py:137-142`
**Issue:** On every call, `lookup_weather` unconditionally computes
`tz = ZoneInfo(location.timezone)`, `now = datetime.now(tz)`, and
`schedule_placeholders(None, now, now)` to populate `{sent_at}/{checked_at}/{schedule_note}`.
But when invoked from the daemon (`send_now` with a non-None `schedule_ctx`),
`extra_placeholders` always contains those same three keys (cli.py:137) and
overwrites all of them immediately at line 142. The on-demand computation is dead
work whose result never reaches output on the scheduled path. Beyond waste, this
is a correctness foot-gun: the two code paths now compute timing in two places,
and a future edit to one (e.g., adding a 4th timing key) can silently diverge.
The override is currently total only because `schedule_placeholders` happens to
emit exactly the same three keys.
**Fix:** Short-circuit when the caller supplies the timing keys, or compute
on-demand timing only when `extra_placeholders` does not already provide them:
```python
values = dict(forecast.placeholders())
if extra_placeholders is not None:
    values.update(extra_placeholders)
else:
    tz = ZoneInfo(location.timezone)
    now = datetime.now(tz)
    values.update(schedule_placeholders(None, now, now))
```
(Adjust if a caller is ever intended to override only a SUBSET of timing keys —
no current caller does.)

### WR-04: Parser slicing assumes `casefold()` is length-preserving

**File:** `weatherbot/interactive/command.py:58-61`
**Issue:** The guard checks `stripped.casefold().startswith(_KEYWORD)` but then
slices the ORIGINAL string: `rest = stripped[len(_KEYWORD):]`. This silently
assumes the casefolded prefix and the original prefix have the SAME length.
`str.casefold()` is NOT length-preserving for some Unicode characters (e.g. a
single 'ß' casefolds to 'ss'). For the literal keyword `"weather"` no such
expansion currently triggers a false start-match, so this is latent rather than
active — but the code documents an invariant (slice the raw string by the
casefolded keyword's length) that does not generally hold. If `_KEYWORD` is ever
changed or extended, or matching is loosened, the off-by-N slice would corrupt
the extracted location.
**Fix:** Slice off the matched prefix length derived from the actual match rather
than assuming positional equivalence, e.g. match against a casefolded copy and
extract location from the casefolded text, or guard explicitly:
```python
stripped = text.strip()
folded = stripped.casefold()
if not folded.startswith(_KEYWORD):
    return Command(CommandKind.NOT_A_COMMAND)
# _KEYWORD is ASCII and length-stable; assert the invariant the slice relies on.
rest = stripped[len(_KEYWORD):]
```
Minimally, document the ASCII-keyword assumption at the slice so a future keyword
change is forced to re-examine it.

## Info

### IN-01: `lookup_weather` forwards `settings` that can never be used on the delegated path

**File:** `weatherbot/cli.py:141-148`
**Issue:** `send_now` always builds a non-None `client` before calling
`lookup_weather` (cli.py:110-113), yet still passes `settings=settings`.
Inside `lookup_weather`, `settings` is consulted only in the `client is None`
branch (lookup.py:105-113), which is never taken from this caller. The argument
is inert here. Harmless, but it obscures the actual dependency (the CLI path
never needs `settings` for the lookup) and invites a reader to think the lookup
might rebuild a client.
**Fix:** Drop `settings=settings` from the `send_now`→`lookup_weather` call, or
add a one-line comment noting it is forwarded only for the
client-built-internally case (which this caller never hits).

### IN-02: Duplicated dual-fetch / render block across `lookup_weather` and `send_now` comments

**File:** `weatherbot/interactive/lookup.py:115-144`
**Issue:** The fetch→Forecast→validate→render sequence and its explanatory
comments (DATA-03 imperial-first ordering, CR-01 primary-unit selection, D-10/11
template validation) now live in `lookup_weather`, while `send_now` retains a
large comment block (cli.py:119-132) re-describing the same HEAD it delegated
away. The stale narrative in `send_now` describes logic that no longer lives
there, which can mislead maintainers during the next edit.
**Fix:** Trim `send_now`'s HEAD comment to a one-line "delegated to
`lookup_weather`; see there" pointer so the authoritative description lives in
exactly one place.

### IN-03: `_ny_config()` lat/lon are inconsistent ("New York" set to a near-but-wrong longitude)

**File:** `tests/test_lookup.py:60-71`
**Issue:** Minor fixture nit: `lat=40.7128, lon=-74.006`. The widely-used NYC
coordinate is `lon=-74.0060`; `-74.006` is the same value but the
adjacent Berlin fixture uses full-precision values, so the inconsistency is
cosmetic only. Not a correctness issue (the client is faked; coordinates are
never used to fetch), noted only for fixture tidiness.
**Fix:** None required; optionally align precision with the other fixtures for
readability.

---

_Reviewed: 2026-06-15T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
