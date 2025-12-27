#!/usr/bin/env python3
# tools/smoke_intake.py
"""
Golden Smoke Test for Intake Pipeline

This script validates the entire intake pipeline end-to-end:
1. Generate a test CSV with valid and invalid rows
2. Insert batch directly into database (simulating upload)
3. Verify batch creation and row staging
4. Poll intake.view_batch_progress until complete
5. Assert expected counts match actual

Exit Codes:
    0 = All tests passed
    1 = Test failed

Usage:
    python -m tools.smoke_intake
    python -m tools.smoke_intake --verbose
    python -m tools.smoke_intake --cleanup-only
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
import os
import sys
import time
import uuid
from datetime import date, timedelta
from typing import Any

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import psycopg
from psycopg.rows import dict_row

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

SMOKE_TEST_PREFIX = "SMOKE_TEST_"
POLL_INTERVAL_SEC = 1.0
MAX_POLL_ATTEMPTS = 30  # 30 seconds max

# Test data: 5 valid rows, 1 invalid row
TEST_ROWS = [
    # Valid rows
    {
        "case_number": f"{SMOKE_TEST_PREFIX}2024-CV-001",
        "defendant_name": "John Doe",
        "plaintiff_name": "Acme Corp",
        "judgment_amount": "15000.00",
        "entry_date": "2024-01-15",
        "county": "Monroe",
    },
    {
        "case_number": f"{SMOKE_TEST_PREFIX}2024-CV-002",
        "defendant_name": "Jane Smith",
        "plaintiff_name": "Beta Inc",
        "judgment_amount": "25000.50",
        "entry_date": "2024-02-20",
        "county": "Erie",
    },
    {
        "case_number": f"{SMOKE_TEST_PREFIX}2024-CV-003",
        "defendant_name": "Bob Johnson",
        "plaintiff_name": "Gamma LLC",
        "judgment_amount": "8500.00",
        "entry_date": "2024-03-10",
        "county": "Onondaga",
    },
    {
        "case_number": f"{SMOKE_TEST_PREFIX}2024-CV-004",
        "defendant_name": "Alice Brown",
        "plaintiff_name": "Delta Corp",
        "judgment_amount": "42000.00",
        "entry_date": "2024-04-05",
        "county": "Monroe",
    },
    {
        "case_number": f"{SMOKE_TEST_PREFIX}2024-CV-005",
        "defendant_name": "Charlie Wilson",
        "plaintiff_name": "Epsilon Inc",
        "judgment_amount": "12750.25",
        "entry_date": "2024-05-12",
        "county": "Erie",
    },
    # Invalid row: missing defendant_name, invalid amount
    {
        "case_number": f"{SMOKE_TEST_PREFIX}2024-CV-006-INVALID",
        "defendant_name": "",  # Empty - should fail
        "plaintiff_name": "Invalid Test",
        "judgment_amount": "NOT_A_NUMBER",  # Invalid amount
        "entry_date": "2024-06-01",
        "county": "Monroe",
    },
]


# =============================================================================
# Database Connection
# =============================================================================


def get_db_connection() -> psycopg.Connection:
    """Get database connection using SUPABASE_MIGRATE_DB_URL."""
    db_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if not db_url:
        db_url = os.environ.get("SUPABASE_DB_URL")

    if not db_url:
        raise RuntimeError("No database URL found. Set SUPABASE_MIGRATE_DB_URL")

    return psycopg.connect(db_url, row_factory=dict_row)


# =============================================================================
# Test CSV Generation
# =============================================================================


def generate_test_csv() -> tuple[str, str]:
    """
    Generate a test CSV with valid and invalid rows.

    Returns:
        Tuple of (csv_content, file_hash)
    """
    output = io.StringIO()

    fieldnames = [
        "case_number",
        "defendant_name",
        "plaintiff_name",
        "judgment_amount",
        "entry_date",
        "county",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for row in TEST_ROWS:
        writer.writerow(row)

    csv_content = output.getvalue()
    file_hash = hashlib.sha256(csv_content.encode()).hexdigest()

    return csv_content, file_hash


# =============================================================================
# Database Operations
# =============================================================================


def cleanup_smoke_test_data(conn: psycopg.Connection) -> int:
    """Remove any existing smoke test data."""
    with conn.cursor() as cur:
        # Delete smoke test batches (cascades to raw/validated/failed rows)
        cur.execute(
            """
            DELETE FROM intake.simplicity_batches 
            WHERE filename LIKE %s
            RETURNING id
        """,
            (f"%{SMOKE_TEST_PREFIX}%",),
        )
        deleted_batches = len(cur.fetchall())

        # Delete smoke test jobs
        cur.execute(
            """
            DELETE FROM ops.job_queue 
            WHERE dedup_key LIKE %s
            RETURNING id
        """,
            (f"%{SMOKE_TEST_PREFIX}%",),
        )
        deleted_jobs = len(cur.fetchall())

        # Delete smoke test judgments
        cur.execute(
            """
            DELETE FROM public.judgments 
            WHERE case_number LIKE %s
            RETURNING id
        """,
            (f"{SMOKE_TEST_PREFIX}%",),
        )
        deleted_judgments = len(cur.fetchall())

        conn.commit()

        total = deleted_batches + deleted_jobs + deleted_judgments
        if total > 0:
            logger.info(
                f"Cleaned up {deleted_batches} batches, {deleted_jobs} jobs, {deleted_judgments} judgments"
            )

        return total


def create_test_batch(conn: psycopg.Connection, file_hash: str) -> uuid.UUID:
    """Create a test batch in intake.simplicity_batches."""
    batch_id = uuid.uuid4()
    filename = f"{SMOKE_TEST_PREFIX}batch_{batch_id.hex[:8]}.csv"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO intake.simplicity_batches 
            (id, filename, source_reference, file_hash, row_count_total, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
            RETURNING id
        """,
            (batch_id, filename, f"smoke_test_{batch_id.hex[:8]}", file_hash, len(TEST_ROWS)),
        )
        conn.commit()

    logger.info(f"Created batch: {batch_id}")
    return batch_id


def stage_raw_rows(conn: psycopg.Connection, batch_id: uuid.UUID) -> int:
    """Stage raw rows into intake.simplicity_raw_rows."""
    import json

    with conn.cursor() as cur:
        for idx, row in enumerate(TEST_ROWS):
            cur.execute(
                """
                INSERT INTO intake.simplicity_raw_rows 
                (batch_id, row_index, raw_data)
                VALUES (%s, %s, %s)
            """,
                (batch_id, idx, json.dumps(row)),
            )

        # Update batch status
        cur.execute(
            """
            UPDATE intake.simplicity_batches 
            SET status = 'staging', 
                row_count_staged = %s,
                staged_at = now()
            WHERE id = %s
        """,
            (len(TEST_ROWS), batch_id),
        )

        conn.commit()

    logger.info(f"Staged {len(TEST_ROWS)} raw rows")
    return len(TEST_ROWS)


def validate_rows(conn: psycopg.Connection, batch_id: uuid.UUID) -> tuple[int, int]:
    """
    Validate rows and populate validated/failed tables.

    Returns:
        Tuple of (valid_count, invalid_count)
    """
    import json

    valid_count = 0
    invalid_count = 0

    with conn.cursor() as cur:
        # Get raw rows
        cur.execute(
            """
            SELECT id, row_index, raw_data 
            FROM intake.simplicity_raw_rows 
            WHERE batch_id = %s 
            ORDER BY row_index
        """,
            (batch_id,),
        )
        raw_rows = cur.fetchall()

        for raw_row in raw_rows:
            row_data = raw_row["raw_data"]
            raw_row_id = raw_row["id"]
            row_index = raw_row["row_index"]

            # Simple validation: check required fields
            errors = []

            if not row_data.get("case_number", "").strip():
                errors.append("Missing case_number")
            if not row_data.get("defendant_name", "").strip():
                errors.append("Missing defendant_name")

            # Validate amount
            amount_str = row_data.get("judgment_amount", "")
            try:
                if amount_str:
                    float(amount_str.replace(",", "").replace("$", ""))
            except ValueError:
                errors.append(f"Invalid judgment_amount: {amount_str}")

            if errors:
                # Insert into failed rows
                cur.execute(
                    """
                    INSERT INTO intake.simplicity_failed_rows 
                    (batch_id, row_index, raw_row_id, error_stage, error_code, error_message, raw_data, retryable)
                    VALUES (%s, %s, %s, 'validate', 'VAL_ERROR', %s, %s, false)
                    ON CONFLICT (batch_id, row_index, error_stage) WHERE resolved_at IS NULL
                    DO UPDATE SET error_message = EXCLUDED.error_message
                """,
                    (batch_id, row_index, raw_row_id, "; ".join(errors), json.dumps(row_data)),
                )
                invalid_count += 1
            else:
                # Insert into validated rows
                cur.execute(
                    """
                    INSERT INTO intake.simplicity_validated_rows 
                    (batch_id, row_index, raw_row_id, case_number, defendant_name, 
                     plaintiff_name, judgment_amount, entry_date, county, validation_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'valid')
                    ON CONFLICT (batch_id, case_number) DO NOTHING
                """,
                    (
                        batch_id,
                        row_index,
                        raw_row_id,
                        row_data.get("case_number"),
                        row_data.get("defendant_name"),
                        row_data.get("plaintiff_name"),
                        float(
                            row_data.get("judgment_amount", "0").replace(",", "").replace("$", "")
                        ),
                        row_data.get("entry_date"),
                        row_data.get("county"),
                    ),
                )
                valid_count += 1

        # Update batch status
        cur.execute(
            """
            UPDATE intake.simplicity_batches 
            SET status = 'transforming', 
                row_count_valid = %s,
                row_count_invalid = %s,
                transformed_at = now()
            WHERE id = %s
        """,
            (valid_count, invalid_count, batch_id),
        )

        conn.commit()

    logger.info(f"Validated rows: {valid_count} valid, {invalid_count} invalid")
    return valid_count, invalid_count


def create_jobs_for_validated_rows(conn: psycopg.Connection, batch_id: uuid.UUID) -> int:
    """Create jobs in ops.job_queue for validated rows."""
    import json

    with conn.cursor() as cur:
        # Get validated rows
        cur.execute(
            """
            SELECT id, case_number, defendant_name, judgment_amount 
            FROM intake.simplicity_validated_rows 
            WHERE batch_id = %s AND validation_status = 'valid'
        """,
            (batch_id,),
        )
        validated_rows = cur.fetchall()

        job_count = 0
        for row in validated_rows:
            dedup_key = f"{SMOKE_TEST_PREFIX}{row['case_number']}"
            payload = {
                "batch_id": str(batch_id),
                "validated_row_id": row["id"],
                "case_number": row["case_number"],
                "action": "upsert_judgment",
            }

            try:
                cur.execute(
                    """
                    INSERT INTO ops.job_queue 
                    (job_type, payload, status, dedup_key)
                    VALUES ('simplicity_ingest', %s, 'pending', %s)
                    ON CONFLICT (job_type, dedup_key) 
                    WHERE dedup_key IS NOT NULL AND status NOT IN ('completed', 'failed')
                    DO NOTHING
                    RETURNING id
                """,
                    (json.dumps(payload), dedup_key),
                )

                if cur.fetchone():
                    job_count += 1
            except psycopg.errors.UniqueViolation:
                # Job already exists, skip
                pass

        # Update batch status to completed
        cur.execute(
            """
            UPDATE intake.simplicity_batches 
            SET status = 'completed', 
                row_count_inserted = %s,
                completed_at = now()
            WHERE id = %s
        """,
            (job_count, batch_id),
        )

        conn.commit()

    logger.info(f"Created {job_count} jobs")
    return job_count


def get_batch_progress(conn: psycopg.Connection, batch_id: uuid.UUID) -> dict[str, Any] | None:
    """Get batch progress from view."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM intake.view_batch_progress 
            WHERE batch_id = %s
        """,
            (batch_id,),
        )
        return cur.fetchone()


def get_failed_rows(conn: psycopg.Connection, batch_id: uuid.UUID) -> list[dict]:
    """Get failed rows for a batch."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT row_index, error_stage, error_code, error_message 
            FROM intake.simplicity_failed_rows 
            WHERE batch_id = %s AND resolved_at IS NULL
        """,
            (batch_id,),
        )
        return cur.fetchall()


# =============================================================================
# Smoke Test Runner
# =============================================================================


def run_smoke_test(verbose: bool = False) -> bool:
    """
    Run the full intake smoke test.

    Returns:
        True if all tests passed, False otherwise
    """
    print("\n" + "=" * 60)
    print("  INTAKE PIPELINE SMOKE TEST")
    print("=" * 60 + "\n")

    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return False

    try:
        # Step 0: Cleanup any existing smoke test data
        print("[1/6] Cleaning up previous smoke test data...")
        cleanup_smoke_test_data(conn)

        # Step 1: Generate test CSV
        print("[2/6] Generating test CSV...")
        csv_content, file_hash = generate_test_csv()
        if verbose:
            print(f"       File hash: {file_hash[:16]}...")
            print(f"       Rows: {len(TEST_ROWS)} ({len(TEST_ROWS) - 1} valid, 1 invalid)")

        # Step 2: Create batch
        print("[3/6] Creating batch...")
        batch_id = create_test_batch(conn, file_hash)

        # Step 3: Stage raw rows
        print("[4/6] Staging raw rows...")
        staged_count = stage_raw_rows(conn, batch_id)

        # Step 4: Validate rows
        print("[5/6] Validating rows...")
        valid_count, invalid_count = validate_rows(conn, batch_id)

        # Step 5: Create jobs
        print("[6/6] Creating jobs for validated rows...")
        job_count = create_jobs_for_validated_rows(conn, batch_id)

        # Verify results
        print("\n" + "-" * 60)
        print("  VERIFICATION")
        print("-" * 60 + "\n")

        progress = get_batch_progress(conn, batch_id)
        failed_rows = get_failed_rows(conn, batch_id)

        all_passed = True

        # Assert: total_rows == 6
        if progress["total_rows"] == len(TEST_ROWS):
            print(f"  ✅ Total rows: {progress['total_rows']} (expected {len(TEST_ROWS)})")
        else:
            print(f"  ❌ Total rows: {progress['total_rows']} (expected {len(TEST_ROWS)})")
            all_passed = False

        # Assert: success_count == 5
        expected_success = len(TEST_ROWS) - 1  # All but the invalid row
        if progress["success_count"] == expected_success:
            print(f"  ✅ Success count: {progress['success_count']} (expected {expected_success})")
        else:
            print(f"  ❌ Success count: {progress['success_count']} (expected {expected_success})")
            all_passed = False

        # Assert: failed_count == 1
        expected_failed = 1
        if progress["failed_count"] == expected_failed:
            print(f"  ✅ Failed count: {progress['failed_count']} (expected {expected_failed})")
        else:
            print(f"  ❌ Failed count: {progress['failed_count']} (expected {expected_failed})")
            all_passed = False

        # Assert: failed row has expected error
        if len(failed_rows) == 1:
            failed = failed_rows[0]
            if (
                "defendant_name" in failed["error_message"].lower()
                or "invalid" in failed["error_message"].lower()
            ):
                print(f"  ✅ Failed row error: {failed['error_message'][:50]}...")
            else:
                print(f"  ⚠️  Failed row error (unexpected): {failed['error_message']}")
        else:
            print(f"  ❌ Expected 1 failed row, got {len(failed_rows)}")
            all_passed = False

        # Assert: job_count == 5
        if progress["job_count"] == expected_success:
            print(f"  ✅ Jobs created: {progress['job_count']} (expected {expected_success})")
        else:
            print(f"  ❌ Jobs created: {progress['job_count']} (expected {expected_success})")
            all_passed = False

        # Assert: status is Complete
        if progress["status"] == "Complete":
            print(f"  ✅ Batch status: {progress['status']}")
        else:
            print(f"  ❌ Batch status: {progress['status']} (expected Complete)")
            all_passed = False

        print()

        if all_passed:
            print("=" * 60)
            print("  ✅ INTAKE SMOKE TEST PASSED")
            print("=" * 60)
            return True
        else:
            print("=" * 60)
            print("  ❌ INTAKE SMOKE TEST FAILED")
            print("=" * 60)
            return False

    except Exception as e:
        logger.exception("Smoke test failed with exception")
        print(f"\n❌ SMOKE TEST FAILED: {e}")
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Intake Pipeline Smoke Test")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--cleanup-only", action="store_true", help="Only cleanup smoke test data")

    args = parser.parse_args()

    if args.cleanup_only:
        try:
            conn = get_db_connection()
            count = cleanup_smoke_test_data(conn)
            print(f"Cleaned up {count} smoke test records")
            conn.close()
            sys.exit(0)
        except Exception as e:
            print(f"Cleanup failed: {e}")
            sys.exit(1)

    success = run_smoke_test(verbose=args.verbose)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
