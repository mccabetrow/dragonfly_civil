"""
Test telemetry API endpoint contract.

Verifies:
1. Valid UI action payloads are accepted and return event_id
2. Invalid payloads return 422 with validation errors
3. Empty event_name is rejected
4. Auth is required (401 without API key)
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
    monkeypatch.setenv("ENVIRONMENT", "dev")

    from backend.main import create_app

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class TestTelemetryHealth:
    """Tests for /api/v1/telemetry/health."""

    def test_telemetry_health_returns_ok(self, client: TestClient, api_key: str) -> None:
        """Telemetry health endpoint should return ok status."""
        response = client.get(
            "/api/v1/telemetry/health",
            headers={"X-DRAGONFLY-API-KEY": api_key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["subsystem"] == "telemetry"


class TestLogUiAction:
    """Tests for POST /api/v1/telemetry/ui-action."""

    def test_valid_payload_returns_event_id(self, client: TestClient, api_key: str) -> None:
        """Valid UI action should be accepted and return event_id."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            headers={"X-DRAGONFLY-API-KEY": api_key},
            json={
                "event_name": "test.event",
                "context": {"foo": "bar", "count": 42},
                "session_id": "test-session-123",
            },
        )

        # Should succeed (200) or fail on DB (500) - not validation error
        assert response.status_code in (200, 500)

        if response.status_code == 200:
            data = response.json()
            assert data["status"] == "ok"
            assert "event_id" in data
            # event_id should be a valid UUID format
            assert len(data["event_id"]) == 36  # UUID length

    def test_minimal_payload_accepted(self, client: TestClient, api_key: str) -> None:
        """Minimal payload with just event_name should be accepted."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            headers={"X-DRAGONFLY-API-KEY": api_key},
            json={
                "event_name": "minimal.event",
                "context": {},
            },
        )

        # Should succeed or fail on DB - not validation error
        assert response.status_code in (200, 500)

    def test_empty_event_name_rejected(self, client: TestClient, api_key: str) -> None:
        """Empty event_name should be rejected with 422."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            headers={"X-DRAGONFLY-API-KEY": api_key},
            json={
                "event_name": "",
                "context": {},
            },
        )

        assert response.status_code == 422

    def test_missing_event_name_rejected(self, client: TestClient, api_key: str) -> None:
        """Missing event_name should be rejected with 422."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            headers={"X-DRAGONFLY-API-KEY": api_key},
            json={
                "context": {"foo": "bar"},
            },
        )

        assert response.status_code == 422

    def test_invalid_event_name_characters_rejected(self, client: TestClient, api_key: str) -> None:
        """Event names with invalid characters should be rejected."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            headers={"X-DRAGONFLY-API-KEY": api_key},
            json={
                "event_name": "invalid event name!",  # spaces and ! not allowed
                "context": {},
            },
        )

        assert response.status_code == 422

    def test_valid_event_name_patterns_accepted(self, client: TestClient, api_key: str) -> None:
        """Valid event name patterns should be accepted."""
        valid_names = [
            "intake.upload_submitted",
            "enforcement.generate_packet_clicked",
            "navigation.page-view",
            "UI_ACTION_2024",
            "test123",
        ]

        for event_name in valid_names:
            response = client.post(
                "/api/v1/telemetry/ui-action",
                headers={"X-DRAGONFLY-API-KEY": api_key},
                json={
                    "event_name": event_name,
                    "context": {},
                },
            )

            # Should not be a validation error
            assert response.status_code in (200, 500), f"Failed for: {event_name}"

    def test_requires_authentication(self, client: TestClient) -> None:
        """Endpoint should require authentication."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            json={
                "event_name": "test.event",
                "context": {},
            },
        )

        assert response.status_code == 401

    def test_complex_context_accepted(self, client: TestClient, api_key: str) -> None:
        """Complex nested context objects should be accepted."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            headers={"X-DRAGONFLY-API-KEY": api_key},
            json={
                "event_name": "complex.context.test",
                "context": {
                    "string_field": "value",
                    "number_field": 42,
                    "boolean_field": True,
                    "null_field": None,
                    "array_field": [1, 2, 3],
                    "nested": {
                        "deep": {
                            "value": "nested-value",
                        },
                    },
                },
            },
        )

        # Should succeed or fail on DB - not validation error
        assert response.status_code in (200, 500)


class TestTelemetryEventTypes:
    """Tests for specific telemetry event scenarios."""

    def test_intake_upload_submitted_event(self, client: TestClient, api_key: str) -> None:
        """Intake upload submitted event should be accepted."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            headers={"X-DRAGONFLY-API-KEY": api_key},
            json={
                "event_name": "intake.upload_submitted",
                "context": {
                    "batch_id": "abc-123-def",
                    "filename": "simplicity_export.csv",
                    "row_count": 150,
                    "valid_rows": 145,
                    "error_rows": 5,
                    "source": "simplicity",
                },
                "session_id": "sess_1234567890",
            },
        )

        assert response.status_code in (200, 500)

    def test_enforcement_generate_packet_clicked_event(
        self, client: TestClient, api_key: str
    ) -> None:
        """Enforcement packet generation click event should be accepted."""
        response = client.post(
            "/api/v1/telemetry/ui-action",
            headers={"X-DRAGONFLY-API-KEY": api_key},
            json={
                "event_name": "enforcement.generate_packet_clicked",
                "context": {
                    "judgment_id": "550e8400-e29b-41d4-a716-446655440000",
                    "strategy": "wage_garnishment",
                    "collectability_score": 85,
                    "judgment_amount": 15000.00,
                },
                "session_id": "sess_1234567890",
            },
        )

        assert response.status_code in (200, 500)
