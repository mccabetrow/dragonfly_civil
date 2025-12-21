"""
Tests for tools/doctor.py - DoctorDiagnostics CLI

These tests verify the doctor module's diagnostic suite:
- CLI invocation and exit codes
- Individual check result structure
- PostgREST retry logic
"""

from __future__ import annotations

from click.testing import CliRunner

from tools import doctor


class FakeCheckResult:
    """Mock CheckResult for testing."""

    def __init__(self, passed: bool, message: str, details: dict | None = None):
        self.passed = passed
        self.message = message
        self.details = details


def test_doctor_diagnostics_init():
    """Test DoctorDiagnostics class initialization."""
    diag = doctor.DoctorDiagnostics(verbose=False)
    assert diag.verbose is False
    assert diag.checks_run == 0
    assert diag.checks_passed == 0
    assert diag.checks_failed == 0


def test_doctor_diagnostics_verbose_flag():
    """Test verbose flag is properly set."""
    diag = doctor.DoctorDiagnostics(verbose=True)
    assert diag.verbose is True


def test_check_result_named_tuple():
    """Test CheckResult structure is correct."""
    result = doctor.CheckResult(passed=True, message="OK", details={"key": "val"})
    assert result.passed is True
    assert result.message == "OK"
    assert result.details == {"key": "val"}


def test_check_result_defaults():
    """Test CheckResult default values."""
    result = doctor.CheckResult(passed=False, message="Failed")
    assert result.passed is False
    assert result.message == "Failed"
    assert result.details is None


def test_doctor_constants():
    """Test module-level constants are defined correctly."""
    assert doctor.EXIT_OK == 0
    assert doctor.EXIT_FAILED == 1
    assert doctor.EXIT_CRITICAL == 2
    assert doctor.POSTGREST_MAX_RETRIES == 3
    assert doctor.POSTGREST_RETRY_DELAY_SECONDS == 2


def test_required_rpcs_defined():
    """Test required RPC list is populated."""
    assert len(doctor.REQUIRED_RPCS) >= 4
    schemas = [schema for schema, _ in doctor.REQUIRED_RPCS]
    assert "ops" in schemas


def test_security_definer_rpcs_defined():
    """Test security definer RPC list is populated."""
    assert len(doctor.SECURITY_DEFINER_RPCS) >= 3
    for schema, fn_name in doctor.SECURITY_DEFINER_RPCS:
        assert schema == "ops"
        assert fn_name in ["claim_pending_job", "update_job_status", "queue_job"]


def test_rls_required_tables_defined():
    """Test RLS required tables list is populated."""
    assert len(doctor.RLS_REQUIRED_TABLES) >= 2
    table_names = [table for _, table in doctor.RLS_REQUIRED_TABLES]
    assert "job_queue" in table_names
    assert "worker_heartbeats" in table_names


def test_doctor_cli_help():
    """Test CLI help output."""
    runner = CliRunner()
    result = runner.invoke(doctor.main, ["--help"])
    assert result.exit_code == 0
    assert "Run the Dragonfly Doctor diagnostic suite" in result.output
    assert "--verbose" in result.output
    assert "--env" in result.output
