"""
Dragonfly Engine - Core Module

Contains security, configuration extensions, and shared utilities.
Includes:
- Pydantic models for data validation
- Structured JSON logging
- Queue processor with retry policies
- Transactional database operations
"""

from .db import Database, DatabaseNotStartedError, get_database, shutdown_database, startup_database
from .errors import (
    DatabaseError,
    DragonflyError,
    ErrorResponse,
    NotFoundError,
    ValidationError,
    setup_error_handlers,
)
from .logging import (
    LogContext,
    Timer,
    configure_structured_logging,
    get_logger,
    log_worker_failure,
    log_worker_start,
    log_worker_success,
    set_context,
    set_run_id,
)
from .middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    ResponseSanitizationMiddleware,
    get_request_id,
)
from .models import (
    BatchIngestRequest,
    BatchIngestResponse,
    ComplianceCheckRequest,
    ComplianceCheckResponse,
    EnrichJobPayload,
    EnrichmentData,
    JudgmentCreate,
    JudgmentRead,
    JudgmentStatus,
    JudgmentUpdate,
    QueueJob,
    QueueJobKind,
    QueueJobStatus,
    ScoreBreakdownModel,
    TierLevel,
    WorkerContext,
)
from .security import AuthContext, get_current_user, require_auth
from .transactions import (
    OptimisticLockError,
    TransactionContext,
    atomic_judgment_update,
    atomic_status_and_enqueue,
    batch_update_scores,
)

__all__ = [
    # Security
    "AuthContext",
    "get_current_user",
    "require_auth",
    # Middleware
    "RequestLoggingMiddleware",
    "RateLimitMiddleware",
    "ResponseSanitizationMiddleware",
    "get_request_id",
    # Errors
    "ErrorResponse",
    "DragonflyError",
    "NotFoundError",
    "ValidationError",
    "DatabaseError",
    "setup_error_handlers",
    # Logging
    "configure_structured_logging",
    "get_logger",
    "LogContext",
    "Timer",
    "set_context",
    "set_run_id",
    "log_worker_start",
    "log_worker_success",
    "log_worker_failure",
    # Models
    "TierLevel",
    "JudgmentStatus",
    "QueueJobKind",
    "QueueJobStatus",
    "JudgmentCreate",
    "JudgmentUpdate",
    "JudgmentRead",
    "EnrichJobPayload",
    "EnrichmentData",
    "ScoreBreakdownModel",
    "BatchIngestRequest",
    "BatchIngestResponse",
    "ComplianceCheckRequest",
    "ComplianceCheckResponse",
    "QueueJob",
    "WorkerContext",
    # Transactions
    "TransactionContext",
    "atomic_status_and_enqueue",
    "atomic_judgment_update",
    "batch_update_scores",
    "OptimisticLockError",
    # Database
    "Database",
    "DatabaseNotStartedError",
    "get_database",
    "startup_database",
    "shutdown_database",
]
