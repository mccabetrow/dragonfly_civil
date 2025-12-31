#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
tools/generate_announcement.py - Go-Live Announcement Generator
═══════════════════════════════════════════════════════════════════════════════

Purpose:
    Automatically generate the Go-Live announcement email/Slack message
    with real metrics from the production system.

Features:
    - Runs doctor checks and captures pass/fail counts
    - Queries ops.v_batch_performance for recent metrics
    - Queries intake.simplicity_batches for batch counts
    - Formats a professional announcement template

Usage:
    # Generate announcement for prod
    python -m tools.generate_announcement --env prod

    # Generate for dev (testing)
    python -m tools.generate_announcement --env dev

    # Output to file
    python -m tools.generate_announcement --env prod --output announcement.md

Output:
    Prints a formatted Go-Live announcement with real system metrics.

Author: Dragonfly Release Team
Created: 2025-01-05
═══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═══════════════════════════════════════════════════════════════════════════


def run_doctor_checks(env: str) -> dict[str, Any]:
    """
    Run doctor checks and return pass/fail counts.
    Uses direct database queries to count check results.
    """
    try:
        db_url = get_supabase_db_url(env)
        passed = 0
        total = 0

        with psycopg.connect(db_url) as conn:
            # Check 1: Database connection
            total += 1
            passed += 1  # If we're here, connection works

            # Check 2: RPC functions exist
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public'
                    AND p.proname IN ('queue_job', 'claim_next_job', 'complete_job', 'fail_job')
                    """
                )
                rpc_count = cur.fetchone()[0]
                total += 1
                if rpc_count >= 4:
                    passed += 1

            # Check 3: Critical views exist
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.views
                    WHERE table_schema = 'public'
                    AND table_name IN ('v_plaintiffs_overview', 'v_judgment_pipeline', 'v_enforcement_overview')
                    """
                )
                view_count = cur.fetchone()[0]
                total += 1
                if view_count >= 3:
                    passed += 1

            # Check 4: RLS enabled on critical tables
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM pg_tables
                    WHERE schemaname = 'public'
                    AND tablename IN ('jobs', 'plaintiffs')
                    AND rowsecurity = true
                    """
                )
                rls_count = cur.fetchone()[0]
                total += 1
                if rls_count >= 2:
                    passed += 1

        return {
            "passed": passed,
            "total": total,
            "all_passed": passed == total,
        }
    except Exception as e:
        return {
            "passed": 0,
            "total": 0,
            "all_passed": False,
            "error": str(e),
        }


def get_batch_metrics(conn: psycopg.Connection) -> dict[str, Any]:
    """
    Query ops.v_batch_performance for recent metrics.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    SUM(total_batches) as total_batches,
                    SUM(completed_batches) as completed_batches,
                    SUM(failed_batches) as failed_batches,
                    SUM(total_rows) as total_rows,
                    SUM(inserted_rows) as inserted_rows,
                    SUM(skipped_rows) as skipped_rows,
                    AVG(avg_total_ms) as avg_processing_ms,
                    AVG(dedupe_rate_pct) as avg_dedupe_pct,
                    AVG(error_rate_pct) as avg_error_pct
                FROM ops.v_batch_performance
                WHERE hour_bucket >= NOW() - INTERVAL '24 hours'
                """
            )
            row = cur.fetchone()
            if row:
                return {
                    "total_batches": row[0] or 0,
                    "completed_batches": row[1] or 0,
                    "failed_batches": row[2] or 0,
                    "total_rows": row[3] or 0,
                    "inserted_rows": row[4] or 0,
                    "skipped_rows": row[5] or 0,
                    "avg_processing_ms": round(row[6] or 0, 2),
                    "avg_dedupe_pct": round(row[7] or 0, 2),
                    "avg_error_pct": round(row[8] or 0, 2),
                }
    except Exception as e:
        print(f"  ⚠️  Warning: Could not query v_batch_performance: {e}")

    return {
        "total_batches": 0,
        "completed_batches": 0,
        "failed_batches": 0,
        "total_rows": 0,
        "inserted_rows": 0,
        "skipped_rows": 0,
        "avg_processing_ms": 0,
        "avg_dedupe_pct": 0,
        "avg_error_pct": 0,
    }


def get_batch_summary(conn: psycopg.Connection) -> dict[str, Any]:
    """
    Get batch summary counts from intake.simplicity_batches.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'processing') as processing,
                    COUNT(*) FILTER (WHERE status = 'uploaded') as pending
                FROM intake.simplicity_batches
                """
            )
            row = cur.fetchone()
            if row:
                return {
                    "total": row[0] or 0,
                    "completed": row[1] or 0,
                    "failed": row[2] or 0,
                    "processing": row[3] or 0,
                    "pending": row[4] or 0,
                }
    except Exception as e:
        print(f"  ⚠️  Warning: Could not query batch summary: {e}")

    return {"total": 0, "completed": 0, "failed": 0, "processing": 0, "pending": 0}


def get_plaintiff_counts(conn: psycopg.Connection) -> dict[str, Any]:
    """
    Get plaintiff counts from public.plaintiffs.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) as total
                FROM public.plaintiffs
                """
            )
            row = cur.fetchone()
            total = row[0] if row else 0

            cur.execute(
                """
                SELECT COUNT(*) as total
                FROM public.plaintiff_contacts
                """
            )
            row = cur.fetchone()
            contacts = row[0] if row else 0

            return {"plaintiffs": total, "contacts": contacts}
    except Exception as e:
        print(f"  ⚠️  Warning: Could not query plaintiff counts: {e}")

    return {"plaintiffs": 0, "contacts": 0}


def reload_postgrest(conn: psycopg.Connection) -> bool:
    """
    Reload PostgREST schema cache.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("NOTIFY pgrst, 'reload schema';")
            conn.commit()
            return True
    except Exception as e:
        print(f"  ⚠️  Warning: Could not reload PostgREST: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════


def generate_announcement(
    env: str,
    doctor_results: dict[str, Any],
    batch_metrics: dict[str, Any],
    batch_summary: dict[str, Any],
    plaintiff_counts: dict[str, Any],
    postgrest_reloaded: bool,
) -> str:
    """
    Generate the Go-Live announcement message.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    env_display = "PRODUCTION" if env == "prod" else "DEVELOPMENT"

    # Calculate success rate
    total = batch_summary.get("completed", 0) + batch_summary.get("failed", 0)
    success_rate = (batch_summary.get("completed", 0) / total * 100) if total > 0 else 100.0

    # Doctor status
    doctor_status = "✅ ALL PASSED" if doctor_results.get("all_passed") else "⚠️ SOME FAILED"
    doctor_detail = (
        f"{doctor_results.get('passed', 0)}/{doctor_results.get('total', 0)} checks passed"
    )

    # PostgREST status
    pgrst_status = "✅ Reloaded" if postgrest_reloaded else "⚠️ Manual reload needed"

    announcement = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                    🚀 DRAGONFLY CIVIL - GO-LIVE ANNOUNCEMENT 🚀              ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Environment:  {env_display.ljust(60)}║
║  Timestamp:    {timestamp.ljust(60)}║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  SYSTEM HEALTH                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Doctor Checks:     {doctor_status} ({doctor_detail}){' ' * (35 - len(doctor_detail))}║
║  PostgREST Cache:   {pgrst_status.ljust(55)}║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  BATCH PIPELINE METRICS (Last 24 Hours)                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Total Batches:     {str(batch_metrics.get('total_batches', 0)).ljust(55)}║
║  Completed:         {str(batch_metrics.get('completed_batches', 0)).ljust(55)}║
║  Failed:            {str(batch_metrics.get('failed_batches', 0)).ljust(55)}║
║  Success Rate:      {f"{success_rate:.1f}%".ljust(55)}║
║                                                                              ║
║  Rows Processed:    {str(batch_metrics.get('total_rows', 0)).ljust(55)}║
║  Rows Inserted:     {str(batch_metrics.get('inserted_rows', 0)).ljust(55)}║
║  Duplicates Skipped:{str(batch_metrics.get('skipped_rows', 0)).ljust(55)}║
║                                                                              ║
║  Avg Processing:    {f"{batch_metrics.get('avg_processing_ms', 0)}ms".ljust(55)}║
║  Dedupe Rate:       {f"{batch_metrics.get('avg_dedupe_pct', 0)}%".ljust(55)}║
║  Error Rate:        {f"{batch_metrics.get('avg_error_pct', 0)}%".ljust(55)}║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  DATA SUMMARY                                                                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Total Batches (All Time):  {str(batch_summary.get('total', 0)).ljust(47)}║
║  Plaintiffs in System:      {str(plaintiff_counts.get('plaintiffs', 0)).ljust(47)}║
║  Plaintiff Contacts:        {str(plaintiff_counts.get('contacts', 0)).ljust(47)}║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  NEXT STEPS                                                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  1. Monitor Sentinel:  python -m backend.workers.sentinel --json             ║
║  2. Check Dashboard:   https://dragonfly-dashboard.vercel.app                ║
║  3. Review Logs:       Supabase Dashboard → Logs → API                       ║
║                                                                              ║
║  For issues, see:      docs/RUNBOOK_GO_LIVE.md                               ║
║                                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║                    THE INTAKE PIPELINE IS NOW LIVE ✨                        ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

    return announcement


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate Go-Live Announcement with Real Metrics")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=get_supabase_env(),
        help="Target environment (default: from SUPABASE_MODE)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path (optional, defaults to stdout)",
    )

    args = parser.parse_args()

    print()
    print("═" * 70)
    print("  📢 GO-LIVE ANNOUNCEMENT GENERATOR")
    print("═" * 70)
    print(f"\n  Environment: {args.env.upper()}")
    print()
    print("─" * 70)
    print("  Collecting metrics...")
    print("─" * 70)

    # Collect data
    print("\n  📋 Running doctor checks...")
    doctor_results = run_doctor_checks(args.env)
    print(f"     {doctor_results.get('passed', 0)}/{doctor_results.get('total', 0)} checks passed")

    db_url = get_supabase_db_url(args.env)

    try:
        with psycopg.connect(db_url) as conn:
            print("\n  🔄 Reloading PostgREST cache...")
            postgrest_ok = reload_postgrest(conn)
            print(f"     {'✅ Reloaded' if postgrest_ok else '⚠️ Failed'}")

            print("\n  📊 Querying batch metrics...")
            batch_metrics = get_batch_metrics(conn)
            print(f"     {batch_metrics.get('total_batches', 0)} batches in last 24h")

            print("\n  📋 Querying batch summary...")
            batch_summary = get_batch_summary(conn)
            print(f"     {batch_summary.get('total', 0)} total batches")

            print("\n  👥 Querying plaintiff counts...")
            plaintiff_counts = get_plaintiff_counts(conn)
            print(f"     {plaintiff_counts.get('plaintiffs', 0)} plaintiffs")

    except Exception as e:
        print(f"\n  ❌ Database error: {e}")
        return 1

    # Generate announcement
    print("\n" + "─" * 70)
    print("  Generating announcement...")
    print("─" * 70)

    announcement = generate_announcement(
        env=args.env,
        doctor_results=doctor_results,
        batch_metrics=batch_metrics,
        batch_summary=batch_summary,
        plaintiff_counts=plaintiff_counts,
        postgrest_reloaded=postgrest_ok,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(announcement, encoding="utf-8")
        print(f"\n  ✅ Announcement saved to: {output_path}")
    else:
        print(announcement)

    return 0


if __name__ == "__main__":
    sys.exit(main())
