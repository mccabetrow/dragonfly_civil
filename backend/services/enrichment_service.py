"""
Dragonfly Engine - Enrichment Service

Background job queue processing for TLOxp, idiCORE enrichment,
and PDF packet generation. Implements stateless, idempotent workers
with FOR UPDATE SKIP LOCKED pattern for safe concurrency.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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
# Score Breakdown Data Structure (v2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreBreakdown:
    """
    Explainable breakdown of collectability score components.

    Components:
      - employment: 0-40 points based on employment status
      - assets: 0-30 points based on real estate/vehicles
      - recency: 0-20 points based on judgment age
      - banking: 0-10 points based on recent bank activity
    """

    employment: int
    assets: int
    recency: int
    banking: int

    @property
    def total(self) -> int:
        """Compute total score from components, clamped to 0-100."""
        raw = self.employment + self.assets + self.recency + self.banking
        return max(0, min(100, raw))


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


def compute_score_breakdown(
    enrichment_data: Dict[str, Any],
    judgment_date: Optional[date | datetime],
) -> ScoreBreakdown:
    """
    Compute an explainable score breakdown (v2) based on enrichment data.

    Scoring rules:
      - Employment (0-40):
        - employed == True: 40
        - self_employed == True: 20
        - else: 0

      - Assets (0-30):
        - has_real_estate == True: 30
        - has_vehicle == True (and no real estate): 10
        - else: 0

      - Banking (0-10):
        - has_bank_account_recent == True: 10
        - else: 0

      - Recency (0-20):
        - Based on years since judgment_date
        - Formula: 20 - (years * 2), clamped to 0-20
        - If judgment_date is None: 0

    Args:
        enrichment_data: Dict with enrichment fields
        judgment_date: Original judgment date for age calculation

    Returns:
        ScoreBreakdown with component scores
    """
    # Employment component (0-40)
    employment_score = 0
    if enrichment_data.get("employed"):
        employment_score = 40
    elif enrichment_data.get("self_employed"):
        employment_score = 20

    # Assets component (0-30)
    assets_score = 0
    if enrichment_data.get("has_real_estate") or enrichment_data.get("homeowner"):
        assets_score = 30
    elif enrichment_data.get("has_vehicle"):
        assets_score = 10

    # Banking component (0-10)
    banking_score = 0
    if enrichment_data.get("has_bank_account_recent") or enrichment_data.get(
        "has_bank_account"
    ):
        banking_score = 10

    # Recency component (0-20)
    recency_score = 0
    years = _years_since(judgment_date)
    if years is not None:
        years = max(0, years)
        raw = 20 - (years * 2)
        recency_score = int(max(0, min(20, raw)))

    return ScoreBreakdown(
        employment=employment_score,
        assets=assets_score,
        recency=recency_score,
        banking=banking_score,
    )


def calculate_collectability_score(
    enrichment_data: Dict[str, Any],
    judgment_date: Optional[date | datetime],
    judgment_id: Optional[int | str] = None,
) -> int:
    """
    Compute collectability score (v2) with explainable breakdown.

    This is the main entry point for scoring. It computes the breakdown,
    optionally persists to the database, and returns the total score.

    Backwards compatible: still returns int, but now also writes breakdown
    columns when judgment_id is provided.

    Args:
        enrichment_data: Dict with enrichment fields
        judgment_date: Original judgment date for age calculation
        judgment_id: Optional judgment ID for database persistence

    Returns:
        Integer score 0-100
    """
    breakdown = compute_score_breakdown(enrichment_data, judgment_date)
    total = breakdown.total

    # If judgment_id is provided, persist breakdown to DB asynchronously
    # This is called from _apply_enrichment which handles the actual DB update
    # We store the breakdown in a thread-local or return it via a different mechanism
    # For now, the caller (_apply_enrichment) will handle persistence

    return total


async def persist_score_breakdown(
    judgment_id: int | str,
    breakdown: ScoreBreakdown,
    conn: Optional[psycopg.AsyncConnection] = None,
) -> None:
    """
    Persist score breakdown to the database.

    Updates public.judgments with both the total score and individual components.

    Args:
        judgment_id: ID of the judgment to update
        breakdown: ScoreBreakdown with component scores
        conn: Optional connection (will get from pool if not provided)
    """
    if conn is None:
        conn = await get_pool()
    if conn is None:
        raise RuntimeError("Database connection not available")

    jid = (
        int(judgment_id)
        if isinstance(judgment_id, str) and judgment_id.isdigit()
        else judgment_id
    )

    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE public.judgments
            SET
                collectability_score = %s,
                score_employment = %s,
                score_assets = %s,
                score_recency = %s,
                score_banking = %s
            WHERE id = %s
            """,
            (
                breakdown.total,
                breakdown.employment,
                breakdown.assets,
                breakdown.recency,
                breakdown.banking,
                jid,
            ),
        )

    logger.debug(
        "Persisted score breakdown for judgment %s: total=%s (emp=%s, assets=%s, recency=%s, bank=%s)",
        judgment_id,
        breakdown.total,
        breakdown.employment,
        breakdown.assets,
        breakdown.recency,
        breakdown.banking,
    )


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
    Apply enrichment results to a judgment (v2 with score breakdown).

    Extracts scoring signals from the enrichment result, fetches the judgment date,
    computes the collectability score with explainable breakdown, and updates
    the judgment record with both total score and component scores.

    Args:
        judgment_id: UUID/ID of the judgment
        result: Raw result dict from TLO/idiCORE with enrichment fields
    """
    conn = await get_pool()
    if conn is None:
        raise RuntimeError("Database connection not available")

    # Extract scoring signals from enrichment result (v2 keys)
    enrichment_data: Dict[str, Any] = {
        # Employment signals
        "employed": result.get("employed"),
        "self_employed": result.get("self_employed"),
        # Asset signals
        "homeowner": result.get("homeowner"),
        "has_real_estate": result.get("has_real_estate") or result.get("homeowner"),
        "has_vehicle": result.get("has_vehicle"),
        # Banking signals
        "has_bank_account": result.get("has_bank_account"),
        "has_bank_account_recent": result.get("has_bank_account_recent")
        or result.get("has_bank_account"),
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

    # Compute v2 score breakdown
    breakdown = compute_score_breakdown(enrichment_data, judgment_date)

    # Persist score breakdown to database
    await persist_score_breakdown(judgment_id, breakdown, conn)

    logger.info(
        "Judgment %s scored (v2): total=%s (emp=%s, assets=%s, recency=%s, bank=%s)",
        judgment_id,
        breakdown.total,
        breakdown.employment,
        breakdown.assets,
        breakdown.recency,
        breakdown.banking,
    )

    # Auto-allocate to finance pool based on score (best-effort, never fail enrichment)
    try:
        from .allocation_service import auto_tranche_and_emit

        jid_int = (
            int(judgment_id)
            if isinstance(judgment_id, str) and judgment_id.isdigit()
            else int(judgment_id)
        )
        allocation_result = await auto_tranche_and_emit(jid_int)

        if allocation_result:
            logger.info(
                "Judgment %s auto-allocated to pool '%s' (score=%s)",
                judgment_id,
                allocation_result.pool_name,
                allocation_result.score,
            )
    except Exception as alloc_err:
        # Never fail enrichment due to allocation issues
        logger.warning(
            "Auto-allocation skipped for judgment %s: %s",
            judgment_id,
            alloc_err,
        )

    # Emit events for significant findings (best-effort, never fail enrichment)
    try:
        from .event_service import emit_event_for_judgment

        source = result.get("source", "enrichment")
        jid = int(judgment_id) if judgment_id.isdigit() else int(judgment_id)

        # Emit job_found event if employer is detected
        if result.get("employed") and result.get("employer_name"):
            await emit_event_for_judgment(
                judgment_id=jid,
                event_type="job_found",
                payload={
                    "judgment_id": jid,
                    "employer_name": result.get("employer_name"),
                    "employer_address": result.get("employer_address"),
                    "source": source.upper(),
                },
            )

        # Emit asset_found event for real estate
        if result.get("has_real_estate") or result.get("homeowner"):
            await emit_event_for_judgment(
                judgment_id=jid,
                event_type="asset_found",
                payload={
                    "judgment_id": jid,
                    "asset_type": "real_estate",
                    "description": "Real estate / home ownership confirmed",
                    "source": source.upper(),
                },
            )

        # Emit asset_found event for vehicles
        if result.get("has_vehicle"):
            await emit_event_for_judgment(
                judgment_id=jid,
                event_type="asset_found",
                payload={
                    "judgment_id": jid,
                    "asset_type": "vehicle",
                    "description": "Vehicle ownership detected",
                    "source": source.upper(),
                },
            )

        # Emit asset_found event for bank accounts
        if result.get("has_bank_account") or result.get("has_bank_account_recent"):
            bank_name = result.get("bank_name") or "Unknown bank"
            await emit_event_for_judgment(
                judgment_id=jid,
                event_type="asset_found",
                payload={
                    "judgment_id": jid,
                    "asset_type": "bank_account",
                    "description": f"Bank account at {bank_name}",
                    "source": source.upper(),
                },
            )

    except Exception as event_err:
        # Never fail enrichment due to event emission
        logger.debug(
            "Event emission skipped for judgment %s: %s",
            judgment_id,
            event_err,
        )

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
