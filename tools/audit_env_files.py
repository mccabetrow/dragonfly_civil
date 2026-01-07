#!/usr/bin/env python3
"""
Dragonfly Engine - Environment File Auditor

Scans .env.dev and .env.prod for common issues that cause silent failures:
  - BOM characters (UTF-8 with BOM breaks connection strings)
  - Trailing whitespace (causes auth failures)
  - Missing critical keys (environment inconsistency)
  - Duplicate keys (last one wins, confusing)

Usage:
    python -m tools.audit_env_files
    python -m tools.audit_env_files --fix  # Auto-fix issues
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Critical keys that MUST exist in both environments
CRITICAL_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_DB_URL",
    "DRAGONFLY_API_KEY",
]

# Keys that should exist but are optional
RECOMMENDED_KEYS = [
    "SUPABASE_ANON_KEY",
    "SUPABASE_MIGRATE_DB_URL",
    "ENVIRONMENT",
    "LOG_LEVEL",
]

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class Issue:
    """Represents a single issue found in an env file."""

    severity: str  # "ERROR" or "WARN"
    line: int | None
    key: str | None
    message: str

    def __str__(self) -> str:
        loc = f"L{self.line}" if self.line else "file"
        key_str = f" [{self.key}]" if self.key else ""
        return f"  [{self.severity}] {loc}{key_str}: {self.message}"


@dataclass
class AuditResult:
    """Result of auditing a single env file."""

    file_path: Path
    exists: bool = True
    issues: list[Issue] = field(default_factory=list)
    keys_found: set[str] = field(default_factory=set)
    has_bom: bool = False
    encoding: str = "utf-8"

    @property
    def passed(self) -> bool:
        return all(i.severity != "ERROR" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "ERROR")

    @property
    def warn_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "WARN")


def check_bom(content: bytes) -> tuple[bool, bytes]:
    """Check for and strip UTF-8 BOM."""
    if content.startswith(b"\xef\xbb\xbf"):
        return True, content[3:]
    return False, content


def check_encoding(content: bytes) -> str | None:
    """Try to detect encoding issues."""
    try:
        content.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        try:
            content.decode("latin-1")
            return "latin-1"
        except UnicodeDecodeError:
            return None


def audit_env_file(file_path: Path) -> AuditResult:
    """Audit a single .env file for issues."""
    result = AuditResult(file_path=file_path)

    if not file_path.exists():
        result.exists = False
        result.issues.append(
            Issue(severity="ERROR", line=None, key=None, message="File does not exist")
        )
        return result

    # Read raw bytes to check encoding
    raw_content = file_path.read_bytes()

    # Check for BOM
    has_bom, content_no_bom = check_bom(raw_content)
    if has_bom:
        result.has_bom = True
        result.issues.append(
            Issue(
                severity="ERROR",
                line=None,
                key=None,
                message="File has UTF-8 BOM (\\ufeff) - this breaks connection strings!",
            )
        )

    # Check encoding
    encoding = check_encoding(content_no_bom)
    if encoding is None:
        result.issues.append(
            Issue(
                severity="ERROR",
                line=None,
                key=None,
                message="File has invalid encoding (not UTF-8 or Latin-1)",
            )
        )
        return result

    result.encoding = encoding
    if encoding != "utf-8":
        result.issues.append(
            Issue(
                severity="WARN",
                line=None,
                key=None,
                message=f"File uses {encoding} encoding instead of UTF-8",
            )
        )

    # Parse lines
    try:
        text_content = content_no_bom.decode(encoding)
    except UnicodeDecodeError as e:
        result.issues.append(
            Issue(
                severity="ERROR",
                line=None,
                key=None,
                message=f"Failed to decode file: {e}",
            )
        )
        return result

    lines = text_content.splitlines()
    seen_keys: dict[str, int] = {}

    for line_num, line in enumerate(lines, start=1):
        # Skip empty lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check for = sign
        if "=" not in line:
            result.issues.append(
                Issue(
                    severity="WARN",
                    line=line_num,
                    key=None,
                    message=f"Line has no '=' sign: {line[:50]}...",
                )
            )
            continue

        # Parse key=value
        key, _, value = line.partition("=")
        key = key.strip()

        # Check for trailing whitespace in key
        if key != line.partition("=")[0]:
            result.issues.append(
                Issue(
                    severity="WARN",
                    line=line_num,
                    key=key,
                    message="Key has leading/trailing whitespace",
                )
            )

        # Check for trailing whitespace in value
        raw_value = line.partition("=")[2]
        if raw_value != raw_value.rstrip():
            result.issues.append(
                Issue(
                    severity="ERROR",
                    line=line_num,
                    key=key,
                    message="Value has trailing whitespace (causes auth failures!)",
                )
            )

        # Check for duplicate keys
        if key in seen_keys:
            result.issues.append(
                Issue(
                    severity="WARN",
                    line=line_num,
                    key=key,
                    message=f"Duplicate key (first seen on line {seen_keys[key]})",
                )
            )
        seen_keys[key] = line_num
        result.keys_found.add(key)

        # Check for unquoted values with special characters
        if value and not (value.startswith('"') or value.startswith("'")):
            if re.search(r"[#\s]", value):
                result.issues.append(
                    Issue(
                        severity="WARN",
                        line=line_num,
                        key=key,
                        message="Value contains spaces or # without quotes",
                    )
                )

        # Check for empty values on critical keys
        if key in CRITICAL_KEYS and not value.strip().strip("\"'"):
            result.issues.append(
                Issue(
                    severity="ERROR",
                    line=line_num,
                    key=key,
                    message="Critical key has empty value",
                )
            )

    # Check for missing critical keys
    for key in CRITICAL_KEYS:
        if key not in result.keys_found:
            result.issues.append(
                Issue(
                    severity="ERROR",
                    line=None,
                    key=key,
                    message="Critical key is missing",
                )
            )

    # Check for missing recommended keys (warnings only)
    for key in RECOMMENDED_KEYS:
        if key not in result.keys_found:
            result.issues.append(
                Issue(
                    severity="WARN",
                    line=None,
                    key=key,
                    message="Recommended key is missing",
                )
            )

    return result


def fix_env_file(file_path: Path, result: AuditResult) -> bool:
    """Attempt to auto-fix issues in an env file."""
    if not result.exists:
        return False

    raw_content = file_path.read_bytes()

    # Strip BOM
    if result.has_bom:
        raw_content = raw_content[3:]

    # Decode
    try:
        text_content = raw_content.decode(result.encoding)
    except UnicodeDecodeError:
        return False

    # Fix trailing whitespace
    lines = text_content.splitlines()
    fixed_lines = []
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.partition("=")
            # Strip trailing whitespace from value only
            fixed_lines.append(f"{key}={value.rstrip()}")
        else:
            fixed_lines.append(line.rstrip())

    # Write back as pure UTF-8 without BOM
    fixed_content = "\n".join(fixed_lines) + "\n"
    file_path.write_text(fixed_content, encoding="utf-8")

    return True


def check_consistency(results: list[AuditResult]) -> list[Issue]:
    """Check for key consistency across all env files."""
    issues: list[Issue] = []

    if len(results) < 2:
        return issues

    # Get keys from each file
    all_keys: dict[str, set[str]] = {}
    for r in results:
        if r.exists:
            all_keys[r.file_path.name] = r.keys_found

    # Check critical keys exist in all files
    for key in CRITICAL_KEYS:
        missing_in: list[str] = []
        for file_name, keys in all_keys.items():
            if key not in keys:
                missing_in.append(file_name)

        if missing_in and len(missing_in) < len(all_keys):
            # Key exists in some but not all
            issues.append(
                Issue(
                    severity="ERROR",
                    line=None,
                    key=key,
                    message=f"Critical key missing in: {', '.join(missing_in)}",
                )
            )

    return issues


def print_report(results: list[AuditResult], consistency_issues: list[Issue]) -> bool:
    """Print audit report and return True if all passed."""
    print("\n" + "=" * 70)
    print("  DRAGONFLY ENV FILE AUDIT")
    print("=" * 70)

    all_passed = True

    for result in results:
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"\n📄 {result.file_path.name}: {status}")

        if not result.exists:
            print("  [ERROR] File does not exist")
            all_passed = False
            continue

        print(f"   Encoding: {result.encoding}")
        print(f"   BOM: {'Yes (BAD!)' if result.has_bom else 'No (good)'}")
        print(f"   Keys found: {len(result.keys_found)}")

        if result.issues:
            print(f"   Issues: {result.error_count} errors, {result.warn_count} warnings")
            for issue in result.issues:
                print(issue)

        if not result.passed:
            all_passed = False

    # Consistency check
    if consistency_issues:
        print("\n🔗 CROSS-FILE CONSISTENCY:")
        for issue in consistency_issues:
            print(issue)
            if issue.severity == "ERROR":
                all_passed = False

    # Summary
    print("\n" + "=" * 70)
    if all_passed:
        print("  ✅ ALL CHECKS PASSED")
    else:
        print("  ❌ AUDIT FAILED - Fix errors before deployment!")
    print("=" * 70 + "\n")

    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit .env files for issues")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to auto-fix issues (BOM, trailing whitespace)",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        default=[".env.dev", ".env.prod"],
        help="Files to audit (default: .env.dev .env.prod)",
    )
    args = parser.parse_args()

    # Audit each file
    results: list[AuditResult] = []
    for file_name in args.files:
        file_path = PROJECT_ROOT / file_name
        result = audit_env_file(file_path)
        results.append(result)

    # Check consistency
    consistency_issues = check_consistency(results)

    # Auto-fix if requested
    if args.fix:
        print("\n🔧 Attempting auto-fix...")
        for result in results:
            if result.exists and (result.has_bom or result.error_count > 0):
                if fix_env_file(result.file_path, result):
                    print(f"   Fixed: {result.file_path.name}")
                else:
                    print(f"   Could not fix: {result.file_path.name}")

        # Re-audit after fix
        results = [audit_env_file(PROJECT_ROOT / f) for f in args.files]
        consistency_issues = check_consistency(results)

    # Print report
    passed = print_report(results, consistency_issues)

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
