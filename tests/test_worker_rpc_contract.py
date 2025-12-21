"""Tests for Worker RPC Contract Compliance.

Verifies that workers adhere to the canonical ops RPC signatures:
- ops.claim_pending_job(job_types TEXT[], lock_timeout_minutes INTEGER, worker_id TEXT)
- ops.update_job_status(job_id UUID, status TEXT, error_message TEXT, backoff_seconds INTEGER)
- ops.queue_job(job_type TEXT, payload JSONB, priority INTEGER, run_at TIMESTAMPTZ)
- ops.register_heartbeat(worker_id TEXT, worker_type TEXT, hostname TEXT, status TEXT)

Contract requirements:
1. claim_pending_job MUST include worker_id for traceability
2. update_job_status on retry MUST include backoff_seconds
3. No raw SQL writes to ops/intake/enforcement schemas
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

import pytest

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def worker_files() -> list[Path]:
    """Get all worker Python files."""
    workers_dir = Path(__file__).parent.parent / "backend" / "workers"
    return list(workers_dir.glob("*.py"))


@pytest.fixture
def rpc_client_source() -> str:
    """Get the rpc_client.py source code."""
    rpc_path = Path(__file__).parent.parent / "backend" / "workers" / "rpc_client.py"
    return rpc_path.read_text(encoding="utf-8")


# =============================================================================
# RPC Client Signature Tests
# =============================================================================


class TestRPCClientSignatures:
    """Verify RPCClient method signatures match canonical DB contract."""

    def test_claim_pending_job_accepts_worker_id(self, rpc_client_source: str):
        """claim_pending_job MUST accept worker_id parameter."""
        tree = ast.parse(rpc_client_source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "claim_pending_job":
                arg_names = [arg.arg for arg in node.args.args]
                # Skip 'self' for class methods
                if "self" in arg_names:
                    arg_names.remove("self")

                assert "worker_id" in arg_names, (
                    f"claim_pending_job must accept worker_id parameter. "
                    f"Found args: {arg_names}"
                )
                return

        pytest.fail("claim_pending_job function not found in rpc_client.py")

    def test_update_job_status_accepts_backoff_seconds(self, rpc_client_source: str):
        """update_job_status MUST accept backoff_seconds parameter."""
        tree = ast.parse(rpc_client_source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "update_job_status":
                arg_names = [arg.arg for arg in node.args.args]
                # Also check kwonlyargs
                arg_names.extend(arg.arg for arg in node.args.kwonlyargs)

                assert "backoff_seconds" in arg_names, (
                    f"update_job_status must accept backoff_seconds parameter. "
                    f"Found args: {arg_names}"
                )
                return

        pytest.fail("update_job_status function not found in rpc_client.py")

    def test_register_heartbeat_accepts_all_params(self, rpc_client_source: str):
        """register_heartbeat MUST accept worker_id, worker_type, hostname, status."""
        tree = ast.parse(rpc_client_source)

        required_params = {"worker_id", "worker_type", "hostname", "status"}

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "register_heartbeat":
                arg_names = set(arg.arg for arg in node.args.args)
                arg_names.update(arg.arg for arg in node.args.kwonlyargs)
                arg_names.discard("self")

                missing = required_params - arg_names
                assert not missing, (
                    f"register_heartbeat missing required params: {missing}. "
                    f"Found args: {arg_names}"
                )
                return

        pytest.fail("register_heartbeat function not found in rpc_client.py")


# =============================================================================
# Bootstrap Contract Tests
# =============================================================================


class TestBootstrapContract:
    """Verify WorkerBootstrap uses correct RPC patterns."""

    def test_default_claim_passes_worker_id(self):
        """_default_claim_job MUST pass worker_id to claim_pending_job."""
        bootstrap_path = Path(__file__).parent.parent / "backend" / "workers" / "bootstrap.py"
        source = bootstrap_path.read_text(encoding="utf-8")

        # Check that claim_pending_job call includes worker_id
        assert (
            "worker_id=worker_id" in source or "worker_id=" in source
        ), "_default_claim_job must pass worker_id to claim_pending_job"

    def test_mark_job_retry_uses_backoff_seconds(self):
        """_mark_job_retry MUST pass backoff_seconds to update_job_status."""
        bootstrap_path = Path(__file__).parent.parent / "backend" / "workers" / "bootstrap.py"
        source = bootstrap_path.read_text(encoding="utf-8")

        # Check that update_job_status call includes backoff_seconds in retry path
        assert (
            "backoff_seconds=backoff_seconds" in source or "backoff_seconds=" in source
        ), "_mark_job_retry must pass backoff_seconds to update_job_status"


# =============================================================================
# No Raw SQL Tests
# =============================================================================


class TestNoRawSQL:
    """Verify workers don't use raw SQL for ops/intake/enforcement writes."""

    # SQL patterns that indicate direct writes (not reads)
    WRITE_PATTERNS = [
        "INSERT INTO ops.",
        "UPDATE ops.",
        "DELETE FROM ops.",
        "INSERT INTO intake.",
        "UPDATE intake.",
        "DELETE FROM intake.",
        "INSERT INTO enforcement.",
        "UPDATE enforcement.",
        "DELETE FROM enforcement.",
    ]

    # Allowed patterns (e.g., in comments or test mocks)
    ALLOWED_CONTEXTS = [
        "# ",  # Comments
        '"""',  # Docstrings
        "'''",  # Docstrings
        "mock",  # Test mocks
        "Mock",
    ]

    def test_no_raw_sql_in_simplicity_worker(self):
        """simplicity_ingest_worker must not use raw SQL for ops/intake writes."""
        worker_path = (
            Path(__file__).parent.parent / "backend" / "workers" / "simplicity_ingest_worker.py"
        )
        self._check_no_raw_sql(worker_path)

    def test_no_raw_sql_in_enforcement_engine(self):
        """enforcement_engine must not use raw SQL for ops/intake writes."""
        worker_path = Path(__file__).parent.parent / "backend" / "workers" / "enforcement_engine.py"
        self._check_no_raw_sql(worker_path)

    def test_no_raw_sql_in_ingest_processor(self):
        """ingest_processor must not use raw SQL for ops/intake writes."""
        worker_path = Path(__file__).parent.parent / "backend" / "workers" / "ingest_processor.py"
        self._check_no_raw_sql(worker_path)

    def test_no_raw_sql_in_bootstrap(self):
        """bootstrap must not use raw SQL for ops writes."""
        worker_path = Path(__file__).parent.parent / "backend" / "workers" / "bootstrap.py"
        self._check_no_raw_sql(worker_path)

    def _check_no_raw_sql(self, file_path: Path) -> None:
        """Check a file for raw SQL write patterns."""
        if not file_path.exists():
            pytest.skip(f"File not found: {file_path}")

        source = file_path.read_text(encoding="utf-8")
        lines = source.splitlines()
        violations = []

        for i, line in enumerate(lines, 1):
            # Skip allowed contexts
            if any(ctx in line for ctx in self.ALLOWED_CONTEXTS):
                continue

            for pattern in self.WRITE_PATTERNS:
                if pattern.lower() in line.lower():
                    violations.append(f"Line {i}: {line.strip()}")

        assert not violations, f"Raw SQL writes found in {file_path.name}:\n" + "\n".join(
            violations
        )


# =============================================================================
# Worker Integration Tests (require mocking)
# =============================================================================


class TestWorkerJobClaimContract:
    """Test that workers use bootstrap's default claim (with worker_id)."""

    def test_simplicity_worker_uses_default_claimer(self):
        """simplicity_ingest_worker.run_worker() must NOT pass job_claimer."""
        worker_path = (
            Path(__file__).parent.parent / "backend" / "workers" / "simplicity_ingest_worker.py"
        )
        source = worker_path.read_text(encoding="utf-8")

        # The run_worker function should call bootstrap.run() without job_claimer
        # This ensures the bootstrap's _default_claim_job (with worker_id) is used
        assert (
            "job_claimer=" not in source or "job_claimer=claim_simplicity_job" not in source
        ), "simplicity_ingest_worker should use bootstrap's default claim (with worker_id)"

    def test_enforcement_engine_uses_default_claimer(self):
        """enforcement_engine.main() must NOT pass job_claimer."""
        worker_path = Path(__file__).parent.parent / "backend" / "workers" / "enforcement_engine.py"
        source = worker_path.read_text(encoding="utf-8")

        # The main function should call bootstrap.run() without _job_claimer
        assert (
            "_job_claimer" not in source
            or "bootstrap.run(_job_processor, _job_claimer)" not in source
        ), "enforcement_engine should use bootstrap's default claim (with worker_id)"

    def test_ingest_processor_uses_default_claimer(self):
        """ingest_processor entry point must NOT pass job_claimer."""
        worker_path = Path(__file__).parent.parent / "backend" / "workers" / "ingest_processor.py"
        source = worker_path.read_text(encoding="utf-8")

        # Check that bootstrap.run() is called without _job_claimer
        assert (
            "_job_claimer" not in source
            or "bootstrap.run(_job_processor, _job_claimer)" not in source
        ), "ingest_processor should use bootstrap's default claim (with worker_id)"
