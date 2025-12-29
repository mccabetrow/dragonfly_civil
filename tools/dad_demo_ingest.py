#!/usr/bin/env python3
"""
Dragonfly Dad Demo Ingest Tool

Creates synthetic demo data for the "Dad Demo" - a visual, impressive
demonstration for non-technical audiences. Generates realistic-looking
judgment data and inserts directly into public.judgments.

Data Format:
    - case_number: 2024-CV-[5-digit random]
    - defendant_name: Realistic company names (e.g., "Apex Construction LLC")
    - judgment_amount: Random between $5k and $150k

Usage:
    python -m tools.dad_demo_ingest --count 50
    python -m tools.dad_demo_ingest --env prod --count 100

Output:
    ✅ Batch [ID] Ready for Orchestration
    💰 Total Value Ingested: $X,XXX,XXX.XX
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

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
    "Inc.",
    "Corp.",
    "Holdings",
    "Enterprises",
    "Group",
    "Partners",
    "Services",
    "Industries",
    "Ventures",
    "Co.",
]

# Realistic company name bases
COMPANY_NAMES = [
    "Apex Construction",
    "Smith Logistics",
    "Western Property",
    "Pacific Development",
    "Metro Builders",
    "Valley Transport",
    "Southwest Contractors",
    "Desert Properties",
    "Mountain View Homes",
    "Sunrise Real Estate",
    "Canyon Materials",
    "Heritage Development",
    "Premier Roofing",
    "Atlas Moving",
    "Phoenix Renovations",
    "Summit Electric",
    "Titan Plumbing",
    "Horizon Landscaping",
    "Liberty Construction",
    "Eagle Transport",
]

# Arizona courts for realism
COURTS = [
    "Maricopa County Superior Court",
    "Pima County Superior Court",
    "Pinal County Superior Court",
    "Yavapai County Superior Court",
    "Mohave County Superior Court",
]


def generate_case_number() -> str:
    """Generate case number: 2024-CV-[5-digit random]"""
    year = random.choice([2023, 2024, 2025])
    random_part = random.randint(10000, 99999)
    return f"{year}-CV-{random_part}"


def generate_defendant_name() -> str:
    """Generate realistic defendant: e.g., 'Apex Construction LLC'"""
    company = random.choice(COMPANY_NAMES)
    suffix = random.choice(CORP_SUFFIXES)
    return f"{company} {suffix}"


def generate_amount() -> Decimal:
    """Generate random amount between $5k and $150k"""
    amount = random.uniform(5000, 150000)
    return Decimal(str(round(amount, 2)))


def generate_entry_date() -> date:
    """Generate random entry date within past 2 years"""
    days_ago = random.randint(30, 730)
    return date.today() - timedelta(days=days_ago)


def generate_judgment_row() -> dict[str, Any]:
    """
    Generate a single synthetic judgment row matching public.judgments schema.
    """
    court = random.choice(COURTS)
    county = court.split(" County")[0]  # Extract county name

    return {
        "case_number": generate_case_number(),
        "plaintiff_name": "Arizona Demo Collections LLC",
        "defendant_name": generate_defendant_name(),
        "judgment_amount": float(generate_amount()),
        "entry_date": generate_entry_date(),
        "judgment_date": generate_entry_date(),
        "court": court,
        "county": county,
        "status": "active",
        "enforcement_stage": "pre_enforcement",
        "source_file": "dad_demo_ingest",
    }


def generate_judgment_rows(count: int) -> list[dict[str, Any]]:
    """Generate a list of synthetic judgment rows."""
    return [generate_judgment_row() for _ in range(count)]


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================


def get_db_connection() -> psycopg.Connection[Any]:
    """Get a database connection using environment configuration."""
    dsn = get_supabase_db_url()
    return psycopg.connect(dsn, row_factory=dict_row)


def insert_judgments(
    conn: psycopg.Connection[Any],
    rows: list[dict[str, Any]],
) -> int:
    """
    Insert judgments into public.judgments.

    Uses ON CONFLICT to handle duplicate case_numbers gracefully.
    Returns the count of rows inserted.
    """
    inserted = 0

    with conn.cursor() as cur:
        for row in rows:
            try:
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        judgment_date,
                        court,
                        county,
                        status,
                        enforcement_stage,
                        source_file
                    ) VALUES (
                        %(case_number)s,
                        %(plaintiff_name)s,
                        %(defendant_name)s,
                        %(judgment_amount)s,
                        %(entry_date)s,
                        %(judgment_date)s,
                        %(court)s,
                        %(county)s,
                        %(status)s,
                        %(enforcement_stage)s,
                        %(source_file)s
                    )
                    ON CONFLICT (case_number) DO NOTHING
                    """,
                    row,
                )
                if cur.rowcount > 0:
                    inserted += 1
            except Exception as e:
                print(f"   ⚠️ Skipped row: {e}")

    return inserted


def calculate_total_value(rows: list[dict[str, Any]]) -> Decimal:
    """Calculate the total judgment value from all rows."""
    total = Decimal("0")
    for row in rows:
        amount = row.get("judgment_amount", 0)
        total += Decimal(str(amount))
    return total


# =============================================================================
# MAIN LOGIC
# =============================================================================


def run_dad_demo_ingest(row_count: int) -> str:
    """
    Run the Dad Demo ingest process.

    Args:
        row_count: Number of synthetic rows to generate

    Returns:
        A batch identifier string on success
    """
    env = get_supabase_env()
    batch_id = uuid4().hex[:12]

    print("\n🐉 DRAGONFLY DAD DEMO INGEST")
    print(f"   Environment: {env}")
    print(f"   Generating {row_count} synthetic judgments...")
    print()

    # Generate synthetic data
    rows = generate_judgment_rows(row_count)
    total_value = calculate_total_value(rows)

    # Insert into database
    with get_db_connection() as conn:
        inserted = insert_judgments(conn, rows)
        conn.commit()

        # Output success
        print(f"✅ Batch [{batch_id}] Ready for Orchestration")
        print(f"   Rows inserted: {inserted}/{row_count}")
        print("   Target: public.judgments")
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
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
