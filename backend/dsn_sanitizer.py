# backend/dsn_sanitizer.py
"""
DSN Sanitization and Validation for Production Safety.

Prevents malformed SUPABASE_DB_URL values from reaching psycopg:
- Strips leading/trailing whitespace
- Rejects DSNs containing internal whitespace (\\n, \\r, \\t, spaces)
- Rejects DSNs wrapped in quotes (single or double)
- Logs safe DSN components (host, port, user, dbname, sslmode) but NEVER password

Exit behavior:
- API: Returns 503 via pool health state (readiness probe fails)
- Workers: Exit code 2 (EXIT_CODE_DB_UNAVAILABLE)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

# Regex patterns for validation
INTERNAL_WHITESPACE_RE = re.compile(r"[\s]")  # Any whitespace character
QUOTE_WRAPPER_RE = re.compile(r'^["\'].*["\']$')  # Starts and ends with quotes


class DSNSanitizationError(Exception):
    """Raised when DSN sanitization fails."""

    def __init__(self, message: str, safe_dsn_info: dict | None = None):
        super().__init__(message)
        self.message = message
        self.safe_dsn_info = safe_dsn_info or {}


@dataclass
class SanitizedDSN:
    """Result of DSN sanitization."""

    dsn: str
    original_length: int
    sanitized_length: int
    stripped_leading: bool
    stripped_trailing: bool
    components: dict[str, str | None]


def _extract_safe_components(dsn: str) -> dict[str, str | None]:
    """
    Extract loggable DSN components (NEVER the password).

    Returns dict with host, port, user, dbname, sslmode.
    Returns error key if parsing fails.
    """
    try:
        parsed = urlparse(dsn)
        query_params = parse_qs(parsed.query)
        sslmode = query_params.get("sslmode", ["not_set"])[0]

        return {
            "host": parsed.hostname,
            "port": str(parsed.port) if parsed.port else "5432",
            "user": parsed.username,
            "dbname": parsed.path.lstrip("/") if parsed.path else None,
            "sslmode": sslmode,
        }
    except Exception as e:
        return {"parse_error": str(e)}


def _check_for_quotes(dsn: str) -> Optional[str]:
    """
    Check if DSN is wrapped in quotes.

    Returns error message if quotes detected, None otherwise.
    """
    dsn_stripped = dsn.strip()

    # Check for surrounding quotes (both matching)
    if QUOTE_WRAPPER_RE.match(dsn_stripped):
        quote_char = dsn_stripped[0]
        return f"DSN is wrapped in {repr(quote_char)} quotes - remove them from the environment variable"

    # Check for leading quote only
    if dsn_stripped.startswith('"') or dsn_stripped.startswith("'"):
        quote_char = dsn_stripped[0]
        return f"DSN starts with {repr(quote_char)} quote - check for malformed value"

    # Check for trailing quote only
    if dsn_stripped.endswith('"') or dsn_stripped.endswith("'"):
        quote_char = dsn_stripped[-1]
        return (
            f'DSN ends with {repr(quote_char)} quote - possible accidental suffix like " v1.3.1\'"'
        )

    return None


def _check_for_internal_whitespace(dsn: str) -> Optional[str]:
    """
    Check for whitespace characters inside the DSN (after stripping edges).

    Returns error message if internal whitespace found, None otherwise.
    """
    dsn_stripped = dsn.strip()

    # Find any whitespace characters
    for i, char in enumerate(dsn_stripped):
        if char.isspace():
            # Identify the type of whitespace
            if char == "\n":
                char_desc = "newline (\\n)"
            elif char == "\r":
                char_desc = "carriage return (\\r)"
            elif char == "\t":
                char_desc = "tab (\\t)"
            elif char == " ":
                char_desc = "space"
            else:
                char_desc = f"whitespace (ord={ord(char)})"

            return (
                f"DSN contains {char_desc} at position {i} - "
                f"this indicates a malformed connection string"
            )

    return None


def sanitize_dsn(dsn: str | None, raise_on_error: bool = True) -> SanitizedDSN:
    """
    Sanitize and validate a PostgreSQL DSN.

    Performs:
    1. Strips leading/trailing whitespace
    2. Rejects DSNs with internal whitespace (\\n, \\r, \\t, spaces)
    3. Rejects DSNs wrapped in quotes
    4. Extracts safe components for logging (never password)

    Args:
        dsn: Raw DSN from environment variable
        raise_on_error: If True, raise DSNSanitizationError on failure

    Returns:
        SanitizedDSN with clean DSN and metadata

    Raises:
        DSNSanitizationError: If validation fails and raise_on_error=True
    """
    if dsn is None:
        if raise_on_error:
            raise DSNSanitizationError("DSN is None - SUPABASE_DB_URL environment variable not set")
        # Return a dummy result for None case
        return SanitizedDSN(
            dsn="",
            original_length=0,
            sanitized_length=0,
            stripped_leading=False,
            stripped_trailing=False,
            components={},
        )

    original_length = len(dsn)

    # Step 1: Strip leading/trailing whitespace
    stripped_dsn = dsn.strip()
    stripped_leading = dsn != dsn.lstrip()
    stripped_trailing = dsn != dsn.rstrip()

    # Log if stripping occurred (common misconfiguration)
    if stripped_leading or stripped_trailing:
        # This is a warning, not an error - we fix it
        pass

    # Step 2: Check for surrounding quotes (REJECT)
    quote_error = _check_for_quotes(stripped_dsn)
    if quote_error:
        safe_info = _extract_safe_components(stripped_dsn.strip("\"'"))
        if raise_on_error:
            raise DSNSanitizationError(quote_error, safe_dsn_info=safe_info)

    # Step 3: Check for internal whitespace (REJECT)
    whitespace_error = _check_for_internal_whitespace(stripped_dsn)
    if whitespace_error:
        safe_info = _extract_safe_components(
            stripped_dsn.split()[0] if stripped_dsn.split() else ""
        )
        if raise_on_error:
            raise DSNSanitizationError(whitespace_error, safe_dsn_info=safe_info)

    # Step 4: Extract safe components
    components = _extract_safe_components(stripped_dsn)

    return SanitizedDSN(
        dsn=stripped_dsn,
        original_length=original_length,
        sanitized_length=len(stripped_dsn),
        stripped_leading=stripped_leading,
        stripped_trailing=stripped_trailing,
        components=components,
    )


def log_sanitization_result(
    result: SanitizedDSN,
    context: str = "database",
    logger_func=None,
) -> None:
    """
    Log sanitization results with safe DSN components.

    Args:
        result: SanitizedDSN from sanitize_dsn()
        context: Context string for log message (e.g., 'API pool', 'worker')
        logger_func: Optional logger function (defaults to print)
    """
    log = logger_func or print

    # Log stripped whitespace as warning
    if result.stripped_leading or result.stripped_trailing:
        stripped_parts = []
        if result.stripped_leading:
            stripped_parts.append("leading")
        if result.stripped_trailing:
            stripped_parts.append("trailing")
        stripped_desc = " and ".join(stripped_parts)
        log(
            f"[{context}] DSN: Stripped {stripped_desc} whitespace "
            f"(original={result.original_length}, sanitized={result.sanitized_length})"
        )

    # Log safe components
    c = result.components
    if "parse_error" not in c:
        log(
            f"[{context}] DSN components: "
            f"host={c.get('host')}, port={c.get('port')}, "
            f"user={c.get('user')}, dbname={c.get('dbname')}, "
            f"sslmode={c.get('sslmode')}"
        )
    else:
        log(f"[{context}] DSN parse error: {c.get('parse_error')}")


# =============================================================================
# Convenience functions for API and Worker integration
# =============================================================================


def sanitize_and_log(
    dsn: str | None,
    context: str,
    logger_info=None,
    logger_error=None,
    logger_warning=None,
) -> str:
    """
    Sanitize DSN, log results, and return clean DSN.

    Raises DSNSanitizationError on failure with detailed message.

    Args:
        dsn: Raw DSN from environment
        context: Context for log messages (e.g., 'init_db_pool', 'worker:ingest')
        logger_info: Info-level logger function
        logger_error: Error-level logger function
        logger_warning: Warning-level logger function

    Returns:
        Sanitized DSN string

    Raises:
        DSNSanitizationError: If DSN is invalid
    """
    log_info = logger_info or (lambda msg, **kw: None)
    log_error = logger_error or (lambda msg, **kw: None)
    log_warning = logger_warning or (lambda msg, **kw: None)

    try:
        result = sanitize_dsn(dsn, raise_on_error=True)

        # Log stripping warnings
        if result.stripped_leading or result.stripped_trailing:
            stripped_parts = []
            if result.stripped_leading:
                stripped_parts.append("leading")
            if result.stripped_trailing:
                stripped_parts.append("trailing")
            log_warning(
                f"DSN whitespace stripped ({' and '.join(stripped_parts)})",
                context=context,
                original_length=result.original_length,
                sanitized_length=result.sanitized_length,
            )

        # Log safe components
        c = result.components
        log_info(
            "DSN validated",
            context=context,
            host=c.get("host"),
            port=c.get("port"),
            user=c.get("user"),
            dbname=c.get("dbname"),
            sslmode=c.get("sslmode"),
        )

        return result.dsn

    except DSNSanitizationError as e:
        log_error(
            f"DSN sanitization failed: {e.message}",
            context=context,
            safe_components=e.safe_dsn_info,
        )
        raise
