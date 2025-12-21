#!/usr/bin/env python3
"""Check judgments and queue final test."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url

url = get_supabase_db_url()
with psycopg.connect(url, row_factory=dict_row) as conn:
    with conn.cursor() as cur:
        # Check inserted judgments
        cur.execute(
            """
            SELECT case_number, plaintiff_name, defendant_name, judgment_amount, county, status, source_file
            FROM public.judgments
            WHERE case_number LIKE '2024-CV-%'
            ORDER BY case_number
        """
        )
        print("Inserted judgments:")
        for r in cur.fetchall():
            print(
                f"  {r['case_number']}: {r['plaintiff_name']} vs {r['defendant_name']} - ${r['judgment_amount']} ({r['county']})"
            )

        # Queue one more job for final verification with the log message
        cur.execute(
            """
            SELECT ops.queue_job('simplicity_ingest', JSONB_BUILD_OBJECT(
                'file_path', 'file://data_in/simplicity_smoke_test.csv'
            ))
        """
        )
        result = cur.fetchone()
        job_id = result["queue_job"]
        conn.commit()
        print(f"\nQueued final test job: {job_id}")
