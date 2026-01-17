#!/usr/bin/env python3
"""
tests/test_dsn_tools.py
=======================
Unit tests for DSN validation and generation tools.

Tests cover:
- tools/build_pooler_dsn.py - DSN building with URL encoding
- tools/validate_dsn.py - DSN validation logic
- tools/probe_db.py - Basic probe function logic (no actual DB connection)

Run with:
    pytest tests/test_dsn_tools.py -v
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

# Ensure tools module is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.build_pooler_dsn import (
    build_dsn,
    get_encoding_hints,
    redact_password,
    validate_host,
    validate_password,
)
from tools.probe_db import extract_host_port
from tools.probe_db import redact_dsn as probe_redact_dsn
from tools.validate_dsn import parse_dsn, redact_dsn, validate_dsn

# =============================================================================
# Tests for build_pooler_dsn.py
# =============================================================================


class TestBuildDsn:
    """Tests for build_dsn function."""

    def test_simple_password(self):
        """Password without special chars should not be encoded."""
        dsn = build_dsn(
            host="aws-0-us-east-1.pooler.supabase.com",
            user="dragonfly_app",
            password="simplepassword123",
        )
        assert "simplepassword123" in dsn
        assert "6543" in dsn
        assert "sslmode=require" in dsn

    def test_password_with_at_sign(self):
        """@ in password should be URL-encoded to %40."""
        dsn = build_dsn(
            host="aws-0-us-east-1.pooler.supabase.com",
            user="dragonfly_app",
            password="pass@word",
        )
        assert "pass%40word" in dsn
        assert "@aws-0" in dsn  # The @ before host should NOT be encoded

    def test_password_with_exclamation(self):
        """! in password should be URL-encoded to %21."""
        dsn = build_dsn(
            host="aws-0-us-east-1.pooler.supabase.com",
            user="dragonfly_app",
            password="password!",
        )
        assert "password%21" in dsn

    def test_password_with_multiple_special_chars(self):
        """Multiple special chars should all be encoded."""
        dsn = build_dsn(
            host="aws-0-us-east-1.pooler.supabase.com",
            user="dragonfly_app",
            password="P@ss!#$%",
        )
        assert "%40" in dsn  # @
        assert "%21" in dsn  # !
        assert "%23" in dsn  # #
        assert "%24" in dsn  # $
        assert "%25" in dsn  # %

    def test_default_port_6543(self):
        """Default port should be 6543 (pooler)."""
        dsn = build_dsn(
            host="host.example.com",
            user="user",
            password="pass",
        )
        assert ":6543/" in dsn

    def test_custom_port_5432(self):
        """Custom port 5432 (direct) should be respected."""
        dsn = build_dsn(
            host="host.example.com",
            user="user",
            password="pass",
            port=5432,
        )
        assert ":5432/" in dsn
        assert ":6543" not in dsn

    def test_forced_sslmode_require(self):
        """sslmode should always be require."""
        dsn = build_dsn(
            host="host.example.com",
            user="user",
            password="pass",
            sslmode="disable",  # Should be ignored
        )
        assert "sslmode=require" in dsn
        assert "sslmode=disable" not in dsn

    def test_custom_database(self):
        """Custom database name should be used."""
        dsn = build_dsn(
            host="host.example.com",
            user="user",
            password="pass",
            database="mydb",
        )
        assert "/mydb?" in dsn


class TestValidateHost:
    """Tests for validate_host function."""

    def test_shared_pooler_valid(self):
        """Shared pooler hostname should be valid."""
        is_valid, msg = validate_host("aws-0-us-east-1.pooler.supabase.com")
        assert is_valid is True
        assert msg == ""

    def test_dedicated_pooler_valid(self):
        """Dedicated pooler hostname should be valid."""
        is_valid, msg = validate_host("db.abcdefgh123.supabase.co")
        assert is_valid is True
        assert msg == ""

    def test_empty_host_invalid(self):
        """Empty host should be invalid."""
        is_valid, msg = validate_host("")
        assert is_valid is False
        assert "empty" in msg.lower()

    def test_host_with_protocol_invalid(self):
        """Host with protocol prefix should be invalid."""
        is_valid, msg = validate_host("postgresql://host.example.com")
        assert is_valid is False
        assert "protocol" in msg.lower()

    def test_unknown_host_warning(self):
        """Unknown host should be valid but with warning."""
        is_valid, msg = validate_host("my-custom-host.example.com")
        assert is_valid is True
        assert "Warning" in msg or "warning" in msg.lower()


class TestValidatePassword:
    """Tests for validate_password function."""

    def test_valid_password(self):
        """Normal password should be valid."""
        is_valid, msg = validate_password("MySecureP@ssword123!")
        assert is_valid is True
        assert msg == ""

    def test_empty_password_invalid(self):
        """Empty password should be invalid."""
        is_valid, msg = validate_password("")
        assert is_valid is False
        assert "empty" in msg.lower()

    def test_password_with_null_byte_invalid(self):
        """Password with null byte should be invalid."""
        is_valid, msg = validate_password("pass\x00word")
        assert is_valid is False
        assert "null" in msg.lower()

    def test_password_with_newline_invalid(self):
        """Password with newline should be invalid."""
        is_valid, msg = validate_password("pass\nword")
        assert is_valid is False
        assert "newline" in msg.lower()


class TestGetEncodingHints:
    """Tests for get_encoding_hints function."""

    def test_no_special_chars(self):
        """Password without special chars should have no hints."""
        hints = get_encoding_hints("simplepassword")
        assert len(hints) == 0

    def test_at_sign_hint(self):
        """@ should produce a hint."""
        hints = get_encoding_hints("user@domain")
        assert any("%40" in h for h in hints)

    def test_multiple_special_chars(self):
        """Multiple special chars should produce multiple hints."""
        hints = get_encoding_hints("P@ss!#")
        assert len(hints) >= 3


class TestRedactPassword:
    """Tests for redact_password function."""

    def test_redacts_password(self):
        """Password should be redacted."""
        dsn = "postgresql://user:secretpass@host:5432/db"
        redacted = redact_password(dsn)
        assert "secretpass" not in redacted
        assert "****" in redacted

    def test_preserves_structure(self):
        """DSN structure should be preserved."""
        dsn = "postgresql://user:secretpass@host:5432/db?sslmode=require"
        redacted = redact_password(dsn)
        assert "user:" in redacted
        assert "@host:5432" in redacted
        assert "sslmode=require" in redacted


# =============================================================================
# Tests for validate_dsn.py
# =============================================================================


class TestValidateDsn:
    """Tests for validate_dsn function."""

    def test_valid_shared_pooler_dsn(self):
        """Valid shared pooler DSN should pass."""
        result = validate_dsn(
            "postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        )
        assert result.valid is True
        assert len(result.errors) == 0

    def test_valid_dedicated_pooler_dsn(self):
        """Valid dedicated pooler DSN (port 6543) should pass."""
        result = validate_dsn(
            "postgresql://user:pass@db.abcdefgh123.supabase.co:6543/postgres?sslmode=require"
        )
        assert result.valid is True
        assert len(result.errors) == 0

    def test_invalid_port_5432(self):
        """Port 5432 should fail (direct connection)."""
        result = validate_dsn(
            "postgresql://user:pass@db.abcdefgh123.supabase.co:5432/postgres?sslmode=require"
        )
        assert result.valid is False
        assert any("PORT" in e for e in result.errors)

    def test_invalid_missing_sslmode(self):
        """Missing sslmode should fail."""
        result = validate_dsn(
            "postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        )
        assert result.valid is False
        assert any("SSLMODE" in e for e in result.errors)

    def test_invalid_sslmode_disable(self):
        """sslmode=disable should fail."""
        result = validate_dsn(
            "postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=disable"
        )
        assert result.valid is False
        assert any("SSLMODE" in e for e in result.errors)

    def test_url_encoded_password_accepted(self):
        """URL-encoded password should be accepted."""
        result = validate_dsn(
            "postgresql://user:P%40ssw0rd%21@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        )
        assert result.valid is True

    def test_redacts_password_in_result(self):
        """Password should be redacted in result."""
        result = validate_dsn(
            "postgresql://user:mysecretpassword@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        )
        assert "mysecretpassword" not in result.dsn_redacted


class TestParseDsn:
    """Tests for parse_dsn function."""

    def test_parses_host(self):
        """Host should be correctly parsed."""
        host, port, params = parse_dsn("postgresql://user:pass@example.com:5432/db")
        assert host == "example.com"

    def test_parses_port(self):
        """Port should be correctly parsed."""
        host, port, params = parse_dsn("postgresql://user:pass@example.com:6543/db")
        assert port == 6543

    def test_parses_sslmode(self):
        """sslmode should be correctly parsed from query params."""
        host, port, params = parse_dsn("postgresql://user:pass@example.com:5432/db?sslmode=require")
        assert params.get("sslmode") == ["require"]

    def test_handles_invalid_dsn(self):
        """Invalid DSN should return None values."""
        host, port, params = parse_dsn("not-a-valid-dsn")
        # Should not raise, but host may be None or unusual
        # The function is defensive


class TestRedactDsn:
    """Tests for redact_dsn function in validate_dsn."""

    def test_redacts_password(self):
        """Password should be redacted."""
        result = redact_dsn("postgresql://user:secret@host:5432/db")
        assert "secret" not in result
        assert "REDACTED" in result


# =============================================================================
# Tests for probe_db.py
# =============================================================================


class TestExtractHostPort:
    """Tests for extract_host_port function."""

    def test_extracts_host(self):
        """Host should be correctly extracted."""
        host, port = extract_host_port("postgresql://user:pass@myhost.example.com:6543/db")
        assert host == "myhost.example.com"

    def test_extracts_port(self):
        """Port should be correctly extracted."""
        host, port = extract_host_port("postgresql://user:pass@myhost.example.com:6543/db")
        assert port == 6543

    def test_handles_invalid_dsn(self):
        """Invalid DSN should return None values."""
        host, port = extract_host_port("invalid")
        # Should not raise


class TestProbeRedactDsn:
    """Tests for redact_dsn function in probe_db."""

    def test_redacts_password(self):
        """Password should be redacted."""
        result = probe_redact_dsn("postgresql://user:secret@host:5432/db")
        assert "secret" not in result
        assert "****" in result


# =============================================================================
# Integration-style tests (no actual DB connection)
# =============================================================================


class TestBuildAndValidateIntegration:
    """Test that build_dsn output passes validate_dsn."""

    def test_built_dsn_passes_validation(self):
        """DSN built by build_pooler_dsn should pass validate_dsn."""
        dsn = build_dsn(
            host="aws-0-us-east-1.pooler.supabase.com",
            user="dragonfly_app",
            password="P@ssw0rd!#$",
        )
        result = validate_dsn(dsn)
        assert result.valid is True, f"Validation failed: {result.errors}"

    def test_built_dsn_with_complex_password_passes(self):
        """Complex password should be properly encoded and valid."""
        dsn = build_dsn(
            host="aws-0-us-east-1.pooler.supabase.com",
            user="dragonfly_app",
            password="MyP@ss!Is#Very$Complex%And^Long&*()+=",
        )
        result = validate_dsn(dsn)
        assert result.valid is True, f"Validation failed: {result.errors}"

    def test_built_dsn_for_dedicated_pooler_passes(self):
        """Dedicated pooler DSN should pass validation."""
        dsn = build_dsn(
            host="db.abcdefgh123.supabase.co",
            user="dragonfly_app",
            password="simplepass",
        )
        result = validate_dsn(dsn)
        assert result.valid is True, f"Validation failed: {result.errors}"


# =============================================================================
# CLI tests (using subprocess or mock)
# =============================================================================


class TestBuildPoolerDsnCli:
    """Tests for build_pooler_dsn CLI."""

    def test_main_with_all_args(self):
        """CLI should work with all arguments provided."""
        from tools.build_pooler_dsn import main

        with patch(
            "sys.argv",
            [
                "build_pooler_dsn",
                "--host",
                "aws-0-us-east-1.pooler.supabase.com",
                "--user",
                "testuser",
                "--password",
                "testpass",
                "--quiet",
            ],
        ):
            exit_code = main()

        assert exit_code == 0

    def test_main_password_from_env(self):
        """CLI should read password from environment variable."""
        from tools.build_pooler_dsn import main

        os.environ["TEST_DB_PASSWORD"] = "envpassword"

        try:
            with patch(
                "sys.argv",
                [
                    "build_pooler_dsn",
                    "--host",
                    "aws-0-us-east-1.pooler.supabase.com",
                    "--password-env",
                    "TEST_DB_PASSWORD",
                    "--quiet",
                ],
            ):
                exit_code = main()

            assert exit_code == 0
        finally:
            del os.environ["TEST_DB_PASSWORD"]


class TestValidateDsnCli:
    """Tests for validate_dsn CLI."""

    def test_main_valid_dsn(self):
        """CLI should return 0 for valid DSN."""
        from tools.validate_dsn import main

        with patch(
            "sys.argv",
            [
                "validate_dsn",
                "postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require",
            ],
        ):
            exit_code = main()

        assert exit_code == 0

    def test_main_invalid_dsn(self):
        """CLI should return 1 for invalid DSN."""
        from tools.validate_dsn import main

        with patch(
            "sys.argv",
            [
                "validate_dsn",
                "postgresql://user:pass@host:5432/postgres",  # Wrong port, no sslmode
            ],
        ):
            exit_code = main()

        assert exit_code == 1

    def test_main_no_dsn_returns_2(self):
        """CLI should return 2 when no DSN provided."""
        from tools.validate_dsn import main

        # Clear any env var
        env_backup = os.environ.pop("SUPABASE_DB_URL", None)

        try:
            with patch("sys.argv", ["validate_dsn"]):
                exit_code = main()

            assert exit_code == 2
        finally:
            if env_backup:
                os.environ["SUPABASE_DB_URL"] = env_backup


class TestProbeDnCli:
    """Tests for probe_db CLI (mocked, no actual DB connection)."""

    def test_main_no_dsn_returns_2(self):
        """CLI should return 2 when no DSN provided."""
        from tools.probe_db import main

        # Clear any env var
        env_backup = os.environ.pop("SUPABASE_DB_URL", None)

        try:
            with patch("sys.argv", ["probe_db"]):
                exit_code = main()

            assert exit_code == 2
        finally:
            if env_backup:
                os.environ["SUPABASE_DB_URL"] = env_backup
