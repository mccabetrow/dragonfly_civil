"""
Tests for the Intake Guardian self-healing subsystem.

Tests cover:
- Detection of stuck batches (processing > stale_minutes)
- Marking stuck batches as failed
- Logging failure reason to ops.intake_logs
- Ignoring recent batches (not stuck)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.services.intake_guardian import GuardianResult, IntakeGuardian, get_intake_guardian


class TestIntakeGuardianUnit:
    """Unit tests for IntakeGuardian (mocked DB)."""

    @pytest.fixture
    def guardian(self) -> IntakeGuardian:
        """Create a guardian instance with default settings."""
        return IntakeGuardian(stale_minutes=5, max_retries=1)

    @pytest.fixture
    def mock_conn(self) -> MagicMock:
        """Create a mock connection wrapper."""
        mock = MagicMock()
        mock.fetch = AsyncMock(return_value=[])
        mock.execute = AsyncMock(return_value="UPDATE 1")
        mock.transaction = MagicMock(return_value=AsyncMock())
        return mock

    @pytest.mark.asyncio
    async def test_no_stuck_batches(self, guardian: IntakeGuardian, mock_conn: MagicMock) -> None:
        """Test that guardian handles no stuck batches gracefully."""
        mock_conn.fetch.return_value = []

        with patch("backend.services.intake_guardian.get_connection") as mock_get_conn:
            mock_get_conn.return_value.__aenter__.return_value = mock_conn

            result = await guardian.check_stuck_batches()

        assert result.checked == 0
        assert result.marked_failed == 0
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_stuck_batch_detected(
        self, guardian: IntakeGuardian, mock_conn: MagicMock
    ) -> None:
        """Test that a stuck batch is detected and marked as failed."""
        batch_id = uuid4()
        stuck_batch = {
            "id": batch_id,
            "filename": "test_stuck.csv",
            "source": "simplicity",
            "created_at": datetime.utcnow() - timedelta(minutes=10),
            "updated_at": datetime.utcnow() - timedelta(minutes=10),
        }
        mock_conn.fetch.return_value = [stuck_batch]

        # Mock the transaction context manager
        mock_transaction = AsyncMock()
        mock_transaction.__aenter__ = AsyncMock()
        mock_transaction.__aexit__ = AsyncMock()
        mock_conn.transaction.return_value = mock_transaction

        with patch("backend.services.intake_guardian.get_connection") as mock_get_conn:
            mock_get_conn.return_value.__aenter__.return_value = mock_conn

            # Mock Discord to prevent actual calls
            with patch("backend.services.intake_guardian.DiscordService") as mock_discord:
                mock_discord_instance = AsyncMock()
                mock_discord_instance.send_message = AsyncMock(return_value=True)
                mock_discord.return_value.__aenter__.return_value = mock_discord_instance
                mock_discord.return_value.__aexit__.return_value = None

                result = await guardian.check_stuck_batches()

        assert result.checked == 1
        assert result.marked_failed == 1
        assert len(result.errors) == 0

        # Verify DB calls were made
        assert mock_conn.fetch.called
        # Should have called execute at least twice (UPDATE + INSERT)
        assert mock_conn.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_recent_batch_not_touched(
        self, guardian: IntakeGuardian, mock_conn: MagicMock
    ) -> None:
        """Test that batches updated recently are not marked as failed."""
        # A batch updated 1 minute ago should NOT be in the stuck query results
        # because our SQL filters for updated_at < NOW() - interval '5 minutes'
        mock_conn.fetch.return_value = []

        with patch("backend.services.intake_guardian.get_connection") as mock_get_conn:
            mock_get_conn.return_value.__aenter__.return_value = mock_conn

            result = await guardian.check_stuck_batches()

        assert result.checked == 0
        assert result.marked_failed == 0

    @pytest.mark.asyncio
    async def test_guardian_handles_db_error(self, guardian: IntakeGuardian) -> None:
        """Test that guardian catches and logs DB errors without crashing."""
        with patch("backend.services.intake_guardian.get_connection") as mock_get_conn:
            mock_get_conn.return_value.__aenter__.side_effect = Exception("DB connection failed")

            result = await guardian.check_stuck_batches()

        assert result.checked == 0
        assert result.marked_failed == 0
        assert len(result.errors) == 1
        assert "DB connection failed" in result.errors[0]


class TestGuardianResultDataclass:
    """Tests for the GuardianResult dataclass."""

    def test_to_dict(self) -> None:
        """Test that to_dict returns correct structure."""
        result = GuardianResult(checked=5, marked_failed=2, errors=["error1"])
        d = result.to_dict()

        assert d["checked"] == 5
        assert d["marked_failed"] == 2
        assert d["errors"] == ["error1"]

    def test_default_values(self) -> None:
        """Test that default values are correct."""
        result = GuardianResult()

        assert result.checked == 0
        assert result.marked_failed == 0
        assert result.errors == []


class TestGetIntakeGuardian:
    """Tests for the singleton getter."""

    def test_singleton_pattern(self) -> None:
        """Test that get_intake_guardian returns the same instance."""
        # Reset the singleton
        import backend.services.intake_guardian as module

        module._guardian_instance = None

        g1 = get_intake_guardian()
        g2 = get_intake_guardian()

        assert g1 is g2

    def test_default_settings(self) -> None:
        """Test that default settings are correct."""
        import backend.services.intake_guardian as module

        module._guardian_instance = None

        guardian = get_intake_guardian()

        assert guardian.stale_minutes == 5
        assert guardian.max_retries == 1
