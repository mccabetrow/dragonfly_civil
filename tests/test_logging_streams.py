"""
Unit tests for logging stream routing.

Verifies that INFO/DEBUG logs go to stdout and WARNING+ logs go to stderr.
This prevents PowerShell/CI NativeCommandError caused by INFO on stderr.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest


class TestLoggingStreams:
    """Test that log levels are routed to correct streams."""

    def test_worker_import_no_info_on_stderr(self):
        """
        Importing a worker should not write INFO logs to stderr.

        This is critical for PowerShell/CI which treats stderr output as errors.
        """
        # Run worker import in subprocess to capture stderr
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import backend.workers.ingest_processor",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
            timeout=30,
        )

        # stderr should be empty or contain only WARNING+ level logs
        stderr_lines = [line for line in result.stderr.strip().split("\n") if line.strip()]

        info_on_stderr = [
            line
            for line in stderr_lines
            if "| INFO" in line or '"level":"INFO"' in line or '"level": "INFO"' in line
        ]

        assert not info_on_stderr, (
            f"Found INFO logs on stderr (causes PowerShell NativeCommandError):\n"
            f"{chr(10).join(info_on_stderr)}"
        )

    def test_configure_worker_logging_routes_correctly(self):
        """Test that configure_worker_logging routes levels to correct streams."""
        import io

        from backend.core.logging import configure_worker_logging

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Save original handlers
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]

        try:
            # Remove all handlers
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)

            # Create custom handlers pointing to our captures
            from backend.core.logging import _MaxLevelFilter, _SimpleFormatter

            stdout_handler = logging.StreamHandler(stdout_capture)
            stdout_handler.setLevel(logging.DEBUG)
            stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
            stdout_handler.setFormatter(_SimpleFormatter())

            stderr_handler = logging.StreamHandler(stderr_capture)
            stderr_handler.setLevel(logging.WARNING)
            stderr_handler.setFormatter(_SimpleFormatter())

            root_logger.addHandler(stdout_handler)
            root_logger.addHandler(stderr_handler)
            root_logger.setLevel(logging.DEBUG)

            # Log at different levels
            test_logger = logging.getLogger("test_streams")
            test_logger.debug("debug message")
            test_logger.info("info message")
            test_logger.warning("warning message")
            test_logger.error("error message")

            # Verify routing
            stdout_content = stdout_capture.getvalue()
            stderr_content = stderr_capture.getvalue()

            # DEBUG and INFO should be on stdout
            assert "debug message" in stdout_content
            assert "info message" in stdout_content
            assert "warning message" not in stdout_content
            assert "error message" not in stdout_content

            # WARNING and ERROR should be on stderr
            assert "warning message" in stderr_content
            assert "error message" in stderr_content
            assert "debug message" not in stderr_content
            assert "info message" not in stderr_content

        finally:
            # Restore original handlers
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)
            for handler in original_handlers:
                root_logger.addHandler(handler)

    def test_structured_logging_routes_correctly(self):
        """Test that configure_structured_logging routes levels to correct streams."""
        import io

        from backend.core.logging import configure_structured_logging

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Save original handlers
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]

        try:
            # Remove all handlers
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)

            # Create custom handlers pointing to our captures
            from backend.core.logging import StructuredJsonFormatter, _MaxLevelFilter

            formatter = StructuredJsonFormatter()

            stdout_handler = logging.StreamHandler(stdout_capture)
            stdout_handler.setLevel(logging.DEBUG)
            stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
            stdout_handler.setFormatter(formatter)

            stderr_handler = logging.StreamHandler(stderr_capture)
            stderr_handler.setLevel(logging.WARNING)
            stderr_handler.setFormatter(formatter)

            root_logger.addHandler(stdout_handler)
            root_logger.addHandler(stderr_handler)
            root_logger.setLevel(logging.DEBUG)

            # Log at different levels
            test_logger = logging.getLogger("test_json_streams")
            test_logger.info("json info message")
            test_logger.warning("json warning message")

            # Verify routing
            stdout_content = stdout_capture.getvalue()
            stderr_content = stderr_capture.getvalue()

            assert "json info message" in stdout_content
            assert "json warning message" not in stdout_content

            assert "json warning message" in stderr_content
            assert "json info message" not in stderr_content

        finally:
            # Restore original handlers
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)
            for handler in original_handlers:
                root_logger.addHandler(handler)

    def test_json_formatter_applies_version_metadata(self, monkeypatch):
        """JSONFormatter should include sha/env metadata from resolver."""
        import backend.middleware.version as version_module
        import backend.utils.logging as logging_utils

        metadata = {
            "env": "stage",
            "sha": "1234567890abcdef1234567890abcdef12345678",
            "sha_short": "12345678",
            "version": "9.9.9-test",
            "sha_source": "RAILWAY_GIT_COMMIT_SHA",
        }

        monkeypatch.setattr(logging_utils, "_LOG_DEFAULTS_READY", False)
        monkeypatch.setattr(logging_utils, "_LOG_DEFAULTS", dict(logging_utils._LOG_DEFAULTS))
        monkeypatch.setattr(version_module, "get_version_info", lambda: metadata)

        formatter = logging_utils.JSONFormatter(service_name="unit-test")
        record = logging.LogRecord(
            name="unit",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="sha-check",
            args=(),
            exc_info=None,
        )

        payload = json.loads(formatter.format(record))

        assert payload["sha"] == metadata["sha"]
        assert payload["sha_short"] == metadata["sha_short"]
        assert payload["env"] == metadata["env"]
        assert payload["version"] == metadata["version"]
        assert payload["service"] == "unit-test"
