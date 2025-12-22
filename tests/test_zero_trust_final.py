"""
Zero Trust Final Verification Tests
====================================
Validates that all tables have RLS enabled and enforced,
and that anonymous access is properly blocked.
"""

import os

import pytest

# Ensure we use dev environment for tests
os.environ.setdefault("SUPABASE_MODE", "dev")

from src.supabase_client import get_supabase_db_url


def get_direct_connection():
    """Get a direct psycopg connection for testing."""
    import psycopg

    db_url = get_supabase_db_url()
    return psycopg.connect(db_url, autocommit=True)


class TestZeroTrustCompliance:
    """Test suite for Zero Trust RLS compliance."""

    def test_rls_coverage_no_violations(self):
        """ops.v_rls_coverage should return 0 VIOLATION rows."""
        conn = get_direct_connection()
        try:
            with conn.cursor() as cur:
                # Check if view exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_views
                        WHERE schemaname = 'ops'
                        AND viewname = 'v_rls_coverage'
                    )
                """
                )
                view_exists = cur.fetchone()[0]

                if not view_exists:
                    pytest.skip("ops.v_rls_coverage view not deployed yet")

                # Query for violations
                cur.execute(
                    """
                    SELECT schema_name, table_name, has_rls, force_rls, compliance_status
                    FROM ops.v_rls_coverage
                    WHERE compliance_status = 'VIOLATION'
                """
                )
                violations = cur.fetchall()

                if violations:
                    violation_list = "\n".join(
                        f"  - {row[0]}.{row[1]} (RLS={row[2]}, FORCE={row[3]})"
                        for row in violations
                    )
                    pytest.fail(
                        f"Zero Trust violation: {len(violations)} table(s) without RLS:\n{violation_list}"
                    )
        finally:
            conn.close()

    def test_rls_coverage_no_partial(self):
        """ops.v_rls_coverage should have 0 PARTIAL rows (RLS without FORCE)."""
        conn = get_direct_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_views
                        WHERE schemaname = 'ops'
                        AND viewname = 'v_rls_coverage'
                    )
                """
                )
                view_exists = cur.fetchone()[0]

                if not view_exists:
                    pytest.skip("ops.v_rls_coverage view not deployed yet")

                cur.execute(
                    """
                    SELECT schema_name, table_name, has_rls, force_rls
                    FROM ops.v_rls_coverage
                    WHERE compliance_status = 'PARTIAL'
                """
                )
                partial = cur.fetchall()

                if partial:
                    partial_list = "\n".join(
                        f"  - {row[0]}.{row[1]} (RLS={row[2]}, FORCE={row[3]} - missing FORCE)"
                        for row in partial
                    )
                    pytest.fail(
                        f"Zero Trust partial: {len(partial)} table(s) with RLS but without FORCE:\n{partial_list}"
                    )
        finally:
            conn.close()

    def test_no_dangerous_grants(self):
        """ops.v_public_grants should have 0 DANGEROUS entries (excluding views)."""
        conn = get_direct_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_views
                        WHERE schemaname = 'ops'
                        AND viewname = 'v_public_grants'
                    )
                """
                )
                view_exists = cur.fetchone()[0]

                if not view_exists:
                    pytest.skip("ops.v_public_grants view not deployed yet")

                # Only check actual tables, not views (views are OK to grant to anon for dashboard)
                cur.execute(
                    """
                    SELECT pg.schema_name, pg.table_name, pg.grantee, pg.privileges
                    FROM ops.v_public_grants pg
                    JOIN pg_class c ON c.relname = pg.table_name
                    JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = pg.schema_name
                    WHERE pg.risk_level = 'DANGEROUS'
                      AND c.relkind = 'r'  -- Only regular tables, not views
                """
                )
                dangerous = cur.fetchall()

                if dangerous:
                    danger_list = "\n".join(
                        f"  - {row[0]}.{row[1]} -> {row[2]} ({row[3]})" for row in dangerous
                    )
                    pytest.fail(
                        f"Dangerous grants detected: {len(dangerous)} entry(ies):\n{danger_list}"
                    )
        finally:
            conn.close()

    def test_security_definers_reviewed(self):
        """Track SECURITY DEFINER functions - log count for awareness."""
        conn = get_direct_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_views
                        WHERE schemaname = 'ops'
                        AND viewname = 'v_security_definers'
                    )
                """
                )
                view_exists = cur.fetchone()[0]

                if not view_exists:
                    pytest.skip("ops.v_security_definers view not deployed yet")

                # Count by status for awareness
                cur.execute(
                    """
                    SELECT security_status, COUNT(*)
                    FROM ops.v_security_definers
                    GROUP BY security_status
                    ORDER BY security_status
                """
                )
                counts = dict(cur.fetchall())

                allowed = counts.get("ALLOWED", 0)
                whitelisted = counts.get("WHITELISTED", 0)
                review_required = counts.get("REVIEW_REQUIRED", 0)

                print("\n  SECURITY DEFINER audit:")
                print(f"    ALLOWED: {allowed}")
                print(f"    WHITELISTED: {whitelisted}")
                print(f"    REVIEW_REQUIRED: {review_required}")

                # This test passes but logs the count for awareness
                # Future: Add new legitimate functions to the whitelist
                assert True
        finally:
            conn.close()


class TestTableLockdown:
    """Test that sensitive tables are properly locked down."""

    @pytest.mark.parametrize(
        "schema,table",
        [
            ("public", "dragonfly_migrations"),
            ("public", "judgment_history"),
            ("public", "raw_simplicity_imports"),
            ("enforcement", "draft_packets"),
            ("enforcement", "enforcement_plans"),
            ("enforcement", "offers"),
            ("enforcement", "serve_jobs"),
        ],
    )
    def test_table_has_rls_enabled(self, schema: str, table: str):
        """Each sensitive table should have RLS enabled and forced."""
        conn = get_direct_connection()
        try:
            with conn.cursor() as cur:
                # Check if table exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_tables
                        WHERE schemaname = %s AND tablename = %s
                    )
                """,
                    (schema, table),
                )
                exists = cur.fetchone()[0]

                if not exists:
                    pytest.skip(f"Table {schema}.{table} does not exist")

                # Check RLS status
                cur.execute(
                    """
                    SELECT c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = %s AND c.relname = %s
                """,
                    (schema, table),
                )
                row = cur.fetchone()

                assert row is not None, f"Table {schema}.{table} not found in pg_class"
                has_rls, force_rls = row

                assert has_rls, f"{schema}.{table}: RLS not enabled"
                assert force_rls, f"{schema}.{table}: FORCE RLS not set"
        finally:
            conn.close()


class TestComplianceSummary:
    """Generate a compliance summary for reporting."""

    def test_print_compliance_summary(self):
        """Print a summary of Zero Trust compliance status."""
        conn = get_direct_connection()
        try:
            with conn.cursor() as cur:
                # Check if view exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_views
                        WHERE schemaname = 'ops'
                        AND viewname = 'v_rls_coverage'
                    )
                """
                )
                view_exists = cur.fetchone()[0]

                if not view_exists:
                    pytest.skip("ops.v_rls_coverage view not deployed yet")

                # Get compliance counts
                cur.execute(
                    """
                    SELECT compliance_status, COUNT(*)
                    FROM ops.v_rls_coverage
                    GROUP BY compliance_status
                    ORDER BY compliance_status
                """
                )
                counts = dict(cur.fetchall())

                compliant = counts.get("COMPLIANT", 0)
                partial = counts.get("PARTIAL", 0)
                violation = counts.get("VIOLATION", 0)
                total = compliant + partial + violation

                print("\n" + "=" * 60)
                print("ZERO TRUST COMPLIANCE SUMMARY")
                print("=" * 60)
                print(f"  COMPLIANT:  {compliant:3d} tables (RLS + FORCE)")
                print(f"  PARTIAL:    {partial:3d} tables (RLS only)")
                print(f"  VIOLATION:  {violation:3d} tables (no RLS)")
                print("-" * 60)
                print(f"  TOTAL:      {total:3d} tables")
                print("=" * 60)

                if violation == 0 and partial == 0:
                    print("✅ ZERO TRUST POSTURE: COMPLETE")
                elif violation == 0:
                    print("⚠️  ZERO TRUST POSTURE: PARTIAL (missing FORCE on some tables)")
                else:
                    print("❌ ZERO TRUST POSTURE: INCOMPLETE")
                print("=" * 60 + "\n")

                # This test always passes - it's just for reporting
                assert True
        finally:
            conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
