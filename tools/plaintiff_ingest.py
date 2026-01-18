#!/usr/bin/env python
"""World-class plaintiff ingestion CLI with production-grade idempotency.

This is the single operator entrypoint for plaintiff data ingestion. It provides:

1. **Atomic Batch Claiming** - Uses ingest.claim_import_run() to prevent duplicates
2. **Row-Level Idempotency** - ON CONFLICT DO NOTHING on dedupe_key
3. **Reconciliation** - Validates expected vs actual row counts
4. **Log Redaction** - SSNs and card numbers are NEVER logged
5. **Rollback Support** - Soft-delete with full audit trail

## Idempotency Guarantees

- **Batch level**: Same (source_system, source_batch_id, file_hash) → duplicate status
- **Row level**: Same dedupe_key → skipped (ON CONFLICT DO NOTHING)
- **Upload same file twice = inserted 0 on second run**

## Usage

    # Dry run (default)
    python -m tools.plaintiff_ingest \\
        --csv data/plaintiffs.csv \\
        --source-system simplicity \\
        --source-batch-id batch-2026-01-17

    # Commit to database
    python -m tools.plaintiff_ingest \\
        --csv data/plaintiffs.csv \\
        --source-system simplicity \\
        --source-batch-id batch-2026-01-17 \\
        --commit

## Exit Codes

- 0: Success (including duplicate batches - no-op is success)
- 1: Gate failure (import failed, reconciliation failed)
- 2: Script error (missing file, database connection error)
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

import psycopg
from psycopg import Connection

from etl.src.ingest_claim import (
    ClaimResult,
    ClaimStatus,
    IngestClaimClient,
    ReconcileResult,
    compute_batch_id,
    compute_file_hash,
)
from etl.src.log_redactor import PIIRedactionFilter, SafeLogger, redact
from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env

# Configure safe logging (PII never logged)
_raw_logger = logging.getLogger(__name__)
logger = SafeLogger(_raw_logger)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class IngestResult:
    """Complete result of an ingestion operation."""

    success: bool
    run_id: Optional[str] = None
    claim_status: Optional[ClaimStatus] = None

    # Counts
    rows_fetched: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    rows_errored: int = 0

    # Reconciliation
    reconcile_passed: bool = False
    reconcile_expected: int = 0
    reconcile_actual: int = 0
    reconcile_delta: int = 0

    # Errors
    error_message: Optional[str] = None
    examples: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        """One-line summary for operators."""
        if self.claim_status == ClaimStatus.DUPLICATE:
            return f"PASS (duplicate): run_id={self.run_id} - already imported"
        if self.claim_status == ClaimStatus.IN_PROGRESS:
            return f"FAIL (in_progress): run_id={self.run_id} - another worker processing"
        if self.success:
            return (
                f"PASS: run_id={self.run_id} fetched={self.rows_fetched} "
                f"inserted={self.rows_inserted} skipped={self.rows_skipped} "
                f"errored={self.rows_errored} reconcile={'PASS' if self.reconcile_passed else 'FAIL'}"
            )
        return f"FAIL: run_id={self.run_id} error={self.error_message}"


# =============================================================================
# CORE INGESTION LOGIC
# =============================================================================


def _configure_logging(verbose: bool) -> None:
    """Configure logging with PII redaction."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")

    # Add PII filter to root logger
    root = logging.getLogger()
    root.addFilter(PIIRedactionFilter())


def _resolve_db_target(env_override: Optional[str] = None) -> tuple[str, str, str, str]:
    """Resolve database connection details."""
    env = env_override or get_supabase_env()
    url = get_supabase_db_url(env)
    host, dbname, user = describe_db_url(url)
    logger.info(
        "Database: host=%s dbname=%s user=%s env=%s",
        host,
        dbname,
        user,
        env,
    )
    return env, url, host, dbname


def _ensure_tables_exist(conn: Connection) -> bool:
    """Verify required tables exist."""
    required = [
        ("public", "plaintiffs"),
        ("ingest", "import_runs"),
        ("ingest", "plaintiffs_raw"),
    ]

    with conn.cursor() as cur:
        for schema, table in required:
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema, table),
            )
            if not cur.fetchone():
                logger.error("Required table %s.%s not found", schema, table)
                return False
    return True


def _insert_plaintiffs_raw(
    conn: Connection,
    run_id: str,
    csv_path: Path,
    source_system: str,
    *,
    limit: Optional[int] = None,
) -> tuple[int, int, int, list[str]]:
    """Insert CSV rows into ingest.plaintiffs_raw with ON CONFLICT DO NOTHING.

    Returns:
        (rows_fetched, rows_inserted, rows_skipped, examples)
    """
    import csv
    from hashlib import sha256

    rows_fetched = 0
    rows_inserted = 0
    rows_skipped = 0
    examples = []

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        with conn.cursor() as cur:
            for i, row in enumerate(reader):
                if limit and i >= limit:
                    break

                rows_fetched += 1

                # Compute deterministic dedupe_key
                # Formula: sha256(source_system || '|' || email || '|' || name_normalized)
                name = row.get("plaintiff_name", row.get("name", "")).strip()
                email = row.get("email", "").strip().lower()
                name_normalized = name.lower().strip()

                dedupe_input = f"{source_system}|{email}|{name_normalized}"
                dedupe_key = sha256(dedupe_input.encode()).hexdigest()

                # Insert with ON CONFLICT DO NOTHING (idempotent)
                cur.execute(
                    """
                    INSERT INTO ingest.plaintiffs_raw (
                        import_run_id,
                        row_index,
                        dedupe_key,
                        plaintiff_name,
                        plaintiff_name_normalized,
                        email,
                        phone,
                        address_line1,
                        city,
                        state,
                        postal_code,
                        raw_data,
                        status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending'
                    )
                    ON CONFLICT (dedupe_key) DO NOTHING
                    RETURNING id
                    """,
                    (
                        run_id,
                        i,
                        dedupe_key,
                        name,
                        name_normalized,
                        email,
                        row.get("phone", ""),
                        row.get("address", row.get("address_line1", "")),
                        row.get("city", ""),
                        row.get("state", ""),
                        row.get("postal_code", row.get("zip", "")),
                        psycopg.types.json.Json(row),
                    ),
                )

                if cur.fetchone():
                    rows_inserted += 1
                    if len(examples) < 3:
                        examples.append(redact(name))
                else:
                    rows_skipped += 1

    return rows_fetched, rows_inserted, rows_skipped, examples


def run_ingestion(
    csv_path: Path,
    source_system: str,
    source_batch_id: str,
    *,
    commit: bool = False,
    limit: Optional[int] = None,
    env_override: Optional[str] = None,
) -> IngestResult:
    """Run the complete ingestion pipeline.

    This is the core function that implements the production-safe, idempotent
    ingestion workflow:

    1. Compute file hash
    2. Claim the batch atomically
    3. Insert rows with ON CONFLICT DO NOTHING
    4. Finalize with counts
    5. Run reconciliation

    Args:
        csv_path: Path to the CSV file
        source_system: Source system identifier (e.g., 'simplicity', 'jbi')
        source_batch_id: Unique batch identifier
        commit: If True, persist changes; if False, dry-run with rollback
        limit: Optional row limit for testing
        env_override: Override SUPABASE_MODE (dev/prod)

    Returns:
        IngestResult with complete operation details
    """
    result = IngestResult(success=False)

    # =========================================================================
    # STEP 0: Compute file hash
    # =========================================================================
    try:
        file_hash = compute_file_hash(csv_path)
        logger.info(
            "File: %s hash=%s source=%s batch=%s",
            csv_path.name,
            file_hash[:12] + "...",
            source_system,
            source_batch_id,
        )
    except Exception as exc:
        result.error_message = f"Failed to compute file hash: {exc}"
        logger.error(result.error_message)
        return result

    # =========================================================================
    # STEP 1: Connect and validate
    # =========================================================================
    try:
        target_env, db_url, host, dbname = _resolve_db_target(env_override)
    except Exception as exc:
        result.error_message = f"Database connection error: {redact(str(exc))}"
        logger.error(result.error_message)
        return result

    # =========================================================================
    # STEP 2: Run with transaction
    # =========================================================================
    try:
        with psycopg.connect(db_url, autocommit=False) as conn:
            # Verify tables exist
            if not _ensure_tables_exist(conn):
                result.error_message = "Required tables not found"
                return result

            client = IngestClaimClient(conn)

            # =================================================================
            # STEP 3: Claim the batch atomically
            # =================================================================
            claim = client.claim(
                source_system=source_system,
                source_batch_id=source_batch_id,
                file_hash=file_hash,
                filename=csv_path.name,
                import_kind="plaintiff",
            )

            result.run_id = str(claim.run_id)
            result.claim_status = claim.status

            if claim.is_duplicate:
                logger.info(
                    "Duplicate batch detected (run_id=%s). Already imported.",
                    claim.run_id,
                )
                result.success = True
                result.reconcile_passed = True
                return result

            if claim.is_in_progress:
                logger.warning(
                    "Batch in_progress by another worker (run_id=%s). Retry later.",
                    claim.run_id,
                )
                result.error_message = "Another worker is processing this batch"
                return result

            logger.info("Claimed batch: run_id=%s", claim.run_id)

            # =================================================================
            # STEP 4: Insert rows with ON CONFLICT DO NOTHING
            # =================================================================
            try:
                rows_fetched, rows_inserted, rows_skipped, examples = _insert_plaintiffs_raw(
                    conn,
                    str(claim.run_id),
                    csv_path,
                    source_system,
                    limit=limit,
                )

                result.rows_fetched = rows_fetched
                result.rows_inserted = rows_inserted
                result.rows_skipped = rows_skipped
                result.examples = examples

                logger.info(
                    "Inserted: fetched=%d inserted=%d skipped=%d",
                    rows_fetched,
                    rows_inserted,
                    rows_skipped,
                )

            except Exception as exc:
                result.error_message = f"Insert failed: {redact(str(exc))}"
                logger.error(result.error_message)

                # Finalize with error
                client.finalize(
                    run_id=claim.run_id,
                    rows_fetched=result.rows_fetched,
                    rows_inserted=result.rows_inserted,
                    rows_skipped=result.rows_skipped,
                    rows_errored=1,
                    error_details={"fatal": True, "message": result.error_message},
                )
                conn.rollback()
                return result

            # =================================================================
            # STEP 5: Finalize with counts
            # =================================================================
            client.finalize(
                run_id=claim.run_id,
                rows_fetched=result.rows_fetched,
                rows_inserted=result.rows_inserted,
                rows_skipped=result.rows_skipped,
                rows_errored=result.rows_errored,
            )

            # =================================================================
            # STEP 6: Reconcile
            # =================================================================
            try:
                reconcile = client.reconcile(
                    run_id=claim.run_id,
                    expected_count=result.rows_fetched,
                )

                result.reconcile_passed = reconcile.is_valid
                result.reconcile_expected = reconcile.expected_count
                result.reconcile_actual = reconcile.actual_count
                result.reconcile_delta = reconcile.delta

                if reconcile.is_valid:
                    logger.info(
                        "Reconcile: PASS (expected=%d actual=%d)",
                        reconcile.expected_count,
                        reconcile.actual_count,
                    )
                else:
                    logger.warning(
                        "Reconcile: FAIL (expected=%d actual=%d delta=%d)",
                        reconcile.expected_count,
                        reconcile.actual_count,
                        reconcile.delta,
                    )
                    result.error_message = f"Reconciliation failed: delta={reconcile.delta}"

            except Exception as exc:
                logger.warning("Reconcile error: %s", exc)
                # Non-fatal, continue

            # =================================================================
            # STEP 7: Commit or rollback
            # =================================================================
            if commit:
                conn.commit()
                logger.info("Transaction: COMMITTED")
                result.success = result.reconcile_passed
            else:
                conn.rollback()
                logger.info("Dry run: ROLLED BACK (use --commit to persist)")
                result.success = True  # Dry run always succeeds

    except Exception as exc:
        result.error_message = f"Unexpected error: {redact(str(exc))}"
        logger.error(result.error_message)
        logger.debug("Traceback: %s", redact(traceback.format_exc()))
        return result

    return result


# =============================================================================
# CLI
# =============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plaintiff_ingest",
        description="Production-safe, idempotent plaintiff ingestion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0  Success (including duplicate batches)
  1  Gate failure (import failed, reconciliation failed)
  2  Script error (missing file, connection error)

Examples:
  # Dry run
  python -m tools.plaintiff_ingest \\
      --csv data/plaintiffs.csv \\
      --source-system simplicity \\
      --source-batch-id batch-2026-01-17

  # Commit
  python -m tools.plaintiff_ingest \\
      --csv data/plaintiffs.csv \\
      --source-system simplicity \\
      --source-batch-id batch-2026-01-17 \\
      --commit
""",
    )

    parser.add_argument(
        "--csv",
        dest="csv_path",
        required=True,
        help="Path to CSV file containing plaintiffs",
    )
    parser.add_argument(
        "--source-system",
        dest="source_system",
        required=True,
        help="Source system identifier (e.g., 'simplicity', 'jbi', 'manual')",
    )
    parser.add_argument(
        "--source-batch-id",
        dest="source_batch_id",
        required=True,
        help="Unique batch identifier for idempotency",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Validate and report without committing (default)",
    )
    mode_group.add_argument(
        "--commit",
        action="store_true",
        help="Persist changes to database",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N rows (for testing)",
    )
    parser.add_argument(
        "--env",
        dest="env_override",
        choices=["dev", "prod"],
        default=None,
        help="Override SUPABASE_MODE",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main CLI entry point."""
    import json

    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    # Validate CSV file exists
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        logger.error("CSV file not found: %s", csv_path)
        return 2

    # Determine commit mode
    commit = args.commit
    if not commit:
        logger.warning("Dry-run mode. Use --commit to persist changes.")

    # Run ingestion
    result = run_ingestion(
        csv_path=csv_path,
        source_system=args.source_system,
        source_batch_id=args.source_batch_id,
        commit=commit,
        limit=args.limit,
        env_override=args.env_override,
    )

    # =========================================================================
    # DATA MOAT OUTPUT: JSON Summary
    # =========================================================================
    # This output format is the "Data Moat" contract:
    # - If run twice on the same file, second run MUST show inserted: 0
    # - The JSON format allows automated validation

    summary_json = {
        "inserted": result.rows_inserted,
        "skipped": result.rows_skipped,
        "errors": result.rows_errored,
        "run_id": result.run_id,
        "claim_status": result.claim_status.value if result.claim_status else None,
        "success": result.success,
        "reconcile_passed": result.reconcile_passed,
        "dry_run": not commit,
    }

    # Add duplicate indicator for clear idempotency verification
    if result.claim_status == ClaimStatus.DUPLICATE:
        summary_json["duplicate"] = True
        summary_json["message"] = "Already imported (idempotent no-op)"

    # Print summary
    print()
    print("=" * 60)
    print("INGEST SUMMARY")
    print("=" * 60)
    print(json.dumps(summary_json, indent=2))
    print("=" * 60)
    print(result.summary_line())
    print("=" * 60)

    # Return exit code
    if result.claim_status == ClaimStatus.DUPLICATE:
        return 0  # Duplicate is success (no-op)

    if result.claim_status == ClaimStatus.IN_PROGRESS:
        return 1  # Another worker has it

    if result.success:
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
