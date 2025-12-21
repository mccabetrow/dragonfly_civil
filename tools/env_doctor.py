#!/usr/bin/env python3
"""
Dragonfly Environment Doctor - Configuration Hygiene Auditor

A specialized diagnostic tool that audits environment variable hygiene
to prevent configuration drift and silent failures.

CHECKS:
  A. Canonical Names Only - Detects deprecated _DEV/_PROD suffixed vars
  B. Missing Essentials - Verifies required vars are present
  C. Connection Mode - Identifies pooler port (5432 vs 6543)

Usage:
    python -m tools.env_doctor              # Run all checks
    python -m tools.env_doctor --verbose    # Show all env vars
    python -m tools.env_doctor --strict     # Exit 1 on any warning

Exit Codes:
    0 - All checks passed
    1 - One or more issues detected (in strict mode)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

import click

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Exit codes
EXIT_OK = 0
EXIT_ISSUES = 1

# Required environment variables
REQUIRED_VARS = [
    "SUPABASE_DB_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_URL",
]

# Optional but recommended
RECOMMENDED_VARS = [
    "DRAGONFLY_API_KEY",
    "SUPABASE_MODE",
    "ENVIRONMENT",
]

# Deprecated suffix patterns (non-canonical)
DEPRECATED_SUFFIXES = ["_DEV", "_PROD", "_DIRECT"]

# Known deprecated variable patterns
DEPRECATED_PATTERNS = [
    r"SUPABASE_.*_(DEV|PROD)$",
    r"SUPABASE_DB_URL_DIRECT.*",
    r"SUPABASE_.*_PASSWORD.*",
]


class EnvCheckResult(NamedTuple):
    """Result of an environment check."""

    passed: bool
    message: str
    severity: str  # 'error', 'warning', 'info', 'pass'


class EnvDoctor:
    """Environment configuration diagnostic suite."""

    def __init__(self, verbose: bool = False, strict: bool = False):
        self.verbose = verbose
        self.strict = strict
        self.issues: list[EnvCheckResult] = []
        self.warnings: list[EnvCheckResult] = []
        self.passes: list[EnvCheckResult] = []

    def _style(self, text: str, severity: str) -> str:
        """Apply color based on severity."""
        colors = {
            "error": "red",
            "warning": "yellow",
            "info": "blue",
            "pass": "green",
        }
        return click.style(text, fg=colors.get(severity, "white"))

    def log(self, result: EnvCheckResult) -> None:
        """Log and record a check result."""
        prefix = {
            "error": "[FAIL]",
            "warning": "[WARN]",
            "info": "[INFO]",
            "pass": "[PASS]",
        }
        click.echo(f"{self._style(prefix[result.severity], result.severity)} {result.message}")

        if result.severity == "error":
            self.issues.append(result)
        elif result.severity == "warning":
            self.warnings.append(result)
        else:
            self.passes.append(result)

    # =========================================================================
    # CHECK A: Canonical Names Only
    # =========================================================================
    def check_canonical_names(self) -> None:
        """
        Check A: Detect non-canonical environment variables.

        Scans os.environ for variables ending in _DEV, _PROD, or matching
        known deprecated patterns. These should be removed in favor of
        canonical names (SUPABASE_URL, SUPABASE_DB_URL, etc.).
        """
        click.echo("\n" + "=" * 60)
        click.echo("  CHECK A: Canonical Names Only")
        click.echo("=" * 60)

        deprecated_found = []

        for key in sorted(os.environ.keys()):
            # Check suffix patterns
            for suffix in DEPRECATED_SUFFIXES:
                if key.endswith(suffix):
                    deprecated_found.append(key)
                    break
            else:
                # Check regex patterns
                for pattern in DEPRECATED_PATTERNS:
                    if re.match(pattern, key, re.IGNORECASE):
                        deprecated_found.append(key)
                        break

        if deprecated_found:
            for key in deprecated_found:
                self.log(
                    EnvCheckResult(
                        passed=False,
                        message=f"Non-Canonical Variable Detected: {key}",
                        severity="error",
                    )
                )
            click.echo()
            click.echo(
                self._style(
                    "  💡 Migration: Remove these variables and use canonical names:\n"
                    "     SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_DB_URL\n"
                    "     Set SUPABASE_MODE=dev|prod to switch environments.",
                    "info",
                )
            )
        else:
            self.log(
                EnvCheckResult(
                    passed=True,
                    message="All environment variables use canonical names",
                    severity="pass",
                )
            )

    # =========================================================================
    # CHECK B: Missing Essentials
    # =========================================================================
    def check_missing_essentials(self) -> None:
        """
        Check B: Verify required environment variables are present.

        Ensures SUPABASE_DB_URL, SUPABASE_SERVICE_ROLE_KEY, and
        DRAGONFLY_API_KEY are set.
        """
        click.echo("\n" + "=" * 60)
        click.echo("  CHECK B: Essential Variables")
        click.echo("=" * 60)

        # Required vars
        for var in REQUIRED_VARS:
            value = os.environ.get(var, "")
            if value:
                # Mask sensitive values
                display = "***" if "KEY" in var or "PASSWORD" in var else value[:30] + "..."
                self.log(
                    EnvCheckResult(
                        passed=True,
                        message=f"{var}: {display}",
                        severity="pass",
                    )
                )
            else:
                self.log(
                    EnvCheckResult(
                        passed=False,
                        message=f"{var}: MISSING (required)",
                        severity="error",
                    )
                )

        # Recommended vars
        click.echo()
        for var in RECOMMENDED_VARS:
            value = os.environ.get(var, "")
            if value:
                display = "***" if "KEY" in var else value
                self.log(
                    EnvCheckResult(
                        passed=True,
                        message=f"{var}: {display}",
                        severity="pass",
                    )
                )
            else:
                self.log(
                    EnvCheckResult(
                        passed=True,  # Recommended, not required
                        message=f"{var}: not set (recommended)",
                        severity="warning",
                    )
                )

    # =========================================================================
    # CHECK C: Connection Mode
    # =========================================================================
    def check_connection_mode(self) -> None:
        """
        Check C: Parse SUPABASE_DB_URL to determine connection mode.

        Port 5432 = Session/Direct mode (for migrations, dev)
        Port 6543 = Transaction Pooler (for Lambda/high-scale production)
        """
        click.echo("\n" + "=" * 60)
        click.echo("  CHECK C: Connection Mode")
        click.echo("=" * 60)

        db_url = os.environ.get("SUPABASE_DB_URL", "")
        if not db_url:
            self.log(
                EnvCheckResult(
                    passed=False,
                    message="Cannot determine mode: SUPABASE_DB_URL not set",
                    severity="error",
                )
            )
            return

        try:
            parsed = urlparse(db_url)
            port = parsed.port or 5432
            host = parsed.hostname or "unknown"

            # Determine mode based on port
            if port == 6543:
                mode_desc = "Transaction Pooler (Correct for Lambda/High Scale)"
                severity = "pass"
            elif port == 5432:
                mode_desc = "Session/Direct (Correct for Migrations/Dev)"
                severity = "pass"
            else:
                mode_desc = f"Unknown port {port}"
                severity = "warning"

            self.log(
                EnvCheckResult(
                    passed=True,
                    message=f"Port: {port}",
                    severity="info",
                )
            )
            self.log(
                EnvCheckResult(
                    passed=True,
                    message=f"Mode: {mode_desc}",
                    severity=severity,
                )
            )

            # Check for pooler hostname pattern
            if "pooler.supabase.com" in host:
                pooler_type = "Supabase Pooler"
            elif "db." in host and ".supabase.co" in host:
                pooler_type = "Direct Connection"
            else:
                pooler_type = "Custom/Unknown Host"

            self.log(
                EnvCheckResult(
                    passed=True,
                    message=f"Host Type: {pooler_type}",
                    severity="info",
                )
            )

        except Exception as e:
            self.log(
                EnvCheckResult(
                    passed=False,
                    message=f"Failed to parse SUPABASE_DB_URL: {e}",
                    severity="error",
                )
            )

    # =========================================================================
    # SUMMARY
    # =========================================================================
    def print_summary(self) -> int:
        """Print summary table and return exit code."""
        click.echo("\n" + "=" * 60)
        click.echo("  ENVIRONMENT DOCTOR SUMMARY")
        click.echo("=" * 60)

        # Summary table
        click.echo()
        click.echo(f"  {'Check':<30} {'Status':<15}")
        click.echo(f"  {'-' * 30} {'-' * 15}")

        total_issues = len(self.issues)
        total_warnings = len(self.warnings)
        total_passes = len(self.passes)

        click.echo(f"  {'Passed':<30} {self._style(str(total_passes), 'pass'):<15}")
        click.echo(f"  {'Warnings':<30} {self._style(str(total_warnings), 'warning'):<15}")
        click.echo(f"  {'Errors':<30} {self._style(str(total_issues), 'error'):<15}")

        click.echo()

        # Final verdict
        if total_issues > 0:
            click.echo(self._style("  ❌ ENVIRONMENT ISSUES DETECTED", "error"))
            click.echo("     Fix the errors above before deploying.")
            return EXIT_ISSUES
        elif total_warnings > 0 and self.strict:
            click.echo(self._style("  ⚠️  WARNINGS DETECTED (strict mode)", "warning"))
            return EXIT_ISSUES
        elif total_warnings > 0:
            click.echo(self._style("  ⚠️  ENVIRONMENT OK (with warnings)", "warning"))
            return EXIT_OK
        else:
            click.echo(self._style("  ✅ ENVIRONMENT HEALTHY", "pass"))
            return EXIT_OK

    def run_all_checks(self) -> int:
        """Run all environment checks and return exit code."""
        click.echo()
        click.echo("╔" + "═" * 58 + "╗")
        click.echo("║" + "  DRAGONFLY ENVIRONMENT DOCTOR".center(58) + "║")
        click.echo("╚" + "═" * 58 + "╝")

        # Show current mode
        mode = os.environ.get("SUPABASE_MODE", "dev")
        env = os.environ.get("ENVIRONMENT", "dev")
        click.echo(f"\n  Current Mode: SUPABASE_MODE={mode}, ENVIRONMENT={env}")

        # Run all checks
        self.check_canonical_names()
        self.check_missing_essentials()
        self.check_connection_mode()

        # Print verbose env dump if requested
        if self.verbose:
            click.echo("\n" + "=" * 60)
            click.echo("  ALL ENVIRONMENT VARIABLES (Verbose)")
            click.echo("=" * 60)
            for key in sorted(os.environ.keys()):
                if key.startswith("SUPABASE") or key.startswith("DRAGONFLY"):
                    value = os.environ[key]
                    if "KEY" in key or "PASSWORD" in key or "SECRET" in key:
                        value = "***"
                    elif len(value) > 50:
                        value = value[:50] + "..."
                    click.echo(f"  {key}={value}")

        return self.print_summary()


@click.command()
@click.option("--verbose", "-v", is_flag=True, help="Show all Supabase/Dragonfly env vars")
@click.option("--strict", "-s", is_flag=True, help="Exit 1 on warnings (not just errors)")
def main(verbose: bool, strict: bool) -> None:
    """
    Run the Dragonfly Environment Doctor.

    Audits environment variable hygiene to prevent configuration drift.
    """
    doctor = EnvDoctor(verbose=verbose, strict=strict)
    exit_code = doctor.run_all_checks()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
