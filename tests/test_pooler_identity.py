"""
tests/test_pooler_identity.py
==============================
Unit tests for Supabase Pooler Identity Contract.

Tests validate:
1. Shared pooler: postgres.<ref>@aws-*...pooler... is valid
2. Shared pooler: postgres@aws-*...pooler... is invalid
3. Dedicated pooler: postgres@db.<ref>.supabase.co:6543 is valid
4. Direct connection: postgres@db.<ref>.supabase.co:5432 is FORBIDDEN
5. Mismatched refs are invalid

Author: Principal Engineer
Date: 2026-01-14
"""

from __future__ import annotations

import pytest

from tools.probe_db import (
    EXPECTED_PROJECT_REF,
    IdentityError,
    PoolerMode,
    get_effective_project_ref,
    parse_dsn_components,
    validate_pooler_identity,
)

# =============================================================================
# Constants for testing
# =============================================================================

TEST_REF = "iaketsyhmqbwaabgykux"  # Production ref
WRONG_REF = "wrongprojectref1234"
SHARED_HOST = "aws-0-us-east-1.pooler.supabase.com"
DEDICATED_HOST = f"db.{TEST_REF}.supabase.co"


# =============================================================================
# Helper functions
# =============================================================================


def build_dsn(
    user: str,
    password: str,
    host: str,
    port: int = 6543,
    database: str = "postgres",
    sslmode: str = "require",
) -> str:
    """Build a DSN from components."""
    return f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}"


# =============================================================================
# Tests for parse_dsn_components
# =============================================================================


class TestParseDsnComponents:
    """Tests for DSN component parsing."""

    def test_parse_shared_pooler_with_ref(self) -> None:
        """Shared pooler DSN with user.ref should parse correctly."""
        dsn = build_dsn(
            user=f"postgres.{TEST_REF}",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)

        assert components["pooler_mode"] == PoolerMode.SHARED
        assert components["user_base"] == "postgres"
        assert components["user_project_ref"] == TEST_REF
        assert components["host_project_ref"] is None
        assert components["pooler_region"] == "aws-0-us-east-1"

    def test_parse_shared_pooler_without_ref(self) -> None:
        """Shared pooler DSN without user.ref should still parse."""
        dsn = build_dsn(
            user="postgres",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)

        assert components["pooler_mode"] == PoolerMode.SHARED
        assert components["user_base"] == "postgres"
        assert components["user_project_ref"] is None

    def test_parse_dedicated_pooler(self) -> None:
        """Dedicated pooler DSN should extract ref from host."""
        dsn = build_dsn(
            user="postgres",
            password="secret",
            host=DEDICATED_HOST,
            port=6543,
        )
        components = parse_dsn_components(dsn)

        assert components["pooler_mode"] == PoolerMode.DEDICATED
        assert components["host_project_ref"] == TEST_REF
        assert components["user_base"] == "postgres"
        assert components["user_project_ref"] is None

    def test_parse_direct_connection(self) -> None:
        """Direct connection (port 5432) should be detected."""
        dsn = build_dsn(
            user="postgres",
            password="secret",
            host=DEDICATED_HOST,
            port=5432,
        )
        components = parse_dsn_components(dsn)

        assert components["pooler_mode"] == PoolerMode.DIRECT
        assert components["host_project_ref"] == TEST_REF
        assert components["port"] == 5432

    def test_parse_custom_user_with_ref(self) -> None:
        """Custom user with ref suffix should parse correctly."""
        dsn = build_dsn(
            user=f"dragonfly_app.{TEST_REF}",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)

        assert components["user_base"] == "dragonfly_app"
        assert components["user_project_ref"] == TEST_REF


# =============================================================================
# Tests for shared pooler validation
# =============================================================================


class TestSharedPoolerValidation:
    """Tests for shared pooler identity validation."""

    def test_shared_pooler_with_correct_ref_is_valid(self) -> None:
        """Shared pooler: postgres.<ref>@aws-*...pooler... is valid."""
        dsn = build_dsn(
            user=f"postgres.{TEST_REF}",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)
        is_valid, error, _ = validate_pooler_identity(components, TEST_REF)

        assert is_valid is True
        assert error == IdentityError.VALID

    def test_shared_pooler_without_ref_is_invalid(self) -> None:
        """Shared pooler: postgres@aws-*...pooler... is invalid."""
        dsn = build_dsn(
            user="postgres",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)
        is_valid, error, suggestion = validate_pooler_identity(components, TEST_REF)

        assert is_valid is False
        assert error == IdentityError.SHARED_POOLER_USER_MISSING_REF
        assert "postgres." in suggestion

    def test_shared_pooler_with_wrong_ref_is_invalid(self) -> None:
        """Shared pooler with wrong project ref is invalid."""
        dsn = build_dsn(
            user=f"postgres.{WRONG_REF}",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)
        is_valid, error, suggestion = validate_pooler_identity(components, TEST_REF)

        assert is_valid is False
        assert error == IdentityError.PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER
        assert TEST_REF in suggestion

    def test_shared_pooler_custom_user_with_ref_is_valid(self) -> None:
        """Shared pooler with custom user and correct ref is valid."""
        dsn = build_dsn(
            user=f"dragonfly_app.{TEST_REF}",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)
        is_valid, error, _ = validate_pooler_identity(components, TEST_REF)

        assert is_valid is True
        assert error == IdentityError.VALID


# =============================================================================
# Tests for dedicated pooler validation
# =============================================================================


class TestDedicatedPoolerValidation:
    """Tests for dedicated pooler identity validation."""

    def test_dedicated_pooler_with_correct_ref_is_valid(self) -> None:
        """Dedicated pooler: postgres@db.<ref>.supabase.co:6543 is valid."""
        dsn = build_dsn(
            user="postgres",
            password="secret",
            host=DEDICATED_HOST,
            port=6543,
        )
        components = parse_dsn_components(dsn)
        is_valid, error, _ = validate_pooler_identity(components, TEST_REF)

        assert is_valid is True
        assert error == IdentityError.VALID

    def test_dedicated_pooler_with_wrong_ref_is_invalid(self) -> None:
        """Dedicated pooler with wrong host ref is invalid."""
        wrong_host = f"db.{WRONG_REF}.supabase.co"
        dsn = build_dsn(
            user="postgres",
            password="secret",
            host=wrong_host,
            port=6543,
        )
        components = parse_dsn_components(dsn)
        is_valid, error, suggestion = validate_pooler_identity(components, TEST_REF)

        assert is_valid is False
        assert error == IdentityError.DEDICATED_POOLER_HOST_REF_MISMATCH
        assert TEST_REF in suggestion

    def test_dedicated_pooler_custom_user_is_valid(self) -> None:
        """Dedicated pooler with custom user (no ref suffix) is valid."""
        dsn = build_dsn(
            user="dragonfly_app",
            password="secret",
            host=DEDICATED_HOST,
            port=6543,
        )
        components = parse_dsn_components(dsn)
        is_valid, error, _ = validate_pooler_identity(components, TEST_REF)

        assert is_valid is True
        assert error == IdentityError.VALID


# =============================================================================
# Tests for direct connection (FORBIDDEN)
# =============================================================================


class TestDirectConnectionForbidden:
    """Tests for direct connection (port 5432) validation."""

    def test_direct_connection_is_forbidden(self) -> None:
        """Direct connection (port 5432) should be forbidden."""
        dsn = build_dsn(
            user="postgres",
            password="secret",
            host=DEDICATED_HOST,
            port=5432,
        )
        components = parse_dsn_components(dsn)
        is_valid, error, suggestion = validate_pooler_identity(components, TEST_REF)

        assert is_valid is False
        assert error == IdentityError.DIRECT_CONNECTION_FORBIDDEN
        assert "6543" in suggestion or "shared pooler" in suggestion.lower()


# =============================================================================
# Tests for sslmode validation
# =============================================================================


class TestSslmodeValidation:
    """Tests for sslmode requirement."""

    def test_missing_sslmode_is_invalid(self) -> None:
        """DSN without sslmode=require is invalid."""
        dsn = f"postgresql://postgres.{TEST_REF}:secret@{SHARED_HOST}:6543/postgres"
        components = parse_dsn_components(dsn)
        is_valid, error, suggestion = validate_pooler_identity(components, TEST_REF)

        assert is_valid is False
        assert error == IdentityError.MISSING_SSLMODE
        assert "sslmode" in suggestion

    def test_wrong_sslmode_is_invalid(self) -> None:
        """DSN with wrong sslmode is invalid."""
        dsn = f"postgresql://postgres.{TEST_REF}:secret@{SHARED_HOST}:6543/postgres?sslmode=prefer"
        components = parse_dsn_components(dsn)
        is_valid, error, suggestion = validate_pooler_identity(components, TEST_REF)

        assert is_valid is False
        assert error == IdentityError.MISSING_SSLMODE


# =============================================================================
# Tests for effective project ref extraction
# =============================================================================


class TestEffectiveProjectRef:
    """Tests for effective project ref extraction."""

    def test_shared_pooler_ref_from_user(self) -> None:
        """Shared pooler should get ref from user."""
        dsn = build_dsn(
            user=f"postgres.{TEST_REF}",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)
        effective_ref = get_effective_project_ref(components)

        assert effective_ref == TEST_REF

    def test_dedicated_pooler_ref_from_host(self) -> None:
        """Dedicated pooler should get ref from host."""
        dsn = build_dsn(
            user="postgres",
            password="secret",
            host=DEDICATED_HOST,
        )
        components = parse_dsn_components(dsn)
        effective_ref = get_effective_project_ref(components)

        assert effective_ref == TEST_REF


# =============================================================================
# Tests for complex scenarios
# =============================================================================


class TestComplexScenarios:
    """Tests for complex/edge case scenarios."""

    def test_user_with_dots_in_name(self) -> None:
        """User with multiple dots should use first part as base."""
        # This is an unusual case but should be handled
        dsn = build_dsn(
            user=f"my.user.{TEST_REF}",
            password="secret",
            host=SHARED_HOST,
        )
        components = parse_dsn_components(dsn)

        # First part before first dot is base, rest is ref
        assert components["user_base"] == "my"
        assert components["user_project_ref"] == f"user.{TEST_REF}"

    def test_url_encoded_password(self) -> None:
        """URL-encoded password should parse correctly."""
        dsn = f"postgresql://postgres.{TEST_REF}:pass%21word@{SHARED_HOST}:6543/postgres?sslmode=require"
        components = parse_dsn_components(dsn)

        assert components["pooler_mode"] == PoolerMode.SHARED
        # Note: urlparse doesn't decode %XX in password - that's expected
        # The password is stored as-is (URL-encoded form)
        assert components["password"] == "pass%21word"

    def test_various_shared_pooler_regions(self) -> None:
        """Various AWS region patterns should be recognized."""
        regions = [
            "aws-0-us-east-1",
            "aws-0-eu-west-1",
            "aws-0-ap-southeast-1",
            "aws-1-us-west-2",
        ]

        for region in regions:
            host = f"{region}.pooler.supabase.com"
            dsn = build_dsn(
                user=f"postgres.{TEST_REF}",
                password="secret",
                host=host,
            )
            components = parse_dsn_components(dsn)

            assert components["pooler_mode"] == PoolerMode.SHARED, f"Failed for region {region}"
            assert components["pooler_region"] == region


# =============================================================================
# Integration tests (validate full flow)
# =============================================================================


class TestFullValidationFlow:
    """Integration tests for full validation flow."""

    def test_production_shared_pooler_dsn(self) -> None:
        """Production-like shared pooler DSN should be valid."""
        dsn = (
            f"postgresql://dragonfly_app.{TEST_REF}:P%40ssword%21"
            f"@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        )
        components = parse_dsn_components(dsn)
        is_valid, error, _ = validate_pooler_identity(components, TEST_REF)

        assert is_valid is True
        assert error == IdentityError.VALID

    def test_production_dedicated_pooler_dsn(self) -> None:
        """Production-like dedicated pooler DSN should be valid."""
        dsn = (
            f"postgresql://dragonfly_app:P%40ssword%21"
            f"@db.{TEST_REF}.supabase.co:6543/postgres?sslmode=require"
        )
        components = parse_dsn_components(dsn)
        is_valid, error, _ = validate_pooler_identity(components, TEST_REF)

        assert is_valid is True
        assert error == IdentityError.VALID

    def test_common_mistake_plain_user_on_shared_pooler(self) -> None:
        """Common mistake: plain user on shared pooler should fail clearly."""
        dsn = (
            "postgresql://postgres:password"
            "@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        )
        components = parse_dsn_components(dsn)
        is_valid, error, suggestion = validate_pooler_identity(components, TEST_REF)

        assert is_valid is False
        assert error == IdentityError.SHARED_POOLER_USER_MISSING_REF
        # Suggestion should tell them to add the ref
        assert TEST_REF in suggestion or "project_ref" in suggestion.lower()

    def test_common_mistake_direct_connection(self) -> None:
        """Common mistake: direct connection should fail clearly."""
        dsn = (
            f"postgresql://postgres:password"
            f"@db.{TEST_REF}.supabase.co:5432/postgres?sslmode=require"
        )
        components = parse_dsn_components(dsn)
        is_valid, error, suggestion = validate_pooler_identity(components, TEST_REF)

        assert is_valid is False
        assert error == IdentityError.DIRECT_CONNECTION_FORBIDDEN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
