#!/usr/bin/env python3
"""
Dragonfly Civil - Environment File Sanitizer

Cleans .env files to prevent deployment warnings:
- Strips leading/trailing whitespace from values
- Removes internal newline characters (\n, \r)
- Removes trailing slashes from URL variables

Usage:
    python -m tools.clean_env              # Clean .env.dev and .env.prod
    python -m tools.clean_env --dry-run    # Preview changes without writing
    python -m tools.clean_env .env.custom  # Clean specific file
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Variables that should have trailing slashes removed
URL_KEYS = {
    "VITE_API_BASE_URL",
    "VITE_SUPABASE_URL",
    "API_BASE_URL",
    "SUPABASE_URL",
    "N8N_API_URL",
    "PROOF_API_URL",
}


def clean_value(key: str, value: str) -> tuple[str, list[str]]:
    """
    Clean an environment variable value.

    Returns:
        tuple of (cleaned_value, list_of_fixes_applied)
    """
    fixes: list[str] = []

    # 1. Strip leading/trailing whitespace
    cleaned = value.strip()
    if cleaned != value:
        fixes.append("stripped whitespace")

    # 2. Remove internal newlines/carriage returns
    if "\n" in cleaned or "\r" in cleaned:
        cleaned = cleaned.replace("\r\n", "").replace("\n", "").replace("\r", "")
        fixes.append("removed newlines")

    # 3. Remove trailing slash from URL variables
    if key in URL_KEYS and cleaned.endswith("/"):
        cleaned = cleaned.rstrip("/")
        fixes.append("removed trailing slash")

    # 4. Collapse multiple spaces (common paste error)
    if "  " in cleaned:
        cleaned = re.sub(r"\s+", " ", cleaned)
        fixes.append("collapsed multiple spaces")

    return cleaned, fixes


def parse_env_file(path: Path) -> list[tuple[str, str, str]]:
    """
    Parse an env file into (line_type, key, value) tuples.

    line_type is one of: 'comment', 'blank', 'var'
    """
    lines: list[tuple[str, str, str]] = []

    if not path.exists():
        return lines

    content = path.read_text(encoding="utf-8")

    for line in content.splitlines():
        stripped = line.strip()

        if not stripped:
            lines.append(("blank", "", ""))
        elif stripped.startswith("#"):
            lines.append(("comment", "", line))
        elif "=" in line:
            # Split on first = only
            key, _, value = line.partition("=")
            lines.append(("var", key.strip(), value))
        else:
            # Preserve any other lines as-is
            lines.append(("other", "", line))

    return lines


def clean_env_file(path: Path, dry_run: bool = False) -> dict[str, list[str]]:
    """
    Clean an env file and return a report of fixes.

    Returns:
        dict mapping variable names to list of fixes applied
    """
    report: dict[str, list[str]] = {}
    lines = parse_env_file(path)

    if not lines:
        return report

    output_lines: list[str] = []

    for line_type, key, value in lines:
        if line_type == "blank":
            output_lines.append("")
        elif line_type == "comment":
            output_lines.append(value)
        elif line_type == "other":
            output_lines.append(value)
        elif line_type == "var":
            cleaned, fixes = clean_value(key, value)
            output_lines.append(f"{key}={cleaned}")
            if fixes:
                report[key] = fixes

    if not dry_run and report:
        # Write back with consistent line endings
        path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    return report


def print_report(path: Path, report: dict[str, list[str]], dry_run: bool) -> None:
    """Print a human-readable report of fixes."""
    prefix = "[DRY RUN] " if dry_run else ""

    if not report:
        print(f"{prefix}✓ {path.name}: No issues found")
        return

    action = "Would fix" if dry_run else "Fixed"
    print(f"{prefix}{action} {len(report)} variable(s) in {path.name}:")

    for key, fixes in report.items():
        fixes_str = ", ".join(fixes)
        print(f"  • {key}: {fixes_str}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanitize .env files to prevent deployment warnings"
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=[".env.dev", ".env.prod"],
        help="Env files to clean (default: .env.dev .env.prod)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Preview changes without writing",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only output if fixes were made",
    )

    args = parser.parse_args()

    # Resolve paths relative to repo root
    repo_root = Path(__file__).parent.parent
    total_fixes = 0

    for filename in args.files:
        path = repo_root / filename

        if not path.exists():
            if not args.quiet:
                print(f"⚠ {filename}: File not found, skipping")
            continue

        report = clean_env_file(path, dry_run=args.dry_run)
        total_fixes += len(report)

        if report or not args.quiet:
            print_report(path, report, args.dry_run)

    if total_fixes > 0:
        verb = "would be" if args.dry_run else "were"
        print(f"\n{'─' * 40}")
        print(f"Total: {total_fixes} variable(s) {verb} cleaned")

    return 0


if __name__ == "__main__":
    sys.exit(main())
