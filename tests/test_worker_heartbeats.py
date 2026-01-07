"""
Tests for worker heartbeats and system health.

Tests cover:
- WorkerHeartbeat class creates unique IDs
- Heartbeats are written to database correctly
- v_system_health view reports status correctly
- GET /api/v1/system/status returns expected data

NOTE: Integration tests require database connection.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


class TestWorkerHeartbeatClass:
    """Unit tests for the WorkerHeartbeat class."""

    def test_worker_id_generation(self) -> None:
        """Verify worker IDs are unique and formatted correctly."""
        from backend.workers.heartbeat import _generate_worker_id

        id1 = _generate_worker_id("ingest_processor")
        id2 = _generate_worker_id("ingest_processor")

        # IDs should be formatted as {type}-{uuid}
        assert id1.startswith("ingest_processor-")
        assert id2.startswith("ingest_processor-")
        # IDs should be unique
        assert id1 != id2

    def test_hostname_retrieval(self) -> None:
        """Verify hostname is retrieved."""
        from backend.workers.heartbeat import _get_hostname

        hostname = _get_hostname()
        assert hostname is not None
        assert len(hostname) > 0

    def test_heartbeat_initialization(self) -> None:
        """Verify HeartbeatContext initializes correctly."""
        from backend.workers.heartbeat import WorkerHeartbeat

        hb = WorkerHeartbeat(
            worker_type="test_worker",
            get_db_url=lambda: "postgresql://fake",
            interval=5.0,
        )

        assert hb.worker_type == "test_worker"
        assert hb.worker_id.startswith("test_worker-")
        assert hb._interval == 5.0

    def test_heartbeat_context_manager(self) -> None:
        """Verify HeartbeatContext can be used as context manager."""
        from backend.workers.heartbeat import HeartbeatContext

        # Mock the database calls
        with patch("backend.workers.heartbeat.psycopg") as mock_psycopg:
            mock_conn = MagicMock()
            mock_psycopg.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_psycopg.connect.return_value.__exit__ = MagicMock(return_value=False)

            ctx = HeartbeatContext(
                "test_worker",
                lambda: "postgresql://fake",
                interval=60.0,  # Long interval to prevent actual heartbeats
            )

            # Enter and exit should work without error
            with patch.object(ctx._heartbeat, "_send_heartbeat"):
                with ctx as hb:
                    assert hb.worker_type == "test_worker"
                    assert hb.worker_id.startswith("test_worker-")


class TestSystemRouterImport:
    """Test that the system router imports cleanly."""

    def test_router_imports(self) -> None:
        """Verify system router can be imported."""
        from backend.api.routers.system import router

        assert router is not None
        assert router.prefix == "/v1/system"

    def test_app_includes_system_router(self) -> None:
        """Verify system router is mounted in the app."""
        from backend.main import create_app

        app = create_app()
        routes = [route.path for route in app.routes]

        # Check system endpoints are registered
        assert "/api/v1/system/status" in routes
        assert "/api/v1/system/health" in routes


class TestSystemHealthEndpoint:
    """Test the system health endpoint."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        from fastapi.testclient import TestClient

        from backend.main import create_app

        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_system_health_returns_200(self, client) -> None:
        """GET /api/v1/system/health should return 200."""
        response = client.get("/api/v1/system/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["subsystem"] == "system"


class TestSystemStatusEndpoint:
    """Test the system status endpoint."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        from fastapi.testclient import TestClient

        from backend.main import create_app

        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_system_status_requires_auth(self, client) -> None:
        """GET /api/v1/system/status should require authentication."""
        response = client.get("/api/v1/system/status")
        # Without auth, should get 401
        assert response.status_code == 401

    def test_system_status_returns_envelope(self, client) -> None:
        """GET /api/v1/system/status should return ApiResponse envelope."""
        import os

        api_key = os.environ.get("DRAGONFLY_API_KEY", "test-key")
        headers = {"X-API-Key": api_key}

        response = client.get("/api/v1/system/status", headers=headers)

        # Should return 200 (even if degraded) or 401 if no key configured
        if response.status_code == 401:
            pytest.skip("DRAGONFLY_API_KEY not configured")

        assert response.status_code == 200

        data = response.json()
        # Check envelope structure
        assert "ok" in data
        assert "data" in data
        assert "meta" in data
        assert "trace_id" in data["meta"]

    def test_system_status_data_structure(self, client) -> None:
        """GET /api/v1/system/status should return expected data structure."""
        import os

        api_key = os.environ.get("DRAGONFLY_API_KEY", "test-key")
        headers = {"X-API-Key": api_key}

        response = client.get("/api/v1/system/status", headers=headers)

        # Skip if no API key configured
        if response.status_code == 401:
            pytest.skip("DRAGONFLY_API_KEY not configured")

        assert response.status_code == 200

        data = response.json()
        payload = data.get("data", {})

        # Check expected fields exist (even if values vary)
        assert "ingest_worker" in payload or data.get("degraded", False)
        assert "enforcement_worker" in payload or data.get("degraded", False)
        assert "queue_depth" in payload or data.get("degraded", False)


@pytest.mark.integration
class TestHeartbeatIntegration:
    """Integration tests for heartbeat functionality.

    These tests require a live database connection and will write/read
    from ops.worker_heartbeats and ops.v_system_health.
    """

    def test_heartbeat_writes_to_database(self) -> None:
        """Verify heartbeats are written to ops.worker_heartbeats."""
        import psycopg

        from src.supabase_client import get_supabase_db_url, get_supabase_env

        env = get_supabase_env()
        if env == "prod":
            pytest.skip("Skipping write test on production")

        db_url = get_supabase_db_url(env)

        # Generate unique worker ID for this test
        test_worker_id = f"test-heartbeat-{int(time.time())}"
        test_worker_type = "test_integration"

        try:
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    # Write heartbeat
                    cur.execute(
                        """
                        INSERT INTO ops.worker_heartbeats
                            (worker_id, worker_type, hostname, last_seen_at, status)
                        VALUES (%s, %s, 'test-host', now(), 'running')
                        ON CONFLICT (worker_id) DO UPDATE SET
                            last_seen_at = now(),
                            status = 'running'
                        """,
                        (test_worker_id, test_worker_type),
                    )
                    conn.commit()

                    # Read back
                    cur.execute(
                        "SELECT worker_id, worker_type, status FROM ops.worker_heartbeats WHERE worker_id = %s",
                        (test_worker_id,),
                    )
                    row = cur.fetchone()

                    assert row is not None
                    assert row[0] == test_worker_id
                    assert row[1] == test_worker_type
                    assert row[2] == "running"

        finally:
            # Cleanup
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM ops.worker_heartbeats WHERE worker_id = %s",
                        (test_worker_id,),
                    )
                    conn.commit()

    def test_v_system_health_view_returns_data(self) -> None:
        """Verify v_system_health view returns expected columns."""
        import psycopg

        from src.supabase_client import get_supabase_db_url, get_supabase_env

        env = get_supabase_env()
        db_url = get_supabase_db_url(env)

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ops.v_system_health")
                row = cur.fetchone()

                # View should always return exactly one row
                assert row is not None

                # Check we have expected number of columns
                # (ingest_status, ingest_last_heartbeat, enforcement_status,
                #  enforcement_last_heartbeat, queue_depth, queue_processing, checked_at)
                assert len(row) == 7

                # ingest_status and enforcement_status should be 'online' or 'offline'
                assert row[0] in ("online", "offline")
                assert row[2] in ("online", "offline")

                # queue_depth and queue_processing should be integers >= 0
                assert isinstance(row[4], int) and row[4] >= 0
                assert isinstance(row[5], int) and row[5] >= 0

    def test_worker_shows_online_when_heartbeat_fresh(self) -> None:
        """Verify worker shows 'online' when heartbeat is within 60 seconds."""
        import psycopg

        from src.supabase_client import get_supabase_db_url, get_supabase_env

        env = get_supabase_env()
        if env == "prod":
            pytest.skip("Skipping write test on production")

        db_url = get_supabase_db_url(env)

        test_worker_id = f"test-online-{int(time.time())}"

        try:
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    # Insert fresh heartbeat for ingest_processor
                    cur.execute(
                        """
                        INSERT INTO ops.worker_heartbeats
                            (worker_id, worker_type, hostname, last_seen_at, status)
                        VALUES (%s, 'ingest_processor', 'test-host', now(), 'running')
                        """,
                        (test_worker_id,),
                    )
                    conn.commit()

                    # Check view
                    cur.execute("SELECT ingest_status FROM ops.v_system_health")
                    row = cur.fetchone()

                    assert row is not None
                    assert row[0] == "online"

        finally:
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM ops.worker_heartbeats WHERE worker_id = %s",
                        (test_worker_id,),
                    )
                    conn.commit()

    def test_worker_shows_offline_when_heartbeat_stale(self) -> None:
        """Verify worker shows 'offline' when heartbeat is older than 60 seconds."""
        import psycopg

        from src.supabase_client import get_supabase_db_url, get_supabase_env

        env = get_supabase_env()
        if env == "prod":
            pytest.skip("Skipping write test on production")

        db_url = get_supabase_db_url(env)

        test_worker_id = f"test-offline-{int(time.time())}"

        try:
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    # First, delete any existing ingest_processor heartbeats
                    cur.execute(
                        "DELETE FROM ops.worker_heartbeats WHERE worker_type = 'ingest_processor'"
                    )

                    # Insert stale heartbeat (2 minutes ago)
                    cur.execute(
                        """
                        INSERT INTO ops.worker_heartbeats
                            (worker_id, worker_type, hostname, last_seen_at, status)
                        VALUES (%s, 'ingest_processor', 'test-host', now() - interval '2 minutes', 'running')
                        """,
                        (test_worker_id,),
                    )
                    conn.commit()

                    # Check view
                    cur.execute("SELECT ingest_status FROM ops.v_system_health")
                    row = cur.fetchone()

                    assert row is not None
                    assert row[0] == "offline"

        finally:
            with psycopg.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM ops.worker_heartbeats WHERE worker_id = %s",
                        (test_worker_id,),
                    )
                    conn.commit()
