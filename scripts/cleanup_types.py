#!/usr/bin/env python3
"""
Cleanup unused 'type: ignore' comments based on mypy output.

Usage:
    # Generate mypy output with unused-ignore warnings
    python -m mypy backend/ src/ --warn-unused-ignores --ignore-missing-imports 2>&1 | tee mypy_output.txt

    # Run cleanup (dry-run by default)
    python scripts/cleanup_types.py mypy_output.txt

    # Apply changes
    python scripts/cleanup_types.py mypy_output.txt --apply

The script parses mypy output for 'Unused "type: ignore" comment' errors
and removes the specific comment from each flagged line.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def parse_mypy_output(content: str) -> list[tuple[str, int]]:
    """
    Parse mypy output for unused type: ignore warnings.

    Returns:
        List of (file_path, line_number) tuples
    """
    pattern = re.compile(
        r'^(.+?):(\d+):\s*error:\s*Unused\s+"type:\s*ignore"',
        re.MULTILINE,
    )
    matches = pattern.findall(content)
    return [(path, int(line_no)) for path, line_no in matches]


def remove_type_ignore(line: str) -> str:
    """
    Remove type: ignore comment from a line.

    Handles various formats:
    - # type: ignore
    - # type: ignore[error-code]
    - # type: ignore[code1, code2]
    """
    # Pattern matches # type: ignore with optional error codes
    # Preserves any content before it
    pattern = re.compile(
        r"\s*#\s*type:\s*ignore(?:\[[^\]]*\])?\s*$",
        re.IGNORECASE,
    )
    cleaned = pattern.sub("", line)
    # Remove trailing whitespace that might be left
    return cleaned.rstrip()


def process_file(file_path: Path, line_numbers: set[int], apply: bool) -> list[str]:
    """
    Process a single file to remove unused type: ignore comments.

    Args:
        file_path: Path to the Python file
        line_numbers: Set of line numbers (1-indexed) to clean
        apply: If True, write changes; otherwise just report

    Returns:
        List of changes made (for reporting)
    """
    if not file_path.exists():
        return [f"  ⚠️  File not found: {file_path}"]

    changes: list[str] = []
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    modified = False

    for i, line in enumerate(lines):
        line_num = i + 1  # 1-indexed
        if line_num in line_numbers:
            original = line.rstrip("\n\r")
            cleaned = remove_type_ignore(original)
            if cleaned != original:
                changes.append(f"  Line {line_num}: {original!r} → {cleaned!r}")
                # Preserve original line ending
                ending = line[len(line.rstrip("\n\r")) :]
                lines[i] = cleaned + ending
                modified = True

    if modified and apply:
        file_path.write_text("".join(lines), encoding="utf-8")
        changes.append(f"  ✅ File updated: {file_path}")

    return changes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove unused 'type: ignore' comments based on mypy output"
    )
    parser.add_argument(
        "mypy_output",
        type=Path,
        help="Path to mypy output file (or - for stdin)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )
    args = parser.parse_args()

    # Read mypy output
    if str(args.mypy_output) == "-":
        content = sys.stdin.read()
    else:
        if not args.mypy_output.exists():
            print(f"Error: File not found: {args.mypy_output}", file=sys.stderr)
            return 1
        content = args.mypy_output.read_text(encoding="utf-8")

    # Parse for unused ignores
    unused = parse_mypy_output(content)
    if not unused:
        print("No unused 'type: ignore' comments found in mypy output.")
        return 0

    print(f"Found {len(unused)} unused 'type: ignore' comment(s):")
    print()

    # Group by file
    file_lines: dict[Path, set[int]] = {}
    for file_path, line_no in unused:
        path = Path(file_path)
        if path not in file_lines:
            file_lines[path] = set()
        file_lines[path].add(line_no)

    # Process each file
    total_changes = 0
    for file_path, line_numbers in sorted(file_lines.items()):
        print(f"📄 {file_path}")
        changes = process_file(file_path, line_numbers, args.apply)
        for change in changes:
            print(change)
        total_changes += len([c for c in changes if "→" in c])
        print()

    # Summary
    if args.apply:
        print(f"✅ Applied {total_changes} change(s) across {len(file_lines)} file(s).")
    else:
        print(f"🔍 Dry-run: {total_changes} change(s) would be made.")
        print("   Run with --apply to make changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
