#!/usr/bin/env python3
"""
Dragonfly Dad Demo Ingest Tool

Creates synthetic demo data for the "Dad Demo" - a visual, impressive
demonstration for non-technical audiences. Generates realistic-looking
judgment data and inserts it into the intake pipeline.

Data Format:
    - file_number: IDX-2025-[RANDOM]
    - defendant: Demo Corp [RANDOM] LLC
    - amount: Random float between $5k and $150k

Usage:
    python -m tools.dad_demo_ingest --count 50
    python -m tools.dad_demo_ingest --env prod --count 100

Output:
    ✅ Batch [ID] created.
    💰 Total Value Ingested: $X,XXX,XXX.XX
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# =============================================================================
# SYNTHETIC DATA GENERATORS
# =============================================================================

# Corporation suffixes for defendant names
CORP_SUFFIXES = [
    "LLC",
    "Inc",
    "Corp",
    "Holdings",
    "Enterprises",
    "Group",
    "Partners",
    "Solutions",
    "Industries",
    "Ventures",
]

# Industry words for company names
INDUSTRY_WORDS = [
    "Capital",
    "Financial",
    "Property",
    "Real Estate",
    "Consulting",
    "Tech",
    "Digital",
    "Global",
    "Premier",
    "Elite",
    "Strategic",
    "Dynamic",
    "Apex",
    "Summit",
    "Horizon",
    "Phoenix",
    "Atlas",
    "Titan",
    "Vertex",
    "Nexus",
]


def generate_file_number(index: int) -> str:
    """Generate file number: IDX-2025-[RANDOM]"""
    random_part = random.randint(10000, 99999)
    return f"IDX-2025-{random_part}"


def generate_defendant_name() -> str:
    """Generate defendant: Demo Corp [RANDOM] LLC"""
    industry = random.choice(INDUSTRY_WORDS)
    suffix = random.choice(CORP_SUFFIXES)
    number = random.randint(100, 999)
    return f"Demo {industry} {number} {suffix}"


def generate_amount() -> Decimal:
    """Generate random amount between $5k and $150k"""
    amount = random.uniform(5000, 150000)
    return Decimal(str(round(amount, 2)))


def generate_demo_row(index: int) -> Dict[str, Any]:
    """
    Generate a single synthetic demo row.

    Returns a dict matching the JSONB raw_data format for simplicity_raw_rows.
    """
    file_number = generate_file_number(index)
    defendant = generate_defendant_name()
    amount = generate_amount()

    # Format as raw CSV data (JSONB)
    return {
        "File Number": file_number,
        "Defendant Name": defendant,
        "Judgment Amount": str(amount),
        "Plaintiff Name": "Arizona Demo Collections LLC",
        "Entry Date": datetime.now(timezone.utc).strftime("%m/%d/%Y"),
        "Court": "Maricopa County Superior Court",
        "County": "Maricopa",
        "Case Status": "Active",
    }


def generate_demo_rows(count: int) -> List[Dict[str, Any]]:
    """Generate a list of synthetic demo rows."""
    return [generate_demo_row(i) for i in range(count)]


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================


def get_db_connection() -> psycopg.Connection[Any]:
    """Get a database connection using environment configuration."""
    dsn = get_supabase_db_url()
    return psycopg.connect(dsn, row_factory=dict_row)


def create_demo_batch(conn: psycopg.Connection[Any], row_count: int) -> UUID:
    """
    Create a batch record in intake.simplicity_batches.

    Sets status to 'validated' so orchestrator picks it up immediately.
    """
    batch_id = uuid4()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"dad_demo_{timestamp}.csv"
    source_reference = f"dad-demo-{batch_id.hex[:12]}"

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
                "completed",  # Use 'completed' status for demo (skips orchestrator)
            ),
        )
        result = cur.fetchone()
        if result is None:
            raise RuntimeError("Failed to create batch - no result returned")
        # result is a dict due to dict_row factory
        return UUID(str(result["id"]))  # type: ignore[index]


def insert_raw_rows(
    conn: psycopg.Connection[Any],
    batch_id: UUID,
    rows: List[Dict[str, Any]],
) -> int:
    """
    Bulk insert rows into intake.simplicity_raw_rows.

    Returns the count of rows inserted.
    """
    import json

    with conn.cursor() as cur:
        # Use executemany for bulk insert
        insert_data = [(str(batch_id), idx, json.dumps(row)) for idx, row in enumerate(rows)]

        cur.executemany(
            """
            INSERT INTO intake.simplicity_raw_rows (
                batch_id,
                row_index,
                raw_data
            ) VALUES (%s, %s, %s)
            """,
            insert_data,
        )

    return len(rows)


def calculate_total_value(rows: List[Dict[str, Any]]) -> Decimal:
    """Calculate the total judgment value from all rows."""
    total = Decimal("0")
    for row in rows:
        amount_str = row.get("Judgment Amount", "0")
        try:
            total += Decimal(amount_str)
        except Exception:
            pass
    return total


# =============================================================================
# MAIN LOGIC
# =============================================================================


def run_dad_demo_ingest(row_count: int) -> UUID:
    """
    Run the Dad Demo ingest process.

    Args:
        row_count: Number of synthetic rows to generate

    Returns:
        The batch_id on success
    """
    env = get_supabase_env()
    print("\n🐉 DRAGONFLY DAD DEMO INGEST")
    print(f"   Environment: {env}")
    print(f"   Generating {row_count} synthetic judgments...")
    print()

    # Generate synthetic data
    rows = generate_demo_rows(row_count)
    total_value = calculate_total_value(rows)

    # Insert into database
    with get_db_connection() as conn:
        # Create batch record
        batch_id = create_demo_batch(conn, row_count)

        # Insert raw rows
        inserted = insert_raw_rows(conn, batch_id, rows)

        conn.commit()

        # Output success
        print(f"✅ Batch {batch_id} created.")
        print(f"   Rows inserted: {inserted}")
        print("   Status: completed")
        print()
        print(f"💰 Total Value Ingested: ${total_value:,.2f}")
        print()

        return batch_id


def main() -> None:
    """Entry point for the Dad Demo ingest tool."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic demo data for Dad Demo",
    )
    parser.add_argument(
        "--count",
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
    args = parser.parse_args()

    # Set environment if specified
    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    try:
        batch_id = run_dad_demo_ingest(args.count)
        # Print batch_id on its own line for script capture
        print(f"BATCH_ID={batch_id}")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Dad Demo Ingest Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
