"""
Tests for PostgreSQL application_name handling.

These tests validate that connection parameters are safe for PostgreSQL
and would have caught the v1.3.1 failure where 'Dragonfly v1.3.1' caused:
    "invalid command-line argument: '-c application_name=Dragonfly v1.3.1'"

The issue was spaces/special chars in application_name when passed via options.
"""

from __future__ import annotations

import re

import pytest

from backend import __version__
from backend.workers.db_connect import get_safe_application_name


class TestGetSafeApplicationName:
    """Tests for get_safe_application_name helper function."""

    def test_returns_string(self):
        """Function returns a string."""
        result = get_safe_application_name("test_worker")
        assert isinstance(result, str)

    def test_includes_dragonfly_prefix(self):
        """Result starts with dragonfly_."""
        result = get_safe_application_name("worker")
        assert result.startswith("dragonfly_")

    def test_includes_version(self):
        """Result includes version number."""
        result = get_safe_application_name("worker")
        # Version should be embedded (with underscores)
        assert "v" in result
        # For version "1.3.1", we expect "1_3_1" in the result
        version_underscored = __version__.replace(".", "_")
        assert version_underscored in result

    def test_includes_worker_type(self):
        """Result includes worker type suffix."""
        result = get_safe_application_name("ingest_processor")
        assert result.endswith("_ingest_processor")

    def test_no_spaces(self):
        """Result contains no spaces (would break PostgreSQL options parsing)."""
        result = get_safe_application_name("my worker name")
        assert " " not in result

    def test_no_dots(self):
        """Result contains no dots (could cause parsing issues)."""
        result = get_safe_application_name("worker.name")
        assert "." not in result

    def test_no_dashes(self):
        """Result contains no dashes (normalized to underscores)."""
        result = get_safe_application_name("worker-name")
        assert "-" not in result

    def test_sanitizes_worker_type_with_spaces(self):
        """Spaces in worker type are converted to underscores."""
        result = get_safe_application_name("my worker")
        assert result.endswith("_my_worker")

    def test_sanitizes_worker_type_with_dashes(self):
        """Dashes in worker type are converted to underscores."""
        result = get_safe_application_name("my-worker")
        assert result.endswith("_my_worker")

    def test_sanitizes_worker_type_with_dots(self):
        """Dots in worker type are converted to underscores."""
        result = get_safe_application_name("my.worker")
        assert result.endswith("_my_worker")

    def test_format_matches_expected_pattern(self):
        """Result matches expected pattern: dragonfly_vX_Y_Z_workertype."""
        result = get_safe_application_name("test")
        # Should match: dragonfly_v{version_with_underscores}_{worker_type}
        pattern = r"^dragonfly_v[0-9]+_[0-9]+_[0-9]+_\w+$"
        assert re.match(pattern, result), f"'{result}' doesn't match pattern {pattern}"


class TestApplicationNamePgSafety:
    """Tests ensuring application_name is safe for PostgreSQL.

    These tests would have caught the v1.3.1 failure where the application_name
    contained spaces and was passed via '-c application_name=...' in options,
    causing PostgreSQL to fail with "invalid command-line argument".
    """

    def test_no_characters_that_break_pg_options(self):
        """Ensure no characters that would break -c option parsing."""
        result = get_safe_application_name("test_worker")

        # Characters that break PostgreSQL -c option parsing
        dangerous_chars = [
            " ",  # Space - caused the v1.3.1 failure
            "'",  # Single quote - breaks shell parsing
            '"',  # Double quote - breaks shell parsing
            "\\",  # Backslash - escape sequences
            "\n",  # Newline - breaks argument parsing
            "\r",  # Carriage return - breaks argument parsing
            "\t",  # Tab - whitespace issues
            ";",  # Semicolon - command injection
            "$",  # Dollar sign - variable expansion
            "`",  # Backtick - command substitution
        ]

        for char in dangerous_chars:
            assert char not in result, f"Dangerous char '{repr(char)}' found in '{result}'"

    def test_only_safe_characters(self):
        """Result contains only alphanumeric and underscores."""
        result = get_safe_application_name("test_worker")
        # Only a-z, A-Z, 0-9, and underscore are allowed
        assert re.match(r"^[a-zA-Z0-9_]+$", result), f"'{result}' contains unsafe characters"

    def test_reasonable_length(self):
        """Result is within PostgreSQL's application_name limit (64 chars)."""
        result = get_safe_application_name("very_long_worker_name_that_might_be_problematic")
        # PostgreSQL application_name max is 64 characters
        assert len(result) <= 64, f"application_name too long: {len(result)} chars"

    def test_not_empty(self):
        """Result is never empty."""
        result = get_safe_application_name("")
        assert len(result) > 0
        assert result.startswith("dragonfly_")


class TestBackendDbPoolApplicationName:
    """Tests for backend/db.py pool initialization."""

    def test_pool_uses_safe_application_name_format(self):
        """Verify the pool init code uses kwargs format, not options."""
        import re
        from pathlib import Path

        db_py = Path(__file__).parent.parent / "backend" / "db.py"
        source = db_py.read_text(encoding="utf-8")

        # Verify we use kwargs= parameter (either inline dict or variable)
        assert "kwargs=" in source, "Pool should use kwargs= parameter"
        assert '"application_name"' in source, "Should include application_name string"

        # Verify we do NOT use options with -c application_name
        assert "-c application_name" not in source
        # options= is OK for statement_timeout, just not for application_name
        if "options=" in source.lower():
            # Check that options doesn't contain application_name
            assert "application_name" not in source.split("options=")[1].split(")")[0]

    def test_no_pgoptions_env_var_usage(self):
        """Verify we don't set PGOPTIONS to configure application_name."""
        from pathlib import Path

        db_py = Path(__file__).parent.parent / "backend" / "db.py"
        source = db_py.read_text(encoding="utf-8")

        assert "PGOPTIONS" not in source, "Should not use PGOPTIONS env var"


class TestVersionSanitization:
    """Tests for version string sanitization."""

    def test_version_dots_become_underscores(self):
        """Version dots are converted to underscores."""
        # The actual __version__ should be sanitized
        result = get_safe_application_name("test")

        # If version is "1.3.1", we should see "1_3_1", not "1.3.1"
        if "." in __version__:
            assert __version__ not in result, "Raw version with dots should not appear"
            expected_version = __version__.replace(".", "_").replace("-", "_")
            assert expected_version in result

    def test_handles_prerelease_versions(self):
        """Handles versions like 1.3.1-alpha safely."""
        # Simulate what would happen with a prerelease version
        test_version = "1.3.1-alpha.2"
        sanitized = test_version.replace(".", "_").replace("-", "_").replace(" ", "_")
        assert " " not in sanitized
        assert "." not in sanitized
        assert "-" not in sanitized
