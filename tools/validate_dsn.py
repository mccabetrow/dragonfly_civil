#!/usr/bin/env python3
"""
tools/validate_dsn.py
======================
Standalone DSN validation tool for Dragonfly Civil production deployments.

STDLIB-ONLY: No external dependencies required. Can be run anywhere Python 3.9+ exists.

SUPABASE POOLER IDENTITY CONTRACT:

SHARED POOLER (aws-*.pooler.supabase.com):
    - Username MUST be: <db_user>.<project_ref>
    - Example: postgres.iaketsyhmqbwaabgykux

DEDICATED POOLER (db.<ref>.supabase.co:6543):
    - Username is plain: <db_user>
    - Port MUST be 6543

DIRECT CONNECTION (db.<ref>.supabase.co:5432):
    - FORBIDDEN in production

Error Codes:
    PARSE_ERROR - Cannot parse DSN
    PORT_INVALID - Wrong port for pooler type
    SSLMODE_INVALID - Missing or wrong sslmode
    SHARED_POOLER_USER_MISSING_REF - Shared pooler username missing project ref
    PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER - Ref mismatch between host and user
    DEDICATED_POOLER_HOST_REF_MISMATCH - Host ref doesn't match expected
    DIRECT_CONNECTION_FORBIDDEN - Port 5432 on db.<ref>.supabase.co

Usage:
    # From environment variable
    python -m tools.validate_dsn

    # From CLI argument
    python -m tools.validate_dsn "postgresql://user:pass@host:6543/postgres?sslmode=require"

Exit Codes:
    0 - DSN is valid and meets all requirements
    1 - DSN is invalid or fails requirements
    2 - No DSN provided

Author: Principal Engineer
Date: 2026-01-14
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

# =============================================================================
# Constants
# =============================================================================

REQUIRED_PORT = 6543
DIRECT_PORT = 5432
REQUIRED_SSLMODE = "require"

# Canonical production project ref
EXPECTED_PROJECT_REF = "iaketsyhmqbwaabgykux"

# Host patterns
SHARED_POOLER_PATTERN = re.compile(r"^(aws-[a-z0-9-]+)\.pooler\.supabase\.com$")
DEDICATED_POOLER_PATTERN = re.compile(r"^db\.([a-z0-9]+)\.supabase\.co$")

ENV_VAR_NAME = "SUPABASE_DB_URL"


# =============================================================================
# Error Codes
# =============================================================================


class ErrorCode:
    """Validation error codes."""

    VALID = "VALID"
    PARSE_ERROR = "PARSE_ERROR"
    PORT_INVALID = "PORT_INVALID"
    SSLMODE_INVALID = "SSLMODE_INVALID"
    HOST_NONSTANDARD = "HOST_NONSTANDARD"
    DIRECT_CONNECTION_FORBIDDEN = "DIRECT_CONNECTION_FORBIDDEN"
    SHARED_POOLER_USER_MISSING_REF = "SHARED_POOLER_USER_MISSING_REF"
    PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER = "PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER"
    DEDICATED_POOLER_HOST_REF_MISMATCH = "DEDICATED_POOLER_HOST_REF_MISMATCH"


# =============================================================================
# Data classes
# =============================================================================


@dataclass
class ValidationResult:
    """Result of DSN validation."""

    valid: bool
    code: str
    dsn_redacted: str
    message: str = ""
    suggestion: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Parsed components
    parsed_host: Optional[str] = None
    parsed_port: Optional[int] = None
    parsed_user: Optional[str] = None
    parsed_sslmode: Optional[str] = None

    # Identity components
    pooler_mode: Optional[str] = None  # shared, dedicated, direct, unknown
    host_project_ref: Optional[str] = None
    user_project_ref: Optional[str] = None
    user_base: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "valid": self.valid,
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
            "dsn_redacted": self.dsn_redacted,
            "errors": self.errors,
            "warnings": self.warnings,
            "parsed_host": self.parsed_host,
            "parsed_port": self.parsed_port,
            "parsed_user": self.parsed_user,
            "parsed_sslmode": self.parsed_sslmode,
            "pooler_mode": self.pooler_mode,
            "host_project_ref": self.host_project_ref,
            "user_project_ref": self.user_project_ref,
            "user_base": self.user_base,
        }


# =============================================================================
# Core validation logic
# =============================================================================


def redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe logging."""
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1***REDACTED***\3", dsn)


def parse_dsn(dsn: str) -> tuple[Optional[str], Optional[int], Optional[str], dict]:
    """Parse DSN into components."""
    try:
        parsed = urlparse(dsn)
        host = parsed.hostname
        port = parsed.port
        user = parsed.username
        query_params = parse_qs(parsed.query)
        return host, port, user, query_params
    except Exception:
        return None, None, None, {}


def extract_user_components(username: str | None) -> tuple[str | None, str | None]:
    """
    Extract base user and project ref from username.

    Args:
        username: Full username (e.g., "postgres.ref" or "postgres")

    Returns:
        Tuple of (user_base, user_project_ref)
    """
    if not username:
        return None, None

    if "." in username:
        parts = username.split(".", 1)
        return parts[0], parts[1]

    return username, None


def validate_dsn(
    dsn: str,
    expected_project_ref: str | None = None,
) -> ValidationResult:
    """
    Validate a PostgreSQL DSN against production requirements and identity contract.

    Args:
        dsn: PostgreSQL connection string
        expected_project_ref: Optional expected project ref (default: production ref)

    Returns:
        ValidationResult with validation status and details
    """
    expected_ref = expected_project_ref or EXPECTED_PROJECT_REF
    errors: List[str] = []
    warnings: List[str] = []
    redacted = redact_dsn(dsn)

    # Parse DSN
    host, port, user, query_params = parse_dsn(dsn)

    if host is None:
        return ValidationResult(
            valid=False,
            code=ErrorCode.PARSE_ERROR,
            dsn_redacted=redacted,
            message="Could not parse host from DSN",
            suggestion="Check DSN format: postgresql://user:pass@host:port/database?sslmode=require",
            errors=["PARSE_ERROR: Could not parse host from DSN"],
        )

    # Extract user components
    user_base, user_project_ref = extract_user_components(user)

    # Get sslmode
    sslmode_list = query_params.get("sslmode", [])
    sslmode = sslmode_list[0] if sslmode_list else None

    # Determine pooler mode and extract host ref
    pooler_mode = "unknown"
    host_project_ref = None

    shared_match = SHARED_POOLER_PATTERN.match(host)
    if shared_match:
        pooler_mode = "shared"

    dedicated_match = DEDICATED_POOLER_PATTERN.match(host)
    if dedicated_match:
        host_project_ref = dedicated_match.group(1)
        if port == REQUIRED_PORT:
            pooler_mode = "dedicated"
        elif port == DIRECT_PORT:
            pooler_mode = "direct"
        else:
            pooler_mode = "unknown"

    # Build base result
    result = ValidationResult(
        valid=True,  # Will be set to False if any checks fail
        code=ErrorCode.VALID,
        dsn_redacted=redacted,
        parsed_host=host,
        parsed_port=port,
        parsed_user=user,
        parsed_sslmode=sslmode,
        pooler_mode=pooler_mode,
        host_project_ref=host_project_ref,
        user_project_ref=user_project_ref,
        user_base=user_base,
    )

    # ==========================================================================
    # CHECK 1: sslmode must be 'require'
    # ==========================================================================
    if sslmode != REQUIRED_SSLMODE:
        result.valid = False
        result.code = ErrorCode.SSLMODE_INVALID
        result.message = f"sslmode is '{sslmode}', must be '{REQUIRED_SSLMODE}'"
        result.suggestion = "Add ?sslmode=require to your DSN"
        errors.append(f"SSLMODE_INVALID: sslmode is '{sslmode}', must be '{REQUIRED_SSLMODE}'")
        result.errors = errors
        return result

    # ==========================================================================
    # CHECK 2: Direct connection forbidden
    # ==========================================================================
    if pooler_mode == "direct":
        result.valid = False
        result.code = ErrorCode.DIRECT_CONNECTION_FORBIDDEN
        result.message = "Direct connections (port 5432) are FORBIDDEN in production"
        result.suggestion = f"Use port 6543 for dedicated pooler, or use shared pooler with username '{user_base}.{expected_ref}'"
        errors.append(
            f"DIRECT_CONNECTION_FORBIDDEN: Host '{host}:5432' bypasses the pooler. "
            "Use port 6543 or switch to shared pooler."
        )
        result.errors = errors
        return result

    # ==========================================================================
    # CHECK 3: Port validation
    # ==========================================================================
    if port != REQUIRED_PORT:
        result.valid = False
        result.code = ErrorCode.PORT_INVALID
        result.message = f"Port is {port}, must be {REQUIRED_PORT} (Supabase pooler)"
        result.suggestion = "Change port to 6543"
        errors.append(f"PORT_INVALID: Port is {port}, must be {REQUIRED_PORT}")
        result.errors = errors
        return result

    # ==========================================================================
    # CHECK 4: Shared pooler identity validation
    # ==========================================================================
    if pooler_mode == "shared":
        # Username MUST have project ref suffix
        if not user_project_ref:
            result.valid = False
            result.code = ErrorCode.SHARED_POOLER_USER_MISSING_REF
            result.message = "Shared pooler requires username format '<user>.<project_ref>'"
            result.suggestion = f"Change username from '{user}' to '{user_base}.{expected_ref}'"
            errors.append(
                f"SHARED_POOLER_USER_MISSING_REF: Username '{user}' missing project ref. "
                f"Use '{user_base}.{expected_ref}'."
            )
            result.errors = errors
            return result

        # Check ref matches expected
        if user_project_ref != expected_ref:
            result.valid = False
            result.code = ErrorCode.PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER
            result.message = f"Project ref in username '{user_project_ref}' does not match expected '{expected_ref}'"
            result.suggestion = f"Change username to '{user_base}.{expected_ref}'"
            errors.append(
                f"PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER: Username ref '{user_project_ref}' "
                f"does not match expected '{expected_ref}'."
            )
            result.errors = errors
            return result

        # Valid shared pooler
        result.message = f"Valid SHARED pooler connection to project {user_project_ref}"
        result.errors = errors
        result.warnings = warnings
        return result

    # ==========================================================================
    # CHECK 5: Dedicated pooler identity validation
    # ==========================================================================
    if pooler_mode == "dedicated":
        # Check host ref matches expected
        if host_project_ref != expected_ref:
            result.valid = False
            result.code = ErrorCode.DEDICATED_POOLER_HOST_REF_MISMATCH
            result.message = (
                f"Host project ref '{host_project_ref}' does not match expected '{expected_ref}'"
            )
            result.suggestion = f"Use host 'db.{expected_ref}.supabase.co'"
            errors.append(
                f"DEDICATED_POOLER_HOST_REF_MISMATCH: Host ref '{host_project_ref}' "
                f"does not match expected '{expected_ref}'."
            )
            result.errors = errors
            return result

        # Check for user ref mismatch (if user has ref)
        if user_project_ref and user_project_ref != host_project_ref:
            result.valid = False
            result.code = ErrorCode.PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER
            result.message = f"Project ref in username '{user_project_ref}' does not match host ref '{host_project_ref}'"
            result.suggestion = f"Use plain username '{user_base}' for dedicated pooler"
            errors.append(
                f"PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER: Username ref '{user_project_ref}' "
                f"does not match host ref '{host_project_ref}'."
            )
            result.errors = errors
            return result

        # Warn if user has unnecessary ref suffix
        if user_project_ref:
            warnings.append(
                f"Username has project ref suffix '{user_project_ref}' which is unnecessary for dedicated pooler. "
                f"Consider using plain username '{user_base}'."
            )

        # Valid dedicated pooler
        result.message = f"Valid DEDICATED pooler connection to project {host_project_ref}"
        result.errors = errors
        result.warnings = warnings
        return result

    # ==========================================================================
    # CHECK 6: Unknown host pattern
    # ==========================================================================
    warnings.append(
        f"HOST_NONSTANDARD: Host '{host}' does not match expected patterns: "
        "*.pooler.supabase.com (shared) or db.<ref>.supabase.co:6543 (dedicated). "
        "Ensure this is intentional."
    )

    result.message = "DSN passes basic validation but host pattern is non-standard"
    result.errors = errors
    result.warnings = warnings
    return result


# =============================================================================
# CLI output formatting
# =============================================================================


def format_result(result: ValidationResult, verbose: bool = False) -> str:
    """Format validation result for CLI output."""
    lines: List[str] = []

    if result.valid:
        lines.append(f"✓ VALID [{result.code}]")
        lines.append(f"  {result.message}")
        lines.append("")
        lines.append(f"  Pooler Mode: {result.pooler_mode}")
        lines.append(f"  Host:        {result.parsed_host}")
        lines.append(f"  Port:        {result.parsed_port}")
        lines.append(f"  Username:    {result.parsed_user}")
        lines.append(f"  SSL Mode:    {result.parsed_sslmode}")

        if result.host_project_ref:
            lines.append(f"  Host Ref:    {result.host_project_ref}")
        if result.user_project_ref:
            lines.append(f"  User Ref:    {result.user_project_ref}")
    else:
        lines.append(f"✗ INVALID [{result.code}]")
        lines.append("")
        lines.append(f"  Error: {result.message}")
        lines.append(f"  Fix:   {result.suggestion}")
        lines.append("")
        lines.append("  Details:")
        for error in result.errors:
            lines.append(f"    ✗ {error}")

    if result.warnings:
        lines.append("")
        lines.append("  Warnings:")
        for warning in result.warnings:
            lines.append(f"    ⚠ {warning}")

    if verbose:
        lines.append("")
        lines.append(f"  Redacted DSN: {result.dsn_redacted}")

    return "\n".join(lines)


def format_single_line(result: ValidationResult) -> str:
    """Format result as single-line FAIL/PASS message."""
    if result.valid:
        return f"PASS [{result.code}]: {result.message}"
    return f"FAIL [{result.code}]: {result.message} → {result.suggestion}"


# =============================================================================
# CLI entry point
# =============================================================================


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate PostgreSQL DSN for Dragonfly Civil production requirements.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
SUPABASE POOLER IDENTITY CONTRACT:

  SHARED POOLER (aws-*.pooler.supabase.com):
    Username MUST be: <user>.<project_ref>
    Example: postgres.{EXPECTED_PROJECT_REF}

  DEDICATED POOLER (db.<ref>.supabase.co:6543):
    Username is plain: <user>
    Example: postgres

  DIRECT CONNECTION (port 5432):
    FORBIDDEN in production

Error Codes:
  SHARED_POOLER_USER_MISSING_REF
  PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER  
  DEDICATED_POOLER_HOST_REF_MISMATCH
  DIRECT_CONNECTION_FORBIDDEN

Expected Production Project Ref: {EXPECTED_PROJECT_REF}
        """,
    )
    parser.add_argument(
        "dsn",
        nargs="?",
        help="PostgreSQL connection string to validate",
    )
    parser.add_argument(
        "--expected-ref",
        default=EXPECTED_PROJECT_REF,
        help=f"Expected project ref (default: {EXPECTED_PROJECT_REF})",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read DSN from stdin",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show additional details",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    parser.add_argument(
        "--single-line",
        action="store_true",
        help="Output as single-line PASS/FAIL",
    )
    parser.add_argument(
        "--env-var",
        default=ENV_VAR_NAME,
        help=f"Environment variable to read DSN from (default: {ENV_VAR_NAME})",
    )

    args = parser.parse_args()

    # Get DSN from appropriate source
    dsn: Optional[str] = None

    if args.stdin:
        dsn = sys.stdin.read().strip()
    elif args.dsn:
        dsn = args.dsn.strip()
    else:
        dsn = os.environ.get(args.env_var, "").strip()

    if not dsn:
        print("ERROR: No DSN provided.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Provide DSN via:", file=sys.stderr)
        print("  1. CLI argument: python -m tools.validate_dsn 'postgresql://...'", file=sys.stderr)
        print(f"  2. Environment: {args.env_var}=postgresql://...", file=sys.stderr)
        print(
            "  3. Stdin: echo 'postgresql://...' | python -m tools.validate_dsn --stdin",
            file=sys.stderr,
        )
        return 2

    # Validate
    result = validate_dsn(dsn, args.expected_ref)

    # Output
    if args.json:
        import json

        print(json.dumps(result.to_dict(), indent=2))
    elif args.single_line:
        print(format_single_line(result))
    else:
        print(format_result(result, verbose=args.verbose))

    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
