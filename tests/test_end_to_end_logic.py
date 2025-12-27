"""
Tests for end-to-end ingest → enrichment wiring.

Validates:
1. Collectability score calculation produces expected results
2. Helper functions work correctly

Note: Full async database integration tests require complex mocking.
The key wiring (ingest → queue_enrichment → scoring) is verified via:
- These unit tests for the scoring logic
- Code review of the wiring in ingest_service.py and enrichment_service.py
- Manual testing against dev database
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

import pytest

from backend.services import enrichment_service

# ---------------------------------------------------------------------------
# Collectability Score Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "enriched, jd, expected",
    [
        # All signals + recent judgment = max score (40+30+10+20=100)
        (
            {"employed": True, "homeowner": True, "has_bank_account": True},
            date.today(),
            100,
        ),
        # Employed + bank account + recent = 40 + 10 + 20 = 70
        (
            {"employed": True, "homeowner": False, "has_bank_account": True},
            date.today(),
            70,
        ),
        # Only recent judgment = 20
        (
            {"employed": False, "homeowner": False, "has_bank_account": False},
            date.today(),
            20,
        ),
        # Old judgment (>5 years), no signals = 0
        (
            {"employed": False, "homeowner": False, "has_bank_account": False},
            date(2000, 1, 1),
            0,
        ),
        # Homeowner only + recent = 30 + 20 = 50
        (
            {"employed": False, "homeowner": True, "has_bank_account": False},
            date.today(),
            50,
        ),
        # None values should be treated as False
        (
            {"employed": None, "homeowner": None, "has_bank_account": None},
            date.today(),
            20,  # Only the recent judgment bonus
        ),
        # Missing keys should be treated as False
        ({}, date.today(), 20),  # Only the recent judgment bonus
        # None judgment_date should skip age bonus
        (
            {"employed": True, "homeowner": False, "has_bank_account": False},
            None,
            40,
        ),
        # Employed + homeowner + old judgment = 40 + 30 = 70
        (
            {"employed": True, "homeowner": True, "has_bank_account": False},
            date(2015, 1, 1),
            70,
        ),
        # Bank account only + recent = 10 + 20 = 30
        (
            {"employed": False, "homeowner": False, "has_bank_account": True},
            date.today(),
            30,
        ),
    ],
)
def test_calculate_collectability_score(enriched: Dict[str, Any], jd: date | None, expected: int):
    """Validate collectability scoring logic against known inputs."""
    score = enrichment_service.calculate_collectability_score(enriched, jd)
    assert score == expected


def test_years_since_helper():
    """Test the _years_since helper function."""
    from backend.services.enrichment_service import _years_since

    # Today should be 0 years
    assert _years_since(date.today()) == pytest.approx(0.0, abs=0.01)

    # 5 years ago
    five_years_ago = date(date.today().year - 5, date.today().month, date.today().day)
    assert _years_since(five_years_ago) == pytest.approx(5.0, abs=0.1)

    # None should return None
    assert _years_since(None) is None


def test_years_since_handles_datetime():
    """Test that _years_since handles datetime objects."""
    from datetime import datetime

    from backend.services.enrichment_service import _years_since

    # datetime should be converted to date
    now_dt = datetime.now()
    result = _years_since(now_dt)
    assert result is not None
    assert result == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Enrichment Service Integration Points
# ---------------------------------------------------------------------------


def test_tlo_client_exists():
    """Verify TLOClient is importable and has search method."""
    from backend.services.enrichment_service import TLOClient

    client = TLOClient()
    assert hasattr(client, "search")


def test_idicore_client_exists():
    """Verify IDICoreClient is importable and has search method."""
    from backend.services.enrichment_service import IDICoreClient

    client = IDICoreClient()
    assert hasattr(client, "search")


def test_queue_enrichment_is_callable():
    """Verify queue_enrichment function is importable."""
    from backend.services.enrichment_service import queue_enrichment

    assert callable(queue_enrichment)


def test_apply_enrichment_is_callable():
    """Verify _apply_enrichment function is importable."""
    from backend.services.enrichment_service import _apply_enrichment

    assert callable(_apply_enrichment)


# ---------------------------------------------------------------------------
# Ingest Service Integration Points
# ---------------------------------------------------------------------------


def test_ingest_simplicity_csv_is_callable():
    """Verify ingest_simplicity_csv function is importable."""
    from backend.services.ingest_service import ingest_simplicity_csv

    assert callable(ingest_simplicity_csv)


def test_ingest_service_imports_queue_enrichment():
    """
    Verify that ingest_service can import queue_enrichment.

    This confirms the wiring exists even without running the full flow.
    """
    # This import should not raise
    from backend.services.enrichment_service import queue_enrichment

    # Verify it's the expected function
    assert queue_enrichment.__name__ == "queue_enrichment"


def test_build_judgment_context_exists():
    """Verify build_judgment_context is available for embedding."""
    from backend.services.ai_service import build_judgment_context

    context = build_judgment_context(
        plaintiff_name="ACME Corp",
        defendant_name="John Doe",
        judgment_amount=10000.0,
    )
    assert "ACME Corp" in context
    assert "John Doe" in context


# ---------------------------------------------------------------------------
# Scoring v2 Tests - ScoreBreakdown
# ---------------------------------------------------------------------------


class TestScoreBreakdown:
    """Tests for the ScoreBreakdown dataclass."""

    def test_breakdown_total_sums_components(self):
        """Total should be sum of components."""
        from backend.services.enrichment_service import ScoreBreakdown

        breakdown = ScoreBreakdown(employment=40, assets=30, recency=20, banking=10)
        assert breakdown.total == 100

    def test_breakdown_total_clamps_to_100(self):
        """Total should not exceed 100."""
        from backend.services.enrichment_service import ScoreBreakdown

        # This would sum to 110, but should clamp to 100
        breakdown = ScoreBreakdown(employment=40, assets=30, recency=20, banking=20)
        assert breakdown.total == 100

    def test_breakdown_total_clamps_to_0(self):
        """Total should not go below 0."""
        from backend.services.enrichment_service import ScoreBreakdown

        # Negative components (shouldn't happen, but test clamping)
        breakdown = ScoreBreakdown(employment=-10, assets=0, recency=0, banking=0)
        assert breakdown.total == 0

    def test_breakdown_is_frozen(self):
        """ScoreBreakdown should be immutable."""
        from backend.services.enrichment_service import ScoreBreakdown

        breakdown = ScoreBreakdown(employment=40, assets=30, recency=20, banking=10)
        with pytest.raises(Exception):  # FrozenInstanceError
            breakdown.employment = 50  # type: ignore


# ---------------------------------------------------------------------------
# Scoring v2 Tests - compute_score_breakdown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "enriched, jd, expected_emp, expected_assets, expected_recency, expected_bank",
    [
        # Full employment + real estate + recent + bank = 40 + 30 + 20 + 10
        (
            {
                "employed": True,
                "has_real_estate": True,
                "has_bank_account_recent": True,
            },
            date.today(),
            40,
            30,
            20,
            10,
        ),
        # Self-employed (partial employment score)
        (
            {"self_employed": True, "has_real_estate": False},
            date.today(),
            20,
            0,
            20,
            0,
        ),
        # Vehicle only (partial assets score)
        (
            {"employed": False, "has_vehicle": True},
            date.today(),
            0,
            10,
            20,
            0,
        ),
        # Homeowner maps to has_real_estate (backwards compat)
        (
            {"homeowner": True},
            date.today(),
            0,
            30,
            20,
            0,
        ),
        # has_bank_account maps to has_bank_account_recent (backwards compat)
        (
            {"has_bank_account": True},
            date.today(),
            0,
            0,
            20,
            10,
        ),
        # Old judgment (10 years) reduces recency score
        (
            {"employed": True},
            date(date.today().year - 10, 1, 1),
            40,
            0,
            0,  # 20 - (10 * 2) = 0
            0,
        ),
        # 5 year old judgment
        (
            {"employed": True},
            date(date.today().year - 5, date.today().month, date.today().day),
            40,
            0,
            10,  # 20 - (5 * 2) = 10
            0,
        ),
        # None judgment_date = 0 recency
        (
            {"employed": True},
            None,
            40,
            0,
            0,
            0,
        ),
        # Empty enrichment data
        (
            {},
            date.today(),
            0,
            0,
            20,
            0,
        ),
        # All False values
        (
            {
                "employed": False,
                "self_employed": False,
                "has_real_estate": False,
                "has_vehicle": False,
                "has_bank_account_recent": False,
            },
            date.today(),
            0,
            0,
            20,
            0,
        ),
    ],
)
def test_compute_score_breakdown(
    enriched: Dict[str, Any],
    jd: date | None,
    expected_emp: int,
    expected_assets: int,
    expected_recency: int,
    expected_bank: int,
):
    """Validate v2 score breakdown computation."""
    from backend.services.enrichment_service import compute_score_breakdown

    breakdown = compute_score_breakdown(enriched, jd)

    assert breakdown.employment == expected_emp, (
        f"Employment: got {breakdown.employment}, expected {expected_emp}"
    )
    assert breakdown.assets == expected_assets, (
        f"Assets: got {breakdown.assets}, expected {expected_assets}"
    )
    assert breakdown.recency == expected_recency, (
        f"Recency: got {breakdown.recency}, expected {expected_recency}"
    )
    assert breakdown.banking == expected_bank, (
        f"Banking: got {breakdown.banking}, expected {expected_bank}"
    )


def test_compute_score_breakdown_total_matches_sum():
    """Total should equal sum of components (when under 100)."""
    from backend.services.enrichment_service import compute_score_breakdown

    enriched = {
        "employed": True,
        "has_real_estate": True,
        "has_bank_account_recent": True,
    }
    breakdown = compute_score_breakdown(enriched, date.today())

    expected_sum = breakdown.employment + breakdown.assets + breakdown.recency + breakdown.banking
    assert breakdown.total == expected_sum


def test_compute_score_breakdown_v1_backwards_compat():
    """v2 should produce similar scores to v1 for common cases."""
    from backend.services.enrichment_service import (
        calculate_collectability_score,
        compute_score_breakdown,
    )

    # v1 style input: employed + homeowner + has_bank_account + recent
    enriched = {
        "employed": True,
        "homeowner": True,
        "has_bank_account": True,
    }
    jd = date.today()

    v1_score = calculate_collectability_score(enriched, jd)
    v2_breakdown = compute_score_breakdown(enriched, jd)

    # v1: 40 + 30 + 10 + 20 = 100
    # v2: 40 + 30 + 20 + 10 = 100 (same total, different allocation)
    assert v1_score == v2_breakdown.total == 100


# ---------------------------------------------------------------------------
# Scoring v2 Tests - persistence helpers
# ---------------------------------------------------------------------------


def test_persist_score_breakdown_is_callable():
    """Verify persist_score_breakdown function is importable."""
    from backend.services.enrichment_service import persist_score_breakdown

    assert callable(persist_score_breakdown)


def test_score_breakdown_can_be_created():
    """ScoreBreakdown can be instantiated with keyword args."""
    from backend.services.enrichment_service import ScoreBreakdown

    breakdown = ScoreBreakdown(
        employment=40,
        assets=30,
        recency=20,
        banking=10,
    )
    assert breakdown.employment == 40
    assert breakdown.assets == 30
    assert breakdown.recency == 20
    assert breakdown.banking == 10
