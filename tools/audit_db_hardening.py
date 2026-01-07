#!/usr/bin/env python3
"""
Audit Database Security Hardening

Validates that Supabase Advisor security fixes are properly applied:
1. Search Path Safety - All SECURITY DEFINER functions have fixed search_path
2. Ops Schema Isolation - No public role access to ops schema
3. View Security Mode - Reports security_invoker status on views

Usage:
    python -m tools.audit_db_hardening [--env dev|prod] [--verbose] [--json]

Exit Codes:
    0 - All checks passed
    1 - One or more checks failed
    2 - Connection or runtime error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
try:
    from backend.core.db import get_sync_engine
except ImportError:
    # Fallback for standalone execution
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backend.core.db import get_sync_engine

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Data classes for structured results
# ---------------------------------------------------------------------------


@dataclass
class FunctionAudit:
    """Result of a SECURITY DEFINER function check."""

    schema: str
    name: str
    has_search_path: bool
    search_path_value: str | None = None


@dataclass
class SchemaGrantAudit:
    """Result of a schema privilege check."""

    grantee: str
    object_schema: str
    object_type: str
    privilege_type: str


@dataclass
class ViewSecurityAudit:
    """Result of a view security mode check."""

    schema: str
    name: str
    security_invoker: bool


@dataclass
class AuditResult:
    """Aggregated audit results."""

    # Check 1: Search path safety
    definer_functions_total: int = 0
    definer_functions_safe: int = 0
    definer_functions_unsafe: list[FunctionAudit] = field(default_factory=list)

    # Check 2: Ops isolation
    ops_grants_to_public: list[SchemaGrantAudit] = field(default_factory=list)

    # Check 3: View security
    views_with_invoker: list[ViewSecurityAudit] = field(default_factory=list)
    views_without_invoker: list[ViewSecurityAudit] = field(default_factory=list)

    @property
    def search_path_passed(self) -> bool:
        return len(self.definer_functions_unsafe) == 0

    @property
    def ops_isolation_passed(self) -> bool:
        return len(self.ops_grants_to_public) == 0

    @property
    def all_passed(self) -> bool:
        return self.search_path_passed and self.ops_isolation_passed


# ---------------------------------------------------------------------------
# SQL Queries
# ---------------------------------------------------------------------------

SQL_CHECK_DEFINER_FUNCTIONS = """
SELECT
    n.nspname AS schema_name,
    p.proname AS function_name,
    p.proconfig,
    CASE
        WHEN p.proconfig IS NOT NULL AND EXISTS (
            SELECT 1 FROM unnest(p.proconfig) AS conf
            WHERE conf LIKE 'search_path=%'
        ) THEN true
        ELSE false
    END AS has_search_path,
    (
        SELECT conf FROM unnest(p.proconfig) AS conf
        WHERE conf LIKE 'search_path=%'
        LIMIT 1
    ) AS search_path_value
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.prosecdef = true
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'extensions', 'pgmq')
ORDER BY n.nspname, p.proname;
"""

SQL_CHECK_OPS_GRANTS = """
-- Check schema usage grants
SELECT
    grantee::text,
    'ops'::text AS object_schema,
    'SCHEMA'::text AS object_type,
    privilege_type::text
FROM information_schema.usage_privileges
WHERE object_schema = 'ops'
  AND grantee IN ('anon', 'authenticated')

UNION ALL

-- Check table grants
SELECT
    grantee::text,
    table_schema::text AS object_schema,
    'TABLE'::text AS object_type,
    privilege_type::text
FROM information_schema.table_privileges
WHERE table_schema = 'ops'
  AND grantee IN ('anon', 'authenticated')

UNION ALL

-- Check routine/function grants
SELECT
    grantee::text,
    routine_schema::text AS object_schema,
    'FUNCTION'::text AS object_type,
    privilege_type::text
FROM information_schema.routine_privileges
WHERE routine_schema = 'ops'
  AND grantee IN ('anon', 'authenticated');
"""

SQL_CHECK_VIEW_SECURITY = """
SELECT
    n.nspname AS schema_name,
    c.relname AS view_name,
    CASE
        WHEN c.reloptions IS NOT NULL
             AND 'security_invoker=true' = ANY(c.reloptions)
        THEN true
        ELSE false
    END AS security_invoker
FROM pg_class c
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE c.relkind = 'v'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'extensions')
ORDER BY n.nspname, c.relname;
"""


# ---------------------------------------------------------------------------
# Audit Functions
# ---------------------------------------------------------------------------


def check_definer_search_paths(engine) -> tuple[int, int, list[FunctionAudit]]:
    """
    Check 1: Verify all SECURITY DEFINER functions have explicit search_path.

    Returns:
        (total_count, safe_count, unsafe_functions)
    """
    unsafe: list[FunctionAudit] = []
    total = 0
    safe = 0

    with engine.connect() as conn:
        result = conn.execute(text(SQL_CHECK_DEFINER_FUNCTIONS))
        for row in result:
            total += 1
            audit = FunctionAudit(
                schema=row.schema_name,
                name=row.function_name,
                has_search_path=row.has_search_path,
                search_path_value=row.search_path_value,
            )
            if row.has_search_path:
                safe += 1
            else:
                unsafe.append(audit)

    return total, safe, unsafe


def check_ops_isolation(engine) -> list[SchemaGrantAudit]:
    """
    Check 2: Verify ops schema has no grants to anon/authenticated.

    Returns:
        List of grants that should not exist (empty = good)
    """
    grants: list[SchemaGrantAudit] = []

    with engine.connect() as conn:
        result = conn.execute(text(SQL_CHECK_OPS_GRANTS))
        for row in result:
            grants.append(
                SchemaGrantAudit(
                    grantee=row.grantee,
                    object_schema=row.object_schema,
                    object_type=row.object_type,
                    privilege_type=row.privilege_type,
                )
            )

    return grants


def check_view_security(engine) -> tuple[list[ViewSecurityAudit], list[ViewSecurityAudit]]:
    """
    Check 3: Report view security_invoker status.

    Returns:
        (views_with_invoker, views_without_invoker)
    """
    with_invoker: list[ViewSecurityAudit] = []
    without_invoker: list[ViewSecurityAudit] = []

    with engine.connect() as conn:
        result = conn.execute(text(SQL_CHECK_VIEW_SECURITY))
        for row in result:
            audit = ViewSecurityAudit(
                schema=row.schema_name,
                name=row.view_name,
                security_invoker=row.security_invoker,
            )
            if row.security_invoker:
                with_invoker.append(audit)
            else:
                without_invoker.append(audit)

    return with_invoker, without_invoker


def run_audit(engine, verbose: bool = False) -> AuditResult:
    """Run all security hardening checks."""
    result = AuditResult()

    # Check 1: Search path safety
    total, safe, unsafe = check_definer_search_paths(engine)
    result.definer_functions_total = total
    result.definer_functions_safe = safe
    result.definer_functions_unsafe = unsafe

    # Check 2: Ops isolation
    result.ops_grants_to_public = check_ops_isolation(engine)

    # Check 3: View security
    result.views_with_invoker, result.views_without_invoker = check_view_security(engine)

    return result


# ---------------------------------------------------------------------------
# Output Formatting
# ---------------------------------------------------------------------------


def print_results(result: AuditResult, verbose: bool = False) -> None:
    """Print audit results to console."""
    print()
    print("═" * 70)
    print("  DATABASE SECURITY HARDENING AUDIT")
    print("═" * 70)
    print()

    # Check 1: Search Path Safety
    print("─" * 70)
    print("  CHECK 1: SECURITY DEFINER Search Path Safety")
    print("─" * 70)

    if result.search_path_passed:
        print(
            f"  ✅ Definer Functions: All {result.definer_functions_safe}/"
            f"{result.definer_functions_total} have fixed search_path"
        )
    else:
        print(
            f"  ❌ Definer Functions: {result.definer_functions_safe}/"
            f"{result.definer_functions_total} have fixed search_path"
        )
        print()
        print("  UNSAFE FUNCTIONS (missing search_path):")
        for fn in result.definer_functions_unsafe:
            print(f"    • {fn.schema}.{fn.name}")

    print()

    # Check 2: Ops Isolation
    print("─" * 70)
    print("  CHECK 2: Ops Schema Isolation")
    print("─" * 70)

    if result.ops_isolation_passed:
        print("  ✅ Ops Schema: 100% Isolated from Public")
    else:
        print(f"  ❌ Ops Schema: {len(result.ops_grants_to_public)} grants to public roles!")
        print()
        print("  LEAKED GRANTS:")
        for grant in result.ops_grants_to_public:
            print(
                f"    • {grant.grantee} has {grant.privilege_type} on "
                f"{grant.object_type} in {grant.object_schema}"
            )

    print()

    # Check 3: View Security
    print("─" * 70)
    print("  CHECK 3: View Security Mode")
    print("─" * 70)

    invoker_count = len(result.views_with_invoker)
    total_views = invoker_count + len(result.views_without_invoker)

    print(f"  ℹ️  Views with security_invoker=true: {invoker_count}/{total_views}")

    if verbose:
        if result.views_with_invoker:
            print()
            print("  SECURITY_INVOKER = TRUE:")
            for v in result.views_with_invoker:
                print(f"    ✓ {v.schema}.{v.name}")

        if result.views_without_invoker:
            print()
            print("  SECURITY_INVOKER = FALSE (or unset):")
            for v in result.views_without_invoker:
                print(f"    ○ {v.schema}.{v.name}")

    print()

    # Summary
    print("═" * 70)
    if result.all_passed:
        print("  ✅ ALL SECURITY CHECKS PASSED")
    else:
        print("  ❌ SOME SECURITY CHECKS FAILED")
    print("═" * 70)
    print()


def to_json(result: AuditResult) -> dict[str, Any]:
    """Convert audit result to JSON-serializable dict."""
    return {
        "passed": result.all_passed,
        "checks": {
            "search_path_safety": {
                "passed": result.search_path_passed,
                "total": result.definer_functions_total,
                "safe": result.definer_functions_safe,
                "unsafe": [
                    {"schema": f.schema, "name": f.name} for f in result.definer_functions_unsafe
                ],
            },
            "ops_isolation": {
                "passed": result.ops_isolation_passed,
                "leaked_grants": [
                    {
                        "grantee": g.grantee,
                        "object_schema": g.object_schema,
                        "object_type": g.object_type,
                        "privilege_type": g.privilege_type,
                    }
                    for g in result.ops_grants_to_public
                ],
            },
            "view_security": {
                "with_invoker": len(result.views_with_invoker),
                "without_invoker": len(result.views_without_invoker),
                "views_with_invoker": [
                    {"schema": v.schema, "name": v.name} for v in result.views_with_invoker
                ],
                "views_without_invoker": [
                    {"schema": v.schema, "name": v.name} for v in result.views_without_invoker
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit database security hardening (Supabase Advisor fixes)"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: from SUPABASE_MODE or 'dev')",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed view listings")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Set environment
    os.environ["SUPABASE_MODE"] = args.env

    try:
        engine = get_sync_engine()
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e), "passed": False}))
        else:
            print(f"❌ Failed to connect to database: {e}", file=sys.stderr)
        return 2

    try:
        result = run_audit(engine, verbose=args.verbose)

        if args.json:
            print(json.dumps(to_json(result), indent=2))
        else:
            print(f"\n🔍 Auditing {args.env.upper()} environment...")
            print_results(result, verbose=args.verbose)

        return 0 if result.all_passed else 1

    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e), "passed": False}))
        else:
            print(f"❌ Audit failed: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
