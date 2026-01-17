"""Strict log redaction for PII patterns.

This module enforces production-grade log hygiene by redacting:
- SSN-like patterns (XXX-XX-XXXX, XXXXXXXXX)
- Credit/debit card patterns (16-digit sequences with common separators)
- Email addresses (optional, for extra caution)

Usage:
    from etl.src.log_redactor import redact, SafeLogger

    # Direct redaction
    safe_msg = redact("SSN is 123-45-6789")  # "SSN is [SSN_REDACTED]"

    # Safe logger wrapper
    logger = SafeLogger(logging.getLogger(__name__))
    logger.info("Processing SSN 123-45-6789")  # Logged as "[SSN_REDACTED]"

Security Principle:
    SSNs and card numbers should NEVER appear in logs, even in dev/debug mode.
    This module provides defense-in-depth for accidental PII logging.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Pattern, Sequence, Tuple

# =============================================================================
# REDACTION PATTERNS
# =============================================================================

# SSN patterns:
# - 123-45-6789 (dashed)
# - 123 45 6789 (spaced)
# - 123456789 (9 consecutive digits, not part of larger number)
SSN_PATTERN: Pattern[str] = re.compile(
    r"""
    (?<!\d)                     # Not preceded by digit
    (?:
        \d{3}[-\s]\d{2}[-\s]\d{4}  # Dashed or spaced: 123-45-6789
        |
        \d{9}                      # 9 consecutive digits: 123456789
    )
    (?!\d)                      # Not followed by digit
    """,
    re.VERBOSE,
)

# Credit/Debit card patterns:
# - 16 digits with optional dashes/spaces every 4 digits
# - 15 digits for Amex (4-6-5 pattern)
CARD_PATTERN: Pattern[str] = re.compile(
    r"""
    (?<!\d)                                           # Not preceded by digit
    (?:
        # 16-digit patterns (Visa, MC, Discover)
        \d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}
        |
        # Amex 15-digit pattern (4-6-5)
        \d{4}[-\s]?\d{6}[-\s]?\d{5}
    )
    (?!\d)                                            # Not followed by digit
    """,
    re.VERBOSE,
)

# Email pattern (optional, conservative match)
EMAIL_PATTERN: Pattern[str] = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Phone patterns (10+ digit sequences that look like phone numbers)
# Avoid false positives on IDs/hashes by requiring common phone formats
PHONE_PATTERN: Pattern[str] = re.compile(
    r"""
    (?<!\d)
    (?:
        # (123) 456-7890
        \(\d{3}\)\s*\d{3}[-.\s]?\d{4}
        |
        # 123-456-7890 or 123.456.7890
        \d{3}[-.\s]\d{3}[-.\s]\d{4}
        |
        # +1 123 456 7890
        \+\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}
    )
    (?!\d)
    """,
    re.VERBOSE,
)

# Redaction tokens
SSN_TOKEN = "[SSN_REDACTED]"
CARD_TOKEN = "[CARD_REDACTED]"
EMAIL_TOKEN = "[EMAIL_REDACTED]"
PHONE_TOKEN = "[PHONE_REDACTED]"

# Pattern registry: (pattern, replacement)
REDACTION_PATTERNS: Sequence[Tuple[Pattern[str], str]] = [
    (SSN_PATTERN, SSN_TOKEN),
    (CARD_PATTERN, CARD_TOKEN),
    # EMAIL and PHONE are optional - uncomment if needed:
    # (EMAIL_PATTERN, EMAIL_TOKEN),
    # (PHONE_PATTERN, PHONE_TOKEN),
]


# =============================================================================
# REDACTION FUNCTIONS
# =============================================================================


def redact(
    text: str,
    *,
    redact_ssn: bool = True,
    redact_card: bool = True,
    redact_email: bool = False,
    redact_phone: bool = False,
) -> str:
    """Redact sensitive patterns from text.

    Args:
        text: Input string to redact.
        redact_ssn: Redact SSN-like patterns (default: True).
        redact_card: Redact credit card patterns (default: True).
        redact_email: Redact email addresses (default: False).
        redact_phone: Redact phone numbers (default: False).

    Returns:
        String with sensitive patterns replaced by redaction tokens.

    Examples:
        >>> redact("SSN: 123-45-6789")
        'SSN: [SSN_REDACTED]'

        >>> redact("Card: 4111-1111-1111-1111")
        'Card: [CARD_REDACTED]'
    """
    if not text:
        return text

    result = text

    if redact_ssn:
        result = SSN_PATTERN.sub(SSN_TOKEN, result)

    if redact_card:
        result = CARD_PATTERN.sub(CARD_TOKEN, result)

    if redact_email:
        result = EMAIL_PATTERN.sub(EMAIL_TOKEN, result)

    if redact_phone:
        result = PHONE_PATTERN.sub(PHONE_TOKEN, result)

    return result


def redact_dict(
    data: dict[str, Any],
    *,
    sensitive_keys: Sequence[str] | None = None,
    **redact_kwargs: bool,
) -> dict[str, Any]:
    """Recursively redact sensitive patterns from dictionary values.

    Args:
        data: Dictionary to redact.
        sensitive_keys: Keys to fully redact (e.g., ['ssn', 'card_number']).
        **redact_kwargs: Passed to redact() function.

    Returns:
        New dictionary with redacted values.
    """
    sensitive_keys = sensitive_keys or ["ssn", "ssn_last_4", "card_number", "cvv"]
    sensitive_set = {k.lower() for k in sensitive_keys}

    def _redact_value(key: str, value: Any) -> Any:
        # Fully redact known sensitive keys
        if key.lower() in sensitive_set:
            return "[REDACTED]"

        if isinstance(value, str):
            return redact(value, **redact_kwargs)
        elif isinstance(value, dict):
            return {k: _redact_value(k, v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_redact_value("", item) for item in value]
        else:
            return value

    return {k: _redact_value(k, v) for k, v in data.items()}


def contains_pii(text: str) -> bool:
    """Check if text contains any PII patterns.

    Returns:
        True if SSN or card patterns are detected.
    """
    if not text:
        return False
    return bool(SSN_PATTERN.search(text) or CARD_PATTERN.search(text))


# =============================================================================
# SAFE LOGGER WRAPPER
# =============================================================================


class SafeLogger:
    """Logger wrapper that automatically redacts PII from all messages.

    Usage:
        import logging
        from etl.src.log_redactor import SafeLogger

        _logger = logging.getLogger(__name__)
        logger = SafeLogger(_logger)

        # All log messages are automatically redacted
        logger.info("User SSN: 123-45-6789")  # Logs: "User SSN: [SSN_REDACTED]"
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        redact_ssn: bool = True,
        redact_card: bool = True,
        redact_email: bool = False,
        redact_phone: bool = False,
    ):
        self._logger = logger
        self._redact_kwargs = {
            "redact_ssn": redact_ssn,
            "redact_card": redact_card,
            "redact_email": redact_email,
            "redact_phone": redact_phone,
        }

    def _safe_format(self, msg: str, args: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
        """Redact message and args."""
        safe_msg = redact(str(msg), **self._redact_kwargs)
        safe_args = tuple(
            redact(str(arg), **self._redact_kwargs) if isinstance(arg, str) else arg for arg in args
        )
        return safe_msg, safe_args

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        safe_msg, safe_args = self._safe_format(msg, args)
        self._logger.debug(safe_msg, *safe_args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        safe_msg, safe_args = self._safe_format(msg, args)
        self._logger.info(safe_msg, *safe_args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        safe_msg, safe_args = self._safe_format(msg, args)
        self._logger.warning(safe_msg, *safe_args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        safe_msg, safe_args = self._safe_format(msg, args)
        self._logger.error(safe_msg, *safe_args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        safe_msg, safe_args = self._safe_format(msg, args)
        self._logger.critical(safe_msg, *safe_args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        safe_msg, safe_args = self._safe_format(msg, args)
        self._logger.exception(safe_msg, *safe_args, **kwargs)

    # Proxy common attributes
    @property
    def level(self) -> int:
        return self._logger.level

    @property
    def name(self) -> str:
        return self._logger.name

    def setLevel(self, level: int | str) -> None:
        self._logger.setLevel(level)

    def isEnabledFor(self, level: int) -> bool:
        return self._logger.isEnabledFor(level)


# =============================================================================
# LOGGING FILTER (alternative approach)
# =============================================================================


class PIIRedactionFilter(logging.Filter):
    """Logging filter that redacts PII from log records.

    Usage:
        import logging

        logger = logging.getLogger(__name__)
        logger.addFilter(PIIRedactionFilter())
    """

    def __init__(
        self,
        name: str = "",
        *,
        redact_ssn: bool = True,
        redact_card: bool = True,
    ):
        super().__init__(name)
        self._redact_kwargs = {
            "redact_ssn": redact_ssn,
            "redact_card": redact_card,
        }

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the message
        if isinstance(record.msg, str):
            record.msg = redact(record.msg, **self._redact_kwargs)

        # Redact args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact(str(v), **self._redact_kwargs) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact(str(arg), **self._redact_kwargs) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        return True
