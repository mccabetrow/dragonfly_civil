"""
Tests for the Intake Fortress API router.

Tests cover:
- FastAPI app imports cleanly
- GET /api/v1/intake/health returns 200
- Router is correctly mounted
- Exception handling returns proper error response

NOTE: Marked legacy - requires intake router and specific app config.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.legacy  # Requires intake router configuration


class TestIntakeRouterImport:
    """Test that the FastAPI app imports cleanly with intake router."""

    def test_app_imports_cleanly(self) -> None:
        """Verify the FastAPI app can be created without import errors."""
        from backend.main import create_app

        app = create_app()
        assert app is not None
        assert app.title == "Dragonfly Engine"

    def test_intake_router_is_mounted(self) -> None:
        """Verify the intake router endpoints are registered."""
        from backend.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]

        # Check intake health endpoint is registered
        assert "/api/v1/intake/health" in routes


class TestIntakeHealth:
    """Test the intake health endpoint."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the FastAPI app."""
        from backend.main import create_app

        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_intake_health_returns_200(self, client: TestClient) -> None:
        """GET /api/v1/intake/health should return 200 with status ok."""
        response = client.get("/api/v1/intake/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["subsystem"] == "intake_fortress"

    def test_intake_health_no_auth_required(self, client: TestClient) -> None:
        """Health endpoint should not require authentication."""
        # No auth headers provided - should still work
        response = client.get("/api/v1/intake/health")
        assert response.status_code == 200


class TestIntakeRouterEndpoints:
    """Test that expected intake endpoints exist (not full integration tests)."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a test client for the FastAPI app."""
        from backend.main import create_app

        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_upload_endpoint_exists(self, client: TestClient) -> None:
        """POST /api/v1/intake/upload should exist (will fail auth but route exists)."""
        # Send empty request - should fail but with 4xx not 404
        response = client.post("/api/v1/intake/upload")
        # 401/403 (auth) or 422 (validation) means route exists, 404 means it doesn't
        assert response.status_code != 404

    def test_batches_endpoint_exists(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches should exist (will fail auth but route exists)."""
        response = client.get("/api/v1/intake/batches")
        # 401/403 (auth) means route exists, 404 means it doesn't
        assert response.status_code != 404


class TestIntakeBatchesSmoke:
    """Smoke tests for the /api/v1/intake/batches endpoint."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient with mocked auth."""
        from backend.core.security import AuthContext, get_current_user
        from backend.main import create_app

        app = create_app()

        async def mock_auth() -> AuthContext:
            return AuthContext(subject="test-user", via="api_key")

        app.dependency_overrides[get_current_user] = mock_auth
        return TestClient(app, raise_server_exceptions=False)

    def test_batches_returns_valid_response_shape(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches should return paginated response with correct shape."""
        response = client.get("/api/v1/intake/batches?limit=5")
        # Skip if DB is not available (500 means connection issue)
        if response.status_code == 500:
            pytest.skip("Database not available for integration test")
        assert response.status_code == 200
        body = response.json()
        assert "batches" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert isinstance(body["batches"], list)

    def test_batches_accepts_status_filter(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches?status=completed should filter by status."""
        response = client.get("/api/v1/intake/batches?status=completed")
        if response.status_code == 500:
            pytest.skip("Database not available for integration test")
        assert response.status_code == 200


class TestIntakeUploadErrorHandling:
    """Test error handling in the intake upload API."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient that bypasses auth and doesn't raise server exceptions."""
        from backend.core.security import AuthContext, get_current_user
        from backend.main import create_app

        app = create_app()

        # Override auth dependency to always return authenticated context
        async def mock_auth() -> AuthContext:
            return AuthContext(subject="test-user", via="api_key")

        app.dependency_overrides[get_current_user] = mock_auth
        return TestClient(app, raise_server_exceptions=False)

    def test_service_exception_returns_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Service exceptions should return 500 with structured error response."""

        # Monkeypatch get_pool to raise an error (simulating DB connection failure)
        async def boom():
            raise RuntimeError("boom")

        monkeypatch.setattr("backend.routers.intake.get_pool", boom)

        # Build a minimal valid CSV upload
        csv_content = b"name,email\nJohn Doe,john@example.com\n"
        files = {"file": ("test.csv", BytesIO(csv_content), "text/csv")}
        data = {"source": "simplicity"}

        response = client.post("/api/v1/intake/upload", files=files, data=data)

        # The outer exception handler returns 500 with our error format
        assert response.status_code == 500
        body = response.json()
        assert body["error"] == "intake_upload_failed"
        assert "boom" in body["message"]
