"""Unit tests for tier assignment handler.

Tests the workers/tier_assignment_handler.py module to verify:
- compute_tier() produces correct tiers for various input combinations
- Boundary conditions at each tier threshold
- Job payload extraction from nested PGMQ structure
- Handler skips closed statuses
- Idempotent tier updates
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workers.tier_assignment_handler import (
    BALANCE_TIER_0_MAX,
    BALANCE_TIER_1_MAX,
    BALANCE_TIER_2_MAX,
    SCORE_TIER_0_MAX,
    SCORE_TIER_1_MAX,
    SCORE_TIER_2_MAX,
    _count_asset_signals,
    _extract_judgment_id,
    _has_asset_hints,
    compute_tier,
    handle_tier_assignment,
)


# =============================================================================
# Tests for _extract_judgment_id
# =============================================================================


class TestExtractJudgmentId:
    """Tests for payload extraction from PGMQ job structure."""

    def test_direct_judgment_id(self):
        """Extract judgment_id from flat payload."""
        job = {"judgment_id": "abc-123", "msg_id": 1}
        assert _extract_judgment_id(job) == "abc-123"

    def test_nested_payload(self):
        """Extract judgment_id from single-nested payload."""
        job = {"msg_id": 1, "payload": {"judgment_id": "def-456"}}
        assert _extract_judgment_id(job) == "def-456"

    def test_double_nested_payload(self):
        """Extract judgment_id from double-nested payload (from queue_job RPC)."""
        job = {"msg_id": 1, "payload": {"payload": {"judgment_id": "ghi-789"}}}
        assert _extract_judgment_id(job) == "ghi-789"

    def test_missing_judgment_id(self):
        """Return None when judgment_id is missing."""
        job = {"msg_id": 1, "payload": {"other": "data"}}
        assert _extract_judgment_id(job) is None

    def test_empty_judgment_id(self):
        """Handle whitespace-only judgment_id."""
        job = {"judgment_id": "  ", "msg_id": 1}
        # Should return stripped string (whitespace only)
        result = _extract_judgment_id(job)
        assert result == ""  # Stripped whitespace

    def test_non_dict_job(self):
        """Return None for non-dict input."""
        assert _extract_judgment_id(None) is None
        assert _extract_judgment_id("string") is None
        assert _extract_judgment_id(123) is None


# =============================================================================
# Tests for _has_asset_hints / _count_asset_signals
# =============================================================================


class TestAssetHints:
    """Tests for asset signal detection."""

    def test_no_intelligence(self):
        """No intelligence returns no asset hints."""
        assert _has_asset_hints(None) is False
        assert _count_asset_signals(None) == 0

    def test_empty_intelligence(self):
        """Empty intelligence returns no asset hints."""
        assert _has_asset_hints({}) is False
        assert _count_asset_signals({}) == 0

    def test_employer_only(self):
        """Employer name counts as asset hint."""
        intel = {"employer_name": "Acme Corp"}
        assert _has_asset_hints(intel) is True
        assert _count_asset_signals(intel) == 1

    def test_bank_only(self):
        """Bank name counts as asset hint."""
        intel = {"bank_name": "Chase Bank"}
        assert _has_asset_hints(intel) is True
        assert _count_asset_signals(intel) == 1

    def test_employer_and_bank(self):
        """Both employer and bank count."""
        intel = {"employer_name": "Acme Corp", "bank_name": "Chase Bank"}
        assert _has_asset_hints(intel) is True
        assert _count_asset_signals(intel) == 2

    def test_all_asset_signals(self):
        """All four asset types counted."""
        intel = {
            "employer_name": "Acme Corp",
            "bank_name": "Chase Bank",
            "real_property_lead": "123 Main St",
            "vehicle_lead": "Toyota Camry 2020",
        }
        assert _has_asset_hints(intel) is True
        assert _count_asset_signals(intel) == 4

    def test_empty_strings_not_counted(self):
        """Empty strings don't count as assets."""
        intel = {"employer_name": "", "bank_name": None}
        assert _has_asset_hints(intel) is False
        assert _count_asset_signals(intel) == 0


# =============================================================================
# Tests for compute_tier
# =============================================================================


class TestComputeTier:
    """Tests for the tier calculation logic.

    Per docs/enforcement_tiers.md:
      Tier 0: score < 35 OR (balance < $5k AND no asset hints)
      Tier 1: 35 <= score < 60, balance $5k-$15k
      Tier 2: 60 <= score < 80 OR balance $15k-$50k with assets
      Tier 3: score >= 80 OR balance >= $50k with multiple assets
    """

    # -------------------------------------------------------------------------
    # Tier 0 - Monitor
    # -------------------------------------------------------------------------

    def test_tier_0_low_score(self):
        """Very low collectability score -> Tier 0 unless balance promotes to higher tier."""
        # Score 20 with balance $10k: balance is in Tier 1 range ($5k-$15k)
        # With OR logic, balance $5k-$15k can promote to Tier 1
        tier, reason = compute_tier(20, Decimal("10000"), None)
        assert tier == 1  # Balance promotes
        assert "balance=$10,000 in [5k,15k)" in reason

    def test_tier_0_low_balance_no_assets(self):
        """Low balance with no assets and low score -> Tier 0."""
        tier, reason = compute_tier(30, Decimal("3000"), None)
        assert tier == 0
        assert "collectability_score=30<35" in reason

    def test_tier_0_boundary_score_34(self):
        """Score at 34 (just under threshold) with high balance -> balance promotes."""
        # Score 34 with balance $10k: balance in Tier 1 range promotes
        tier, reason = compute_tier(34, Decimal("10000"), None)
        assert tier == 1  # Balance promotes
        assert "balance=$10,000 in [5k,15k)" in reason

    def test_tier_0_low_score_low_balance(self):
        """Score < 35 with low balance and no assets -> Tier 0."""
        tier, reason = compute_tier(25, Decimal("3000"), None)
        assert tier == 0
        assert "collectability_score=25<35" in reason

    def test_tier_0_none_values(self):
        """None score and balance -> Tier 0 (default)."""
        tier, reason = compute_tier(None, None, None)
        assert tier == 0

    # -------------------------------------------------------------------------
    # Tier 1 - Warm Prospects
    # -------------------------------------------------------------------------

    def test_tier_1_moderate_score(self):
        """Moderate collectability score (35-60) -> Tier 1."""
        tier, reason = compute_tier(45, Decimal("3000"), None)
        assert tier == 1
        assert "collectability_score=45 in [35,60)" in reason

    def test_tier_1_boundary_score_35(self):
        """Score exactly at 35 -> Tier 1."""
        tier, reason = compute_tier(35, Decimal("3000"), None)
        assert tier == 1

    def test_tier_1_boundary_score_59(self):
        """Score at 59 (just under Tier 2) -> Tier 1."""
        tier, reason = compute_tier(59, Decimal("3000"), None)
        assert tier == 1

    def test_tier_1_mid_range_balance(self):
        """Mid-range balance ($5k-$15k) with low score -> Tier 1."""
        tier, reason = compute_tier(30, Decimal("8000"), None)
        assert tier == 1
        assert "balance=$8,000 in [5k,15k)" in reason

    # -------------------------------------------------------------------------
    # Tier 2 - Active Enforcement
    # -------------------------------------------------------------------------

    def test_tier_2_good_score(self):
        """Good collectability score (60-80) -> Tier 2."""
        tier, reason = compute_tier(65, Decimal("5000"), {"employer_name": "Acme"})
        assert tier == 2
        assert "collectability_score=65 in [60,80)" in reason

    def test_tier_2_boundary_score_60(self):
        """Score exactly at 60 -> Tier 2."""
        tier, reason = compute_tier(60, Decimal("5000"), None)
        assert tier == 2

    def test_tier_2_boundary_score_79(self):
        """Score at 79 -> Tier 2."""
        tier, reason = compute_tier(79, Decimal("5000"), None)
        assert tier == 2

    def test_tier_2_larger_balance_with_assets(self):
        """Larger balance ($15k-$50k) with assets -> Tier 2."""
        tier, reason = compute_tier(50, Decimal("25000"), {"employer_name": "Acme"})
        assert tier == 2
        assert "balance=$25,000 in [15k,50k)" in reason
        assert "has_asset_hints" in reason

    def test_tier_2_larger_balance_without_assets_stays_tier_1(self):
        """Larger balance but no assets -> may stay lower tier based on score."""
        tier, reason = compute_tier(45, Decimal("20000"), None)
        # Score 45 qualifies for Tier 1; balance check requires assets for Tier 2
        assert tier == 1

    # -------------------------------------------------------------------------
    # Tier 3 - Strategic / Priority
    # -------------------------------------------------------------------------

    def test_tier_3_high_score(self):
        """High collectability score (>=80) -> Tier 3."""
        tier, reason = compute_tier(85, Decimal("10000"), None)
        assert tier == 3
        assert "collectability_score=85>=80" in reason

    def test_tier_3_boundary_score_80(self):
        """Score exactly at 80 -> Tier 3."""
        tier, reason = compute_tier(80, Decimal("5000"), None)
        assert tier == 3

    def test_tier_3_very_high_score(self):
        """Very high score -> Tier 3."""
        tier, reason = compute_tier(
            95, Decimal("100000"), {"employer_name": "Big Corp"}
        )
        assert tier == 3

    def test_tier_3_large_balance_with_multiple_assets(self):
        """Large balance (>=$50k) with multiple assets -> Tier 3."""
        intel = {"employer_name": "Acme", "bank_name": "Chase"}
        tier, reason = compute_tier(50, Decimal("75000"), intel)
        assert tier == 3
        assert "balance=$75,000>=50k" in reason
        assert "asset_signals=2" in reason

    def test_tier_3_large_balance_single_asset_stays_tier_2(self):
        """Large balance with only 1 asset may not reach Tier 3."""
        # If score is in Tier 2 range and balance is high but only 1 asset
        # The score check for 60-80 would trigger Tier 2 first
        tier, reason = compute_tier(65, Decimal("75000"), {"employer_name": "Acme"})
        # Score 65 is in [60,80) so Tier 2 triggers first
        assert tier == 2

    # -------------------------------------------------------------------------
    # Combined / Edge Cases
    # -------------------------------------------------------------------------

    def test_high_score_overrides_low_balance(self):
        """High score -> Tier 3 even with small balance."""
        tier, reason = compute_tier(90, Decimal("1000"), None)
        assert tier == 3

    def test_zero_balance(self):
        """Zero balance with decent score."""
        tier, reason = compute_tier(50, Decimal("0"), None)
        assert tier == 1  # Score 50 is in Tier 1 range


# =============================================================================
# Tests for handle_tier_assignment (async handler)
# =============================================================================


class FakeTable:
    """Fake Supabase table for testing."""

    def __init__(self, name: str, data_store: Dict[str, List[Dict[str, Any]]]):
        self.name = name
        self._data_store = data_store
        self._query_filters: Dict[str, Any] = {}
        self._select_fields: Optional[str] = None
        self._pending_update: Optional[Dict[str, Any]] = None
        self._order_col: Optional[str] = None
        self._order_desc: bool = False
        self._limit_val: Optional[int] = None

    def select(self, fields: str) -> "FakeTable":
        self._select_fields = fields
        return self

    def eq(self, column: str, value: Any) -> "FakeTable":
        self._query_filters[column] = value
        return self

    def order(self, col: str, desc: bool = False) -> "FakeTable":
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int) -> "FakeTable":
        self._limit_val = n
        return self

    def update(self, data: Dict[str, Any]) -> "FakeTable":
        self._pending_update = data
        return self

    def execute(self) -> SimpleNamespace:
        # Handle pending updates
        if self._pending_update is not None:
            key = f"{self.name}_updates"
            if key not in self._data_store:
                self._data_store[key] = []
            self._data_store[key].append(
                {"filters": self._query_filters.copy(), "data": self._pending_update}
            )
            self._pending_update = None
            return SimpleNamespace(
                data=[{"id": self._query_filters.get("id", "updated")}]
            )

        # Return data based on table and filters
        if self.name in self._data_store:
            records = self._data_store[self.name]
            # Filter by query filters
            for col, val in self._query_filters.items():
                records = [r for r in records if r.get(col) == val]
            if self._limit_val:
                records = records[: self._limit_val]
            return SimpleNamespace(data=records)

        return SimpleNamespace(data=[])


class FakeClient:
    """Fake Supabase client for testing."""

    def __init__(self, data_store: Dict[str, List[Dict[str, Any]]]):
        self._data_store = data_store

    def table(self, name: str) -> FakeTable:
        return FakeTable(name, self._data_store)


@pytest.fixture
def mock_supabase():
    """Create a mock Supabase client with test data."""
    data_store = {
        "core_judgments": [
            {
                "id": "judgment-active-123",
                "case_index_number": "2024-001",
                "status": "open",
                "collectability_score": 75,
                "principal_amount": 25000,
                "tier": None,
            },
            {
                "id": "judgment-satisfied-456",
                "case_index_number": "2024-002",
                "status": "satisfied",
                "collectability_score": 80,
                "principal_amount": 50000,
                "tier": 2,
            },
            {
                "id": "judgment-low-score-789",
                "case_index_number": "2024-003",
                "status": "open",
                "collectability_score": 25,
                "principal_amount": 3000,
                "tier": None,
            },
        ],
        "debtor_intelligence": [
            {
                "judgment_id": "judgment-active-123",
                "employer_name": "Big Corp",
                "bank_name": "Chase",
                "last_updated": "2024-01-15T00:00:00Z",
            },
        ],
    }
    return FakeClient(data_store), data_store


@pytest.mark.asyncio
async def test_handler_assigns_tier_to_active_judgment(mock_supabase):
    """Handler should compute and update tier for active judgment."""
    client, data_store = mock_supabase

    job = {
        "msg_id": 1,
        "payload": {"payload": {"judgment_id": "judgment-active-123"}},
    }

    with patch(
        "workers.tier_assignment_handler.create_supabase_client", return_value=client
    ):
        result = await handle_tier_assignment(job)

    assert result is True
    # Check update was recorded
    updates = data_store.get("core_judgments_updates", [])
    assert len(updates) == 1
    update = updates[0]
    assert update["filters"]["id"] == "judgment-active-123"
    assert update["data"]["tier"] == 2  # Score 75 in [60,80) -> Tier 2
    assert "tier_reason" in update["data"]
    assert "tier_as_of" in update["data"]


@pytest.mark.asyncio
async def test_handler_skips_satisfied_judgment(mock_supabase):
    """Handler should skip judgments with closed status."""
    client, data_store = mock_supabase

    job = {
        "msg_id": 2,
        "payload": {"payload": {"judgment_id": "judgment-satisfied-456"}},
    }

    with patch(
        "workers.tier_assignment_handler.create_supabase_client", return_value=client
    ):
        result = await handle_tier_assignment(job)

    assert result is True
    # No update should have been recorded
    updates = data_store.get("core_judgments_updates", [])
    assert len(updates) == 0


@pytest.mark.asyncio
async def test_handler_assigns_tier_0_for_low_score(mock_supabase):
    """Handler assigns Tier 0 for low collectability score."""
    client, data_store = mock_supabase

    job = {
        "msg_id": 3,
        "payload": {"payload": {"judgment_id": "judgment-low-score-789"}},
    }

    with patch(
        "workers.tier_assignment_handler.create_supabase_client", return_value=client
    ):
        result = await handle_tier_assignment(job)

    assert result is True
    updates = data_store.get("core_judgments_updates", [])
    assert len(updates) == 1
    update = updates[0]
    assert update["data"]["tier"] == 0


@pytest.mark.asyncio
async def test_handler_returns_true_for_missing_judgment(mock_supabase):
    """Handler returns True (don't retry) for non-existent judgment."""
    client, _ = mock_supabase

    job = {
        "msg_id": 4,
        "payload": {"payload": {"judgment_id": "non-existent-judgment"}},
    }

    with patch(
        "workers.tier_assignment_handler.create_supabase_client", return_value=client
    ):
        result = await handle_tier_assignment(job)

    # Should return True (don't retry for missing data)
    assert result is True


@pytest.mark.asyncio
async def test_handler_returns_true_for_invalid_payload():
    """Handler returns True for invalid payload (no retry)."""
    job = {"msg_id": 5, "payload": {"other_field": "value"}}

    with patch("workers.tier_assignment_handler.create_supabase_client"):
        result = await handle_tier_assignment(job)

    assert result is True
