"""
Tests for tools/prod_gate.py - Production Gate Checks

These tests verify the release gate logic using mocked database connections.
Integration tests (marked @pytest.mark.integration) test against real DB.

Note: Because prod_gate.py imports backend.core.logging which triggers Settings
validation at import time, we must either:
1. Use subprocess (for CLI tests) with proper env vars loaded from dotenv
2. Use conftest.py fixtures that load before collection

These tests rely on the conftest.py test fixtures that set up proper env vars.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load dotenv so subprocess tests have real credentials
try:
    from dotenv import load_dotenv

    _project_root = Path(__file__).parent.parent
    load_dotenv(_project_root / ".env")
except ImportError:
    pass  # dotenv not available - tests will skip if credentials missing


def _has_real_credentials() -> bool:
    """Check if we have real Supabase credentials in the environment."""
    # Check both new-style (_DEV suffix) and legacy (no suffix) env vars
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY_DEV", "")
    if not key or len(key) < 100:
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return len(key) >= 100


def _get_test_env() -> dict[str, str]:
    """Get environment for subprocess tests.

    Inherit actual env vars (which should be loaded from .env) and just
    ensure SUPABASE_MODE is set to dev. Don't override credentials.
    """
    env = os.environ.copy()
    env["SUPABASE_MODE"] = "dev"
    return env


# =============================================================================
# Sanity Tests (no credentials required)
# =============================================================================


class TestProdGateSanity:
    """Basic sanity tests that don't require credentials."""

    def test_test_file_is_importable(self) -> None:
        """This test file can be collected without errors."""
        assert True

    def test_has_real_credentials_returns_bool(self) -> None:
        """_has_real_credentials() returns a boolean."""
        result = _has_real_credentials()
        assert isinstance(result, bool)

    def test_get_test_env_returns_dict(self) -> None:
        """_get_test_env() returns a dict with SUPABASE_MODE."""
        env = _get_test_env()
        assert isinstance(env, dict)
        assert env.get("SUPABASE_MODE") == "dev"


# =============================================================================
# No-Credential --help Tests (CRITICAL: must work with empty env)
# =============================================================================


class TestToolsHelpNoCredentials:
    """
    Test that operational tools can run --help WITHOUT any environment vars.

    This is a critical requirement for developer ergonomics:
    - `python -m tools.prod_gate --help` should exit 0 even if SUPABASE_* missing
    - `python -m tools.prod_smoke --help` should exit 0 even if SUPABASE_* missing
    - `python -m tools.doctor --help` should exit 0 even if SUPABASE_* missing

    These tests run in a subprocess with a deliberately empty environment
    (no SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_DB_URL).
    """

    @pytest.fixture
    def project_root(self) -> Path:
        """Get project root directory."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def empty_env(self) -> dict[str, str]:
        """Return an environment with Supabase vars explicitly cleared."""
        env = os.environ.copy()
        # Clear all Supabase-related vars
        for key in list(env.keys()):
            if "SUPABASE" in key or key == "ENV_FILE":
                del env[key]
        # Set ENV_FILE to nonexistent to prevent .env loading
        env["ENV_FILE"] = "nonexistent.env"
        return env

    def test_prod_gate_help_no_credentials(
        self, project_root: Path, empty_env: dict[str, str]
    ) -> None:
        """prod_gate --help exits 0 with no SUPABASE_* vars set."""
        result = subprocess.run(
            [sys.executable, "-m", "tools.prod_gate", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
            env=empty_env,
        )
        assert result.returncode == 0, (
            f"prod_gate --help failed without credentials.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "usage:" in result.stdout.lower() or "--help" in result.stdout

    def test_prod_smoke_help_no_credentials(
        self, project_root: Path, empty_env: dict[str, str]
    ) -> None:
        """prod_smoke --help exits 0 with no SUPABASE_* vars set."""
        result = subprocess.run(
            [sys.executable, "-m", "tools.prod_smoke", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
            env=empty_env,
        )
        assert result.returncode == 0, (
            f"prod_smoke --help failed without credentials.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "usage:" in result.stdout.lower() or "--help" in result.stdout

    def test_doctor_help_no_credentials(
        self, project_root: Path, empty_env: dict[str, str]
    ) -> None:
        """doctor --help exits 0 with no SUPABASE_* vars set."""
        result = subprocess.run(
            [sys.executable, "-m", "tools.doctor", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
            env=empty_env,
        )
        assert result.returncode == 0, (
            f"doctor --help failed without credentials.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        # Click uses "Usage:" with capital U
        assert "usage:" in result.stdout.lower() or "Usage:" in result.stdout

    def test_doctor_all_help_no_credentials(
        self, project_root: Path, empty_env: dict[str, str]
    ) -> None:
        """doctor_all --help exits 0 with no SUPABASE_* vars set."""
        result = subprocess.run(
            [sys.executable, "-m", "tools.doctor_all", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
            env=empty_env,
        )
        assert result.returncode == 0, (
            f"doctor_all --help failed without credentials.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "usage:" in result.stdout.lower() or "Usage:" in result.stdout


# =============================================================================
# CLI Interface Tests (subprocess-based, avoid import issues)
# =============================================================================


@pytest.mark.skipif(
    not _has_real_credentials(),
    reason="SUPABASE_SERVICE_ROLE_KEY_DEV not set or too short",
)
class TestProdGateCliInterface:
    """Test prod_gate via CLI interface."""

    @pytest.fixture
    def project_root(self) -> Path:
        """Get project root directory."""
        return Path(__file__).parent.parent

    def test_prod_gate_help(self, project_root: Path) -> None:
        """prod_gate --help exits cleanly."""
        result = subprocess.run(
            [sys.executable, "-m", "tools.prod_gate", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
            env=_get_test_env(),
        )
        assert result.returncode == 0, f"Failed with stderr: {result.stderr}"
        assert "Dragonfly Release Gate" in result.stdout

    def test_prod_gate_skip_choices_include_new_options(self, project_root: Path) -> None:
        """--skip choices include role, rpc, drift."""
        result = subprocess.run(
            [sys.executable, "-m", "tools.prod_gate", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
            env=_get_test_env(),
        )
        assert result.returncode == 0, f"Failed with stderr: {result.stderr}"
        assert "role" in result.stdout
        assert "rpc" in result.stdout
        assert "drift" in result.stdout


# =============================================================================
# Unit Tests - Test data structures and skip logic only (no imports needed)
# =============================================================================


@pytest.mark.skipif(
    not _has_real_credentials(),
    reason="SUPABASE_SERVICE_ROLE_KEY_DEV not set or too short",
)
class TestCheckFunctions:
    """Unit tests for individual check functions using skip=True."""

    def test_check_db_connectivity_skip(self) -> None:
        """check_db_connectivity with skip=True returns skipped result."""
        from tools.prod_gate import check_db_connectivity

        result = check_db_connectivity("dev", skip=True)
        assert result.skipped is True
        assert result.passed is True
        assert "Skipped" in result.message

    def test_check_current_user_skip(self) -> None:
        """check_current_user with skip=True returns skipped result."""
        from tools.prod_gate import check_current_user

        result = check_current_user("dev", skip=True)
        assert result.skipped is True

    def test_check_worker_rpc_capability_skip(self) -> None:
        """check_worker_rpc_capability with skip=True returns skipped result."""
        from tools.prod_gate import check_worker_rpc_capability

        result = check_worker_rpc_capability("dev", skip=True)
        assert result.skipped is True

    def test_check_schema_drift_skip(self) -> None:
        """check_schema_drift with skip=True returns skipped result."""
        from tools.prod_gate import check_schema_drift

        result = check_schema_drift("dev", skip=True)
        assert result.skipped is True

    def test_check_migrations_skip(self) -> None:
        """check_migrations with skip=True returns skipped result."""
        from tools.prod_gate import check_migrations

        result = check_migrations("dev", skip=True)
        assert result.skipped is True


@pytest.mark.skipif(
    not _has_real_credentials(),
    reason="SUPABASE_SERVICE_ROLE_KEY_DEV not set or too short",
)
class TestDataStructures:
    """Tests for CheckResult and GateReport data structures.

    These tests import from tools.prod_gate which triggers Settings validation.
    Tests will pass locally (with .env loaded) but should be marked @skipif
    for CI environments without credentials.
    """

    def test_check_result_to_dict(self) -> None:
        """CheckResult.to_dict() returns proper structure."""
        from tools.prod_gate import CheckResult

        result = CheckResult(
            name="Test",
            passed=False,
            message="Failed",
            remediation="Fix it",
            details={"key": "value"},
        )
        d = result.to_dict()
        assert d["name"] == "Test"
        assert d["passed"] is False
        assert d["remediation"] == "Fix it"
        assert d["details"]["key"] == "value"

    def test_gate_report_passes_when_all_pass(self) -> None:
        """GateReport.overall_passed is True when all checks pass."""
        from tools.prod_gate import CheckResult, GateReport

        report = GateReport(
            mode="dev",
            timestamp="2024-01-01T00:00:00Z",
            environment="dev",
        )
        report.add(CheckResult(name="A", passed=True, message="OK"))
        report.add(CheckResult(name="B", passed=True, message="OK"))
        report.finalize()

        assert report.overall_passed is True
        assert report.pass_count == 2
        assert report.fail_count == 0

    def test_gate_report_fails_when_any_fails(self) -> None:
        """GateReport.overall_passed is False when any check fails."""
        from tools.prod_gate import CheckResult, GateReport

        report = GateReport(
            mode="prod",
            timestamp="2024-01-01T00:00:00Z",
            environment="prod",
        )
        report.add(CheckResult(name="A", passed=True, message="OK"))
        report.add(CheckResult(name="B", passed=False, message="Failed"))
        report.finalize()

        assert report.overall_passed is False
        assert report.pass_count == 1
        assert report.fail_count == 1

    def test_skipped_checks_dont_affect_pass_status(self) -> None:
        """Skipped checks don't count toward pass/fail."""
        from tools.prod_gate import CheckResult, GateReport

        report = GateReport(
            mode="dev",
            timestamp="2024-01-01T00:00:00Z",
            environment="dev",
        )
        report.add(CheckResult(name="A", passed=True, message="OK"))
        report.add(CheckResult(name="B", passed=True, message="Skipped", skipped=True))
        report.finalize()

        assert report.overall_passed is True
        assert report.pass_count == 1
        assert report.skip_count == 1

    def test_gate_report_to_dict_json_serializable(self) -> None:
        """GateReport.to_dict() is JSON serializable."""
        from tools.prod_gate import CheckResult, GateReport

        report = GateReport(
            mode="prod",
            timestamp="2024-01-01T00:00:00Z",
            environment="prod",
        )
        report.add(CheckResult(name="Test", passed=True, message="OK"))
        report.finalize()

        json_str = json.dumps(report.to_dict())
        assert "Test" in json_str


# =============================================================================
# Mocked Database Tests
# =============================================================================


def _create_mock_connection(cursor_mock: MagicMock) -> MagicMock:
    """Helper to create a properly mocked psycopg connection."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor_mock)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


@pytest.mark.skipif(
    not _has_real_credentials(),
    reason="SUPABASE_SERVICE_ROLE_KEY_DEV not set or too short",
)
class TestDbChecksWithMocking:
    """Tests with mocked database connections."""

    def test_db_connectivity_passes_with_all_tables(self) -> None:
        """check_db_connectivity passes when all tables exist."""
        from tools.prod_gate import check_db_connectivity

        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            (1,),  # SELECT 1
            (True, True, True),  # All tables exist
        ]
        mock_conn = _create_mock_connection(mock_cursor)

        with (
            patch("tools.prod_gate.psycopg.connect", return_value=mock_conn),
            patch("tools.prod_gate.get_supabase_db_url", return_value="mock://"),
        ):
            result = check_db_connectivity("dev")

        assert result.passed is True

    def test_db_connectivity_fails_with_missing_table(self) -> None:
        """check_db_connectivity fails when table is missing."""
        from tools.prod_gate import check_db_connectivity

        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            (1,),  # SELECT 1
            (True, False, True),  # worker_heartbeats missing
        ]
        mock_conn = _create_mock_connection(mock_cursor)

        with (
            patch("tools.prod_gate.psycopg.connect", return_value=mock_conn),
            patch("tools.prod_gate.get_supabase_db_url", return_value="mock://"),
        ):
            result = check_db_connectivity("dev")

        assert result.passed is False
        assert "worker_heartbeats" in result.message

    def test_current_user_passes_for_expected_role(self) -> None:
        """check_current_user passes for expected roles."""
        from tools.prod_gate import check_current_user

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("postgres", "postgres", "dragonfly")
        mock_conn = _create_mock_connection(mock_cursor)

        with (
            patch("tools.prod_gate.psycopg.connect", return_value=mock_conn),
            patch("tools.prod_gate.get_supabase_db_url", return_value="mock://"),
        ):
            result = check_current_user("dev")

        assert result.passed is True
        assert "postgres" in result.message

    def test_current_user_fails_for_unexpected_role(self) -> None:
        """check_current_user fails for unexpected roles."""
        from tools.prod_gate import check_current_user

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("hacker", "hacker", "dragonfly")
        mock_conn = _create_mock_connection(mock_cursor)

        with (
            patch("tools.prod_gate.psycopg.connect", return_value=mock_conn),
            patch("tools.prod_gate.get_supabase_db_url", return_value="mock://"),
        ):
            result = check_current_user("dev")

        assert result.passed is False
        assert "unexpected" in result.message.lower()

    def test_worker_rpc_passes_when_all_exist(self) -> None:
        """check_worker_rpc_capability passes when all RPCs exist."""
        from tools.prod_gate import check_worker_rpc_capability

        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            (None,),  # claim_pending_job returns NULL (no jobs - OK)
            (1,),  # register_heartbeat exists
            (1,),  # queue_job exists
        ]
        mock_conn = _create_mock_connection(mock_cursor)

        with (
            patch("tools.prod_gate.psycopg.connect", return_value=mock_conn),
            patch("tools.prod_gate.get_supabase_db_url", return_value="mock://"),
        ):
            result = check_worker_rpc_capability("dev")

        assert result.passed is True

    def test_schema_drift_passes_when_all_views_exist(self) -> None:
        """check_schema_drift passes when all critical views exist."""
        from tools.prod_gate import check_schema_drift

        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [
                ("public.v_plaintiffs_overview",),
                ("public.v_judgment_pipeline",),
                ("public.v_enforcement_overview",),
                ("public.v_enforcement_recent",),
                ("public.v_plaintiff_call_queue",),
            ],
            [
                ("ops.claim_pending_job",),
                ("ops.register_heartbeat",),
                ("ops.queue_job",),
            ],
        ]
        mock_conn = _create_mock_connection(mock_cursor)

        with (
            patch("tools.prod_gate.psycopg.connect", return_value=mock_conn),
            patch("tools.prod_gate.get_supabase_db_url", return_value="mock://"),
        ):
            result = check_schema_drift("dev")

        assert result.passed is True

    def test_schema_drift_fails_when_view_missing(self) -> None:
        """check_schema_drift fails when a critical view is missing."""
        from tools.prod_gate import check_schema_drift

        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [
            [
                ("public.v_plaintiffs_overview",),
                ("public.v_enforcement_overview",),
                ("public.v_enforcement_recent",),
                ("public.v_plaintiff_call_queue",),
            ],
        ]
        mock_conn = _create_mock_connection(mock_cursor)

        with (
            patch("tools.prod_gate.psycopg.connect", return_value=mock_conn),
            patch("tools.prod_gate.get_supabase_db_url", return_value="mock://"),
        ):
            result = check_schema_drift("dev")

        assert result.passed is False
        assert "v_judgment_pipeline" in str(result.details.get("missing_views", []))


# =============================================================================
# Integration Tests (require real database)
# =============================================================================


@pytest.mark.integration
class TestProdGateIntegration:
    """Integration tests for prod_gate against real database."""

    def test_db_connectivity_real(self) -> None:
        """Test DB connectivity against real dev database."""
        import os

        if not os.getenv("SUPABASE_DB_URL_DEV"):
            pytest.skip("SUPABASE_DB_URL_DEV not set")

        from tools.prod_gate import check_db_connectivity

        result = check_db_connectivity("dev")
        assert result.passed or "connection" not in result.message.lower()

    def test_full_dev_gate_via_cli(self) -> None:
        """Run full dev gate via CLI."""
        import os

        if not os.getenv("SUPABASE_DB_URL_DEV"):
            pytest.skip("SUPABASE_DB_URL_DEV not set")

        project_root = Path(__file__).parent.parent
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.prod_gate",
                "--mode",
                "dev",
                "--skip",
                "pytest",
                "lint",
                "evaluator",
                "--json",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
        )

        try:
            report = json.loads(result.stdout)
            assert "checks" in report
            assert "overall_passed" in report
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON output: {result.stdout[:500]}")
