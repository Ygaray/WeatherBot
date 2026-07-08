# Phase 22: Channel + Delivery-Reliability Seam (+ in-place boundary) - Pattern Map

**Mapped:** 2026-06-27
**Files analyzed:** 11 (5 created, 6 modified)
**Analogs found:** 11 / 11 (this is a RELOCATION phase — every "new" module file has an exact existing source moving into it)

> Read alongside `22-CONTEXT.md` (D-01..D-13) and `22-RESEARCH.md` (verified move/stay split, grimp/AST gate prototypes). This file pins the *concrete source lines* each new/modified file copies from. Every excerpt below was read from the current working tree this session.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `yahir_reusable_bot/__init__.py` | config (package marker) | n/a | `weatherbot/__init__.py` | role-match |
| `yahir_reusable_bot/channels/__init__.py` | module (re-export surface) | request-response | `weatherbot/channels/__init__.py` (current) | exact (subset) |
| `yahir_reusable_bot/channels/base.py` | model + abstract contract | request-response | `weatherbot/channels/base.py` | **exact move (minus `send_briefing` + `Forecast`)** |
| `yahir_reusable_bot/reliability/__init__.py` | module (re-export surface) | n/a | `weatherbot/reliability/__init__.py` | **exact move** |
| `yahir_reusable_bot/reliability/retry.py` | utility (retry engine) | event-driven / transform | `weatherbot/reliability/retry.py` | **verbatim move** |
| `yahir_reusable_bot/ports/alerts.py` | port (Protocol) | event-driven | `weatherbot/channels/factory.py` `Callable[...]` registry + `interactive/state.py` callable-fields dataclass | role-match (shape mirror) |
| `tests/test_import_hygiene.py` | test (gate self-proof) | n/a | `tests/test_oracle_selfproof.py` | role-match (meta-test structure) |
| `weatherbot/channels/__init__.py` (mod) | module (re-export shim) | request-response | itself (current, lines 8-17) | exact (re-point) |
| `weatherbot/reliability/__init__.py` (mod) | module (re-export shim) | n/a | itself (current, lines 8-26) | exact (re-point) |
| `weatherbot/scheduler/daemon.py` (mod) | controller (`fire_slot`) | event-driven (retry-then-alert) | itself (current `fire_slot`, lines 231-364) | exact (adapt, not rewrite — D-07) |
| `weatherbot/cli.py` (mod) | controller (`send_now` dispatch) | request-response | itself (current, line 159) | exact (keep byte-identical) |
| `pyproject.toml` (mod) | config (build/coverage/dev-dep) | n/a | itself (current, lines 19-49) | exact (additive) |

---

## Pattern Assignments

### `yahir_reusable_bot/channels/base.py` (model + abstract contract, request-response)

**Analog:** `weatherbot/channels/base.py` (the WHOLE current file).
**The move (D-03 / D-12):** copy `DeliveryResult` and `Channel` **verbatim**, then make exactly two deletions — drop the `send_briefing` method (lines 52-61) and drop the `TYPE_CHECKING` `Forecast` import (lines 19-20). After deletion, `Channel` is `send(text) -> DeliveryResult` only. These two deletions are what make all three gates pass at once (the litmus signature hit `send_briefing`/`forecast: Forecast` disappears; the grimp `weatherbot.weather.models` edge disappears).

**Delete these two blocks** (current `weatherbot/channels/base.py`):
```python
# lines 17-20 — DELETE the TYPE_CHECKING Forecast import (the only module→app edge)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weatherbot.weather.models import Forecast
```
```python
# lines 52-61 — DELETE send_briefing from the module abstraction (D-03)
    def send_briefing(self, text: str, forecast: Forecast) -> DeliveryResult:
        """Deliver the briefing, optionally with provider-specific enrichment.
        ...
        """
        return self.send(text)
```

**Keep verbatim** (current lines 23-50) — `DeliveryResult` dataclass + `Channel` ABC with `name` attr and the abstract `send`:
```python
@dataclass
class DeliveryResult:
    ok: bool
    detail: str = ""


class Channel(ABC):
    name: str = "channel"

    @abstractmethod
    def send(self, text: str) -> DeliveryResult:
        """Deliver the canonical plain-text briefing body."""
        raise NotImplementedError
```

**Anti-pattern (Pitfall 3):** there must be exactly ONE `Channel` class after this move. Do NOT leave a `Channel` definition behind in `weatherbot/channels/base.py` — either delete that file or make it a pure re-export shim (see Open Question 2 in RESEARCH; planner's discretion, D-01). `DiscordWebhookChannel` must subclass the *module's* `Channel` so `isinstance(ch, Channel)` in `tests/test_channel.py:84` still tests the one true class.

---

### `yahir_reusable_bot/reliability/retry.py` (utility / retry engine, event-driven transform)

**Analog:** `weatherbot/reliability/retry.py` — **moves 100% verbatim** (RESEARCH VERIFIED: zero `weatherbot.*` edges today; pure `tenacity`/`httpx`/`structlog`/stdlib composition).

**Import block to copy unchanged** (current lines 39-54) — all third-party / stdlib, all allowed in the module:
```python
from __future__ import annotations

import random
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import httpx
import structlog
from tenacity import (
    Retrying,
    retry_if_exception,
    retry_if_result,
    stop_after_attempt,
)

_log = structlog.get_logger(__name__)
```

**Public surface that moves** (these names are what `weatherbot/reliability/__init__.py` re-exports):
- Constants: `BURST_SIZE`, `BURST_SPREAD_S`, `MID_PAUSE_S`, `RETRY_AFTER_CAP_S` (lines 57-67); `PERMANENT`/`TRANSIENT` frozensets (lines 71-72); `REASON_TRANSIENT_EXHAUSTED`/`REASON_AUTH_FAILED`/`REASON_INTERNAL_ERROR` (lines 75-77).
- Functions: `is_transient` (80), `is_auth_failure` (94), `parse_retry_after` (102), `_within_burst_wait` (133), `two_burst_wait` (146), `build_retrying` (184).

**Litmus note (D-11):** the docstrings here say "OpenWeather", "Discord", "briefing" (prose) — the AST signature-only litmus IGNORES these by construction; do NOT scrub them (that's deferred to Phase 28 / DOCS-01). No `def`/`class`/param/annotation NAME in this file matches the litmus pattern (VERIFIED zero hits).

**`# pragma: no cover` convention preserved** (line 125): the existing `# pragma: no cover - <reason>` comment moves verbatim with the function (Phase-21 D-09 convention).

---

### `yahir_reusable_bot/reliability/__init__.py` (re-export surface)

**Analog:** `weatherbot/reliability/__init__.py` — **the body moves unchanged** (it already re-exports from `.retry`). Copy current lines 8-26 verbatim into the new file:
```python
from .retry import (
    REASON_AUTH_FAILED,
    REASON_INTERNAL_ERROR,
    REASON_TRANSIENT_EXHAUSTED,
    build_retrying,
    is_auth_failure,
    is_transient,
    parse_retry_after,
)

__all__ = [
    "REASON_AUTH_FAILED",
    "REASON_INTERNAL_ERROR",
    "REASON_TRANSIENT_EXHAUSTED",
    "build_retrying",
    "is_auth_failure",
    "is_transient",
    "parse_retry_after",
]
```
Note: the app-side `weatherbot/reliability/__init__.py` becomes a re-export shim pointing back at THIS (see modified-files section).

---

### `yahir_reusable_bot/channels/__init__.py` (re-export surface)

**Analog:** `weatherbot/channels/__init__.py` (current lines 8-17) — but **a SUBSET**: the module package exports only the clean two (`Channel`, `DeliveryResult`); `DiscordWebhookChannel` and `build_channel` STAY app-side (D-04).
```python
from .base import Channel, DeliveryResult

__all__ = ["Channel", "DeliveryResult"]
```

---

### `yahir_reusable_bot/ports/alerts.py` (AlertSink port, event-driven)

**No exact analog — this is the one genuinely new abstraction (D-07).** Mirror the codebase's two existing callable-port shapes:

**Shape source A — typed `Callable` alias** (`weatherbot/channels/factory.py:31`):
```python
_REGISTRY: dict[str, Callable[["Config", "Settings"], Channel]] = {
    "discord": _build_discord,
}
```

**Shape source B — callable fields on a dataclass** (`weatherbot/interactive/state.py:55-56`):
```python
    bot_alive: Callable[[], bool]
    monitor_alive: Callable[[], bool] | None = None
```

**Shape the port to what `fire_slot` actually calls** (the two app-side store functions it consumes — read this session):

`weatherbot/weather/store.py:317` —
```python
def record_alert(
    db_path: str | Path,
    location_name: str,
    slot_time: str,
    local_date: str,
    reason: str,
    severity: str = "critical",
) -> bool:        # returns "self_first": True ⇒ THIS caller wrote the row
```
`weatherbot/weather/store.py:411` —
```python
def resolve_alert(
    db_path: str | Path,
    location_name: str,
    slot_time: str,
    local_date: str,
) -> None:
```

**Port content (Protocol, weather-clean — discretion D-07):** a `typing.Protocol` (or two `Callable` aliases) with `record_alert(...) -> bool` and `resolve_alert(...) -> None` matching the arg lists above. **Litmus constraint (D-11):** parameter/annotation NAMES must NOT contain a litmus noun — so `location_name` must be renamed in the *port signature* (e.g. `location_id` / `target`) even though the app impl keeps `location_name`. Do NOT add `briefing_missed` or any heartbeat method (D-08). The `Forecast`/weather types never appear; args are `str | Path` + `str` + `bool`.

**`exclude_also` already covers Protocol stubs** (`pyproject.toml:59-63`): `raise NotImplementedError` and bare `...` ellipsis bodies are excluded from coverage — the port's stub bodies inherit this.

---

### `tests/test_import_hygiene.py` (gate self-proof meta-test)

**Analog:** `tests/test_oracle_selfproof.py` (the WHOLE Phase-21 file) — copy its **structure**, not its content. The shared pattern: a standing GREEN test whose green-ness *depends on a real perturbation tripping the guard* (`with pytest.raises(AssertionError): ...`). Mirror that for the import-graph gate's self-proof.

**Module-docstring discipline to copy** (selfproof lines 1-38): a long docstring stating (1) what the guard protects, (2) the two halves (unperturbed must pass / perturbed must fail), (3) why it's NOT an xfail marker. Reproduce for each new gate.

**Self-proof half-structure to copy** (selfproof lines 95-132) — the "two halves, same slot" shape:
```python
def test_field_reorder_is_caught(json_snapshot):
    good = _real_embed_golden()
    assert good == json_snapshot(name="real_embed")          # Half 1: real value passes
    reordered = {**good, "fields": list(reversed(good["fields"]))}
    with pytest.raises(AssertionError):                       # Half 2: perturbation must FAIL
        assert reordered == json_snapshot(name="real_embed")
```

**Apply to the three gates (RESEARCH Code Examples + Patterns 4-6 are the verified bodies):**
1. `test_module_imports_zero_app_code` — grimp graph assert (RESEARCH § "grimp gate — full pytest test", VERIFIED). Self-proof half: temporarily inject a `(importer, "weatherbot.x")` edge into a copy of the leak-scan and assert it's caught.
2. `test_module_imports_with_app_blocked` — `sys.meta_path` blocker smoke test (RESEARCH Pattern 5, VERIFIED). Remember the `finally:` cleanup that purges `sys.modules["yahir_reusable_bot*"]`.
3. `test_litmus_clean` — AST signature walk (RESEARCH Pattern 6, VERIFIED). Self-proof half: feed a synthetic `def send_briefing(forecast): ...` source through `public_names()` and assert the pattern catches it; feed a docstring-only weather noun and assert it does NOT.

**Import-path convention to copy** (selfproof lines 48-52): real production symbols imported by absolute path (`from weatherbot.interactive import ...`). The new gates import `grimp`, `ast`, `sys`, `importlib`, `pkgutil`, `pytest`.

---

### `weatherbot/channels/__init__.py` (MODIFIED — re-export shim)

**Analog:** itself (current lines 8-17). **Re-point** the `Channel`/`DeliveryResult` source from `.base` to the module; keep the app-side concrete + factory re-exports so call-site imports stay byte-identical.

Current:
```python
from .base import Channel, DeliveryResult
from .discord import DiscordWebhookChannel
from .factory import build_channel
```
Target (RESEARCH Pattern 1):
```python
from yahir_reusable_bot.channels import Channel, DeliveryResult   # re-pointed (one Channel)
from .discord import DiscordWebhookChannel    # STAYS app-side (D-04)
from .factory import build_channel            # STAYS app-side
```
`__all__` (lines 12-17) is unchanged. This keeps `tests/test_channel.py`'s `from weatherbot.channels import (Channel, DeliveryResult, ...)` and `isinstance(ch, Channel)` green with zero churn.

**Cross-file caveat:** `weatherbot/scheduler/daemon.py:82` and `weatherbot/channels/discord.py:26` import from `weatherbot.channels.base` *specifically* (not the package `__init__`). If `base.py` is deleted, re-point BOTH:
- `daemon.py:82` (under `TYPE_CHECKING`): `from weatherbot.channels.base import Channel, DeliveryResult` → re-point to `from weatherbot.channels import ...` or `from yahir_reusable_bot.channels import ...`.
- `discord.py:26`: `from .base import Channel, DeliveryResult` → re-point to the module (and `discord.py` must subclass the module's `Channel`).

---

### `weatherbot/reliability/__init__.py` (MODIFIED — re-export shim)

**Analog:** itself (current lines 8-26). Replace `from .retry import (...)` with `from yahir_reusable_bot.reliability import (...)`, keeping the identical name list + `__all__`. `weatherbot/scheduler/daemon.py:58-64` and `weatherbot/cli.py` import `from weatherbot.reliability import build_retrying, is_transient, ...` — the shim keeps those byte-identical (the Phase-21 exception-identity pins stay green).

---

### `weatherbot/scheduler/daemon.py` (MODIFIED — `fire_slot`, ADAPT not rewrite)

**Analog:** itself, current `fire_slot` (lines 131-364). **D-07: adapt, never rewrite.** `fire_slot` is APP code and may keep importing `record_alert`/`resolve_alert` directly from `weatherbot.weather.store` — the AlertSink port matters for the *module's* surface, not for forcing an injection here. The minimal byte-identical move: imports of `build_retrying`/`is_auth_failure` now resolve through the re-export shim (no source change at the call sites).

**Do NOT touch the retry/alert orchestration body.** These exact call sites stay byte-identical (current lines shown):
```python
# line 231 — build_retrying call (args unchanged)
retrying = build_retrying(stop, attempts_per_burst=..., burst_spread_s=..., mid_pause_s=...)

# lines 264-266 / 282-288 / 308-314 / 349-355 — record_alert calls (args unchanged)
self_first = record_alert(db_path, location.id, slot.time, local_date, reason)

# line 330 — resolve_alert on success (unchanged)
resolve_alert(db_path, location.id, slot.time, local_date)
```
The `except httpx.HTTPStatusError` / `except (TimeoutException, ConnectError, ReadError)` / `if not result.ok` / broad `except Exception` reason-taxonomy branches (lines 254-364) are the byte-identical-locked surface — `test_scheduler.py` + `test_reliability.py` + the DB-row golden arbitrate any drift.

**Out of scope (D-08):** `_heartbeat_tick` (line 569) and the `__heartbeat__`/`stamp_tick` lifecycle are NOT touched this phase (Phase 25).

---

### `weatherbot/cli.py` (MODIFIED — `send_now` dispatch, keep byte-identical)

**Analog:** itself (line 159). The dispatch line stays EXACTLY:
```python
result = channel.send_briefing(result_lr.text, result_lr.forecast)
```
Because the module `Channel` loses `send_briefing` (D-03), `send_now` must keep getting a channel that HAS it. Resolve app-side (RESEARCH Pattern 2 / Pitfall 2 — planner's discretion):
- **(a) lower-risk:** an app-side `BriefingChannel(Channel)` intermediate base re-adding the default `send_briefing(text, forecast) -> self.send(text)` + the `Forecast` `TYPE_CHECKING` import; `DiscordWebhookChannel` subclasses it. Preserves the exact "send_now calls send_briefing on whatever channel it gets" contract.
- **(b):** keep `send_briefing` only on `DiscordWebhookChannel` (the sole v1 channel) — its override at `discord.py:54-70` already exists and stays put.

Either way the returned `Forecast` import lives APP-side → no new module→app edge. `tests/test_send_now.py` + `test_channel.py::test_base_send_briefing_defaults_to_send_text` are the gates.

---

### `pyproject.toml` (MODIFIED — additive build/coverage/dev-dep)

**Analog:** itself (current lines 19-49). Three additive edits (RESEARCH § "pyproject.toml additions", backend VERIFIED = hatchling, no `[tool.hatch]` block exists today):

1. **New `[tool.hatch.build.targets.wheel]` block** (D-02 — without it hatchling silently drops the 2nd package, Pitfall 4):
```toml
[tool.hatch.build.targets.wheel]
packages = ["weatherbot", "yahir_reusable_bot"]
```
2. **Add `grimp>=3.14` to the EXISTING dev group** (current lines 26-33 — append one line, dev-only, D-09):
```toml
    "grimp>=3.14",
```
3. **Extend `[tool.coverage.run] source`** (current lines 42-49 — append, Pitfall 5):
```toml
    "yahir_reusable_bot",
```
Leave `requires-python`, `[build-system]`, `[project.scripts]` (the `weatherbot` console script — `yahir_reusable_bot` ships NONE), `[tool.pytest.ini_options]` (`pythonpath=["."]`, `testpaths`), and `[tool.coverage.report] exclude_also` UNCHANGED (D-01: byte-undisturbed test/coverage config).

---

## Shared Patterns

### Re-export shim (keeps the 732-test suite's import paths byte-identical)
**Source:** the existing `weatherbot/channels/__init__.py` (lines 8-17) and `weatherbot/reliability/__init__.py` (lines 8-26) ALREADY follow the "import symbols, list them in `__all__`" re-export idiom.
**Apply to:** both moved subpackages' app-side `__init__` files. Re-point the source to `yahir_reusable_bot.*`; preserve the exact symbol names + `__all__`. Zero call-site churn = byte-identical-safe.

### Exactly ONE class (no dual-definition)
**Source:** Pitfall 3 (RESEARCH). `isinstance(ch, Channel)` (`test_channel.py:84`) is only correct if there is a single `Channel`.
**Apply to:** `Channel` + `DeliveryResult` — define once in `yahir_reusable_bot/channels/base.py`; everywhere else re-exports or subclasses that one.

### `TYPE_CHECKING` import block is a graph edge
**Source:** the three current `if TYPE_CHECKING:` app-import blocks — `channels/base.py:19-20` (the leak D-03 removes), `channels/discord.py:28-29`, `channels/factory.py:17-19`, `scheduler/daemon.py:81-84`.
**Apply to:** the grimp gate sees these by default (`exclude_type_checking_imports=False` — keep it). The MODULE files must carry zero such app-import blocks; the APP files keep theirs freely.

### `# pragma: no cover - <reason>` convention
**Source:** `weatherbot/reliability/retry.py:125` (Phase-21 D-09 convention).
**Apply to:** moves verbatim with the code; any new defensive branch in the module follows the same `# pragma: no cover - <reason>` form.

### Self-proof meta-test (perturbation-must-fail)
**Source:** `tests/test_oracle_selfproof.py` (whole file) — green BECAUSE `pytest.raises(AssertionError)` catches a real perturbation.
**Apply to:** the import-graph + litmus gates in `tests/test_import_hygiene.py` (a passing gate is only trustworthy if a deliberately-injected leak/noun is proven to trip it).

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `yahir_reusable_bot/ports/alerts.py` (the `AlertSink` Protocol itself) | port | event-driven | No existing `typing.Protocol` port exists in the codebase. SHAPE is mirrored from the two callable-port idioms (`channels/factory.py:31` typed `Callable` alias; `interactive/state.py:55-56` callable dataclass fields) and the arg lists of `store.record_alert`/`store.resolve_alert`. Planner uses these as the shape reference; the method body is new (D-07, discretion). |
| The three gate BODIES (grimp / meta_path / AST) | test | n/a | No existing import-hygiene/AST-litmus test in the repo. The verified bodies live in `22-RESEARCH.md` (Code Examples + Patterns 4-6); `test_oracle_selfproof.py` supplies only the meta-test *structure*, not the gate logic. |

---

## Metadata

**Analog search scope:** `weatherbot/channels/`, `weatherbot/reliability/`, `weatherbot/scheduler/daemon.py`, `weatherbot/cli.py`, `weatherbot/weather/store.py`, `weatherbot/interactive/state.py`, `tests/test_oracle_selfproof.py`, `pyproject.toml`.
**Files scanned:** 11 source/config/test files read this session (full or targeted ranges).
**Pattern extraction date:** 2026-06-27
**Working tree state:** Phase-21 artifacts present; 732-test suite + syrupy goldens are the byte-identical oracle.
