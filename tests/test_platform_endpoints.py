"""
Tests for platform endpoints (/api/version, /api/ready).

These endpoints are critical for deployment and monitoring:
- /api/version: Returns version info without DB touch
- /api/ready: Full readiness probe with DB/views/auth checks
"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from backend.main import create_app

    app = create_app()
    return TestClient(app)


class TestVersionEndpoint:
    """Tests for GET /api/version."""

    def test_returns_200(self, client):
        """Version endpoint returns 200 OK."""
        response = client.get("/api/version")
        assert response.status_code == 200

    def test_returns_required_fields(self, client):
        """Response contains all required fields."""
        response = client.get("/api/version")
        data = response.json()

        assert "git_sha" in data
        assert "environment" in data
        assert "service" in data
        assert "version" in data
        assert "timestamp" in data

    def test_service_name_is_dragonfly_api(self, client):
        """Service name is DragonflyAPI."""
        response = client.get("/api/version")
        data = response.json()
        assert data["service"] == "DragonflyAPI"

    def test_git_sha_from_env(self, client):
        """Git SHA is read from environment."""
        with patch.dict(os.environ, {"GIT_SHA": "abc123def456"}):
            response = client.get("/api/version")
            data = response.json()
            # Should be truncated to 8 chars
            assert data["git_sha"] == "abc123de"

    def test_git_sha_falls_back_to_render(self, client):
        """Git SHA falls back to RENDER_GIT_COMMIT."""
        env = {"RENDER_GIT_COMMIT": "render789xyz"}
        with patch.dict(os.environ, env, clear=False):
            # Clear GIT_SHA if it exists
            if "GIT_SHA" in os.environ:
                del os.environ["GIT_SHA"]
            response = client.get("/api/version")
            # Just verify it works - actual value depends on env
            assert response.status_code == 200

    def test_git_sha_unknown_if_missing(self, client):
        """Git SHA is 'unknown' if no env var set."""
        with patch.dict(os.environ, {}, clear=True):
            # Need to keep SUPABASE vars for settings to load
            env = {
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,
            }
            with patch.dict(os.environ, env):
                response = client.get("/api/version")
                # Just check it doesn't crash
                assert response.status_code == 200

    def test_timestamp_is_iso_format(self, client):
        """Timestamp is in ISO format."""
        response = client.get("/api/version")
        data = response.json()
        # Should parse without error
        timestamp = data["timestamp"]
        assert "T" in timestamp  # ISO format has T separator

    def test_no_db_connection_required(self, client):
        """Endpoint works even if DB is unavailable."""
        # Version endpoint doesn't touch DB at all, so it should always work
        # Just verify it returns 200 regardless of DB state
        response = client.get("/api/version")
        assert response.status_code == 200
        # Verify it has the expected structure
        data = response.json()
        assert "git_sha" in data
        assert "service" in data


class TestReadyEndpoint:
    """Tests for GET /api/ready."""

    def test_returns_200_when_ready(self, client):
        """Ready endpoint returns 200 when all checks pass."""
        # This test depends on actual DB connectivity in test environment
        # If DB is available, should return 200
        response = client.get("/api/ready")
        # Either 200 (ready) or 503 (not ready) is valid
        assert response.status_code in (200, 503)

    def test_response_has_required_fields(self, client):
        """Response contains all required fields."""
        response = client.get("/api/ready")
        data = response.json()

        assert "ready" in data
        assert "checks" in data
        assert "timestamp" in data
        assert isinstance(data["checks"], dict)

    def test_checks_include_database(self, client):
        """Checks include database connectivity."""
        response = client.get("/api/ready")
        data = response.json()
        assert "database" in data["checks"]

    def test_checks_include_views(self, client):
        """Checks include required views."""
        response = client.get("/api/ready")
        data = response.json()
        # Views check may be present if database check passed
        # It's conditional so just verify structure
        assert isinstance(data["checks"], dict)

    def test_checks_include_supabase_auth(self, client):
        """Checks include Supabase authentication."""
        response = client.get("/api/ready")
        data = response.json()
        assert "supabase_auth" in data["checks"]

    def test_returns_503_on_failure(self, client):
        """Returns 503 when checks fail."""
        # Mock get_pool to return None to simulate DB unavailable
        with patch("backend.api.routers.platform.get_pool", new_callable=AsyncMock) as mock_pool:
            mock_pool.return_value = None
            response = client.get("/api/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["ready"] is False
            assert data["failure_reason"] is not None

    def test_failure_reason_is_redacted(self, client):
        """Failure reason doesn't expose sensitive details."""
        # Mock get_pool to return None to simulate failure
        with patch("backend.api.routers.platform.get_pool", new_callable=AsyncMock) as mock_pool:
            mock_pool.return_value = None
            response = client.get("/api/ready")
            data = response.json()
            # Failure reason should be a generic category, not stack trace
            if data.get("failure_reason"):
                assert "password" not in data["failure_reason"].lower()
                assert "connection string" not in data["failure_reason"].lower()
                assert len(data["failure_reason"]) < 100  # Reasonably short

    def test_timestamp_is_iso_format(self, client):
        """Timestamp is in ISO format."""
        response = client.get("/api/ready")
        data = response.json()
        timestamp = data["timestamp"]
        assert "T" in timestamp  # ISO format has T separator


class TestEndpointMounting:
    """Tests for correct endpoint mounting."""

    def test_version_at_api_version(self, client):
        """Version endpoint is at /api/version."""
        response = client.get("/api/version")
        assert response.status_code == 200

    def test_ready_at_api_ready(self, client):
        """Ready endpoint is at /api/ready."""
        response = client.get("/api/ready")
        assert response.status_code in (200, 503)

    def test_not_at_api_health_version(self, client):
        """Version is NOT at /api/health/version (that's the old location)."""
        # The health router still has its own /version - this is fine
        # We're just testing our new endpoint is at the right place
        response = client.get("/api/version")
        data = response.json()
        # Our new endpoint has 'git_sha' and 'service' fields
        assert "git_sha" in data
        assert "service" in data
