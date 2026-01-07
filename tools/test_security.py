#!/usr/bin/env python3
"""
Test script for security schema and middleware.

Usage:
    python -m tools.test_security [--env dev|prod]
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg


def main() -> int:
    parser = argparse.ArgumentParser(description="Test security schema")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    args = parser.parse_args()

    os.environ["SUPABASE_MODE"] = args.env

    from src.supabase_client import get_supabase_db_url

    db_url = get_supabase_db_url()
    print(f"Testing security schema on {args.env}...\n")

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # 1. Check security schema exists
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s",
                ("security",),
            )
            schema_exists = cur.fetchone()[0] > 0
            print(f"[{'✓' if schema_exists else '✗'}] security schema exists")

            if not schema_exists:
                print("\n❌ security schema not found. Run migrations first.")
                return 1

            # 2. Check incidents table
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                ("security", "incidents"),
            )
            table_exists = cur.fetchone()[0] > 0
            print(f"[{'✓' if table_exists else '✗'}] security.incidents table exists")

            # 3. Check log_incident function
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema = %s AND routine_name = %s",
                ("security", "log_incident"),
            )
            func_exists = cur.fetchone()[0] > 0
            print(f"[{'✓' if func_exists else '✗'}] security.log_incident function exists")

            # 4. Test inserting an incident
            print("\n--- Testing incident logging ---")
            cur.execute(
                """
                SELECT security.log_incident(
                    'info'::security.incident_severity,
                    'test_security_script',
                    '127.0.0.1'::inet,
                    NULL::uuid,
                    '/api/v1/test',
                    'GET',
                    'TestScript/1.0',
                    '{"test": true}'::jsonb
                )
            """
            )
            incident_id = cur.fetchone()[0]
            print(f"[✓] Created test incident: {incident_id}")

            # 5. Verify the incident
            cur.execute(
                "SELECT severity, event_type, source_ip, request_path FROM security.incidents WHERE id = %s",
                (incident_id,),
            )
            row = cur.fetchone()
            print(
                f"[✓] Verified incident: severity={row[0]}, event={row[1]}, ip={row[2]}, path={row[3]}"
            )

            # 6. Test get_recent_incidents_by_ip
            cur.execute(
                "SELECT * FROM security.get_recent_incidents_by_ip('127.0.0.1'::inet, NULL, 60)"
            )
            recent = cur.fetchone()
            print(
                f"[✓] Recent incidents from 127.0.0.1: {recent[0]} found (first: {recent[1]}, last: {recent[2]})"
            )

            # 7. Test get_incident_summary
            cur.execute("SELECT * FROM security.get_incident_summary(24)")
            summary = cur.fetchall()
            print(f"[✓] Incident summary (24h): {len(summary)} event types")
            for row in summary:
                print(f"    {row[0]} / {row[1]}: {row[2]} incidents from {row[3]} IPs")

            # 8. Clean up test incident
            cur.execute("DELETE FROM security.incidents WHERE id = %s", (incident_id,))
            print("[✓] Cleaned up test incident")

            conn.commit()

    print("\n✅ All security schema tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
