"""
Tests for Smart Strategy Agent

Tests the deterministic enforcement strategy selection based on debtor intelligence.

Decision Tree:
    1. IF employer found → Wage Garnishment
    2. ELIF bank_name found → Bank Levy
    3. ELIF home_ownership = 'owner' → Property Lien
    4. ELSE → Surveillance (queue for enrichment)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from backend.workers.smart_strategy import (
    DebtorIntelligence,
    SmartStrategy,
    StrategyDecision,
    StrategyType,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_conn() -> MagicMock:
    """Create a mock database connection."""
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock()
    conn.cursor.return_value.__exit__ = MagicMock()
    return conn


@pytest.fixture
def sample_judgment_id() -> str:
    """Generate a sample judgment UUID."""
    return str(uuid.uuid4())


# =============================================================================
# DebtorIntelligence PROPERTY TESTS
# =============================================================================


class TestDebtorIntelligenceProperties:
    """Test DebtorIntelligence property methods."""

    def test_has_employer_true(self):
        """has_employer returns True when employer_name is present."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            employer_name="ACME Corp",
            employer_address="123 Main St",
        )
        assert intel.has_employer is True

    def test_has_employer_false_empty(self):
        """has_employer returns False when employer_name is empty."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            employer_name="",
        )
        assert intel.has_employer is False

    def test_has_employer_false_whitespace(self):
        """has_employer returns False when employer_name is whitespace only."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            employer_name="   ",
        )
        assert intel.has_employer is False

    def test_has_employer_false_none(self):
        """has_employer returns False when employer_name is None."""
        intel = DebtorIntelligence(judgment_id="test-id")
        assert intel.has_employer is False

    def test_has_bank_true(self):
        """has_bank returns True when bank_name is present and not benefits-only."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            bank_name="Chase Bank",
            has_benefits_only_account=False,
        )
        assert intel.has_bank is True

    def test_has_bank_false_benefits_only(self):
        """has_bank returns False when account is benefits-only (CPLR 5222(d))."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            bank_name="Chase Bank",
            has_benefits_only_account=True,
        )
        assert intel.has_bank is False

    def test_has_bank_false_empty(self):
        """has_bank returns False when bank_name is empty."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            bank_name="",
        )
        assert intel.has_bank is False

    def test_is_homeowner_true(self):
        """is_homeowner returns True when home_ownership is 'owner'."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            home_ownership="owner",
        )
        assert intel.is_homeowner is True

    def test_is_homeowner_true_case_insensitive(self):
        """is_homeowner is case insensitive."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            home_ownership="OWNER",
        )
        assert intel.is_homeowner is True

    def test_is_homeowner_false_renter(self):
        """is_homeowner returns False for renters."""
        intel = DebtorIntelligence(
            judgment_id="test-id",
            home_ownership="renter",
        )
        assert intel.is_homeowner is False


# =============================================================================
# DECISION LOGIC TESTS
# =============================================================================


class TestSmartStrategyDecision:
    """Test the decide() method with various intelligence scenarios."""

    @pytest.fixture
    def strategy(self, mock_conn: MagicMock) -> SmartStrategy:
        """Create a SmartStrategy instance with mocked connection."""
        return SmartStrategy(mock_conn)

    def test_priority_1_wage_garnishment(self, strategy: SmartStrategy, sample_judgment_id: str):
        """Employer found → Wage Garnishment (highest priority)."""
        intel = DebtorIntelligence(
            judgment_id=sample_judgment_id,
            employer_name="ACME Corporation",
            employer_address="456 Business Blvd",
            bank_name="Chase",  # Has bank too, but employer takes priority
            home_ownership="owner",  # Has property too
        )

        decision = strategy.decide(intel, sample_judgment_id)

        assert decision.strategy_type == StrategyType.WAGE_GARNISHMENT
        assert "ACME Corporation" in decision.strategy_reason
        assert "456 Business Blvd" in decision.strategy_reason

    def test_priority_2_bank_levy(self, strategy: SmartStrategy, sample_judgment_id: str):
        """Bank found (no employer) → Bank Levy."""
        intel = DebtorIntelligence(
            judgment_id=sample_judgment_id,
            bank_name="Wells Fargo",
            bank_address="789 Finance Ave",
            home_ownership="owner",  # Has property, but bank takes priority
        )

        decision = strategy.decide(intel, sample_judgment_id)

        assert decision.strategy_type == StrategyType.BANK_LEVY
        assert "Wells Fargo" in decision.strategy_reason
        assert "789 Finance Ave" in decision.strategy_reason

    def test_priority_3_property_lien(self, strategy: SmartStrategy, sample_judgment_id: str):
        """Homeowner (no employer, no bank) → Property Lien."""
        intel = DebtorIntelligence(
            judgment_id=sample_judgment_id,
            home_ownership="owner",
        )

        decision = strategy.decide(intel, sample_judgment_id)

        assert decision.strategy_type == StrategyType.PROPERTY_LIEN
        assert "homeowner" in decision.strategy_reason.lower()

    def test_priority_4_surveillance_no_intel(
        self, strategy: SmartStrategy, sample_judgment_id: str
    ):
        """No intelligence → Surveillance."""
        decision = strategy.decide(None, sample_judgment_id)

        assert decision.strategy_type == StrategyType.SURVEILLANCE
        assert (
            "queued" in decision.strategy_reason.lower()
            or "enrichment" in decision.strategy_reason.lower()
        )

    def test_priority_4_surveillance_empty_intel(
        self, strategy: SmartStrategy, sample_judgment_id: str
    ):
        """Empty intelligence → Surveillance."""
        intel = DebtorIntelligence(judgment_id=sample_judgment_id)

        decision = strategy.decide(intel, sample_judgment_id)

        assert decision.strategy_type == StrategyType.SURVEILLANCE

    def test_bank_benefits_only_skipped(self, strategy: SmartStrategy, sample_judgment_id: str):
        """Benefits-only bank account should be skipped per CPLR 5222(d)."""
        intel = DebtorIntelligence(
            judgment_id=sample_judgment_id,
            bank_name="Social Security Credit Union",
            has_benefits_only_account=True,  # Exempt!
            home_ownership="owner",
        )

        decision = strategy.decide(intel, sample_judgment_id)

        # Should fall through to property lien, not bank levy
        assert decision.strategy_type == StrategyType.PROPERTY_LIEN

    def test_renter_no_property_lien(self, strategy: SmartStrategy, sample_judgment_id: str):
        """Renter should not get property lien."""
        intel = DebtorIntelligence(
            judgment_id=sample_judgment_id,
            home_ownership="renter",
        )

        decision = strategy.decide(intel, sample_judgment_id)

        assert decision.strategy_type == StrategyType.SURVEILLANCE


# =============================================================================
# DATABASE INTEGRATION TESTS (MOCKED)
# =============================================================================


class TestSmartStrategyDatabaseOps:
    """Test database operations with mocked connection."""

    def test_fetch_debtor_intelligence_found(self, mock_conn: MagicMock, sample_judgment_id: str):
        """fetch_debtor_intelligence returns data when found."""
        # Setup mock cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "judgment_id": sample_judgment_id,
            "employer_name": "Test Corp",
            "employer_address": "123 Test St",
            "income_band": "$50k-75k",
            "bank_name": None,
            "bank_address": None,
            "home_ownership": "renter",
            "has_benefits_only_account": False,
            "confidence_score": 85.5,
            "is_verified": True,
            "data_source": "lexisnexis",
        }
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        strategy = SmartStrategy(mock_conn)
        intel = strategy.fetch_debtor_intelligence(sample_judgment_id)

        assert intel is not None
        assert intel.employer_name == "Test Corp"
        assert intel.confidence_score == 85.5
        assert intel.is_verified is True

    def test_fetch_debtor_intelligence_not_found(
        self, mock_conn: MagicMock, sample_judgment_id: str
    ):
        """fetch_debtor_intelligence returns None when not found."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        strategy = SmartStrategy(mock_conn)
        intel = strategy.fetch_debtor_intelligence(sample_judgment_id)

        assert intel is None

    def test_persist_plan(self, mock_conn: MagicMock, sample_judgment_id: str):
        """persist_plan creates enforcement plan record."""
        mock_cursor = MagicMock()
        plan_id = str(uuid.uuid4())
        mock_cursor.fetchone.return_value = (plan_id,)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        decision = StrategyDecision(
            judgment_id=sample_judgment_id,
            strategy_type=StrategyType.WAGE_GARNISHMENT,
            strategy_reason="Test reason",
        )

        strategy = SmartStrategy(mock_conn)
        result_id = strategy.persist_plan(decision)

        assert result_id == plan_id
        mock_conn.commit.assert_called_once()


# =============================================================================
# FULL EVALUATION FLOW TESTS
# =============================================================================


class TestSmartStrategyEvaluate:
    """Test the full evaluate() workflow."""

    def test_evaluate_with_employer(self, mock_conn: MagicMock, sample_judgment_id: str):
        """Full evaluation with employer data."""
        # Mock fetch returning employer data
        mock_cursor = MagicMock()
        mock_cursor.fetchone.side_effect = [
            # First call: fetch_debtor_intelligence
            {
                "judgment_id": sample_judgment_id,
                "employer_name": "Big Corp",
                "employer_address": None,
                "income_band": None,
                "bank_name": None,
                "bank_address": None,
                "home_ownership": None,
                "has_benefits_only_account": None,
                "confidence_score": None,
                "is_verified": False,
                "data_source": "manual",
            },
            # Second call: persist_plan
            (str(uuid.uuid4()),),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        strategy = SmartStrategy(mock_conn)
        decision = strategy.evaluate(sample_judgment_id, persist=True)

        assert decision.strategy_type == StrategyType.WAGE_GARNISHMENT
        assert "Big Corp" in decision.strategy_reason

    def test_evaluate_no_persist(self, mock_conn: MagicMock, sample_judgment_id: str):
        """Evaluation without persisting (dry run)."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # No intel
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        strategy = SmartStrategy(mock_conn)
        decision = strategy.evaluate(sample_judgment_id, persist=False)

        assert decision.strategy_type == StrategyType.SURVEILLANCE
        # Should NOT have called commit twice (only for fetch, not persist)
        assert mock_conn.commit.call_count == 0  # No commits in read-only mode


# =============================================================================
# STRATEGY TYPE ENUM TESTS
# =============================================================================


class TestStrategyType:
    """Test StrategyType enum values."""

    def test_enum_values(self):
        """Verify all strategy types have correct string values."""
        assert StrategyType.WAGE_GARNISHMENT.value == "wage_garnishment"
        assert StrategyType.BANK_LEVY.value == "bank_levy"
        assert StrategyType.PROPERTY_LIEN.value == "property_lien"
        assert StrategyType.SURVEILLANCE.value == "surveillance"

    def test_enum_from_string(self):
        """StrategyType can be constructed from string."""
        assert StrategyType("wage_garnishment") == StrategyType.WAGE_GARNISHMENT


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_employer_name_with_special_chars(self, mock_conn: MagicMock, sample_judgment_id: str):
        """Strategy handles employer names with special characters."""
        intel = DebtorIntelligence(
            judgment_id=sample_judgment_id,
            employer_name="O'Brien & Associates, LLC",
        )

        strategy = SmartStrategy(mock_conn)
        decision = strategy.decide(intel, sample_judgment_id)

        assert decision.strategy_type == StrategyType.WAGE_GARNISHMENT
        assert "O'Brien & Associates, LLC" in decision.strategy_reason

    def test_very_long_reason_text(self, mock_conn: MagicMock, sample_judgment_id: str):
        """Strategy handles very long employer/bank names."""
        long_name = "A" * 500
        intel = DebtorIntelligence(
            judgment_id=sample_judgment_id,
            employer_name=long_name,
        )

        strategy = SmartStrategy(mock_conn)
        decision = strategy.decide(intel, sample_judgment_id)

        assert decision.strategy_type == StrategyType.WAGE_GARNISHMENT
        assert long_name in decision.strategy_reason

    def test_unicode_in_names(self, mock_conn: MagicMock, sample_judgment_id: str):
        """Strategy handles unicode characters."""
        intel = DebtorIntelligence(
            judgment_id=sample_judgment_id,
            employer_name="日本株式会社",  # Japanese company name
        )

        strategy = SmartStrategy(mock_conn)
        decision = strategy.decide(intel, sample_judgment_id)

        assert decision.strategy_type == StrategyType.WAGE_GARNISHMENT
        assert "日本株式会社" in decision.strategy_reason
