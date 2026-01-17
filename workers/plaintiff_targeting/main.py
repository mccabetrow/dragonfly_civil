"""
Plaintiff Targeting Worker

Transforms raw judgments from judgments_raw into scored, prioritized
plaintiff leads in plaintiff_leads table.

This worker:
1. Reads pending judgments from judgments_raw
2. Computes collectability scores using the scoring spec
3. Creates/updates plaintiff_leads with priority tiers
4. Tracks runs in targeting_runs table

EXIT CODES:
    0 = Success
    1 = Failure (recoverable)
    2 = Configuration error (no retry)
    4 = Database unreachable
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

# ============================================================================
# Exit Codes
# ============================================================================

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CONFIG_ERROR = 2
EXIT_DB_UNREACHABLE = 4

# ============================================================================
# Logging
# ============================================================================

logger = logging.getLogger(__name__)


def configure_logging(env: str) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if env == "dev" else logging.INFO
    log_format = "%(asctime)s level=%(levelname)s logger=%(name)s %(message)s"
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stdout,
    )
    for lib in ("httpx", "httpcore", "urllib3", "psycopg"):
        logging.getLogger(lib).setLevel(logging.WARNING)


# ============================================================================
# Configuration
# ============================================================================


@dataclass(frozen=True)
class TargetingConfig:
    """Configuration for the plaintiff targeting worker."""

    database_url: str
    env: str = "dev"
    worker_name: str = "plaintiff_targeting"
    worker_version: str = "1.0.0"

    # Targeting parameters
    batch_size: int = 100
    min_score_threshold: int = 20  # Don't create leads below this score
    source_county: str | None = None  # Filter by county (None = all)
    source_system: str | None = None  # Filter by source (None = all)

    # Only process judgments in these statuses
    source_statuses: tuple[str, ...] = ("pending", "processed")


def load_config() -> TargetingConfig:
    """Load configuration from environment."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    return TargetingConfig(
        database_url=database_url,
        env=os.environ.get("ENV", os.environ.get("SUPABASE_MODE", "dev")),
        batch_size=int(os.environ.get("TARGETING_BATCH_SIZE", "100")),
        min_score_threshold=int(os.environ.get("TARGETING_MIN_SCORE", "20")),
        source_county=os.environ.get("TARGETING_COUNTY"),
        source_system=os.environ.get("TARGETING_SOURCE"),
    )


# ============================================================================
# Database Operations
# ============================================================================


def get_connection(dsn: str) -> psycopg.Connection:
    """Create database connection."""
    conn = psycopg.connect(
        dsn,
        row_factory=dict_row,
        application_name="plaintiff_targeting",
        connect_timeout=10,
    )
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
    return conn


def check_database_health(conn: psycopg.Connection) -> bool:
    """Verify required tables exist."""
    required = ["judgments_raw", "plaintiff_leads", "targeting_runs"]
    with conn.cursor() as cur:
        for table in required:
            try:
                cur.execute(f"SELECT 1 FROM public.{table} LIMIT 1")
            except Exception:
                logger.error("missing_table table=%s", table)
                return False
    return True


def create_targeting_run(
    conn: psycopg.Connection,
    config: TargetingConfig,
) -> UUID:
    """Create a new targeting run record."""
    query = """
        INSERT INTO public.targeting_runs (
            worker_name,
            worker_version,
            source_system,
            source_county,
            min_score_threshold,
            status
        ) VALUES (
            %(worker_name)s,
            %(worker_version)s,
            %(source_system)s,
            %(source_county)s,
            %(min_score)s,
            'running'
        )
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            query,
            {
                "worker_name": config.worker_name,
                "worker_version": config.worker_version,
                "source_system": config.source_system,
                "source_county": config.source_county,
                "min_score": config.min_score_threshold,
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row["id"]


def get_pending_judgments(
    conn: psycopg.Connection,
    config: TargetingConfig,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """
    Fetch judgments that haven't been targeted yet.

    Uses LEFT JOIN to find judgments_raw not yet in plaintiff_leads.
    """
    query = """
        SELECT
            jr.id,
            jr.source_system,
            jr.source_county,
            jr.case_type,
            jr.external_id as case_number,
            jr.raw_payload,
            jr.dedupe_key,
            jr.content_hash,
            jr.judgment_entered_at,
            jr.filed_at
        FROM public.judgments_raw jr
        LEFT JOIN public.plaintiff_leads pl ON pl.source_judgment_id = jr.id
        WHERE pl.id IS NULL
          AND jr.status IN %(statuses)s
    """
    params: dict[str, Any] = {"statuses": config.source_statuses}

    if config.source_county:
        query += " AND jr.source_county = %(county)s"
        params["county"] = config.source_county

    if config.source_system:
        query += " AND jr.source_system = %(source)s"
        params["source"] = config.source_system

    query += " ORDER BY jr.judgment_entered_at DESC NULLS LAST LIMIT %(limit)s"
    params["limit"] = limit

    with conn.cursor() as cur:
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def extract_fields_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Extract structured fields from raw_payload.

    The payload structure depends on the source system.
    This function normalizes various formats into a standard structure.
    """
    # Default empty values
    result = {
        "plaintiff_name": None,
        "plaintiff_address": None,
        "plaintiff_phone": None,
        "plaintiff_email": None,
        "attorney_name": None,
        "attorney_phone": None,
        "attorney_email": None,
        "debtor_name": None,
        "debtor_address": None,
        "employer_name": None,
        "judgment_amount": None,
    }

    if not payload:
        return result

    # Try various field mappings
    # Plaintiff/Creditor
    for key in ["plaintiff", "creditor", "plaintiff_name", "creditor_name"]:
        if key in payload and payload[key]:
            result["plaintiff_name"] = payload[key]
            break

    # Defendant/Debtor
    for key in ["defendant", "debtor", "defendant_name", "debtor_name"]:
        if key in payload and payload[key]:
            result["debtor_name"] = payload[key]
            break

    # Judgment amount
    for key in ["judgment_amount", "amount", "principal", "total_judgment"]:
        if key in payload and payload[key]:
            try:
                # Handle currency strings like "$1,234.56"
                amount_str = str(payload[key]).replace("$", "").replace(",", "")
                result["judgment_amount"] = float(amount_str)
            except (ValueError, TypeError):
                pass
            break

    # Addresses
    result["plaintiff_address"] = payload.get("plaintiff_address") or payload.get(
        "creditor_address"
    )
    result["debtor_address"] = payload.get("defendant_address") or payload.get("debtor_address")

    # Contact info
    result["plaintiff_phone"] = payload.get("plaintiff_phone") or payload.get("creditor_phone")
    result["plaintiff_email"] = payload.get("plaintiff_email") or payload.get("creditor_email")

    # Attorney
    result["attorney_name"] = (
        payload.get("attorney") or payload.get("attorney_name") or payload.get("plaintiff_attorney")
    )
    result["attorney_phone"] = payload.get("attorney_phone")
    result["attorney_email"] = payload.get("attorney_email")

    # Employer
    result["employer_name"] = payload.get("employer") or payload.get("employer_name")

    return result


def determine_debtor_type(debtor_name: str | None) -> str:
    """Determine if debtor is business, DBA, individual, or unknown."""
    if not debtor_name:
        return "unknown"

    name_upper = debtor_name.upper()

    # Business indicators
    if any(
        ind in name_upper for ind in ["LLC", "INC", "CORP", "LP", "LLP", "CORPORATION", "LIMITED"]
    ):
        return "business"

    # DBA indicators
    if any(ind in name_upper for ind in ["DBA", "D/B/A", "TRADING AS", "T/A"]):
        return "dba"

    # Business-like names
    if any(
        ind in name_upper
        for ind in [
            "SERVICES",
            "ENTERPRISES",
            "HOLDINGS",
            "MANAGEMENT",
            "CONSTRUCTION",
            "REALTY",
            "PROPERTIES",
        ]
    ):
        return "business"

    return "individual"


def compute_score_for_judgment(
    conn: psycopg.Connection,
    judgment: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute collectability score using the database function.

    Returns score components and priority tier.
    """
    query = """
        SELECT * FROM public.compute_collectability_score(
            %(amount)s::numeric,
            %(judgment_date)s::date,
            %(debtor_name)s,
            %(debtor_address)s,
            %(plaintiff_phone)s,
            %(plaintiff_email)s,
            %(attorney_name)s,
            %(employer_name)s,
            %(raw_payload)s::jsonb
        )
    """

    judgment_date = judgment.get("judgment_entered_at")
    if judgment_date and hasattr(judgment_date, "date"):
        judgment_date = judgment_date.date()
    elif judgment_date and hasattr(judgment_date, "isoformat"):
        judgment_date = judgment_date
    else:
        judgment_date = None

    with conn.cursor() as cur:
        cur.execute(
            query,
            {
                "amount": fields.get("judgment_amount"),
                "judgment_date": judgment_date,
                "debtor_name": fields.get("debtor_name"),
                "debtor_address": fields.get("debtor_address"),
                "plaintiff_phone": fields.get("plaintiff_phone"),
                "plaintiff_email": fields.get("plaintiff_email"),
                "attorney_name": fields.get("attorney_name"),
                "employer_name": fields.get("employer_name"),
                "raw_payload": Json(judgment.get("raw_payload", {})),
            },
        )
        row = cur.fetchone()

    return (
        dict(row)
        if row
        else {
            "total_score": 0,
            "amount_score": 0,
            "recency_score": 0,
            "debtor_type_score": 0,
            "address_score": 0,
            "contact_score": 0,
            "asset_signal_score": 0,
            "priority_tier": "F",
        }
    )


def insert_plaintiff_lead(
    conn: psycopg.Connection,
    judgment: dict[str, Any],
    fields: dict[str, Any],
    score: dict[str, Any],
    run_id: UUID,
) -> tuple[bool, bool]:
    """
    Insert or update a plaintiff lead.

    Returns (inserted: bool, updated: bool).
    Uses ON CONFLICT to handle idempotency.
    """
    query = """
        INSERT INTO public.plaintiff_leads (
            source_judgment_id,
            source_system,
            source_county,
            case_number,
            case_type,
            plaintiff_name,
            plaintiff_address,
            plaintiff_phone,
            plaintiff_email,
            attorney_name,
            attorney_phone,
            attorney_email,
            debtor_name,
            debtor_address,
            debtor_type,
            employer_name,
            judgment_amount,
            judgment_entered_at,
            filed_at,
            collectability_score,
            priority_tier,
            score_amount,
            score_recency,
            score_debtor_type,
            score_address,
            score_contact,
            score_asset_signals,
            targeting_run_id,
            raw_payload,
            dedupe_key,
            content_hash
        ) VALUES (
            %(source_judgment_id)s,
            %(source_system)s,
            %(source_county)s,
            %(case_number)s,
            %(case_type)s,
            %(plaintiff_name)s,
            %(plaintiff_address)s,
            %(plaintiff_phone)s,
            %(plaintiff_email)s,
            %(attorney_name)s,
            %(attorney_phone)s,
            %(attorney_email)s,
            %(debtor_name)s,
            %(debtor_address)s,
            %(debtor_type)s,
            %(employer_name)s,
            %(judgment_amount)s,
            %(judgment_entered_at)s,
            %(filed_at)s,
            %(score)s,
            %(tier)s,
            %(score_amount)s,
            %(score_recency)s,
            %(score_debtor_type)s,
            %(score_address)s,
            %(score_contact)s,
            %(score_asset_signals)s,
            %(run_id)s,
            %(raw_payload)s,
            %(dedupe_key)s,
            %(content_hash)s
        )
        ON CONFLICT (dedupe_key) DO UPDATE SET
            collectability_score = EXCLUDED.collectability_score,
            priority_tier = EXCLUDED.priority_tier,
            score_amount = EXCLUDED.score_amount,
            score_recency = EXCLUDED.score_recency,
            score_debtor_type = EXCLUDED.score_debtor_type,
            score_address = EXCLUDED.score_address,
            score_contact = EXCLUDED.score_contact,
            score_asset_signals = EXCLUDED.score_asset_signals,
            targeting_run_id = EXCLUDED.targeting_run_id,
            scored_at = now(),
            updated_at = now()
        RETURNING (xmax = 0) as inserted
    """

    # Handle dates
    judgment_date = judgment.get("judgment_entered_at")
    if judgment_date and hasattr(judgment_date, "date"):
        judgment_date = judgment_date.date()

    filed_date = judgment.get("filed_at")
    if filed_date and hasattr(filed_date, "date"):
        filed_date = filed_date.date()

    params = {
        "source_judgment_id": judgment["id"],
        "source_system": judgment.get("source_system"),
        "source_county": judgment.get("source_county"),
        "case_number": judgment.get("case_number"),
        "case_type": judgment.get("case_type"),
        "plaintiff_name": fields.get("plaintiff_name") or "Unknown Plaintiff",
        "plaintiff_address": fields.get("plaintiff_address"),
        "plaintiff_phone": fields.get("plaintiff_phone"),
        "plaintiff_email": fields.get("plaintiff_email"),
        "attorney_name": fields.get("attorney_name"),
        "attorney_phone": fields.get("attorney_phone"),
        "attorney_email": fields.get("attorney_email"),
        "debtor_name": fields.get("debtor_name") or "Unknown Debtor",
        "debtor_address": fields.get("debtor_address"),
        "debtor_type": determine_debtor_type(fields.get("debtor_name")),
        "employer_name": fields.get("employer_name"),
        "judgment_amount": fields.get("judgment_amount"),
        "judgment_entered_at": judgment_date,
        "filed_at": filed_date,
        "score": score["total_score"],
        "tier": score["priority_tier"],
        "score_amount": score["amount_score"],
        "score_recency": score["recency_score"],
        "score_debtor_type": score["debtor_type_score"],
        "score_address": score["address_score"],
        "score_contact": score["contact_score"],
        "score_asset_signals": score["asset_signal_score"],
        "run_id": run_id,
        "raw_payload": Json(judgment.get("raw_payload", {})),
        "dedupe_key": judgment["dedupe_key"],
        "content_hash": judgment.get("content_hash"),
    }

    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()

    inserted = row["inserted"] if row else False
    return (inserted, not inserted)


def update_targeting_run(
    conn: psycopg.Connection,
    run_id: UUID,
    evaluated: int,
    created: int,
    updated: int,
    skipped: int,
    status: str = "completed",
    error_message: str | None = None,
) -> None:
    """Update targeting run with final stats."""
    query = """
        UPDATE public.targeting_runs
        SET
            finished_at = now(),
            judgments_evaluated = %(evaluated)s,
            leads_created = %(created)s,
            leads_updated = %(updated)s,
            leads_skipped = %(skipped)s,
            status = %(status)s,
            error_message = %(error)s
        WHERE id = %(run_id)s
    """
    with conn.cursor() as cur:
        cur.execute(
            query,
            {
                "run_id": run_id,
                "evaluated": evaluated,
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "status": status,
                "error": error_message,
            },
        )
    conn.commit()


# ============================================================================
# Main Orchestrator
# ============================================================================


def run_sync() -> int:
    """
    Main entry point for the plaintiff targeting worker.

    Returns exit code (0-4).
    """
    config: TargetingConfig | None = None
    conn: psycopg.Connection | None = None
    run_id: UUID | None = None

    stats = {
        "evaluated": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
    }

    try:
        # =================================================================
        # STEP 1: Load Configuration
        # =================================================================
        try:
            config = load_config()
            configure_logging(config.env)
        except Exception as e:
            print(f"FATAL config_error={e}", file=sys.stderr)
            return EXIT_CONFIG_ERROR

        logger.info(
            "worker_start worker=%s version=%s env=%s",
            config.worker_name,
            config.worker_version,
            config.env,
        )

        # =================================================================
        # STEP 2: Connect to Database
        # =================================================================
        try:
            conn = get_connection(config.database_url)
            logger.info("db_connected application_name=%s", config.worker_name)
        except Exception as e:
            logger.critical("db_connection_failed error=%s", str(e)[:200])
            return EXIT_DB_UNREACHABLE

        if not check_database_health(conn):
            logger.critical("db_health_failed")
            return EXIT_DB_UNREACHABLE

        # =================================================================
        # STEP 3: Create Targeting Run
        # =================================================================
        run_id = create_targeting_run(conn, config)
        logger.info("targeting_run_created run_id=%s", run_id)

        # =================================================================
        # STEP 4: Fetch Pending Judgments
        # =================================================================
        judgments = get_pending_judgments(conn, config, limit=config.batch_size * 10)
        logger.info("judgments_fetched count=%d", len(judgments))

        if not judgments:
            logger.info("no_pending_judgments")
            update_targeting_run(conn, run_id, 0, 0, 0, 0)
            return EXIT_SUCCESS

        # =================================================================
        # STEP 5: Process Each Judgment
        # =================================================================
        for judgment in judgments:
            try:
                stats["evaluated"] += 1

                # Extract fields from raw payload
                fields = extract_fields_from_payload(judgment.get("raw_payload", {}))

                # Skip if no plaintiff or debtor
                if not fields.get("plaintiff_name") and not fields.get("debtor_name"):
                    logger.debug(
                        "skip_incomplete judgment_id=%s reason=missing_parties",
                        judgment["id"],
                    )
                    stats["skipped"] += 1
                    continue

                # Compute collectability score
                score = compute_score_for_judgment(conn, judgment, fields)

                # Skip if below threshold
                if score["total_score"] < config.min_score_threshold:
                    logger.debug(
                        "skip_low_score judgment_id=%s score=%d threshold=%d",
                        judgment["id"],
                        score["total_score"],
                        config.min_score_threshold,
                    )
                    stats["skipped"] += 1
                    continue

                # Insert/update lead
                inserted, updated = insert_plaintiff_lead(conn, judgment, fields, score, run_id)

                if inserted:
                    stats["created"] += 1
                elif updated:
                    stats["updated"] += 1

                if stats["evaluated"] % 100 == 0:
                    logger.info(
                        "progress evaluated=%d created=%d updated=%d skipped=%d",
                        stats["evaluated"],
                        stats["created"],
                        stats["updated"],
                        stats["skipped"],
                    )
                    conn.commit()

            except Exception as e:
                logger.warning(
                    "judgment_error judgment_id=%s error=%s",
                    judgment.get("id"),
                    str(e)[:100],
                )
                stats["skipped"] += 1

        # Final commit
        conn.commit()

        # =================================================================
        # STEP 6: Finalize Run
        # =================================================================
        update_targeting_run(
            conn,
            run_id,
            stats["evaluated"],
            stats["created"],
            stats["updated"],
            stats["skipped"],
        )

        logger.info(
            "worker_complete run_id=%s evaluated=%d created=%d updated=%d skipped=%d",
            run_id,
            stats["evaluated"],
            stats["created"],
            stats["updated"],
            stats["skipped"],
        )

        return EXIT_SUCCESS

    except Exception as e:
        logger.exception(
            "unhandled_exception error=%s type=%s",
            str(e)[:500],
            type(e).__name__,
        )

        if conn and run_id:
            try:
                update_targeting_run(
                    conn,
                    run_id,
                    stats["evaluated"],
                    stats["created"],
                    stats["updated"],
                    stats["skipped"],
                    status="failed",
                    error_message=str(e)[:500],
                )
            except Exception:
                pass

        return EXIT_FAILURE

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        logger.info("worker_shutdown")


async def run() -> int:
    """Async wrapper for compatibility."""
    return run_sync()


def main() -> int:
    """CLI entry point."""
    return run_sync()


if __name__ == "__main__":
    sys.exit(main())
