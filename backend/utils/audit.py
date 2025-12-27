"""
Dragonfly Audit Logging - Ops-Grade Universal Traceability

Provides helper functions for logging operational events to the universal
ops.event_log table for end-to-end traceability across all domains:
- ingest: Data ingestion pipeline events
- enforcement: Enforcement action events
- pdf: PDF generation and delivery events
- external: Third-party API integration events
- system: System-level events (workers, reaper, etc.)
- api: API request/response events
- worker: Background worker events

Usage:
    from backend.utils.audit import log_event

    # Log any domain event
    await log_event(
        domain="enforcement",
        stage="wage_garnishment",
        event="completed",
        correlation_id=trace_id,
        metadata={"debtor_id": "abc", "amount": 500.00}
    )

    # Legacy ingest event (backwards compatible)
    await log_ingest_event(
        batch_id=batch_id,
        stage="validate",
        event="completed",
        metadata={"valid_count": 100, "failed_count": 5}
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Thread pool for fire-and-forget audit logging
_audit_executor: ThreadPoolExecutor | None = None

# Valid domains for the universal audit log
AuditDomain = Literal["ingest", "enforcement", "pdf", "external", "system", "api", "worker"]


def _get_executor() -> ThreadPoolExecutor:
    """Get or create the audit logging thread pool."""
    global _audit_executor
    if _audit_executor is None:
        _audit_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audit")
    return _audit_executor


# =============================================================================
# UNIVERSAL AUDIT LOG
# =============================================================================


async def log_event(
    domain: AuditDomain,
    stage: str,
    event: str,
    correlation_id: uuid.UUID | str | None = None,
    batch_id: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> uuid.UUID | None:
    """
    Log an event to the universal ops.event_log.

    This is the primary audit logging function that supports all domains:
    - ingest: Data ingestion pipeline
    - enforcement: Enforcement actions
    - pdf: PDF generation and delivery
    - external: Third-party API integrations
    - system: System-level events
    - api: API request/response events
    - worker: Background worker events

    Args:
        domain: Event domain (ingest, enforcement, pdf, external, system, api, worker)
        stage: Domain-specific processing stage
        event: Event type (started, completed, failed, retried, skipped, warning, info)
        correlation_id: End-to-end trace ID for request correlation
        batch_id: Optional batch ID (primarily for ingest domain)
        metadata: Structured event data (counts, errors, timing, etc.)

    Returns:
        The UUID of the created audit log entry, or None on failure

    Example:
        await log_event(
            domain="enforcement",
            stage="wage_garnishment",
            event="completed",
            correlation_id=trace_id,
            metadata={"debtor_id": "abc", "amount": 500.00}
        )
    """
    from ..db import get_pool

    try:
        pool = await get_pool()
        if pool is None:
            logger.warning("Audit log skipped: database pool not initialized")
            return None

        # Convert string UUIDs if needed
        if correlation_id and isinstance(correlation_id, str):
            correlation_id = uuid.UUID(correlation_id)
        if batch_id and isinstance(batch_id, str):
            batch_id = uuid.UUID(batch_id)

        # Ensure metadata is JSON serializable
        if metadata:
            metadata = _sanitize_metadata(metadata)

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO ops.event_log 
                    (correlation_id, batch_id, domain, stage, event, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        correlation_id,
                        batch_id,
                        domain,
                        stage,
                        event,
                        json.dumps(metadata) if metadata else "{}",
                    ),
                )
                row = await cur.fetchone()
                await conn.commit()

                log_id = row[0] if row else None
                logger.debug(f"Audit logged: {domain}/{stage}/{event} (id={log_id})")
                return log_id

    except Exception as e:
        # Never fail the main operation due to audit logging
        logger.warning(f"Audit log failed (non-fatal): {e}")
        return None


def log_event_sync(
    domain: AuditDomain,
    stage: str,
    event: str,
    correlation_id: uuid.UUID | str | None = None,
    batch_id: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    Fire-and-forget sync wrapper for universal audit logging.

    Submits the audit log to a background thread pool so it doesn't
    block the calling code. Use this for non-critical audit events.

    Args:
        domain: Event domain
        stage: Domain-specific processing stage
        event: Event type
        correlation_id: Optional correlation ID
        batch_id: Optional batch ID
        metadata: Additional context as JSON
    """

    def _log_in_thread():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    log_event(
                        domain=domain,
                        stage=stage,
                        event=event,
                        correlation_id=correlation_id,
                        batch_id=batch_id,
                        metadata=metadata,
                    )
                )
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"Background audit log failed: {e}")

    try:
        executor = _get_executor()
        executor.submit(_log_in_thread)
    except Exception as e:
        logger.warning(f"Failed to submit audit log to executor: {e}")


# =============================================================================
# LEGACY INGEST LOGGING (Backwards Compatible)
# =============================================================================


async def log_ingest_event(
    batch_id: uuid.UUID | str,
    stage: str,
    event: str,
    metadata: dict[str, Any] | None = None,
    correlation_id: uuid.UUID | str | None = None,
) -> uuid.UUID | None:
    """
    Log an intake pipeline event (legacy wrapper for log_event).

    Args:
        batch_id: The batch this event belongs to
        stage: Pipeline stage (upload, parse, validate, transform, enrich, complete)
        event: Event type (started, completed, failed, retried, skipped)
        metadata: Additional context as JSON (row counts, errors, timing)
        correlation_id: Optional correlation ID for tracing

    Returns:
        The UUID of the created audit log entry, or None on failure

    Example:
        await log_ingest_event(
            batch_id="abc-123",
            stage="validate",
            event="completed",
            metadata={"valid_count": 100, "failed_count": 5}
        )
    """
    # Delegate to universal log_event with domain="ingest"
    return await log_event(
        domain="ingest",
        stage=stage,
        event=event,
        correlation_id=correlation_id,
        batch_id=batch_id,
        metadata=metadata,
    )


def log_ingest_event_sync(
    batch_id: uuid.UUID | str,
    stage: str,
    event: str,
    metadata: dict[str, Any] | None = None,
    correlation_id: uuid.UUID | str | None = None,
) -> None:
    """
    Fire-and-forget sync wrapper for ingest audit logging.

    Submits the audit log to a background thread pool so it doesn't
    block the calling code. Use this for non-critical audit events.

    Args:
        batch_id: The batch this event belongs to
        stage: Pipeline stage
        event: Event type
        metadata: Additional context as JSON
        correlation_id: Optional correlation ID
    """
    # Delegate to universal log_event_sync
    log_event_sync(
        domain="ingest",
        stage=stage,
        event=event,
        correlation_id=correlation_id,
        batch_id=batch_id,
        metadata=metadata,
    )


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize metadata to ensure JSON serialization.

    Converts non-serializable types to strings.
    """
    sanitized = {}
    for key, value in metadata.items():
        try:
            # Test if value is JSON serializable
            json.dumps(value)
            sanitized[key] = value
        except (TypeError, ValueError):
            # Convert to string representation
            if isinstance(value, datetime):
                sanitized[key] = value.isoformat()
            elif isinstance(value, uuid.UUID):
                sanitized[key] = str(value)
            elif hasattr(value, "__dict__"):
                sanitized[key] = str(value)
            else:
                sanitized[key] = repr(value)
    return sanitized


# Convenience functions for common audit events
async def audit_batch_started(
    batch_id: uuid.UUID | str,
    filename: str,
    source: str,
    correlation_id: uuid.UUID | str | None = None,
) -> uuid.UUID | None:
    """Log batch processing started."""
    return await log_ingest_event(
        batch_id=batch_id,
        stage="upload",
        event="started",
        metadata={"filename": filename, "source": source},
        correlation_id=correlation_id,
    )


async def audit_batch_completed(
    batch_id: uuid.UUID | str,
    total_rows: int,
    valid_rows: int,
    failed_rows: int,
    duration_seconds: float,
    correlation_id: uuid.UUID | str | None = None,
) -> uuid.UUID | None:
    """Log batch processing completed."""
    return await log_ingest_event(
        batch_id=batch_id,
        stage="complete",
        event="completed",
        metadata={
            "total_rows": total_rows,
            "valid_rows": valid_rows,
            "failed_rows": failed_rows,
            "duration_seconds": round(duration_seconds, 2),
            "success_rate": round((valid_rows / total_rows) * 100, 2) if total_rows else 0,
        },
        correlation_id=correlation_id,
    )


async def audit_batch_failed(
    batch_id: uuid.UUID | str,
    error: str,
    stage: str = "unknown",
    correlation_id: uuid.UUID | str | None = None,
) -> uuid.UUID | None:
    """Log batch processing failed."""
    return await log_ingest_event(
        batch_id=batch_id,
        stage=stage,
        event="failed",
        metadata={"error": error[:500]},  # Truncate long errors
        correlation_id=correlation_id,
    )


async def audit_validation_completed(
    batch_id: uuid.UUID | str,
    valid_count: int,
    failed_count: int,
    correlation_id: uuid.UUID | str | None = None,
) -> uuid.UUID | None:
    """Log validation stage completed."""
    return await log_ingest_event(
        batch_id=batch_id,
        stage="validate",
        event="completed",
        metadata={
            "valid_count": valid_count,
            "failed_count": failed_count,
        },
        correlation_id=correlation_id,
    )
