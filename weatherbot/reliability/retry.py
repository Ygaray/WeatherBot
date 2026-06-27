"""Two-burst retry engine for the Phase-4 reliability layer (RELY-01/02, D-07/08).

This module is the shared retry contract for the whole phase: Plans 03 (daemon
patient path) and 04 (manual tight path) both import :func:`build_retrying`,
the classifiers, and the ``REASON_*`` taxonomy from here rather than re-deriving
the classification logic (D-07/08/09).

It composes ``tenacity`` primitives into the locked two-burst schedule (D-07):
Burst 1 = ``BURST_SIZE`` attempts spread across ~``BURST_SPREAD_S`` seconds,
then a ~``MID_PAUSE_S`` pause, then Burst 2 = another ``BURST_SIZE`` attempts —
``2 * BURST_SIZE`` total, intentionally under Phase 3's 90-min catch-up grace.

Two properties are load-bearing:

* **Interruptibility (D-07 / Pitfall 1).** ``build_retrying`` wires
  ``sleep=stop_event.wait`` so the entire schedule — including the long mid-pause
  — abandons the instant the daemon's ``threading.Event`` is set on SIGTERM /
  Ctrl-C. The blocking stdlib sleep is deliberately never used here.
* **Honoring a capped ``Retry-After`` (Pattern 1 <-> Pattern 4).** The wait
  callable ``two_burst_wait`` does not merely *parse* a ``Retry-After`` header —
  it inspects the failing attempt's outcome and, on an OpenWeather fetch 429
  whose response carries ``Retry-After``, WAITS at least the capped value
  (``max(base, parse_retry_after(resp))``, never above ``RETRY_AFTER_CAP_S``).
  This keeps :func:`parse_retry_after` live at runtime instead of dead code.

Scope of the ``Retry-After`` honoring (Pitfall 2 / Anti-Patterns): it applies to
the OpenWeather FETCH 429 path ONLY. The Discord channel is constructed with
``rate_limit_retry=True`` and owns its own within-attempt 429 wait; a Discord
``DeliveryResult(ok=False)`` is treated as a single transient unit (the
``retry_if_result`` predicate) and carries no ``httpx.HTTPStatusError`` /
response, so the wait callable naturally falls through to the plain two-burst
base for it — we never double-retry a Discord 429.

Secret hygiene (T-04-01): this module never references the OpenWeather API key,
its host, or a delivery URL; the optional ``before_sleep`` log event carries only
the attempt number and burst index — outcome fields only, never a secret.
"""

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

# --- Two-burst schedule constants (D-07 / D-09 defaults) ------------------- #
BURST_SIZE = 8  # attempts per burst (16 total across two bursts)
BURST_SPREAD_S = 600  # ~10 min spread across one burst's attempts
MID_PAUSE_S = 2700  # ~45 min pause between burst 1 and burst 2

# Cap on an untrusted Retry-After header so an oversized value can't blow the
# retry budget past Phase 3's 90-min grace (D-08 / Pitfall 5, Claude's discretion).
# This cap is also folded into the config budget guard (Reliability._budget_under_grace,
# WR-02): the real worst-case per-retry wait is max(within_burst_max, RETRY_AFTER_CAP_S),
# so with the defaults the worst case is 14*max(128.6, 120) + 2700 ≈ 4500s ≈ 75 min —
# under, not "comfortably ~65 min under", the 90-min grace (WR-01/WR-02).
RETRY_AFTER_CAP_S = 120

# Status-code classification (D-08). 401/403 are auth failures (never retried);
# 400/404 are other permanent client errors (never retried).
PERMANENT = frozenset({400, 401, 403, 404})
TRANSIENT = frozenset({429, 500, 502, 503, 504})

# Reason taxonomy consumed by Plans 03/04 when writing a briefing_missed alert.
REASON_TRANSIENT_EXHAUSTED = "transient_exhausted"
REASON_AUTH_FAILED = "auth_failed"
REASON_INTERNAL_ERROR = "internal_error"


def is_transient(exc: BaseException) -> bool:
    """True for retryable failures: network errors and transient HTTP statuses.

    Timeouts / connect / read errors and ``HTTPStatusError`` whose status is in
    :data:`TRANSIENT` (429 / 5xx) are retryable; everything else (incl. 4xx in
    :data:`PERMANENT`) is not (D-08, RELY-02).
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in TRANSIENT
    return False


def is_auth_failure(exc: BaseException) -> bool:
    """True only for an ``HTTPStatusError`` 401/403 (chooses ``reason=auth_failed``)."""
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {
        401,
        403,
    }


def parse_retry_after(resp: httpx.Response) -> float | None:
    """Parse a ``Retry-After`` header (seconds OR HTTP-date), capped at the cap.

    Returns the capped wait in seconds, or ``None`` when the header is absent OR
    malformed (WR-05). The header is untrusted input (V5) — an oversized value is
    clamped to :data:`RETRY_AFTER_CAP_S` so it can't blow the retry budget (Pattern
    4, D-08), and a garbage HTTP-date degrades to ``None`` (the wait callable then
    uses the plain two-burst base) rather than raising.
    """
    ra = resp.headers.get("Retry-After")
    if not ra:
        return None
    try:
        secs = float(ra)  # seconds form
    except ValueError:
        # RFC HTTP-date form (stdlib, RFC-compliant). The header is UNTRUSTED (V5):
        # a malformed date makes ``parsedate_to_datetime`` either raise ValueError
        # or return None (→ a TypeError on the subtraction). Treat ANY parse failure
        # as "no usable header" so the wait callable falls back to the plain base
        # instead of escaping into the daemon's broad handler / crashing the CLI
        # (WR-05).
        try:
            dt = parsedate_to_datetime(ra)
            if dt is None:  # pragma: no cover - CPython 3.12 parsedate_to_datetime always raises ValueError on malformed input, never returns None; this is a cross-version defensive guard
                return None
            secs = (dt - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            return None
    return max(0.0, min(secs, RETRY_AFTER_CAP_S))


def _within_burst_wait(
    attempt_number: int, *, burst_spread_s: float, burst_size: int, mid_pause_s: float
) -> float:
    """Base two-burst wait (Pattern 1), independent of any Retry-After honoring."""
    if attempt_number == burst_size:
        # Just finished burst 1 -> the long interruptible pause before burst 2.
        return mid_pause_s
    # Spread a burst's attempts across ~burst_spread_s with bounded jitter.
    step = burst_spread_s / (burst_size - 1)
    jitter = random.uniform(0, step * 0.5)
    return step + jitter


def two_burst_wait(
    retry_state,
    *,
    burst_spread_s: float = BURST_SPREAD_S,
    burst_size: int = BURST_SIZE,
    mid_pause_s: float = MID_PAUSE_S,
) -> float:
    """Two-burst wait that HONORS a capped ``Retry-After`` (Pattern 1 <-> Pattern 4).

    1. Compute the base two-burst wait from ``retry_state.attempt_number``.
    2. Inspect ``retry_state.outcome``: when the failing attempt raised an
       ``httpx.HTTPStatusError`` whose response carries a ``Retry-After`` header
       (the OpenWeather fetch 429 path), return ``max(base, capped_retry_after)``
       — i.e. wait AT LEAST the capped value, never above the cap. Otherwise (no
       outcome, no exception, no header — incl. the Discord ``ok=False`` path)
       return the plain base.
    """
    base = _within_burst_wait(
        retry_state.attempt_number,
        burst_spread_s=burst_spread_s,
        burst_size=burst_size,
        mid_pause_s=mid_pause_s,
    )
    outcome = getattr(retry_state, "outcome", None)
    if outcome is not None and outcome.failed:
        exc = outcome.exception()
        if isinstance(exc, httpx.HTTPStatusError):
            ra = parse_retry_after(exc.response)  # already capped at RETRY_AFTER_CAP_S
            if ra is not None:
                # Wait at least the base spacing, honor a larger Retry-After, but
                # keep RETRY_AFTER_CAP_S a HARD ceiling on the honored wait (D-08).
                # base carries up to 0.5*step of jitter and can itself exceed the
                # cap, so an unclamped max(base, ra) would breach the very budget
                # guarantee stated in this module's docstring. Clamp it.
                return min(max(base, ra), RETRY_AFTER_CAP_S)
    return base


def build_retrying(
    stop_event,
    *,
    attempts_per_burst: int = BURST_SIZE,
    burst_spread_s: float = BURST_SPREAD_S,
    mid_pause_s: float = MID_PAUSE_S,
) -> Retrying:
    """Build a ``Retrying`` for the two-burst interruptible schedule (D-07).

    * ``wait`` is the :func:`two_burst_wait` closure (closing over the burst
      params) so the schedule actually WAITS a honored, capped ``Retry-After``.
    * ``sleep=stop_event.wait`` is the LOCKED interruptibility constraint (D-07 /
      Pitfall 1) — the mid-pause abandons on shutdown; the blocking stdlib sleep is never used.
    * ``retry`` retries a transient EXCEPTION (fetch path) OR a non-ok
      ``DeliveryResult`` (send path returns ``ok=False`` instead of raising).
    * ``stop_after_attempt(2 * attempts_per_burst)`` bounds the whole schedule.
    * ``retry_error_callback`` returns the FINAL outcome's ``.result()`` on
      exhaustion. This is load-bearing for the daemon's reason taxonomy: when
      every attempt returns a non-ok ``DeliveryResult`` (a Discord outage — no
      exception ever raised), bare ``reraise=True`` would raise ``RetryError``
      (it can only reraise a real exception, and a non-ok RESULT has none), which
      ``fire_slot`` then mis-classifies as ``internal_error``. Routing through
      ``rs.outcome.result()`` instead RETURNS the last non-ok ``DeliveryResult``
      (so ``fire_slot`` records ``transient_exhausted``), while an EXHAUSTED
      exception outcome (5xx/timeout) is re-raised by ``.result()`` and caught by
      ``fire_slot``'s ``except httpx.*`` handlers (also ``transient_exhausted``).
      A non-retryable exception (401/403) still propagates immediately — the stop
      callback only fires on attempt exhaustion. Mirrors the manual path (04-04).
    """

    def _wait(retry_state) -> float:
        return two_burst_wait(
            retry_state,
            burst_spread_s=burst_spread_s,
            burst_size=attempts_per_burst,
            mid_pause_s=mid_pause_s,
        )

    def _before_sleep(retry_state) -> None:
        # Outcome-only retry log event (NEVER a secret — T-04-01). Built as a
        # closure so the logged burst index honors the CONFIGURED
        # ``attempts_per_burst`` (WR-03), not the module BURST_SIZE constant —
        # burst 1 = attempts 1..n, burst 2 = attempts n+1..2n.
        attempt = retry_state.attempt_number
        _log.info(
            "retry_attempt",
            attempt=attempt,
            burst=1 if attempt <= attempts_per_burst else 2,
        )

    return Retrying(
        wait=_wait,
        stop=stop_after_attempt(2 * attempts_per_burst),
        retry=(
            retry_if_result(lambda r: not getattr(r, "ok", True))
            | retry_if_exception(is_transient)
        ),
        sleep=stop_event.wait,  # interruptible pause (D-07) — NOT a blocking stdlib sleep
        before_sleep=_before_sleep,
        # On exhaustion, return the final outcome's .result(): a non-ok
        # DeliveryResult is returned (→ transient_exhausted), an exhausted
        # exception is re-raised (→ caught by fire_slot's httpx handlers). This
        # avoids a RetryError being mis-classified as internal_error (UAT Test 1).
        retry_error_callback=lambda rs: rs.outcome.result(),
    )
