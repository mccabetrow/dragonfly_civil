"""
Dragonfly Engine - Database Readiness State

Provides global database readiness state tracking for degraded-mode operations.
This module enables the API to start and serve /health even when DB is unavailable.

Key design principles:
- API must never crash-loop due to DB unavailability
- /health always returns 200 (process alive)
- /readyz returns 503 with metadata when DB not ready
- Background supervisor attempts reconnection with polite backoff

Usage:
    from backend.core.db_state import db_state, ProcessRole

    # Check if DB is ready
    if db_state.ready:
        # DB operations safe
        ...

    # Get operator status line
    print(db_state.operator_status())
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ProcessRole(Enum):
    """Process execution role for DB failure handling policy.

    API: Never fatal on DB connect failure - supports degraded mode
    WORKER: May exit on auth failure to prevent lockout amplification
    """

    API = "api"
    WORKER = "worker"


def detect_process_role() -> ProcessRole:
    """Detect process role from environment or entrypoint heuristics.

    Priority:
    1. PROCESS_ROLE env var (explicit)
    2. WORKER_MODE env var (legacy compat)
    3. Entrypoint heuristics (script name patterns)
    """
    # Explicit env var
    role_env = os.getenv("PROCESS_ROLE", "").lower().strip()
    if role_env == "api":
        return ProcessRole.API
    if role_env == "worker":
        return ProcessRole.WORKER

    # Legacy worker mode detection
    if os.getenv("WORKER_MODE", "").lower() in ("1", "true", "yes"):
        return ProcessRole.WORKER

    # Entrypoint heuristics
    script = sys.argv[0] if sys.argv else ""
    worker_patterns = (
        "worker",
        "celery",
        "rq",
        "dramatiq",
        "ingest",
        "watcher",
        "scheduler",
        "sentinel",
        "orchestrator",
    )
    if any(p in script.lower() for p in worker_patterns):
        return ProcessRole.WORKER

    # Default to API (safest - no crash-loops)
    return ProcessRole.API


# ═══════════════════════════════════════════════════════════════════════════
# BACKOFF CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Normal transient failures: quick exponential backoff
NORMAL_BASE_DELAY_S = 2.0
NORMAL_MAX_DELAY_S = 60.0
NORMAL_JITTER_FACTOR = 0.2

# Auth failures: POLITE backoff (15-30 min) to avoid lockout spiral
AUTH_FAILURE_MIN_DELAY_S = 15 * 60  # 15 minutes
AUTH_FAILURE_MAX_DELAY_S = 30 * 60  # 30 minutes

# ═══════════════════════════════════════════════════════════════════════════
# LOCKOUT CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════════════════
# When Supabase pooler returns server_login_retry or query_wait_timeout, it
# indicates we're in a lockout spiral. Workers must exit immediately;
# API must enter degraded mode with a 15-minute minimum backoff.

LOCKOUT_BACKOFF_MIN_S = 900  # 15 minutes - pooler lockout recovery window
LOCKOUT_BACKOFF_MAX_S = 1200  # 20 minutes - upper bound with jitter
LOCKOUT_JITTER_FACTOR = 0.1  # ±10% jitter

# Exit code for lockout kill-switch (EX_CONFIG from sysexits.h)
# Using 78 to distinguish from generic exit(1)
EXIT_CODE_AUTH_LOCKOUT = 78

# Lockout error patterns - these indicate pooler is actively rejecting us
LOCKOUT_ERROR_PATTERNS = frozenset(
    [
        "server_login_retry",  # Supabase pooler: repeated bad auth
        "query_wait_timeout",  # Connection pool exhaustion
    ]
)


# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL CONNECTIVITY FLAG (for Indestructible Boot)
# ═══════════════════════════════════════════════════════════════════════════
# This flag is set by db.py when connection fails. Health endpoints check it.
# Import via: from backend.core.db_state import is_db_connected
is_db_connected: bool = False


@dataclass
class DBReadinessState:
    """Global database readiness state for degraded-mode operations.

    Thread-safe state tracking for:
    - Current readiness (ready: bool)
    - Last error information
    - Retry timing and backoff
    - Init statistics
    """

    # Core state
    ready: bool = False
    healthy: bool = False
    initialized: bool = False

    # Error tracking
    last_error: Optional[str] = None
    last_error_class: Optional[str] = None  # "auth_failure", "network", "other"
    last_attempt_ts: Optional[float] = None  # time.monotonic()
    next_retry_ts: Optional[float] = None  # time.monotonic()

    # Statistics
    init_attempts: int = 0
    consecutive_failures: int = 0
    init_duration_ms: Optional[float] = None

    # Supervisor state
    supervisor_running: bool = False

    # Process role
    process_role: ProcessRole = field(default_factory=detect_process_role)

    def mark_connected(self, init_duration_ms: float) -> None:
        """Mark database as ready after successful connection."""
        self.ready = True
        self.healthy = True
        self.initialized = True
        self.last_error = None
        self.last_error_class = None
        self.consecutive_failures = 0
        self.init_duration_ms = init_duration_ms
        self.last_attempt_ts = time.monotonic()
        self.next_retry_ts = None  # No retry needed

        logger.info(
            "[DB] READY=true",
            extra={
                "db_ready": True,
                "init_duration_ms": round(init_duration_ms),
                "init_attempts": self.init_attempts,
            },
        )

    def mark_failed(
        self,
        error: str,
        error_class: str,
        next_retry_delay_s: float,
    ) -> None:
        """Mark database connection attempt as failed."""
        self.ready = False
        self.healthy = False
        self.last_error = error[:500]  # Truncate for safety
        self.last_error_class = error_class
        self.consecutive_failures += 1
        self.last_attempt_ts = time.monotonic()
        self.next_retry_ts = time.monotonic() + next_retry_delay_s

        logger.warning(
            f"[DB] READY=false reason={error_class} next_retry_in={int(next_retry_delay_s)}s",
            extra={
                "db_ready": False,
                "error_class": error_class,
                "error_msg": error[:200],
                "consecutive_failures": self.consecutive_failures,
                "next_retry_s": int(next_retry_delay_s),
            },
        )

    def mark_no_config(self) -> None:
        """Mark database as unconfigured (no DSN provided)."""
        self.ready = False
        self.healthy = False
        self.initialized = False
        self.last_error = "SUPABASE_DB_URL not configured"
        self.last_error_class = "no_config"
        self.next_retry_ts = None

        logger.warning(
            "[DB] READY=false reason=no_config",
            extra={"db_ready": False, "error_class": "no_config"},
        )

    def next_retry_in_seconds(self) -> Optional[int]:
        """Return seconds until next retry, or None if not scheduled."""
        if self.next_retry_ts is None:
            return None
        remaining = self.next_retry_ts - time.monotonic()
        return max(0, int(remaining))

    def operator_status(self) -> str:
        """Return single-line operator status for logging/observability."""
        if self.ready:
            return "[DB] READY=true"

        reason = self.last_error_class or "unknown"
        retry_in = self.next_retry_in_seconds()
        if retry_in is not None:
            return f"[DB] READY=false reason={reason} next_retry_in={retry_in}s"
        return f"[DB] READY=false reason={reason}"

    def readiness_metadata(self) -> dict:
        """Return metadata for /readyz responses."""
        return {
            "ready": self.ready,
            "initialized": self.initialized,
            "last_error": self.last_error,
            "last_error_class": self.last_error_class,
            "consecutive_failures": self.consecutive_failures,
            "next_retry_in_seconds": self.next_retry_in_seconds(),
            "init_attempts": self.init_attempts,
        }

    def should_exit_on_auth_failure(self) -> bool:
        """Return True if process should exit on auth failure.

        Workers exit immediately to prevent lockout amplification.
        API stays alive in degraded mode.
        """
        return self.process_role == ProcessRole.WORKER


def calculate_backoff_delay(
    consecutive_failures: int,
    error_class: str,
) -> float:
    """Calculate next retry delay with exponential backoff and jitter.

    Lockout errors use 15-20 min backoff to respect pooler recovery.
    Auth failures use POLITE backoff (15-30 min) to avoid Supabase lockouts.
    Network/other failures use quick exponential backoff.
    """
    if error_class == "lockout":
        # Lockout circuit breaker: 15-20 min to let pooler recover
        delay = random.uniform(LOCKOUT_BACKOFF_MIN_S, LOCKOUT_BACKOFF_MAX_S)
        jitter = delay * LOCKOUT_JITTER_FACTOR * random.uniform(-1, 1)
        delay = delay + jitter
        logger.info(
            f"[DB] Lockout detected - circuit breaker: {int(delay)}s "
            f"({int(delay/60)}m) to allow pooler recovery"
        )
        return delay

    if error_class == "auth_failure":
        # Polite backoff for auth failures: 15-30 minutes
        # Random within range to prevent synchronized retries
        delay = random.uniform(AUTH_FAILURE_MIN_DELAY_S, AUTH_FAILURE_MAX_DELAY_S)
        logger.info(
            f"[DB] Auth failure detected - polite backoff: {int(delay)}s "
            f"({int(delay/60)}m) to avoid lockout spiral"
        )
        return delay

    # Exponential backoff: 2s -> 4s -> 8s -> 16s -> 32s -> 60s (capped)
    base_delay = NORMAL_BASE_DELAY_S * (2 ** min(consecutive_failures, 5))
    delay = min(base_delay, NORMAL_MAX_DELAY_S)

    # Add jitter
    jitter = random.uniform(-delay * NORMAL_JITTER_FACTOR, delay * NORMAL_JITTER_FACTOR)
    return max(1.0, delay + jitter)


# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND DB SUPERVISOR
# ═══════════════════════════════════════════════════════════════════════════


class DBSupervisor:
    """Background supervisor for database reconnection attempts.

    Runs in API processes to attempt DB reconnection with polite backoff.
    Respects auth failure lockout avoidance timing.

    CRITICAL: This supervisor MUST honor the backoff window set by mark_failed().
    During lockout (error_class="lockout"), next_retry_ts is 15-20 minutes in future.
    The supervisor MUST wait until that time - zero login attempts before then.
    """

    # Minimum seconds remaining before we allow a retry (safety margin)
    RETRY_SAFETY_MARGIN_S = 5

    def __init__(
        self,
        state: DBReadinessState,
        connect_fn: Callable[[], asyncio.coroutine],
    ) -> None:
        self.state = state
        self.connect_fn = connect_fn
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

    async def start(self) -> None:
        """Start the background supervisor task."""
        if self.state.supervisor_running:
            logger.debug("[DB Supervisor] Already running")
            return

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run())
        self.state.supervisor_running = True
        logger.info("[DB Supervisor] Started background reconnection supervisor")

    async def stop(self) -> None:
        """Stop the background supervisor task."""
        if not self.state.supervisor_running:
            return

        if self._stop_event:
            self._stop_event.set()

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self.state.supervisor_running = False
        logger.info("[DB Supervisor] Stopped")

    def _can_retry_now(self) -> bool:
        """Check if we can attempt a retry RIGHT NOW.

        Returns True only if:
        1. next_retry_ts is None (never failed), OR
        2. Current time >= next_retry_ts (backoff expired)

        CRITICAL: During lockout, this returns False for 15-20 minutes.
        """
        if self.state.next_retry_ts is None:
            return True
        remaining = self.state.next_retry_ts - time.monotonic()
        # Only allow retry if past the backoff window (with small margin for clock drift)
        return remaining <= self.RETRY_SAFETY_MARGIN_S

    async def _run(self) -> None:
        """Main supervisor loop - attempts reconnection with backoff.

        LOCKOUT ENFORCEMENT:
        - When error_class is "lockout", next_retry_ts is 15-20 min in future
        - This loop MUST NOT attempt any DB connection before that time
        - We log the wait time so operators know the supervisor is honoring backoff
        """
        while not self._stop_event.is_set():
            # If already connected, check periodically
            if self.state.ready:
                await asyncio.sleep(60)  # Health check interval
                continue

            # CRITICAL: Check if we're allowed to retry yet
            retry_in = self.state.next_retry_in_seconds()
            if retry_in is not None and retry_in > self.RETRY_SAFETY_MARGIN_S:
                # Log if this is a lockout situation (long wait)
                if retry_in > 120:  # > 2 minutes suggests lockout
                    logger.info(
                        f"[DB Supervisor] Lockout backoff: {retry_in}s ({retry_in // 60}m) remaining. "
                        f"No connection attempts until backoff expires.",
                        extra={
                            "retry_in_seconds": retry_in,
                            "error_class": self.state.last_error_class,
                        },
                    )
                # Wait in chunks (max 60s) to stay responsive to stop events
                wait_time = min(retry_in, 60)
                await asyncio.sleep(wait_time)
                continue

            # Double-check we're allowed to retry (defensive)
            if not self._can_retry_now():
                await asyncio.sleep(5)
                continue

            # Attempt reconnection
            self.state.init_attempts += 1
            try:
                logger.info(
                    f"[DB Supervisor] Attempting reconnection (attempt {self.state.init_attempts})"
                )
                await self.connect_fn()
                # If connect_fn didn't raise, we're connected
                # State should be updated by connect_fn via mark_connected()
            except Exception as e:
                # Error handling done by connect_fn
                logger.debug(f"[DB Supervisor] Reconnection failed: {e}")

            # Brief pause before checking state again
            await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL STATE SINGLETON
# ═══════════════════════════════════════════════════════════════════════════

db_state = DBReadinessState()


# Export supervisor factory
def create_db_supervisor(connect_fn: Callable) -> DBSupervisor:
    """Create a DB supervisor instance for the global state."""
    return DBSupervisor(db_state, connect_fn)
