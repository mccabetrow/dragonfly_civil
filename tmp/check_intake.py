#!/usr/bin/env python3
"""Check intake table data."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url

url = get_supabase_db_url()
print(f"Connecting to: {url[:50]}...")

with psycopg.connect(url, row_factory=dict_row) as conn:
    with conn.cursor() as cur:
        # Check table columns
        cur.execute(
            """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'intake' AND table_name = 'simplicity_batches'
            ORDER BY ordinal_position
        """
        )
        print("\nsimplicity_batches columns:")
        for r in cur.fetchall():
            print(f"  {r['column_name']}: {r['data_type']}")

        # Check validated_rows columns
        cur.execute(
            """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'intake' AND table_name = 'simplicity_validated_rows'
            ORDER BY ordinal_position
        """
        )
        print("\nsimplicity_validated_rows columns:")
        for r in cur.fetchall():
            print(f"  {r['column_name']}: {r['data_type']}")

        # Check recent batches
        cur.execute(
            """
            SELECT id, filename, status, row_count_total, row_count_valid
            FROM intake.simplicity_batches 
            ORDER BY created_at DESC LIMIT 5
        """
        )
        print("\nRecent batches:")
        for r in cur.fetchall():
            print(f"  {r}")

        # Check validated rows for latest batch
        cur.execute(
            """
            SELECT case_number, judgment_amount, validation_status
            FROM intake.simplicity_validated_rows 
            ORDER BY created_at DESC LIMIT 10
        """
        )
        print("\nValidated rows:")
        for r in cur.fetchall():
            print(f"  {r}")
