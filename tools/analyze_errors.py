#!/usr/bin/env python3
"""
tools/analyze_errors.py - Error Distribution Analyzer

Analyzes error patterns in batch processing to identify common failure modes
and provide actionable recommendations.

Usage:
    python -m tools.analyze_errors --batch-id UUID
    python -m tools.analyze_errors --recent 10       # Last 10 failed batches
    python -m tools.analyze_errors --env prod

Failure Mode: High Error Rate / Quality Issues
Resolution: Identify error patterns and suggest fixes
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from psycopg import Connection

# ---------------------------------------------------------------------------
# Error Code Recommendations
# ---------------------------------------------------------------------------

ERROR_RECOMMENDATIONS = {
    "budget_exceeded": {
        "icon": "💡",
        "message": "Increase error threshold or fix input CSV quality",
        "details": [
            "The batch exceeded the allowed error percentage threshold.",
            "Options:",
            "  1. Review and fix the source CSV data",
            "  2. Increase error_threshold_percent on the batch",
            "  3. Pre-validate data before import",
        ],
    },
    "missing_required_field": {
        "icon": "📋",
        "message": "Required fields are missing from input data",
        "details": [
            "One or more required columns have NULL/empty values.",
            "Check: plaintiff_name, case_number, judgment_amount",
        ],
    },
    "invalid_date_format": {
        "icon": "📅",
        "message": "Date fields are not in expected format",
        "details": [
            "Expected formats: YYYY-MM-DD, MM/DD/YYYY",
            "Check: judgment_date, filing_date columns",
        ],
    },
    "invalid_amount": {
        "icon": "💰",
        "message": "Amount values contain invalid characters",
        "details": [
            "Amounts should be numeric (decimals OK)",
            "Remove currency symbols ($), commas, or text",
        ],
    },
    "duplicate_record": {
        "icon": "🔄",
        "message": "Duplicate records detected in batch",
        "details": [
            "The same case_number + plaintiff appears multiple times.",
            "Remove duplicates from source CSV before import.",
        ],
    },
    "validation_error": {
        "icon": "⚠️",
        "message": "Generic validation failure",
        "details": [
            "Review the specific row data for issues.",
            "Check data types and field constraints.",
        ],
    },
}

# ---------------------------------------------------------------------------
# Environment Setup
# ---------------------------------------------------------------------------


def get_config(env: str) -> dict[str, str]:
    """Load configuration for the specified environment."""
    os.environ["SUPABASE_MODE"] = env

    from src.supabase_client import get_supabase_db_url, get_supabase_env

    return {
        "env": get_supabase_env(),
        "db_url": get_supabase_db_url(),
    }


def get_batch_summary(conn: Connection, batch_id: str) -> dict | None:
    """Get batch summary info."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 
                id,
                filename,
                status,
                row_count_total,
                row_count_invalid,
                rejection_reason,
                error_threshold_percent,
                created_at
            FROM intake.simplicity_batches
            WHERE id = %s
            """,
            (batch_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))


def get_error_distribution(conn: Connection, batch_id: str) -> list[dict]:
    """
    Get error distribution for a batch.

    Tries ops.v_error_distribution view first, falls back to direct query.
    """
    with conn.cursor() as cur:
        # Check if view exists
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.views 
                WHERE table_schema = 'ops' AND table_name = 'v_error_distribution'
            )
            """
        )
        view_exists = cur.fetchone()[0]

        if view_exists:
            cur.execute(
                """
                SELECT error_code, error_count, percentage
                FROM ops.v_error_distribution
                WHERE batch_id = %s
                ORDER BY error_count DESC
                """,
                (batch_id,),
            )
        else:
            # Fallback: query batch_rows or rejection_reason
            cur.execute(
                """
                SELECT 
                    COALESCE(rejection_reason, 'unknown') as error_code,
                    1 as error_count,
                    100.0 as percentage
                FROM intake.simplicity_batches
                WHERE id = %s AND status = 'failed'
                """,
                (batch_id,),
            )

        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_recent_failed_batches(conn: Connection, limit: int = 10) -> list[dict]:
    """Get recent failed batches for analysis."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 
                id,
                filename,
                status,
                row_count_total,
                row_count_invalid,
                rejection_reason,
                created_at
            FROM intake.simplicity_batches
            WHERE status = 'failed'
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_error_summary_all(conn: Connection) -> list[dict]:
    """Get aggregated error summary across all batches."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 
                COALESCE(rejection_reason, 'unknown') as error_code,
                COUNT(*) as batch_count,
                SUM(COALESCE(row_count_invalid, row_count_total)) as total_errors
            FROM intake.simplicity_batches
            WHERE status = 'failed'
            GROUP BY rejection_reason
            ORDER BY batch_count DESC
            LIMIT 20
            """
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def format_error_table(errors: list[dict], total_errors: int = 0) -> str:
    """Format error distribution as a table."""
    if not errors:
        return "  No errors found."

    lines = []
    lines.append("  " + "-" * 60)
    lines.append(f"  {'Error Code':<30} {'Count':>10} {'% of Total':>12}")
    lines.append("  " + "-" * 60)

    for e in errors:
        code = str(e.get("error_code", "unknown"))[:29]
        count = e.get("error_count", e.get("batch_count", 0))
        pct = e.get("percentage", 0)
        if total_errors > 0 and pct == 0:
            pct = (count / total_errors) * 100
        lines.append(f"  {code:<30} {count:>10} {pct:>11.1f}%")

    lines.append("  " + "-" * 60)
    return "\n".join(lines)


def print_recommendations(errors: list[dict]) -> None:
    """Print recommendations based on error codes."""
    seen_codes = set()

    print()
    print("─" * 70)
    print("  RECOMMENDATIONS")
    print("─" * 70)

    recommendations_printed = False

    for e in errors:
        code = str(e.get("error_code", "")).lower()

        # Check for matching recommendation
        for key, rec in ERROR_RECOMMENDATIONS.items():
            if key in code and key not in seen_codes:
                seen_codes.add(key)
                recommendations_printed = True
                print()
                print(f"  {rec['icon']} {rec['message']}")
                for detail in rec["details"]:
                    print(f"     {detail}")

    if not recommendations_printed:
        print()
        print("  ℹ️  No specific recommendations available for these error codes.")
        print("     Review batch logs for detailed error information.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze error patterns in batch processing")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        help="Specific batch ID to analyze",
    )
    parser.add_argument(
        "--recent",
        type=int,
        metavar="N",
        help="Analyze last N failed batches",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show aggregated error summary across all batches",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  ERROR ANALYZER - Batch Processing Diagnostics")
    print("=" * 70)
    print(f"\n  Environment: {args.env.upper()}")
    print()

    # Load configuration
    try:
        config = get_config(args.env)
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return 1

    # Connect to database
    try:
        conn = psycopg.connect(config["db_url"])
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1

    try:
        # Mode 1: Analyze specific batch
        if args.batch_id:
            print("─" * 70)
            print(f"  Analyzing Batch: {args.batch_id}")
            print("─" * 70)

            batch = get_batch_summary(conn, args.batch_id)
            if not batch:
                print(f"  ❌ Batch not found: {args.batch_id}")
                return 1

            print(f"  File: {batch['file_name']}")
            print(f"  Status: {batch['status']}")
            print(f"  Total Rows: {batch['row_count']}")
            print(f"  Error Count: {batch['error_count']}")
            print(f"  Error Threshold: {batch['error_threshold_percent']}%")

            if batch["rejection_reason"]:
                print(f"  Rejection: {batch['rejection_reason']}")

            print()
            print("─" * 70)
            print("  ERROR DISTRIBUTION")
            print("─" * 70)

            errors = get_error_distribution(conn, args.batch_id)
            total_errors = batch["error_count"] or 0
            print(format_error_table(errors, total_errors))

            print_recommendations(errors)
            return 0

        # Mode 2: Recent failed batches
        if args.recent:
            print("─" * 70)
            print(f"  Recent Failed Batches (Last {args.recent})")
            print("─" * 70)

            batches = get_recent_failed_batches(conn, args.recent)

            if not batches:
                print("  ✅ No failed batches found")
                return 0

            print()
            print("  " + "-" * 80)
            print(f"  {'ID':<10} {'File':<25} {'Rows':>8} {'Errors':>8} {'Reason':<20}")
            print("  " + "-" * 80)

            for b in batches:
                batch_id = str(b["id"])[:8] + "..."
                file_name = (b["file_name"] or "unknown")[:24]
                rows = b["row_count"] or 0
                errors = b["error_count"] or 0
                reason = (b["rejection_reason"] or "unknown")[:19]
                print(f"  {batch_id:<10} {file_name:<25} {rows:>8} {errors:>8} {reason:<20}")

            print("  " + "-" * 80)
            print()
            print("  For detailed analysis of a specific batch:")
            print("    python -m tools.analyze_errors --batch-id <UUID>")
            return 0

        # Mode 3: Aggregated summary
        if args.summary or (not args.batch_id and not args.recent):
            print("─" * 70)
            print("  Aggregated Error Summary (All Failed Batches)")
            print("─" * 70)

            errors = get_error_summary_all(conn)

            if not errors:
                print()
                print("  ✅ No failed batches in the system")
                return 0

            print()
            print("  " + "-" * 50)
            print(f"  {'Error Code':<30} {'Batches':>10}")
            print("  " + "-" * 50)

            for e in errors:
                code = str(e.get("error_code", "unknown"))[:29]
                count = e.get("batch_count", 0)
                print(f"  {code:<30} {count:>10}")

            print("  " + "-" * 50)

            print_recommendations(errors)

            print()
            print("─" * 70)
            print("  NEXT STEPS")
            print("─" * 70)
            print()
            print("  View recent failures:")
            print("    python -m tools.analyze_errors --recent 10")
            print()
            print("  Analyze specific batch:")
            print("    python -m tools.analyze_errors --batch-id <UUID>")

            return 0

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
