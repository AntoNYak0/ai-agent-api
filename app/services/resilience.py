"""Resilience patterns for external service calls.

ECC error-handling skill adapted for agent-api:
  - CircuitBreaker: three-state (CLOSED/OPEN/HALF_OPEN), fast-fail when open
  - async_retry: exponential backoff with jitter, configurable retryable exceptions
  - Per-service circuit breakers via name-based registry

Usage:
    from app.services.resilience import get_circuit_breaker, async_retry

    cb = get_circuit_breaker("deepseek")
    cb.before_call()              # raises CircuitBreakerOpen if OPEN
    try:
        result = await async_retry(my_callable, max_retries=3, ...)
        cb.on_success()
    except Exception:
        cb.on_failure()
        raise
"""

import asyncio
import enum
import logging
import random
import threading
import time
from collections.abc import Callable, Awaitable
from typing import TypeVar, ParamSpec

logger = logging.getLogger("resilience")

P = ParamSpec("P")
T = TypeVar("T")

# ── Circuit breaker registry (module-level, thread-safe) ──────────────

_circuit_breakers: dict[str, "CircuitBreaker"] = {}
_breaker_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════

class CircuitBreakerState(enum.Enum):
    """Three states of the circuit breaker pattern."""
    CLOSED = "closed"        # Normal operation — calls pass through
    OPEN = "open"            # Failing — calls are rejected immediately
    HALF_OPEN = "half_open"  # Probing — one trial call allowed through


class CircuitBreakerOpen(Exception):
    """Raised by CircuitBreaker.before_call() when the breaker is OPEN.

    This is a standalone exception (NOT an ApiError subclass) so the
    resilience module stays decoupled from FastAPI. Route handlers
    should catch this and convert to the HTTP-level CircuitBreakerOpen
    from app.errors.
    """

    def __init__(self, name: str, retry_after_seconds: float = 60.0):
        self.name = name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Circuit breaker '{name}' is OPEN — retry in {retry_after_seconds:.0f}s")


class CircuitBreaker:
    """Thread-safe circuit breaker for a named external service.

    State machine:
        CLOSED ──(failures >= threshold)──▶ OPEN
        OPEN   ──(timeout elapsed)────────▶ HALF_OPEN
        HALF_OPEN ──(success)─────────────▶ CLOSED
        HALF_OPEN ──(failure)─────────────▶ OPEN

    Thread safety: uses threading.Lock (no await inside critical sections).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout

        self._lock = threading.Lock()
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._last_success_time = 0.0
        self._total_failures = 0
        self._total_successes = 0

    # ── Public API ──────────────────────────────────────────────────

    def before_call(self) -> None:
        """Check if a call can be made. Raises CircuitBreakerOpen if OPEN."""
        with self._lock:
            if self._state is CircuitBreakerState.CLOSED:
                return

            if self._state is CircuitBreakerState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.reset_timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    logger.info(
                        "Circuit breaker '%s': OPEN -> HALF_OPEN (%.1fs elapsed ≥ %.1fs timeout)",
                        self.name, elapsed, self.reset_timeout,
                    )
                    return
                else:
                    remaining = self.reset_timeout - elapsed
                    raise CircuitBreakerOpen(self.name, retry_after_seconds=remaining)

            # HALF_OPEN — allow the trial call through
            if self._state is CircuitBreakerState.HALF_OPEN:
                return

    def on_success(self) -> None:
        """Report a successful call."""
        with self._lock:
            self._total_successes += 1
            self._last_success_time = time.monotonic()

            if self._state is CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker '%s': HALF_OPEN -> CLOSED (trial succeeded)", self.name)
            elif self._state is CircuitBreakerState.CLOSED:
                # Reset failure window on any success
                self._failure_count = 0

    def on_failure(self) -> None:
        """Report a failed call."""
        with self._lock:
            self._total_failures += 1
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state is CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.OPEN
                logger.warning(
                    "Circuit breaker '%s': HALF_OPEN -> OPEN (trial failed)",
                    self.name,
                )
            elif (
                self._state is CircuitBreakerState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitBreakerState.OPEN
                logger.warning(
                    "Circuit breaker '%s': CLOSED -> OPEN (%d failures ≥ %d threshold)",
                    self.name, self._failure_count, self.failure_threshold,
                )

    def get_stats(self) -> dict:
        """Return a snapshot of breaker state for monitoring."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "failure_threshold": self.failure_threshold,
            "reset_timeout": self.reset_timeout,
        }


# ── Registry helpers ──────────────────────────────────────────────────

def get_circuit_breaker(name: str) -> CircuitBreaker:
    """Get or create a named circuit breaker. Thread-safe singleton."""
    with _breaker_lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker(name=name)
        return _circuit_breakers[name]


def get_all_circuit_breakers() -> dict[str, dict]:
    """Return stats for all registered circuit breakers (for health dashboard)."""
    with _breaker_lock:
        return {name: cb.get_stats() for name, cb in _circuit_breakers.items()}


# ═══════════════════════════════════════════════════════════════════════
# Async Retry with Exponential Backoff + Jitter
# ═══════════════════════════════════════════════════════════════════════

async def async_retry(
    fn: Callable[P, Awaitable[T]],
    *args: P.args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    max_cumulative_timeout: float = 0.0,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
    **kwargs: P.kwargs,
) -> T:
    """Call an async function with exponential backoff and optional jitter.

    Args:
        fn: Async callable to retry.
        *args, **kwargs: Passed through to fn.
        max_retries: Maximum number of attempts (1 = try once, no retries).
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay cap in seconds.
        jitter: If True, add ±50% random variation to delay (prevents thundering herd).
        max_cumulative_timeout: If > 0, total time across all attempts. Raises TimeoutError.
        retryable_exceptions: Tuple of exception types that trigger a retry.
            Non-retryable exceptions propagate immediately.

    Returns:
        The result of fn(*args, **kwargs).

    Raises:
        The last exception from fn if all retries are exhausted.
        TimeoutError if max_cumulative_timeout is exceeded.
        Any non-retryable exception from fn immediately.
    """
    start_time = time.monotonic()
    last_exception: BaseException | None = None

    for attempt in range(max_retries):
        # Check cumulative timeout before each attempt
        if max_cumulative_timeout > 0:
            elapsed = time.monotonic() - start_time
            if elapsed >= max_cumulative_timeout:
                raise TimeoutError(
                    f"Cumulative retry timeout exceeded: {elapsed:.1f}s > {max_cumulative_timeout:.1f}s"
                )

        try:
            return await fn(*args, **kwargs)
        except retryable_exceptions as e:
            last_exception = e

            if attempt >= max_retries - 1:
                # All retries exhausted
                logger.error(
                    "async_retry: all %d attempts failed. Last error: %s",
                    max_retries, e,
                )
                raise

            # Calculate delay with exponential backoff
            delay = min(base_delay * (2 ** attempt), max_delay)

            # Add jitter: 50%–100% of computed delay
            if jitter:
                delay = delay * (0.5 + random.random() * 0.5)

            logger.warning(
                "async_retry: attempt %d/%d failed (%s). Retrying in %.1fs...",
                attempt + 1, max_retries, e, delay,
            )

            await asyncio.sleep(delay)

    # Should be unreachable, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("async_retry: unexpected — all retries exhausted with no exception")
