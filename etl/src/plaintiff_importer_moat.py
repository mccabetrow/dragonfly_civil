"""Enhanced plaintiff importer with ingestion moat protection.

This module wraps the core plaintiff importer with production-grade features:

1. **Ingestion Moat**: Atomic claim/finalize/rollback via ingest.* RPC functions
2. **Log Redaction**: SSN and card patterns are never logged
3. **Idempotency**: Duplicate batches are detected and skipped gracefully
4. **Audit Trail**: Full tracking of all import attempts in ingest.import_runs

Workflow:
    1. Compute file hash and claim the batch via ingest.claim_import_run()
    2. If duplicate: exit 0 with "duplicate batch" message
    3. If in_progress: exit 1 with "another worker processing" message
    4. If claimed: proceed with import
    5. On success: finalize with counts
    6. On failure: finalize with error details

Usage:
    python -m etl.src.plaintiff_importer_moat --csv data/plaintiffs.csv --commit

    # With explicit source system
    python -m etl.src.plaintiff_importer_moat \\
        --csv data/simplicity_export.csv \\
        --source-system simplicity \\
        --commit
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

from etl.src.ingest_claim import ClaimStatus, IngestClaimClient, compute_batch_id, compute_file_hash
from etl.src.log_redactor import SafeLogger, redact
from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env

# Use SafeLogger to prevent PII leakage
_raw_logger = logging.getLogger(__name__)
logger = SafeLogger(_raw_logger)


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class ImportResult:
    """Result of an import operation."""

    success: bool
    run_id: Optional[str] = None
    claim_status: Optional[ClaimStatus] = None
    rows_fetched: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    rows_errored: int = 0
    error_message: Optional[str] = None
    examples: list[str] = field(default_factory=list)


# =============================================================================
# CORE IMPORT LOGIC
# =============================================================================


def _resolve_db_target() -> tuple[str, str, str, str]:
    """Resolve database connection details."""
    env = get_supabase_env()
    url = get_supabase_db_url(env)
    host, dbname, user = describe_db_url(url)
    logger.info(
        "Connecting to db host=%s dbname=%s user=%s env=%s",
        host,
        dbname,
        user,
        env,
    )
    return env, url, host, dbname


def _ensure_required_tables(conn: Connection, env: str, host: str, dbname: str) -> bool:
    """Verify required tables exist."""
    required = [
        ("public", "plaintiffs"),
        ("public", "plaintiff_contacts"),
        ("ingest", "import_runs"),
    ]

    with conn.cursor() as cur:
        for schema, table in required:
            cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                (schema, table),
            )
            if not cur.fetchone():
                logger.error(
                    "Required table %s.%s not found in %s/%s (env=%s). "
                    "Have migrations been applied?",
                    schema,
                    table,
                    host,
                    dbname,
                    env,
                )
                return False
    return True


def _process_csv_with_moat(
    conn: Connection,
    csv_path: Path,
    source_system: str,
    batch_id: str,
    file_hash: str,
    *,
    commit: bool,
    limit: Optional[int] = None,
) -> ImportResult:
    """Process CSV with full ingestion moat protection.

    Returns:
        ImportResult with success status and counts.
    """
    result = ImportResult(success=False)

    # =========================================================================
    # STEP 1: Claim the batch
    # =========================================================================
    client = IngestClaimClient(conn)

    claim = client.claim(
        source_system=source_system,
        source_batch_id=batch_id,
        file_hash=file_hash,
        filename=csv_path.name,
        import_kind="plaintiff",
    )

    result.run_id = str(claim.run_id)
    result.claim_status = claim.status

    if claim.is_duplicate:
        logger.info(
            "Duplicate batch detected (run_id=%s). File already imported successfully.",
            claim.run_id,
        )
        result.success = True
        return result

    if claim.is_in_progress:
        logger.warning(
            "Batch is being processed by another worker (run_id=%s). Retry later.",
            claim.run_id,
        )
        result.success = False
        result.error_message = "Another worker is processing this batch"
        return result

    # =========================================================================
    # STEP 2: Import using the core plaintiff importer
    # =========================================================================
    logger.info(
        "Claimed batch (run_id=%s, source=%s, batch=%s)",
        claim.run_id,
        source_system,
        batch_id,
    )

    try:
        # Import the core processor
        from etl.src.plaintiff_importer import ImportStats, _process_candidates, _read_csv

        # Parse CSV
        parse_result = _read_csv(csv_path, limit=limit)
        result.rows_fetched = parse_result.total_rows
        result.rows_skipped = parse_result.rows_skipped

        if not parse_result.candidates:
            logger.warning("No valid plaintiff rows parsed from %s", csv_path.name)
            result.success = True
            client.finalize(
                run_id=claim.run_id,
                rows_fetched=result.rows_fetched,
                rows_inserted=0,
                rows_skipped=result.rows_skipped,
                rows_errored=0,
            )
            return result

        # Process candidates
        stats = ImportStats(
            total_rows=parse_result.total_rows,
            rows_skipped=parse_result.rows_skipped,
        )

        _process_candidates(conn, parse_result.candidates, commit=commit, stats=stats)

        if commit:
            conn.commit()

        # Update result
        result.rows_inserted = stats.created_plaintiffs + stats.created_contacts
        result.examples = stats.examples[:3]
        result.success = True

        # Finalize the run
        client.finalize(
            run_id=claim.run_id,
            rows_fetched=result.rows_fetched,
            rows_inserted=result.rows_inserted,
            rows_skipped=result.rows_skipped,
            rows_errored=0,
        )

        logger.info(
            "Import completed (run_id=%s): fetched=%d inserted=%d skipped=%d",
            claim.run_id,
            result.rows_fetched,
            result.rows_inserted,
            result.rows_skipped,
        )

    except Exception as exc:
        # =====================================================================
        # STEP 3: Handle failure - finalize with error
        # =====================================================================
        result.success = False
        result.error_message = redact(str(exc))  # Redact any PII in error message
        result.rows_errored = 1

        logger.error(
            "Import failed (run_id=%s): %s",
            claim.run_id,
            result.error_message,
        )

        # Finalize with error details
        try:
            client.finalize(
                run_id=claim.run_id,
                rows_fetched=result.rows_fetched,
                rows_inserted=result.rows_inserted,
                rows_skipped=result.rows_skipped,
                rows_errored=result.rows_errored,
                error_details={
                    "fatal": True,
                    "message": result.error_message,
                    "type": type(exc).__name__,
                },
            )
        except Exception as finalize_exc:
            logger.error(
                "Failed to finalize run (run_id=%s): %s",
                claim.run_id,
                finalize_exc,
            )

    return result


# =============================================================================
# CLI
# =============================================================================


def _configure_logging(verbose: bool) -> None:
    """Configure logging with PII redaction filter."""
    from etl.src.log_redactor import PIIRedactionFilter

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")

    # Add PII filter to root logger
    root_logger = logging.getLogger()
    root_logger.addFilter(PIIRedactionFilter())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import plaintiffs from CSV with ingestion moat protection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (default)
  python -m etl.src.plaintiff_importer_moat --csv data/plaintiffs.csv

  # Commit changes
  python -m etl.src.plaintiff_importer_moat --csv data/plaintiffs.csv --commit

  # With explicit source system
  python -m etl.src.plaintiff_importer_moat \\
      --csv data/simplicity_export.csv \\
      --source-system simplicity \\
      --commit
""",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        required=True,
        help="Path to the CSV file containing plaintiffs",
    )
    parser.add_argument(
        "--source-system",
        dest="source_system",
        default="manual",
        help="Source system identifier (default: 'manual')",
    )
    parser.add_argument(
        "--batch-id",
        dest="batch_id",
        default=None,
        help="Explicit batch ID (default: auto-generated from filename)",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing to the database (default)",
    )
    mode_group.add_argument(
        "--commit",
        action="store_true",
        help="Apply the changes to the database",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N data rows (for smoke tests)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    return parser


def run_cli(argv: Optional[Sequence[str]] = None) -> int:
    """Main CLI entry point.

    Returns:
        0 on success or duplicate
        1 on in_progress or error
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        logger.error("CSV file not found: %s", csv_path)
        return 1

    # Determine mode
    commit = args.commit
    if not commit and not args.dry_run:
        logger.warning(
            "No mode flag supplied; defaulting to dry-run. Pass --commit to persist changes."
        )

    # Compute file hash and batch ID
    try:
        file_hash = compute_file_hash(csv_path)
        batch_id = args.batch_id or compute_batch_id(args.source_system, csv_path.name)
    except Exception as exc:
        logger.error("Failed to compute file hash: %s", exc)
        return 1

    logger.info(
        "Starting import: file=%s source=%s batch=%s hash=%s",
        csv_path.name,
        args.source_system,
        batch_id,
        file_hash[:12] + "...",
    )

    # Resolve database
    try:
        target_env, db_url, host, dbname = _resolve_db_target()
    except Exception as exc:
        logger.error("Unable to resolve Supabase database URL: %s", exc)
        return 1

    # Run import
    try:
        with psycopg.connect(db_url, autocommit=not commit) as conn:
            # Verify tables exist
            if not _ensure_required_tables(conn, target_env, host, dbname):
                return 1

            # Process with moat
            result = _process_csv_with_moat(
                conn,
                csv_path,
                source_system=args.source_system,
                batch_id=batch_id,
                file_hash=file_hash,
                commit=commit,
                limit=args.limit,
            )

            # Return code based on result
            if result.claim_status == ClaimStatus.DUPLICATE:
                logger.info("Exit 0: duplicate batch (already imported)")
                return 0

            if result.claim_status == ClaimStatus.IN_PROGRESS:
                logger.info("Exit 1: another worker is processing this batch")
                return 1

            if result.success:
                if not commit:
                    logger.info("Dry run complete. Re-run with --commit to persist changes.")
                return 0
            else:
                logger.error("Import failed: %s", result.error_message)
                return 1

    except Exception as exc:
        logger.error("Unexpected error: %s", redact(str(exc)))
        logger.debug("Traceback: %s", redact(traceback.format_exc()))
        return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Synchronous main entry point."""
    return run_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
