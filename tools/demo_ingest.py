#!/usr/bin/env python3
"""
Dragonfly Demo Ingest Tool

Creates synthetic demo data directly into the intake pipeline for the
Golden Path Demo. Generates in-memory CSV-like rows and inserts them
into intake.simplicity_batches and intake.simplicity_validated_rows
with status = 'validated', ready for orchestration.

Usage:
    # Create 50 synthetic demo rows (default)
    python -m tools.demo_ingest --env prod

    # Create 100 rows
    python -m tools.demo_ingest --env prod --rows 100

    # Dry run (show what would be created)
    python -m tools.demo_ingest --env prod --dry-run

Output:
    Prints batch_id on success for downstream orchestration.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("demo_ingest")


# =============================================================================
# SYNTHETIC DATA GENERATORS
# =============================================================================

# First names pool
FIRST_NAMES = [
    "James",
    "Mary",
    "John",
    "Patricia",
    "Robert",
    "Jennifer",
    "Michael",
    "Linda",
    "William",
    "Elizabeth",
    "David",
    "Barbara",
    "Richard",
    "Susan",
    "Joseph",
    "Jessica",
    "Thomas",
    "Sarah",
    "Charles",
    "Karen",
    "Christopher",
    "Nancy",
    "Daniel",
    "Lisa",
    "Matthew",
    "Betty",
    "Anthony",
    "Margaret",
    "Mark",
    "Sandra",
    "Donald",
    "Ashley",
]

# Last names pool
LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
    "Lee",
    "Perez",
    "Thompson",
    "White",
    "Harris",
    "Sanchez",
    "Clark",
    "Ramirez",
    "Lewis",
    "Robinson",
    "Walker",
]

# Court names
COURTS = [
    "Maricopa County Superior Court",
    "Pima County Superior Court",
    "Phoenix Municipal Court",
    "Tucson City Court",
    "Yavapai County Superior Court",
    "Coconino County Superior Court",
    "Pinal County Superior Court",
    "Mohave County Superior Court",
]

# Counties
COUNTIES = [
    "Maricopa",
    "Pima",
    "Pinal",
    "Yavapai",
    "Coconino",
    "Mohave",
    "Yuma",
    "Cochise",
    "Navajo",
    "Apache",
]


def _generate_defendant_name() -> str:
    """Generate a random defendant name."""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    # 30% chance of middle initial
    if random.random() < 0.3:
        middle = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        return f"{first} {middle}. {last}"
    return f"{first} {last}"


def _generate_case_number(index: int) -> str:
    """Generate a unique case number."""
    year = random.randint(2020, 2024)
    court_code = random.choice(["CV", "DC", "CC", "SC"])
    seq = 10000 + index
    return f"{year}-{court_code}-{seq:06d}"


def _generate_amount() -> Decimal:
    """Generate a realistic judgment amount."""
    # Mix of small and large judgments
    if random.random() < 0.6:
        # Small claims: $500 - $10,000
        amount = random.uniform(500, 10000)
    elif random.random() < 0.9:
        # Medium: $10,000 - $50,000
        amount = random.uniform(10000, 50000)
    else:
        # Large: $50,000 - $250,000
        amount = random.uniform(50000, 250000)

    return Decimal(str(round(amount, 2)))


def _generate_date_in_range(days_ago_min: int, days_ago_max: int) -> datetime:
    """Generate a date within a range of days ago."""
    days_ago = random.randint(days_ago_min, days_ago_max)
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def generate_demo_row(index: int) -> Dict[str, Any]:
    """
    Generate a single synthetic demo row.

    Returns a dict with all fields needed for intake.simplicity_validated_rows.
    """
    case_number = _generate_case_number(index)
    defendant_name = _generate_defendant_name()
    amount = _generate_amount()
    entry_date = _generate_date_in_range(30, 365)  # 1 month to 1 year ago
    judgment_date = entry_date + timedelta(
        days=random.randint(7, 90)
    )  # 1 week to 3 months after entry
    court = random.choice(COURTS)
    county = random.choice(COUNTIES)

    return {
        "case_number": case_number,
        "plaintiff_name": "Demo Plaintiff LLC",  # Fixed plaintiff for demo
        "defendant_name": defendant_name,
        "judgment_amount": amount,
        "entry_date": entry_date.date(),
        "judgment_date": judgment_date.date(),
        "court": court,
        "county": county,
    }


def generate_demo_rows(count: int) -> List[Dict[str, Any]]:
    """Generate a list of synthetic demo rows."""
    return [generate_demo_row(i) for i in range(count)]


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================


def get_db_connection() -> psycopg.Connection:
    """Get a database connection using environment configuration."""
    dsn = get_supabase_db_url()
    return psycopg.connect(dsn, row_factory=dict_row)


def create_demo_batch(conn: psycopg.Connection, row_count: int) -> UUID:
    """
    Create a batch record in intake.simplicity_batches.

    Sets status to 'validated' so orchestrator picks it up immediately.
    """
    batch_id = uuid4()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"demo_batch_{timestamp}.csv"
    source_reference = f"demo-{batch_id.hex[:12]}"

    # Generate a unique file hash for idempotency
    hash_input = f"{batch_id}-{timestamp}-{row_count}".encode()
    file_hash = hashlib.sha256(hash_input).hexdigest()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO intake.simplicity_batches (
                id,
                filename,
                source_reference,
                file_hash,
                row_count_total,
                row_count_staged,
                row_count_valid,
                row_count_invalid,
                status,
                created_at,
                staged_at,
                transformed_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                NOW(), NOW(), NOW()
            )
            RETURNING id
            """,
            (
                str(batch_id),
                filename,
                source_reference,
                file_hash,
                row_count,
                row_count,
                row_count,
                0,
                "validated",  # Ready for orchestration
            ),
        )
        result = cur.fetchone()
        return UUID(str(result["id"]))


def insert_validated_rows(
    conn: psycopg.Connection,
    batch_id: UUID,
    rows: List[Dict[str, Any]],
) -> int:
    """
    Insert validated rows into intake.simplicity_validated_rows.

    Returns the count of rows inserted.
    """
    with conn.cursor() as cur:
        for idx, row in enumerate(rows):
            cur.execute(
                """
                INSERT INTO intake.simplicity_validated_rows (
                    batch_id,
                    row_index,
                    case_number,
                    plaintiff_name,
                    defendant_name,
                    judgment_amount,
                    entry_date,
                    judgment_date,
                    court,
                    county,
                    validation_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    str(batch_id),
                    idx,
                    row["case_number"],
                    row["plaintiff_name"],
                    row["defendant_name"],
                    row["judgment_amount"],
                    row["entry_date"],
                    row["judgment_date"],
                    row["court"],
                    row["county"],
                    "valid",
                ),
            )

    return len(rows)


def log_intake_event(
    conn: psycopg.Connection,
    batch_id: UUID,
    event_type: str,
    message: str,
) -> None:
    """Log an event to ops.intake_event_log if it exists."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.intake_event_log (
                    batch_id,
                    event_type,
                    message,
                    created_at
                ) VALUES (%s, %s, %s, NOW())
                """,
                (str(batch_id), event_type, message),
            )
    except psycopg.errors.UndefinedTable:
        # Table doesn't exist, skip logging
        conn.rollback()
    except Exception as e:
        # Non-critical, log and continue
        logger.debug(f"Could not log intake event: {e}")
        conn.rollback()


# =============================================================================
# MAIN LOGIC
# =============================================================================


def run_demo_ingest(
    row_count: int,
    dry_run: bool = False,
) -> Optional[UUID]:
    """
    Run the demo ingest process.

    Args:
        row_count: Number of synthetic rows to generate
        dry_run: If True, show what would be created without writing to DB

    Returns:
        The batch_id if successful, None on failure
    """
    logger.info(f"[demo_ingest] Environment: {get_supabase_env()}")
    logger.info(f"[demo_ingest] Generating {row_count} synthetic demo rows...")

    # Generate synthetic data
    rows = generate_demo_rows(row_count)

    if dry_run:
        logger.info("[demo_ingest] DRY RUN - showing sample rows:")
        for i, row in enumerate(rows[:3]):
            logger.info(
                f"  Row {i}: {row['case_number']} | {row['defendant_name']} | ${row['judgment_amount']}"
            )
        if row_count > 3:
            logger.info(f"  ... and {row_count - 3} more rows")
        return None

    # Insert into database
    try:
        with get_db_connection() as conn:
            # Create batch record
            batch_id = create_demo_batch(conn, row_count)
            logger.info(f"[demo_ingest] Created batch: {batch_id}")

            # Insert validated rows
            inserted = insert_validated_rows(conn, batch_id, rows)
            logger.info(f"[demo_ingest] Inserted {inserted} validated rows")

            # Log event
            log_intake_event(
                conn,
                batch_id,
                "demo_ingest",
                f"Demo batch created with {inserted} synthetic rows",
            )

            conn.commit()

            # Output success
            print("\n✅ Batch Created & Validated")
            print(f"   batch_id: {batch_id}")
            print(f"   rows: {inserted}")
            print("   status: validated")

            return batch_id

    except Exception as e:
        logger.error(f"[demo_ingest] Failed: {e}")
        raise


def main() -> None:
    """Entry point for the demo ingest tool."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic demo data for Golden Path Demo",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=50,
        help="Number of synthetic rows to generate (default: 50)",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Supabase environment (defaults to SUPABASE_MODE)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing to database",
    )
    args = parser.parse_args()

    # Set environment if specified
    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    try:
        batch_id = run_demo_ingest(args.rows, args.dry_run)
        if batch_id:
            # Print batch_id to stdout for script capture
            print(f"\nBATCH_ID={batch_id}")
            sys.exit(0)
        else:
            # Dry run completed
            sys.exit(0)
    except Exception as e:
        logger.error(f"[demo_ingest] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
