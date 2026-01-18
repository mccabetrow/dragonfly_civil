#!/usr/bin/env python3
"""
Test: Indestructible Boot Pattern

Validates that the API can boot and respond even when DATABASE_URL is missing.
This is critical for production resilience - the API should never crash-loop.

Acceptance Criteria:
1. validate_required_env(fail_fast=False) returns missing vars but doesn't raise
2. config.py model validator logs warning but doesn't raise on missing DB URL
3. main.py imports successfully (API can start)
"""

import os

import pytest


class TestIndestructibleBoot:
    """Test suite for Indestructible Boot pattern."""

    def test_validate_required_env_returns_missing_vars(self):
        """validate_required_env(fail_fast=False) should return missing vars without raising."""
        # Clear BOTH DATABASE_URL and SUPABASE_DB_URL (fallback) to test missing
        originals = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SUPABASE_DB_URL": os.environ.get("SUPABASE_DB_URL"),
        }
        os.environ["DATABASE_URL"] = ""
        os.environ["SUPABASE_DB_URL"] = ""

        try:
            # Import here to avoid cached settings
            from backend.core.config import validate_required_env

            # Should NOT raise with fail_fast=False
            result = validate_required_env(fail_fast=False)

            assert not result["valid"], "Should be invalid when DB URL missing"
            # DATABASE_URL is now the canonical primary key
            assert "DATABASE_URL" in result["missing"], "DATABASE_URL should be in missing list"
        finally:
            # Restore
            for key, val in originals.items():
                if val:
                    os.environ[key] = val
                elif key in os.environ:
                    del os.environ[key]

    def test_validate_required_env_raises_with_fail_fast(self):
        """validate_required_env(fail_fast=True) should raise when vars missing."""
        originals = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SUPABASE_DB_URL": os.environ.get("SUPABASE_DB_URL"),
        }
        os.environ["DATABASE_URL"] = ""
        os.environ["SUPABASE_DB_URL"] = ""

        try:
            from backend.core.config import validate_required_env

            with pytest.raises(RuntimeError, match="Missing required environment"):
                validate_required_env(fail_fast=True)
        finally:
            for key, val in originals.items():
                if val:
                    os.environ[key] = val
                elif key in os.environ:
                    del os.environ[key]

    def test_settings_handles_empty_db_url(self):
        """Settings should not crash when DATABASE_URL is empty (degraded mode)."""
        # Save originals
        originals = {
            "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
            "SUPABASE_DB_URL": os.environ.get("SUPABASE_DB_URL", ""),
            "SUPABASE_URL": os.environ.get("SUPABASE_URL", ""),
            "SUPABASE_SERVICE_ROLE_KEY": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            "DRAGONFLY_ENV": os.environ.get("DRAGONFLY_ENV", "dev"),
        }

        try:
            # Set minimal config without DB URL
            os.environ["DATABASE_URL"] = ""
            os.environ["SUPABASE_DB_URL"] = ""
            os.environ["SUPABASE_URL"] = "https://test.supabase.co"
            os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-key"
            os.environ["DRAGONFLY_ENV"] = "dev"

            # Clear cached settings
            from backend.core.config import Settings, reset_settings

            reset_settings()

            # Should NOT raise - enters degraded mode
            settings = Settings()
            # The resolved database_url property should be empty
            assert settings.database_url == "", "Empty DB URL should be allowed"

        finally:
            # Restore
            for key, val in originals.items():
                os.environ[key] = val
            from backend.core.config import reset_settings

            reset_settings()

    def test_db_state_marks_no_config(self):
        """db_state should mark no_config when DB URL is missing."""
        from backend.core.db_state import db_state

        # Call mark_no_config
        db_state.mark_no_config()

        assert not db_state.ready, "Should not be ready when no config"
        assert not db_state.healthy, "Should not be healthy when no config"
        assert db_state.last_error_class == "no_config", "Error class should be no_config"

    def test_readiness_metadata_includes_no_config(self):
        """Readiness metadata should reflect no_config state."""
        from backend.core.db_state import db_state

        db_state.mark_no_config()
        metadata = db_state.readiness_metadata()

        assert metadata["ready"] is False
        assert metadata["last_error_class"] == "no_config"
        # Either DATABASE_URL or SUPABASE_DB_URL reference is acceptable
        assert "not configured" in (metadata["last_error"] or "").lower()


class TestDataMoat:
    """Test suite for Data Moat (ingest idempotency) pattern."""

    def test_ingest_worker_has_idempotency_functions(self):
        """Ingest worker should have all required idempotency functions."""
        # Verify the module has the expected functions
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "ingest_worker", "backend/workers/ingest_worker.py"
        )
        assert spec is not None, "ingest_worker.py should exist"

        # Read the source and check for key patterns
        with open("backend/workers/ingest_worker.py") as f:
            source = f.read()

        assert "get_import_run_status" in source, "Should have idempotency check function"
        assert "claim_import_run" in source, "Should have claim function"
        assert "ON CONFLICT" in source, "Should use ON CONFLICT for idempotency"
        assert "complete_import_run" in source, "Should have completion function"
        assert "fail_import_run" in source, "Should have failure tracking function"

    def test_ingest_worker_uses_transaction_pattern(self):
        """Ingest worker should use transaction commit/rollback pattern."""
        with open("backend/workers/ingest_worker.py") as f:
            source = f.read()

        assert "conn.commit()" in source, "Should commit transactions"
        assert "conn.rollback()" in source, "Should rollback on failure"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
