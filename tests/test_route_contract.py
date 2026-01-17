"""
Dragonfly Route Contract Tests

These tests enforce the production certification route contract:
1. / MUST return service_name="dragonfly-api" (Railway domain contract)
2. /whoami MUST return process identity for debugging
3. /health MUST exist at root (not just /api/health)
4. /readyz MUST exist at root (not just /api/readyz)
5. OpenAPI spec MUST include /health and /readyz
6. All responses MUST include X-Dragonfly-* headers

If any of these tests fail, production certification will also fail.
These are MANDATORY requirements for deployment.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from backend.main import create_app

    app = create_app()
    return TestClient(app)


class TestRailwayDomainContract:
    """
    Tests for the Railway Domain Contract (Step 0 of certification).

    GET / must return:
    - service_name="dragonfly-api" (exact match)
    - env, sha_short, version for tracing

    This prevents certifying a URL that points to Railway fallback
    or a different service entirely.
    """

    def test_root_returns_service_identity(self, client: TestClient) -> None:
        """
        GET / must return 200 with service identity JSON.

        This is the first check in production certification.
        If this fails, the domain is not attached to dragonfly-api.
        """
        response = client.get("/")
        assert response.status_code == 200, (
            f"GET / returned {response.status_code}, expected 200. "
            "Root endpoint must always return 200 for domain verification."
        )

    def test_root_returns_correct_service_name(self, client: TestClient) -> None:
        """
        GET / must return service_name='dragonfly-api'.

        This is the KEY assertion that prevents certifying wrong URLs.
        """
        response = client.get("/")
        data = response.json()
        assert data.get("service_name") == "dragonfly-api", (
            f"Expected service_name='dragonfly-api', got {data.get('service_name')!r}. "
            "This endpoint is used to verify Railway domain attachment."
        )

    def test_root_includes_version_info(self, client: TestClient) -> None:
        """GET / must include version, sha_short, and env."""
        response = client.get("/")
        data = response.json()

        assert "version" in data, "Root response missing 'version' field"
        assert "sha_short" in data, "Root response missing 'sha_short' field"
        assert "env" in data, "Root response missing 'env' field"

    def test_root_has_no_db_dependency(self, client: TestClient) -> None:
        """
        GET / must return 200 even if database is down.

        This endpoint is checked BEFORE /readyz, so it cannot depend on DB.
        (We can't easily test DB-down scenario, but we verify 200 response.)
        """
        response = client.get("/")
        # Should never return 503
        assert (
            response.status_code != 503
        ), "GET / returned 503. Root identity endpoint must not check database."


class TestWhoAmIEndpoint:
    """
    Tests for the /whoami debugging endpoint.

    This endpoint provides detailed process identity for debugging
    Railway deployments without exposing secrets.
    """

    def test_whoami_returns_200(self, client: TestClient) -> None:
        """GET /whoami must return 200."""
        response = client.get("/whoami")
        assert (
            response.status_code == 200
        ), f"GET /whoami returned {response.status_code}, expected 200."

    def test_whoami_includes_service_name(self, client: TestClient) -> None:
        """GET /whoami must include service_name."""
        response = client.get("/whoami")
        data = response.json()
        assert data.get("service_name") == "dragonfly-api"

    def test_whoami_includes_hostname(self, client: TestClient) -> None:
        """GET /whoami must include hostname for multi-replica debugging."""
        response = client.get("/whoami")
        data = response.json()
        assert "hostname" in data and data["hostname"], "Missing or empty hostname"

    def test_whoami_includes_pid(self, client: TestClient) -> None:
        """GET /whoami must include process ID."""
        response = client.get("/whoami")
        data = response.json()
        assert "pid" in data and isinstance(data["pid"], int), "Missing or invalid pid"

    def test_whoami_includes_listening_port(self, client: TestClient) -> None:
        """GET /whoami must include listening port (or null)."""
        response = client.get("/whoami")
        data = response.json()
        assert "listening_port" in data, "Missing listening_port field"

    def test_whoami_includes_database_ready(self, client: TestClient) -> None:
        """GET /whoami must include database_ready boolean."""
        response = client.get("/whoami")
        data = response.json()
        assert "database_ready" in data, "Missing database_ready field"
        assert isinstance(data["database_ready"], bool), "database_ready must be boolean"

    def test_whoami_includes_dsn_identity(self, client: TestClient) -> None:
        """GET /whoami must include redacted DSN identity."""
        response = client.get("/whoami")
        data = response.json()
        assert "dsn_identity" in data, "Missing dsn_identity field"
        # DSN identity should NOT contain password
        dsn = data["dsn_identity"]
        assert (
            ":" not in dsn.split("@")[0] if "@" in dsn else True
        ), "dsn_identity appears to contain password (found : before @)"

    def test_whoami_never_exposes_password(self, client: TestClient) -> None:
        """GET /whoami must never expose database password."""
        response = client.get("/whoami")
        data = response.json()
        dsn = data.get("dsn_identity", "")
        # Should not have password format (user:password@)
        assert dsn.count(":") <= 1, "dsn_identity may contain password (multiple colons found)"


class TestRootHealthEndpoints:
    """
    Tests that /health and /readyz exist at the ROOT path.

    These endpoints are required by load balancers (Railway, Kubernetes)
    and production certification. They MUST NOT be only under /api.
    """

    def test_health_exists_at_root(self, client: TestClient) -> None:
        """
        /health MUST exist at root path.

        Failure means: Production certification will fail with 404.
        Remediation: Ensure health_root_router is mounted with prefix="".
        """
        response = client.get("/health")
        assert response.status_code == 200, (
            f"GET /health returned {response.status_code}, expected 200. "
            "The /health endpoint MUST exist at root for load balancers."
        )

    def test_readyz_exists_at_root(self, client: TestClient) -> None:
        """
        /readyz MUST exist at root path.

        Failure means: Production certification will fail with 404.
        Remediation: Ensure health_root_router is mounted with prefix="".
        """
        # readyz may return 200 or 503 depending on DB state
        response = client.get("/readyz")
        assert response.status_code in (200, 503), (
            f"GET /readyz returned {response.status_code}, expected 200 or 503. "
            "The /readyz endpoint MUST exist at root for readiness probes."
        )

    def test_health_is_not_only_under_api(self, client: TestClient) -> None:
        """
        /health at root must NOT redirect to /api/health.

        If /health redirects, load balancers may not follow redirects correctly.
        """
        response = client.get("/health", follow_redirects=False)
        assert response.status_code == 200, (
            f"GET /health returned {response.status_code} without following redirects. "
            "The /health endpoint must be directly at root, not a redirect."
        )

    def test_readyz_is_not_only_under_api(self, client: TestClient) -> None:
        """
        /readyz at root must NOT redirect to /api/readyz.
        """
        response = client.get("/readyz", follow_redirects=False)
        assert response.status_code in (200, 503), (
            f"GET /readyz returned {response.status_code} without following redirects. "
            "The /readyz endpoint must be directly at root, not a redirect."
        )


class TestHealthResponseContent:
    """Tests that health endpoints return the expected content."""

    def test_health_returns_ok_status(self, client: TestClient) -> None:
        """Health endpoint must return status=ok."""
        response = client.get("/health")
        data = response.json()
        assert data.get("status") == "ok", f"Expected status='ok', got {data.get('status')}"

    def test_health_includes_version_info(self, client: TestClient) -> None:
        """Health endpoint should include version/sha/env for debugging."""
        response = client.get("/health")
        data = response.json()
        # These fields are included by the root_health_check endpoint
        assert (
            "version" in data or "sha" in data
        ), "Health response should include version or sha for debugging deployments"


class TestRequiredHeaders:
    """
    Tests that all responses include mandatory X-Dragonfly-* headers.

    These headers are required for:
    - Tracing responses to specific deployments
    - Verifying correct environment
    - Production certification
    """

    REQUIRED_HEADERS = [
        "X-Dragonfly-Env",
        "X-Dragonfly-SHA-Short",
    ]

    def test_health_has_dragonfly_headers(self, client: TestClient) -> None:
        """Health response must include X-Dragonfly-* headers."""
        response = client.get("/health")
        for header in self.REQUIRED_HEADERS:
            assert header in response.headers, (
                f"Response missing required header: {header}. "
                "All responses must include X-Dragonfly-Env and X-Dragonfly-SHA-Short."
            )
            # Header should not be empty or "unknown"
            value = response.headers[header]
            assert (
                value and value.lower() != "unknown"
            ), f"Header {header} has invalid value: {value!r}"

    def test_readyz_has_dragonfly_headers(self, client: TestClient) -> None:
        """Readyz response must include X-Dragonfly-* headers."""
        response = client.get("/readyz")
        for header in self.REQUIRED_HEADERS:
            assert header in response.headers, (
                f"Response missing required header: {header}. "
                "All responses must include X-Dragonfly-Env and X-Dragonfly-SHA-Short."
            )

    def test_api_version_has_dragonfly_headers(self, client: TestClient) -> None:
        """API version endpoint must include X-Dragonfly-* headers."""
        response = client.get("/api/version")
        for header in self.REQUIRED_HEADERS:
            assert header in response.headers, f"Response missing required header: {header}"

    def test_error_response_has_dragonfly_headers(self, client: TestClient) -> None:
        """Even 404 errors must include X-Dragonfly-* headers."""
        response = client.get("/nonexistent-endpoint-12345")
        assert response.status_code == 404
        for header in self.REQUIRED_HEADERS:
            assert header in response.headers, (
                f"404 response missing required header: {header}. "
                "Exception handlers must include version headers."
            )


class TestOpenAPIContract:
    """
    Tests that OpenAPI spec includes required endpoints.

    Production certification fetches /openapi.json to verify
    route mounting is correct.
    """

    def test_openapi_json_accessible(self, client: TestClient) -> None:
        """OpenAPI spec must be accessible at /openapi.json."""
        response = client.get("/openapi.json")
        assert response.status_code == 200, (
            f"GET /openapi.json returned {response.status_code}. "
            "OpenAPI spec must be available for certification autodiscovery."
        )

    def test_openapi_includes_health(self, client: TestClient) -> None:
        """/health must be in OpenAPI paths."""
        response = client.get("/openapi.json")
        spec = response.json()
        paths = spec.get("paths", {})
        assert "/health" in paths, (
            f"/health not in OpenAPI paths: {list(paths.keys())[:10]}... "
            "The health_root_router must be mounted with prefix='' to appear at root."
        )

    def test_openapi_includes_readyz(self, client: TestClient) -> None:
        """/readyz must be in OpenAPI paths."""
        response = client.get("/openapi.json")
        spec = response.json()
        paths = spec.get("paths", {})
        assert "/readyz" in paths, (
            f"/readyz not in OpenAPI paths: {list(paths.keys())[:10]}... "
            "The health_root_router must be mounted with prefix='' to appear at root."
        )

    def test_openapi_health_not_only_under_api(self, client: TestClient) -> None:
        """
        If /api/health exists, /health must ALSO exist at root.

        This catches misconfiguration where routes are only under /api.
        """
        response = client.get("/openapi.json")
        spec = response.json()
        paths = spec.get("paths", {})

        if "/api/health" in paths:
            assert "/health" in paths, (
                "/api/health exists but /health does not exist at root. "
                "Load balancers require /health at root path. "
                "REMEDIATION: Mount health_root_router with prefix='' OR use --base-path /api"
            )


class TestLivenessVsReadiness:
    """
    Tests the contract difference between /health and /readyz.

    - /health: ALWAYS returns 200 if process is alive (no DB check)
    - /readyz: Returns 200 only if DB is ready, else 503
    """

    def test_health_never_returns_503(self, client: TestClient) -> None:
        """
        /health must NEVER return 503 - it's a liveness probe.

        Liveness probes indicate the process is running.
        If /health returns 503, Kubernetes will restart the container unnecessarily.
        """
        response = client.get("/health")
        assert response.status_code != 503, (
            "/health returned 503. Liveness probes must always return 200 if alive. "
            "Only /readyz should return 503 when DB is unavailable."
        )

    def test_readyz_returns_503_with_metadata_on_failure(self, client: TestClient) -> None:
        """
        When /readyz returns 503, it should include helpful metadata.

        This helps operators understand why the service is not ready.
        """
        response = client.get("/readyz")
        if response.status_code == 503:
            data = response.json()
            # Should have some indication of the failure
            assert (
                "status" in data or "reason" in data
            ), "503 response should include status or reason field"
