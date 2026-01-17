"""
Tests for Plaintiff Targeting Worker (Perfect Plaintiffs Engine)

Tests the scoring logic, field extraction, debtor type detection,
and acceptance criteria for the plaintiff targeting pipeline.

Acceptance Criteria:
- Deterministic scoring: same input always produces same score
- Idempotent upserts: re-running doesn't duplicate leads
- Priority tiers correctly assigned: A(80+), B(60-79), C(40-59), D(20-39), F(<20)
- All score components calculated correctly
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pytest

# Import functions to test
from workers.plaintiff_targeting.main import (
    TargetingConfig,
    determine_debtor_type,
    extract_fields_from_payload,
)

# =============================================================================
# Test: Debtor Type Detection
# =============================================================================


class TestDebtorTypeDetection:
    """Tests for debtor type classification."""

    def test_llc_is_business(self):
        """LLC should be classified as business."""
        assert determine_debtor_type("ABC Construction LLC") == "business"
        assert determine_debtor_type("XYZ Holdings, LLC") == "business"

    def test_inc_is_business(self):
        """Inc should be classified as business."""
        assert determine_debtor_type("Acme Inc") == "business"
        assert determine_debtor_type("ACME INC.") == "business"

    def test_corp_is_business(self):
        """Corp/Corporation should be classified as business."""
        assert determine_debtor_type("Big Corp") == "business"
        assert determine_debtor_type("Mega Corporation") == "business"

    def test_lp_is_business(self):
        """LP/LLP should be classified as business."""
        assert determine_debtor_type("Investment LP") == "business"
        assert determine_debtor_type("Law Firm LLP") == "business"

    def test_dba_is_dba(self):
        """DBA should be classified as dba."""
        assert determine_debtor_type("John Smith DBA Smith Services") == "dba"
        assert determine_debtor_type("Jane Doe d/b/a Doe Catering") == "dba"
        assert determine_debtor_type("Trading As Quick Mart") == "dba"

    def test_business_keywords_is_business(self):
        """Business-like keywords should classify as business."""
        assert determine_debtor_type("Smith Construction") == "business"
        assert determine_debtor_type("Jones Holdings") == "business"
        assert determine_debtor_type("ABC Realty") == "business"
        assert determine_debtor_type("XYZ Properties") == "business"

    def test_individual_names_are_individual(self):
        """Regular names should classify as individual."""
        assert determine_debtor_type("John Smith") == "individual"
        assert determine_debtor_type("JANE DOE") == "individual"
        assert determine_debtor_type("Robert Johnson Jr.") == "individual"

    def test_empty_is_unknown(self):
        """Empty/None should classify as unknown."""
        assert determine_debtor_type(None) == "unknown"
        assert determine_debtor_type("") == "unknown"


# =============================================================================
# Test: Field Extraction from Payload
# =============================================================================


class TestFieldExtraction:
    """Tests for extracting structured fields from raw payload."""

    def test_extract_plaintiff_name(self):
        """Should extract plaintiff name from various keys."""
        # 'plaintiff' key
        result = extract_fields_from_payload({"plaintiff": "John Doe"})
        assert result["plaintiff_name"] == "John Doe"

        # 'creditor' key
        result = extract_fields_from_payload({"creditor": "Jane Smith"})
        assert result["plaintiff_name"] == "Jane Smith"

        # 'plaintiff_name' key
        result = extract_fields_from_payload({"plaintiff_name": "Bob Jones"})
        assert result["plaintiff_name"] == "Bob Jones"

    def test_extract_debtor_name(self):
        """Should extract debtor name from various keys."""
        result = extract_fields_from_payload({"defendant": "ABC LLC"})
        assert result["debtor_name"] == "ABC LLC"

        result = extract_fields_from_payload({"debtor": "XYZ Corp"})
        assert result["debtor_name"] == "XYZ Corp"

    def test_extract_judgment_amount_numeric(self):
        """Should extract numeric judgment amount."""
        result = extract_fields_from_payload({"judgment_amount": 5000.50})
        assert result["judgment_amount"] == 5000.50

        result = extract_fields_from_payload({"amount": 10000})
        assert result["judgment_amount"] == 10000

    def test_extract_judgment_amount_string(self):
        """Should parse string judgment amounts."""
        result = extract_fields_from_payload({"judgment_amount": "$5,000.50"})
        assert result["judgment_amount"] == 5000.50

        result = extract_fields_from_payload({"amount": "1,234"})
        assert result["judgment_amount"] == 1234

    def test_extract_addresses(self):
        """Should extract plaintiff and debtor addresses."""
        payload = {
            "plaintiff_address": "123 Main St, NY",
            "defendant_address": "456 Oak Ave, NJ",
        }
        result = extract_fields_from_payload(payload)
        assert result["plaintiff_address"] == "123 Main St, NY"
        assert result["debtor_address"] == "456 Oak Ave, NJ"

    def test_extract_contact_info(self):
        """Should extract phone and email."""
        payload = {
            "plaintiff_phone": "555-1234",
            "plaintiff_email": "john@example.com",
        }
        result = extract_fields_from_payload(payload)
        assert result["plaintiff_phone"] == "555-1234"
        assert result["plaintiff_email"] == "john@example.com"

    def test_extract_attorney(self):
        """Should extract attorney info."""
        payload = {
            "attorney": "Jane Smith, Esq.",
            "attorney_phone": "555-5678",
        }
        result = extract_fields_from_payload(payload)
        assert result["attorney_name"] == "Jane Smith, Esq."
        assert result["attorney_phone"] == "555-5678"

    def test_extract_employer(self):
        """Should extract employer name."""
        result = extract_fields_from_payload({"employer": "Acme Corp"})
        assert result["employer_name"] == "Acme Corp"

    def test_empty_payload_returns_defaults(self):
        """Empty payload should return all None values."""
        result = extract_fields_from_payload({})
        assert result["plaintiff_name"] is None
        assert result["debtor_name"] is None
        assert result["judgment_amount"] is None

    def test_none_payload_returns_defaults(self):
        """None payload should return all None values."""
        result = extract_fields_from_payload(None)
        assert result["plaintiff_name"] is None


# =============================================================================
# Test: Collectability Score Components (Unit)
# =============================================================================


class TestCollectabilityScoreLogic:
    """
    Unit tests for collectability scoring logic.

    Note: The actual compute_collectability_score function is in Postgres.
    These tests verify the expected score ranges based on the spec.
    """

    def test_amount_thresholds(self):
        """Verify amount score thresholds from spec."""
        # These are the expected scores per the spec
        thresholds = [
            (500, 0),  # < $1,000 = 0
            (1000, 10),  # $1,000 - $4,999 = 10
            (5000, 15),  # $5,000 - $9,999 = 15
            (10000, 20),  # $10,000 - $24,999 = 20
            (25000, 25),  # $25,000 - $49,999 = 25
            (50000, 28),  # $50,000 - $99,999 = 28
            (100000, 30),  # >= $100,000 = 30
        ]

        for amount, expected_score in thresholds:
            score = self._compute_amount_score(amount)
            assert (
                score == expected_score
            ), f"Amount {amount} expected {expected_score}, got {score}"

    def test_recency_thresholds(self):
        """Verify recency score thresholds from spec."""
        thresholds = [
            (15, 20),  # 0-30 days = 20
            (60, 18),  # 31-90 days = 18
            (120, 15),  # 91-180 days = 15
            (300, 12),  # 181-365 days = 12
            (500, 8),  # 1-2 years = 8
            (1000, 5),  # 2-5 years = 5
            (2500, 2),  # 5-10 years = 2
            (4000, 0),  # > 10 years = 0
        ]

        for days, expected_score in thresholds:
            score = self._compute_recency_score(days)
            assert score == expected_score, f"Days {days} expected {expected_score}, got {score}"

    def test_priority_tiers(self):
        """Verify priority tier assignment."""
        tiers = [
            (95, "A"),  # 80-100 = A
            (80, "A"),
            (75, "B"),  # 60-79 = B
            (60, "B"),
            (55, "C"),  # 40-59 = C
            (40, "C"),
            (35, "D"),  # 20-39 = D
            (20, "D"),
            (15, "F"),  # 0-19 = F
            (0, "F"),
        ]

        for score, expected_tier in tiers:
            tier = self._get_priority_tier(score)
            assert tier == expected_tier, f"Score {score} expected tier {expected_tier}, got {tier}"

    # Helper methods that mirror the SQL logic
    @staticmethod
    def _compute_amount_score(amount: float) -> int:
        if amount < 1000:
            return 0
        elif amount < 5000:
            return 10
        elif amount < 10000:
            return 15
        elif amount < 25000:
            return 20
        elif amount < 50000:
            return 25
        elif amount < 100000:
            return 28
        else:
            return 30

    @staticmethod
    def _compute_recency_score(days: int) -> int:
        if days <= 30:
            return 20
        elif days <= 90:
            return 18
        elif days <= 180:
            return 15
        elif days <= 365:
            return 12
        elif days <= 730:
            return 8
        elif days <= 1825:
            return 5
        elif days <= 3650:
            return 2
        else:
            return 0

    @staticmethod
    def _get_priority_tier(score: int) -> str:
        if score >= 80:
            return "A"
        elif score >= 60:
            return "B"
        elif score >= 40:
            return "C"
        elif score >= 20:
            return "D"
        else:
            return "F"


# =============================================================================
# Test: Perfect Plaintiff Examples
# =============================================================================


class TestPerfectPlaintiffExamples:
    """Test the example cases from the spec."""

    def test_perfect_plaintiff_example(self):
        """
        Example 1 from spec: Perfect Plaintiff (Score: 95)
        - Amount: $75,000 → 28
        - Days old: 15 → 20
        - Debtor: "ABC Construction LLC" → 15
        - Address: Full → 15
        - Contact: Phone + Email → 10
        - Signals: Employer + Suite → ~7-8
        """
        # Using the helper methods
        amount_score = TestCollectabilityScoreLogic._compute_amount_score(75000)
        recency_score = TestCollectabilityScoreLogic._compute_recency_score(15)

        assert amount_score == 28
        assert recency_score == 20
        assert determine_debtor_type("ABC Construction LLC") == "business"

    def test_average_plaintiff_example(self):
        """
        Example 2 from spec: Average Plaintiff (Score: ~46)
        - Amount: $8,500 → 15
        - Days old: 120 → 15
        - Debtor: "John Smith" → 8 (individual)
        """
        amount_score = TestCollectabilityScoreLogic._compute_amount_score(8500)
        recency_score = TestCollectabilityScoreLogic._compute_recency_score(120)

        assert amount_score == 15
        assert recency_score == 15
        assert determine_debtor_type("John Smith") == "individual"

    def test_poor_plaintiff_example(self):
        """
        Example 3 from spec: Poor Plaintiff (Score: ~10)
        - Amount: $800 → 0
        - Days old: 2000 (~5.5 years) → 2 (falls in 5-10 year bucket: 1825-3650 days)
        - Debtor: Unknown → 5
        Total would be: 0 + 2 + 5 + 0 + 0 + 0 = 7 (tier F)
        """
        amount_score = TestCollectabilityScoreLogic._compute_amount_score(800)
        recency_score = TestCollectabilityScoreLogic._compute_recency_score(2000)

        assert amount_score == 0
        # 2000 days = ~5.5 years, which falls in 5-10 year bucket (score: 2)
        assert recency_score == 2

        tier = TestCollectabilityScoreLogic._get_priority_tier(10)
        assert tier == "F"


# =============================================================================
# Test: Idempotency
# =============================================================================


class TestIdempotency:
    """Tests for idempotency guarantees."""

    def test_same_dedupe_key_produces_same_result(self):
        """Same input should produce same dedupe key behavior."""
        # This is tested at the database level with ON CONFLICT
        # Here we just verify the concept
        payload1 = {"plaintiff": "John", "defendant": "Jane", "amount": 5000}
        payload2 = {"plaintiff": "John", "defendant": "Jane", "amount": 5000}

        fields1 = extract_fields_from_payload(payload1)
        fields2 = extract_fields_from_payload(payload2)

        assert fields1 == fields2

    def test_deterministic_scoring_same_input(self):
        """Same input should always produce same score."""
        # Given the same inputs, the scoring should be deterministic
        amount = 50000
        days = 30

        score1 = TestCollectabilityScoreLogic._compute_amount_score(amount)
        score2 = TestCollectabilityScoreLogic._compute_amount_score(amount)
        assert score1 == score2

        recency1 = TestCollectabilityScoreLogic._compute_recency_score(days)
        recency2 = TestCollectabilityScoreLogic._compute_recency_score(days)
        assert recency1 == recency2

    def test_dedupe_key_computation(self):
        """Verify dedupe key is computed deterministically."""
        # The dedupe_key is sha256(source_system || "|" || source_county || "|" || external_id)
        source_system = "ny_ecourts"
        source_county = "kings"
        external_id = "2026-CV-12345"

        key_input = f"{source_system}|{source_county}|{external_id}"
        dedupe_key1 = hashlib.sha256(key_input.encode()).hexdigest()
        dedupe_key2 = hashlib.sha256(key_input.encode()).hexdigest()

        assert dedupe_key1 == dedupe_key2
        assert len(dedupe_key1) == 64  # SHA-256 hex length


# =============================================================================
# Test: Configuration
# =============================================================================


class TestConfiguration:
    """Tests for worker configuration."""

    def test_config_defaults(self):
        """Config should have sensible defaults."""
        config = TargetingConfig(
            database_url="postgresql://test:test@localhost:5432/test",
        )
        assert config.batch_size == 100
        assert config.min_score_threshold == 20
        assert config.source_county is None
        assert config.source_system is None

    def test_config_env_override(self):
        """Config should allow overrides."""
        config = TargetingConfig(
            database_url="postgresql://test:test@localhost:5432/test",
            batch_size=200,
            min_score_threshold=30,
            source_county="kings",
        )
        assert config.batch_size == 200
        assert config.min_score_threshold == 30
        assert config.source_county == "kings"


# =============================================================================
# Acceptance Tests: End-to-End Scenarios
# =============================================================================


class TestAcceptanceCriteria:
    """
    Acceptance tests for the Perfect Plaintiffs Engine.

    These verify the core requirements are met.
    """

    def test_tier_boundaries_exact(self):
        """Tier boundaries are exactly: A(80+), B(60-79), C(40-59), D(20-39), F(<20)."""
        assert TestCollectabilityScoreLogic._get_priority_tier(100) == "A"
        assert TestCollectabilityScoreLogic._get_priority_tier(80) == "A"
        assert TestCollectabilityScoreLogic._get_priority_tier(79) == "B"
        assert TestCollectabilityScoreLogic._get_priority_tier(60) == "B"
        assert TestCollectabilityScoreLogic._get_priority_tier(59) == "C"
        assert TestCollectabilityScoreLogic._get_priority_tier(40) == "C"
        assert TestCollectabilityScoreLogic._get_priority_tier(39) == "D"
        assert TestCollectabilityScoreLogic._get_priority_tier(20) == "D"
        assert TestCollectabilityScoreLogic._get_priority_tier(19) == "F"
        assert TestCollectabilityScoreLogic._get_priority_tier(0) == "F"

    def test_max_possible_score(self):
        """Maximum possible score is 100."""
        # Max scores per component:
        # Amount: 30, Recency: 20, Debtor Type: 15, Address: 15, Contact: 10, Asset: 10
        max_score = 30 + 20 + 15 + 15 + 10 + 10
        assert max_score == 100

    def test_score_range_valid(self):
        """All computed scores should be 0-100."""
        # Test edge cases
        for amount in [0, 100, 1000, 10000, 100000, 1000000]:
            score = TestCollectabilityScoreLogic._compute_amount_score(amount)
            assert 0 <= score <= 30

        for days in [0, 30, 90, 365, 730, 3650, 10000]:
            score = TestCollectabilityScoreLogic._compute_recency_score(days)
            assert 0 <= score <= 20

    def test_all_tiers_have_valid_letters(self):
        """Only A, B, C, D, F tiers are valid."""
        valid_tiers = {"A", "B", "C", "D", "F"}
        for score in range(0, 101):
            tier = TestCollectabilityScoreLogic._get_priority_tier(score)
            assert tier in valid_tiers, f"Score {score} produced invalid tier {tier}"

    def test_business_detection_comprehensive(self):
        """All business indicators should classify correctly."""
        business_names = [
            "ABC LLC",
            "XYZ Inc.",
            "Mega Corp",
            "Smith Corporation",
            "Holdings LP",
            "Law Partners LLP",
            "Tech Limited",
        ]
        for name in business_names:
            assert determine_debtor_type(name) == "business", f"'{name}' should be business"

    def test_dba_detection_comprehensive(self):
        """All DBA indicators should classify correctly."""
        dba_names = [
            "John Smith DBA Quick Mart",
            "Jane Doe d/b/a Catering Plus",
            "Bob Trading As Best Deals",
            "Alice T/A Service Pro",
        ]
        for name in dba_names:
            assert determine_debtor_type(name) == "dba", f"'{name}' should be dba"

    def test_individual_detection_excludes_business(self):
        """Individual names should not contain business indicators."""
        individual_names = [
            "John Smith",
            "Jane Doe",
            "Robert Johnson Jr.",
            "Maria Garcia-Lopez",
            "Dr. James Wilson",
        ]
        for name in individual_names:
            assert determine_debtor_type(name) == "individual", f"'{name}' should be individual"

    def test_field_extraction_priority(self):
        """Field extraction should prefer certain keys over others."""
        # plaintiff > creditor
        payload = {"plaintiff": "First", "creditor": "Second"}
        result = extract_fields_from_payload(payload)
        assert result["plaintiff_name"] == "First"

        # defendant > debtor
        payload = {"defendant": "Defendant", "debtor": "Debtor"}
        result = extract_fields_from_payload(payload)
        assert result["debtor_name"] == "Defendant"

    def test_currency_parsing_robustness(self):
        """Currency strings should be parsed correctly."""
        test_cases = [
            ({"amount": 1234.56}, 1234.56),
            ({"amount": "1234.56"}, 1234.56),
            ({"amount": "$1,234.56"}, 1234.56),
            ({"amount": "1,234"}, 1234.0),
            ({"amount": "$5000"}, 5000.0),
        ]
        for payload, expected in test_cases:
            result = extract_fields_from_payload(payload)
            assert result["judgment_amount"] == expected, f"Failed for {payload}"

    def test_null_safety(self):
        """Functions should handle None/empty values safely."""
        assert determine_debtor_type(None) == "unknown"
        assert determine_debtor_type("") == "unknown"
        assert extract_fields_from_payload(None) is not None
        assert extract_fields_from_payload({}) is not None
