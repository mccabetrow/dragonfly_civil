"""
Integration tests for the Offer Engine API.

Tests cover:
- POST /api/v1/offers happy path
- POST /api/v1/offers invalid judgment_id
- POST /api/v1/offers invalid amount (<=0)
- GET /api/v1/offers/stats with date filtering
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient


def _get_db_url() -> str:
    """Resolve the Supabase database URL from environment."""
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit
    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if not project_ref or not password:
        pytest.skip("Supabase database credentials not configured")
    return (
        f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"
    )


@pytest.fixture(scope="module")
def app_client() -> TestClient:
    """Create a test client for the FastAPI app."""
    from backend.main import create_app

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def test_judgment_id() -> int:
    """Create a test judgment and return its ID.

    Creates a minimal judgment row for testing offers against.
    Cleans up after the module completes.
    """
    db_url = _get_db_url()
    case_number = f"OFFERS-TEST-{uuid.uuid4().hex[:8].upper()}"

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.judgments (
                    case_number,
                    plaintiff_name,
                    defendant_name,
                    county,
                    judgment_amount
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    case_number,
                    "Test Plaintiff",
                    "Test Defendant",
                    "Test County",
                    10000.00,
                ),
            )
            judgment_id = cur.fetchone()[0]
            conn.commit()

    yield judgment_id

    # Cleanup: delete offers first (FK constraint), then judgment
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM enforcement.offers WHERE judgment_id = %s",
                (judgment_id,),
            )
            cur.execute(
                "DELETE FROM public.judgments WHERE id = %s",
                (judgment_id,),
            )
            conn.commit()


@pytest.mark.integration
class TestOffersAPI:
    """Tests for POST /api/v1/offers endpoint."""

    def test_create_offer_happy_path(
        self,
        app_client: TestClient,
        test_judgment_id: int,
    ):
        """Valid judgment with positive amount should return 201."""
        payload = {
            "judgment_id": test_judgment_id,
            "offer_amount": "5000.00",
            "offer_type": "purchase",
            "operator_notes": "Test offer",
        }
        response = app_client.post("/api/v1/offers", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["judgment_id"] == test_judgment_id
        assert Decimal(data["offer_amount"]) == Decimal("5000.00")
        assert data["offer_type"] == "purchase"
        assert data["offer_status"] == "pending"
        assert data["operator_notes"] == "Test offer"
        assert "id" in data
        assert "created_at" in data

    def test_create_offer_no_notes(
        self,
        app_client: TestClient,
        test_judgment_id: int,
    ):
        """Offer without operator_notes should still succeed."""
        payload = {
            "judgment_id": test_judgment_id,
            "offer_amount": "2500.50",
            "offer_type": "contingency",
        }
        response = app_client.post("/api/v1/offers", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["offer_type"] == "contingency"
        assert data["operator_notes"] is None

    def test_create_offer_invalid_judgment_id(
        self,
        app_client: TestClient,
    ):
        """Non-existent judgment_id should return 404."""
        payload = {
            "judgment_id": 999999999,  # unlikely to exist
            "offer_amount": "1000.00",
            "offer_type": "purchase",
        }
        response = app_client.post("/api/v1/offers", json=payload)
        # Could be 404 or 400 depending on FK enforcement timing
        assert response.status_code in (400, 404), response.text

    def test_create_offer_zero_amount(
        self,
        app_client: TestClient,
        test_judgment_id: int,
    ):
        """offer_amount of 0 should return 400."""
        payload = {
            "judgment_id": test_judgment_id,
            "offer_amount": "0.00",
            "offer_type": "purchase",
        }
        response = app_client.post("/api/v1/offers", json=payload)
        assert response.status_code == 400, response.text
        assert "greater than zero" in response.json()["detail"].lower()

    def test_create_offer_negative_amount(
        self,
        app_client: TestClient,
        test_judgment_id: int,
    ):
        """Negative offer_amount should return 400."""
        payload = {
            "judgment_id": test_judgment_id,
            "offer_amount": "-500.00",
            "offer_type": "purchase",
        }
        response = app_client.post("/api/v1/offers", json=payload)
        assert response.status_code == 400, response.text
        assert "greater than zero" in response.json()["detail"].lower()

    def test_create_offer_invalid_type(
        self,
        app_client: TestClient,
        test_judgment_id: int,
    ):
        """Invalid offer_type should return 422 (Pydantic validation)."""
        payload = {
            "judgment_id": test_judgment_id,
            "offer_amount": "1000.00",
            "offer_type": "invalid_type",
        }
        response = app_client.post("/api/v1/offers", json=payload)
        assert response.status_code == 422, response.text


@pytest.mark.integration
class TestOfferStatsAPI:
    """Tests for GET /api/v1/offers/stats endpoint."""

    def test_get_stats_no_filters(
        self,
        app_client: TestClient,
    ):
        """Stats endpoint should return aggregate data."""
        response = app_client.get("/api/v1/offers/stats")
        assert response.status_code == 200, response.text
        data = response.json()
        # Stats should have expected structure
        assert "total_offers" in data
        assert "total_amount" in data
        assert "offers_by_type" in data
        assert "offers_by_status" in data
        assert isinstance(data["total_offers"], int)
        assert isinstance(data["offers_by_type"], dict)
        assert isinstance(data["offers_by_status"], dict)

    def test_get_stats_with_date_filters(
        self,
        app_client: TestClient,
    ):
        """Stats should respect date range filters."""
        today = date.today()
        start = (today - timedelta(days=30)).isoformat()
        end = today.isoformat()

        response = app_client.get(
            "/api/v1/offers/stats",
            params={"start_date": start, "end_date": end},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "total_offers" in data

    def test_get_stats_future_date_range(
        self,
        app_client: TestClient,
    ):
        """Future date range should return zero counts."""
        future_start = (date.today() + timedelta(days=100)).isoformat()
        future_end = (date.today() + timedelta(days=200)).isoformat()

        response = app_client.get(
            "/api/v1/offers/stats",
            params={"start_date": future_start, "end_date": future_end},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_offers"] == 0
        assert Decimal(data["total_amount"]) == Decimal("0")


@pytest.mark.integration
class TestOfferWorkflow:
    """End-to-end workflow tests for offers."""

    def test_create_multiple_offers_same_judgment(
        self,
        app_client: TestClient,
        test_judgment_id: int,
    ):
        """Multiple offers on same judgment should all succeed."""
        for i, (amount, offer_type) in enumerate(
            [
                ("1000.00", "purchase"),
                ("1500.00", "contingency"),
                ("2000.00", "purchase"),
            ],
            start=1,
        ):
            payload = {
                "judgment_id": test_judgment_id,
                "offer_amount": amount,
                "offer_type": offer_type,
                "operator_notes": f"Offer #{i}",
            }
            response = app_client.post("/api/v1/offers", json=payload)
            assert response.status_code == 201, f"Offer #{i} failed: {response.text}"

    def test_stats_reflect_created_offers(
        self,
        app_client: TestClient,
        test_judgment_id: int,
    ):
        """Stats should update after creating offers."""
        # Get baseline stats
        baseline = app_client.get("/api/v1/offers/stats")
        baseline_count = baseline.json()["total_offers"]

        # Create a new offer
        payload = {
            "judgment_id": test_judgment_id,
            "offer_amount": "7500.00",
            "offer_type": "purchase",
        }
        create_resp = app_client.post("/api/v1/offers", json=payload)
        assert create_resp.status_code == 201

        # Get updated stats
        updated = app_client.get("/api/v1/offers/stats")
        updated_count = updated.json()["total_offers"]

        # Count should have increased
        assert updated_count >= baseline_count + 1
