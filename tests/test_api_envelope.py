"""
Tests for API Response Envelope (PR-1)

Verifies that:
1. ApiResponse envelope has correct structure
2. Health endpoint returns envelope with trace_id
3. Intake state endpoint returns envelope with trace_id
4. Intake batches endpoint returns envelope (degraded on error)
5. Trace ID middleware works correctly
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api import ApiResponse, ResponseMeta, api_response, degraded_response
from backend.core.trace_middleware import get_trace_id, set_trace_id


class TestApiResponseModel:
    """Test ApiResponse Pydantic model."""

    def test_success_response_structure(self):
        """ApiResponse should have ok, data, degraded, error, meta fields."""
        meta = ResponseMeta(trace_id="test-123")
        response = ApiResponse(
            ok=True,
            data={"foo": "bar"},
            degraded=False,
            error=None,
            meta=meta,
        )

        assert response.ok is True
        assert response.data == {"foo": "bar"}
        assert response.degraded is False
        assert response.error is None
        assert response.meta.trace_id == "test-123"
        assert response.meta.timestamp is not None

    def test_degraded_response_structure(self):
        """Degraded response should have ok=False, degraded=True."""
        meta = ResponseMeta(trace_id="trace-456")
        response = ApiResponse(
            ok=False,
            data=[],
            degraded=True,
            error="Database timeout",
            meta=meta,
        )

        assert response.ok is False
        assert response.data == []
        assert response.degraded is True
        assert response.error == "Database timeout"
        assert response.meta.trace_id == "trace-456"

    def test_response_meta_timestamp_auto_generated(self):
        """ResponseMeta should auto-generate timestamp if not provided."""
        meta = ResponseMeta(trace_id="auto-ts")
        assert meta.timestamp is not None
        # Should be ISO 8601 format
        datetime.fromisoformat(meta.timestamp.replace("Z", "+00:00"))

    def test_api_response_json_serialization(self):
        """ApiResponse should serialize to JSON correctly."""
        meta = ResponseMeta(trace_id="json-test")
        response = ApiResponse(
            ok=True,
            data={"count": 42},
            meta=meta,
        )

        json_dict = response.model_dump()
        assert json_dict["ok"] is True
        assert json_dict["data"]["count"] == 42
        assert json_dict["meta"]["trace_id"] == "json-test"
        assert "timestamp" in json_dict["meta"]


class TestApiResponseHelpers:
    """Test api_response() and degraded_response() helper functions."""

    def test_api_response_success(self):
        """api_response() should create success envelope."""
        # Set trace ID for context
        set_trace_id("helper-test-1")

        response = api_response(data={"items": [1, 2, 3]})

        assert response.ok is True
        assert response.data == {"items": [1, 2, 3]}
        assert response.degraded is False
        assert response.error is None
        assert response.meta.trace_id == "helper-test-1"

    def test_api_response_with_error(self):
        """api_response() should allow setting error flag."""
        set_trace_id("helper-test-2")

        response = api_response(data=None, ok=False, error="Not found")

        assert response.ok is False
        assert response.data is None
        assert response.error == "Not found"

    def test_degraded_response_helper(self):
        """degraded_response() should create degraded envelope."""
        set_trace_id("degrade-test")

        response = degraded_response(error="Connection timeout", data=[])

        assert response.ok is False
        assert response.degraded is True
        assert response.error == "Connection timeout"
        assert response.data == []
        assert response.meta.trace_id == "degrade-test"

    def test_degraded_response_truncates_long_errors(self):
        """degraded_response() should truncate very long error messages."""
        set_trace_id("truncate-test")

        long_error = "x" * 1000
        response = degraded_response(error=long_error, data=None)

        assert len(response.error) <= 500
        assert response.error == "x" * 500


class TestTraceMiddleware:
    """Test trace ID middleware functionality."""

    def test_get_trace_id_default(self):
        """get_trace_id() should return 'no-trace' when not in request context."""
        # Reset context
        set_trace_id("no-trace")
        assert get_trace_id() == "no-trace"

    def test_set_and_get_trace_id(self):
        """set_trace_id() should set trace ID retrievable by get_trace_id()."""
        set_trace_id("custom-trace-abc")
        assert get_trace_id() == "custom-trace-abc"


class TestHealthEndpointEnvelope:
    """Test health endpoint returns API envelope."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from backend.main import app

        return TestClient(app)

    def test_health_returns_envelope(self, client):
        """GET /api/health should return ApiResponse envelope."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()

        # Check envelope structure
        assert "ok" in data
        assert "data" in data
        assert "meta" in data
        assert "trace_id" in data["meta"]
        assert "timestamp" in data["meta"]

        # Check success values
        assert data["ok"] is True
        assert data["degraded"] is False
        assert data["error"] is None

        # Check data payload
        assert data["data"]["status"] == "ok"
        assert "timestamp" in data["data"]
        assert "environment" in data["data"]

    def test_health_response_has_trace_id_header(self, client):
        """Health response should include X-Trace-ID header."""
        response = client.get("/api/health")

        assert "X-Trace-ID" in response.headers
        trace_id = response.headers["X-Trace-ID"]

        # Trace ID should be a valid UUID
        try:
            uuid.UUID(trace_id)
        except ValueError:
            pytest.fail(f"X-Trace-ID header is not a valid UUID: {trace_id}")

    def test_health_trace_id_matches_body(self, client):
        """X-Trace-ID header should match meta.trace_id in body."""
        response = client.get("/api/health")

        header_trace_id = response.headers["X-Trace-ID"]
        body_trace_id = response.json()["meta"]["trace_id"]

        assert header_trace_id == body_trace_id


class TestIntakeStateEndpointEnvelope:
    """Test intake state endpoint returns API envelope."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from backend.main import app

        return TestClient(app)

    @pytest.fixture
    def mock_db_pool(self):
        """Mock database pool for testing."""
        with patch("backend.api.routers.intake.get_pool") as mock:
            # Create mock connection and cursor
            mock_cursor = AsyncMock()
            mock_cursor.fetchone = AsyncMock(
                return_value=(5, 2, 10, 1, 18, datetime.utcnow())
            )  # pending, processing, completed, failed, total, last_batch_at
            mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
            mock_cursor.__aexit__ = AsyncMock(return_value=None)

            mock_conn = AsyncMock()
            mock_conn.cursor = lambda *args, **kwargs: mock_cursor
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=None)

            mock_pool = AsyncMock()
            mock_pool.connection = lambda: mock_conn
            mock.return_value = mock_pool

            yield mock

    def test_intake_state_returns_envelope(self, client, mock_db_pool):
        """GET /api/v1/intake/state should return ApiResponse envelope."""
        response = client.get("/api/v1/intake/state")

        assert response.status_code == 200
        data = response.json()

        # Check envelope structure
        assert "ok" in data
        assert "data" in data
        assert "meta" in data
        assert "trace_id" in data["meta"]

        # Check data fields exist
        assert "pending" in data["data"]
        assert "processing" in data["data"]
        assert "completed" in data["data"]
        assert "failed" in data["data"]
        assert "total_batches" in data["data"]
        assert "checked_at" in data["data"]

    def test_intake_state_has_trace_id(self, client, mock_db_pool):
        """Intake state response should include trace_id in meta."""
        response = client.get("/api/v1/intake/state")

        data = response.json()
        assert data["meta"]["trace_id"] is not None
        assert len(data["meta"]["trace_id"]) > 0


class TestIntakeBatchesEndpointEnvelope:
    """Test intake batches endpoint returns API envelope with degrade guards."""

    @pytest.fixture
    def client(self):
        """Create test client with mocked auth."""
        from backend.core.security import AuthContext, get_current_user
        from backend.main import app

        # Override auth dependency
        async def mock_auth():
            return AuthContext(subject="test-user", via="api_key")

        app.dependency_overrides[get_current_user] = mock_auth

        yield TestClient(app)

        # Clean up
        app.dependency_overrides.clear()

    def test_batches_returns_envelope_structure(self, client):
        """GET /api/v1/intake/batches should return ApiResponse envelope."""
        # Even if DB fails, should return 200 with degraded envelope
        with patch("backend.api.routers.intake.get_pool") as mock:
            mock.side_effect = Exception("Database unavailable")

            response = client.get("/api/v1/intake/batches")

            # Should NOT be 500 - degrade guard active
            assert response.status_code == 200

            data = response.json()

            # Check envelope structure
            assert "ok" in data
            assert "data" in data
            assert "meta" in data
            assert "trace_id" in data["meta"]

            # Should be degraded
            assert data["ok"] is False
            assert data["degraded"] is True
            assert data["error"] is not None

    def test_batches_degraded_has_trace_id(self, client):
        """Degraded batches response should include trace_id for debugging."""
        with patch("backend.api.routers.intake.get_pool") as mock:
            mock.side_effect = Exception("Connection refused")

            response = client.get("/api/v1/intake/batches")

            data = response.json()

            # Trace ID must be present for debugging
            assert "trace_id" in data["meta"]
            assert len(data["meta"]["trace_id"]) > 0

            # Error should be present
            assert "Connection refused" in data["error"]


class TestEnvelopeConsistency:
    """Test that all endpoints return consistent envelope format."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from backend.main import app

        return TestClient(app)

    def test_all_envelopes_have_required_fields(self, client):
        """All API envelopes should have ok, data, meta.trace_id, meta.timestamp."""
        required_fields = {"ok", "data", "meta"}
        required_meta_fields = {"trace_id", "timestamp"}

        # Test health endpoint
        health_resp = client.get("/api/health")
        health_data = health_resp.json()

        assert required_fields.issubset(health_data.keys()), "Health missing required fields"
        assert required_meta_fields.issubset(
            health_data["meta"].keys()
        ), "Health meta missing fields"

    def test_envelope_degraded_defaults_to_false(self, client):
        """Successful responses should have degraded=False."""
        response = client.get("/api/health")
        data = response.json()

        assert data["degraded"] is False

    def test_envelope_error_defaults_to_none(self, client):
        """Successful responses should have error=None."""
        response = client.get("/api/health")
        data = response.json()

        assert data["error"] is None
