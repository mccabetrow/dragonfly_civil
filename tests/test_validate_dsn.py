"""
tests/test_validate_dsn.py
===========================
Unit tests for tools/validate_dsn.py

Tests DSN validation logic for production requirements and Supabase Pooler Identity Contract.

NOTE: These tests are standalone and do not require backend imports.
"""

from __future__ import annotations

import pytest

from tools.validate_dsn import (
    DEDICATED_POOLER_PATTERN,
    REQUIRED_PORT,
    REQUIRED_SSLMODE,
    SHARED_POOLER_PATTERN,
    ErrorCode,
    ValidationResult,
    parse_dsn,
    redact_dsn,
    validate_dsn,
)

# =============================================================================
# Tests for redact_dsn
# =============================================================================


class TestRedactDsn:
    """Tests for DSN password redaction."""

    def test_redact_simple_dsn(self) -> None:
        """Simple DSN with password should be redacted."""
        dsn = "postgresql://user:secret_password@host:5432/db"
        result = redact_dsn(dsn)
        assert "secret_password" not in result
        assert "***REDACTED***" in result
        assert "user:" in result
        assert "@host" in result

    def test_redact_complex_password(self) -> None:
        """Complex password with special chars should be redacted."""
        dsn = "postgresql://user:p@ss:w0rd!#$@host:5432/db"
        result = redact_dsn(dsn)
        assert "p@ss" not in result
        assert "***REDACTED***" in result

    def test_redact_preserves_host(self) -> None:
        """Redaction should preserve host and other parts."""
        dsn = "postgresql://myuser:mypass@db.xyz.supabase.co:5432/postgres?sslmode=require"
        result = redact_dsn(dsn)
        assert "db.xyz.supabase.co" in result
        assert "postgres" in result
        assert "sslmode=require" in result
        assert "mypass" not in result


# =============================================================================
# Tests for parse_dsn
# =============================================================================


class TestParseDsn:
    """Tests for DSN parsing."""

    def test_parse_standard_dsn(self) -> None:
        """Standard PostgreSQL DSN should parse correctly."""
        dsn = "postgresql://user:pass@host.example.com:6543/dbname?sslmode=require"
        host, port, user, params = parse_dsn(dsn)
        assert host == "host.example.com"
        assert port == 6543
        assert user == "user"
        assert params.get("sslmode") == ["require"]

    def test_parse_no_port(self) -> None:
        """DSN without port should return None for port."""
        dsn = "postgresql://user:pass@host.example.com/dbname"
        host, port, user, params = parse_dsn(dsn)
        assert host == "host.example.com"
        assert port is None
        assert user == "user"

    def test_parse_multiple_params(self) -> None:
        """DSN with multiple query params should parse all."""
        dsn = "postgresql://user:pass@host:5432/db?sslmode=require&connect_timeout=10"
        host, port, user, params = parse_dsn(dsn)
        assert params.get("sslmode") == ["require"]
        assert params.get("connect_timeout") == ["10"]


# =============================================================================
# Tests for SHARED_POOLER_PATTERN
# =============================================================================


class TestSharedPoolerPattern:
    """Tests for shared pooler host detection."""

    def test_matches_aws_pooler_host(self) -> None:
        """Pattern should match aws-*.pooler.supabase.com hosts."""
        assert SHARED_POOLER_PATTERN.match("aws-0-us-east-1.pooler.supabase.com")
        assert SHARED_POOLER_PATTERN.match("aws-0-eu-west-1.pooler.supabase.com")
        assert SHARED_POOLER_PATTERN.match("aws-1-ap-southeast-1.pooler.supabase.com")

    def test_does_not_match_direct_host(self) -> None:
        """Pattern should NOT match direct hosts."""
        assert SHARED_POOLER_PATTERN.match("db.abc123.supabase.co") is None

    def test_does_not_match_arbitrary_host(self) -> None:
        """Pattern should NOT match arbitrary hosts."""
        assert SHARED_POOLER_PATTERN.match("localhost") is None


# =============================================================================
# Tests for DEDICATED_POOLER_PATTERN
# =============================================================================


class TestDedicatedPoolerPattern:
    """Tests for dedicated pooler host detection."""

    def test_matches_dedicated_pooler_host(self) -> None:
        """Pattern should match db.<ref>.supabase.co hosts."""
        match = DEDICATED_POOLER_PATTERN.match("db.abc123.supabase.co")
        assert match is not None
        assert match.group(1) == "abc123"

    def test_extracts_project_ref(self) -> None:
        """Pattern should extract project ref from host."""
        match = DEDICATED_POOLER_PATTERN.match("db.iaketsyhmqbwaabgykux.supabase.co")
        assert match is not None
        assert match.group(1) == "iaketsyhmqbwaabgykux"

    def test_does_not_match_shared_pooler_host(self) -> None:
        """Pattern should NOT match shared pooler hosts."""
        assert DEDICATED_POOLER_PATTERN.match("aws-0-us-east-1.pooler.supabase.com") is None

    def test_does_not_match_arbitrary_host(self) -> None:
        """Pattern should NOT match arbitrary hosts."""
        assert DEDICATED_POOLER_PATTERN.match("localhost") is None


# =============================================================================
# Tests for validate_dsn - Valid cases (both pooler types)
# =============================================================================


class TestValidateDsnValid:
    """Tests for valid DSN validation."""

    def test_valid_shared_pooler_dsn_with_ref(self) -> None:
        """Valid shared pooler DSN with project ref in username should pass."""
        ref = "iaketsyhmqbwaabgykux"
        dsn = f"postgresql://postgres.{ref}:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        result = validate_dsn(dsn, expected_project_ref=ref)
        assert result.valid is True
        assert result.code == ErrorCode.VALID
        assert result.parsed_host == "aws-0-us-east-1.pooler.supabase.com"
        assert result.parsed_port == 6543
        assert result.pooler_mode == "shared"

    def test_valid_dedicated_pooler_dsn(self) -> None:
        """Valid dedicated pooler DSN (db.<ref>.supabase.co:6543) should pass."""
        ref = "iaketsyhmqbwaabgykux"
        dsn = f"postgresql://postgres:pass@db.{ref}.supabase.co:6543/postgres?sslmode=require"
        result = validate_dsn(dsn, expected_project_ref=ref)
        assert result.valid is True
        assert result.code == ErrorCode.VALID
        assert result.parsed_host == f"db.{ref}.supabase.co"
        assert result.parsed_port == 6543
        assert result.pooler_mode == "dedicated"


# =============================================================================
# Tests for validate_dsn - Invalid sslmode
# =============================================================================


class TestValidateDsnInvalidSslmode:
    """Tests for sslmode validation failures."""

    def test_sslmode_disable_fails(self) -> None:
        """sslmode=disable should fail validation."""
        dsn = "postgresql://postgres.ref:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=disable"
        result = validate_dsn(dsn)
        assert result.valid is False
        assert result.code == ErrorCode.SSLMODE_INVALID

    def test_sslmode_prefer_fails(self) -> None:
        """sslmode=prefer should fail validation (must be require)."""
        dsn = "postgresql://postgres.ref:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=prefer"
        result = validate_dsn(dsn)
        assert result.valid is False
        assert result.code == ErrorCode.SSLMODE_INVALID

    def test_missing_sslmode_fails(self) -> None:
        """Missing sslmode should fail validation."""
        dsn = "postgresql://postgres.ref:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        result = validate_dsn(dsn)
        assert result.valid is False
        assert result.code == ErrorCode.SSLMODE_INVALID


# =============================================================================
# Tests for validate_dsn - Direct connection (port 5432) forbidden
# =============================================================================


class TestValidateDsnDirectConnectionForbidden:
    """Tests for direct connection detection and rejection."""

    def test_direct_connection_port_5432_fails(self) -> None:
        """Direct connection (db.*.supabase.co:5432) should fail validation."""
        dsn = "postgresql://postgres:pass@db.abc123.supabase.co:5432/postgres?sslmode=require"
        result = validate_dsn(dsn)
        assert result.valid is False
        assert result.code == ErrorCode.DIRECT_CONNECTION_FORBIDDEN

    def test_dedicated_pooler_with_correct_port_passes(self) -> None:
        """Dedicated pooler host with port 6543 should pass."""
        ref = "abc123"
        dsn = f"postgresql://postgres:pass@db.{ref}.supabase.co:6543/postgres?sslmode=require"
        result = validate_dsn(dsn, expected_project_ref=ref)
        assert result.valid is True
        assert result.code == ErrorCode.VALID


# =============================================================================
# Tests for validate_dsn - Shared pooler identity validation
# =============================================================================


class TestSharedPoolerIdentityValidation:
    """Tests for shared pooler username format validation."""

    def test_shared_pooler_without_ref_fails(self) -> None:
        """Shared pooler with plain username should fail."""
        dsn = "postgresql://postgres:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        result = validate_dsn(dsn)
        assert result.valid is False
        assert result.code == ErrorCode.SHARED_POOLER_USER_MISSING_REF

    def test_shared_pooler_with_wrong_ref_fails(self) -> None:
        """Shared pooler with wrong project ref should fail."""
        dsn = "postgresql://postgres.wrongref:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        expected_ref = "iaketsyhmqbwaabgykux"
        result = validate_dsn(dsn, expected_project_ref=expected_ref)
        assert result.valid is False
        assert result.code == ErrorCode.PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER


# =============================================================================
# Tests for validate_dsn - Dedicated pooler identity validation
# =============================================================================


class TestDedicatedPoolerIdentityValidation:
    """Tests for dedicated pooler host ref validation."""

    def test_dedicated_pooler_wrong_host_ref_fails(self) -> None:
        """Dedicated pooler with wrong host ref should fail."""
        dsn = "postgresql://postgres:pass@db.wrongref.supabase.co:6543/postgres?sslmode=require"
        expected_ref = "iaketsyhmqbwaabgykux"
        result = validate_dsn(dsn, expected_project_ref=expected_ref)
        assert result.valid is False
        assert result.code == ErrorCode.DEDICATED_POOLER_HOST_REF_MISMATCH


# =============================================================================
# Tests for validate_dsn - Port validation
# =============================================================================


class TestValidateDsnPortValidation:
    """Tests for port validation."""

    def test_wrong_port_fails(self) -> None:
        """Non-standard port should fail."""
        dsn = "postgresql://postgres.ref:pass@aws-0-us-east-1.pooler.supabase.com:5433/postgres?sslmode=require"
        result = validate_dsn(dsn)
        assert result.valid is False
        assert result.code == ErrorCode.PORT_INVALID


# =============================================================================
# Tests for ValidationResult
# =============================================================================


class TestValidationResult:
    """Tests for ValidationResult data class."""

    def test_to_dict(self) -> None:
        """to_dict should return serializable dictionary."""
        result = ValidationResult(
            valid=True,
            code=ErrorCode.VALID,
            dsn_redacted="postgresql://user:***REDACTED***@host:6543/db",
            errors=[],
            warnings=["some warning"],
            parsed_host="host",
            parsed_port=6543,
            parsed_sslmode="require",
        )
        d = result.to_dict()
        assert d["valid"] is True
        assert d["parsed_port"] == 6543
        assert d["warnings"] == ["some warning"]

    def test_to_dict_with_errors(self) -> None:
        """to_dict should include errors."""
        result = ValidationResult(
            valid=False,
            code=ErrorCode.PORT_INVALID,
            dsn_redacted="redacted",
            errors=["error 1", "error 2"],
        )
        d = result.to_dict()
        assert d["valid"] is False
        assert len(d["errors"]) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
