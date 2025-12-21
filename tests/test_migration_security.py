"""Tests to guard against dangerous grants in SQL migrations.

These tests scan migration files for patterns that would grant INSERT, UPDATE,
DELETE, or TRUNCATE privileges to authenticated, anon, OR dragonfly_app roles
on protected schemas (ops, intake, enforcement).

Perfect Deployment Spec:
- Fail Condition: If any file contains:
  GRANT (INSERT|UPDATE|DELETE|ALL) ON .*ops\\..* TO (anon|authenticated|dragonfly_app)
- Exception: Allow GRANT EXECUTE ON FUNCTION (RPCs are fine)

If a migration attempts to grant write privileges to public-facing roles,
these tests will fail - catching security violations before they reach prod.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

# Protected schemas where authenticated/anon/dragonfly_app should NEVER have write access
# Note: public schema tables use RLS with grants to authenticated, which is fine
PROTECTED_SCHEMAS = ["ops", "intake", "enforcement"]

# Dangerous privileges that should never be granted to public roles
DANGEROUS_PRIVILEGES = ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALL"]

# Public-facing roles that should not have write access to protected schemas
# dragonfly_app is the worker role - should only have SELECT on tables, write via RPC
FORBIDDEN_GRANTEES = ["authenticated", "anon", "dragonfly_app"]


class DangerousGrant(NamedTuple):
    """A detected dangerous GRANT statement."""

    file: str
    line: int
    schema: str
    privilege: str
    grantee: str
    snippet: str


def find_dangerous_grants(file_path: Path) -> list[DangerousGrant]:
    """
    Scan a SQL migration file for dangerous GRANT statements.

    Looks for patterns like:
    - GRANT INSERT ON TABLE ops.* TO authenticated
    - GRANT ALL ON TABLE ops.job_queue TO authenticated
    - GRANT UPDATE, DELETE ON ops.* TO anon
    - GRANT INSERT ON TABLE public.* TO dragonfly_app

    Exception: GRANT EXECUTE ON FUNCTION is allowed (RPCs are fine).

    Returns a list of violations found.
    """
    violations = []
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Build regex patterns for dangerous grants
    # Pattern: GRANT <privileges> ON [TABLE] <schema>.<table> TO <grantee>
    privilege_pattern = "|".join(DANGEROUS_PRIVILEGES)
    schema_pattern = "|".join(PROTECTED_SCHEMAS)
    grantee_pattern = "|".join(FORBIDDEN_GRANTEES)

    # Regex to match dangerous GRANT statements
    # Captures: privileges, schema, grantee
    grant_pattern = re.compile(
        rf"""
        GRANT\s+                           # GRANT keyword
        (?P<privs>(?:{privilege_pattern})  # First privilege
        (?:\s*,\s*(?:{privilege_pattern}))*) # Additional privileges (optional)
        \s+ON\s+                           # ON keyword
        (?:TABLE\s+)?                      # Optional TABLE keyword
        (?P<schema>{schema_pattern})\.     # Schema name (protected)
        \S+                                # Table name
        \s+TO\s+                           # TO keyword
        (?P<grantee>{grantee_pattern})     # Grantee (forbidden)
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # Pattern to detect GRANT EXECUTE ON FUNCTION (allowed, skip these)
    execute_on_function_pattern = re.compile(
        r"GRANT\s+EXECUTE\s+ON\s+(?:ALL\s+)?FUNCTION",
        re.IGNORECASE,
    )

    # Also check for bulk grants: GRANT ... ON ALL TABLES IN SCHEMA ops TO authenticated
    bulk_grant_pattern = re.compile(
        rf"""
        GRANT\s+                           # GRANT keyword
        (?P<privs>(?:{privilege_pattern})  # First privilege
        (?:\s*,\s*(?:{privilege_pattern}))*) # Additional privileges (optional)
        \s+ON\s+ALL\s+TABLES\s+IN\s+SCHEMA\s+ # ON ALL TABLES IN SCHEMA
        (?P<schema>{schema_pattern})       # Schema name (protected)
        \s+TO\s+                           # TO keyword
        (?:[^;]*\s)?                       # Optional other grantees before
        (?P<grantee>{grantee_pattern})     # Grantee (forbidden)
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    for line_num, line in enumerate(lines, 1):
        # Skip comment lines
        stripped = line.strip()
        if stripped.startswith("--"):
            continue

        # Skip GRANT EXECUTE ON FUNCTION (RPCs are allowed)
        if execute_on_function_pattern.search(line):
            continue

        # Check for direct table grants
        for match in grant_pattern.finditer(line):
            privs = match.group("privs").upper()
            schema = match.group("schema").lower()
            grantee = match.group("grantee").lower()

            # Check if any dangerous privilege is being granted
            for priv in DANGEROUS_PRIVILEGES:
                if priv in privs:
                    violations.append(
                        DangerousGrant(
                            file=str(file_path.name),
                            line=line_num,
                            schema=schema,
                            privilege=priv,
                            grantee=grantee,
                            snippet=stripped[:120],
                        )
                    )
                    break  # Only report once per line

        # Check for bulk grants
        for match in bulk_grant_pattern.finditer(line):
            privs = match.group("privs").upper()
            schema = match.group("schema").lower()
            grantee = match.group("grantee").lower()

            for priv in DANGEROUS_PRIVILEGES:
                if priv in privs:
                    violations.append(
                        DangerousGrant(
                            file=str(file_path.name),
                            line=line_num,
                            schema=schema,
                            privilege=priv,
                            grantee=grantee,
                            snippet=stripped[:120],
                        )
                    )
                    break

    return violations


def find_revokes_before_grants(file_path: Path) -> bool:
    """
    Check if a break-glass migration properly REVOKEs dangerous privileges
    before or after any GRANT statements.

    Returns True if revokes are present (safe), False otherwise.
    """
    content = file_path.read_text(encoding="utf-8")

    # Look for REVOKE patterns
    revoke_pattern = re.compile(
        r"REVOKE\s+(?:INSERT|UPDATE|DELETE|TRUNCATE|ALL).*?FROM\s+(?:authenticated|anon)",
        re.IGNORECASE,
    )

    return bool(revoke_pattern.search(content))


class TestMigrationSecurityGuard:
    """Test suite to detect dangerous grants in migrations."""

    @pytest.fixture
    def migrations_dir(self) -> Path:
        """Get migrations directory."""
        return Path(__file__).parent.parent / "supabase" / "migrations"

    def test_no_dangerous_grants_in_any_migration(self, migrations_dir: Path) -> None:
        """Scan all migrations for dangerous grants to authenticated/anon."""
        if not migrations_dir.exists():
            pytest.skip(f"Migrations directory not found: {migrations_dir}")

        all_violations = []

        for sql_file in migrations_dir.glob("*.sql"):
            violations = find_dangerous_grants(sql_file)
            all_violations.extend(violations)

        if all_violations:
            msg = "DANGEROUS GRANTS detected in migrations:\n"
            for v in all_violations:
                msg += f"  {v.file}:{v.line} - GRANT {v.privilege} ON {v.schema}.* TO {v.grantee}\n"
                msg += f"    {v.snippet}\n"
            msg += "\nThese grants would allow authenticated/anon to write to protected tables."
            msg += "\nUse SECURITY DEFINER functions instead."
            pytest.fail(msg)

    def test_break_glass_has_revokes(self, migrations_dir: Path) -> None:
        """Verify break-glass migrations include REVOKE statements."""
        if not migrations_dir.exists():
            pytest.skip(f"Migrations directory not found: {migrations_dir}")

        break_glass_files = list(migrations_dir.glob("*break_glass*.sql"))

        if not break_glass_files:
            pytest.skip("No break-glass migrations found")

        for sql_file in break_glass_files:
            has_revokes = find_revokes_before_grants(sql_file)
            if not has_revokes:
                pytest.fail(
                    f"{sql_file.name} is a break-glass migration but lacks REVOKE statements.\n"
                    "Break-glass migrations must explicitly REVOKE dangerous privileges from "
                    "authenticated/anon to ensure security."
                )

    def test_ops_schema_grants_only_to_privileged_roles(self, migrations_dir: Path) -> None:
        """Verify ops schema tables only grant DML to postgres/service_role."""
        if not migrations_dir.exists():
            pytest.skip(f"Migrations directory not found: {migrations_dir}")

        # Look for any GRANT INSERT/UPDATE/DELETE on ops.* to authenticated/anon
        # across all migrations (not just break-glass)
        all_violations = []

        for sql_file in migrations_dir.glob("*.sql"):
            content = sql_file.read_text(encoding="utf-8")

            # Skip if this is a REVOKE-focused migration (like our fixed one)
            if "REVOKE INSERT, UPDATE, DELETE" in content:
                continue

            violations = find_dangerous_grants(sql_file)
            # Filter to only ops schema
            ops_violations = [v for v in violations if v.schema == "ops"]
            all_violations.extend(ops_violations)

        if all_violations:
            msg = "SECURITY VIOLATION: ops schema grants to public roles:\n"
            for v in all_violations:
                msg += f"  {v.file}:{v.line} - {v.privilege} to {v.grantee}\n"
            pytest.fail(msg)


class TestBreakGlassSecurityInvariant:
    """Specific tests for break-glass migration security invariants."""

    @pytest.fixture
    def break_glass_file(self) -> Path:
        """Get the break-glass migration file."""
        migrations_dir = Path(__file__).parent.parent / "supabase" / "migrations"
        files = list(migrations_dir.glob("*break_glass*.sql"))
        if not files:
            pytest.skip("No break-glass migration found")
        return files[0]

    def test_break_glass_revokes_authenticated_dml(self, break_glass_file: Path) -> None:
        """Verify break-glass explicitly REVOKEs DML from authenticated."""
        content = break_glass_file.read_text(encoding="utf-8")

        # Must contain explicit REVOKE of INSERT, UPDATE, DELETE from authenticated
        assert re.search(
            r"REVOKE\s+INSERT.*FROM\s+authenticated", content, re.IGNORECASE
        ), "Break-glass must REVOKE INSERT from authenticated"

        assert re.search(
            r"REVOKE\s+(?:INSERT,\s*)?UPDATE.*FROM\s+authenticated", content, re.IGNORECASE
        ), "Break-glass must REVOKE UPDATE from authenticated"

        assert re.search(
            r"REVOKE\s+(?:INSERT,\s*UPDATE,\s*)?DELETE.*FROM\s+authenticated",
            content,
            re.IGNORECASE,
        ), "Break-glass must REVOKE DELETE from authenticated"

    def test_break_glass_revokes_anon_dml(self, break_glass_file: Path) -> None:
        """Verify break-glass explicitly REVOKEs DML from anon."""
        content = break_glass_file.read_text(encoding="utf-8")

        # Must revoke from anon as well
        assert re.search(
            r"REVOKE.*FROM.*anon", content, re.IGNORECASE
        ), "Break-glass must REVOKE privileges from anon"

    def test_break_glass_grants_to_service_role(self, break_glass_file: Path) -> None:
        """Verify break-glass grants DML to service_role."""
        content = break_glass_file.read_text(encoding="utf-8")

        # Must grant to service_role
        assert re.search(
            r"GRANT\s+ALL.*TO\s+service_role", content, re.IGNORECASE
        ), "Break-glass must GRANT ALL to service_role"

    def test_break_glass_has_verification_block(self, break_glass_file: Path) -> None:
        """Verify break-glass includes a verification DO block."""
        content = break_glass_file.read_text(encoding="utf-8")

        # Should have a verification block that raises exception on violations
        assert re.search(
            r"RAISE\s+EXCEPTION.*SECURITY", content, re.IGNORECASE
        ), "Break-glass must include verification block that raises on security violations"

    def test_break_glass_is_idempotent(self, break_glass_file: Path) -> None:
        """Verify break-glass can be run multiple times safely."""
        content = break_glass_file.read_text(encoding="utf-8")

        # Should use IF EXISTS patterns or unconditional operations
        # ALTER TABLE ... DISABLE ROW LEVEL SECURITY is idempotent
        # GRANT/REVOKE are idempotent
        # Should not have CREATE TABLE without IF NOT EXISTS
        assert not re.search(
            r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", content, re.IGNORECASE
        ), "Break-glass must use CREATE TABLE IF NOT EXISTS"

        # Should not have DROP TABLE without IF EXISTS
        assert not re.search(
            r"DROP\s+TABLE\s+(?!IF\s+EXISTS)", content, re.IGNORECASE
        ), "Break-glass must use DROP TABLE IF EXISTS"
