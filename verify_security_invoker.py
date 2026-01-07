"""Verify security_invoker status for all views in exposed schemas."""

import sys

sys.path.insert(0, "c:\\Users\\mccab\\dragonfly_civil")
import psycopg

from src.supabase_client import get_supabase_db_url


def verify_security_invoker(env="dev"):
    db_url = get_supabase_db_url(env)

    # Query all views in operational schemas
    query = """
    SELECT
        n.nspname AS schema,
        c.relname AS view_name,
        CASE
            WHEN c.reloptions @> ARRAY['security_invoker=true'] THEN 'INVOKER'
            ELSE 'DEFINER'
        END AS security_mode
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'v'
      AND n.nspname IN ('public', 'intake', 'enforcement', 'legal', 'rag', 'evidence', 'workers', 'ops', 'analytics')
    ORDER BY security_mode DESC, n.nspname, c.relname
    """

    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
                result = [
                    {"schema": row[0], "view_name": row[1], "security_mode": row[2]} for row in rows
                ]
    except Exception as e:
        print(f"❌ Failed to query views: {e}")
        return False

    print("Security Invoker Verification")
    print("=" * 70)

    invoker_count = 0
    definer_count = 0
    definer_views = []

    for row in result:
        mode = row["security_mode"]
        if mode == "INVOKER":
            invoker_count += 1
        else:
            definer_count += 1
            definer_views.append(f"{row['schema']}.{row['view_name']}")

    if definer_views:
        print("\n⚠️  Views still using SECURITY DEFINER:")
        for view in definer_views:
            print(f"   • {view}")

    print("\n" + "=" * 70)
    print(f"Total views checked: {invoker_count + definer_count}")
    print(f"✅ INVOKER (correct): {invoker_count}")
    print(f"❌ DEFINER (needs fix): {definer_count}")
    print("=" * 70)

    return definer_count == 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verify security_invoker on all views")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev", help="Environment")
    args = parser.parse_args()

    success = verify_security_invoker(args.env)
    sys.exit(0 if success else 1)
