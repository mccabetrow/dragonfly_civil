from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Sequence

import phonenumbers
from loguru import logger

DEFAULT_DATE_FORMATS: Sequence[str] = ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y")


def normalize_docket(s: str) -> str:
    """Uppercase docket/case numbers and strip non-alphanumerics."""
    if not s:
        return ""
    stripped = re.sub(r"[^0-9A-Za-z]", "", s)
    normalized = stripped.upper()
    logger.debug("normalize_docket: '%s' -> '%s'", s, normalized)
    return normalized


def normalize_phone(s: str) -> str:
    """Normalize US phone numbers using E.164 via phonenumbers."""
    if not s:
        return ""
    try:
        parsed = phonenumbers.parse(s, "US")
    except phonenumbers.NumberParseException as exc:
        logger.debug("normalize_phone: unable to parse '%s': %s", s, exc)
        return ""
    if not phonenumbers.is_possible_number(parsed):
        logger.debug("normalize_phone: not possible '%s'", s)
        return ""
    normalized = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    logger.debug("normalize_phone: '%s' -> '%s'", s, normalized)
    return normalized


def namecase(s: str) -> str:
    """Title-case names while respecting common particles (Mc, Mac, O')."""
    if not s:
        return ""
    tokens = s.strip().split()

    def _fix(token: str) -> str:
        lower = token.lower()
        if lower.startswith("mc") and len(token) > 2:
            return "Mc" + token[2:].capitalize()
        if lower.startswith("mac") and len(token) > 3:
            return "Mac" + token[3:].capitalize()
        if "'" in token:
            head, tail = token.split("'", 1)
            return head.capitalize() + "'" + tail.capitalize()
        return token.capitalize()

    normalized = " ".join(_fix(token) for token in tokens)
    logger.debug("namecase: '%s' -> '%s'", s, normalized)
    return normalized


def to_date(s: str, *, formats: Iterable[str] | None = None) -> date | None:
    """Convert strings to date objects using provided formats or ISO detection."""
    if not s:
        return None
    formats_to_try = list(formats or DEFAULT_DATE_FORMATS)
    for fmt in formats_to_try:
        try:
            parsed = datetime.strptime(s.strip(), fmt).date()
            logger.debug("to_date: '%s' -> %s (fmt=%s)", s, parsed, fmt)
            return parsed
        except ValueError:
            continue
    logger.warning("to_date: unable to parse date '%s'", s)
    return None


def validate_required(row: Dict[str, Any], fields: Sequence[str]) -> List[str]:
    """Return a list of required field names that are missing or blank."""
    missing = [field for field in fields if not (row.get(field) or "")]
    if missing:
        logger.debug("validate_required: missing=%s row=%s", missing, row)
    return missing
