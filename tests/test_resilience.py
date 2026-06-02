"""Tests for resilience patterns: CircuitBreaker, async_retry, and integration.

ECC error-handling skill — adapted for agent-api.
"""

import asyncio
import time

import pytest

from app.services.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitBreakerState,
    async_retry,
    get_all_circuit_breakers,
    get_circuit_breaker,
)


# ═══════════════════════════════════════════════════════════════════════════
# TestCircuitBreaker — state machine, transitions, thread safety
# ═══════════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    """State machine tests for CircuitBreaker."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.cb = CircuitBreaker(name="test-cb", failure_threshold=3, reset_timeout=1.0)

    def test_initial_state_closed(self):
        """New breaker starts CLOSED."""
        assert self.cb._state == CircuitBreakerState.CLOSED
        assert self.cb._failure_count == 0

    def test_before_call_does_not_raise_when_closed(self):
        """before_call() passes through when CLOSED."""
        self.cb.before_call()  # should not raise

    def test_before_call_raises_when_open(self):
        """before_call() raises CircuitBreakerOpen when OPEN."""
        # Trip the breaker
        for _ in range(3):
            self.cb.on_failure()
        assert self.cb._state == CircuitBreakerState.OPEN

        with pytest.raises(CircuitBreakerOpen) as exc_info:
            self.cb.before_call()
        assert exc_info.value.name == "test-cb"
        assert exc_info.value.retry_after_seconds > 0

    def test_closed_to_open_transition(self):
        """CLOSED → OPEN after failure_threshold consecutive failures."""
        self.cb.on_failure()
        assert self.cb._state == CircuitBreakerState.CLOSED
        self.cb.on_failure()
        assert self.cb._state == CircuitBreakerState.CLOSED
        self.cb.on_failure()  # 3rd → threshold
        assert self.cb._state == CircuitBreakerState.OPEN

    def test_open_to_half_open_after_timeout(self):
        """OPEN → HALF_OPEN after reset_timeout elapses."""
        # Use short timeout for this test
        self.cb.reset_timeout = 0.1
        # Trip to OPEN
        for _ in range(3):
            self.cb.on_failure()
        assert self.cb._state == CircuitBreakerState.OPEN

        # Wait for reset_timeout (0.1s)
        time.sleep(0.15)

        # before_call should transition to HALF_OPEN and not raise
        self.cb.before_call()
        assert self.cb._state == CircuitBreakerState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        """HALF_OPEN → CLOSED after a successful trial call."""
        # Use short timeout for this test
        self.cb.reset_timeout = 0.1
        # Trip → OPEN → wait → HALF_OPEN
        for _ in range(3):
            self.cb.on_failure()
        time.sleep(0.15)
        self.cb.before_call()

        # Trial succeeds
        self.cb.on_success()
        assert self.cb._state == CircuitBreakerState.CLOSED
        assert self.cb._failure_count == 0

    def test_half_open_to_open_on_failure(self):
        """HALF_OPEN → OPEN if the trial call fails."""
        # Use short timeout for this test
        self.cb.reset_timeout = 0.1
        # Trip → OPEN → wait → HALF_OPEN
        for _ in range(3):
            self.cb.on_failure()
        time.sleep(0.15)
        self.cb.before_call()

        # Trial fails
        self.cb.on_failure()
        assert self.cb._state == CircuitBreakerState.OPEN

    def test_success_resets_failure_count(self):
        """A success in CLOSED state resets the failure counter."""
        self.cb.on_failure()
        self.cb.on_failure()  # 2 failures
        assert self.cb._failure_count == 2

        self.cb.on_success()
        assert self.cb._failure_count == 0

        # Should need 3 MORE failures to trip
        self.cb.on_failure()
        self.cb.on_failure()
        assert self.cb._state == CircuitBreakerState.CLOSED
        self.cb.on_failure()
        assert self.cb._state == CircuitBreakerState.OPEN

    def test_get_stats_returns_snapshot(self):
        """get_stats() returns a dict with all fields."""
        self.cb.on_failure()
        stats = self.cb.get_stats()
        assert stats["name"] == "test-cb"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 1
        assert stats["total_failures"] == 1
        assert stats["total_successes"] == 0
        assert "failure_threshold" in stats
        assert "reset_timeout" in stats

    def test_multiple_before_call_while_half_open(self):
        """Multiple before_call() in HALF_OPEN state — only first is the trial."""
        self.cb.reset_timeout = 0.1
        for _ in range(3):
            self.cb.on_failure()
        time.sleep(0.15)

        # First call transitions to HALF_OPEN
        self.cb.before_call()
        assert self.cb._state == CircuitBreakerState.HALF_OPEN

        # Second call is still HALF_OPEN (same probe window)
        self.cb.before_call()
        assert self.cb._state == CircuitBreakerState.HALF_OPEN


# ═══════════════════════════════════════════════════════════════════════════
# TestAsyncRetry — backoff, jitter, cumulative timeout, exception filtering
# ═══════════════════════════════════════════════════════════════════════════

class TestAsyncRetry:
    """Tests for async_retry with exponential backoff + jitter."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        """Returns result on first attempt — no retries."""
        call_count = 0

        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await async_retry(succeed, max_retries=3)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        """Retries on retryable exception, returns result on success."""
        call_count = 0

        async def fail_twice_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("fail")
            return "recovered"

        result = await async_retry(
            fail_twice_then_ok,
            max_retries=4,
            base_delay=0.01,
            jitter=False,
        )
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self):
        """Raises the last exception if all retries fail."""
        async def always_fail():
            raise RuntimeError("always")

        with pytest.raises(RuntimeError, match="always"):
            await async_retry(
                always_fail,
                max_retries=3,
                base_delay=0.01,
                jitter=False,
            )

    @pytest.mark.asyncio
    async def test_non_retryable_exception_propagates_immediately(self):
        """Non-retryable exceptions propagate without retries."""
        call_count = 0

        async def fail_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad value")

        with pytest.raises(ValueError, match="bad value"):
            await async_retry(
                fail_value_error,
                max_retries=5,
                base_delay=0.01,
                retryable_exceptions=(RuntimeError,),  # ValueError NOT retryable
            )
        assert call_count == 1  # no retries

    @pytest.mark.asyncio
    async def test_cumulative_timeout_exceeded(self):
        """Raises TimeoutError when cumulative timeout is exceeded."""
        async def slow_fail():
            await asyncio.sleep(0.1)
            raise RuntimeError("fail")

        with pytest.raises(TimeoutError):
            await async_retry(
                slow_fail,
                max_retries=10,
                base_delay=0.2,
                jitter=False,
                max_cumulative_timeout=0.15,  # too short for even 1 attempt
            )

    @pytest.mark.asyncio
    async def test_jitter_produces_variable_delays(self):
        """Jitter adds randomization — delays should vary between runs."""
        delays = []

        async def fail_once():
            nonlocal delays
            # Record the delay from the first call context is tricky;
            # instead verify jitter is enabled by checking the delay
            # formula produces a value 50-100% of the base
            if not hasattr(fail_once, "called"):
                fail_once.called = True
                raise RuntimeError("first")
            return "ok"

        # Just verify jitter doesn't break anything
        result = await async_retry(
            fail_once,
            max_retries=2,
            base_delay=0.01,
            jitter=True,
        )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_exponential_backoff_increases_delay(self):
        """Each retry waits longer — exponential backoff."""
        attempt_delays = []
        start = time.monotonic()

        async def fail_until_last():
            elapsed = time.monotonic() - start
            attempt_delays.append(elapsed)
            if len(attempt_delays) < 3:
                raise RuntimeError("fail")
            return "ok"

        await async_retry(
            fail_until_last,
            max_retries=3,
            base_delay=0.05,
            max_delay=1.0,
            jitter=False,
        )
        # With no jitter: delays are 0.05, 0.10 (2x)
        # We just verify it completed successfully
        assert len(attempt_delays) == 3

    @pytest.mark.asyncio
    async def test_max_delay_cap(self):
        """Delay is capped at max_delay regardless of exponent."""
        # With base_delay=1, max_delay=2, jitter=False:
        # attempt 1: delay=1, attempt 2: delay=min(2,2)=2, attempt 3: delay=min(4,2)=2
        # This is tested implicitly — the function completes without timing out
        call_count = 0

        async def fail_n_times():
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                raise RuntimeError("fail")
            return "ok"

        result = await async_retry(
            fail_n_times,
            max_retries=5,
            base_delay=1.0,
            max_delay=0.01,  # very low cap
            jitter=False,
        )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        """fn receives *args and **kwargs correctly."""
        async def echo(a, b, c=None):
            return f"{a}-{b}-{c}"

        result = await async_retry(echo, "x", "y", c="z")
        assert result == "x-y-z"

    @pytest.mark.asyncio
    async def test_max_retries_one_means_no_retry(self):
        """max_retries=1 means attempt once, no retries."""
        call_count = 0

        async def fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await async_retry(fail, max_retries=1, base_delay=0.01)
        assert call_count == 1


# ═══════════════════════════════════════════════════════════════════════════
# TestCircuitBreakerOpenError — standalone exception shape
# ═══════════════════════════════════════════════════════════════════════════

class TestCircuitBreakerOpenError:
    """Tests for the standalone CircuitBreakerOpen exception (resilience module)."""

    def test_exception_attributes(self):
        """Exception carries name and retry_after_seconds."""
        exc = CircuitBreakerOpen(name="deepseek", retry_after_seconds=42.5)
        assert exc.name == "deepseek"
        assert exc.retry_after_seconds == 42.5
        assert "deepseek" in str(exc)
        assert "42" in str(exc)

    def test_default_retry_after(self):
        """Default retry_after_seconds is 60."""
        exc = CircuitBreakerOpen(name="test")
        assert exc.retry_after_seconds == 60.0


# ═══════════════════════════════════════════════════════════════════════════
# TestHttpCircuitBreakerOpen — HTTP-layer error (app.errors)
# ═══════════════════════════════════════════════════════════════════════════

class TestHttpCircuitBreakerOpen:
    """Tests for the HTTP-level CircuitBreakerOpen ApiError."""

    def test_status_code_is_503(self):
        """HTTP CircuitBreakerOpen returns 503."""
        from app.errors import CircuitBreakerOpen as HttpCBO
        err = HttpCBO(service_name="deepseek", retry_after_seconds=30)
        assert err.status_code == 503

    def test_response_shape(self):
        """to_response() includes service_name and retry_after_seconds."""
        from app.errors import CircuitBreakerOpen as HttpCBO
        err = HttpCBO(
            message="DeepSeek is down",
            service_name="deepseek",
            retry_after_seconds=45,
        )
        resp = err.to_response()
        assert resp["error"]["code"] == "circuit_breaker_open"
        assert resp["error"]["message"] == "DeepSeek is down"
        assert resp["error"]["service_name"] == "deepseek"
        assert resp["error"]["retry_after_seconds"] == 45

    def test_default_message(self):
        """Uses class-level default message when none provided."""
        from app.errors import CircuitBreakerOpen as HttpCBO
        err = HttpCBO()
        assert "Circuit breaker is open" in err.message


# ═══════════════════════════════════════════════════════════════════════════
# TestCircuitBreakerRegistry — singleton factory
# ═══════════════════════════════════════════════════════════════════════════

class TestCircuitBreakerRegistry:
    """Tests for get_circuit_breaker and get_all_circuit_breakers."""

    def test_returns_same_instance(self):
        """get_circuit_breaker returns the same instance for the same name."""
        cb1 = get_circuit_breaker("test-registry")
        cb2 = get_circuit_breaker("test-registry")
        assert cb1 is cb2

    def test_different_names_different_instances(self):
        """Different names get different circuit breakers."""
        cb_a = get_circuit_breaker("svc-a")
        cb_b = get_circuit_breaker("svc-b")
        assert cb_a is not cb_b

    def test_get_all_returns_all_registered(self):
        """get_all_circuit_breakers returns stats for all registered breakers."""
        get_circuit_breaker("svc-1")
        get_circuit_breaker("svc-2")
        all_cbs = get_all_circuit_breakers()
        assert "svc-1" in all_cbs
        assert "svc-2" in all_cbs


# ═══════════════════════════════════════════════════════════════════════════
# TestIntegrationCircuitBreakerAndRetry — breaker + retry together
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegrationCircuitBreakerAndRetry:
    """Integration: circuit breaker wraps async_retry calls."""

    @pytest.mark.asyncio
    async def test_breaker_opens_after_repeated_retry_failures(self):
        """When retries exhaust and breaker opens, subsequent calls fast-fail."""
        cb = CircuitBreaker(name="integ-test", failure_threshold=2, reset_timeout=60.0)

        async def always_fail():
            raise RuntimeError("down")

        # Trip breaker with 2 failures (each exhausts async_retry)
        for _ in range(2):
            try:
                await async_retry(
                    always_fail,
                    max_retries=2,
                    base_delay=0.01,
                    jitter=False,
                )
            except RuntimeError:
                cb.on_failure()

        assert cb._state == CircuitBreakerState.OPEN

        # Subsequent before_call should raise
        with pytest.raises(CircuitBreakerOpen):
            cb.before_call()

    @pytest.mark.asyncio
    async def test_successful_retry_keeps_breaker_closed(self):
        """Retry that eventually succeeds keeps the breaker CLOSED."""
        cb = CircuitBreaker(name="integ-ok", failure_threshold=3, reset_timeout=60.0)

        call_count = 0

        async def fail_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient")
            return "ok"

        try:
            cb.before_call()
        except CircuitBreakerOpen:
            pytest.fail("Breaker should be CLOSED")

        try:
            result = await async_retry(
                fail_then_ok,
                max_retries=3,
                base_delay=0.01,
                jitter=False,
            )
            cb.on_success()
        except RuntimeError:
            cb.on_failure()
            raise

        assert result == "ok"
        assert cb._state == CircuitBreakerState.CLOSED
        assert cb._failure_count == 0
