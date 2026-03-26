"""Circuit breaker and backpressure for downstream dependencies.

Prevents cascade failures when model-serving, Postgres, Redis,
or Ollama are degraded.  Implements the standard circuit breaker
pattern (closed → open → half-open) with configurable thresholds.

Also provides a semaphore-based backpressure mechanism to bound
concurrent downstream calls and shed load when queues grow.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(str, Enum):
    CLOSED = 'closed'          # normal — requests pass through
    OPEN = 'open'              # tripped — all requests fail-fast
    HALF_OPEN = 'half_open'    # probe — one request allowed to test recovery


@dataclass
class CircuitBreakerConfig:
    """Tunable parameters per downstream dependency."""
    failure_threshold: int = 5          # consecutive failures to trip
    recovery_timeout_seconds: float = 30.0   # time before moving to half-open
    half_open_max_calls: int = 1        # probes allowed in half-open state
    success_threshold: int = 2          # consecutive successes to close again


@dataclass
class CircuitBreakerStats:
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = 0.0
    total_failures: int = 0
    total_successes: int = 0
    total_rejections: int = 0


class CircuitBreaker:
    """Per-dependency circuit breaker.

    Usage:
        cb = CircuitBreaker('model-serving', config=CircuitBreakerConfig(failure_threshold=3))
        result = await cb.call(async_fn, arg1, arg2)
    """

    def __init__(self, name: str, *, config: CircuitBreakerConfig | None = None) -> None:
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        return self._stats.state

    @property
    def stats(self) -> CircuitBreakerStats:
        return self._stats

    async def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute fn through the circuit breaker."""
        async with self._lock:
            self._maybe_transition_to_half_open()

            if self._stats.state == CircuitState.OPEN:
                self._stats.total_rejections += 1
                logger.warning(
                    'Circuit breaker OPEN — rejecting call.',
                    extra={'circuit': self.name, 'rejections': self._stats.total_rejections},
                )
                raise CircuitOpenError(
                    f'Circuit breaker [{self.name}] is OPEN. '
                    f'Recovery in {self._time_until_half_open():.1f}s.'
                )

            if self._stats.state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    self._stats.total_rejections += 1
                    raise CircuitOpenError(
                        f'Circuit breaker [{self.name}] is HALF_OPEN — max probes reached.'
                    )
                self._half_open_calls += 1

        # Execute outside the lock to avoid holding it during I/O
        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)
        except Exception as exc:
            await self._on_failure()
            raise
        else:
            await self._on_success()
            return result

    async def _on_success(self) -> None:
        async with self._lock:
            self._stats.total_successes += 1
            self._stats.consecutive_failures = 0
            self._stats.consecutive_successes += 1

            if self._stats.state == CircuitState.HALF_OPEN:
                if self._stats.consecutive_successes >= self.config.success_threshold:
                    self._transition(CircuitState.CLOSED)
                    logger.info('Circuit breaker CLOSED (recovered).', extra={'circuit': self.name})

    async def _on_failure(self) -> None:
        async with self._lock:
            self._stats.total_failures += 1
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._stats.last_failure_time = time.monotonic()

            if self._stats.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
                logger.error('Circuit breaker re-OPENED from half-open.', extra={'circuit': self.name})
            elif self._stats.consecutive_failures >= self.config.failure_threshold:
                self._transition(CircuitState.OPEN)
                logger.error(
                    'Circuit breaker OPENED — failure threshold reached.',
                    extra={'circuit': self.name, 'failures': self._stats.consecutive_failures},
                )

    def _maybe_transition_to_half_open(self) -> None:
        if self._stats.state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._stats.last_failure_time
        if elapsed >= self.config.recovery_timeout_seconds:
            self._transition(CircuitState.HALF_OPEN)
            self._half_open_calls = 0
            logger.info(
                'Circuit breaker HALF_OPEN — allowing probes.',
                extra={'circuit': self.name, 'elapsed': round(elapsed, 1)},
            )

    def _transition(self, new_state: CircuitState) -> None:
        self._stats.state = new_state
        self._stats.last_state_change = time.monotonic()
        if new_state == CircuitState.CLOSED:
            self._stats.consecutive_failures = 0
            self._stats.consecutive_successes = 0

    def _time_until_half_open(self) -> float:
        elapsed = time.monotonic() - self._stats.last_failure_time
        remaining = self.config.recovery_timeout_seconds - elapsed
        return max(0.0, remaining)


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open and rejecting calls."""
    pass


# ---------------------------------------------------------------------------
# Backpressure / concurrency limiter
# ---------------------------------------------------------------------------

class BackpressureLimiter:
    """Semaphore-based concurrency limiter for downstream calls.

    Prevents unbounded fan-out when upstream suddenly spikes.
    When max concurrent calls are in-flight, new callers wait up
    to `timeout_seconds` before receiving a 503 / backpressure signal.
    """

    def __init__(
        self,
        name: str,
        *,
        max_concurrent: int = 50,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.name = name
        self.max_concurrent = max(1, max_concurrent)
        self.timeout_seconds = max(0.1, timeout_seconds)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._waiting = 0
        self._in_flight = 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def waiting(self) -> int:
        return self._waiting

    async def acquire(self) -> None:
        self._waiting += 1
        try:
            acquired = await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._waiting -= 1
            logger.warning(
                'Backpressure — timeout waiting for slot.',
                extra={'limiter': self.name, 'in_flight': self._in_flight, 'waiting': self._waiting},
            )
            raise BackpressureError(
                f'Backpressure limiter [{self.name}]: {self._in_flight} calls in-flight, '
                f'timed out after {self.timeout_seconds}s.'
            )
        self._waiting -= 1
        self._in_flight += 1

    def release(self) -> None:
        self._in_flight = max(0, self._in_flight - 1)
        self._semaphore.release()

    async def __aenter__(self) -> 'BackpressureLimiter':
        await self.acquire()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.release()


class BackpressureError(Exception):
    """Raised when backpressure rejects a call due to capacity."""
    pass
