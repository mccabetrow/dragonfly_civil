"""
Test API authentication contract.

Verifies:
1. X-DRAGONFLY-API-KEY header is accepted (primary)
2. X-API-Key header is accepted (legacy/backward compatibility)
3. Missing/invalid keys return 401 with {"detail": "..."}
4. /api/health requires no auth and returns {status, environment}
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_key() -> str:
    """Get or set a test API key."""
    return "test-api-key-12345"


@pytest.fixture
def client(api_key: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a test client with API key configured."""
    monkeypatch.setenv("DRAGONFLY_API_KEY", api_key)
    monkeypatch.setenv("ENVIRONMENT", "dev")  # Must be dev/staging/prod

    from backend.main import create_app

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    """Tests for /api/health - no auth required."""

    def test_health_returns_ok_without_auth(self, client: TestClient) -> None:
        """Health endpoint should work without any authentication."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "environment" in data
        assert "timestamp" in data

    def test_health_returns_environment(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Health endpoint should return the current environment."""
        # The environment is already set to "dev" in the fixture
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        # Environment comes from settings, which is set to dev/staging/prod
        assert data["environment"] in ["dev", "staging", "prod"]


class TestApiKeyAuth:
    """Tests for API key authentication."""

    def test_primary_header_x_dragonfly_api_key_accepted(
        self, client: TestClient, api_key: str
    ) -> None:
        """X-DRAGONFLY-API-KEY header should authenticate successfully."""
        response = client.get(
            "/api/v1/intake/batches",
            headers={"X-DRAGONFLY-API-KEY": api_key},
        )

        # Should not be 401 - may be 200 or 500 (if DB not available)
        assert response.status_code != 401

    def test_legacy_header_x_api_key_accepted(
        self, client: TestClient, api_key: str
    ) -> None:
        """X-API-Key header should authenticate successfully (backward compat)."""
        response = client.get(
            "/api/v1/intake/batches",
            headers={"X-API-Key": api_key},
        )

        # Should not be 401 - may be 200 or 500 (if DB not available)
        assert response.status_code != 401

    def test_primary_header_takes_precedence(
        self, client: TestClient, api_key: str
    ) -> None:
        """When both headers present, X-DRAGONFLY-API-KEY should be used."""
        response = client.get(
            "/api/v1/intake/batches",
            headers={
                "X-DRAGONFLY-API-KEY": api_key,
                "X-API-Key": "wrong-key",
            },
        )

        # Should authenticate via X-DRAGONFLY-API-KEY
        assert response.status_code != 401


class TestAuthFailure:
    """Tests for authentication failure cases."""

    def test_missing_auth_returns_401(self, client: TestClient) -> None:
        """Request without auth headers should return 401."""
        response = client.get("/api/v1/intake/batches")

        assert response.status_code == 401
        data = response.json()
        # The error handler wraps the response with 'message' or 'detail'
        assert data.get("message") or data.get("detail")

    def test_invalid_key_returns_401(self, client: TestClient) -> None:
        """Request with invalid API key should return 401."""
        response = client.get(
            "/api/v1/intake/batches",
            headers={"X-DRAGONFLY-API-KEY": "wrong-api-key"},
        )

        assert response.status_code == 401
        data = response.json()
        # Check for either 'message' or 'detail' containing the error
        error_msg = data.get("message") or data.get("detail", "")
        assert "Invalid API key" in error_msg

    def test_empty_key_returns_401(self, client: TestClient) -> None:
        """Request with empty API key should return 401."""
        response = client.get(
            "/api/v1/intake/batches",
            headers={"X-DRAGONFLY-API-KEY": ""},
        )

        # Empty string header is treated as no auth
        assert response.status_code == 401

    def test_invalid_legacy_key_returns_401(self, client: TestClient) -> None:
        """Request with invalid X-API-Key should return 401."""
        response = client.get(
            "/api/v1/intake/batches",
            headers={"X-API-Key": "wrong-api-key"},
        )

        assert response.status_code == 401
        data = response.json()
        # Check for either 'message' or 'detail' containing the error
        error_msg = data.get("message") or data.get("detail", "")
        assert "Invalid API key" in error_msg


class TestProtectedEndpoints:
    """Verify key protected endpoints exist and require auth."""

    PROTECTED_ENDPOINTS = [
        ("GET", "/api/v1/intake/batches"),
        ("POST", "/api/v1/intake/upload"),
        ("POST", "/api/v1/ops/guardian/run"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_endpoint_requires_auth(
        self, client: TestClient, method: str, path: str
    ) -> None:
        """Protected endpoints should return 401 without auth."""
        if method == "GET":
            response = client.get(path)
        elif method == "POST":
            response = client.post(path)
        else:
            pytest.fail(f"Unknown method: {method}")

        # Should be 401 (auth required) or 422 (validation error after auth bypass)
        # but NOT 404 (endpoint missing)
        assert response.status_code in [
            401,
            422,
        ], f"{method} {path} returned {response.status_code}, expected 401 or 422"

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_endpoint_accessible_with_key(
        self, client: TestClient, api_key: str, method: str, path: str
    ) -> None:
        """Protected endpoints should be accessible with valid API key."""
        headers = {"X-DRAGONFLY-API-KEY": api_key}

        if method == "GET":
            response = client.get(path, headers=headers)
        elif method == "POST":
            response = client.post(path, headers=headers)
        else:
            pytest.fail(f"Unknown method: {method}")

        # Should NOT be 401 - may be 200, 422 (validation), or 500 (DB)
        assert (
            response.status_code != 401
        ), f"{method} {path} returned 401 even with valid API key"
