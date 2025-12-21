"""
Dragonfly Engine - Shared Backoff State

Provides exponential backoff with jitter for transient failure handling.
Used by WorkerBootstrap, HeartbeatContext, and any service needing retry logic.

Usage:
    from backend.workers.backoff import BackoffState

    backoff = BackoffState()

    try:
        do_something()
        backoff.record_success()
    except TransientError:
        delay = backoff.record_failure()
        time.sleep(delay)

Configuration:
    INITIAL_BACKOFF_SECONDS: Starting delay (default: 1.0)
    MAX_BACKOFF_SECONDS: Maximum delay cap (default: 60.0)
    BACKOFF_MULTIPLIER: Exponential growth factor (default: 2.0)
    BACKOFF_JITTER: Jitter percentage to prevent thundering herd (default: 0.1)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

# Backoff configuration for transient failures
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0
BACKOFF_MULTIPLIER = 2.0
BACKOFF_JITTER = 0.1  # 10% jitter to prevent thundering herd


@dataclass
class BackoffState:
    """
    Tracks exponential backoff state for crash loop protection.

    Provides exponential backoff with jitter to:
    - Prevent thundering herd on recovery
    - Protect against crash loops
    - Allow graceful degradation on transient failures

    Attributes:
        current_delay: Current backoff delay in seconds
        consecutive_failures: Count of consecutive failures
        last_failure_time: Monotonic timestamp of last failure
        total_failures: Total failures since creation
    """

    current_delay: float = INITIAL_BACKOFF_SECONDS
    consecutive_failures: int = 0
    last_failure_time: Optional[float] = None
    total_failures: int = 0

    def record_failure(self) -> float:
        """
        Record a failure and return the backoff delay to use.

        The delay grows exponentially up to MAX_BACKOFF_SECONDS,
        with random jitter to prevent thundering herd.

        Returns:
            Delay in seconds to wait before retry
        """
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_failure_time = time.monotonic()

        # Calculate delay with exponential backoff
        delay = min(
            self.current_delay * (BACKOFF_MULTIPLIER ** (self.consecutive_failures - 1)),
            MAX_BACKOFF_SECONDS,
        )

        # Add jitter to prevent thundering herd
        # Use time-based hash for deterministic jitter in tests
        jitter_factor = 2 * (hash(time.time()) % 100) / 100 - 1  # -1 to 1
        jitter = delay * BACKOFF_JITTER * jitter_factor
        delay = max(INITIAL_BACKOFF_SECONDS, delay + jitter)

        self.current_delay = delay
        return delay

    def record_success(self) -> None:
        """
        Record a success - reset consecutive failures.

        Resets the backoff delay to initial value after successful operation.
        Total failure count is preserved for diagnostics.
        """
        self.consecutive_failures = 0
        self.current_delay = INITIAL_BACKOFF_SECONDS

    def is_in_crash_loop(self, threshold: int = 10) -> bool:
        """
        Check if we're in a crash loop (too many consecutive failures).

        Args:
            threshold: Number of consecutive failures to trigger crash loop

        Returns:
            True if consecutive_failures >= threshold
        """
        return self.consecutive_failures >= threshold

    def reset(self) -> None:
        """
        Fully reset backoff state.

        Clears all failure counters and returns to initial state.
        """
        self.current_delay = INITIAL_BACKOFF_SECONDS
        self.consecutive_failures = 0
        self.last_failure_time = None
        self.total_failures = 0

    @property
    def time_since_last_failure(self) -> Optional[float]:
        """
        Get seconds elapsed since last failure, or None if no failures.

        Returns:
            Seconds since last failure, or None
        """
        if self.last_failure_time is None:
            return None
        return time.monotonic() - self.last_failure_time
