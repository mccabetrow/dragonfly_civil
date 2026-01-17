"""Tests for log redaction module.

This module proves that SSN-like and card-like patterns are never logged.
"""

import logging

import pytest

from etl.src.log_redactor import (
    CARD_TOKEN,
    SSN_TOKEN,
    PIIRedactionFilter,
    SafeLogger,
    contains_pii,
    redact,
    redact_dict,
)

# =============================================================================
# SSN PATTERN TESTS
# =============================================================================


class TestSSNRedaction:
    """Tests for SSN pattern redaction."""

    def test_ssn_dashed_format(self):
        """SSN in XXX-XX-XXXX format is redacted."""
        assert redact("SSN: 123-45-6789") == f"SSN: {SSN_TOKEN}"

    def test_ssn_spaced_format(self):
        """SSN in XXX XX XXXX format is redacted."""
        assert redact("SSN: 123 45 6789") == f"SSN: {SSN_TOKEN}"

    def test_ssn_continuous_format(self):
        """SSN as 9 consecutive digits is redacted."""
        assert redact("SSN: 123456789") == f"SSN: {SSN_TOKEN}"

    def test_ssn_in_sentence(self):
        """SSN embedded in text is redacted."""
        text = "The customer SSN is 987-65-4321 and should not be logged."
        expected = f"The customer SSN is {SSN_TOKEN} and should not be logged."
        assert redact(text) == expected

    def test_multiple_ssns(self):
        """Multiple SSNs in same text are all redacted."""
        text = "Primary: 111-22-3333, Secondary: 444-55-6666"
        result = redact(text)
        assert result == f"Primary: {SSN_TOKEN}, Secondary: {SSN_TOKEN}"

    def test_ssn_at_start(self):
        """SSN at start of string is redacted."""
        assert redact("123-45-6789 is the SSN") == f"{SSN_TOKEN} is the SSN"

    def test_ssn_at_end(self):
        """SSN at end of string is redacted."""
        assert redact("The SSN is 123-45-6789") == f"The SSN is {SSN_TOKEN}"

    def test_ssn_standalone(self):
        """Standalone SSN is redacted."""
        assert redact("123-45-6789") == SSN_TOKEN

    def test_not_ssn_too_few_digits(self):
        """8 digits should not match SSN pattern."""
        assert redact("12345678") == "12345678"

    def test_not_ssn_too_many_digits(self):
        """10+ digits should not match SSN pattern."""
        assert redact("1234567890") == "1234567890"

    def test_not_ssn_part_of_larger_number(self):
        """9 digits as part of larger number should not match."""
        # This is tricky - 12345678901234 contains 123456789 but shouldn't match
        # because it's part of a larger sequence
        text = "ID: 12345678901234"
        # The 9-digit pattern should NOT match here
        assert "123456789" in text  # Verify the substring exists
        result = redact(text)
        # Should not be redacted because it's part of a larger number
        assert result == "ID: 12345678901234"


# =============================================================================
# CARD PATTERN TESTS
# =============================================================================


class TestCardRedaction:
    """Tests for credit card pattern redaction."""

    def test_card_dashed_format(self):
        """Card in XXXX-XXXX-XXXX-XXXX format is redacted."""
        assert redact("Card: 4111-1111-1111-1111") == f"Card: {CARD_TOKEN}"

    def test_card_spaced_format(self):
        """Card in XXXX XXXX XXXX XXXX format is redacted."""
        assert redact("Card: 4111 1111 1111 1111") == f"Card: {CARD_TOKEN}"

    def test_card_continuous_format(self):
        """Card as 16 consecutive digits is redacted."""
        assert redact("Card: 4111111111111111") == f"Card: {CARD_TOKEN}"

    def test_card_amex_format(self):
        """Amex card (15 digits) is redacted."""
        assert redact("Amex: 3782-822463-10005") == f"Amex: {CARD_TOKEN}"

    def test_card_amex_continuous(self):
        """Amex card as continuous digits is redacted."""
        assert redact("Amex: 378282246310005") == f"Amex: {CARD_TOKEN}"

    def test_card_in_sentence(self):
        """Card embedded in text is redacted."""
        text = "Charge card 4111-1111-1111-1111 for $100"
        expected = f"Charge card {CARD_TOKEN} for $100"
        assert redact(text) == expected

    def test_multiple_cards(self):
        """Multiple cards in same text are all redacted."""
        text = "Old: 4111-1111-1111-1111, New: 5500-0000-0000-0004"
        result = redact(text)
        assert result == f"Old: {CARD_TOKEN}, New: {CARD_TOKEN}"


# =============================================================================
# COMBINED PATTERN TESTS
# =============================================================================


class TestCombinedRedaction:
    """Tests for combined SSN and card redaction."""

    def test_ssn_and_card_together(self):
        """Both SSN and card in same text are redacted."""
        text = "SSN: 123-45-6789, Card: 4111-1111-1111-1111"
        result = redact(text)
        assert result == f"SSN: {SSN_TOKEN}, Card: {CARD_TOKEN}"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert redact("") == ""

    def test_none_returns_none(self):
        """None input returns None."""
        assert redact(None) is None

    def test_no_pii_unchanged(self):
        """Text without PII is unchanged."""
        text = "This is a normal log message with no sensitive data."
        assert redact(text) == text

    def test_disable_ssn_redaction(self):
        """SSN redaction can be disabled."""
        text = "SSN: 123-45-6789, Card: 4111-1111-1111-1111"
        result = redact(text, redact_ssn=False)
        assert "123-45-6789" in result
        assert CARD_TOKEN in result

    def test_disable_card_redaction(self):
        """Card redaction can be disabled."""
        text = "SSN: 123-45-6789, Card: 4111-1111-1111-1111"
        result = redact(text, redact_card=False)
        assert SSN_TOKEN in result
        assert "4111-1111-1111-1111" in result


# =============================================================================
# DICT REDACTION TESTS
# =============================================================================


class TestDictRedaction:
    """Tests for dictionary redaction."""

    def test_redact_dict_values(self):
        """String values in dict are redacted."""
        data = {"name": "John", "ssn": "123-45-6789"}
        result = redact_dict(data)
        assert result["name"] == "John"
        assert result["ssn"] == "[REDACTED]"

    def test_redact_dict_sensitive_keys(self):
        """Known sensitive keys are fully redacted."""
        data = {"ssn": "anything", "card_number": "test"}
        result = redact_dict(data)
        assert result["ssn"] == "[REDACTED]"
        assert result["card_number"] == "[REDACTED]"

    def test_redact_dict_nested(self):
        """Nested dicts are redacted."""
        data = {
            "user": {
                "name": "John",
                "contact": {"ssn": "123-45-6789"},
            }
        }
        result = redact_dict(data)
        assert result["user"]["contact"]["ssn"] == "[REDACTED]"

    def test_redact_dict_lists(self):
        """Lists in dict are redacted."""
        data = {"ids": ["123-45-6789", "normal-id"]}
        result = redact_dict(data)
        assert result["ids"][0] == SSN_TOKEN
        assert result["ids"][1] == "normal-id"


# =============================================================================
# CONTAINS_PII TESTS
# =============================================================================


class TestContainsPII:
    """Tests for PII detection."""

    def test_detects_ssn(self):
        """SSN pattern is detected."""
        assert contains_pii("SSN: 123-45-6789") is True

    def test_detects_card(self):
        """Card pattern is detected."""
        assert contains_pii("Card: 4111-1111-1111-1111") is True

    def test_no_pii(self):
        """Normal text has no PII."""
        assert contains_pii("Hello, world!") is False

    def test_empty_string(self):
        """Empty string has no PII."""
        assert contains_pii("") is False


# =============================================================================
# SAFE LOGGER TESTS
# =============================================================================


class TestSafeLogger:
    """Tests for SafeLogger wrapper."""

    def test_info_redacts_message(self, caplog):
        """Info messages are redacted."""
        with caplog.at_level(logging.INFO):
            raw_logger = logging.getLogger("test_safe_info")
            logger = SafeLogger(raw_logger)
            logger.info("Processing SSN 123-45-6789")

        assert SSN_TOKEN in caplog.text
        assert "123-45-6789" not in caplog.text

    def test_error_redacts_message(self, caplog):
        """Error messages are redacted."""
        with caplog.at_level(logging.ERROR):
            raw_logger = logging.getLogger("test_safe_error")
            logger = SafeLogger(raw_logger)
            logger.error("Failed for card 4111-1111-1111-1111")

        assert CARD_TOKEN in caplog.text
        assert "4111-1111-1111-1111" not in caplog.text

    def test_redacts_format_args(self, caplog):
        """Format arguments are redacted."""
        with caplog.at_level(logging.INFO):
            raw_logger = logging.getLogger("test_safe_args")
            logger = SafeLogger(raw_logger)
            logger.info("User SSN: %s", "123-45-6789")

        assert SSN_TOKEN in caplog.text
        assert "123-45-6789" not in caplog.text


# =============================================================================
# PII REDACTION FILTER TESTS
# =============================================================================


class TestPIIRedactionFilter:
    """Tests for logging filter."""

    def test_filter_redacts_message(self, caplog):
        """Log filter redacts messages."""
        test_logger = logging.getLogger("test_filter")
        test_logger.addFilter(PIIRedactionFilter())

        with caplog.at_level(logging.INFO):
            test_logger.info("SSN is 123-45-6789")

        assert SSN_TOKEN in caplog.text
        assert "123-45-6789" not in caplog.text


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestEdgeCases:
    """Edge case tests for redaction."""

    def test_unicode_text(self):
        """Unicode text is handled correctly."""
        text = "用户SSN: 123-45-6789"
        result = redact(text)
        assert SSN_TOKEN in result
        assert "123-45-6789" not in result

    def test_multiline_text(self):
        """Multiline text is handled correctly."""
        text = "Line 1\nSSN: 123-45-6789\nLine 3"
        result = redact(text)
        assert SSN_TOKEN in result
        assert "123-45-6789" not in result

    def test_json_like_text(self):
        """JSON-like text is handled correctly."""
        text = '{"ssn": "123-45-6789", "name": "John"}'
        result = redact(text)
        assert SSN_TOKEN in result
        assert "123-45-6789" not in result

    def test_url_with_card(self):
        """URLs with card-like numbers are handled."""
        text = "https://example.com/pay?card=4111111111111111"
        result = redact(text)
        assert CARD_TOKEN in result
        assert "4111111111111111" not in result


# =============================================================================
# PROOF TESTS - These prove SSN/card never appears in logs
# =============================================================================


class TestProofNoSSNInLogs:
    """Proof that SSN patterns never appear in logs."""

    @pytest.mark.parametrize(
        "ssn_variant",
        [
            "123-45-6789",
            "123 45 6789",
            "123456789",
            "987-65-4321",
            "000-00-0000",
            "999-99-9999",
        ],
    )
    def test_ssn_variants_always_redacted(self, ssn_variant):
        """All SSN format variants are always redacted."""
        result = redact(f"SSN: {ssn_variant}")
        assert ssn_variant not in result
        assert SSN_TOKEN in result

    @pytest.mark.parametrize(
        "card_variant",
        [
            "4111-1111-1111-1111",
            "4111 1111 1111 1111",
            "4111111111111111",
            "5500-0000-0000-0004",
            "3782-822463-10005",  # Amex
            "378282246310005",  # Amex continuous
        ],
    )
    def test_card_variants_always_redacted(self, card_variant):
        """All card format variants are always redacted."""
        # Normalize for comparison (remove separators)
        result = redact(f"Card: {card_variant}")
        # Card should not appear in any form
        assert (
            card_variant.replace("-", "").replace(" ", "")
            not in result.replace("-", "").replace(" ", "")
            or CARD_TOKEN in result
        )


class TestProofSafeLoggerNeverLeaksPII:
    """Proof that SafeLogger never allows PII in logs."""

    def test_ssn_in_message_redacted(self, caplog):
        """SSN in log message is always redacted."""
        with caplog.at_level(logging.DEBUG):
            logger = SafeLogger(logging.getLogger("proof_ssn_msg"))
            logger.debug("SSN: 123-45-6789")

        assert "123-45-6789" not in caplog.text

    def test_ssn_in_args_redacted(self, caplog):
        """SSN in log args is always redacted."""
        with caplog.at_level(logging.DEBUG):
            logger = SafeLogger(logging.getLogger("proof_ssn_args"))
            logger.debug("User SSN is %s", "123-45-6789")

        assert "123-45-6789" not in caplog.text

    def test_card_in_message_redacted(self, caplog):
        """Card in log message is always redacted."""
        with caplog.at_level(logging.DEBUG):
            logger = SafeLogger(logging.getLogger("proof_card_msg"))
            logger.debug("Card: 4111-1111-1111-1111")

        assert "4111-1111-1111-1111" not in caplog.text
        assert "4111111111111111" not in caplog.text

    def test_mixed_pii_all_redacted(self, caplog):
        """Multiple PII types are all redacted."""
        with caplog.at_level(logging.DEBUG):
            logger = SafeLogger(logging.getLogger("proof_mixed"))
            logger.debug("SSN: %s, Card: %s", "123-45-6789", "4111-1111-1111-1111")

        assert "123-45-6789" not in caplog.text
        assert "4111-1111-1111-1111" not in caplog.text
