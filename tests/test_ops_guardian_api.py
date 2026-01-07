"""
Tests for the Ops Guardian API router.

Tests cover:
- POST /api/v1/ops/guardian/run returns 200
- Response contains checked/marked_failed counters
- GET /api/v1/ops/guardian/status returns configuration
- Endpoints require authentication
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.core.security import AuthContext
from backend.services.intake_guardian import GuardianResult


class TestOpsGuardianRouterImport:
    """Test that the router imports and mounts correctly."""

    def test_router_is_mounted(self) -> None:
        """Verify the ops guardian router endpoints are registered."""
        from backend.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]

        assert "/api/v1/ops/guardian/run" in routes
        assert "/api/v1/ops/guardian/status" in routes


class TestOpsGuardianRunEndpoint:
    """Tests for the /run endpoint."""

    @pytest.fixture
    def auth_client(self) -> TestClient:
        """Create a test client with auth bypassed."""
        from backend.core.security import get_current_user
        from backend.main import create_app

        app = create_app()

        # Override auth to allow requests
        async def mock_auth() -> AuthContext:
            return AuthContext(subject="test-user", via="api_key")

        app.dependency_overrides[get_current_user] = mock_auth

        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture
    def unauth_client(self) -> TestClient:
        """Create a test client without auth."""
        from backend.main import create_app

        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_run_endpoint_exists(self, unauth_client: TestClient) -> None:
        """POST /api/v1/ops/guardian/run should exist (will fail auth)."""
        response = unauth_client.post("/api/v1/ops/guardian/run")
        # 401 means route exists but auth failed, 404 means route doesn't exist
        assert response.status_code == 401

    def test_run_endpoint_requires_auth(self, unauth_client: TestClient) -> None:
        """POST /api/v1/ops/guardian/run should require authentication."""
        response = unauth_client.post("/api/v1/ops/guardian/run")
        assert response.status_code == 401

    def test_run_returns_200_with_counters(self, auth_client: TestClient) -> None:
        """POST /api/v1/ops/guardian/run should return 200 with counters."""
        mock_result = GuardianResult(checked=3, marked_failed=1, errors=[])

        with patch("backend.api.routers.ops_guardian.get_intake_guardian") as mock_get_guardian:
            mock_guardian = AsyncMock()
            mock_guardian.check_stuck_batches.return_value = mock_result
            mock_get_guardian.return_value = mock_guardian

            response = auth_client.post("/api/v1/ops/guardian/run")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["checked"] == 3
        assert data["marked_failed"] == 1
        assert data["errors"] == []

    def test_run_returns_errors_in_response(self, auth_client: TestClient) -> None:
        """POST /api/v1/ops/guardian/run should include errors if any."""
        mock_result = GuardianResult(
            checked=2,
            marked_failed=0,
            errors=["Failed to connect to Discord"],
        )

        with patch("backend.api.routers.ops_guardian.get_intake_guardian") as mock_get_guardian:
            mock_guardian = AsyncMock()
            mock_guardian.check_stuck_batches.return_value = mock_result
            mock_get_guardian.return_value = mock_guardian

            response = auth_client.post("/api/v1/ops/guardian/run")

        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) == 1
        assert "Discord" in data["errors"][0]


class TestOpsGuardianStatusEndpoint:
    """Tests for the /status endpoint."""

    @pytest.fixture
    def auth_client(self) -> TestClient:
        """Create a test client with auth bypassed."""
        from backend.core.security import get_current_user
        from backend.main import create_app

        app = create_app()

        async def mock_auth() -> AuthContext:
            return AuthContext(subject="test-user", via="api_key")

        app.dependency_overrides[get_current_user] = mock_auth

        return TestClient(app, raise_server_exceptions=False)

    def test_status_returns_configuration(self, auth_client: TestClient) -> None:
        """GET /api/v1/ops/guardian/status should return guardian config."""
        response = auth_client.get("/api/v1/ops/guardian/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "stale_minutes" in data
        assert "max_retries" in data
        assert isinstance(data["stale_minutes"], int)
        assert isinstance(data["max_retries"], int)
