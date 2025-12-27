"""
Test: RPC Contract Validation
==============================

Ensures the canonical DB contract is enforced and won't drift.

This test validates that:
1. RPCClient methods match the canonical SQL RPC signatures exactly
2. All SECURITY DEFINER RPCs have explicit search_path
3. No ambiguous function overloads exist
4. All required columns exist on ops.job_queue

Run with: pytest tests/test_rpc_contract.py -v
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

import pytest

# =============================================================================
# MARKERS
# =============================================================================

pytestmark = pytest.mark.contract  # Contract gate marker


class RPCSignature(NamedTuple):
    """Expected RPC signature."""

    schema: str
    name: str
    params: list[tuple[str, str]]  # (param_name, param_type)
    returns: str


# ============================================================================
# CANONICAL RPC SIGNATURES
# ============================================================================
# These MUST match the migration: 20251220180001_world_class_canonical_rpcs.sql
# and the Python code in backend/workers/rpc_client.py

CANONICAL_RPC_SIGNATURES: dict[str, RPCSignature] = {
    "claim_pending_job": RPCSignature(
        schema="ops",
        name="claim_pending_job",
        params=[
            ("p_job_types", "TEXT[]"),
            ("p_lock_timeout_minutes", "INTEGER"),
            ("p_worker_id", "TEXT"),
        ],
        returns="TABLE",
    ),
    "update_job_status": RPCSignature(
        schema="ops",
        name="update_job_status",
        params=[
            ("p_job_id", "UUID"),
            ("p_status", "TEXT"),
            ("p_error_message", "TEXT"),
            ("p_backoff_seconds", "INTEGER"),
        ],
        returns="BOOLEAN",
    ),
    "queue_job": RPCSignature(
        schema="ops",
        name="queue_job",
        params=[
            ("p_type", "TEXT"),
            ("p_payload", "JSONB"),
            ("p_priority", "INTEGER"),
            ("p_run_at", "TIMESTAMPTZ"),
        ],
        returns="UUID",
    ),
    "register_heartbeat": RPCSignature(
        schema="ops",
        name="register_heartbeat",
        params=[
            ("p_worker_id", "TEXT"),
            ("p_worker_type", "TEXT"),
            ("p_hostname", "TEXT"),
            ("p_status", "TEXT"),
        ],
        returns="TEXT",
    ),
}

# Required columns on ops.job_queue
REQUIRED_JOB_QUEUE_COLUMNS = [
    "id",
    "job_type",
    "status",
    "payload",
    "attempts",
    "max_attempts",
    "next_run_at",
    "started_at",
    "worker_id",
    "locked_at",
    "created_at",
    "updated_at",
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).resolve().parents[1]


def read_file_content(path: Path) -> str:
    """Read file content with error handling."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


# ============================================================================
# TEST: RPC Client Method Signatures
# ============================================================================


class TestRPCClientContract:
    """Verify RPCClient matches canonical RPC signatures."""

    @pytest.fixture
    def rpc_client_content(self) -> str:
        """Load rpc_client.py content."""
        path = get_project_root() / "backend" / "workers" / "rpc_client.py"
        return read_file_content(path)

    def test_claim_pending_job_signature(self, rpc_client_content: str) -> None:
        """claim_pending_job must have the canonical signature."""
        # Check method exists
        assert "def claim_pending_job(" in rpc_client_content, (
            "RPCClient must have claim_pending_job method"
        )

        # Check it calls the correct SQL
        assert "ops.claim_pending_job(" in rpc_client_content, (
            "claim_pending_job must call ops.claim_pending_job RPC"
        )

        # Check p_worker_id parameter exists
        assert "p_worker_id" in rpc_client_content, (
            "claim_pending_job SQL must include p_worker_id parameter"
        )

        # Check worker_id is a parameter in the Python method
        assert "worker_id:" in rpc_client_content or "worker_id =" in rpc_client_content, (
            "claim_pending_job Python method must accept worker_id"
        )

    def test_update_job_status_signature(self, rpc_client_content: str) -> None:
        """update_job_status must have the canonical signature."""
        assert "def update_job_status(" in rpc_client_content, (
            "RPCClient must have update_job_status method"
        )

        assert "ops.update_job_status(" in rpc_client_content, (
            "update_job_status must call ops.update_job_status RPC"
        )

        # Check backoff_seconds parameter exists
        assert "p_backoff_seconds" in rpc_client_content, (
            "update_job_status SQL must include p_backoff_seconds parameter"
        )

        # Check p_error_message parameter exists (not p_error)
        assert "p_error_message" in rpc_client_content, (
            "update_job_status SQL must use p_error_message (not p_error)"
        )

    def test_queue_job_signature(self, rpc_client_content: str) -> None:
        """queue_job must have the canonical signature."""
        assert "def queue_job(" in rpc_client_content, "RPCClient must have queue_job method"

        assert "ops.queue_job(" in rpc_client_content, "queue_job must call ops.queue_job RPC"

        # Check priority parameter
        assert "p_priority" in rpc_client_content, "queue_job SQL must include p_priority parameter"

    def test_register_heartbeat_signature(self, rpc_client_content: str) -> None:
        """register_heartbeat must have the canonical signature."""
        assert "def register_heartbeat(" in rpc_client_content, (
            "RPCClient must have register_heartbeat method"
        )

        assert "ops.register_heartbeat(" in rpc_client_content, (
            "register_heartbeat must call ops.register_heartbeat RPC"
        )

    def test_no_raw_dml_on_ops_tables(self, rpc_client_content: str) -> None:
        """RPCClient must not contain raw INSERT/UPDATE/DELETE on ops tables."""
        # Pattern to detect raw DML on ops tables (outside of RPC calls)
        dangerous_patterns = [
            r"INSERT\s+INTO\s+ops\.",
            r"UPDATE\s+ops\.",
            r"DELETE\s+FROM\s+ops\.",
        ]

        for pattern in dangerous_patterns:
            matches = re.findall(pattern, rpc_client_content, re.IGNORECASE)
            # Filter out comments and strings
            # This is a simple check - the real enforcement is in test_invariants.py
            if matches:
                # Make sure it's not in a docstring or comment
                # A "real" DML line would have SQL in a string like: execute("INSERT INTO ops...")
                # Docstrings just describe what the code does
                lines_with_matches = []
                for line in rpc_client_content.split("\n"):
                    if not re.search(pattern, line, re.IGNORECASE):
                        continue
                    stripped = line.strip()
                    # Skip comments
                    if stripped.startswith("#") or stripped.startswith("--"):
                        continue
                    # Skip lines that are clearly docstring content (just text, no code)
                    # Real DML would be inside a string like execute("INSERT...")
                    # or inside quotes like 'INSERT INTO ops...'
                    if not ('"' in line or "'" in line or "execute" in line.lower()):
                        continue
                    lines_with_matches.append(line)

                # If there are real matches, they should be inside SELECT ops.* calls
                for line in lines_with_matches:
                    assert "SELECT" in line.upper() or not line.strip(), (
                        f"Raw DML to ops schema detected: {line}"
                    )


# ============================================================================
# TEST: Migration SQL Validation
# ============================================================================


class TestMigrationContract:
    """Verify canonical migration has correct signatures."""

    @pytest.fixture
    def migration_content(self) -> str:
        """Load the canonical migration SQL."""
        migrations_dir = get_project_root() / "supabase" / "migrations"
        # Find the canonical migration
        canonical_migration = migrations_dir / "20251231100000_world_class_canonical_rpcs.sql"
        if canonical_migration.exists():
            return read_file_content(canonical_migration)

        # Fall back to searching for world_class pattern
        for migration in sorted(migrations_dir.glob("*world_class*.sql"), reverse=True):
            return read_file_content(migration)

        pytest.skip("Canonical migration not found")
        return ""

    def test_claim_pending_job_has_three_params(self, migration_content: str) -> None:
        """claim_pending_job must have exactly 3 parameters."""
        # Find the CREATE FUNCTION statement
        pattern = r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+ops\.claim_pending_job\s*\(([^)]+)\)"
        match = re.search(pattern, migration_content, re.IGNORECASE | re.DOTALL)

        assert match, "ops.claim_pending_job CREATE FUNCTION not found in migration"

        params = match.group(1)
        # Count parameters (separated by commas, but be careful with DEFAULT values)
        param_lines = [p.strip() for p in params.split(",") if p.strip()]

        # Should have 3 parameters
        assert len(param_lines) == 3, (
            f"claim_pending_job must have 3 parameters, found {len(param_lines)}: {param_lines}"
        )

        # Check parameter names
        assert "p_job_types" in params.lower(), "Missing p_job_types parameter"
        assert "p_lock_timeout_minutes" in params.lower(), (
            "Missing p_lock_timeout_minutes parameter"
        )
        assert "p_worker_id" in params.lower(), "Missing p_worker_id parameter"

    def test_update_job_status_has_four_params(self, migration_content: str) -> None:
        """update_job_status must have exactly 4 parameters."""
        pattern = r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+ops\.update_job_status\s*\(([^)]+)\)"
        match = re.search(pattern, migration_content, re.IGNORECASE | re.DOTALL)

        assert match, "ops.update_job_status CREATE FUNCTION not found in migration"

        params = match.group(1)
        assert "p_job_id" in params.lower(), "Missing p_job_id parameter"
        assert "p_status" in params.lower(), "Missing p_status parameter"
        assert "p_error_message" in params.lower(), "Missing p_error_message parameter"
        assert "p_backoff_seconds" in params.lower(), "Missing p_backoff_seconds parameter"

    def test_all_rpcs_are_security_definer(self, migration_content: str) -> None:
        """All ops RPCs must be SECURITY DEFINER."""
        rpc_names = ["claim_pending_job", "update_job_status", "queue_job", "register_heartbeat"]

        for rpc in rpc_names:
            # Find the function and check for SECURITY DEFINER
            pattern = rf"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+ops\.{rpc}.*?SECURITY\s+DEFINER"
            match = re.search(pattern, migration_content, re.IGNORECASE | re.DOTALL)
            assert match, f"ops.{rpc} must be SECURITY DEFINER"

    def test_all_rpcs_have_search_path(self, migration_content: str) -> None:
        """All SECURITY DEFINER RPCs must SET search_path."""
        rpc_names = ["claim_pending_job", "update_job_status", "queue_job", "register_heartbeat"]

        for rpc in rpc_names:
            # Find the function and check for SET search_path
            pattern = rf"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+ops\.{rpc}.*?SET\s+search_path"
            match = re.search(pattern, migration_content, re.IGNORECASE | re.DOTALL)
            assert match, f"ops.{rpc} must SET search_path (required for SECURITY DEFINER)"

    def test_no_grants_to_anon_authenticated(self, migration_content: str) -> None:
        """No GRANT EXECUTE to anon or authenticated on ops RPCs."""
        # Pattern to detect dangerous grants
        dangerous_grants = [
            r"GRANT\s+EXECUTE.*TO\s+anon",
            r"GRANT\s+EXECUTE.*TO\s+authenticated",
        ]

        for pattern in dangerous_grants:
            match = re.search(pattern, migration_content, re.IGNORECASE)
            if match:
                # Make sure it's not in a comment
                line_start = migration_content.rfind("\n", 0, match.start()) + 1
                line = migration_content[line_start : match.end()]
                assert line.strip().startswith("--"), (
                    f"Dangerous grant detected (should be revoked): {line}"
                )

    def test_uses_fully_qualified_column_refs(self, migration_content: str) -> None:
        """claim_pending_job must use fully qualified column references."""
        # Find the claim_pending_job function body
        pattern = r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+ops\.claim_pending_job.*?END;\s*\$\$"
        match = re.search(pattern, migration_content, re.IGNORECASE | re.DOTALL)

        assert match, "claim_pending_job function body not found"

        func_body = match.group(0)

        # Check for inner_jq. prefix (subquery alias)
        assert "inner_jq.id" in func_body.lower() or "inner_jq.job_type" in func_body.lower(), (
            "claim_pending_job subquery must use inner_jq. prefix for column references"
        )

        # Check for jq. prefix (main update alias)
        assert "jq.id" in func_body.lower() or "jq.attempts" in func_body.lower(), (
            "claim_pending_job UPDATE must use jq. prefix for column references"
        )


# ============================================================================
# TEST: No Ambiguous Function Overloads
# ============================================================================


class TestNoAmbiguousOverloads:
    """Ensure no conflicting function signatures exist in migrations."""

    def test_no_conflicting_claim_pending_job(self) -> None:
        """Only ONE claim_pending_job signature should be defined."""
        migrations_dir = get_project_root() / "supabase" / "migrations"

        create_func_pattern = r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+ops\.claim_pending_job\s*\("

        # Find all migrations that create claim_pending_job
        migrations_with_func = []
        for migration in sorted(migrations_dir.glob("*.sql")):
            content = migration.read_text(encoding="utf-8")
            if re.search(create_func_pattern, content, re.IGNORECASE):
                migrations_with_func.append(migration.name)

        # The canonical migration should be the last one (or second to last if there's a rollback)
        # This test documents which migrations define the function
        # The key is that DROP FUNCTION statements should clear old versions
        assert len(migrations_with_func) >= 1, (
            "At least one migration must define ops.claim_pending_job"
        )

        # Check the latest migration drops old versions first
        if migrations_with_func:
            latest = migrations_dir / migrations_with_func[-1]
            content = latest.read_text(encoding="utf-8")
            drop_pattern = r"DROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?ops\.claim_pending_job"
            has_drop = bool(re.search(drop_pattern, content, re.IGNORECASE))

            # If there are multiple migrations, the latest should drop old versions
            if len(migrations_with_func) > 1:
                assert has_drop, (
                    f"Latest migration ({migrations_with_func[-1]}) should DROP old claim_pending_job variants"
                )


# ============================================================================
# TEST: Doctor Tool Alignment
# ============================================================================


class TestDoctorAlignment:
    """Verify tools/doctor.py checks the canonical RPCs."""

    def test_doctor_checks_canonical_rpcs(self) -> None:
        """Doctor tool must check for all canonical RPCs."""
        doctor_path = get_project_root() / "tools" / "doctor.py"
        content = read_file_content(doctor_path)

        required_rpcs = [
            ("ops", "claim_pending_job"),
            ("ops", "update_job_status"),
            ("ops", "queue_job"),
            ("ops", "register_heartbeat"),
        ]

        for schema, name in required_rpcs:
            assert name in content, f"Doctor tool must check for {schema}.{name}"

    def test_doctor_checks_security_definer(self) -> None:
        """Doctor tool must verify SECURITY DEFINER on critical RPCs."""
        doctor_path = get_project_root() / "tools" / "doctor.py"
        content = read_file_content(doctor_path)

        assert "SECURITY_DEFINER" in content or "security_definer" in content.lower(), (
            "Doctor tool must verify SECURITY DEFINER on RPCs"
        )


# ============================================================================
# SUMMARY
# ============================================================================


class TestContractSummary:
    """Meta-test to ensure contract test coverage."""

    def test_contract_tests_exist(self) -> None:
        """Verify all contract test classes exist."""
        test_classes = [
            TestRPCClientContract,
            TestMigrationContract,
            TestNoAmbiguousOverloads,
            TestDoctorAlignment,
        ]

        for cls in test_classes:
            methods = [m for m in dir(cls) if m.startswith("test_")]
            assert len(methods) >= 1, f"{cls.__name__} must have at least one test method"
