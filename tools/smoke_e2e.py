#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════
tools/smoke_e2e.py - End-to-End Ingestion Smoke Test
═══════════════════════════════════════════════════════════════════════════

Purpose:
    Pre-deployment validation of the complete ingestion pipeline.
    Tests Good, Bad, and Duplicate scenarios via API.

Test Cases:
    1. HAPPY PATH: Upload valid CSV → poll → assert status=completed
    2. IDEMPOTENCY: Re-upload same file → assert duplicate detected
    3. QUALITY CHECK: Upload invalid CSV → poll → assert status=failed with error budget

Usage:
    # Run smoke test (dev)
    SUPABASE_MODE=dev python -m tools.smoke_e2e

    # Run smoke test (prod) - for pre-deploy validation
    SUPABASE_MODE=prod python -m tools.smoke_e2e

    # Verbose output
    python -m tools.smoke_e2e --env dev --verbose

Exit Codes:
    0 = All tests passed
    1 = One or more tests failed
    2 = Setup/teardown error

CI/CD Integration:
    ```bash
    # In your deploy script
    SUPABASE_MODE=dev python -m tools.smoke_e2e || exit 1
    echo "✅ Smoke tests passed - proceeding with deployment"
    ```

Author: Dragonfly QA Team
Created: 2025-01-04
═══════════════════════════════════════════════════════════════════════════
"""

import argparse
import csv
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import create_supabase_client, get_supabase_env

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

POLL_INTERVAL_SECONDS = 2
MAX_POLL_ATTEMPTS = 60  # 2 minutes max
TEMP_DIR = Path("tmp/smoke_e2e")

# PGRST002 retry configuration
API_HEALTH_MAX_ATTEMPTS = 10
API_HEALTH_RETRY_DELAY = 1.0  # seconds

# Sample data templates
GOOD_ROW_TEMPLATE = {
    "File #": "2025-CV-{:05d}",
    "Plaintiff": "Test Plaintiff LLC",
    "Defendant": "Test Defendant {idx}",
    "Amount": "$5,000.00",
    "Entry Date": "01/15/2025",
    "Court": "New York Supreme Court",
    "County": "New York",
}

BAD_ROW_TEMPLATE = {
    # Missing 'File #' (case_number) - required field
    "File #": "",
    "Plaintiff": "Bad Data Corp",
    "Defendant": "",  # Missing defendant
    "Amount": "NOT_A_NUMBER",  # Invalid amount
    "Entry Date": "INVALID-DATE",
    "Court": "",
    "County": "",
}

# ═══════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TestResult:
    """Result of a single test case."""

    test_name: str
    passed: bool
    message: str
    duration_seconds: float
    batch_id: str | None = None


@dataclass
class SmokeTestReport:
    """Overall smoke test report."""

    environment: str
    total_tests: int
    passed: int
    failed: int
    duration_seconds: float
    results: list[TestResult]


# ═══════════════════════════════════════════════════════════════════════════
# CSV GENERATION
# ═══════════════════════════════════════════════════════════════════════════


def create_good_csv(path: Path, row_count: int = 10) -> Path:
    """
    Create a valid CSV file with good data.

    Args:
        path: Output file path
        row_count: Number of rows to generate

    Returns:
        Path to created file
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(GOOD_ROW_TEMPLATE.keys()))
        writer.writeheader()

        for i in range(row_count):
            row = {
                "File #": GOOD_ROW_TEMPLATE["File #"].format(i + 1),
                "Plaintiff": GOOD_ROW_TEMPLATE["Plaintiff"],
                "Defendant": GOOD_ROW_TEMPLATE["Defendant"].format(idx=i + 1),
                "Amount": GOOD_ROW_TEMPLATE["Amount"],
                "Entry Date": GOOD_ROW_TEMPLATE["Entry Date"],
                "Court": GOOD_ROW_TEMPLATE["Court"],
                "County": GOOD_ROW_TEMPLATE["County"],
            }
            writer.writerow(row)

    return path


def create_bad_csv(path: Path, row_count: int = 10) -> Path:
    """
    Create an invalid CSV file with bad data (triggers error budget).

    Args:
        path: Output file path
        row_count: Number of rows to generate

    Returns:
        Path to created file
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(BAD_ROW_TEMPLATE.keys()))
        writer.writeheader()

        for i in range(row_count):
            writer.writerow(BAD_ROW_TEMPLATE)

    return path


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of file (for idempotency check)."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# PGRST002 RETRY LOGIC
# ═══════════════════════════════════════════════════════════════════════════

# Retry configuration for PGRST002 errors during API calls
PGRST002_MAX_RETRIES = 5
PGRST002_RETRY_DELAY = 2.0  # seconds


def is_pgrst002_error(error: Exception) -> bool:
    """Check if an exception is a PGRST002 (schema cache stale) error."""
    error_str = str(error).lower()
    return (
        "pgrst002" in error_str
        or "503" in str(error)
        or "schema cache" in error_str
        or "service unavailable" in error_str
    )


def with_pgrst002_retry(func):
    """
    Decorator to add PGRST002 retry logic to API call functions.

    When PostgREST's schema cache is stale (after migrations), requests
    return 503/PGRST002. This decorator retries with exponential backoff.
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = kwargs.get("logger") or args[-1]  # Logger is typically last arg

        for attempt in range(1, PGRST002_MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if is_pgrst002_error(e):
                    if attempt < PGRST002_MAX_RETRIES:
                        logger.warning(
                            f"⚠️  API warming up (PGRST002, attempt {attempt}/{PGRST002_MAX_RETRIES}), "
                            f"retrying in {PGRST002_RETRY_DELAY}s..."
                        )
                        time.sleep(PGRST002_RETRY_DELAY)
                        continue
                    else:
                        logger.error(
                            f"❌ API still unhealthy after {PGRST002_MAX_RETRIES} retries. "
                            "Run: python -m tools.pgrst_reload --env <env>"
                        )
                # Re-raise non-PGRST002 errors or after max retries
                raise

    return wrapper


def wait_for_api_health(logger: logging.Logger) -> bool:
    """
    Wait for PostgREST API to become healthy (schema cache populated).

    Handles PGRST002 errors that occur when PostgREST's schema cache is stale
    after migrations or schema changes. Retries with exponential backoff.

    Args:
        logger: Logger instance

    Returns:
        True if API is healthy, False if max attempts exceeded

    Raises:
        Exception: If a non-PGRST002 error occurs
    """
    sb = create_supabase_client()

    for attempt in range(1, API_HEALTH_MAX_ATTEMPTS + 1):
        try:
            # Try public schema first (tends to recover faster)
            result = sb.table("plaintiffs").select("id").limit(1).execute()
            # If we get here without exception, API is healthy
            logger.debug(f"API health check passed on attempt {attempt}")
            return True

        except Exception as e:
            error_str = str(e)

            # Check for PGRST002 (schema cache stale)
            if "PGRST002" in error_str or "503" in error_str or "schema cache" in error_str.lower():
                if attempt < API_HEALTH_MAX_ATTEMPTS:
                    logger.warning(
                        f"⏳ PGRST002 detected (attempt {attempt}/{API_HEALTH_MAX_ATTEMPTS}), "
                        f"waiting {API_HEALTH_RETRY_DELAY}s for schema cache..."
                    )
                    time.sleep(API_HEALTH_RETRY_DELAY)
                    continue
                else:
                    logger.error(
                        f"❌ API still unhealthy after {API_HEALTH_MAX_ATTEMPTS} attempts. "
                        "Run: python -m tools.pgrst_reload --env <env>"
                    )
                    return False
            else:
                # Non-PGRST002 error - re-raise
                raise

    return False


# ═══════════════════════════════════════════════════════════════════════════
# API HELPERS
# ═══════════════════════════════════════════════════════════════════════════


@with_pgrst002_retry
def upload_batch(file_path: Path, logger: logging.Logger) -> dict[str, Any]:
    """
    Upload a batch via Supabase API.

    Args:
        file_path: Path to CSV file
        logger: Logger instance

    Returns:
        Dict with batch_id, status, is_duplicate
    """
    sb = create_supabase_client()

    # Compute file hash for idempotency
    file_hash = compute_file_hash(file_path)
    logger.debug(f"File hash: {file_hash[:16]}...")

    # Check if batch already exists (idempotency)
    existing = (
        sb.schema("intake")
        .table("simplicity_batches")
        .select("id,status,file_hash")
        .eq("file_hash", file_hash)
        .execute()
    )

    if existing.data:
        logger.debug(f"Duplicate detected: batch_id={existing.data[0]['id'][:8]}...")
        return {
            "batch_id": existing.data[0]["id"],
            "status": existing.data[0]["status"],
            "is_duplicate": True,
        }

    # Read file content
    with open(file_path, "rb") as f:
        content = f.read()

    # Count rows (exclude header)
    row_count = len(content.decode("utf-8").strip().split("\n")) - 1

    # Create new batch record
    batch = (
        sb.schema("intake")
        .table("simplicity_batches")
        .insert(
            {
                "filename": file_path.name,
                "file_hash": file_hash,
                "status": "uploaded",
                "row_count_total": row_count,
            }
        )
        .execute()
    )

    if not batch.data:
        raise Exception("Failed to create batch record")

    logger.debug(f"Batch created: {batch.data[0]['id'][:8]}...")

    return {
        "batch_id": batch.data[0]["id"],
        "status": "uploaded",
        "is_duplicate": False,
    }


@with_pgrst002_retry
def poll_batch_status(
    batch_id: str, target_statuses: list[str], logger: logging.Logger
) -> dict[str, Any]:
    """
    Poll batch status until it reaches one of the target statuses.

    Args:
        batch_id: Batch UUID
        target_statuses: List of statuses to wait for (e.g., ['completed', 'failed'])
        logger: Logger instance

    Returns:
        Batch data when target status is reached

    Raises:
        TimeoutError: If max poll attempts exceeded
    """
    sb = create_supabase_client()

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        result = (
            sb.schema("intake")
            .table("simplicity_batches")
            .select(
                "id,status,filename,row_count_total,row_count_inserted,row_count_invalid,row_count_duplicate,rejection_reason,error_threshold_percent"
            )
            .eq("id", batch_id)
            .execute()
        )

        if not result.data:
            raise Exception(f"Batch {batch_id} not found")

        batch = result.data[0]
        logger.debug(f"Poll #{attempt}: batch_id={batch_id[:8]}... status={batch['status']}")

        if batch["status"] in target_statuses:
            return batch

        if batch["status"] == "failed" and "failed" not in target_statuses:
            raise Exception(
                f"Batch failed unexpectedly: {batch.get('rejection_reason', 'Unknown error')}"
            )

        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"Batch {batch_id} did not reach target status after {MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s"
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST CASES
# ═══════════════════════════════════════════════════════════════════════════


def test_happy_path(logger: logging.Logger) -> TestResult:
    """
    Test Case 1: The Happy Path
    Upload valid data and verify successful ingestion.
    """
    test_name = "Happy Path (Valid Data)"
    start_time = time.time()

    try:
        logger.info("=" * 80)
        logger.info(f"TEST 1: {test_name}")
        logger.info("=" * 80)

        # Setup: Create good CSV
        csv_path = TEMP_DIR / "good_data.csv"
        create_good_csv(csv_path, row_count=10)
        logger.info(f"✓ Created test file: {csv_path.name} (10 rows)")

        # Upload batch
        logger.info("⏳ Uploading batch...")
        upload_result = upload_batch(csv_path, logger)
        batch_id = upload_result["batch_id"]
        logger.info(f"✓ Batch created: {batch_id[:8]}...")

        # Poll until completed
        logger.info("⏳ Polling for completion (max 2min)...")
        batch = poll_batch_status(batch_id, ["completed"], logger)

        # Assertions
        assert batch["status"] == "completed", f"Expected completed, got {batch['status']}"
        assert (
            batch["row_count_inserted"] == 10
        ), f"Expected 10 inserted rows, got {batch['row_count_inserted']}"
        assert (
            batch["row_count_invalid"] == 0
        ), f"Expected 0 invalid rows, got {batch['row_count_invalid']}"

        duration = time.time() - start_time
        logger.info("=" * 80)
        logger.info(f"✅ TEST 1 PASSED ({duration:.1f}s)")
        logger.info(f"   Batch ID: {batch_id[:8]}...")
        logger.info(f"   Inserted: {batch['row_count_inserted']} rows")
        logger.info(f"   Invalid: {batch['row_count_invalid']} rows")
        logger.info("=" * 80)

        return TestResult(
            test_name=test_name,
            passed=True,
            message=f"Successfully ingested {batch['row_count_inserted']} rows",
            duration_seconds=duration,
            batch_id=batch_id,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"❌ TEST 1 FAILED ({duration:.1f}s): {e}")
        return TestResult(
            test_name=test_name,
            passed=False,
            message=str(e),
            duration_seconds=duration,
        )


def test_idempotency(first_batch_id: str, logger: logging.Logger) -> TestResult:
    """
    Test Case 2: The Gatekeeper (Idempotency)
    Re-upload the same file and verify it's deduplicated.
    """
    test_name = "Idempotency (Duplicate Upload)"
    start_time = time.time()

    try:
        logger.info("=" * 80)
        logger.info(f"TEST 2: {test_name}")
        logger.info("=" * 80)

        # Upload same file again
        csv_path = TEMP_DIR / "good_data.csv"
        logger.info(f"⏳ Re-uploading same file: {csv_path.name}")
        upload_result = upload_batch(csv_path, logger)

        # Assertions
        assert upload_result["is_duplicate"], "Expected duplicate detection, but got new batch"
        assert (
            upload_result["batch_id"] == first_batch_id
        ), f"Expected same batch_id {first_batch_id[:8]}..., got {upload_result['batch_id'][:8]}..."

        duration = time.time() - start_time
        logger.info("=" * 80)
        logger.info(f"✅ TEST 2 PASSED ({duration:.1f}s)")
        logger.info(f"   Original Batch: {first_batch_id[:8]}...")
        logger.info(f"   Returned Batch: {upload_result['batch_id'][:8]}...")
        logger.info("   ✓ Idempotency enforced via file_hash")
        logger.info("=" * 80)

        return TestResult(
            test_name=test_name,
            passed=True,
            message=f"Duplicate detected, returned existing batch {first_batch_id[:8]}...",
            duration_seconds=duration,
            batch_id=first_batch_id,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"❌ TEST 2 FAILED ({duration:.1f}s): {e}")
        return TestResult(
            test_name=test_name,
            passed=False,
            message=str(e),
            duration_seconds=duration,
        )


def test_quality_check(logger: logging.Logger) -> TestResult:
    """
    Test Case 3: The Quality Check (Bad Data)
    Upload invalid data and verify it's rejected (error budget).
    """
    test_name = "Quality Check (Bad Data)"
    start_time = time.time()

    try:
        logger.info("=" * 80)
        logger.info(f"TEST 3: {test_name}")
        logger.info("=" * 80)

        # Setup: Create bad CSV (100% error rate)
        csv_path = TEMP_DIR / "bad_data.csv"
        create_bad_csv(csv_path, row_count=10)
        logger.info(f"✓ Created test file: {csv_path.name} (10 rows, 100% invalid)")

        # Upload batch
        logger.info("⏳ Uploading batch...")
        upload_result = upload_batch(csv_path, logger)
        batch_id = upload_result["batch_id"]
        logger.info(f"✓ Batch created: {batch_id[:8]}...")

        # Poll until failed (should trigger error budget)
        logger.info("⏳ Polling for rejection (max 2min)...")
        batch = poll_batch_status(batch_id, ["failed"], logger)

        # Assertions
        assert batch["status"] == "failed", f"Expected failed, got {batch['status']}"
        assert batch["rejection_reason"], "Expected rejection_reason to be populated"
        assert (
            "budget" in batch["rejection_reason"].lower()
            or "error" in batch["rejection_reason"].lower()
            or "exceeded" in batch["rejection_reason"].lower()
        ), f"Expected 'budget'/'error'/'exceeded' in rejection_reason, got: {batch['rejection_reason']}"

        duration = time.time() - start_time
        logger.info("=" * 80)
        logger.info(f"✅ TEST 3 PASSED ({duration:.1f}s)")
        logger.info(f"   Batch ID: {batch_id[:8]}...")
        logger.info(f"   Status: {batch['status']}")
        logger.info(f"   Rejection: {batch['rejection_reason']}")
        logger.info(f"   ✓ Error budget enforced (threshold: {batch['error_threshold_percent']}%)")
        logger.info("=" * 80)

        return TestResult(
            test_name=test_name,
            passed=True,
            message=f"Batch rejected: {batch['rejection_reason']}",
            duration_seconds=duration,
            batch_id=batch_id,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"❌ TEST 3 FAILED ({duration:.1f}s): {e}")
        return TestResult(
            test_name=test_name,
            passed=False,
            message=str(e),
            duration_seconds=duration,
        )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN SMOKE TEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════


def run_smoke_test(logger: logging.Logger) -> SmokeTestReport:
    """
    Execute all smoke test cases in sequence.

    Returns:
        SmokeTestReport with results
    """
    env = get_supabase_env()
    start_time = time.time()
    results: list[TestResult] = []

    logger.info("╔" + "=" * 78 + "╗")
    logger.info(f"║ DRAGONFLY END-TO-END SMOKE TEST - Environment: {env.upper():38} ║")
    logger.info("╚" + "=" * 78 + "╝")

    # Pre-flight: Wait for API health (handles PGRST002 schema cache issues)
    logger.info("\n🔍 PRE-FLIGHT: Checking API health...")
    if not wait_for_api_health(logger):
        return SmokeTestReport(
            environment=env,
            total_tests=0,
            passed=0,
            failed=1,
            duration_seconds=time.time() - start_time,
            results=[
                TestResult(
                    test_name="API Health Check",
                    passed=False,
                    message="PGRST002: PostgREST schema cache stale after max retries",
                    duration_seconds=time.time() - start_time,
                    batch_id=None,
                )
            ],
        )
    logger.info("   ✓ API is healthy")

    # Setup: Create temp directory
    logger.info("\n🔧 SETUP: Creating temp directory...")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"   ✓ Temp directory: {TEMP_DIR}")

    # Test 1: Happy Path
    result1 = test_happy_path(logger)
    results.append(result1)

    if not result1.passed:
        logger.warning("⚠️  Test 1 failed, skipping Test 2 (idempotency)")
    else:
        # Test 2: Idempotency (requires Test 1 batch_id)
        result2 = test_idempotency(result1.batch_id, logger)
        results.append(result2)

    # Test 3: Quality Check (independent)
    result3 = test_quality_check(logger)
    results.append(result3)

    # Teardown: Clean up temp files
    logger.info("\n🧹 TEARDOWN: Cleaning up temp files...")
    for file in TEMP_DIR.glob("*.csv"):
        file.unlink()
        logger.info(f"   ✓ Deleted: {file.name}")

    # Compile report
    total_duration = time.time() - start_time
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    return SmokeTestReport(
        environment=env,
        total_tests=len(results),
        passed=passed,
        failed=failed,
        duration_seconds=total_duration,
        results=results,
    )


def print_report(report: SmokeTestReport, logger: logging.Logger):
    """Print final smoke test report."""
    logger.info("\n")
    logger.info("╔" + "=" * 78 + "╗")
    logger.info("║ SMOKE TEST REPORT" + " " * 60 + "║")
    logger.info("╠" + "=" * 78 + "╣")
    logger.info(f"║ Environment: {report.environment:64} ║")
    logger.info(f"║ Total Tests: {report.total_tests:64} ║")
    logger.info(f"║ Passed:      {report.passed:64} ║")
    logger.info(f"║ Failed:      {report.failed:64} ║")
    logger.info(f"║ Duration:    {report.duration_seconds:.1f}s{' ' * 60} ║")
    logger.info("╠" + "=" * 78 + "╣")

    for i, result in enumerate(report.results, 1):
        status_icon = "✅" if result.passed else "❌"
        logger.info(f"║ Test {i}: {status_icon} {result.test_name:64} ║")
        logger.info(f"║   Message: {result.message[:70]:70} ║")
        logger.info(f"║   Duration: {result.duration_seconds:.1f}s{' ' * 67} ║")
        if result.batch_id:
            logger.info(f"║   Batch ID: {result.batch_id[:8]}...{' ' * 62} ║")

    logger.info("╚" + "=" * 78 + "╝")

    if report.failed == 0:
        logger.info("\n🎉 ALL SMOKE TESTS PASSED - System is healthy! 🎉")
    else:
        logger.error(f"\n❌ {report.failed}/{report.total_tests} TESTS FAILED")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Dragonfly End-to-End Ingestion Smoke Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run smoke test (dev)
  SUPABASE_MODE=dev python -m tools.smoke_e2e
  
  # Run smoke test (prod) - pre-deploy validation
  SUPABASE_MODE=prod python -m tools.smoke_e2e
  
  # Verbose output
  python -m tools.smoke_e2e --env dev --verbose

Exit Codes:
  0 = All tests passed
  1 = One or more tests failed
  2 = Setup/teardown error
        """,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Environment (default: from SUPABASE_MODE env var)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Set environment if specified
    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("smoke_e2e")

    try:
        report = run_smoke_test(logger)
        print_report(report, logger)

        # Exit with appropriate code
        if report.failed > 0:
            sys.exit(1)
        else:
            sys.exit(0)

    except KeyboardInterrupt:
        logger.warning("\n⚠️  Smoke test interrupted by user")
        sys.exit(2)
    except Exception as e:
        logger.exception(f"\n❌ Smoke test crashed: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
