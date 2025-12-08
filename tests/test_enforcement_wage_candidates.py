"""
Tests for the Enforcement Wage Candidates API endpoint.

Tests cover:
- GET /api/v1/enforcement/wage-candidates returns paginated response
- Endpoint requires authentication
- Query parameters work correctly
- Response model validates
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestWageCandidatesEndpointExists:
    """Test that the wage candidates endpoint is properly registered."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the FastAPI app."""
        from backend.main import create_app

        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_wage_candidates_endpoint_exists(self, client: TestClient) -> None:
        """GET /api/v1/enforcement/wage-candidates should exist."""
        response = client.get("/api/v1/enforcement/wage-candidates")
        # 401/403 (auth) means route exists, 404 means it doesn't
        assert response.status_code != 404, "Endpoint should be registered"

    def test_wage_candidates_requires_auth(self, client: TestClient) -> None:
        """Wage candidates endpoint should require authentication."""
        response = client.get("/api/v1/enforcement/wage-candidates")
        # Should get 401 or 403 without auth
        assert response.status_code in [401, 403]


class TestWageCandidatesWithAuth:
    """Test wage candidates endpoint with mocked authentication."""

    @pytest.fixture
    def auth_client(self) -> TestClient:
        """Create a TestClient with mocked auth."""
        from backend.core.security import AuthContext, get_current_user
        from backend.main import create_app

        app = create_app()

        # Mock auth to always succeed
        mock_auth = AuthContext(
            subject="test-user",
            via="api_key",
        )
        app.dependency_overrides[get_current_user] = lambda: mock_auth

        return TestClient(app, raise_server_exceptions=False)

    def test_wage_candidates_returns_paginated_response(self, auth_client: TestClient) -> None:
        """Authenticated request should return paginated response structure."""
        # Mock the Supabase client to return empty results
        mock_result = MagicMock()
        mock_result.data = []
        mock_result.count = 0

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.ilike.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_schema = MagicMock()
        mock_schema.from_.return_value = mock_query

        mock_client = MagicMock()
        mock_client.schema.return_value = mock_schema

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_client,
        ):
            response = auth_client.get("/api/v1/enforcement/wage-candidates")

        assert response.status_code == 200
        data = response.json()

        # Check paginated response structure
        assert "candidates" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "has_more" in data

        assert isinstance(data["candidates"], list)
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 50
        assert data["has_more"] is False

    def test_wage_candidates_pagination_params(self, auth_client: TestClient) -> None:
        """Pagination parameters should be applied correctly."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_result.count = 100  # Simulate 100 total records

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.ilike.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_schema = MagicMock()
        mock_schema.from_.return_value = mock_query

        mock_client = MagicMock()
        mock_client.schema.return_value = mock_schema

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_client,
        ):
            response = auth_client.get(
                "/api/v1/enforcement/wage-candidates",
                params={"page": 2, "page_size": 25},
            )

        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 2
        assert data["page_size"] == 25
        assert data["total"] == 100
        assert data["has_more"] is True  # page 2 of 4 (100 / 25)

    def test_wage_candidates_with_mock_data(self, auth_client: TestClient) -> None:
        """Test with mock candidate data to verify response mapping."""
        mock_candidate = {
            "plaintiff_id": "11111111-1111-1111-1111-111111111111",
            "case_number": "2024-CV-12345",
            "defendant_name": "John Doe",
            "employer_name": "Acme Corp",
            "employer_address": "123 Main St, New York, NY",
            "balance": 15000.00,
            "jurisdiction": "Queens",
            "priority_score": 85.0,
            "judgment_id": "22222222-2222-2222-2222-222222222222",
            "plaintiff_name": "ABC Collections",
            "plaintiff_tier": "A",
            "judgment_date": "2024-01-15",
            "collectability_score": 75,
            "income_band": "$75k-100k",
            "intel_source": "lexisnexis",
            "intel_confidence": 90.0,
            "intel_verified": True,
            "enforcement_stage": "pre_enforcement",
            "status": "unsatisfied",
            "created_at": "2024-01-01T00:00:00Z",
        }

        mock_result = MagicMock()
        mock_result.data = [mock_candidate]
        mock_result.count = 1

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.ilike.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_schema = MagicMock()
        mock_schema.from_.return_value = mock_query

        mock_client = MagicMock()
        mock_client.schema.return_value = mock_schema

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_client,
        ):
            response = auth_client.get("/api/v1/enforcement/wage-candidates")

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 1
        assert len(data["candidates"]) == 1

        candidate = data["candidates"][0]
        assert candidate["case_number"] == "2024-CV-12345"
        assert candidate["employer_name"] == "Acme Corp"
        assert candidate["balance"] == 15000.00
        assert candidate["jurisdiction"] == "Queens"
        assert candidate["priority_score"] == 85.0
        assert candidate["intel_verified"] is True

    def test_wage_candidates_filters(self, auth_client: TestClient) -> None:
        """Test that filter parameters are passed to the query."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_result.count = 0

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.ilike.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.range.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_schema = MagicMock()
        mock_schema.from_.return_value = mock_query

        mock_client = MagicMock()
        mock_client.schema.return_value = mock_schema

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_client,
        ):
            response = auth_client.get(
                "/api/v1/enforcement/wage-candidates",
                params={
                    "min_balance": 5000,
                    "min_priority": 50,
                    "jurisdiction": "Queens",
                    "verified_only": True,
                },
            )

        assert response.status_code == 200

        # Verify filters were applied
        mock_query.gte.assert_any_call("balance", 5000)
        mock_query.gte.assert_any_call("priority_score", 50)
        mock_query.ilike.assert_called_once_with("jurisdiction", "%Queens%")
        mock_query.eq.assert_called_once_with("intel_verified", True)


class TestWageCandidatesErrorHandling:
    """Test error handling for wage candidates endpoint."""

    @pytest.fixture
    def auth_client(self) -> TestClient:
        """Create a TestClient with mocked auth."""
        from backend.core.security import AuthContext, get_current_user
        from backend.main import create_app

        app = create_app()

        mock_auth = AuthContext(
            subject="test-user",
            via="api_key",
        )
        app.dependency_overrides[get_current_user] = lambda: mock_auth

        return TestClient(app, raise_server_exceptions=False)

    def test_wage_candidates_handles_db_error(self, auth_client: TestClient) -> None:
        """Database errors should return 500 with error detail."""
        mock_client = MagicMock()
        mock_client.schema.side_effect = Exception("Database connection failed")

        with patch(
            "backend.routers.enforcement.get_supabase_client",
            return_value=mock_client,
        ):
            response = auth_client.get("/api/v1/enforcement/wage-candidates")

        assert response.status_code == 500
        data = response.json()
        # Middleware wraps errors in 'message' field
        assert "message" in data or "detail" in data
        error_msg = data.get("message") or data.get("detail", "")
        assert "Failed to query wage candidates" in error_msg

    def test_wage_candidates_invalid_page_param(self, auth_client: TestClient) -> None:
        """Invalid page parameter should return 422."""
        response = auth_client.get(
            "/api/v1/enforcement/wage-candidates",
            params={"page": 0},  # Invalid: must be >= 1
        )
        assert response.status_code == 422

    def test_wage_candidates_invalid_page_size_param(self, auth_client: TestClient) -> None:
        """Invalid page_size parameter should return 422."""
        response = auth_client.get(
            "/api/v1/enforcement/wage-candidates",
            params={"page_size": 500},  # Invalid: max 200
        )
        assert response.status_code == 422
