"""
Dragonfly Engine - Transactional Database Operations

Utilities for ensuring data integrity through transactional writes.
Provides atomic operations for common patterns:
- Status update + queue job (atomic)
- Multi-table writes with rollback
- Optimistic locking patterns

Usage:
    from backend.core.transactions import (
        atomic_status_and_enqueue,
        TransactionContext,
    )

    # Atomic: update judgment status AND enqueue enrichment job
    await atomic_status_and_enqueue(
        judgment_id=123,
        new_status="pending_enrichment",
        job_kind=QueueJobKind.ENRICH,
        job_payload={"case_number": "2024-CV-001"},
    )
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, TypeVar
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

from backend.core.logging import LogContext, get_logger
from backend.core.models import JudgmentStatus, QueueJobKind
from backend.db import get_pool

logger = get_logger(__name__)

T = TypeVar("T")


# =============================================================================
# Transaction Context Manager
# =============================================================================


@asynccontextmanager
async def TransactionContext(
    isolation_level: str = "READ COMMITTED",
) -> AsyncGenerator[psycopg.AsyncConnection, None]:
    """
    Async context manager for database transactions.

    Automatically commits on success, rolls back on exception.

    Args:
        isolation_level: Transaction isolation level

    Usage:
        async with TransactionContext() as conn:
            await conn.execute("UPDATE ...")
            await conn.execute("INSERT ...")
            # Commits automatically if no exception
    """
    pool = await get_pool()

    async with pool.connection() as conn:
        # Set isolation level
        await conn.set_autocommit(False)

        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


# =============================================================================
# Atomic Status + Enqueue
# =============================================================================


async def atomic_status_and_enqueue(
    judgment_id: int,
    new_status: JudgmentStatus,
    job_kind: QueueJobKind,
    job_payload: Dict[str, Any],
    idempotency_key: Optional[str] = None,
    expected_current_status: Optional[JudgmentStatus] = None,
) -> int:
    """
    Atomically update judgment status AND enqueue a follow-up job.

    This ensures that if the status update succeeds, the job is guaranteed
    to be enqueued, and vice versa.

    Args:
        judgment_id: Judgment to update
        new_status: New status value
        job_kind: Type of job to enqueue
        job_payload: Job payload data
        idempotency_key: Optional dedup key for job
        expected_current_status: If provided, only update if current status matches

    Returns:
        New job msg_id

    Raises:
        ValueError: If judgment not found or status mismatch
    """
    pool = await get_pool()

    async with pool.connection() as conn:
        await conn.set_autocommit(False)

        try:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Update judgment status with optional optimistic locking
                if expected_current_status:
                    await cur.execute(
                        """
                        UPDATE public.judgments
                        SET status = %(new_status)s,
                            updated_at = NOW()
                        WHERE id = %(judgment_id)s
                          AND status = %(expected_status)s
                        RETURNING id, status
                        """,
                        {
                            "judgment_id": judgment_id,
                            "new_status": new_status.value,
                            "expected_status": expected_current_status.value,
                        },
                    )
                else:
                    await cur.execute(
                        """
                        UPDATE public.judgments
                        SET status = %(new_status)s,
                            updated_at = NOW()
                        WHERE id = %(judgment_id)s
                        RETURNING id, status
                        """,
                        {
                            "judgment_id": judgment_id,
                            "new_status": new_status.value,
                        },
                    )

                row = await cur.fetchone()
                if row is None:
                    await conn.rollback()
                    if expected_current_status:
                        raise ValueError(
                            f"Judgment {judgment_id} not found or status "
                            f"is not {expected_current_status.value}"
                        )
                    raise ValueError(f"Judgment {judgment_id} not found")

                # Enqueue the job
                await cur.execute(
                    """
                    INSERT INTO job_queue (kind, payload, idempotency_key, status, created_at)
                    VALUES (%(kind)s, %(payload)s::jsonb, %(key)s, 'pending', NOW())
                    ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                    DO NOTHING
                    RETURNING msg_id
                    """,
                    {
                        "kind": job_kind.value,
                        "payload": psycopg.types.json.Jsonb(job_payload),
                        "key": idempotency_key,
                    },
                )

                job_row = await cur.fetchone()
                if job_row is None:
                    # Duplicate idempotency key - fetch existing
                    await cur.execute(
                        "SELECT msg_id FROM job_queue WHERE idempotency_key = %(key)s",
                        {"key": idempotency_key},
                    )
                    job_row = await cur.fetchone()

                msg_id = job_row["msg_id"]

            await conn.commit()

            logger.info(
                f"Atomic update: judgment {judgment_id} -> {new_status.value}, "
                f"enqueued {job_kind.value} job {msg_id}",
                extra={
                    "judgment_id": judgment_id,
                    "new_status": new_status.value,
                    "job_kind": job_kind.value,
                    "job_id": msg_id,
                },
            )

            return msg_id

        except Exception:
            await conn.rollback()
            raise


# =============================================================================
# Atomic Multi-Table Writes
# =============================================================================


async def atomic_judgment_update(
    judgment_id: int,
    updates: Dict[str, Any],
    create_event: bool = True,
    event_type: str = "status_change",
    event_details: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Atomically update judgment fields and optionally create an event log entry.

    Args:
        judgment_id: Judgment to update
        updates: Dict of column -> value updates
        create_event: If True, also create an enforcement_events entry
        event_type: Event type for the log
        event_details: Additional event metadata

    Returns:
        True if update succeeded
    """
    if not updates:
        return False

    pool = await get_pool()

    # Build SET clause dynamically
    set_parts = []
    params: Dict[str, Any] = {"judgment_id": judgment_id}

    for i, (col, val) in enumerate(updates.items()):
        param_name = f"val_{i}"
        set_parts.append(f"{col} = %({param_name})s")
        params[param_name] = val

    set_parts.append("updated_at = NOW()")
    set_clause = ", ".join(set_parts)

    async with pool.connection() as conn:
        await conn.set_autocommit(False)

        try:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Update judgment
                await cur.execute(
                    f"""
                    UPDATE public.judgments
                    SET {set_clause}
                    WHERE id = %(judgment_id)s
                    RETURNING id, case_number
                    """,
                    params,
                )

                row = await cur.fetchone()
                if row is None:
                    await conn.rollback()
                    return False

                # Create event if requested
                if create_event:
                    await cur.execute(
                        """
                        INSERT INTO enforcement.enforcement_events
                        (case_id, event_type, details, created_at)
                        VALUES (%(case_id)s, %(event_type)s, %(details)s::jsonb, NOW())
                        """,
                        {
                            "case_id": row["case_number"],
                            "event_type": event_type,
                            "details": psycopg.types.json.Jsonb(
                                {
                                    "judgment_id": judgment_id,
                                    "updates": updates,
                                    **(event_details or {}),
                                }
                            ),
                        },
                    )

            await conn.commit()

            logger.info(
                f"Atomic judgment update: {judgment_id}",
                extra={"judgment_id": judgment_id, "updates": list(updates.keys())},
            )

            return True

        except Exception:
            await conn.rollback()
            raise


# =============================================================================
# Batch Operations with Transactions
# =============================================================================


async def batch_update_scores(
    score_updates: List[Dict[str, Any]],
    batch_size: int = 100,
) -> Dict[str, int]:
    """
    Batch update collectability scores with transaction safety.

    Each batch is its own transaction - if one record fails,
    only that batch rolls back.

    Args:
        score_updates: List of dicts with judgment_id, score, tier, breakdown
        batch_size: Records per transaction

    Returns:
        Dict with 'updated' and 'failed' counts
    """
    pool = await get_pool()
    updated = 0
    failed = 0

    for i in range(0, len(score_updates), batch_size):
        batch = score_updates[i : i + batch_size]

        async with pool.connection() as conn:
            await conn.set_autocommit(False)

            try:
                async with conn.cursor() as cur:
                    for record in batch:
                        await cur.execute(
                            """
                            UPDATE public.judgments
                            SET collectability_score = %(score)s,
                                collectability_tier = %(tier)s,
                                score_breakdown = %(breakdown)s::jsonb,
                                scored_at = NOW(),
                                updated_at = NOW()
                            WHERE id = %(judgment_id)s
                            """,
                            {
                                "judgment_id": record["judgment_id"],
                                "score": record["score"],
                                "tier": record["tier"],
                                "breakdown": psycopg.types.json.Jsonb(record.get("breakdown", {})),
                            },
                        )

                await conn.commit()
                updated += len(batch)

            except Exception as e:
                await conn.rollback()
                failed += len(batch)
                logger.error(
                    f"Batch score update failed: {e}",
                    extra={"batch_start": i, "batch_size": len(batch)},
                )

    logger.info(
        f"Batch score update complete: {updated} updated, {failed} failed",
        extra={"updated": updated, "failed": failed},
    )

    return {"updated": updated, "failed": failed}


# =============================================================================
# Optimistic Locking
# =============================================================================


class OptimisticLockError(Exception):
    """Raised when optimistic lock check fails."""

    def __init__(self, entity: str, entity_id: Any, expected_version: Any):
        self.entity = entity
        self.entity_id = entity_id
        self.expected_version = expected_version
        super().__init__(
            f"Optimistic lock failed for {entity} {entity_id}: expected version {expected_version}"
        )


async def update_with_version_check(
    table: str,
    id_column: str,
    id_value: Any,
    updates: Dict[str, Any],
    expected_updated_at: datetime,
) -> bool:
    """
    Update a record only if updated_at matches expected value.

    This implements optimistic locking to prevent lost updates
    in concurrent scenarios.

    Args:
        table: Table name
        id_column: Primary key column name
        id_value: Primary key value
        updates: Dict of column -> value updates
        expected_updated_at: Expected current updated_at value

    Returns:
        True if update succeeded

    Raises:
        OptimisticLockError: If version check fails
    """
    pool = await get_pool()

    set_parts = []
    params: Dict[str, Any] = {
        "id_value": id_value,
        "expected_updated_at": expected_updated_at,
    }

    for i, (col, val) in enumerate(updates.items()):
        param_name = f"val_{i}"
        set_parts.append(f"{col} = %({param_name})s")
        params[param_name] = val

    set_parts.append("updated_at = NOW()")
    set_clause = ", ".join(set_parts)

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE {table}
                SET {set_clause}
                WHERE {id_column} = %(id_value)s
                  AND updated_at = %(expected_updated_at)s
                RETURNING {id_column}
                """,
                params,
            )

            row = await cur.fetchone()

            if row is None:
                raise OptimisticLockError(table, id_value, expected_updated_at)

            return True
