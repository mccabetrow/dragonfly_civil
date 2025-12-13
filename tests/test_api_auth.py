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
        # Response is now wrapped in API envelope
        assert data["ok"] is True
        assert data["data"]["status"] == "ok"
        assert "environment" in data["data"]
        assert "timestamp" in data["data"]
        assert "trace_id" in data["meta"]

    def test_health_returns_environment(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Health endpoint should return the current environment."""
        # The environment is already set to "dev" in the fixture
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        # Environment comes from settings, which is set to dev/staging/prod
        # Response is now wrapped in API envelope
        assert data["data"]["environment"] in ["dev", "staging", "prod"]


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

    def test_legacy_header_x_api_key_accepted(self, client: TestClient, api_key: str) -> None:
        """X-API-Key header should authenticate successfully (backward compat)."""
        response = client.get(
            "/api/v1/intake/batches",
            headers={"X-API-Key": api_key},
        )

        # Should not be 401 - may be 200 or 500 (if DB not available)
        assert response.status_code != 401

    def test_primary_header_takes_precedence(self, client: TestClient, api_key: str) -> None:
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
        ("GET", "/api/v1/analytics/overview"),
        ("POST", "/api/v1/intake/upload"),
        ("POST", "/api/v1/ops/guardian/run"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_endpoint_requires_auth(self, client: TestClient, method: str, path: str) -> None:
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
        assert response.status_code != 401, f"{method} {path} returned 401 even with valid API key"


class TestCORSConfiguration:
    """Tests for CORS configuration - critical for Vercel console.

    These tests use PRODUCTION origins to ensure they reflect real-world behavior.
    Previously tests used localhost:5173 which is always in fallback - that's why
    tests would pass while production would fail.

    IMPORTANT: We create a dedicated client fixture that clears the settings cache
    and sets DRAGONFLY_CORS_ORIGINS BEFORE creating the app. This ensures the CORS
    middleware gets the production origins we're testing.
    """

    # Production Vercel origins - these MUST work or console is broken
    PROD_ORIGIN = "https://dragonfly-console1.vercel.app"
    PROD_ORIGIN_GIT = "https://dragonfly-console1-git-main-mccabetrow.vercel.app"
    LOCALHOST_ORIGIN = "http://localhost:5173"
    # Vercel preview deployment (random hash)
    PREVIEW_ORIGIN = "https://dragonfly-console1-hkyvsyq2h.vercel.app"

    @pytest.fixture
    def cors_client(self, monkeypatch: pytest.MonkeyPatch) -> TestClient:
        """Create a test client with production CORS origins configured.

        This fixture clears the settings cache and sets env vars BEFORE
        importing and creating the app, ensuring CORS is configured correctly.
        """
        # Set env vars BEFORE importing anything from backend
        prod_origins = ",".join(
            [
                self.PROD_ORIGIN,
                self.PROD_ORIGIN_GIT,
                self.LOCALHOST_ORIGIN,
            ]
        )
        monkeypatch.setenv("DRAGONFLY_CORS_ORIGINS", prod_origins)
        monkeypatch.setenv("DRAGONFLY_API_KEY", "test-api-key-12345")
        monkeypatch.setenv("ENVIRONMENT", "prod")  # Enable regex matching

        # Clear the settings cache so our env vars are picked up
        from backend.config import get_settings

        get_settings.cache_clear()

        # Now create the app - it will read fresh settings with our CORS origins
        from backend.main import create_app

        app = create_app()

        return TestClient(app, raise_server_exceptions=False)

    def test_cors_preflight_prod_origin(self, cors_client: TestClient) -> None:
        """OPTIONS preflight with production Vercel origin returns 200."""
        response = cors_client.options(
            "/api/health",
            headers={
                "Origin": self.PROD_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-DRAGONFLY-API-KEY",
            },
        )

        assert response.status_code == 200, (
            f"Preflight failed with {response.status_code}. " f"Headers: {dict(response.headers)}"
        )
        assert response.headers.get("Access-Control-Allow-Origin") == self.PROD_ORIGIN

    def test_cors_preflight_git_branch_origin(self, cors_client: TestClient) -> None:
        """OPTIONS preflight with Vercel git preview origin returns 200."""
        response = cors_client.options(
            "/api/health",
            headers={
                "Origin": self.PROD_ORIGIN_GIT,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-DRAGONFLY-API-KEY",
            },
        )

        assert (
            response.status_code == 200
        ), f"Preflight for git preview origin failed with {response.status_code}"
        assert response.headers.get("Access-Control-Allow-Origin") == self.PROD_ORIGIN_GIT

    def test_cors_preflight_vercel_preview_origin(self, cors_client: TestClient) -> None:
        """OPTIONS preflight with Vercel preview deployment origin returns 200.

        This tests the allow_origin_regex pattern that matches:
          https://dragonfly-console1-<hash>.vercel.app
        """
        response = cors_client.options(
            "/api/health",
            headers={
                "Origin": self.PREVIEW_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-DRAGONFLY-API-KEY",
            },
        )

        assert response.status_code == 200, (
            f"Preflight for Vercel preview origin failed with {response.status_code}. "
            f"Headers: {dict(response.headers)}. "
            f"Origin {self.PREVIEW_ORIGIN} should match regex pattern."
        )
        assert response.headers.get("Access-Control-Allow-Origin") == self.PREVIEW_ORIGIN

    def test_cors_allows_credentials(self, cors_client: TestClient) -> None:
        """CORS must allow credentials for cross-origin requests."""
        response = cors_client.options(
            "/api/health",
            headers={
                "Origin": self.PROD_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )

        allow_credentials = response.headers.get("Access-Control-Allow-Credentials")
        assert allow_credentials == "true", (
            f"Expected Access-Control-Allow-Credentials: true, got: {allow_credentials}. "
            f"This breaks cookie/auth header passing from Vercel console."
        )

    def test_cors_allows_api_key_header(self, cors_client: TestClient) -> None:
        """CORS must allow X-DRAGONFLY-API-KEY header for authenticated requests."""
        response = cors_client.options(
            "/api/v1/intake/batches",
            headers={
                "Origin": self.PROD_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-DRAGONFLY-API-KEY",
            },
        )

        allow_headers = response.headers.get("Access-Control-Allow-Headers", "")
        # Should either be "*" or include the specific header
        assert allow_headers == "*" or "X-DRAGONFLY-API-KEY" in allow_headers, (
            f"CORS must allow X-DRAGONFLY-API-KEY header, got: {allow_headers}. "
            f"This breaks API authentication from Vercel console."
        )

    def test_cors_allows_all_methods(self, cors_client: TestClient) -> None:
        """CORS must allow all HTTP methods for full API access."""
        response = cors_client.options(
            "/api/health",
            headers={
                "Origin": self.PROD_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )

        allow_methods = response.headers.get("Access-Control-Allow-Methods", "")
        # Must include POST for mutations
        assert "POST" in allow_methods, f"CORS must allow POST method, got: {allow_methods}"

    def test_cors_rejects_unknown_origin(self, cors_client: TestClient) -> None:
        """CORS should not set Allow-Origin for untrusted origins."""
        response = cors_client.options(
            "/api/health",
            headers={
                "Origin": "https://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        # Starlette CORS returns 400 for disallowed origins
        # OR returns 200 but without Allow-Origin header
        allow_origin = response.headers.get("Access-Control-Allow-Origin")
        assert allow_origin != "https://evil.com", f"CORS allowed untrusted origin: {allow_origin}"
