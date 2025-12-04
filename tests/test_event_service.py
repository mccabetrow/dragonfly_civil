"""
Tests for the Event Service.

Tests event emission, timeline retrieval, and entity lookup.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.services.event_service import (
    EVENT_TYPES,
    EventDTO,
    emit_event,
    emit_event_for_judgment,
    get_entity_id_for_judgment,
    get_timeline_for_entity,
    get_timeline_for_judgment,
)

# =============================================================================
# Test Data
# =============================================================================

SAMPLE_ENTITY_ID = uuid4()
SAMPLE_JUDGMENT_ID = 12345
SAMPLE_EVENT_ID = uuid4()


class MockAsyncCursor:
    """Mock async cursor that properly supports async context manager protocol."""

    def __init__(self):
        self.execute = AsyncMock()
        self.fetchall = AsyncMock(return_value=[])
        self.fetchone = AsyncMock(return_value=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def create_mock_connection():
    """Create a properly configured mock async connection."""
    mock_cursor = MockAsyncCursor()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


# =============================================================================
# Unit Tests: emit_event
# =============================================================================


class TestEmitEvent:
    """Tests for emit_event function."""

    @pytest.mark.asyncio
    async def test_emit_event_with_valid_type(self):
        """emit_event should insert a row for valid event types."""
        mock_conn, mock_cursor = create_mock_connection()

        with patch("backend.services.event_service.get_pool", return_value=mock_conn):
            await emit_event(
                entity_id=SAMPLE_ENTITY_ID,
                event_type="new_judgment",
                payload={"judgment_id": 123, "amount": "5000"},
            )

        # Verify INSERT was called
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert "INSERT INTO intelligence.events" in call_args[0][0]
        assert call_args[0][1][1] == "new_judgment"

    @pytest.mark.asyncio
    async def test_emit_event_rejects_invalid_type(self):
        """emit_event should log warning and return for invalid event types."""
        with patch("backend.services.event_service.get_pool") as mock_get_pool, patch(
            "backend.services.event_service.logger"
        ) as mock_logger:
            await emit_event(
                entity_id=SAMPLE_ENTITY_ID,
                event_type="invalid_type",  # type: ignore
                payload={},
            )

        # Should not call database
        mock_get_pool.assert_not_called()

        # Should log warning
        mock_logger.warning.assert_called_once()
        assert "Invalid event_type" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_emit_event_handles_db_failure_gracefully(self):
        """emit_event should log error and return (not raise) on DB failure."""
        mock_conn, mock_cursor = create_mock_connection()
        mock_cursor.execute.side_effect = Exception("Database error")

        with patch(
            "backend.services.event_service.get_pool", return_value=mock_conn
        ), patch("backend.services.event_service.logger") as mock_logger:
            # Should not raise
            await emit_event(
                entity_id=SAMPLE_ENTITY_ID,
                event_type="new_judgment",
                payload={},
            )

        # Should log warning
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_event_handles_no_connection(self):
        """emit_event should handle case when no DB connection is available."""
        with patch("backend.services.event_service.get_pool", return_value=None), patch(
            "backend.services.event_service.logger"
        ) as mock_logger:
            await emit_event(
                entity_id=SAMPLE_ENTITY_ID,
                event_type="job_found",
                payload={},
            )

        mock_logger.warning.assert_called_once()
        assert "Database connection not available" in str(mock_logger.warning.call_args)

    @pytest.mark.asyncio
    async def test_emit_event_with_all_valid_types(self):
        """emit_event should accept all valid event types."""
        for event_type in EVENT_TYPES:
            mock_conn, mock_cursor = create_mock_connection()

            with patch(
                "backend.services.event_service.get_pool", return_value=mock_conn
            ):
                await emit_event(
                    entity_id=SAMPLE_ENTITY_ID,
                    event_type=event_type,  # type: ignore
                    payload={},
                )

            # Verify INSERT was called
            mock_cursor.execute.assert_called_once()


# =============================================================================
# Unit Tests: get_timeline_for_entity
# =============================================================================


class TestGetTimelineForEntity:
    """Tests for get_timeline_for_entity function."""

    @pytest.mark.asyncio
    async def test_get_timeline_returns_events(self):
        """get_timeline_for_entity should return list of EventDTO."""
        now = datetime.now(timezone.utc)
        mock_rows = [
            (SAMPLE_EVENT_ID, "new_judgment", now, {"amount": "5000"}),
            (uuid4(), "job_found", now, {"employer_name": "ACME Corp"}),
        ]

        mock_conn, mock_cursor = create_mock_connection()
        mock_cursor.fetchall.return_value = mock_rows

        with patch("backend.services.event_service.get_pool", return_value=mock_conn):
            events = await get_timeline_for_entity(SAMPLE_ENTITY_ID, limit=100)

        assert len(events) == 2
        assert isinstance(events[0], EventDTO)
        assert events[0].event_type == "new_judgment"
        assert events[1].event_type == "job_found"

    @pytest.mark.asyncio
    async def test_get_timeline_empty_result(self):
        """get_timeline_for_entity should return empty list when no events."""
        mock_conn, mock_cursor = create_mock_connection()
        mock_cursor.fetchall.return_value = []

        with patch("backend.services.event_service.get_pool", return_value=mock_conn):
            events = await get_timeline_for_entity(SAMPLE_ENTITY_ID)

        assert events == []

    @pytest.mark.asyncio
    async def test_get_timeline_handles_db_error(self):
        """get_timeline_for_entity should return empty list on error."""
        mock_conn, mock_cursor = create_mock_connection()
        mock_cursor.fetchall.side_effect = Exception("Database error")

        with patch("backend.services.event_service.get_pool", return_value=mock_conn):
            events = await get_timeline_for_entity(SAMPLE_ENTITY_ID)

        assert events == []

    @pytest.mark.asyncio
    async def test_get_timeline_respects_limit(self):
        """get_timeline_for_entity should pass limit to query."""
        mock_conn, mock_cursor = create_mock_connection()
        mock_cursor.fetchall.return_value = []

        with patch("backend.services.event_service.get_pool", return_value=mock_conn):
            await get_timeline_for_entity(SAMPLE_ENTITY_ID, limit=50)

        call_args = mock_cursor.execute.call_args
        assert 50 in call_args[0][1]


# =============================================================================
# Unit Tests: get_entity_id_for_judgment
# =============================================================================


class TestGetEntityIdForJudgment:
    """Tests for get_entity_id_for_judgment function."""

    @pytest.mark.asyncio
    async def test_returns_entity_id_when_found(self):
        """get_entity_id_for_judgment should return UUID when entity exists."""
        mock_conn, mock_cursor = create_mock_connection()
        mock_cursor.fetchone.return_value = (str(SAMPLE_ENTITY_ID),)

        with patch("backend.services.event_service.get_pool", return_value=mock_conn):
            entity_id = await get_entity_id_for_judgment(SAMPLE_JUDGMENT_ID)

        assert entity_id == SAMPLE_ENTITY_ID

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """get_entity_id_for_judgment should return None when no entity."""
        mock_conn, mock_cursor = create_mock_connection()
        mock_cursor.fetchone.return_value = (None,)

        with patch("backend.services.event_service.get_pool", return_value=mock_conn):
            entity_id = await get_entity_id_for_judgment(SAMPLE_JUDGMENT_ID)

        assert entity_id is None

    @pytest.mark.asyncio
    async def test_handles_db_error(self):
        """get_entity_id_for_judgment should return None on error."""
        mock_conn, mock_cursor = create_mock_connection()
        mock_cursor.fetchone.side_effect = Exception("Database error")

        with patch("backend.services.event_service.get_pool", return_value=mock_conn):
            entity_id = await get_entity_id_for_judgment(SAMPLE_JUDGMENT_ID)

        assert entity_id is None


# =============================================================================
# Unit Tests: get_timeline_for_judgment
# =============================================================================


class TestGetTimelineForJudgment:
    """Tests for get_timeline_for_judgment function."""

    @pytest.mark.asyncio
    async def test_returns_timeline_when_entity_found(self):
        """get_timeline_for_judgment should return timeline when entity exists."""
        now = datetime.now(timezone.utc)

        with patch(
            "backend.services.event_service.get_entity_id_for_judgment",
            return_value=SAMPLE_ENTITY_ID,
        ), patch(
            "backend.services.event_service.get_timeline_for_entity",
            return_value=[
                EventDTO(
                    id=str(SAMPLE_EVENT_ID),
                    event_type="new_judgment",
                    created_at=now,
                    payload={"amount": "5000"},
                )
            ],
        ):
            events = await get_timeline_for_judgment(SAMPLE_JUDGMENT_ID)

        assert len(events) == 1
        assert events[0].event_type == "new_judgment"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_entity(self):
        """get_timeline_for_judgment should return empty list when no entity."""
        with patch(
            "backend.services.event_service.get_entity_id_for_judgment",
            return_value=None,
        ):
            events = await get_timeline_for_judgment(SAMPLE_JUDGMENT_ID)

        assert events == []


# =============================================================================
# Unit Tests: emit_event_for_judgment
# =============================================================================


class TestEmitEventForJudgment:
    """Tests for emit_event_for_judgment function."""

    @pytest.mark.asyncio
    async def test_emits_event_when_entity_found(self):
        """emit_event_for_judgment should emit event when entity exists."""
        with patch(
            "backend.services.event_service.get_entity_id_for_judgment",
            return_value=SAMPLE_ENTITY_ID,
        ), patch("backend.services.event_service.emit_event") as mock_emit:
            await emit_event_for_judgment(
                judgment_id=SAMPLE_JUDGMENT_ID,
                event_type="offer_made",
                payload={"amount": "1000"},
            )

        mock_emit.assert_called_once_with(
            SAMPLE_ENTITY_ID, "offer_made", {"amount": "1000"}
        )

    @pytest.mark.asyncio
    async def test_skips_when_no_entity(self):
        """emit_event_for_judgment should skip when no entity found."""
        with patch(
            "backend.services.event_service.get_entity_id_for_judgment",
            return_value=None,
        ), patch("backend.services.event_service.emit_event") as mock_emit:
            await emit_event_for_judgment(
                judgment_id=SAMPLE_JUDGMENT_ID,
                event_type="offer_made",
                payload={"amount": "1000"},
            )

        mock_emit.assert_not_called()


# =============================================================================
# Validation Tests
# =============================================================================


class TestEventTypeValidation:
    """Tests for event type constants and validation."""

    def test_event_types_is_frozenset(self):
        """EVENT_TYPES should be immutable."""
        assert isinstance(EVENT_TYPES, frozenset)

    def test_event_types_contains_all_expected_types(self):
        """EVENT_TYPES should contain all defined event types."""
        expected = {
            "new_judgment",
            "job_found",
            "asset_found",
            "offer_made",
            "offer_accepted",
            "packet_sent",
        }
        assert EVENT_TYPES == expected


# =============================================================================
# EventDTO Tests
# =============================================================================


class TestEventDTO:
    """Tests for EventDTO Pydantic model."""

    def test_event_dto_creation(self):
        """EventDTO should be creatable with valid data."""
        now = datetime.now(timezone.utc)
        dto = EventDTO(
            id=str(SAMPLE_EVENT_ID),
            event_type="new_judgment",
            created_at=now,
            payload={"amount": "5000"},
        )

        assert dto.id == str(SAMPLE_EVENT_ID)
        assert dto.event_type == "new_judgment"
        assert dto.created_at == now
        assert dto.payload == {"amount": "5000"}

    def test_event_dto_default_payload(self):
        """EventDTO should default to empty payload."""
        now = datetime.now(timezone.utc)
        dto = EventDTO(
            id=str(SAMPLE_EVENT_ID),
            event_type="job_found",
            created_at=now,
        )

        assert dto.payload == {}
