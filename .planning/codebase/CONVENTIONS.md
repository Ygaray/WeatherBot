# Coding Conventions

**Analysis Date:** 2026-07-07

## Naming Patterns

**Files:**
- Lowercase, single-word module names: `discord.py`, `retry.py`, `loader.py`, `daemon.py`, `pidfile.py`
- Package dirs group by domain: `weatherbot/channels/`, `weatherbot/weather/`, `weatherbot/scheduler/`, `weatherbot/config/`, `weatherbot/reliability/`, `weatherbot/interactive/`, `weatherbot/ops/`
- Test files mirror the unit under test with a `test_` prefix: `tests/test_client.py`, `tests/test_config.py`; golden suites use `test_golden_<subject>.py`; meta/harness tests use descriptive names (`test_oracle_selfproof.py`, `test_import_hygiene.py`).

**Functions:**
- `snake_case` for functions and methods: `send_now`, `claim_slot`, `parse_days`, `worst_case_seconds`, `build_retrying`.
- Leading underscore for module-private helpers and pydantic validators: `_load_fixture`, `_post`, `_hhmm`, `_default_id_from_name`, `_budget_under_grace`.

**Variables:**
- `snake_case` locals; module-level constants are `UPPER_SNAKE`: `DEFAULT_USERNAME`, `RETRY_AFTER_CAP_S`, `FROZEN`, `_CATCHUP_GRACE_SECONDS`.
- Module-private constants keep the leading underscore: `_VALID_UNITS`, `_VALID_FORECAST_KINDS`.
- Module loggers are bound to a private `_log`: `_log = structlog.get_logger(__name__)` or `_log = logging.getLogger(__name__)`.

**Types:**
- `PascalCase` for classes / pydantic models: `Schedule`, `ForecastSchedule`, `Location`, `Config`, `DiscordWebhookChannel`, `DeliveryResult`, `Channel`.
- Config models are nouns; channel classes end in `Channel`.

## Code Style

**Formatting:**
- `ruff` (>=0.15.16) is the single lint + format tool (declared in `[dependency-groups] dev` of `pyproject.toml`).
- No `[tool.ruff]` table exists — the project runs **ruff defaults** (line length 88, double quotes, spaces). Match that: 4-space indent, double-quoted strings, ~88-col wrapping (multi-line f-strings are broken across lines to stay under width, e.g. `config/models.py`).

**Linting:**
- Inline suppressions use the `# noqa: <RULE>` form with an explicit code, e.g. `def fetch_onecall(self, location, units):  # noqa: ANN001` (`tests/test_oracle_selfproof.py`).
- Run lint/format via `uv run ruff check` / `uv run ruff format`.

## Import Organization

**Order (ruff/isort default groups, blank-line separated):**
1. `from __future__ import annotations` — **first line of every module** (universal in this codebase).
2. Standard library (`import json`, `import sqlite3`, `from datetime import ...`, `from zoneinfo import ...`).
3. Third-party (`import structlog`, `from pydantic import ...`, `from discord_webhook import ...`, `from apscheduler...`).
4. First-party (`from weatherbot.reliability.retry import ...`, `from yahir_reusable_bot.channels import ...`).

**Deferred / conditional imports (deliberate patterns):**
- `if TYPE_CHECKING:` blocks hold annotation-only imports to avoid runtime import edges — e.g. `discord.py` channel imports `Forecast` only under `TYPE_CHECKING` (`channels/base.py`, `channels/discord.py`). This is excluded from coverage (`exclude_also` in `pyproject.toml`).
- Lazy in-function imports break potential cycles / defer heavy deps (e.g. `from weatherbot.weather.store import claim_slot` inside a helper in `conftest.py`). An import-hygiene gate (`tests/test_import_hygiene.py`, grimp dev-dep) forbids reintroducing the resolved `render_embed ↔ PanelView` cycle.

**Path aliases:**
- None. `pythonpath = ["."]` in `[tool.pytest.ini_options]` makes both `weatherbot.*` and `tests.*` importable; tests import shared harness via `from tests.conftest import FROZEN, embed_to_golden`.

## Pydantic Model Patterns

This is the dominant convention in `weatherbot/config/models.py` — **follow it for every config model**:

- **Pydantic v2** only (`pydantic>=2.13.4`). Never mix v1-era APIs.
- Every config model sets `model_config = ConfigDict(extra="forbid", frozen=True)`:
  - `extra="forbid"` → an unknown TOML key **fails loud at load** (the project's "fail-loud-at-load" posture), not silently at 9am.
  - `frozen=True` → immutable snapshots safe for lock-free shared reads via `ConfigHolder`.
- **Field validators** are `@field_validator("field")` + `@classmethod`, named with a leading underscore, and `raise ValueError(f"... got {v!r}")` on bad input (always include the offending value with `!r`):
  ```python
  @field_validator("threshold")
  @classmethod
  def _threshold_in_range(cls, v: float) -> float:
      if not 0 <= v <= 20:
          raise ValueError(f"uv.threshold must be between 0 and 20, got {v!r}")
      return v
  ```
- **Cross-field / whole-model** checks use `@model_validator(mode="after")` returning `self` (e.g. `Reliability._budget_under_grace`).
- To mutate a frozen model inside an after-validator, use the pydantic-blessed escape hatch `object.__setattr__(self, "id", self.name)` (see `Location._default_id_from_name`).
- **Optional-vs-default discipline is intentional and load-bearing:**
  - Absence must mean "not configured" → plain optional with `None` default: `bot: BotConfig | None = None`.
  - Absence must mean "use defaults" → `Field(default_factory=UvConfig)` / `Field(default_factory=list)`.
  - Choosing the wrong one changes behavior — decide by "what does an absent table mean?"
- Reuse one source of truth: `ForecastSchedule` reuses `Schedule`'s HH:MM + `parse_days` validators verbatim rather than re-deriving them.

## structlog Usage

- **Two logging systems coexist by design:**
  - **structlog** is the app default for the long-running daemon / CLI / interactive paths (`weatherbot/__init__.py`, `scheduler/daemon.py`, `interactive/*`).
  - **stdlib `logging`** is used where a third-party lib's logger must be tamed or where a simple module logger suffices (`channels/discord.py`, `weather/client.py`, `ops/*`).
- **Project structlog default** (`weatherbot/__init__.py`) renders to **STDERR** (not STDOUT — STDOUT is reserved for the briefing) via a `PrintLoggerFactory` over a live-stderr wrapper, with `wrapper_class=structlog.make_filtering_bound_logger(logging.INFO)`. The CLI's `_configure_logging` tunes the effective level per subcommand.
- **Bind a module logger** as `_log = structlog.get_logger(__name__)`.
- **Log events as a short event name + key=value pairs**, never interpolated prose:
  ```python
  _log.critical("briefing_missed", location=location.name, reason=reason)
  ```
- **Credential hygiene is mandatory in logs (a hard convention):** never log the webhook URL, API key, or bot token. `channels/discord.py` raises the third-party `discord_webhook` / `requests` loggers to WARNING so the URL can't leak, and log details carry only `type(exc).__name__` or a status + body snippet — never the secret.

## Error Handling

- **Expected failures return a result object; they do NOT raise.** A non-2xx webhook response or a network blip becomes `DeliveryResult(ok=False, detail=...)` — the `send`/`_post` contract is "never raises" (`channels/discord.py`). `detail` carries a status + short snippet or the exception class name only.
- **Config/validation errors DO raise** (`ValueError`) — fail loud at load, never defer.
- Guard against surprising third-party return shapes: `discord_webhook.execute()` may return `None`/a list, so `getattr(response, "status_code", None)` is checked before use.
- The retry engine reraises the original exception (`reraise=True`) so the caller can classify it (see below).

## Retry / tenacity Patterns

- The two-burst retry engine lives in the **hub** `yahir_reusable_bot.reliability.retry`; `weatherbot/reliability/retry.py` is a **re-export shim** (`__all__` re-exports the constants, `REASON_*` taxonomy, and `build_retrying` / `is_transient` / `is_auth_failure` / `parse_retry_after` / `two_burst_wait`). Import retry symbols via `from weatherbot.reliability.retry import ...` to keep call sites byte-identical.
- **Timing knobs are user-config** (`Reliability` model): `attempts_per_burst` / `burst_spread_seconds` / `mid_pause_seconds`. The model validates the *actual jittered worst-case budget* stays under the 90-min catch-up grace window (`worst_case_seconds()` is the single source of truth for both the validator and the `--check` echo).
- **Build a retrying callable, wrap the single attempt, classify on exhaustion** (`scheduler/daemon.py`):
  ```python
  retrying = build_retrying(stop, attempts_per_burst=..., burst_spread_s=..., mid_pause_s=...)
  def _attempt() -> DeliveryResult:
      return send_now(...)          # let httpx.HTTPStatusError propagate (carries Retry-After)
  try:
      result = retrying(_attempt)
  except httpx.HTTPStatusError as exc:
      reason = REASON_AUTH_FAILED if is_auth_failure(exc) else REASON_TRANSIENT_EXHAUSTED
      ...                            # release claim, record alert, _log.critical("briefing_missed", ...)
  ```
- The retry is **interruptible**: the daemon's stop `Event.wait` is threaded into the wait callable so SIGTERM cancels an in-progress pause cleanly. Do NOT hand-roll retry loops — use `build_retrying`.
- Let the transport error (`httpx.HTTPStatusError` with `.response`/`Retry-After`) **propagate untranslated** so the wait callable can honor the capped `Retry-After` (`RETRY_AFTER_CAP_S`).

## Comments

**When to Comment:**
- Comments explain **why**, not what — nearly every non-obvious decision cites its origin (e.g. `D-07`, `CONF-02`, `Pitfall 5`, `T-04-01`, requirement IDs). This decision-provenance style is pervasive; preserve it when editing.
- Module docstrings are substantial: they state the module's contract, its seams, and the invariants it upholds.

**Docstrings:**
- Every module, public class, and public method has a docstring. Method docstrings state the contract ("never raises", "fails loud at load") and reference the requirement/decision IDs they satisfy.
- Use `!r` in error messages and reStructuredText cross-refs (`:class:`, `:mod:`) in docstrings.

## Function & Module Design

**Function design:**
- Type-annotate signatures and returns (`def worst_case_seconds(self) -> float:`, `def _post(self, text: str, embed: DiscordEmbed | None) -> DeliveryResult:`). Use `X | None` union syntax (enabled by the `from __future__ import annotations` header, targeting Python 3.12+).
- Keep-alive credentials private (`self._url`, `self._username`) and never echoed.

**Module design:**
- **App-side shims re-export hub symbols** to keep import paths stable after the v2.0 physical split (`channels/base.py`, `reliability/retry.py`). App-specific enrichment (e.g. `send_briefing`'s embed, `Channel.send_briefing` default) stays app-side; reusable mechanism lives in `yahir_reusable_bot`.
- Explicit `__all__` on re-export/shim modules.
- Composition-root injection over cyclic imports: `render_embed` is injected into the hub `PanelKit` rather than imported back (guarded by `tests/test_import_hygiene.py`).

---

*Convention analysis: 2026-07-07*
