#!/usr/bin/env python3
"""
Dragonfly Civil - Simplicity Pipeline Smoke Test
═══════════════════════════════════════════════════════════════════════════════

CI-friendly smoke test for the hardened ingestion pipeline.

Features Tested:
1. Schema Validation: Required columns exist in intake.simplicity_batches
2. Idempotency: Duplicate file_hash is rejected
3. Error Budget: Verify error_threshold_percent column exists
4. Timing Metrics: Verify parse_duration_ms, db_duration_ms columns exist
5. Direct Insert Test: End-to-end batch creation and processing

Usage:
    python -m tools.smoke_simplicity --env dev
    python -m tools.smoke_simplicity --env prod --verbose

Exit Codes:
    0 = All tests passed
    1 = One or more tests failed
    2 = Configuration error

Example Output:
    ═══════════════════════════════════════════════════════════════════════════════
    🧪 Simplicity Pipeline Smoke Test
    ═══════════════════════════════════════════════════════════════════════════════
    Environment: dev
    ───────────────────────────────────────────────────────────────────────────────
    ✅ Schema check: All required columns exist
    ✅ Batch created: id=abc123..., rows=10
    ✅ Idempotency: Duplicate hash detected
    ✅ Error budget: Column error_threshold_percent exists (default=10)
    ✅ Timing metrics: Columns parse_duration_ms, db_duration_ms exist
    ═══════════════════════════════════════════════════════════════════════════════
    Results: 5/5 passed ✅
    ═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg
from uuid import uuid4

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# =============================================================================
# TEST RESULT TRACKER
# =============================================================================


@dataclass
class TestResult:
    """Track test results."""

    passed: int = 0
    failed: int = 0
    verbose: bool = False
    errors: list[str] = field(default_factory=list)

    def ok(self, test: str, details: str = "") -> None:
        """Record a passed test."""
        self.passed += 1
        msg = f"✅ {test}"
        if details:
            msg += f": {details}"
        print(msg)

    def fail(self, test: str, details: str = "") -> None:
        """Record a failed test."""
        self.failed += 1
        msg = f"❌ {test}"
        if details:
            msg += f": {details}"
        print(msg)
        self.errors.append(f"{test}: {details}")

    def log(self, msg: str) -> None:
        """Log verbose message."""
        if self.verbose:
            print(f"   📋 {msg}")

    def summary(self) -> bool:
        """Print summary and return True if all passed."""
        print()
        print("═" * 79)
        total = self.passed + self.failed
        if self.failed == 0:
            print(f"✅ Results: {self.passed}/{total} passed - ALL TESTS PASSED")
        else:
            print(f"❌ Results: {self.passed}/{total} passed - {self.failed} FAILED")
            for err in self.errors:
                print(f"   • {err}")
        print("═" * 79)
        return self.failed == 0


# =============================================================================
# DATABASE CONNECTION (Direct, no pool)
# =============================================================================


def get_db_url(env: str) -> str:
    """Get database URL for the specified environment."""
    # Set the environment variable before loading settings
    os.environ["SUPABASE_MODE"] = env

    # Load from .env file based on environment
    env_file = PROJECT_ROOT / f".env.{env}"
    if env_file.exists():
        # Simple .env parser (handle encoding issues)
        with open(env_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ[key.strip()] = value.strip()

    # Prefer MIGRATE URL (direct connection) over pooler for CI reliability
    db_url = os.environ.get("SUPABASE_MIGRATE_DB_URL") or os.environ.get("SUPABASE_DB_URL")

    if not db_url:
        raise ValueError(
            f"No SUPABASE_DB_URL or SUPABASE_MIGRATE_DB_URL found for environment: {env}\n"
            f"Check that {env_file} exists and contains one of these variables"
        )

    # Ensure sslmode is set
    if "sslmode" not in db_url:
        db_url += "?sslmode=require" if "?" not in db_url else "&sslmode=require"

    return db_url


def get_connection(db_url: str) -> "psycopg.Connection[dict[str, Any]]":
    """Get a direct psycopg connection (sync, simple)."""
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(db_url, row_factory=dict_row)  # type: ignore[return-value]


# =============================================================================
# TEST DATA GENERATION
# =============================================================================


def generate_test_csv(
    row_count: int = 10,
    error_count: int = 1,
    prefix: str = "SMOKE",
) -> tuple[str, bytes, int]:
    """Generate a test CSV with valid and invalid rows."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"smoke_test_{timestamp}.csv"

    lines = ["File #,Plaintiff,Defendant,Amount,Entry Date,Court,County"]

    # Generate valid rows
    valid_count = row_count - error_count
    for i in range(valid_count):
        lines.append(
            f"{prefix}-{timestamp}-{i:04d},"
            f"Test Plaintiff {i},"
            f"Test Defendant {i},"
            f"${1000 + i * 100}.00,"
            f"2024-01-{(i % 28) + 1:02d},"
            f"Test District Court,"
            f"Test County"
        )

    # Generate invalid rows (missing defendant)
    for i in range(error_count):
        lines.append(
            f"{prefix}-{timestamp}-ERR{i:04d},"
            f"Error Plaintiff {i},"
            f","  # Empty defendant - validation error
            f"NOT_A_NUMBER,"  # Invalid amount
            f"2024-01-01,"
            f"Test Court,"
            f"Test County"
        )

    content = "\n".join(lines).encode("utf-8")
    return filename, content, valid_count


# =============================================================================
# MAIN SMOKE TEST
# =============================================================================


def run_smoke_test(env: str, verbose: bool = False) -> bool:
    """
    Run the smoke test suite (synchronous, simple).

    Args:
        env: Environment (dev/prod)
        verbose: Enable verbose logging

    Returns:
        True if all tests passed
    """
    print()
    print("═" * 79)
    print("🧪 Simplicity Pipeline Smoke Test")
    print("═" * 79)
    print(f"Environment: {env}")
    print("─" * 79)

    result = TestResult(verbose=verbose)

    # Set environment
    os.environ["SUPABASE_MODE"] = env

    try:
        db_url = get_db_url(env)
        result.log(f"DB URL: {db_url[:50]}...")
    except Exception as e:
        result.fail("Configuration", str(e))
        return result.summary()

    try:
        conn = get_connection(db_url)
        result.log("Connected to database")
    except Exception as e:
        result.fail("Database connection", str(e))
        return result.summary()

    try:
        # =====================================================================
        # TEST 1: Schema Validation
        # =====================================================================
        result.log("Checking schema...")

        required_columns = [
            "file_hash",
            "error_threshold_percent",
            "rejection_reason",
            "parse_duration_ms",
            "db_duration_ms",
            "plaintiff_inserted",
            "plaintiff_duplicate",
            "plaintiff_failed",
        ]

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'intake'
                AND table_name = 'simplicity_batches'
                """
            )
            existing_columns = {row["column_name"] for row in cur.fetchall()}

        missing = [col for col in required_columns if col not in existing_columns]

        if missing:
            result.fail("Schema check", f"Missing columns: {', '.join(missing)}")
        else:
            result.ok("Schema check", "All required columns exist")

        # =====================================================================
        # TEST 2: Error threshold default value
        # =====================================================================
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'intake'
                AND table_name = 'simplicity_batches'
                AND column_name = 'error_threshold_percent'
                """
            )
            row = cur.fetchone()
            if row and row["column_default"] == "10":
                result.ok("Error threshold default", "error_threshold_percent defaults to 10")
            else:
                result.fail(
                    "Error threshold default",
                    f"Expected default=10, got {row['column_default'] if row else 'None'}",
                )

        # =====================================================================
        # TEST 3: Batch Creation (Direct SQL)
        # =====================================================================
        result.log("Testing batch creation...")

        filename, content, expected_valid = generate_test_csv(
            row_count=10, error_count=1, prefix="SMOKE"
        )
        file_hash = hashlib.sha256(content).hexdigest()
        batch_id = str(uuid4())

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO intake.simplicity_batches (
                    id, filename, file_hash, row_count_total, status,
                    error_threshold_percent, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (batch_id, filename, file_hash, 10, "pending", 10),
            )
            conn.commit()
            result.ok("Batch created", f"id={batch_id[:8]}..., rows=10")

        # =====================================================================
        # TEST 4: Idempotency (Duplicate Hash Rejected)
        # =====================================================================
        result.log("Testing idempotency...")

        duplicate_batch_id = str(uuid4())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO intake.simplicity_batches (
                        id, filename, file_hash, row_count_total, status,
                        error_threshold_percent, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (duplicate_batch_id, filename, file_hash, 10, "pending", 10),
                )
                conn.commit()
                # If we get here, uniqueness constraint failed
                result.fail("Idempotency", "Duplicate hash was NOT rejected")
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                conn.rollback()
                result.ok("Idempotency", "Duplicate file_hash correctly rejected")
            else:
                conn.rollback()
                result.fail("Idempotency", f"Unexpected error: {e}")

        # =====================================================================
        # TEST 5: Timing Metrics Update
        # =====================================================================
        result.log("Testing timing metrics...")

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE intake.simplicity_batches
                SET parse_duration_ms = 45,
                    db_duration_ms = 120,
                    status = 'completed',
                    completed_at = NOW()
                WHERE id = %s
                RETURNING parse_duration_ms, db_duration_ms
                """,
                (batch_id,),
            )
            conn.commit()
            row = cur.fetchone()
            if row and row["parse_duration_ms"] == 45 and row["db_duration_ms"] == 120:
                result.ok("Timing metrics", "parse=45ms, db=120ms recorded")
            else:
                result.fail("Timing metrics", f"Values not stored correctly: {row}")

        # =====================================================================
        # TEST 6: Error Budget / Rejection Reason
        # =====================================================================
        result.log("Testing rejection reason...")

        failed_batch_id = str(uuid4())
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO intake.simplicity_batches (
                    id, filename, file_hash, row_count_total, status,
                    error_threshold_percent, rejection_reason, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING rejection_reason
                """,
                (
                    failed_batch_id,
                    "failed_batch.csv",
                    hashlib.sha256(b"failed").hexdigest(),
                    10,
                    "failed",
                    10,
                    "Error rate 50.0% exceeded limit 10%",
                ),
            )
            conn.commit()
            row = cur.fetchone()
            if row and "exceeded" in (row["rejection_reason"] or ""):
                result.ok("Rejection reason", "Error budget rejection recorded")
            else:
                result.fail("Rejection reason", f"Not stored: {row}")

        # =====================================================================
        # TEST 7: View exists (intake.view_batch_metrics)
        # =====================================================================
        result.log("Checking metrics view...")

        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT COUNT(*) as cnt FROM intake.view_batch_metrics LIMIT 1
                    """
                )
                result.ok("Metrics view", "intake.view_batch_metrics exists")
            except Exception as e:
                result.fail("Metrics view", f"View missing: {e}")

        # =====================================================================
        # CLEANUP
        # =====================================================================
        result.log("Cleaning up test data...")

        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM intake.simplicity_batches
                WHERE filename LIKE 'smoke_test_%'
                   OR filename = 'failed_batch.csv'
                """
            )
            conn.commit()

        result.log("Cleanup complete")

    except Exception as e:
        result.fail("Unexpected error", str(e))
        if verbose:
            import traceback

            traceback.print_exc()
    finally:
        conn.close()

    return result.summary()


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Smoke test for Simplicity ingestion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    try:
        success = run_smoke_test(env=args.env, verbose=args.verbose)
        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n⚠️ Test interrupted")
        return 1

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
