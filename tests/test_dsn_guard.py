"""
Tests for DSN Guard - Zero Drift Policy Enforcement

These tests verify the DSN Guard correctly:
1. Accepts valid prod DSNs (iaketsyhmqbwaabgykux:6543)
2. Rejects prod DSNs with wrong project ref
3. Rejects prod DSNs with wrong port (5432)
4. Accepts valid dev DSNs (ejiddanxtqcleyswqvkc or localhost)
5. Rejects dev environment using prod project ref (prevents data corruption)

Author: Principal SRE
Date: 2026-01-15
"""

import pytest

from backend.core.dsn_guard import (
    DEV_PROJECT_REF,
    PROD_PROJECT_REF,
    PROD_REQUIRED_PORT,
    DSNEnvironmentMismatchError,
    validate_dsn_for_environment,
)

# =============================================================================
# Test DSNs
# =============================================================================

# Valid production DSN (Transaction Pooler)
VALID_PROD_DSN = (
    f"postgresql://dragonfly_app:password@db.{PROD_PROJECT_REF}.supabase.co"
    f":{PROD_REQUIRED_PORT}/postgres?sslmode=require"
)

# Invalid prod DSN - wrong port (direct connection)
INVALID_PROD_DSN_WRONG_PORT = (
    f"postgresql://dragonfly_app:password@db.{PROD_PROJECT_REF}.supabase.co"
    f":5432/postgres?sslmode=require"
)

# Invalid prod DSN - dev project ref
INVALID_PROD_DSN_DEV_REF = (
    f"postgresql://dragonfly_app:password@db.{DEV_PROJECT_REF}.supabase.co"
    f":{PROD_REQUIRED_PORT}/postgres?sslmode=require"
)

# Valid dev DSN (project ref)
VALID_DEV_DSN = (
    f"postgresql://dragonfly_app:password@db.{DEV_PROJECT_REF}.supabase.co"
    f":5432/postgres?sslmode=require"
)

# Valid dev DSN (localhost)
VALID_DEV_DSN_LOCALHOST = "postgresql://postgres:password@localhost:5432/postgres"

# Invalid dev DSN - using prod project ref (dangerous!)
INVALID_DEV_DSN_PROD_REF = (
    f"postgresql://dragonfly_app:password@db.{PROD_PROJECT_REF}.supabase.co"
    f":5432/postgres?sslmode=require"
)


# =============================================================================
# PROD Environment Tests
# =============================================================================


class TestProdEnvironment:
    """Tests for production environment DSN validation."""

    def test_valid_prod_dsn_accepted(self):
        """Valid prod DSN with correct project ref and port should pass."""
        result = validate_dsn_for_environment(VALID_PROD_DSN, "prod", fatal_on_mismatch=False)
        assert result is True

    def test_prod_dsn_wrong_port_rejected(self):
        """Prod DSN with port 5432 (direct) should be rejected."""
        with pytest.raises(DSNEnvironmentMismatchError) as exc_info:
            validate_dsn_for_environment(
                INVALID_PROD_DSN_WRONG_PORT, "prod", fatal_on_mismatch=True
            )

        assert "6543" in str(exc_info.value)
        assert exc_info.value.dsn_port == 5432

    def test_prod_dsn_dev_ref_rejected(self):
        """Prod DSN with dev project ref should be rejected."""
        with pytest.raises(DSNEnvironmentMismatchError) as exc_info:
            validate_dsn_for_environment(INVALID_PROD_DSN_DEV_REF, "prod", fatal_on_mismatch=True)

        assert PROD_PROJECT_REF in str(exc_info.value)
        assert exc_info.value.environment == "prod"

    def test_prod_dsn_localhost_rejected(self):
        """Prod DSN pointing to localhost should be rejected."""
        with pytest.raises(DSNEnvironmentMismatchError):
            validate_dsn_for_environment(VALID_DEV_DSN_LOCALHOST, "prod", fatal_on_mismatch=True)


# =============================================================================
# DEV Environment Tests
# =============================================================================


class TestDevEnvironment:
    """Tests for development environment DSN validation."""

    def test_valid_dev_dsn_accepted(self):
        """Valid dev DSN with dev project ref should pass."""
        result = validate_dsn_for_environment(VALID_DEV_DSN, "dev", fatal_on_mismatch=False)
        assert result is True

    def test_dev_dsn_localhost_accepted(self):
        """Dev DSN pointing to localhost should pass."""
        result = validate_dsn_for_environment(
            VALID_DEV_DSN_LOCALHOST, "dev", fatal_on_mismatch=False
        )
        assert result is True

    def test_dev_dsn_prod_ref_rejected(self):
        """Dev DSN with prod project ref should be REJECTED (prevents data corruption)."""
        with pytest.raises(DSNEnvironmentMismatchError) as exc_info:
            validate_dsn_for_environment(INVALID_DEV_DSN_PROD_REF, "dev", fatal_on_mismatch=True)

        # Should mention using prod in dev
        error_msg = str(exc_info.value)
        assert "PROD" in error_msg or "prod" in error_msg.lower()
        assert exc_info.value.environment == "dev"

    def test_dev_dsn_pooler_port_accepted(self):
        """Dev DSN with pooler port (6543) should also be accepted."""
        dev_dsn_pooler = (
            f"postgresql://dragonfly_app:password@db.{DEV_PROJECT_REF}.supabase.co"
            f":6543/postgres?sslmode=require"
        )
        result = validate_dsn_for_environment(dev_dsn_pooler, "dev", fatal_on_mismatch=False)
        assert result is True


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_invalid_dsn_rejected(self):
        """Malformed DSN should be rejected."""
        with pytest.raises(DSNEnvironmentMismatchError):
            validate_dsn_for_environment("not-a-valid-dsn", "prod", fatal_on_mismatch=True)

    def test_empty_dsn_rejected(self):
        """Empty DSN should be rejected."""
        with pytest.raises(DSNEnvironmentMismatchError):
            validate_dsn_for_environment("", "prod", fatal_on_mismatch=True)

    def test_unknown_environment_rejected(self):
        """Unknown environment should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_dsn_for_environment(VALID_PROD_DSN, "unknown_env", fatal_on_mismatch=True)

        assert "unknown" in str(exc_info.value).lower()

    def test_staging_maps_to_dev(self):
        """Staging environment should follow dev rules."""
        result = validate_dsn_for_environment(VALID_DEV_DSN, "staging", fatal_on_mismatch=False)
        assert result is True

    def test_fatal_on_mismatch_false_returns_bool(self):
        """When fatal_on_mismatch=False, should return False instead of raising."""
        result = validate_dsn_for_environment(
            INVALID_PROD_DSN_WRONG_PORT, "prod", fatal_on_mismatch=False
        )
        assert result is False


# =============================================================================
# Exception Content Tests
# =============================================================================


class TestExceptionContent:
    """Tests for exception content and metadata."""

    def test_exception_contains_environment(self):
        """Exception should contain the environment."""
        with pytest.raises(DSNEnvironmentMismatchError) as exc_info:
            validate_dsn_for_environment(
                INVALID_PROD_DSN_WRONG_PORT, "prod", fatal_on_mismatch=True
            )

        assert exc_info.value.environment == "prod"

    def test_exception_contains_host(self):
        """Exception should contain the DSN host."""
        with pytest.raises(DSNEnvironmentMismatchError) as exc_info:
            validate_dsn_for_environment(
                INVALID_PROD_DSN_WRONG_PORT, "prod", fatal_on_mismatch=True
            )

        assert PROD_PROJECT_REF in exc_info.value.dsn_host

    def test_exception_contains_port(self):
        """Exception should contain the DSN port."""
        with pytest.raises(DSNEnvironmentMismatchError) as exc_info:
            validate_dsn_for_environment(
                INVALID_PROD_DSN_WRONG_PORT, "prod", fatal_on_mismatch=True
            )

        assert exc_info.value.dsn_port == 5432
