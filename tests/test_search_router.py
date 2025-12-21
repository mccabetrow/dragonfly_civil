"""
Tests for backend.routers.search

Integration-style tests for the semantic search endpoint with mocked embedding.

NOTE: Marked integration (FastAPI TestClient) + legacy (requires search router).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mark as integration (creates FastAPI app) + legacy (optional config)
pytestmark = [pytest.mark.integration, pytest.mark.legacy]


@pytest.fixture
def mock_embedding() -> list[float]:
    """Standard 1536-dimension mock embedding."""
    return [0.01] * 1536


class TestSemanticSearchEndpoint:
    """Tests for POST /api/v1/search/semantic endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_results_when_embedding_fails(self):
        """Returns empty results when embedding generation fails."""
        from fastapi.testclient import TestClient

        from backend.main import create_app

        app = create_app()

        with patch("backend.routers.search.generate_embedding") as mock_gen:
            mock_gen.return_value = None  # Simulate failure

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/v1/search/semantic",
                    json={"query": "test query", "limit": 5},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_successful_search_returns_results(self, mock_embedding: list[float]):
        """Successfully returns search results with valid embedding."""
        from fastapi.testclient import TestClient

        from backend.main import create_app

        app = create_app()

        # Mock database results as asyncpg-style Record objects
        mock_rows = [
            {
                "id": 1,
                "plaintiff_name": "John Doe",
                "defendant_name": "ABC Corp",
                "judgment_amount": 50000.0,
                "county": "New York",
                "case_number": "2024-CV-001",
                "score": 0.877,
            },
            {
                "id": 2,
                "plaintiff_name": "Jane Smith",
                "defendant_name": "XYZ Inc",
                "judgment_amount": 25000.0,
                "county": "Brooklyn",
                "case_number": "2024-CV-002",
                "score": 0.754,
            },
        ]

        # Create mock Record objects
        mock_records = []
        for row in mock_rows:
            mock_record = MagicMock()
            mock_record.__getitem__ = lambda self, key, r=row: r[key]
            mock_record.get = lambda key, default=None, r=row: r.get(key, default)
            mock_records.append(mock_record)

        with patch("backend.routers.search.generate_embedding") as mock_gen:
            mock_gen.return_value = mock_embedding
            with patch("backend.routers.search.get_connection") as mock_get_conn:
                mock_conn = AsyncMock()
                mock_conn.fetch.return_value = mock_records
                mock_get_conn.return_value.__aenter__.return_value = mock_conn
                mock_get_conn.return_value.__aexit__.return_value = None

                with TestClient(app, raise_server_exceptions=False) as client:
                    response = client.post(
                        "/api/v1/search/semantic",
                        json={"query": "judgment against ABC", "limit": 5},
                    )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 2
        assert data["results"][0]["id"] == 1
        assert data["results"][0]["plaintiff_name"] == "John Doe"
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_list(self, mock_embedding: list[float]):
        """Returns empty results list when no matches found."""
        from fastapi.testclient import TestClient

        from backend.main import create_app

        app = create_app()

        with patch("backend.routers.search.generate_embedding") as mock_gen:
            mock_gen.return_value = mock_embedding
            with patch("backend.routers.search.get_connection") as mock_get_conn:
                mock_conn = AsyncMock()
                mock_conn.fetch.return_value = []
                mock_get_conn.return_value.__aenter__.return_value = mock_conn
                mock_get_conn.return_value.__aexit__.return_value = None

                with TestClient(app, raise_server_exceptions=False) as client:
                    response = client.post(
                        "/api/v1/search/semantic",
                        json={"query": "nonexistent query", "limit": 5},
                    )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 0

    def test_validates_limit_parameter(self):
        """Validates limit parameter is positive integer."""
        from fastapi.testclient import TestClient

        from backend.main import create_app

        app = create_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            # Test negative limit
            response = client.post(
                "/api/v1/search/semantic",
                json={"query": "test", "limit": -1},
            )

        # Pydantic validation should fail
        assert response.status_code == 422

    def test_requires_query_parameter(self):
        """Requires query parameter in request body."""
        from fastapi.testclient import TestClient

        from backend.main import create_app

        app = create_app()

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/api/v1/search/semantic",
                json={"limit": 5},  # Missing query
            )

        assert response.status_code == 422


class TestSearchRequestModel:
    """Tests for SemanticSearchRequest model validation."""

    def test_default_limit(self):
        """Default limit is 5."""
        from backend.routers.search import SemanticSearchRequest

        request = SemanticSearchRequest(query="test")
        assert request.limit == 5

    def test_custom_limit(self):
        """Accepts custom limit."""
        from backend.routers.search import SemanticSearchRequest

        request = SemanticSearchRequest(query="test", limit=10)
        assert request.limit == 10


class TestJudgmentSearchResultModel:
    """Tests for JudgmentSearchResult model."""

    def test_creates_result_from_db_row(self):
        """Creates result model from database row data."""
        from backend.routers.search import JudgmentSearchResult

        result = JudgmentSearchResult(
            id=1,
            plaintiff_name="John Doe",
            defendant_name="ABC Corp",
            judgment_amount=50000.0,
            county="New York",
            case_number="2024-CV-001",
            score=0.877,
        )

        assert result.id == 1
        assert result.plaintiff_name == "John Doe"
        assert result.defendant_name == "ABC Corp"
        assert result.judgment_amount == 50000.0
        assert result.county == "New York"
        assert result.score == 0.877

    def test_handles_optional_fields(self):
        """Handles optional/nullable fields."""
        from backend.routers.search import JudgmentSearchResult

        result = JudgmentSearchResult(
            id=1,
            plaintiff_name=None,
            defendant_name=None,
            judgment_amount=None,
            county=None,
            case_number=None,
            score=0.5,
        )

        assert result.id == 1
        assert result.plaintiff_name is None
