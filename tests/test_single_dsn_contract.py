"""
tests/test_single_dsn_contract.py
=================================
Unit tests for the Single DSN Contract implementation.

Tests cover:
- DATABASE_URL as the canonical variable
- SUPABASE_DB_URL deprecation warnings
- Project reference extraction from DSNs
- Environment validation (dev/prod)
- Tool exit codes for probe_db

Run with:
    pytest tests/test_single_dsn_contract.py -v

Author: Principal Database Reliability Engineer
Date: 2026-01-15
"""

from __future__ import annotations

import os
import sys
import warnings
from unittest.mock import patch

import pytest

# Ensure src module is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dsn_compat import (
    CANONICAL_VAR,
    DEPRECATED_VARS,
    DEV_PROJECT_REF,
    PROD_PROJECT_REF,
    PROD_REQUIRED_PORT,
    extract_host_port,
    extract_project_ref,
    get_database_url,
    redact_dsn,
    validate_dsn_for_env,
)

# =============================================================================
# Test DSNs
# =============================================================================

# Valid production DSN (dedicated pooler, port 6543)
VALID_PROD_DSN = (
    f"postgresql://dragonfly_app:password123@db.{PROD_PROJECT_REF}.supabase.co"
    f":{PROD_REQUIRED_PORT}/postgres?sslmode=require"
)

# Valid dev DSN (dedicated pooler)
VALID_DEV_DSN = (
    f"postgresql://dragonfly_app:password@db.{DEV_PROJECT_REF}.supabase.co"
    f":5432/postgres?sslmode=require"
)

# Valid dev DSN (localhost)
VALID_LOCALHOST_DSN = "postgresql://postgres:password@localhost:5432/postgres"

# Shared pooler DSN (username contains project ref)
SHARED_POOLER_DSN = (
    f"postgresql://postgres.{PROD_PROJECT_REF}:password"
    f"@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
)


# =============================================================================
# DSN Parsing Tests
# =============================================================================


class TestExtractHostPort:
    """Tests for extract_host_port function."""

    def test_standard_dsn(self):
        """Standard DSN should parse correctly."""
        host, port = extract_host_port(VALID_PROD_DSN)
        assert host == f"db.{PROD_PROJECT_REF}.supabase.co"
        assert port == PROD_REQUIRED_PORT

    def test_localhost_dsn(self):
        """Localhost DSN should parse correctly."""
        host, port = extract_host_port(VALID_LOCALHOST_DSN)
        assert host == "localhost"
        assert port == 5432

    def test_no_port(self):
        """DSN without port should return None for port."""
        dsn = "postgresql://user:pass@host/db"
        host, port = extract_host_port(dsn)
        assert host == "host"
        assert port is None

    def test_invalid_dsn(self):
        """Invalid DSN should return None for both."""
        host, port = extract_host_port("not-a-dsn")
        # urlparse doesn't fail, just gives empty hostname
        assert host is None or host == ""


class TestExtractProjectRef:
    """Tests for extract_project_ref function."""

    def test_dedicated_pooler_host(self):
        """Project ref from db.<ref>.supabase.co pattern."""
        ref = extract_project_ref(VALID_PROD_DSN)
        assert ref == PROD_PROJECT_REF

    def test_shared_pooler_username(self):
        """Project ref from username.<ref> pattern."""
        ref = extract_project_ref(SHARED_POOLER_DSN)
        assert ref == PROD_PROJECT_REF

    def test_dev_project_ref(self):
        """Dev project ref should be extracted correctly."""
        ref = extract_project_ref(VALID_DEV_DSN)
        assert ref == DEV_PROJECT_REF

    def test_localhost_no_ref(self):
        """Localhost should return None (no project ref)."""
        ref = extract_project_ref(VALID_LOCALHOST_DSN)
        assert ref is None

    def test_custom_host_no_ref(self):
        """Custom host without Supabase pattern should return None."""
        dsn = "postgresql://user:pass@mydb.example.com:5432/postgres"
        ref = extract_project_ref(dsn)
        assert ref is None


class TestRedactDsn:
    """Tests for redact_dsn function."""

    def test_password_redacted(self):
        """Password should be replaced with ****."""
        redacted = redact_dsn(VALID_PROD_DSN)
        assert "password123" not in redacted
        assert "****" in redacted
        assert PROD_PROJECT_REF in redacted  # Host preserved

    def test_special_chars_in_password(self):
        """Password with special chars should be fully redacted."""
        dsn = "postgresql://user:p@ss!word#123@host:5432/db"
        redacted = redact_dsn(dsn)
        assert "****" in redacted
        assert "p@ss" not in redacted


# =============================================================================
# Environment Validation Tests
# =============================================================================


class TestValidateDsnForEnv:
    """Tests for validate_dsn_for_env function."""

    def test_valid_prod_dsn(self):
        """Valid prod DSN should pass."""
        is_valid, error = validate_dsn_for_env(VALID_PROD_DSN, "prod")
        assert is_valid is True
        assert error == ""

    def test_prod_dsn_wrong_port(self):
        """Prod DSN with port 5432 should fail."""
        dsn = f"postgresql://user:pass@db.{PROD_PROJECT_REF}.supabase.co:5432/postgres"
        is_valid, error = validate_dsn_for_env(dsn, "prod")
        assert is_valid is False
        assert "6543" in error
        assert "FORBIDDEN" in error

    def test_prod_dsn_wrong_ref(self):
        """Prod DSN with dev project ref should fail."""
        dsn = f"postgresql://user:pass@db.{DEV_PROJECT_REF}.supabase.co:6543/postgres"
        is_valid, error = validate_dsn_for_env(dsn, "prod")
        assert is_valid is False
        assert PROD_PROJECT_REF in error

    def test_valid_dev_dsn(self):
        """Valid dev DSN should pass."""
        is_valid, error = validate_dsn_for_env(VALID_DEV_DSN, "dev")
        assert is_valid is True
        assert error == ""

    def test_dev_dsn_localhost(self):
        """Dev DSN with localhost should pass."""
        is_valid, error = validate_dsn_for_env(VALID_LOCALHOST_DSN, "dev")
        assert is_valid is True

    def test_dev_dsn_prod_ref_rejected(self):
        """Dev DSN with prod project ref should fail (prevents data corruption)."""
        dsn = f"postgresql://user:pass@db.{PROD_PROJECT_REF}.supabase.co:5432/postgres"
        is_valid, error = validate_dsn_for_env(dsn, "dev")
        assert is_valid is False
        assert "PROD" in error or "production" in error.lower()

    def test_unknown_env_fails(self):
        """Unknown environment should fail."""
        is_valid, error = validate_dsn_for_env(VALID_PROD_DSN, "unknown")
        assert is_valid is False
        assert "Unknown environment" in error


# =============================================================================
# get_database_url Tests
# =============================================================================


class TestGetDatabaseUrl:
    """Tests for get_database_url function."""

    def test_canonical_var_used(self, monkeypatch):
        """DATABASE_URL should be used when set."""
        monkeypatch.setenv(CANONICAL_VAR, VALID_PROD_DSN)
        monkeypatch.delenv("SUPABASE_DB_URL", raising=False)

        result = get_database_url(require=True)
        assert result == VALID_PROD_DSN

    def test_deprecated_var_with_warning(self, monkeypatch):
        """SUPABASE_DB_URL should work but emit deprecation warning."""
        monkeypatch.delenv(CANONICAL_VAR, raising=False)
        monkeypatch.setenv("SUPABASE_DB_URL", VALID_PROD_DSN)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = get_database_url(require=True, suppress_deprecation=False)

            assert result == VALID_PROD_DSN
            # Check deprecation warning was emitted
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "DEPRECATED" in str(deprecation_warnings[0].message)

    def test_canonical_takes_priority(self, monkeypatch):
        """DATABASE_URL should take priority over SUPABASE_DB_URL."""
        canonical_dsn = "postgresql://canonical@host:5432/db"
        deprecated_dsn = "postgresql://deprecated@host:5432/db"

        monkeypatch.setenv(CANONICAL_VAR, canonical_dsn)
        monkeypatch.setenv("SUPABASE_DB_URL", deprecated_dsn)

        result = get_database_url(require=True)
        assert result == canonical_dsn

    def test_missing_raises_when_required(self, monkeypatch):
        """Missing DATABASE_URL should raise RuntimeError when require=True."""
        monkeypatch.delenv(CANONICAL_VAR, raising=False)
        monkeypatch.delenv("SUPABASE_DB_URL", raising=False)

        with pytest.raises(RuntimeError) as exc_info:
            get_database_url(require=True)

        assert CANONICAL_VAR in str(exc_info.value)

    def test_missing_returns_none_when_not_required(self, monkeypatch):
        """Missing DATABASE_URL should return None when require=False."""
        monkeypatch.delenv(CANONICAL_VAR, raising=False)
        monkeypatch.delenv("SUPABASE_DB_URL", raising=False)

        result = get_database_url(require=False)
        assert result is None

    def test_env_validation_prod(self, monkeypatch):
        """check_env='prod' should validate against prod rules."""
        monkeypatch.setenv(CANONICAL_VAR, VALID_PROD_DSN)

        # Valid prod DSN should pass
        result = get_database_url(require=True, check_env="prod")
        assert result == VALID_PROD_DSN

    def test_env_validation_prod_rejects_dev_dsn(self, monkeypatch):
        """check_env='prod' should reject dev DSN."""
        monkeypatch.setenv(CANONICAL_VAR, VALID_DEV_DSN)

        with pytest.raises(RuntimeError) as exc_info:
            get_database_url(require=True, check_env="prod")

        assert "validation failed" in str(exc_info.value).lower()

    def test_env_validation_dev(self, monkeypatch):
        """check_env='dev' should validate against dev rules."""
        monkeypatch.setenv(CANONICAL_VAR, VALID_DEV_DSN)

        result = get_database_url(require=True, check_env="dev")
        assert result == VALID_DEV_DSN

    def test_invalid_format_raises(self, monkeypatch):
        """Non-postgres DSN should raise RuntimeError."""
        monkeypatch.setenv(CANONICAL_VAR, "mysql://user:pass@host/db")

        with pytest.raises(RuntimeError) as exc_info:
            get_database_url(require=True)

        assert "postgres" in str(exc_info.value).lower()


# =============================================================================
# probe_db Tool Exit Code Tests
# =============================================================================


class TestProbeDbExitCodes:
    """Tests for probe_db.py exit codes."""

    def test_parse_dsn_components(self):
        """Verify parse_dsn_components extracts expected fields."""
        from tools.probe_db import parse_dsn_components

        components = parse_dsn_components(VALID_PROD_DSN)
        assert components["host"] == f"db.{PROD_PROJECT_REF}.supabase.co"
        assert components["port"] == PROD_REQUIRED_PORT
        assert components["user"] == "dragonfly_app"
        assert components["sslmode"] == "require"
        assert components["host_project_ref"] == PROD_PROJECT_REF

    def test_validate_pooler_identity_valid(self):
        """Valid pooler identity should pass."""
        from tools.probe_db import parse_dsn_components, validate_pooler_identity

        components = parse_dsn_components(VALID_PROD_DSN)
        is_valid, error_code, suggestion = validate_pooler_identity(components, PROD_PROJECT_REF)
        assert is_valid is True
        assert error_code == "VALID"

    def test_validate_pooler_identity_wrong_port(self):
        """Wrong port should fail identity validation."""
        from tools.probe_db import parse_dsn_components, validate_pooler_identity

        dsn = f"postgresql://user:pass@db.{PROD_PROJECT_REF}.supabase.co:5432/postgres?sslmode=require"
        components = parse_dsn_components(dsn)
        is_valid, error_code, suggestion = validate_pooler_identity(components, PROD_PROJECT_REF)
        assert is_valid is False
        assert "FORBIDDEN" in error_code

    def test_validate_pooler_identity_missing_sslmode(self):
        """Missing sslmode should fail identity validation."""
        from tools.probe_db import parse_dsn_components, validate_pooler_identity

        dsn = f"postgresql://user:pass@db.{PROD_PROJECT_REF}.supabase.co:6543/postgres"
        components = parse_dsn_components(dsn)
        is_valid, error_code, suggestion = validate_pooler_identity(components, PROD_PROJECT_REF)
        assert is_valid is False
        assert "SSLMODE" in error_code


# =============================================================================
# Constants Verification
# =============================================================================


class TestConstants:
    """Verify canonical constants are correct."""

    def test_canonical_var_name(self):
        """Canonical variable should be DATABASE_URL."""
        assert CANONICAL_VAR == "DATABASE_URL"

    def test_prod_project_ref(self):
        """Prod project ref should be correct."""
        assert PROD_PROJECT_REF == "iaketsyhmqbwaabgykux"

    def test_dev_project_ref(self):
        """Dev project ref should be correct."""
        assert DEV_PROJECT_REF == "ejiddanxtqcleyswqvkc"

    def test_prod_required_port(self):
        """Prod required port should be 6543."""
        assert PROD_REQUIRED_PORT == 6543

    def test_deprecated_vars_includes_supabase_db_url(self):
        """SUPABASE_DB_URL should be in deprecated vars."""
        assert "SUPABASE_DB_URL" in DEPRECATED_VARS


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestSingleDsnContractIntegration:
    """Integration tests for the Single DSN Contract."""

    def test_full_prod_workflow(self, monkeypatch):
        """Test complete prod workflow: set DATABASE_URL, validate, use."""
        monkeypatch.setenv(CANONICAL_VAR, VALID_PROD_DSN)
        monkeypatch.setenv("SUPABASE_MODE", "prod")

        # Get URL with validation
        db_url = get_database_url(require=True, check_env="prod")
        assert db_url == VALID_PROD_DSN

        # Extract and verify ref
        ref = extract_project_ref(db_url)
        assert ref == PROD_PROJECT_REF

        # Verify host/port
        host, port = extract_host_port(db_url)
        assert PROD_PROJECT_REF in host
        assert port == PROD_REQUIRED_PORT

    def test_full_dev_workflow(self, monkeypatch):
        """Test complete dev workflow: set DATABASE_URL, validate, use."""
        monkeypatch.setenv(CANONICAL_VAR, VALID_DEV_DSN)
        monkeypatch.setenv("SUPABASE_MODE", "dev")

        # Get URL with validation
        db_url = get_database_url(require=True, check_env="dev")
        assert db_url == VALID_DEV_DSN

        # Extract and verify ref
        ref = extract_project_ref(db_url)
        assert ref == DEV_PROJECT_REF

    def test_localhost_dev_workflow(self, monkeypatch):
        """Test localhost dev workflow (no project ref)."""
        monkeypatch.setenv(CANONICAL_VAR, VALID_LOCALHOST_DSN)
        monkeypatch.setenv("SUPABASE_MODE", "dev")

        # Get URL with validation (localhost is valid for dev)
        db_url = get_database_url(require=True, check_env="dev")
        assert db_url == VALID_LOCALHOST_DSN

        # No project ref for localhost
        ref = extract_project_ref(db_url)
        assert ref is None

        # Host should be localhost
        host, port = extract_host_port(db_url)
        assert host == "localhost"
