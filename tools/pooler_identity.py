#!/usr/bin/env python3
"""
tools/pooler_identity.py
========================
Supabase Pooler Identity Contract - Core validation logic.

CANONICAL PROJECT REF: iaketsyhmqbwaabgykux

This module implements the identity contract for Supabase connection poolers:

SHARED POOLER (aws-*.pooler.supabase.com):
    - Username MUST be in format: <db_user>.<project_ref>
    - Example: postgres.iaketsyhmqbwaabgykux
    - Project ref is ONLY in the username, not the host

DEDICATED POOLER (db.<ref>.supabase.co:6543):
    - Username is plain: <db_user>
    - Example: postgres
    - Project ref is in the hostname
    - Port MUST be 6543 (port 5432 = direct connection, FORBIDDEN)

DIRECT CONNECTION (db.<ref>.supabase.co:5432):
    - Username is plain: <db_user>
    - Project ref is in the hostname
    - FORBIDDEN in production (bypasses pooler)

Error Codes:
    SHARED_POOLER_USER_MISSING_REF - Shared pooler username missing project ref
    PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER - Ref in host differs from ref in user
    DEDICATED_POOLER_HOST_REF_MISMATCH - Dedicated pooler host ref doesn't match expected
    INVALID_POOLER_MODE - Cannot determine pooler mode from DSN
    DIRECT_CONNECTION_FORBIDDEN - Direct connection (port 5432) not allowed

Author: Principal Engineer
Date: 2026-01-14
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import parse_qs, quote_plus, urlparse

# =============================================================================
# Constants
# =============================================================================

# Canonical production project ref
EXPECTED_PROJECT_REF = "iaketsyhmqbwaabgykux"

# Pooler ports
POOLER_PORT = 6543
DIRECT_PORT = 5432

# Host patterns
SHARED_POOLER_PATTERN = re.compile(r"^(aws-[a-z0-9-]+)\.pooler\.supabase\.com$")
DEDICATED_POOLER_PATTERN = re.compile(r"^db\.([a-z0-9]+)\.supabase\.co$")


# =============================================================================
# Enums
# =============================================================================


class PoolerMode(Enum):
    """Connection pooler modes."""

    SHARED = "shared"  # aws-*.pooler.supabase.com
    DEDICATED = "dedicated"  # db.<ref>.supabase.co:6543
    DIRECT = "direct"  # db.<ref>.supabase.co:5432 (FORBIDDEN)
    UNKNOWN = "unknown"


class IdentityErrorCode(Enum):
    """Pooler identity error codes."""

    VALID = "VALID"
    SHARED_POOLER_USER_MISSING_REF = "SHARED_POOLER_USER_MISSING_REF"
    PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER = "PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER"
    DEDICATED_POOLER_HOST_REF_MISMATCH = "DEDICATED_POOLER_HOST_REF_MISMATCH"
    INVALID_POOLER_MODE = "INVALID_POOLER_MODE"
    DIRECT_CONNECTION_FORBIDDEN = "DIRECT_CONNECTION_FORBIDDEN"
    MISSING_SSLMODE = "MISSING_SSLMODE"
    PARSE_ERROR = "PARSE_ERROR"


# =============================================================================
# Data classes
# =============================================================================


@dataclass
class PoolerIdentity:
    """Parsed pooler identity from DSN."""

    mode: PoolerMode
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    database: Optional[str] = None
    sslmode: Optional[str] = None

    # Extracted refs
    host_project_ref: Optional[str] = None  # From db.<ref>.supabase.co
    user_project_ref: Optional[str] = None  # From user.<ref> format
    user_base: Optional[str] = None  # Base username without ref

    # Region info (shared pooler only)
    pooler_region: Optional[str] = None  # e.g., "aws-0-us-east-1"

    def effective_project_ref(self) -> Optional[str]:
        """Get the effective project ref (from host or user)."""
        return self.host_project_ref or self.user_project_ref


@dataclass
class IdentityValidationResult:
    """Result of pooler identity validation."""

    valid: bool
    code: IdentityErrorCode
    identity: PoolerIdentity
    message: str
    suggestion: str = ""
    dsn_redacted: str = ""


# =============================================================================
# Parsing functions
# =============================================================================


def redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe logging."""
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", dsn)


def parse_pooler_identity(dsn: str) -> PoolerIdentity:
    """
    Parse DSN into pooler identity components.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        PoolerIdentity with parsed components
    """
    try:
        parsed = urlparse(dsn)
    except Exception:
        return PoolerIdentity(mode=PoolerMode.UNKNOWN)

    host = parsed.hostname
    port = parsed.port
    username = parsed.username
    database = parsed.path.lstrip("/") if parsed.path else "postgres"

    # Parse query params
    query_params = parse_qs(parsed.query)
    sslmode_list = query_params.get("sslmode", [])
    sslmode = sslmode_list[0] if sslmode_list else None

    # Initialize identity
    identity = PoolerIdentity(
        mode=PoolerMode.UNKNOWN,
        host=host,
        port=port,
        username=username,
        database=database,
        sslmode=sslmode,
    )

    if not host:
        return identity

    # Check for shared pooler: aws-*.pooler.supabase.com
    shared_match = SHARED_POOLER_PATTERN.match(host)
    if shared_match:
        identity.mode = PoolerMode.SHARED
        identity.pooler_region = shared_match.group(1)

        # For shared pooler, project ref is in username
        if username and "." in username:
            parts = username.split(".", 1)
            identity.user_base = parts[0]
            identity.user_project_ref = parts[1]
        else:
            identity.user_base = username

        return identity

    # Check for dedicated pooler / direct: db.<ref>.supabase.co
    dedicated_match = DEDICATED_POOLER_PATTERN.match(host)
    if dedicated_match:
        identity.host_project_ref = dedicated_match.group(1)
        identity.user_base = username

        # Determine mode by port
        if port == POOLER_PORT:
            identity.mode = PoolerMode.DEDICATED
        elif port == DIRECT_PORT:
            identity.mode = PoolerMode.DIRECT
        else:
            # Non-standard port on db.<ref>.supabase.co
            identity.mode = PoolerMode.UNKNOWN

        # Check if username has ref suffix (unusual for dedicated/direct)
        if username and "." in username:
            parts = username.split(".", 1)
            identity.user_base = parts[0]
            identity.user_project_ref = parts[1]

        return identity

    # Unknown host pattern
    identity.mode = PoolerMode.UNKNOWN
    identity.user_base = username

    # Still try to extract user ref if present
    if username and "." in username:
        parts = username.split(".", 1)
        identity.user_base = parts[0]
        identity.user_project_ref = parts[1]

    return identity


# =============================================================================
# Validation functions
# =============================================================================


def validate_pooler_identity(
    dsn: str,
    expected_project_ref: Optional[str] = None,
) -> IdentityValidationResult:
    """
    Validate DSN against Supabase pooler identity contract.

    Args:
        dsn: PostgreSQL connection string
        expected_project_ref: Optional expected project ref to validate against

    Returns:
        IdentityValidationResult with validation status
    """
    expected_ref = expected_project_ref or EXPECTED_PROJECT_REF
    redacted = redact_dsn(dsn)

    # Parse identity
    identity = parse_pooler_identity(dsn)

    # Check for parse failure
    if not identity.host:
        return IdentityValidationResult(
            valid=False,
            code=IdentityErrorCode.PARSE_ERROR,
            identity=identity,
            message="Could not parse host from DSN",
            suggestion="Check DSN format: postgresql://user:pass@host:port/database?sslmode=require",
            dsn_redacted=redacted,
        )

    # Check sslmode
    if identity.sslmode != "require":
        return IdentityValidationResult(
            valid=False,
            code=IdentityErrorCode.MISSING_SSLMODE,
            identity=identity,
            message=f"sslmode is '{identity.sslmode}', must be 'require'",
            suggestion="Add ?sslmode=require to your DSN",
            dsn_redacted=redacted,
        )

    # ==========================================================================
    # SHARED POOLER VALIDATION
    # ==========================================================================
    if identity.mode == PoolerMode.SHARED:
        # Rule: Username MUST have project ref suffix
        if not identity.user_project_ref:
            return IdentityValidationResult(
                valid=False,
                code=IdentityErrorCode.SHARED_POOLER_USER_MISSING_REF,
                identity=identity,
                message="Shared pooler requires username format '<user>.<project_ref>'",
                suggestion=f"Change username from '{identity.username}' to "
                f"'{identity.user_base}.{expected_ref}'",
                dsn_redacted=redacted,
            )

        # Check ref matches expected
        if identity.user_project_ref != expected_ref:
            return IdentityValidationResult(
                valid=False,
                code=IdentityErrorCode.PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER,
                identity=identity,
                message=f"Project ref in username '{identity.user_project_ref}' "
                f"does not match expected '{expected_ref}'",
                suggestion=f"Change username to '{identity.user_base}.{expected_ref}'",
                dsn_redacted=redacted,
            )

        # Valid shared pooler
        return IdentityValidationResult(
            valid=True,
            code=IdentityErrorCode.VALID,
            identity=identity,
            message=f"Valid SHARED pooler connection to project {identity.user_project_ref}",
            dsn_redacted=redacted,
        )

    # ==========================================================================
    # DEDICATED POOLER VALIDATION
    # ==========================================================================
    if identity.mode == PoolerMode.DEDICATED:
        # Check host ref matches expected
        if identity.host_project_ref != expected_ref:
            return IdentityValidationResult(
                valid=False,
                code=IdentityErrorCode.DEDICATED_POOLER_HOST_REF_MISMATCH,
                identity=identity,
                message=f"Host project ref '{identity.host_project_ref}' "
                f"does not match expected '{expected_ref}'",
                suggestion=f"Use host 'db.{expected_ref}.supabase.co'",
                dsn_redacted=redacted,
            )

        # Warn if username has ref (unusual for dedicated)
        if identity.user_project_ref:
            # Not an error, but check for mismatch
            if identity.user_project_ref != identity.host_project_ref:
                return IdentityValidationResult(
                    valid=False,
                    code=IdentityErrorCode.PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER,
                    identity=identity,
                    message=f"Project ref in username '{identity.user_project_ref}' "
                    f"does not match host ref '{identity.host_project_ref}'",
                    suggestion=f"Use plain username '{identity.user_base}' for dedicated pooler",
                    dsn_redacted=redacted,
                )

        # Valid dedicated pooler
        return IdentityValidationResult(
            valid=True,
            code=IdentityErrorCode.VALID,
            identity=identity,
            message=f"Valid DEDICATED pooler connection to project {identity.host_project_ref}",
            dsn_redacted=redacted,
        )

    # ==========================================================================
    # DIRECT CONNECTION (FORBIDDEN)
    # ==========================================================================
    if identity.mode == PoolerMode.DIRECT:
        return IdentityValidationResult(
            valid=False,
            code=IdentityErrorCode.DIRECT_CONNECTION_FORBIDDEN,
            identity=identity,
            message="Direct connections (port 5432) are FORBIDDEN in production",
            suggestion=f"Use port 6543 for dedicated pooler, or use shared pooler at "
            f"aws-0-us-east-1.pooler.supabase.com with username "
            f"'{identity.user_base}.{expected_ref}'",
            dsn_redacted=redacted,
        )

    # ==========================================================================
    # UNKNOWN MODE
    # ==========================================================================
    return IdentityValidationResult(
        valid=False,
        code=IdentityErrorCode.INVALID_POOLER_MODE,
        identity=identity,
        message=f"Cannot determine pooler mode from host '{identity.host}'",
        suggestion="Use shared pooler (aws-*.pooler.supabase.com) or "
        "dedicated pooler (db.<ref>.supabase.co:6543)",
        dsn_redacted=redacted,
    )


# =============================================================================
# Helper functions for other tools
# =============================================================================


def build_shared_pooler_dsn(
    user: str,
    password: str,
    project_ref: str,
    region: str = "aws-0-us-east-1",
    database: str = "postgres",
) -> str:
    """
    Build a shared pooler DSN with proper identity format.

    Args:
        user: Base username (e.g., "postgres", "dragonfly_app")
        password: Raw password (will be URL-encoded)
        project_ref: Supabase project reference
        region: Pooler region (default: aws-0-us-east-1)
        database: Database name (default: postgres)

    Returns:
        Properly formatted shared pooler DSN
    """
    encoded_password = quote_plus(password)
    username = f"{user}.{project_ref}"
    host = f"{region}.pooler.supabase.com"

    return f"postgresql://{username}:{encoded_password}@{host}:{POOLER_PORT}/{database}?sslmode=require"


def build_dedicated_pooler_dsn(
    user: str,
    password: str,
    project_ref: str,
    database: str = "postgres",
) -> str:
    """
    Build a dedicated pooler DSN with proper identity format.

    Args:
        user: Username (plain, no ref suffix)
        password: Raw password (will be URL-encoded)
        project_ref: Supabase project reference
        database: Database name (default: postgres)

    Returns:
        Properly formatted dedicated pooler DSN
    """
    encoded_password = quote_plus(password)
    host = f"db.{project_ref}.supabase.co"

    return f"postgresql://{user}:{encoded_password}@{host}:{POOLER_PORT}/{database}?sslmode=require"


def format_identity_error(result: IdentityValidationResult) -> str:
    """
    Format validation result as single-line FAIL message.

    Args:
        result: IdentityValidationResult

    Returns:
        Single-line error message with code and suggestion
    """
    if result.valid:
        return f"PASS: {result.message}"

    return f"FAIL [{result.code.value}]: {result.message} → {result.suggestion}"


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    """CLI entry point for standalone testing."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Validate Supabase pooler identity in DSN",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Supabase Pooler Identity Contract:

SHARED POOLER (aws-*.pooler.supabase.com):
    Username MUST be: <db_user>.<project_ref>
    Example: postgres.{EXPECTED_PROJECT_REF}

DEDICATED POOLER (db.<ref>.supabase.co:6543):
    Username is plain: <db_user>
    Example: postgres

DIRECT CONNECTION (db.<ref>.supabase.co:5432):
    FORBIDDEN in production

Error Codes:
    SHARED_POOLER_USER_MISSING_REF
    PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER
    DEDICATED_POOLER_HOST_REF_MISMATCH
    DIRECT_CONNECTION_FORBIDDEN

Expected Production Project Ref: {EXPECTED_PROJECT_REF}
""",
    )

    parser.add_argument("dsn", help="PostgreSQL connection string")
    parser.add_argument(
        "--expected-ref",
        default=EXPECTED_PROJECT_REF,
        help=f"Expected project ref (default: {EXPECTED_PROJECT_REF})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    result = validate_pooler_identity(args.dsn, args.expected_ref)

    if args.json:
        import json

        output = {
            "valid": result.valid,
            "code": result.code.value,
            "message": result.message,
            "suggestion": result.suggestion,
            "dsn_redacted": result.dsn_redacted,
            "identity": {
                "mode": result.identity.mode.value,
                "host": result.identity.host,
                "port": result.identity.port,
                "username": result.identity.username,
                "host_project_ref": result.identity.host_project_ref,
                "user_project_ref": result.identity.user_project_ref,
                "user_base": result.identity.user_base,
                "pooler_region": result.identity.pooler_region,
            },
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_identity_error(result))
        if not result.valid:
            print()
            print(f"  Mode:       {result.identity.mode.value}")
            print(f"  Host:       {result.identity.host}")
            print(f"  Port:       {result.identity.port}")
            print(f"  Username:   {result.identity.username}")
            print(f"  Host Ref:   {result.identity.host_project_ref or '(none)'}")
            print(f"  User Ref:   {result.identity.user_project_ref or '(none)'}")

    return 0 if result.valid else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
