"""Query DB contract truth.

Verifies canonical RPC signatures and checks for ambiguous overloads.
Used by deploy_db_prod.ps1 to show contract truth after migration.
"""

import sys

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url


def main():
    try:
        conn = psycopg.connect(get_supabase_db_url())
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        sys.exit(1)

    cur = conn.cursor(row_factory=dict_row)

    # ========================================================================
    # CONTRACT TRUTH - RPC Signatures with Overload Detection
    # ========================================================================
    print("=" * 70)
    print("CONTRACT TRUTH - Canonical RPC Signatures")
    print("=" * 70)
    print()

    cur.execute(
        """
        SELECT
            n.nspname || '.' || p.proname AS function_name,
            pg_get_function_identity_arguments(p.oid) AS signature,
            pg_get_function_result(p.oid) AS return_type,
            CASE WHEN p.prosecdef THEN 'SECURITY DEFINER' ELSE 'SECURITY INVOKER' END AS security,
            (SELECT COUNT(*) FROM pg_proc p2
             JOIN pg_namespace n2 ON p2.pronamespace = n2.oid
             WHERE n2.nspname = 'ops' AND p2.proname = p.proname) AS overload_count
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'ops'
          AND p.proname IN (
              'claim_pending_job',
              'update_job_status',
              'queue_job',
              'register_heartbeat'
          )
        ORDER BY p.proname;
    """
    )

    issues = []
    for row in cur.fetchall():
        func_name = row["function_name"]
        signature = row["signature"]
        return_type = row["return_type"]
        security = row["security"]
        overload_count = row["overload_count"]

        print(f"{func_name}({signature})")
        print(f"  -> {return_type}")
        print(f"  [{security}]")

        if overload_count > 1:
            print(f"  ⚠️  WARNING: {overload_count} overloads exist!")
            issues.append(f"{func_name} has {overload_count} overloads")
        else:
            print("  ✅ Single signature (no ambiguity)")
        print()

    print("=" * 70)

    if issues:
        print("⚠️  ISSUES DETECTED:")
        for issue in issues:
            print(f"  - {issue}")
        print()
        print("Consider dropping old overloads before redeploying workers.")
    else:
        print("✅ All functions have single canonical signatures")

    print()

    # ========================================================================
    # Additional Info - Table Columns
    # ========================================================================
    print()
    print("=== ops.job_queue columns ===")
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='ops' AND table_name='job_queue'
        ORDER BY ordinal_position
    """
    )
    for row in cur.fetchall():
        print(f"  {row['column_name']}: {row['data_type']}")

    print()
    print("=== ops.worker_heartbeats columns ===")
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='ops' AND table_name='worker_heartbeats'
        ORDER BY ordinal_position
    """
    )
    for row in cur.fetchall():
        print(f"  {row['column_name']}: {row['data_type']}")

    conn.close()

    # Exit with error if issues detected
    if issues:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
