"""Quick script to verify ingested judgments."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from src.supabase_client import get_supabase_db_url


def main():
    conn = psycopg.connect(get_supabase_db_url())
    cur = conn.cursor()

    # Check judgments
    cur.execute(
        """
        SELECT case_number, plaintiff_name, defendant_name, judgment_amount, collectability_score 
        FROM public.judgments 
        WHERE case_number LIKE 'TEST-INGEST-%' OR case_number LIKE 'SIMP-TEST-%'
        ORDER BY case_number
    """
    )
    print("=== Ingested Judgments ===")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[2]} owes {row[1]} ${row[3]:,.2f} (score: {row[4]})")

    # Check batch status
    cur.execute(
        """
        SELECT id, source, filename, status, row_count_valid 
        FROM ops.ingest_batches 
        WHERE source = 'manual_test'
        ORDER BY created_at DESC
        LIMIT 5
    """
    )
    print("\n=== Batch Status ===")
    for row in cur.fetchall():
        print(f"  {str(row[0])[:8]}... | {row[2]} | status={row[3]} | valid={row[4]}")

    # Check job status
    cur.execute(
        """
        SELECT id, job_type, status, attempts
        FROM ops.job_queue
        WHERE job_type = 'ingest_csv'
        ORDER BY created_at DESC
        LIMIT 5
    """
    )
    print("\n=== Job Queue ===")
    for row in cur.fetchall():
        print(f"  {str(row[0])[:8]}... | {row[1]} | status={row[2]} | attempts={row[3]}")

    conn.close()


if __name__ == "__main__":
    main()
