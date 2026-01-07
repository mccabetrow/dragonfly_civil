"""
Dragonfly Engine - Credential Security Guard

POST-BOOTSTRAP VERIFICATION
============================

This module provides verification functions to run IMMEDIATELY after
bootstrap_environment(). It ensures credentials match the target environment.

HARD RULES:
    1. PROD environment MUST use PROD database (iaketsyhmqbwaabgykux)
    2. DEV environment should NOT use PROD database (warn only)
    3. Cross-environment mismatch = FATAL ERROR (exit 1)

Usage:
------
    from backend.core.bootstrap import bootstrap_environment
    from backend.core.security_guard import verify_safe_environment

    env_name = bootstrap_environment()
    verify_safe_environment(env_name)  # Exits if unsafe!

    # Safe to proceed...
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

# Import Discord alerting (fire-and-forget)
try:
    from backend.utils.discord import alert_config_error as _discord_alert

    _DISCORD_AVAILABLE = True
except ImportError:
    _DISCORD_AVAILABLE = False
    _discord_alert = None  # type: ignore


def _send_config_alert(
    env_name: str, error_message: str, component: str = "security_guard"
) -> None:
    """Fire-and-forget Discord alert for config errors."""
    if _DISCORD_AVAILABLE and _discord_alert:
        try:
            _discord_alert(env_name, error_message, component)
        except Exception:
            pass  # Never block on alerting


# Known Supabase project references
PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"
DEV_PROJECT_REF = "ejiddanxtqcleyswqvkc"


def _extract_project_ref(supabase_url: str | None) -> str | None:
    """
    Extract the Supabase project reference from URL.

    Args:
        supabase_url: Supabase REST URL (e.g., https://xxx.supabase.co)

    Returns:
        Project reference (subdomain) or None
    """
    if not supabase_url:
        return None

    try:
        parsed = urlparse(supabase_url)
        hostname = parsed.hostname or ""

        # Format: {project_ref}.supabase.co
        if ".supabase.co" in hostname:
            return hostname.split(".")[0]

        # Local development
        if hostname in ("localhost", "127.0.0.1"):
            return "localhost"

        return hostname
    except Exception:
        return None


def _print_critical_error(message: str) -> None:
    """Print a bright red critical error message."""
    red = "\033[91m"
    bold = "\033[1m"
    reset = "\033[0m"

    print(
        f"\n"
        f"{red}{bold}"
        f"╔══════════════════════════════════════════════════════════════════╗\n"
        f"║  🚨 CRITICAL SECURITY ERROR                                      ║\n"
        f"╠══════════════════════════════════════════════════════════════════╣\n"
        f"║                                                                  ║\n"
        f"║  {message[:62]:<62}║\n"
        f"║                                                                  ║\n"
        f"║  The application will now EXIT to prevent data corruption.      ║\n"
        f"║                                                                  ║\n"
        f"╚══════════════════════════════════════════════════════════════════╝"
        f"{reset}\n"
    )


def _print_warning(message: str) -> None:
    """Print a yellow warning message."""
    yellow = "\033[93m"
    reset = "\033[0m"

    print(
        f"\n"
        f"{yellow}"
        f"╔══════════════════════════════════════════════════════════════════╗\n"
        f"║  ⚠️  WARNING                                                      ║\n"
        f"╠══════════════════════════════════════════════════════════════════╣\n"
        f"║  {message[:62]:<62}║\n"
        f"╚══════════════════════════════════════════════════════════════════╝"
        f"{reset}\n"
    )


def _print_verified(env_name: str, project_ref: str) -> None:
    """Print a green verification message."""
    green = "\033[92m"
    reset = "\033[0m"

    print(f"{green}🛡️  Environment Verified: [{env_name.upper()}] -> Ref [{project_ref}]{reset}")


def verify_safe_environment(env_name: str, exit_on_failure: bool = True) -> bool:
    """
    Verify that credentials match the target environment.

    HARD RULES:
        1. If env_name == 'prod' AND ref != PROD_PROJECT_REF:
           → EXIT 1 immediately (CRITICAL ERROR)

        2. If env_name == 'dev' AND ref == PROD_PROJECT_REF:
           → Warn loudly but allow (read-only safety check)

        3. Otherwise:
           → Print verification success

    Args:
        env_name: The target environment ('dev' or 'prod')
        exit_on_failure: If True, sys.exit(1) on critical error

    Returns:
        True if verified safe, False otherwise

    Raises:
        SystemExit: If exit_on_failure=True and critical error detected
    """
    # Get SUPABASE_URL from environment
    supabase_url = os.environ.get("SUPABASE_URL")

    if not supabase_url:
        message = "SUPABASE_URL not set in environment!"
        if exit_on_failure:
            _print_critical_error(message)
            sys.exit(1)
        return False

    # Extract project reference
    project_ref = _extract_project_ref(supabase_url)

    if not project_ref:
        message = f"Could not extract project ref from: {supabase_url}"
        if exit_on_failure:
            _print_critical_error(message)
            sys.exit(1)
        return False

    # HARD RULE 1: PROD must use PROD database
    if env_name == "prod" and project_ref != PROD_PROJECT_REF:
        message = "ATTEMPTING TO RUN PROD AGAINST NON-PROD DATABASE"
        _print_critical_error(message)
        print(f"  Expected ref: {PROD_PROJECT_REF}")
        print(f"  Actual ref:   {project_ref}")
        print(f"  SUPABASE_URL: {supabase_url}")
        print()

        # Alert operations team
        _send_config_alert(
            env_name,
            f"PROD running against wrong database! Expected {PROD_PROJECT_REF}, got {project_ref}",
        )

        if exit_on_failure:
            sys.exit(1)
        return False

    # HARD RULE 2: DEV using PROD database - warn loudly
    if env_name == "dev" and project_ref == PROD_PROJECT_REF:
        message = "DEV environment is pointing to PRODUCTION database!"
        _print_warning(message)
        print("  This is allowed but DANGEROUS. Proceed with caution.")
        print("  All writes should be disabled or read-only mode enforced.")
        print()
        # Don't exit - allow with warning

    # Verification passed
    _print_verified(env_name, project_ref)
    return True


def verify_db_url_matches(env_name: str, exit_on_failure: bool = True) -> bool:
    """
    Additional verification: Check SUPABASE_DB_URL matches environment.

    This catches cases where SUPABASE_URL is correct but DB_URL is wrong.

    Args:
        env_name: The target environment
        exit_on_failure: If True, sys.exit(1) on critical error

    Returns:
        True if verified, False otherwise
    """
    db_url = os.environ.get("SUPABASE_DB_URL")

    if not db_url:
        # DB_URL might not be set in all contexts - just warn
        print("⚠️  SUPABASE_DB_URL not set (OK for some workers)")
        return True

    try:
        parsed = urlparse(db_url)
        db_host = parsed.hostname or ""
    except Exception:
        return True  # Can't parse, skip verification

    # Check for prod/dev mismatch
    if env_name == "prod" and DEV_PROJECT_REF in db_host:
        message = "PROD env has DEV database URL!"
        _print_critical_error(message)
        print(f"  DB Host: {db_host}")
        print(f"  Contains DEV ref: {DEV_PROJECT_REF}")
        print()

        if exit_on_failure:
            sys.exit(1)
        return False

    if env_name == "dev" and PROD_PROJECT_REF in db_host:
        message = "DEV env has PROD database URL!"
        _print_warning(message)
        # Allow with warning

    return True


def full_environment_check(env_name: str, exit_on_failure: bool = True) -> bool:
    """
    Run all environment safety checks.

    Combines:
        1. verify_safe_environment() - SUPABASE_URL check
        2. verify_db_url_matches() - SUPABASE_DB_URL check

    Args:
        env_name: The target environment
        exit_on_failure: If True, sys.exit(1) on critical error

    Returns:
        True if all checks pass
    """
    url_ok = verify_safe_environment(env_name, exit_on_failure)
    db_ok = verify_db_url_matches(env_name, exit_on_failure)

    return url_ok and db_ok


def verify_alerting_status() -> bool:
    """
    Log Discord alerting status at boot time (without leaking secrets).

    This is called after verify_safe_environment() to confirm
    whether operational alerts are wired up.

    Returns:
        True if Discord alerting is enabled, False otherwise.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")

    if webhook_url and webhook_url.startswith("http"):
        print("🔔 Discord alerts: ENABLED")
        return True
    else:
        print("🔕 Discord alerts: DISABLED (Webhook missing)")
        return False
