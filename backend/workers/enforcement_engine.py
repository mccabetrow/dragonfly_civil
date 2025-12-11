#!/usr/bin/env python3
"""
Dragonfly Engine - Enforcement Engine Worker

Background worker that processes enforcement jobs from ops.job_queue.
Polls for jobs with job_type in ('enforcement_strategy', 'enforcement_drafting')
and status = 'pending', then dispatches to the appropriate AI agent pipeline.

Architecture:
- Uses FOR UPDATE SKIP LOCKED for safe concurrent dequeue
- Transactional job state management
- Idempotent design (can safely retry failed jobs)
- Structured logging with correlation IDs
- Logs activity to ops.intake_logs for observability

Job Types:
- enforcement_strategy: Runs Extractor → Normalizer → Reasoner → Strategist
- enforcement_drafting: Runs full pipeline including Drafter → Auditor

Payload Schema:
    {
        "judgment_id": "uuid-of-judgment-to-process",
        "plan_id": "optional-plan-id-for-drafting"
    }

Usage:
    python -m backend.workers.enforcement_engine

Environment:
    SUPABASE_MODE: dev | prod (determines which Supabase project to use)
    SUPABASE_DB_URL_DEV / SUPABASE_DB_URL_PROD: Postgres connection strings
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("enforcement_engine")

# Worker configuration
POLL_INTERVAL_SECONDS = 5.0
LOCK_TIMEOUT_MINUTES = 30
JOB_TYPES = ("enforcement_strategy", "enforcement_drafting", "enforcement_generate_packet")


# =============================================================================
# Job Queue Operations
# =============================================================================


def claim_pending_job(conn: psycopg.Connection) -> dict[str, Any] | None:
    """
    Claim a pending enforcement job using FOR UPDATE SKIP LOCKED.

    Returns the job row dict, or None if no jobs available.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'processing',
                locked_at = now(),
                attempts = attempts + 1
            WHERE id = (
                SELECT id FROM ops.job_queue
                WHERE job_type::text = ANY(%s)
                  AND status::text = 'pending'
                  AND (locked_at IS NULL OR locked_at < now() - interval '%s minutes')
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            (list(JOB_TYPES), LOCK_TIMEOUT_MINUTES),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def mark_job_completed(conn: psycopg.Connection, job_id: str | UUID) -> None:
    """Mark a job as completed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'completed', locked_at = NULL, updated_at = now()
            WHERE id = %s
            """,
            (str(job_id),),
        )
        conn.commit()


def mark_job_failed(conn: psycopg.Connection, job_id: str | UUID, error: str) -> None:
    """Mark a job as failed with error message."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'failed', locked_at = NULL, last_error = %s, updated_at = now()
            WHERE id = %s
            """,
            (error[:2000], str(job_id)),  # Truncate error to avoid column overflow
        )
        conn.commit()


def log_job_event(
    conn: psycopg.Connection,
    job_id: str | UUID | None,
    level: str,
    message: str,
    raw_payload: dict[str, Any] | None = None,
) -> None:
    """Write a record into ops.intake_logs for observability."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.intake_logs (job_id, level, message, raw_payload, created_at)
                VALUES (%s::uuid, %s, %s, %s, now())
                """,
                (
                    str(job_id) if job_id else None,
                    level,
                    message[:1000],
                    json.dumps(raw_payload, default=str) if raw_payload else None,
                ),
            )
            conn.commit()
    except Exception as e:
        # Table might not exist yet - rollback and continue
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug(f"Could not log event to ops.intake_logs: {e}")


# =============================================================================
# Agent Pipeline Execution
# =============================================================================


def run_smart_strategy(conn: psycopg.Connection, judgment_id: str) -> dict[str, Any]:
    """
    Execute Smart Strategy Agent - deterministic strategy selection.

    Decision logic:
        1. IF employer found → Wage Garnishment
        2. ELIF bank_name found → Bank Levy
        3. ELIF home_ownership = 'owner' → Property Lien
        4. ELSE → Surveillance (queue for enrichment)

    Args:
        conn: Active database connection
        judgment_id: UUID of judgment to process

    Returns:
        dict with success status, strategy_type, strategy_reason, and plan_id
    """
    from backend.workers.smart_strategy import SmartStrategy

    logger.info(f"[enforcement_strategy] Running Smart Strategy for judgment_id={judgment_id}")

    try:
        agent = SmartStrategy(conn)
        decision = agent.evaluate(judgment_id, persist=True)

        return {
            "success": True,
            "strategy_type": decision.strategy_type.value,
            "strategy_reason": decision.strategy_reason,
            "plan_id": None,  # Plan ID is generated during persist but not returned
            "error_message": None,
        }
    except Exception as e:
        logger.exception(f"[enforcement_strategy] Smart Strategy failed: {e}")
        return {
            "success": False,
            "strategy_type": None,
            "strategy_reason": None,
            "plan_id": None,
            "error_message": str(e),
        }


async def run_strategy_pipeline(judgment_id: str) -> dict[str, Any]:
    """
    Execute strategy-only pipeline via Orchestrator (AI-powered).

    Runs: Extractor → Normalizer → Reasoner → Strategist
    Does NOT run Drafter or Auditor.

    Note: For simpler, deterministic strategy selection based on debtor
    intelligence, use run_smart_strategy() instead.

    Args:
        judgment_id: UUID of judgment to process

    Returns:
        dict with success status and optional plan_id
    """
    from backend.agents.orchestrator import Orchestrator

    logger.info(f"[enforcement_strategy] Starting AI pipeline for judgment_id={judgment_id}")

    orchestrator = Orchestrator()
    output = await orchestrator.run_strategy_only(judgment_id)

    return {
        "success": output.success,
        "run_id": output.run_id,
        "plan_id": output.persisted_plan_id,
        "stages_completed": [s.value for s in output.stages_completed],
        "duration_seconds": output.duration_seconds,
        "error_message": output.error_message,
    }


async def run_drafting_pipeline(judgment_id: str, plan_id: str | None = None) -> dict[str, Any]:
    """
    Execute full pipeline including drafting via Orchestrator.

    Runs: Extractor → Normalizer → Reasoner → Strategist → Drafter → Auditor

    Args:
        judgment_id: UUID of judgment to process
        plan_id: Optional plan_id (for future use - currently re-runs full pipeline)

    Returns:
        dict with success status and optional packet_id
    """
    from backend.agents.orchestrator import Orchestrator

    logger.info(
        f"[enforcement_drafting] Starting pipeline for judgment_id={judgment_id}, plan_id={plan_id}"
    )

    orchestrator = Orchestrator()
    output = await orchestrator.run_full(judgment_id)

    return {
        "success": output.success,
        "run_id": output.run_id,
        "plan_id": output.persisted_plan_id,
        "packet_id": output.persisted_packet_id,
        "stages_completed": [s.value for s in output.stages_completed],
        "duration_seconds": output.duration_seconds,
        "error_message": output.error_message,
    }


# =============================================================================
# Job Processing
# =============================================================================


async def process_job(conn: psycopg.Connection, job: dict[str, Any]) -> None:
    """
    Process a single enforcement job.

    Dispatches to the appropriate pipeline based on job_type.
    Updates job status on completion or failure.
    """
    job_id = job["id"]
    job_type = str(job.get("job_type", "")).strip()
    payload = job.get("payload") or {}

    # Parse payload if it's a string
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}

    judgment_id = payload.get("judgment_id")

    if not judgment_id:
        error_msg = f"Job {job_id} missing required judgment_id in payload"
        logger.error(error_msg)
        log_job_event(conn, job_id, "ERROR", error_msg, payload)
        mark_job_failed(conn, job_id, error_msg)
        return

    logger.info(f"Processing job {job_id} type={job_type} judgment_id={judgment_id}")
    log_job_event(conn, job_id, "INFO", f"Started processing {job_type}", payload)

    try:
        if job_type == "enforcement_strategy":
            # Use Smart Strategy (deterministic) by default
            # Set payload.use_ai_pipeline=true to use the full AI Orchestrator
            use_ai = payload.get("use_ai_pipeline", False)
            if use_ai:
                result = await run_strategy_pipeline(judgment_id)
            else:
                # SmartStrategy is sync - no await needed
                result = run_smart_strategy(conn, judgment_id)
        elif job_type == "enforcement_drafting":
            plan_id = payload.get("plan_id")
            result = await run_drafting_pipeline(judgment_id, plan_id)
        elif job_type == "enforcement_generate_packet":
            # Generate enforcement packet - runs full drafting pipeline
            strategy = payload.get("strategy", "wage_garnishment")
            case_number = payload.get("case_number", "UNKNOWN")
            result = await run_drafting_pipeline(judgment_id)
            # Log packet generation to ops.intake_logs
            if result["success"]:
                log_job_event(
                    conn,
                    job_id,
                    "INFO",
                    f"Packet Generated for Case {case_number}",
                    {"strategy": strategy, "packet_id": result.get("packet_id")},
                )
        else:
            raise ValueError(f"Unknown job_type: {job_type}")

        if result["success"]:
            logger.info(f"Job {job_id} completed successfully: {result}")
            log_job_event(conn, job_id, "INFO", f"Completed {job_type}", result)
            mark_job_completed(conn, job_id)
        else:
            error_msg = result.get("error_message") or "Pipeline returned success=False"
            logger.error(f"Job {job_id} pipeline failed: {error_msg}")
            log_job_event(conn, job_id, "ERROR", f"Pipeline failed: {error_msg}", result)
            mark_job_failed(conn, job_id, error_msg)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(f"Job {job_id} raised exception: {error_msg}")
        log_job_event(conn, job_id, "ERROR", f"Exception: {error_msg}", payload)
        mark_job_failed(conn, job_id, error_msg)


# =============================================================================
# Main Worker Loop
# =============================================================================


def run_once(conn: psycopg.Connection) -> bool:
    """
    Claim and process a single job (if available).

    Returns:
        True if a job was processed, False if no jobs available
    """
    job = claim_pending_job(conn)
    if not job:
        return False

    # Run async pipeline in sync context
    asyncio.run(process_job(conn, job))
    return True


def run_forever(db_url: str) -> None:
    """
    Main polling loop. Runs until interrupted.
    """
    logger.info(f"Starting enforcement_engine worker (poll={POLL_INTERVAL_SECONDS}s)")
    logger.info(f"Handling job types: {JOB_TYPES}")
    logger.info(f"Lock timeout: {LOCK_TIMEOUT_MINUTES} minutes")

    while True:
        try:
            with psycopg.connect(db_url, row_factory=dict_row) as conn:
                if run_once(conn):
                    # Job processed - check for more immediately
                    continue
                else:
                    # No jobs - sleep before next poll
                    time.sleep(POLL_INTERVAL_SECONDS)

        except psycopg.OperationalError as e:
            logger.error(f"Database connection error: {e}")
            time.sleep(10.0)  # Back off on connection errors

        except KeyboardInterrupt:
            logger.info("Shutting down enforcement_engine worker (keyboard interrupt)")
            break

        except Exception as e:
            logger.exception(f"Unexpected error in worker loop: {e}")
            time.sleep(5.0)


def main() -> None:
    """Entry point for the enforcement engine worker."""
    env = get_supabase_env()
    db_url = get_supabase_db_url()

    logger.info(f"Environment: {env}")
    logger.info(f"Database: {db_url[:30]}...")

    run_forever(db_url)


if __name__ == "__main__":
    main()
