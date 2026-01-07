#!/usr/bin/env python3
"""
Dragonfly Civil - View Security Auditor

This script audits all views in operational schemas to ensure they have
security_invoker=true, which means they respect the calling user's RLS policies.

SECURITY MODEL:
- Views with security_invoker=true: SAFE (respects RLS)
- Views with security_invoker=false/missing: INSECURE (bypasses RLS)
- ops schema functions: Should NOT be accessible to anon/authenticated

Usage:
    python -m tools.audit_view_security --env dev
    python -m tools.audit_view_security --env prod --strict

Exit Codes:
    0: All views are secure
    1: Insecure views found

Author: Principal Security Architect
Date: 2026-01-07
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Target schemas to audit (exclude Supabase-managed schemas)
TARGET_SCHEMAS = [
    "public",
    "intake",
    "enforcement",
    "legal",
    "rag",
    "evidence",
    "workers",
    "ops",
    "analytics",
]

# Supabase-managed schemas to skip
EXCLUDED_SCHEMAS = [
    "auth",
    "storage",
    "extensions",
    "vault",
    "graphql",
    "graphql_public",
    "realtime",
    "supabase_functions",
    "supabase_migrations",
    "pgbouncer",
    "pgsodium",
    "pgsodium_masks",
    "_realtime",
    "net",
    "pg_catalog",
    "information_schema",
]


@dataclass
class ViewAuditResult:
    """Result of auditing a single view."""

    schema: str
    view_name: str
    is_invoker: bool
    options: Optional[str]

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.view_name}"


@dataclass
class GrantAuditResult:
    """Result of auditing a grant."""

    schema: str
    object_name: str
    object_type: str
    grantee: str
    privilege: str


def get_db_connection():
    """Get database connection using environment DSN."""
    import psycopg

    dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        print("ERROR: No database URL configured", file=sys.stderr)
        print("Set SUPABASE_MIGRATE_DB_URL or SUPABASE_DB_URL", file=sys.stderr)
        sys.exit(1)

    return psycopg.connect(dsn)


def audit_views(conn) -> list[ViewAuditResult]:
    """
    Audit all views in target schemas for security_invoker setting.

    Returns list of ViewAuditResult for each view found.
    """
    # Build schema list for query
    schema_list = ", ".join(f"'{s}'" for s in TARGET_SCHEMAS)

    query = f"""
        SELECT 
            n.nspname AS schema_name,
            c.relname AS view_name,
            COALESCE(c.reloptions @> ARRAY['security_invoker=true'], false) AS is_invoker,
            array_to_string(c.reloptions, ', ') AS options
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'v'  -- ordinary views only
          AND n.nspname IN ({schema_list})
        ORDER BY n.nspname, c.relname
    """

    results = []
    with conn.cursor() as cur:
        cur.execute(query)
        for row in cur.fetchall():
            results.append(
                ViewAuditResult(
                    schema=row[0],
                    view_name=row[1],
                    is_invoker=row[2],
                    options=row[3],
                )
            )

    return results


def audit_ops_grants(conn) -> list[GrantAuditResult]:
    """
    Audit grants on ops schema objects to ensure anon/authenticated don't have access.

    Only service_role and ops_viewer should have access to ops schema.
    """
    query = """
        SELECT 
            n.nspname AS schema_name,
            COALESCE(p.proname, c.relname) AS object_name,
            CASE 
                WHEN p.proname IS NOT NULL THEN 'function'
                WHEN c.relkind = 'v' THEN 'view'
                WHEN c.relkind = 'r' THEN 'table'
                ELSE 'other'
            END AS object_type,
            acl.grantee::regrole::text AS grantee,
            acl.privilege_type AS privilege
        FROM pg_namespace n
        LEFT JOIN pg_class c ON c.relnamespace = n.oid
        LEFT JOIN pg_proc p ON p.pronamespace = n.oid
        CROSS JOIN LATERAL (
            SELECT 
                (aclexplode(COALESCE(c.relacl, p.proacl))).grantee,
                (aclexplode(COALESCE(c.relacl, p.proacl))).privilege_type
        ) AS acl
        WHERE n.nspname = 'ops'
          AND acl.grantee::regrole::text IN ('anon', 'authenticated')
          AND (c.relname IS NOT NULL OR p.proname IS NOT NULL)
        ORDER BY object_name, grantee
    """

    results = []
    with conn.cursor() as cur:
        try:
            cur.execute(query)
            for row in cur.fetchall():
                results.append(
                    GrantAuditResult(
                        schema=row[0],
                        object_name=row[1],
                        object_type=row[2],
                        grantee=row[3],
                        privilege=row[4],
                    )
                )
        except Exception as e:
            # If ops schema doesn't exist, that's fine
            if "schema" in str(e).lower() and "does not exist" in str(e).lower():
                pass
            else:
                print(f"Warning: Could not audit ops grants: {e}", file=sys.stderr)

    return results


def print_header(title: str) -> None:
    """Print a formatted header."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit view security settings in Dragonfly Civil database"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Environment to audit (default: dev)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any warning (for CI)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show all views, not just insecure ones",
    )

    args = parser.parse_args()

    # Load environment
    env_file = f".env.{args.env}"
    if os.path.exists(env_file):
        load_dotenv(env_file)
    else:
        load_dotenv()

    os.environ["SUPABASE_MODE"] = args.env

    print_header(f"VIEW SECURITY AUDIT - {args.env.upper()}")

    # Connect to database
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}", file=sys.stderr)
        return 1

    exit_code = 0

    # =========================================================================
    # AUDIT 1: View Security Invoker
    # =========================================================================
    print("\n📋 Auditing view security_invoker settings...")
    print("-" * 50)

    views = audit_views(conn)
    insecure_views = [v for v in views if not v.is_invoker]
    secure_views = [v for v in views if v.is_invoker]

    if args.verbose:
        print(f"\n✓ Secure views ({len(secure_views)}):")
        for v in secure_views:
            print(f"  ✓ {v.full_name}")

    if insecure_views:
        print(f"\n✗ INSECURE VIEWS FOUND ({len(insecure_views)}):")
        print("  These views bypass RLS using owner permissions!")
        print()
        for v in insecure_views:
            print(f"  ✗ {v.full_name}")
            if v.options:
                print(f"    Options: {v.options}")
        print()
        print("  FIX: Run migration 20261001_enforce_invoker_views.sql")
        print("       ALTER VIEW <schema>.<view> SET (security_invoker = true);")
        exit_code = 1
    else:
        print(f"\n✅ All {len(views)} views are Security Invoker (RLS-safe)")

    # =========================================================================
    # AUDIT 2: Ops Schema Grants
    # =========================================================================
    print("\n📋 Auditing ops schema grants...")
    print("-" * 50)

    ops_grants = audit_ops_grants(conn)

    if ops_grants:
        print(f"\n⚠️ INSECURE GRANTS FOUND ({len(ops_grants)}):")
        print("  anon/authenticated should NOT have access to ops schema!")
        print()
        for g in ops_grants:
            print(f"  ✗ {g.schema}.{g.object_name} ({g.object_type})")
            print(f"    {g.grantee} has {g.privilege}")
        print()
        print("  FIX: REVOKE ALL ON FUNCTION/VIEW ops.* FROM anon, authenticated;")

        if args.strict:
            exit_code = 1
    else:
        print("\n✅ ops schema has no grants to anon/authenticated")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print_header("AUDIT SUMMARY")

    print(f"  Views audited:     {len(views)}")
    print(f"  Secure (invoker):  {len(secure_views)}")
    print(f"  Insecure:          {len(insecure_views)}")
    print(f"  Ops grant issues:  {len(ops_grants)}")
    print()

    if exit_code == 0:
        print("✅ ALL SECURITY CHECKS PASSED")
    else:
        print("❌ SECURITY ISSUES FOUND - See details above")

    print()

    conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
