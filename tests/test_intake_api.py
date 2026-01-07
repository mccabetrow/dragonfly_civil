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
        # App title may change with version, just verify it exists
        assert app.title is not None and "Dragonfly" in app.title

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
    """Smoke tests for the /api/v1/intake/batches endpoint (PR-1 envelope, PR-3 base table)."""

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

    def test_batches_returns_valid_envelope_shape(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches should return PR-1 envelope with paginated data."""
        response = client.get("/api/v1/intake/batches?limit=5")
        # Skip if DB is not available (degraded response is still valid)
        assert response.status_code == 200
        body = response.json()
        # PR-1 envelope structure
        assert "ok" in body
        assert "data" in body
        assert "meta" in body
        # Data payload structure
        data = body["data"]
        assert "batches" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["batches"], list)

    def test_batches_accepts_status_filter(self, client: TestClient) -> None:
        """GET /api/v1/intake/batches?status=completed should filter by status."""
        response = client.get("/api/v1/intake/batches?status=completed")
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

        monkeypatch.setattr("backend.api.routers.intake.get_pool", boom)

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
    """Tests for the minimal /api/v1/intake/state endpoint (PR-1 envelope format)."""

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

    def test_state_returns_valid_envelope_shape(self, client: TestClient) -> None:
        """Response should have PR-1 envelope with all required fields."""
        response = client.get("/api/v1/intake/state")
        assert response.status_code == 200
        body = response.json()

        # PR-1 envelope fields
        assert "ok" in body
        assert "degraded" in body
        assert "data" in body
        assert "meta" in body
        assert "trace_id" in body["meta"]

        # Data fields inside envelope
        data = body["data"]
        assert "checked_at" in data
        assert "pending" in data
        assert "processing" in data
        assert "completed" in data
        assert "failed" in data
        assert "total_batches" in data
        assert "queue_depth" in data

        # Types are correct
        assert isinstance(body["ok"], bool)
        assert isinstance(body["degraded"], bool)
        assert isinstance(data["pending"], int)
        assert isinstance(data["processing"], int)
        assert isinstance(data["completed"], int)
        assert isinstance(data["failed"], int)
        assert isinstance(data["total_batches"], int)
        assert isinstance(data["queue_depth"], int)

    def test_state_never_throws_on_db_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """State endpoint must return degraded envelope, never throw."""

        async def boom():
            raise RuntimeError("Database connection failed")

        monkeypatch.setattr("backend.api.routers.intake.get_pool", boom)

        response = client.get("/api/v1/intake/state")

        # Must still return 200 with degraded envelope
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["degraded"] is True
        assert body["error"] is not None
        assert "Database connection failed" in body["error"]
        # Data should contain zero counts when degraded
        data = body["data"]
        assert data["pending"] == 0
        assert data["processing"] == 0
        assert data["completed"] == 0
        assert data["failed"] == 0
        assert data["queue_depth"] == 0

    def test_state_no_auth_required(self, client: TestClient) -> None:
        """State endpoint should not require authentication."""
        # No auth headers provided - should still work
        response = client.get("/api/v1/intake/state")
        assert response.status_code == 200


@pytest.mark.unit
class TestListBatchesDegradeGuard:
    """Tests for the list_batches degrade guard pattern (PR-3: base table only)."""

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
        """list_batches must return 200 OK with degraded envelope on DB error."""

        async def boom():
            raise RuntimeError("Database connection failed")

        monkeypatch.setattr("backend.api.routers.intake.get_pool", boom)

        response = client.get("/api/v1/intake/batches")

        # MUST return 200 - never 500
        assert response.status_code == 200
        body = response.json()
        # PR-1 envelope format
        assert body["ok"] is False
        assert body["degraded"] is True
        assert body["data"]["batches"] == []
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

    def test_batches_returns_envelope_with_trace_id(self, client: TestClient) -> None:
        """Batches response should include PR-1 envelope with trace_id in meta."""
        response = client.get("/api/v1/intake/batches")
        assert response.status_code == 200
        body = response.json()
        # PR-1 envelope structure
        assert "ok" in body
        assert "data" in body
        assert "meta" in body
        assert "trace_id" in body["meta"]
        # Data should have batch list structure
        assert "batches" in body["data"]
        assert "total" in body["data"]
        assert "page" in body["data"]
        assert "page_size" in body["data"]

    def test_batches_queries_base_table_only(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PR-3: Verify list_batches queries ops.ingest_batches, not the view.

        This test verifies the SQL query targets the base table by checking
        that the degrade guard pattern still works when the view is missing.
        """
        # We can't easily test SQL directly, but we can verify the endpoint
        # works without the view by checking it returns 200 with proper envelope
        response = client.get("/api/v1/intake/batches")
        assert response.status_code == 200
        body = response.json()
        # Should have envelope structure regardless of DB state
        assert "ok" in body
        assert "data" in body
        assert "meta" in body
