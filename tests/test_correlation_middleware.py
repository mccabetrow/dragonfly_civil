"""
Tests for backend/middleware/correlation.py - Observability Headers.

Verifies the three required headers are present on every response:
- X-Request-ID: UUID correlation ID
- X-Dragonfly-SHA: Git commit SHA (8 chars)
- X-Dragonfly-Env: Environment name

These headers are critical for production observability and debugging.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware.correlation import CorrelationMiddleware, _get_env_name, _get_sha_short


@pytest.fixture
def app_with_middleware() -> FastAPI:
    """Create a minimal FastAPI app with CorrelationMiddleware."""
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(app_with_middleware: FastAPI) -> TestClient:
    """Create a test client for the app."""
    return TestClient(app_with_middleware)


class TestObservabilityHeaders:
    """Tests for the three required observability headers."""

    def test_x_request_id_generated_when_missing(self, client: TestClient):
        """X-Request-ID should be generated if not provided by client."""
        response = client.get("/test")
        assert response.status_code == 200

        # Header must be present
        assert "X-Request-ID" in response.headers
        request_id = response.headers["X-Request-ID"]

        # Must be a valid UUID
        try:
            uuid.UUID(request_id)
        except ValueError:
            pytest.fail(f"X-Request-ID is not a valid UUID: {request_id}")

    def test_x_request_id_preserved_when_provided(self, client: TestClient):
        """X-Request-ID should be preserved if provided by client."""
        client_id = "test-correlation-id-12345"
        response = client.get("/test", headers={"X-Request-ID": client_id})
        assert response.status_code == 200

        # Header must match what was provided
        assert response.headers["X-Request-ID"] == client_id

    def test_x_dragonfly_sha_present(self, client: TestClient):
        """X-Dragonfly-SHA header must be present on every response."""
        response = client.get("/test")
        assert response.status_code == 200

        # Header must be present
        assert "X-Dragonfly-SHA" in response.headers
        sha = response.headers["X-Dragonfly-SHA"]

        # Must be non-empty
        assert sha, "X-Dragonfly-SHA cannot be empty"
        # Should be 8 chars or "local-dev"
        assert len(sha) <= 9, f"SHA should be short (8 chars): {sha}"

    def test_x_dragonfly_env_present(self, client: TestClient):
        """X-Dragonfly-Env header must be present on every response."""
        response = client.get("/test")
        assert response.status_code == 200

        # Header must be present
        assert "X-Dragonfly-Env" in response.headers
        env = response.headers["X-Dragonfly-Env"]

        # Must be non-empty
        assert env, "X-Dragonfly-Env cannot be empty"
        # Must be a known environment
        assert env in {"dev", "staging", "prod", "test"}, f"Unknown env: {env}"

    def test_all_three_headers_present(self, client: TestClient):
        """All three observability headers must be present together."""
        response = client.get("/test")

        required_headers = ["X-Request-ID", "X-Dragonfly-SHA", "X-Dragonfly-Env"]
        for header in required_headers:
            assert header in response.headers, f"Missing required header: {header}"


class TestHelperFunctions:
    """Tests for the SHA and env resolution functions."""

    def test_get_sha_short_returns_string(self):
        """_get_sha_short should return a non-empty string."""
        sha = _get_sha_short()
        assert isinstance(sha, str)
        assert sha, "SHA cannot be empty"

    def test_get_env_name_returns_string(self):
        """_get_env_name should return a known environment string."""
        env = _get_env_name()
        assert isinstance(env, str)
        assert env in {"dev", "staging", "prod", "test"}, f"Unknown env: {env}"
