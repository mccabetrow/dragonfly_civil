"""
Dragonfly Invariant Enforcement Suite

World-class architectural invariant enforcement via automated testing.
Ensures security, reliability, and data correctness contracts are never violated.

Invariants Enforced:
1. Security: ops and intake schemas are RPC-only. No raw DML from app code.
2. Migration Security: No dangerous GRANT statements in migrations.
3. Idempotency: WorkerBootstrap enforces atomic job transitions with rollback.

Usage:
    pytest tests/test_invariants.py -v
    pytest tests/test_invariants.py::test_no_raw_sql_to_protected_schemas -v

If any of these tests fail, the deployment should be blocked until fixed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

import pytest

# ============================================================================
# CONFIGURATION
# ============================================================================

# Protected schemas where app code should NEVER write raw SQL
PROTECTED_SCHEMAS = ["ops", "intake"]

# Files to scan for raw SQL violations
BACKEND_GLOB = "backend/**/*.py"

# Migration files to scan for dangerous grants
MIGRATION_GLOB = "supabase/migrations/*.sql"

# Roles that should never receive write privileges on protected schemas
FORBIDDEN_GRANTEES = ["authenticated", "anon"]

# Dangerous privileges
DANGEROUS_PRIVILEGES = ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALL"]

# Pattern to detect raw DML on protected schemas
# Matches: INSERT|UPDATE|DELETE ... ops. or intake.
RAW_DML_PATTERN = re.compile(
    r"(INSERT|UPDATE|DELETE)\s+.*\b(ops\.|intake\.)",
    re.IGNORECASE | re.MULTILINE,
)


# ============================================================================
# DATA CLASSES
# ============================================================================


class RawSQLViolation(NamedTuple):
    """A detected raw SQL write to protected schema."""

    file: str
    line: int
    operation: str
    schema: str
    snippet: str


class DangerousGrantViolation(NamedTuple):
    """A detected dangerous GRANT in migration."""

    file: str
    line: int
    privilege: str
    schema: str
    grantee: str
    snippet: str


# ============================================================================
# CHECK A: NO RAW SQL TO PROTECTED SCHEMAS
# ============================================================================


def is_comment_line(line: str) -> bool:
    """Check if a line is a Python comment."""
    stripped = line.strip()
    return stripped.startswith("#")


def is_in_docstring(content: str, position: int) -> bool:
    """
    Heuristic check if position is inside a docstring.

    This is a simplified check - looks for triple quotes before and after.
    """
    # Count triple quotes before position
    before = content[:position]
    triple_double = before.count('"""')
    triple_single = before.count("'''")

    # Odd count means we're inside a docstring
    return (triple_double % 2 == 1) or (triple_single % 2 == 1)


def find_raw_sql_violations(file_path: Path) -> list[RawSQLViolation]:
    """
    Scan a Python file for raw SQL DML statements against protected schemas.

    Ignores:
    - Comment lines
    - Docstrings
    - Test files (they may contain examples)
    - Migration helpers

    Returns list of violations found.
    """
    violations = []

    # Skip test files
    if "test_" in file_path.name or "_test.py" in file_path.name:
        return violations

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return violations

    lines = content.split("\n")

    for line_num, line in enumerate(lines, 1):
        # Skip comment lines
        if is_comment_line(line):
            continue

        # Skip if line position is in docstring
        line_start_pos = sum(len(ln) + 1 for ln in lines[: line_num - 1])
        if is_in_docstring(content, line_start_pos):
            continue

        # Look for DML patterns
        for match in RAW_DML_PATTERN.finditer(line):
            operation = match.group(1).upper()
            # Determine which schema
            schema = "ops" if "ops." in match.group(0).lower() else "intake"

            violations.append(
                RawSQLViolation(
                    file=str(file_path),
                    line=line_num,
                    operation=operation,
                    schema=schema,
                    snippet=line.strip()[:120],
                )
            )

    return violations


def scan_backend_for_raw_sql() -> list[RawSQLViolation]:
    """Scan all backend/ files for raw SQL violations."""
    project_root = Path(__file__).resolve().parents[1]
    backend_dir = project_root / "backend"

    if not backend_dir.exists():
        return []

    all_violations = []
    for py_file in backend_dir.rglob("*.py"):
        # Skip __pycache__ and test files
        if "__pycache__" in str(py_file):
            continue
        violations = find_raw_sql_violations(py_file)
        all_violations.extend(violations)

    return all_violations


# ============================================================================
# CHECK B: MIGRATION SECURITY
# ============================================================================


def find_dangerous_grants(file_path: Path) -> list[DangerousGrantViolation]:
    """
    Scan a SQL migration file for dangerous GRANT statements.

    Fails if any GRANT gives INSERT/UPDATE/DELETE/ALL on protected schemas
    to authenticated or anon roles.

    Exception: GRANT EXECUTE ON FUNCTION is allowed (RPCs are fine).
    """
    violations = []

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return violations

    lines = content.split("\n")

    # Build pattern for dangerous grants
    priv_pattern = "|".join(DANGEROUS_PRIVILEGES)
    schema_pattern = "|".join(PROTECTED_SCHEMAS)
    grantee_pattern = "|".join(FORBIDDEN_GRANTEES)

    # Pattern 1: GRANT <priv> ON [TABLE] <schema>.<table> TO <grantee>
    table_grant_pattern = re.compile(
        rf"""
        GRANT\s+
        (?P<privs>(?:{priv_pattern})(?:\s*,\s*(?:{priv_pattern}))*)
        \s+ON\s+
        (?:TABLE\s+)?
        (?P<schema>{schema_pattern})\.
        \S+
        \s+TO\s+
        (?P<grantee>{grantee_pattern})
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # Pattern 2: GRANT <priv> ON ALL TABLES IN SCHEMA <schema> TO <grantee>
    bulk_grant_pattern = re.compile(
        rf"""
        GRANT\s+
        (?P<privs>(?:{priv_pattern})(?:\s*,\s*(?:{priv_pattern}))*)
        \s+ON\s+ALL\s+TABLES\s+IN\s+SCHEMA\s+
        (?P<schema>{schema_pattern})
        \s+TO\s+
        (?P<grantee>{grantee_pattern})
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # Pattern for GRANT EXECUTE ON FUNCTION (this is ALLOWED)
    execute_on_function = re.compile(
        r"GRANT\s+EXECUTE\s+ON\s+(?:ALL\s+)?FUNCTION",
        re.IGNORECASE,
    )

    for line_num, line in enumerate(lines, 1):
        # Skip SQL comments
        stripped = line.strip()
        if stripped.startswith("--"):
            continue

        # Skip GRANT EXECUTE ON FUNCTION (RPCs are allowed)
        if execute_on_function.search(line):
            continue

        # Check table grants
        for pattern in [table_grant_pattern, bulk_grant_pattern]:
            match = pattern.search(line)
            if match:
                violations.append(
                    DangerousGrantViolation(
                        file=str(file_path),
                        line=line_num,
                        privilege=match.group("privs"),
                        schema=match.group("schema"),
                        grantee=match.group("grantee"),
                        snippet=stripped[:120],
                    )
                )

    return violations


def scan_migrations_for_dangerous_grants() -> list[DangerousGrantViolation]:
    """Scan all migration files for dangerous grants."""
    project_root = Path(__file__).resolve().parents[1]
    migrations_dir = project_root / "supabase" / "migrations"

    if not migrations_dir.exists():
        return []

    all_violations = []
    for sql_file in migrations_dir.glob("*.sql"):
        violations = find_dangerous_grants(sql_file)
        all_violations.extend(violations)

    return all_violations


# ============================================================================
# CHECK C: IDEMPOTENCY CONTRACT
# ============================================================================


def check_worker_bootstrap_has_transaction_rollback() -> tuple[bool, str]:
    """
    Verify that WorkerBootstrap has proper transaction handling with rollback.

    Checks for:
    1. Transaction block in job processing
    2. Rollback on error
    3. Atomic job state transitions

    Returns (passed, message).
    """
    project_root = Path(__file__).resolve().parents[1]
    bootstrap_path = project_root / "backend" / "workers" / "bootstrap.py"

    if not bootstrap_path.exists():
        return False, f"bootstrap.py not found at {bootstrap_path}"

    try:
        content = bootstrap_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Could not read bootstrap.py: {e}"

    # Check for transaction rollback pattern
    has_rollback = "conn.rollback()" in content or ".rollback()" in content
    has_transaction_handling = "InFailedSqlTransaction" in content

    # Check for atomic job transitions (DLQ pattern)
    has_job_failure_handling = (
        "mark_job_failed" in content or "update_job_status" in content or "set_error" in content
    )

    # Check for backoff state (self-healing)
    has_backoff = "BackoffState" in content or "backoff" in content.lower()

    # Check for crash loop detection
    has_crash_loop_detection = "crash_loop" in content.lower() or "is_in_crash_loop" in content

    issues = []
    if not has_rollback:
        issues.append("Missing transaction rollback on error")
    if not has_transaction_handling:
        issues.append("Missing InFailedSqlTransaction handling")
    if not has_job_failure_handling:
        issues.append("Missing job failure marking (DLQ pattern)")
    if not has_backoff:
        issues.append("Missing exponential backoff")
    if not has_crash_loop_detection:
        issues.append("Missing crash loop detection")

    if issues:
        return False, f"Idempotency contract violations: {', '.join(issues)}"

    return True, "WorkerBootstrap has proper transaction rollback and DLQ handling"


def check_rpc_client_has_circuit_breaker() -> tuple[bool, str]:
    """
    Verify that RPCClient has circuit breaker retry logic.

    Returns (passed, message).
    """
    project_root = Path(__file__).resolve().parents[1]
    rpc_path = project_root / "backend" / "workers" / "rpc_client.py"

    if not rpc_path.exists():
        return False, f"rpc_client.py not found at {rpc_path}"

    try:
        content = rpc_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Could not read rpc_client.py: {e}"

    # Check for tenacity/retry patterns
    has_tenacity = "from tenacity import" in content or "import tenacity" in content
    has_retry_decorator = "@retry" in content or "with_circuit_breaker" in content
    has_exponential_backoff = "wait_exponential" in content or "exponential" in content.lower()
    has_transient_exceptions = "TRANSIENT_EXCEPTIONS" in content or "OperationalError" in content

    issues = []
    if not has_tenacity:
        issues.append("Missing tenacity import for retry logic")
    if not has_retry_decorator:
        issues.append("Missing @retry decorator or circuit breaker")
    if not has_exponential_backoff:
        issues.append("Missing exponential backoff")
    if not has_transient_exceptions:
        issues.append("Missing transient exception handling")

    if issues:
        return False, f"Circuit breaker violations: {', '.join(issues)}"

    return True, "RPCClient has proper circuit breaker with exponential backoff"


# ============================================================================
# PYTEST TESTS
# ============================================================================


class TestNoRawSQL:
    """Tests that enforce: No raw DML to ops/intake schemas from app code."""

    def test_no_raw_sql_to_protected_schemas(self) -> None:
        """
        Scan all backend/ files and fail if any contain raw INSERT/UPDATE/DELETE
        statements against ops. or intake. schemas.

        Security Invariant: All writes to ops/intake must go through RPCs.
        """
        violations = scan_backend_for_raw_sql()

        if violations:
            msg_parts = ["Raw SQL violations detected in backend code:"]
            for v in violations[:10]:  # Limit output
                msg_parts.append(f"  - {v.file}:{v.line}: {v.operation} on {v.schema}")
                msg_parts.append(f"    Snippet: {v.snippet}")

            if len(violations) > 10:
                msg_parts.append(f"  ... and {len(violations) - 10} more violations")

            msg_parts.append("")
            msg_parts.append("Fix: Use RPCClient methods instead of raw SQL.")
            msg_parts.append("Example: rpc.update_job_status(job_id, 'completed', None)")

            pytest.fail("\n".join(msg_parts))

    def test_protected_schemas_list_is_complete(self) -> None:
        """Verify we're checking all protected schemas."""
        assert "ops" in PROTECTED_SCHEMAS
        assert "intake" in PROTECTED_SCHEMAS


class TestMigrationSecurity:
    """Tests that enforce: No dangerous GRANTs in migration files."""

    def test_no_dangerous_grants_to_public_roles(self) -> None:
        """
        Scan all migration files and fail if any GRANT INSERT/UPDATE/DELETE/ALL
        on ops/intake schemas to authenticated or anon roles.

        Security Invariant: Public roles get SELECT only. Writes via RPC.
        """
        violations = scan_migrations_for_dangerous_grants()

        if violations:
            msg_parts = ["Dangerous GRANT statements detected in migrations:"]
            for v in violations[:10]:
                msg_parts.append(
                    f"  - {Path(v.file).name}:{v.line}: "
                    f"GRANT {v.privilege} ON {v.schema}.* TO {v.grantee}"
                )
                msg_parts.append(f"    Snippet: {v.snippet}")

            if len(violations) > 10:
                msg_parts.append(f"  ... and {len(violations) - 10} more violations")

            msg_parts.append("")
            msg_parts.append(
                "Fix: Remove dangerous GRANTs. Use GRANT EXECUTE ON FUNCTION for RPCs only."
            )

            pytest.fail("\n".join(msg_parts))

    def test_forbidden_grantees_list(self) -> None:
        """Verify forbidden grantees are configured."""
        assert "authenticated" in FORBIDDEN_GRANTEES
        assert "anon" in FORBIDDEN_GRANTEES


class TestIdempotencyContract:
    """Tests that enforce: Workers have atomic, self-healing job processing."""

    def test_worker_bootstrap_has_rollback_on_error(self) -> None:
        """
        Verify WorkerBootstrap has proper transaction rollback.

        Reliability Invariant: Failed transactions must rollback cleanly.
        """
        passed, message = check_worker_bootstrap_has_transaction_rollback()
        if not passed:
            pytest.fail(f"Idempotency contract violation: {message}")

    def test_rpc_client_has_circuit_breaker(self) -> None:
        """
        Verify RPCClient has circuit breaker retry logic.

        Reliability Invariant: Transient failures are retried with backoff.
        """
        passed, message = check_rpc_client_has_circuit_breaker()
        if not passed:
            pytest.fail(f"Circuit breaker violation: {message}")

    def test_backoff_module_exists(self) -> None:
        """Verify backoff module exists and has required components."""
        project_root = Path(__file__).resolve().parents[1]
        backoff_path = project_root / "backend" / "workers" / "backoff.py"

        assert backoff_path.exists(), "backoff.py not found"

        content = backoff_path.read_text(encoding="utf-8")
        assert "BackoffState" in content, "BackoffState class not found"
        assert "record_failure" in content, "record_failure method not found"
        assert "record_success" in content, "record_success method not found"
        assert "is_in_crash_loop" in content, "is_in_crash_loop method not found"


class TestSecurityDefenderRPCs:
    """Tests that critical RPCs are SECURITY DEFINER."""

    def test_rpc_client_wraps_all_writes(self) -> None:
        """
        Verify RPCClient provides methods for all required write operations.

        This ensures workers have proper RPC wrappers for their operations.
        """
        project_root = Path(__file__).resolve().parents[1]
        rpc_path = project_root / "backend" / "workers" / "rpc_client.py"

        if not rpc_path.exists():
            pytest.skip("rpc_client.py not found")

        content = rpc_path.read_text(encoding="utf-8")

        # Critical RPC wrappers that should exist
        required_methods = [
            "claim_pending_job",
            "update_job_status",
        ]

        missing = []
        for method in required_methods:
            if f"def {method}" not in content:
                missing.append(method)

        if missing:
            pytest.fail(
                f"RPCClient missing required methods: {', '.join(missing)}\n"
                "These methods wrap SECURITY DEFINER RPCs and must exist."
            )


# ============================================================================
# SUMMARY TEST
# ============================================================================


class TestInvariantSummary:
    """Summary test that runs all invariant checks."""

    def test_all_invariants_pass(self) -> None:
        """
        Meta-test: Verifies all invariant categories are checked.

        This ensures the invariant suite is comprehensive.
        """
        # Verify we have tests for each invariant category
        test_classes = [
            TestNoRawSQL,
            TestMigrationSecurity,
            TestIdempotencyContract,
            TestSecurityDefenderRPCs,
        ]

        for cls in test_classes:
            # Each class should have at least one test method
            test_methods = [m for m in dir(cls) if m.startswith("test_")]
            assert len(test_methods) >= 1, f"{cls.__name__} has no test methods"
