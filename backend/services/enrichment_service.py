"""
Dragonfly Engine - Enrichment Service

Background job queue processing for TLOxp, idiCORE enrichment,
and PDF packet generation. Implements stateless, idempotent workers
with FOR UPDATE SKIP LOCKED pattern for safe concurrency.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from ..config import get_settings
from ..db import get_pool

logger = logging.getLogger(__name__)

settings = get_settings()


# ---------------------------------------------------------------------------
# Collectability Score Helpers
# ---------------------------------------------------------------------------


def _years_since(dt: date | datetime | None) -> Optional[float]:
    """Calculate years elapsed since a given date."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        dt = dt.date()
    today = date.today()
    days = (today - dt).days
    return days / 365.25


def calculate_collectability_score(
    enrichment_data: Dict[str, Any],
    judgment_date: Optional[date | datetime],
) -> int:
    """
    Compute a v1 collectability score (0–100) based on simple rules.

    Rules:
      - +40 if employed
      - +30 if homeowner
      - +10 if has_bank_account
      - +20 if judgment < 5 years old

    Args:
        enrichment_data: Dict with enrichment fields (employed, homeowner, has_bank_account)
        judgment_date: Original judgment date for age calculation

    Returns:
        Integer score 0-100
    """
    score = 0

    employed = bool(enrichment_data.get("employed"))
    homeowner = bool(enrichment_data.get("homeowner"))
    has_bank_account = bool(enrichment_data.get("has_bank_account"))

    if employed:
        score += 40
    if homeowner:
        score += 30
    if has_bank_account:
        score += 10

    age_years = _years_since(judgment_date)
    if age_years is not None and age_years < 5:
        score += 20

    if score > 100:
        score = 100
    if score < 0:
        score = 0

    return int(score)


# ---------------------------------------------------------------------------
# External client stubs (to be replaced with real implementations)
# ---------------------------------------------------------------------------


class TLOClient:
    """Stub for TLOxp API client."""

    async def search(self, judgment_id: str, amount: float) -> dict[str, Any]:
        """
        Search TLOxp for debtor intelligence.

        Returns enrichment data dict with fields like:
        - employed: bool
        - employer_name: str | None
        - homeowner: bool
        - has_bank_account: bool
        """
        logger.info(f"[TLO] Searching for judgment_id={judgment_id}, amount={amount}")
        # TODO: Replace with real TLOxp API call
        await asyncio.sleep(0.1)  # Simulate API latency
        return {
            "employed": True,
            "employer_name": "ACME Corp",
            "homeowner": False,
            "has_bank_account": True,
            "source": "tlo",
        }


class IDICoreClient:
    """Stub for idiCORE API client."""

    async def search(self, judgment_id: str, amount: float) -> dict[str, Any]:
        """
        Search idiCORE for debtor intelligence.

        Returns enrichment data dict.
        """
        logger.info(
            f"[idiCORE] Searching for judgment_id={judgment_id}, amount={amount}"
        )
        # TODO: Replace with real idiCORE API call
        await asyncio.sleep(0.1)  # Simulate API latency
        return {
            "employed": False,
            "employer_name": None,
            "homeowner": True,
            "has_bank_account": True,
            "source": "idicore",
        }


class PDFClient:
    """Stub for PDF generation service."""

    async def generate_packet(self, judgment_id: str, **kwargs: Any) -> dict[str, Any]:
        """
        Generate enforcement packet PDF.

        Returns dict with generated file info.
        """
        logger.info(f"[PDF] Generating packet for judgment_id={judgment_id}")
        # TODO: Replace with real PDF generation
        await asyncio.sleep(0.2)  # Simulate generation time
        return {
            "url": f"https://storage.example.com/packets/{judgment_id}.pdf",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# Singleton client instances
tlo_client = TLOClient()
idicore_client = IDICoreClient()
pdf_client = PDFClient()


# ---------------------------------------------------------------------------
# Job Queue Functions
# ---------------------------------------------------------------------------


async def queue_enrichment(judgment_id: str, amount: float) -> Optional[UUID]:
    """
    Queue an enrichment job for a judgment.

    Business logic:
    - If amount > 5000: use TLO (premium data source)
    - Otherwise: use idiCORE (standard data source)

    Args:
        judgment_id: UUID of the judgment to enrich
        amount: Judgment amount (determines enrichment source)

    Returns:
        UUID of the created job, or None if queueing is not available
    """
    job_type = "enrich_tlo" if amount > 5000 else "enrich_idicore"
    payload = {"judgment_id": judgment_id, "amount": amount}

    conn = await get_pool()
    if conn is None:
        logger.warning("Database connection not available, skipping enrichment queue")
        return None

    try:
        # Check if the job_queue table exists first
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'ops' AND table_name = 'job_queue'
                )
            """
            )
            row = await cur.fetchone()
            if not row or not row[0]:
                logger.debug(
                    "ops.job_queue table does not exist, skipping enrichment queue"
                )
                return None

        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO ops.job_queue (job_type, payload, status)
                    VALUES (%s::ops.job_type_enum, %s::jsonb, 'pending')
                    RETURNING id
                    """,
                    (job_type, psycopg.types.json.Json(payload)),
                )
                row = await cur.fetchone()

        if row is None:
            logger.warning("Failed to create job - no row returned")
            return None

        job_id = row["id"]
        logger.info(f"Queued {job_type} job {job_id} for judgment {judgment_id}")
        return job_id

    except Exception as e:
        logger.warning(f"Failed to queue enrichment job: {e}")
        return None


async def queue_pdf_generation(judgment_id: str, **kwargs: Any) -> UUID:
    """
    Queue a PDF packet generation job.

    Args:
        judgment_id: UUID of the judgment
        **kwargs: Additional parameters for PDF generation

    Returns:
        UUID of the created job
    """
    payload = {"judgment_id": judgment_id, **kwargs}

    conn = await get_pool()
    if conn is None:
        raise RuntimeError("Database connection not available")

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            INSERT INTO ops.job_queue (job_type, payload, status)
            VALUES ('generate_pdf'::ops.job_type_enum, %s::jsonb, 'pending')
            RETURNING id
            """,
            (psycopg.types.json.Json(payload),),
        )
        row = await cur.fetchone()

    if row is None:
        raise RuntimeError("Failed to create job")

    job_id = row["id"]
    logger.info(f"Queued PDF generation job {job_id} for judgment {judgment_id}")
    return job_id


async def process_one_job() -> bool:
    """
    Attempt to claim and process one job from the queue.

    Uses FOR UPDATE SKIP LOCKED for safe concurrent access.
    Jobs locked for more than 5 minutes are considered stuck and reclaimable.

    Returns:
        True if a job was processed (success or failure)
        False if no pending job was found
    """
    conn = await get_pool()
    if conn is None:
        raise RuntimeError("Database connection not available")

    job: Optional[dict[str, Any]] = None

    try:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                # Claim a job with FOR UPDATE SKIP LOCKED
                await cur.execute(
                    """
                    SELECT id, job_type, payload, attempts
                    FROM ops.job_queue
                    WHERE status = 'pending'
                      AND (locked_at IS NULL OR locked_at < now() - interval '5 minutes')
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                job = await cur.fetchone()

                if job is None:
                    return False

                # Lock the job
                await cur.execute(
                    """
                    UPDATE ops.job_queue
                    SET status = 'processing',
                        locked_at = now(),
                        attempts = attempts + 1
                    WHERE id = %s
                    """,
                    (job["id"],),
                )

        # Process outside the lock transaction
        job_id = job["id"]
        job_type = job["job_type"]
        payload = job["payload"]
        attempts = job["attempts"] + 1  # Already incremented in DB

        logger.info(f"Processing job {job_id} (type={job_type}, attempt={attempts})")

        try:
            await _execute_job(job_type, payload)
            await _mark_job_completed(conn, job_id)
            logger.info(f"Job {job_id} completed successfully")
            return True

        except Exception as exc:
            error_msg = str(exc)
            logger.error(f"Job {job_id} failed: {error_msg}")

            if attempts >= 3:
                await _mark_job_failed(conn, job_id, error_msg)
                logger.warning(
                    f"Job {job_id} permanently failed after {attempts} attempts"
                )
            else:
                await _mark_job_pending(conn, job_id, error_msg)
                logger.info(f"Job {job_id} will be retried (attempt {attempts}/3)")

            return True

    except Exception as exc:
        logger.exception(f"Error processing job queue: {exc}")
        return False


async def _execute_job(job_type: str, payload: dict[str, Any]) -> None:
    """
    Execute a job based on its type.

    Args:
        job_type: One of 'enrich_tlo', 'enrich_idicore', 'generate_pdf'
        payload: Job payload with judgment_id and other params
    """
    judgment_id = payload.get("judgment_id")
    if not judgment_id:
        raise ValueError("Missing judgment_id in payload")

    if job_type == "enrich_tlo":
        amount = payload.get("amount", 0)
        enrichment_data = await tlo_client.search(judgment_id, amount)
        await _apply_enrichment(judgment_id, enrichment_data)

    elif job_type == "enrich_idicore":
        amount = payload.get("amount", 0)
        enrichment_data = await idicore_client.search(judgment_id, amount)
        await _apply_enrichment(judgment_id, enrichment_data)

    elif job_type == "generate_pdf":
        result = await pdf_client.generate_packet(judgment_id, **payload)
        # TODO: Store PDF URL in judgments or a separate table
        logger.info(f"PDF generated: {result.get('url')}")

    else:
        raise ValueError(f"Unknown job type: {job_type}")


async def _apply_enrichment(judgment_id: str, result: dict[str, Any]) -> None:
    """
    Apply enrichment results to a judgment.

    Extracts scoring signals from the enrichment result, fetches the judgment date,
    computes the collectability score, and updates the judgment record.

    Args:
        judgment_id: UUID/ID of the judgment
        result: Raw result dict from TLO/idiCORE with enrichment fields
    """
    conn = await get_pool()
    if conn is None:
        raise RuntimeError("Database connection not available")

    # Extract scoring signals from enrichment result
    enrichment_data: Dict[str, Any] = {
        "employed": result.get("employed"),
        "homeowner": result.get("homeowner"),
        "has_bank_account": result.get("has_bank_account"),
    }

    # Fetch judgment date for score calculation
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT entry_date FROM public.judgments WHERE id = %s",
            (int(judgment_id) if judgment_id.isdigit() else judgment_id,),
        )
        row = await cur.fetchone()

    # Normalize judgment date (handle both date and datetime)
    judgment_date: Optional[date] = None
    if row and row.get("entry_date") is not None:
        jd = row["entry_date"]
        judgment_date = jd if isinstance(jd, date) else jd.date()

    # Compute collectability score
    score = calculate_collectability_score(enrichment_data, judgment_date)

    # Update judgment with score
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE public.judgments
            SET collectability_score = %s
            WHERE id = %s
            """,
            (score, int(judgment_id) if judgment_id.isdigit() else judgment_id),
        )

    logger.info("Judgment %s scored: %s", judgment_id, score)

    # TODO: Store detailed enrichment data in normalized tables
    # e.g., enrichment.employers, enrichment.assets


async def _mark_job_completed(conn: psycopg.AsyncConnection, job_id: UUID) -> None:
    """Mark a job as completed."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'completed',
                locked_at = NULL,
                last_error = NULL
            WHERE id = %s
            """,
            (job_id,),
        )


async def _mark_job_failed(
    conn: psycopg.AsyncConnection, job_id: UUID, error_msg: str
) -> None:
    """Mark a job as permanently failed."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'failed',
                locked_at = NULL,
                last_error = %s
            WHERE id = %s
            """,
            (error_msg, job_id),
        )


async def _mark_job_pending(
    conn: psycopg.AsyncConnection, job_id: UUID, error_msg: str
) -> None:
    """Mark a job as pending for retry."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'pending',
                locked_at = NULL,
                last_error = %s
            WHERE id = %s
            """,
            (error_msg, job_id),
        )


async def worker_loop(poll_interval_seconds: int = 5) -> None:
    """
    Run an infinite loop processing jobs from the queue.

    This should be run as a separate process/service (e.g., Railway worker).

    Args:
        poll_interval_seconds: Seconds to wait when no jobs are available
    """
    logger.info(
        f"Starting enrichment worker loop (poll_interval={poll_interval_seconds}s)"
    )

    while True:
        try:
            job_processed = await process_one_job()

            if not job_processed:
                # No job found, sleep before polling again
                await asyncio.sleep(poll_interval_seconds)

        except Exception as exc:
            logger.exception(f"Worker loop error: {exc}")
            # Sleep on error to avoid tight loop
            await asyncio.sleep(poll_interval_seconds)


# ---------------------------------------------------------------------------
# Entrypoint for running as standalone worker
# ---------------------------------------------------------------------------


async def main() -> None:
    """Main entrypoint for running the enrichment worker."""
    from ..db import init_db_pool

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logger.info("Initializing enrichment worker...")
    await init_db_pool()

    await worker_loop()


if __name__ == "__main__":
    asyncio.run(main())
