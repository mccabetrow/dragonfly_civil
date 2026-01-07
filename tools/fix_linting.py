#!/usr/bin/env python3
"""
tools/fix_linting.py - Automated Linting Cleanup

PURPOSE:
    Enforce the "Green Main" policy by running all linters and auto-fixers.
    This script ensures pre-commit passes cleanly before any push.

WORKFLOW:
    1. Run pre-commit on all files
    2. If clean: done
    3. If dirty: run auto-fixers (ruff format, ruff check --fix, isort)
    4. Re-run pre-commit to verify

USAGE:
    python -m tools.fix_linting           # Standard run
    python -m tools.fix_linting --check   # Check-only (no auto-fix)
    python -m tools.fix_linting --verbose # Show detailed output

EXIT CODES:
    0 - Repo is green (all checks pass)
    1 - Auto-fix attempted, manual review needed
    2 - Pre-commit not available or other error
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal


@dataclass
class LintResult:
    """Result of a linting operation."""

    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def run_command(
    cmd: list[str],
    capture: bool = True,
    verbose: bool = False,
) -> LintResult:
    """
    Run a shell command and capture results.

    Args:
        cmd: Command and arguments
        capture: Whether to capture output
        verbose: Print output in real-time

    Returns:
        LintResult with exit code and output
    """
    cmd_str = " ".join(cmd)

    if verbose:
        print(f"\n$ {cmd_str}")

    try:
        if capture and not verbose:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
            return LintResult(
                command=cmd_str,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        else:
            # Stream output in real-time
            result = subprocess.run(
                cmd,
                timeout=300,
            )
            return LintResult(
                command=cmd_str,
                exit_code=result.returncode,
                stdout="",
                stderr="",
            )
    except subprocess.TimeoutExpired:
        return LintResult(
            command=cmd_str,
            exit_code=124,
            stdout="",
            stderr="Command timed out after 5 minutes",
        )
    except FileNotFoundError:
        return LintResult(
            command=cmd_str,
            exit_code=127,
            stdout="",
            stderr=f"Command not found: {cmd[0]}",
        )


def check_pre_commit_available() -> bool:
    """Verify pre-commit is installed and available."""
    result = run_command(["pre-commit", "--version"])
    return result.passed


def run_pre_commit(verbose: bool = False) -> LintResult:
    """Run pre-commit on all files."""
    return run_command(
        ["pre-commit", "run", "--all-files"],
        capture=not verbose,
        verbose=verbose,
    )


def run_ruff_format(verbose: bool = False) -> LintResult:
    """Run ruff format to fix formatting issues."""
    return run_command(
        ["python", "-m", "ruff", "format", "."],
        capture=not verbose,
        verbose=verbose,
    )


def run_ruff_check_fix(verbose: bool = False) -> LintResult:
    """Run ruff check with auto-fix."""
    return run_command(
        ["python", "-m", "ruff", "check", "--fix", "."],
        capture=not verbose,
        verbose=verbose,
    )


def run_isort(verbose: bool = False) -> LintResult:
    """Run isort to fix import ordering."""
    return run_command(
        ["python", "-m", "isort", "."],
        capture=not verbose,
        verbose=verbose,
    )


def run_black(verbose: bool = False) -> LintResult:
    """Run black to fix formatting."""
    return run_command(
        ["python", "-m", "black", "."],
        capture=not verbose,
        verbose=verbose,
    )


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automated linting cleanup for Green Main policy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.fix_linting           # Auto-fix and verify
    python -m tools.fix_linting --check   # Check only, no fixes
    python -m tools.fix_linting --verbose # Show all output

The script runs pre-commit hooks and auto-formatters to ensure
the repository passes all lint checks before pushing.
        """,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check only, do not attempt auto-fix",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed command output",
    )

    args = parser.parse_args()

    print_section("DRAGONFLY LINTING AUTOMATION")
    print("Enforcing Green Main policy...")

    # Step 0: Check pre-commit is available
    if not check_pre_commit_available():
        print("\n❌ ERROR: pre-commit is not installed")
        print("   Install with: pip install pre-commit")
        print("   Then run: pre-commit install")
        return 2

    # Step 1: Initial pre-commit check
    print("\n[1/4] Running pre-commit on all files...")
    result = run_pre_commit(verbose=args.verbose)

    if result.passed:
        print("\n✅ Repo is Green")
        print("   All pre-commit hooks passed on first try.")
        return 0

    # Pre-commit failed
    if args.check:
        print("\n❌ Linting failed (--check mode, no auto-fix)")
        if result.stdout and not args.verbose:
            print("\nOutput:")
            print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        return 1

    # Step 2: Auto-fix attempt
    print("\n⚠️  Linting failed. Attempting auto-fix...")

    print("\n[2/4] Running formatters...")

    # Run black first (primary formatter)
    print("   Running black...")
    black_result = run_black(verbose=args.verbose)
    if not black_result.passed:
        print(f"   ⚠️  black had issues (exit {black_result.exit_code})")

    # Run isort
    print("   Running isort...")
    isort_result = run_isort(verbose=args.verbose)
    if not isort_result.passed:
        print(f"   ⚠️  isort had issues (exit {isort_result.exit_code})")

    # Run ruff format
    print("   Running ruff format...")
    format_result = run_ruff_format(verbose=args.verbose)
    if not format_result.passed:
        print(f"   ⚠️  ruff format had issues (exit {format_result.exit_code})")

    print("\n[3/4] Running ruff check --fix...")
    fix_result = run_ruff_check_fix(verbose=args.verbose)
    if not fix_result.passed:
        print(f"   ⚠️  ruff check --fix had issues (exit {fix_result.exit_code})")

    # Step 3: Re-run pre-commit
    print("\n[4/4] Re-running pre-commit to verify...")
    final_result = run_pre_commit(verbose=args.verbose)

    if final_result.passed:
        print("\n✅ Repo is Green")
        print("   Auto-fix succeeded. All pre-commit hooks now pass.")
        print("\n   📝 Note: Files were modified. Review changes before committing.")
        return 0

    # Still failing
    print("\n❌ Linting still failing after auto-fix")
    print("   Manual intervention required.")

    if not args.verbose and final_result.stdout:
        print("\nRemaining issues:")
        # Show last 2000 chars of output
        output = final_result.stdout
        if len(output) > 2000:
            print("   [truncated, use --verbose for full output]")
            output = output[-2000:]
        print(output)

    print("\nSuggestions:")
    print("   1. Run: pre-commit run --all-files")
    print("   2. Fix issues manually")
    print("   3. Re-run: python -m tools.fix_linting")

    return 1


if __name__ == "__main__":
    sys.exit(main())
