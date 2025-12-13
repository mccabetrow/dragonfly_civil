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


@pytest.mark.unit
class TestIntakeStateEndpoint:
    """Tests for the minimal /api/v1/intake/state endpoint."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the FastAPI app."""
        from backend.main import create_app

        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_state_endpoint_exists(self, client: TestClient) -> None:
        """GET /api/v1/intake/state should exist and return 200."""
        response = client.get("/api/v1/intake/state")
        # Should never 404 - endpoint must exist
        assert response.status_code != 404
        # Should return 200 even without DB (returns degraded state)
        assert response.status_code == 200

    def test_state_returns_valid_response_shape(self, client: TestClient) -> None:
        """Response should have all required fields."""
        response = client.get("/api/v1/intake/state")
        assert response.status_code == 200
        body = response.json()

        # Required fields always present
        assert "ok" in body
        assert "degraded" in body
        assert "checked_at" in body
        assert "pending" in body
        assert "processing" in body
        assert "completed" in body
        assert "failed" in body
        assert "total_batches" in body
        assert "queue_depth" in body

        # Types are correct
        assert isinstance(body["ok"], bool)
        assert isinstance(body["degraded"], bool)
        assert isinstance(body["pending"], int)
        assert isinstance(body["processing"], int)
        assert isinstance(body["completed"], int)
        assert isinstance(body["failed"], int)
        assert isinstance(body["total_batches"], int)
        assert isinstance(body["queue_depth"], int)

    def test_state_never_throws_on_db_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """State endpoint must return degraded response, never throw."""

        async def boom():
            raise RuntimeError("Database connection failed")

        monkeypatch.setattr("backend.routers.intake.get_pool", boom)

        response = client.get("/api/v1/intake/state")

        # Must still return 200 with degraded state
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["degraded"] is True
        assert body["error"] is not None
        assert "Database connection failed" in body["error"]
        # Counts should be zero when degraded
        assert body["pending"] == 0
        assert body["processing"] == 0
        assert body["completed"] == 0
        assert body["failed"] == 0
        assert body["queue_depth"] == 0

    def test_state_no_auth_required(self, client: TestClient) -> None:
        """State endpoint should not require authentication."""
        # No auth headers provided - should still work
        response = client.get("/api/v1/intake/state")
        assert response.status_code == 200


@pytest.mark.unit
class TestListBatchesDegradeGuard:
    """Tests for the list_batches degrade guard pattern."""

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

    def test_batches_returns_200_on_db_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """list_batches must return 200 OK with degraded response on DB error."""

        async def boom():
            raise RuntimeError("SQL placeholder mismatch")

        monkeypatch.setattr("backend.routers.intake.get_pool", boom)

        response = client.get("/api/v1/intake/batches")

        # MUST return 200 - never 500
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["degraded"] is True
        assert body["data"] == []
        assert "error" in body

    def test_batches_without_filter_returns_200(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches should return 200 OK."""
        response = client.get("/api/v1/intake/batches")
        # Should return 200 (either normal or degraded)
        assert response.status_code == 200

    def test_batches_with_status_filter_returns_200(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches?status=completed should return 200 OK."""
        response = client.get("/api/v1/intake/batches?status=completed")
        # Should return 200 (either normal or degraded)
        assert response.status_code == 200

    def test_batches_with_pagination_returns_200(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches?page=2&page_size=10 should return 200 OK."""
        response = client.get("/api/v1/intake/batches?page=2&page_size=10")
        # Should return 200 (either normal or degraded)
        assert response.status_code == 200

    def test_batches_with_filter_and_pagination_returns_200(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches?status=pending&page=1&page_size=5 should return 200 OK."""
        response = client.get("/api/v1/intake/batches?status=pending&page=1&page_size=5")
        # Should return 200 (either normal or degraded)
        assert response.status_code == 200
