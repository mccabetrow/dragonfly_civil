"""
Tests for Supabase Pooler Metadata Derivation

Validates _derive_pooler_metadata correctly identifies:
- Shared pooler (aws-*.pooler.supabase.com)
- Dedicated pooler (db.<ref>.supabase.co:6543)
- Direct connection (db.<ref>.supabase.co:5432) - FORBIDDEN
- Project ref extraction from hostname or username
"""

import pytest

from backend.db import _derive_pooler_metadata


class TestSharedPoolerDetection:
    """Tests for shared pooler (aws-*.pooler.supabase.com)."""

    def test_shared_pooler_detected(self) -> None:
        """Shared pooler with correct username format."""
        dsn = "postgresql://postgres.iaketsyhmqbwaabgykux:pwd@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        meta = _derive_pooler_metadata(dsn)

        assert meta["pooler_mode"] == "shared"
        assert meta["host"] == "aws-0-us-east-1.pooler.supabase.com"
        assert meta["port"] == "6543"
        assert meta["project_ref"] == "iaketsyhmqbwaabgykux"
        assert meta["region"] == "aws-0-us-east-1"

    def test_shared_pooler_user_redacted(self) -> None:
        """Username should be redacted to user.***"""
        dsn = "postgresql://postgres.iaketsyhmqbwaabgykux:pwd@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        meta = _derive_pooler_metadata(dsn)

        assert meta["user_redacted"] == "postgres.***"

    def test_shared_pooler_missing_project_ref(self) -> None:
        """Username without project ref should flag missing."""
        dsn = "postgresql://postgres:pwd@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        meta = _derive_pooler_metadata(dsn)

        assert meta["pooler_mode"] == "shared"
        assert meta["user_redacted"] == "postgres.*MISSING*"
        assert meta["project_ref"] is None

    def test_shared_pooler_custom_role(self) -> None:
        """Custom role with project ref suffix."""
        dsn = "postgresql://dragonfly_app.iaketsyhmqbwaabgykux:pwd@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        meta = _derive_pooler_metadata(dsn)

        assert meta["pooler_mode"] == "shared"
        assert meta["user_redacted"] == "dragonfly_app.***"
        assert meta["project_ref"] == "iaketsyhmqbwaabgykux"


class TestDedicatedPoolerDetection:
    """Tests for dedicated pooler (db.<ref>.supabase.co:6543)."""

    def test_dedicated_pooler_detected(self) -> None:
        """Dedicated pooler on port 6543."""
        dsn = "postgresql://postgres:pwd@db.iaketsyhmqbwaabgykux.supabase.co:6543/postgres"
        meta = _derive_pooler_metadata(dsn)

        assert meta["pooler_mode"] == "dedicated"
        assert meta["host"] == "db.iaketsyhmqbwaabgykux.supabase.co"
        assert meta["port"] == "6543"
        assert meta["project_ref"] == "iaketsyhmqbwaabgykux"

    def test_dedicated_pooler_user_redacted(self) -> None:
        """Username should be partially redacted."""
        dsn = "postgresql://postgres:pwd@db.iaketsyhmqbwaabgykux.supabase.co:6543/postgres"
        meta = _derive_pooler_metadata(dsn)

        # First 3 chars + ***
        assert meta["user_redacted"] == "pos***"


class TestDirectConnectionDetection:
    """Tests for direct connection (db.<ref>.supabase.co:5432) - FORBIDDEN."""

    def test_direct_connection_detected(self) -> None:
        """Direct connection on port 5432 should be flagged."""
        dsn = "postgresql://postgres:pwd@db.iaketsyhmqbwaabgykux.supabase.co:5432/postgres"
        meta = _derive_pooler_metadata(dsn)

        assert meta["pooler_mode"] == "direct"
        assert meta["port"] == "5432"
        assert meta["project_ref"] == "iaketsyhmqbwaabgykux"


class TestUnknownHosts:
    """Tests for non-Supabase hosts."""

    def test_unknown_host(self) -> None:
        """Non-Supabase host should be unknown."""
        dsn = "postgresql://user:pwd@localhost:5432/mydb"
        meta = _derive_pooler_metadata(dsn)

        assert meta["pooler_mode"] == "unknown"
        assert meta["project_ref"] is None

    def test_custom_postgres_host(self) -> None:
        """Custom PostgreSQL host."""
        dsn = "postgresql://user:pwd@my-db.example.com:5432/mydb"
        meta = _derive_pooler_metadata(dsn)

        assert meta["pooler_mode"] == "unknown"


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_invalid_dsn(self) -> None:
        """Invalid DSN should not crash."""
        meta = _derive_pooler_metadata("not-a-valid-dsn")

        assert meta["pooler_mode"] == "unknown"

    def test_empty_dsn(self) -> None:
        """Empty DSN should not crash."""
        meta = _derive_pooler_metadata("")

        assert meta["pooler_mode"] == "unknown"

    def test_dsn_with_sslmode(self) -> None:
        """DSN with query parameters."""
        dsn = "postgresql://postgres.iaketsyhmqbwaabgykux:pwd@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
        meta = _derive_pooler_metadata(dsn)

        assert meta["pooler_mode"] == "shared"
        assert meta["project_ref"] == "iaketsyhmqbwaabgykux"
