#!/usr/bin/env python
"""
Plaintiff Promotion Tool

Promotes plaintiffs from ingest.plaintiffs_raw (pending) to public.plaintiffs.

Workflow:
  1. pending → processing (lock rows being promoted)
  2. Insert into public.plaintiffs
  3. processing → promoted (mark as complete)

Usage:
  python -m tools.plaintiff_promote --batch-size 100 --dry-run
  python -m tools.plaintiff_promote --commit
  python -m tools.plaintiff_promote --run-id <uuid> --commit  # Promote specific batch
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class PromotionResult:
    """Result of a promotion run."""

    promoted: int = 0
    skipped: int = 0
    errors: int = 0
    dry_run: bool = True
    success: bool = False
    error_message: Optional[str] = None
    promoted_ids: list[str] = field(default_factory=list)


def get_default_org_id(conn: psycopg.Connection) -> uuid.UUID:
    """Get the default organization ID from tenant.orgs."""
    with conn.cursor(row_factory=dict_row) as cur:
        # Get existing org from tenant.orgs
        cur.execute("SELECT id FROM tenant.orgs LIMIT 1")
        row = cur.fetchone()
        if row:
            return uuid.UUID(str(row["id"]))

        # Fallback: check if there's an existing plaintiff and use their org_id
        cur.execute("SELECT org_id FROM public.plaintiffs LIMIT 1")
        row = cur.fetchone()
        if row:
            return uuid.UUID(str(row["org_id"]))

        raise RuntimeError("No organization found in tenant.orgs. Create one first.")


def promote_plaintiffs(
    conn: psycopg.Connection,
    batch_size: int = 100,
    run_id: Optional[uuid.UUID] = None,
    dry_run: bool = True,
) -> PromotionResult:
    """
    Promote pending plaintiffs from ingest.plaintiffs_raw to public.plaintiffs.

    Args:
        conn: Database connection
        batch_size: Maximum rows to promote in one run
        run_id: Optional specific import_run_id to promote
        dry_run: If True, rollback instead of commit

    Returns:
        PromotionResult with counts and status
    """
    result = PromotionResult(dry_run=dry_run)

    try:
        with conn.transaction():
            org_id = get_default_org_id(conn)
            logger.info(f"Using org_id: {org_id}")

            with conn.cursor(row_factory=dict_row) as cur:
                # Step 1: Lock pending rows for promotion
                if run_id:
                    cur.execute(
                        """
                        UPDATE ingest.plaintiffs_raw
                        SET status = 'processing', updated_at = now()
                        WHERE status = 'pending' AND import_run_id = %s
                        RETURNING id, dedupe_key, plaintiff_name, contact_email, 
                                  contact_phone, contact_address, firm_name, short_name,
                                  source_system, source_reference, import_run_id, 
                                  row_index, raw_payload
                    """,
                        (str(run_id),),
                    )
                else:
                    # Use subquery for LIMIT since PostgreSQL UPDATE doesn't support LIMIT directly
                    cur.execute(
                        """
                        UPDATE ingest.plaintiffs_raw pr
                        SET status = 'processing', updated_at = now()
                        FROM (
                            SELECT id FROM ingest.plaintiffs_raw
                            WHERE status = 'pending'
                            ORDER BY created_at
                            LIMIT %s
                            FOR UPDATE SKIP LOCKED
                        ) sub
                        WHERE pr.id = sub.id
                        RETURNING pr.id, pr.dedupe_key, pr.plaintiff_name, pr.contact_email, 
                                  pr.contact_phone, pr.contact_address, pr.firm_name, pr.short_name,
                                  pr.source_system, pr.source_reference, pr.import_run_id, 
                                  pr.row_index, pr.raw_payload
                    """,
                        (batch_size,),
                    )

                rows_to_promote = cur.fetchall()

                if not rows_to_promote:
                    logger.info("No pending plaintiffs to promote")
                    result.success = True
                    return result

                logger.info(f"Locked {len(rows_to_promote)} rows for promotion")

                # Step 2: Insert into public.plaintiffs
                for row in rows_to_promote:
                    try:
                        # Check for existing by normalized name (dedupe_key in public.plaintiffs is generated from name)
                        # Use normalize_party_name function to match the generated column
                        cur.execute(
                            """
                            SELECT id FROM public.plaintiffs 
                            WHERE dedupe_key = normalize_party_name(%s)
                        """,
                            (row["plaintiff_name"] or "Unknown",),
                        )

                        if cur.fetchone():
                            # Already exists - mark as promoted (duplicate)
                            cur.execute(
                                """
                                UPDATE ingest.plaintiffs_raw
                                SET status = 'promoted', 
                                    promoted_at = now(),
                                    updated_at = now()
                                WHERE id = %s
                            """,
                                (str(row["id"]),),
                            )
                            result.skipped += 1
                            continue

                        # Insert new plaintiff (omit name_normalized & dedupe_key - they're GENERATED columns)
                        # Note: source_batch_id references intake.simplicity_batches, not ingest.import_runs
                        cur.execute(
                            """
                            INSERT INTO public.plaintiffs (
                                name,
                                short_name,
                                firm_name,
                                status,
                                source_system,
                                source_reference,
                                source_row_index,
                                email,
                                phone,
                                org_id,
                                metadata,
                                first_ingested_at
                            ) VALUES (
                                %s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s, now()
                            )
                            RETURNING id
                        """,
                            (
                                row["plaintiff_name"] or "Unknown",
                                row["short_name"],
                                row["firm_name"],
                                row["source_system"],
                                row["source_reference"],
                                row["row_index"],
                                row["contact_email"],
                                row["contact_phone"],
                                str(org_id),
                                json.dumps(row["raw_payload"]) if row["raw_payload"] else "{}",
                            ),
                        )

                        new_plaintiff = cur.fetchone()

                        # Mark raw row as promoted
                        cur.execute(
                            """
                            UPDATE ingest.plaintiffs_raw
                            SET status = 'promoted',
                                promoted_at = now(),
                                promoted_plaintiff_id = %s,
                                updated_at = now()
                            WHERE id = %s
                        """,
                            (str(new_plaintiff["id"]), str(row["id"])),
                        )

                        result.promoted += 1
                        result.promoted_ids.append(str(new_plaintiff["id"]))

                    except Exception as e:
                        logger.error(f"Failed to promote row {row['id']}: {e}")
                        # Mark as failed
                        cur.execute(
                            """
                            UPDATE ingest.plaintiffs_raw
                            SET status = 'failed',
                                error_details = %s,
                                updated_at = now()
                            WHERE id = %s
                        """,
                            (json.dumps({"error": str(e)}), str(row["id"])),
                        )
                        result.errors += 1

                if dry_run:
                    logger.info("Dry run: ROLLING BACK")
                    raise DryRunRollback()

                result.success = True

    except DryRunRollback:
        result.success = True
    except Exception as e:
        logger.error(f"Promotion failed: {e}")
        result.error_message = str(e)
        result.success = False

    return result


class DryRunRollback(Exception):
    """Raised to trigger rollback in dry-run mode."""

    pass


def main():
    parser = argparse.ArgumentParser(description="Promote plaintiffs from ingest to public")
    parser.add_argument("--batch-size", type=int, default=100, help="Max rows to promote")
    parser.add_argument("--run-id", type=str, help="Specific import_run_id to promote")
    parser.add_argument(
        "--dry-run", action="store_true", default=True, help="Rollback instead of commit"
    )
    parser.add_argument("--commit", action="store_true", help="Actually commit changes")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev", help="Environment")

    args = parser.parse_args()

    dry_run = not args.commit

    if dry_run:
        logger.info("Dry-run mode. Use --commit to persist changes.")

    # Get database URL
    try:
        db_url = get_supabase_db_url(env=args.env)
    except Exception:
        import os

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            logger.error("DATABASE_URL not set")
            sys.exit(1)

    logger.info(f"Database: {describe_db_url(db_url)} env={args.env}")

    run_id = uuid.UUID(args.run_id) if args.run_id else None

    with psycopg.connect(db_url) as conn:
        result = promote_plaintiffs(
            conn=conn,
            batch_size=args.batch_size,
            run_id=run_id,
            dry_run=dry_run,
        )

    # Print summary
    print("\n" + "=" * 60)
    print("PROMOTION SUMMARY")
    print("=" * 60)
    print(
        json.dumps(
            {
                "promoted": result.promoted,
                "skipped": result.skipped,
                "errors": result.errors,
                "success": result.success,
                "dry_run": result.dry_run,
            },
            indent=2,
        )
    )
    print("=" * 60)

    if result.success:
        status = "PASS" if result.promoted > 0 else "NO-OP"
        print(
            f"{status}: promoted={result.promoted} skipped={result.skipped} errors={result.errors}"
        )
    else:
        print(f"FAIL: {result.error_message}")

    print("=" * 60)

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
