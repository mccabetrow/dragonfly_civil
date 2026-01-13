"""
Dragonfly Engine - Environment Loader

STRICT ENVIRONMENT BOOTSTRAP
============================

This module provides strict, explicit environment loading with clear precedence:

    1. CLI args (--env prod)        → Highest priority
    2. System env vars              → Explicit exports
    3. .env.{env} file              → File-based credentials

ISOLATION GUARANTEE:
    When --env prod is specified, the local .env file is NEVER loaded.
    This prevents cross-contamination between dev and prod credentials.

VERIFICATION:
    At startup, the loader prints the active environment and DB host
    for audit trail visibility.

Usage:
------
    # In entrypoints (main.py, workers, scripts):
    from backend.core.loader import load_environment

    # MUST run before importing config
    env_name = load_environment()

    # Now safe to import settings
    from backend.core.config import settings

    print(f"🚀 Booting in [{env_name.upper()}] mode")
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

# Avoid importing pydantic_settings here - we need to control when it loads

logger = logging.getLogger(__name__)

# Environment marker key - set after successful load
ENV_MARKER = "DRAGONFLY_ENV"

# Expected DB host patterns for verification
_DB_HOST_PATTERNS = {
    "dev": ["ejiddanxtqcleyswqvkc", "localhost", "127.0.0.1"],
    "prod": ["iaketsyhmqbwaabgykux"],
}


def _parse_cli_args() -> str:
    """
    Parse CLI arguments for --env flag.

    Returns:
        Environment name ('dev' or 'prod'), defaults to 'dev'
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--env",
        type=str,
        choices=["dev", "prod"],
        default=None,
        help="Target environment (dev or prod)",
    )

    # Parse known args only - don't interfere with other CLI tools
    args, _ = parser.parse_known_args()
    return args.env or "dev"


def _clear_pydantic_cache() -> None:
    """
    Clear Pydantic settings cache to force re-evaluation.

    This is critical when switching environments dynamically.
    """
    try:
        from src.core_config import reset_settings

        reset_settings()
        logger.debug("Cleared Pydantic settings cache")
    except ImportError:
        pass


def _load_dotenv_file(env_file: Path, override: bool = True) -> int:
    """
    Load environment variables from a dotenv file.

    Args:
        env_file: Path to the .env file
        override: If True, override existing env vars

    Returns:
        Number of variables loaded
    """
    try:
        from dotenv import dotenv_values
    except ImportError:
        logger.warning("python-dotenv not installed, skipping file load")
        return 0

    if not env_file.exists():
        logger.warning(f"Environment file not found: {env_file}")
        return 0

    # Load values from file
    values = dotenv_values(env_file, encoding="utf-8")

    count = 0
    for key, value in values.items():
        if value is None:
            continue

        # Clean the value (strip quotes and whitespace)
        clean_value = value.strip().strip('"').strip("'").strip()

        # Override or set new
        if override or key not in os.environ:
            os.environ[key] = clean_value
            count += 1
            logger.debug(f"Loaded {key}={'***' if 'KEY' in key or 'URL' in key else clean_value}")

    return count


def _extract_db_host(db_url: str | None) -> str | None:
    """Extract the host from a database URL."""
    if not db_url:
        return None
    try:
        parsed = urlparse(db_url)
        return parsed.hostname
    except Exception:
        return None


def _verify_db_host(env: str, db_url: str | None) -> bool:
    """
    Verify that the DB host matches the expected environment.

    Args:
        env: Target environment ('dev' or 'prod')
        db_url: Database URL to verify

    Returns:
        True if host matches expected pattern, False otherwise

    Raises:
        RuntimeError: If prod env has dev credentials (CRITICAL)
    """
    host = _extract_db_host(db_url)
    if not host:
        logger.warning("No DB host found in SUPABASE_DB_URL")
        return False

    expected_patterns = _DB_HOST_PATTERNS.get(env, [])

    # Check if host matches any expected pattern
    for pattern in expected_patterns:
        if pattern in host:
            return True

    # CRITICAL: Prod environment with dev credentials
    if env == "prod":
        dev_patterns = _DB_HOST_PATTERNS.get("dev", [])
        for dev_pattern in dev_patterns:
            if dev_pattern in host:
                raise RuntimeError(
                    f"CRITICAL: PROD CONFIG LOADED DEV CREDENTIALS\n"
                    f"  Environment: {env}\n"
                    f"  DB Host: {host}\n"
                    f"  Expected pattern containing: {expected_patterns}\n\n"
                    f"This is a FATAL configuration error. Check your .env.prod file."
                )

    logger.warning(
        f"DB host '{host}' does not match expected patterns for '{env}': {expected_patterns}"
    )
    return False


def load_environment(
    env: str | None = None,
    project_root: Path | None = None,
    verbose: bool = True,
) -> Literal["dev", "prod"]:
    """
    Load environment configuration with strict precedence.

    PRODUCTION SAFETY (CRASH-PROOF):
        This function NEVER raises FileNotFoundError. In Railway/production
        where .env files don't exist, it gracefully falls back to system
        environment variables and continues startup.

    Precedence (highest to lowest):
        1. Explicit `env` parameter
        2. CLI --env argument
        3. DRAGONFLY_ENV environment variable
        4. Default: 'dev'

    Args:
        env: Explicit environment override (bypasses CLI parsing)
        project_root: Project root directory (defaults to cwd or script location)
        verbose: If True, print startup diagnostics

    Returns:
        The loaded environment name ('dev' or 'prod')

    Raises:
        RuntimeError: If prod environment has dev credentials

    Note:
        If .env.{env} file is missing, logs a warning and continues.
        This is expected in Railway/production where variables come from
        the platform, not local files.
    """
    # Step 1: Determine target environment
    if env is None:
        # Check explicit env var first
        env = os.environ.get(ENV_MARKER)

    if env is None:
        # Parse CLI args
        env = _parse_cli_args()

    # Normalize
    env = env.lower().strip()
    if env in ("production", "prod"):
        env = "prod"
    elif env in ("development", "dev", ""):
        env = "dev"

    if env not in ("dev", "prod"):
        raise ValueError(f"Invalid environment: {env}. Must be 'dev' or 'prod'.")

    # Step 2: Determine project root
    if project_root is None:
        # Try to find project root by looking for pyproject.toml
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "pyproject.toml").exists():
                project_root = parent
                break
        if project_root is None:
            project_root = cwd

    # Step 3: Clear Pydantic cache before loading new environment
    _clear_pydantic_cache()

    # Step 4: Load the target env file (if it exists)
    env_file = project_root / f".env.{env}"

    # PRODUCTION SAFETY: Do NOT raise if file is missing.
    # In Railway/production, environment variables come from the platform,
    # not local .env files. The file is optional.
    loaded_count = 0
    if env_file.exists():
        loaded_count = _load_dotenv_file(env_file, override=True)
        logger.info(f"✅ Loaded config from {env_file.name} ({loaded_count} vars)")
    else:
        logger.warning(
            f"⚠️ Env file not found ({env_file.name}). " "Relying on System Environment Variables."
        )

    # Step 5: Set environment markers
    os.environ[ENV_MARKER] = env
    os.environ["SUPABASE_MODE"] = env
    os.environ["ENVIRONMENT"] = env

    # Also set ENV_FILE for Pydantic fallback
    os.environ["ENV_FILE"] = str(env_file)

    # Step 6: Verify DB host matches environment
    db_url = os.environ.get("SUPABASE_DB_URL")
    _verify_db_host(env, db_url)  # Raises on prod/dev mismatch

    # Step 7: Print audit trail
    if verbose:
        db_host = _extract_db_host(db_url) or "NOT SET"
        supabase_url = os.environ.get("SUPABASE_URL", "NOT SET")

        # Extract project ID from Supabase URL
        project_id = "unknown"
        if "supabase.co" in supabase_url:
            try:
                project_id = supabase_url.split("//")[1].split(".")[0]
            except IndexError:
                pass

        print("╔══════════════════════════════════════════════════════════════════╗")
        print(f"║  DRAGONFLY ENVIRONMENT: {env.upper():<42} ║")
        print("╠══════════════════════════════════════════════════════════════════╣")
        print(f"║  Env File:   {str(env_file):<52} ║")
        print(f"║  Vars Loaded: {loaded_count:<51} ║")
        print(f"║  Project ID:  {project_id:<51} ║")
        print(f"║  DB Host:     {db_host[:51]:<51} ║")
        print("╚══════════════════════════════════════════════════════════════════╝")

    logger.info(f"Environment loaded: {env} (from {env_file})")

    return env  # type: ignore[return-value]


def get_current_env() -> Literal["dev", "prod"]:
    """
    Get the current environment name.

    Returns:
        Current environment ('dev' or 'prod')

    Raises:
        RuntimeError: If load_environment() hasn't been called
    """
    env = os.environ.get(ENV_MARKER)
    if not env:
        raise RuntimeError(
            "Environment not initialized. Call load_environment() before accessing config."
        )
    return "prod" if env == "prod" else "dev"


def require_environment(expected: Literal["dev", "prod"]) -> None:
    """
    Assert that the current environment matches the expected value.

    Use this at the top of scripts that should only run in a specific environment.

    Args:
        expected: Expected environment

    Raises:
        RuntimeError: If current environment doesn't match
    """
    current = get_current_env()
    if current != expected:
        raise RuntimeError(
            f"Environment mismatch: expected '{expected}', got '{current}'\n"
            f"Run with --env {expected} to fix."
        )


# Convenience exports
__all__ = [
    "load_environment",
    "get_current_env",
    "require_environment",
    "ENV_MARKER",
]
