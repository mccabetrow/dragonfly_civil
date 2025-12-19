# tests/test_dsn_sanitizer.py
"""
Unit tests for DSN sanitizer/validator.

Tests cover:
- Trailing newline rejection
- Surrounding quotes rejection
- Accidental suffix rejection (e.g., " v1.3.1'")
- Internal whitespace rejection
- Valid DSN passthrough
- Safe component extraction (no password)
"""

import pytest

from backend.dsn_sanitizer import (
    DSNSanitizationError,
    SanitizedDSN,
    _check_for_internal_whitespace,
    _check_for_quotes,
    _extract_safe_components,
    sanitize_dsn,
)

# =============================================================================
# Valid DSN Tests
# =============================================================================


class TestValidDSN:
    """Tests for valid DSN handling."""

    def test_valid_dsn_passes(self):
        """A well-formed DSN should pass sanitization."""
        dsn = "postgresql://user:password@host.example.com:5432/mydb?sslmode=require"
        result = sanitize_dsn(dsn)

        assert isinstance(result, SanitizedDSN)
        assert result.dsn == dsn
        assert not result.stripped_leading
        assert not result.stripped_trailing
        assert result.components["host"] == "host.example.com"
        assert result.components["port"] == "5432"
        assert result.components["user"] == "user"
        assert result.components["dbname"] == "mydb"
        assert result.components["sslmode"] == "require"

    def test_valid_dsn_no_sslmode(self):
        """DSN without sslmode should still pass sanitization."""
        dsn = "postgresql://user:pass@host:5432/db"
        result = sanitize_dsn(dsn)

        assert result.dsn == dsn
        assert result.components["sslmode"] == "not_set"

    def test_supabase_style_dsn(self):
        """Supabase-style DSN should pass."""
        dsn = "postgresql://dragonfly_app:SecretPass123@db.iaketsyhmqbwaabgykux.supabase.co:5432/postgres?sslmode=require"
        result = sanitize_dsn(dsn)

        assert result.dsn == dsn
        assert result.components["host"] == "db.iaketsyhmqbwaabgykux.supabase.co"
        assert result.components["user"] == "dragonfly_app"
        assert result.components["dbname"] == "postgres"


# =============================================================================
# Trailing Newline Tests
# =============================================================================


class TestTrailingNewline:
    """Tests for trailing newline handling (edge whitespace is stripped)."""

    def test_trailing_newline_stripped(self):
        """DSN with trailing newline should be stripped (not rejected)."""
        dsn = "postgresql://user:pass@host:5432/db\n"
        result = sanitize_dsn(dsn)

        # Edge whitespace (including newlines) is stripped
        assert result.dsn == "postgresql://user:pass@host:5432/db"
        assert result.stripped_trailing is True

    def test_trailing_crlf_stripped(self):
        """DSN with trailing CRLF should be stripped (not rejected)."""
        dsn = "postgresql://user:pass@host:5432/db\r\n"
        result = sanitize_dsn(dsn)

        # Edge whitespace is stripped first
        assert result.dsn == "postgresql://user:pass@host:5432/db"
        assert result.stripped_trailing is True

    def test_internal_newline_rejected(self):
        """DSN with newline in the middle should be rejected."""
        dsn = "postgresql://user:pass@host:5432/db\nsslmode=require"

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "newline" in exc_info.value.message.lower()

    def test_internal_carriage_return_rejected(self):
        """DSN with carriage return in the middle should be rejected."""
        dsn = "postgresql://user:pass@host:5432/db\rsslmode=require"

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "carriage return" in exc_info.value.message.lower()


# =============================================================================
# Surrounding Quotes Tests
# =============================================================================


class TestSurroundingQuotes:
    """Tests for surrounding quotes rejection."""

    def test_double_quoted_dsn_rejected(self):
        """DSN wrapped in double quotes should be rejected."""
        dsn = '"postgresql://user:pass@host:5432/db"'

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "quote" in exc_info.value.message.lower()

    def test_single_quoted_dsn_rejected(self):
        """DSN wrapped in single quotes should be rejected."""
        dsn = "'postgresql://user:pass@host:5432/db'"

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "quote" in exc_info.value.message.lower()

    def test_leading_quote_only_rejected(self):
        """DSN with only leading quote should be rejected."""
        dsn = '"postgresql://user:pass@host:5432/db'

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "quote" in exc_info.value.message.lower()

    def test_trailing_quote_only_rejected(self):
        """DSN with only trailing quote should be rejected."""
        dsn = "postgresql://user:pass@host:5432/db'"

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "quote" in exc_info.value.message.lower()


# =============================================================================
# Accidental Suffix Tests
# =============================================================================


class TestAccidentalSuffix:
    """Tests for accidental suffix rejection (e.g., version strings)."""

    def test_version_suffix_rejected(self):
        """DSN with accidental version suffix should be rejected."""
        dsn = "postgresql://user:pass@host:5432/db v1.3.1'"

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        # Should fail - either due to trailing quote or internal space
        msg = exc_info.value.message.lower()
        assert "space" in msg or "quote" in msg

    def test_comment_suffix_rejected(self):
        """DSN with accidental comment suffix should be rejected."""
        dsn = "postgresql://user:pass@host:5432/db # production"

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "space" in exc_info.value.message.lower()

    def test_tab_suffix_rejected(self):
        """DSN with accidental tab suffix (embedded) should be rejected."""
        dsn = "postgresql://user:pass@host:5432/db\textra"

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "tab" in exc_info.value.message.lower()


# =============================================================================
# Whitespace Stripping Tests
# =============================================================================


class TestWhitespaceStripping:
    """Tests for edge whitespace stripping behavior."""

    def test_leading_whitespace_stripped(self):
        """Leading whitespace should be stripped (with warning logged)."""
        dsn = "  postgresql://user:pass@host:5432/db"
        result = sanitize_dsn(dsn)

        assert result.dsn == "postgresql://user:pass@host:5432/db"
        assert result.stripped_leading is True
        assert result.stripped_trailing is False

    def test_trailing_whitespace_stripped(self):
        """Trailing whitespace should be stripped (with warning logged)."""
        dsn = "postgresql://user:pass@host:5432/db  "
        result = sanitize_dsn(dsn)

        assert result.dsn == "postgresql://user:pass@host:5432/db"
        assert result.stripped_leading is False
        assert result.stripped_trailing is True

    def test_both_ends_stripped(self):
        """Whitespace on both ends should be stripped."""
        dsn = "  postgresql://user:pass@host:5432/db  "
        result = sanitize_dsn(dsn)

        assert result.dsn == "postgresql://user:pass@host:5432/db"
        assert result.stripped_leading is True
        assert result.stripped_trailing is True

    def test_trailing_newline_stripped_then_valid(self):
        """Trailing newline is stripped, and if DSN is otherwise valid, it passes."""
        dsn = "postgresql://user:pass@host:5432/db\n"
        result = sanitize_dsn(dsn)

        # Edge newlines get stripped first
        assert result.dsn == "postgresql://user:pass@host:5432/db"
        assert result.stripped_trailing is True


# =============================================================================
# Safe Component Extraction Tests
# =============================================================================


class TestSafeComponents:
    """Tests for safe component extraction (no password exposure)."""

    def test_password_never_in_components(self):
        """Password should never appear in extracted components."""
        dsn = "postgresql://user:SuperSecretPassword123@host:5432/db"
        result = sanitize_dsn(dsn)

        # Check that password is not in any component value
        for key, value in result.components.items():
            if value:
                assert "SuperSecretPassword123" not in str(value), f"Password leaked in {key}"

    def test_all_safe_components_extracted(self):
        """All safe components should be correctly extracted."""
        dsn = "postgresql://myuser:pass@myhost.com:6543/mydb?sslmode=verify-full"
        result = sanitize_dsn(dsn)

        assert result.components["host"] == "myhost.com"
        assert result.components["port"] == "6543"
        assert result.components["user"] == "myuser"
        assert result.components["dbname"] == "mydb"
        assert result.components["sslmode"] == "verify-full"


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_none_dsn_raises(self):
        """None DSN should raise DSNSanitizationError."""
        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(None)

        assert "None" in exc_info.value.message or "not set" in exc_info.value.message

    def test_empty_dsn_after_strip(self):
        """DSN that becomes empty after stripping should be handled."""
        dsn = "   \n\t   "
        # After stripping, this becomes empty string
        result = sanitize_dsn(dsn, raise_on_error=False)
        # Should have empty/minimal components
        assert result.dsn == ""

    def test_no_raise_mode(self):
        """raise_on_error=False should not raise on invalid DSN."""
        dsn = '"postgresql://user:pass@host:5432/db"'
        result = sanitize_dsn(dsn, raise_on_error=False)

        # Should return a result even though invalid
        assert isinstance(result, SanitizedDSN)

    def test_unicode_in_dsn_preserved(self):
        """Unicode characters in DSN should be preserved."""
        dsn = "postgresql://user:päss@host:5432/db"
        result = sanitize_dsn(dsn)

        assert "päss" not in result.components.values()  # Password not exposed
        assert result.dsn == dsn


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_check_for_quotes_double(self):
        """_check_for_quotes should detect double quotes."""
        error = _check_for_quotes('"some value"')
        assert error is not None
        assert "quote" in error.lower()

    def test_check_for_quotes_single(self):
        """_check_for_quotes should detect single quotes."""
        error = _check_for_quotes("'some value'")
        assert error is not None
        assert "quote" in error.lower()

    def test_check_for_quotes_none_when_valid(self):
        """_check_for_quotes should return None for valid values."""
        error = _check_for_quotes("postgresql://user:pass@host:5432/db")
        assert error is None

    def test_check_internal_whitespace_space(self):
        """_check_for_internal_whitespace should detect spaces."""
        error = _check_for_internal_whitespace("value with space")
        assert error is not None
        assert "space" in error.lower()

    def test_check_internal_whitespace_newline(self):
        """_check_for_internal_whitespace should detect newlines."""
        error = _check_for_internal_whitespace("value\nwith\nnewline")
        assert error is not None
        assert "newline" in error.lower()

    def test_check_internal_whitespace_none_when_valid(self):
        """_check_for_internal_whitespace should return None for valid values."""
        error = _check_for_internal_whitespace("postgresql://user:pass@host:5432/db")
        assert error is None

    def test_extract_safe_components(self):
        """_extract_safe_components should extract correct fields."""
        components = _extract_safe_components(
            "postgresql://testuser:testpass@testhost.com:1234/testdb?sslmode=require"
        )

        assert components["host"] == "testhost.com"
        assert components["port"] == "1234"
        assert components["user"] == "testuser"
        assert components["dbname"] == "testdb"
        assert components["sslmode"] == "require"
        # Password should not be in components
        assert "testpass" not in str(components)


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestRealWorldScenarios:
    """Tests simulating real-world misconfiguration scenarios."""

    def test_railway_copy_paste_with_newline(self):
        """Simulate Railway env var with trailing newline from copy-paste."""
        dsn = "postgresql://dragonfly_app:secret@db.supabase.co:5432/postgres?sslmode=require\n"
        result = sanitize_dsn(dsn)

        # Should strip the newline and pass
        assert result.stripped_trailing is True
        assert "\n" not in result.dsn

    def test_yaml_quoted_value(self):
        """Simulate YAML config with accidentally quoted value."""
        dsn = '"postgresql://user:pass@host:5432/db?sslmode=require"'

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "quote" in exc_info.value.message.lower()

    def test_env_file_with_version_comment(self):
        """Simulate .env file with accidental version annotation."""
        dsn = "postgresql://user:pass@host:5432/db v1.3.1"

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "space" in exc_info.value.message.lower()

    def test_multiline_env_var(self):
        """Simulate multi-line environment variable (misconfigured)."""
        dsn = """postgresql://user:pass@host:5432/db
ANOTHER_VAR=value"""

        with pytest.raises(DSNSanitizationError) as exc_info:
            sanitize_dsn(dsn)

        assert "newline" in exc_info.value.message.lower()
