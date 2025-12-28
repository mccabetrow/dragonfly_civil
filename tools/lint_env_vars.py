#!/usr/bin/env python3
"""
Dragonfly Environment Variable Linter

Detects "silent killers" in environment files:
- Leading/trailing whitespace in values
- Embedded newlines
- Invisible characters that break deployments

These issues are common Vercel deployment killers that cause
"works on my machine" syndrome.

Usage:
    python -m tools.lint_env_vars
    python -m tools.lint_env_vars --file .env.prod
    python -m tools.lint_env_vars --file .env.dev --fix

Options:
    --file FILE   Env file to lint (default: .env.prod)
    --fix         Automatically fix issues (creates .env.fixed backup)
    --strict      Exit 1 on warnings too (not just errors)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class Severity(Enum):
    """Issue severity levels."""

    ERROR = "ERROR"  # Fatal - will break deployment
    WARNING = "WARN"  # May cause issues
    INFO = "INFO"  # Informational


@dataclass
class LintIssue:
    """A linting issue found in an env file."""

    line_num: int
    key: str
    severity: Severity
    message: str
    raw_value: Optional[str] = None
    suggestion: Optional[str] = None


# =============================================================================
# LINT CHECKS
# =============================================================================


def check_leading_whitespace(key: str, value: str, line_num: int) -> Optional[LintIssue]:
    """Check for leading whitespace in value."""
    if value != value.lstrip():
        spaces = len(value) - len(value.lstrip())
        return LintIssue(
            line_num=line_num,
            key=key,
            severity=Severity.ERROR,
            message=f"Leading whitespace ({spaces} chars)",
            raw_value=repr(value[:20]),
            suggestion=value.strip(),
        )
    return None


def check_trailing_whitespace(key: str, value: str, line_num: int) -> Optional[LintIssue]:
    """Check for trailing whitespace in value."""
    if value != value.rstrip():
        spaces = len(value) - len(value.rstrip())
        return LintIssue(
            line_num=line_num,
            key=key,
            severity=Severity.ERROR,
            message=f"Trailing whitespace ({spaces} chars)",
            raw_value=repr(value[-20:]) if len(value) > 20 else repr(value),
            suggestion=value.strip(),
        )
    return None


def check_embedded_newlines(key: str, value: str, line_num: int) -> Optional[LintIssue]:
    """Check for embedded newlines in value."""
    if "\n" in value or "\r" in value:
        return LintIssue(
            line_num=line_num,
            key=key,
            severity=Severity.ERROR,
            message="Embedded newline character",
            raw_value=repr(value[:50]),
            suggestion=value.replace("\n", "").replace("\r", "").strip(),
        )
    return None


def check_invisible_chars(key: str, value: str, line_num: int) -> Optional[LintIssue]:
    """Check for invisible/control characters."""
    # Common invisible characters that break things
    invisible_chars = {
        "\u200b": "ZERO WIDTH SPACE",
        "\u200c": "ZERO WIDTH NON-JOINER",
        "\u200d": "ZERO WIDTH JOINER",
        "\ufeff": "BOM",
        "\u00a0": "NON-BREAKING SPACE",
        "\t": "TAB",
    }

    for char, name in invisible_chars.items():
        if char in value:
            clean = value
            for c in invisible_chars:
                clean = clean.replace(c, "" if c != "\t" else " ")
            return LintIssue(
                line_num=line_num,
                key=key,
                severity=Severity.ERROR,
                message=f"Invisible character: {name}",
                raw_value=repr(value[:30]),
                suggestion=clean.strip(),
            )
    return None


def check_empty_value(key: str, value: str, line_num: int) -> Optional[LintIssue]:
    """Check for empty values on required keys."""
    required_keys = {
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_DB_URL",
    }

    if key in required_keys and not value.strip():
        return LintIssue(
            line_num=line_num,
            key=key,
            severity=Severity.ERROR,
            message="Required variable is empty",
        )
    return None


def check_quoted_value(key: str, value: str, line_num: int) -> Optional[LintIssue]:
    """Check for unnecessarily quoted values (can cause issues)."""
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        inner = value[1:-1]
        # Only warn if inner value doesn't need quotes
        if " " not in inner and "=" not in inner:
            return LintIssue(
                line_num=line_num,
                key=key,
                severity=Severity.WARNING,
                message="Value is quoted but may not need quotes",
                raw_value=value,
                suggestion=inner,
            )
    return None


def check_url_format(key: str, value: str, line_num: int) -> Optional[LintIssue]:
    """Check URL values for common issues."""
    url_keys = {"SUPABASE_URL", "PROD_API_URL", "NEXT_PUBLIC_APP_URL"}

    if key in url_keys and value:
        # Check for trailing slash (often causes issues)
        if value.endswith("/"):
            return LintIssue(
                line_num=line_num,
                key=key,
                severity=Severity.WARNING,
                message="URL has trailing slash (may cause double-slash in paths)",
                raw_value=value,
                suggestion=value.rstrip("/"),
            )

        # Check for missing protocol
        if value and not value.startswith(("http://", "https://")):
            return LintIssue(
                line_num=line_num,
                key=key,
                severity=Severity.ERROR,
                message="URL missing protocol (http:// or https://)",
                raw_value=value,
            )
    return None


def check_password_in_url(key: str, value: str, line_num: int) -> Optional[LintIssue]:
    """Check for special characters in DB URL passwords that need encoding."""
    db_url_keys = {"SUPABASE_DB_URL", "SUPABASE_MIGRATE_DB_URL", "DATABASE_URL"}

    if key in db_url_keys and value:
        # Extract password from connection string format
        # Pattern matches: postgres(ql)://user:password@host
        pg_pattern = r"postgres(?:ql)?://([^:]+):([^@]+)@"
        match = re.match(pg_pattern, value)
        if match:
            password = match.group(2)
            # Check for characters that should be URL-encoded
            special_chars = {"@", "/", "?", "#", "%", " "}
            found = [c for c in password if c in special_chars]
            if found:
                return LintIssue(
                    line_num=line_num,
                    key=key,
                    severity=Severity.WARNING,
                    message=f"Password contains special chars that may need URL-encoding: {found}",
                    raw_value="(password hidden)",
                )
    return None


# =============================================================================
# LINTER CORE
# =============================================================================


def lint_env_file(filepath: Path) -> List[LintIssue]:
    """
    Lint an environment file for issues.

    Returns list of issues found.
    """
    issues: List[LintIssue] = []

    if not filepath.exists():
        issues.append(
            LintIssue(
                line_num=0,
                key="(file)",
                severity=Severity.ERROR,
                message=f"File not found: {filepath}",
            )
        )
        return issues

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for line_num, line in enumerate(lines, start=1):
        # Skip comments and empty lines
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Parse KEY=VALUE
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()

        # Keep value as-is (don't strip) for whitespace detection
        # But remove the trailing newline from readline
        value = value.rstrip("\n\r")

        # Run all checks
        checks = [
            check_leading_whitespace,
            check_trailing_whitespace,
            check_embedded_newlines,
            check_invisible_chars,
            check_empty_value,
            check_quoted_value,
            check_url_format,
            check_password_in_url,
        ]

        for check_fn in checks:
            issue = check_fn(key, value, line_num)
            if issue:
                issues.append(issue)

    return issues


def fix_env_file(filepath: Path, issues: List[LintIssue]) -> Path:
    """
    Fix issues in an env file.

    Creates a backup and writes fixed content.
    Returns path to the fixed file.
    """
    # Create backup
    backup_path = filepath.with_suffix(filepath.suffix + ".backup")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Build fix map: line_num -> (key, fixed_value)
    fixes = {}
    for issue in issues:
        if issue.suggestion and issue.line_num > 0:
            fixes[issue.line_num] = (issue.key, issue.suggestion)

    # Apply fixes
    lines = content.splitlines(keepends=True)
    for line_num, (key, fixed_value) in fixes.items():
        if line_num <= len(lines):
            idx = line_num - 1
            old_line = lines[idx]
            if "=" in old_line and old_line.split("=")[0].strip() == key:
                # Reconstruct line with fixed value
                lines[idx] = f"{key}={fixed_value}\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return backup_path


# =============================================================================
# MAIN
# =============================================================================


def print_results(filepath: Path, issues: List[LintIssue]) -> None:
    """Print linting results."""
    print("")
    print("═" * 70)
    print("  🔍 DRAGONFLY ENV FILE LINTER")
    print("═" * 70)
    print(f"  File: {filepath}")
    print("")

    if not issues:
        print("  ✅ .env file is clean - no issues found")
        print("═" * 70)
        print("")
        return

    errors = [i for i in issues if i.severity == Severity.ERROR]
    warnings = [i for i in issues if i.severity == Severity.WARNING]
    # Count infos for potential verbose mode (currently not displayed)
    _infos = [i for i in issues if i.severity == Severity.INFO]

    print(f"  Found: {len(errors)} errors, {len(warnings)} warnings")
    print("")
    print("─" * 70)

    for issue in issues:
        icon = (
            "❌"
            if issue.severity == Severity.ERROR
            else "⚠️" if issue.severity == Severity.WARNING else "ℹ️"
        )
        print(f"\n  {icon} Line {issue.line_num}: [{issue.key}]")
        print(f"     {issue.message}")
        if issue.raw_value:
            print(f"     Value: {issue.raw_value}")
        if issue.suggestion:
            # Show truncated suggestion for long values
            suggestion = issue.suggestion
            if len(suggestion) > 50:
                suggestion = suggestion[:50] + "..."
            print(f"     Fix: {suggestion}")

    print("")
    print("─" * 70)

    if errors:
        print("")
        print("  ❌ FATAL: Fix errors before deploying!")
        print("     Run with --fix to auto-fix issues")
    elif warnings:
        print("")
        print("  ⚠️  Warnings found - review recommended")

    print("═" * 70)
    print("")


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Lint environment files for deployment issues",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=".env.prod",
        help="Environment file to lint (default: .env.prod)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix issues (creates backup)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on warnings too (not just errors)",
    )
    args = parser.parse_args()

    # Resolve file path
    project_root = Path(__file__).parent.parent
    filepath = project_root / args.file

    # Lint the file
    issues = lint_env_file(filepath)

    # Print results
    print_results(filepath, issues)

    # Apply fixes if requested
    if args.fix and issues:
        fixable = [i for i in issues if i.suggestion]
        if fixable:
            backup = fix_env_file(filepath, issues)
            print(f"  📝 Applied {len(fixable)} fixes")
            print(f"     Backup: {backup}")
            print("")

            # Re-lint to show remaining issues
            remaining = lint_env_file(filepath)
            if remaining:
                print(f"  ⚠️  {len(remaining)} issues remain (manual fix required)")
            else:
                print("  ✅ All issues fixed!")
            print("")

    # Determine exit code
    errors = [i for i in issues if i.severity == Severity.ERROR]
    warnings = [i for i in issues if i.severity == Severity.WARNING]

    if errors:
        sys.exit(1)
    elif warnings and args.strict:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
