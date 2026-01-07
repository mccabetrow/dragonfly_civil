#!/usr/bin/env python3
"""
Dragonfly Civil - Frontend Security Scanner

RAG Safety Policy #1: "Frontend NEVER talks to OpenAI directly."

This static analysis tool scans the frontend directory to ensure:
1. No OpenAI imports or SDK usage
2. No OpenAI API keys in source code
3. No VITE_OPENAI_API_KEY in environment files

Usage:
    python -m tools.scan_frontend_security
    python -m tools.scan_frontend_security --frontend-dir ./dragonfly-dashboard
    python -m tools.scan_frontend_security --strict

Exit Codes:
    0 - Frontend is clean (strictly decoupled from OpenAI)
    1 - Forbidden patterns detected (CRITICAL security violation)
    2 - Configuration error (directory not found, etc.)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class SecurityViolation:
    """A single security violation found in the frontend."""

    file_path: str
    line_number: int
    pattern_name: str
    matched_text: str
    severity: str  # CRITICAL, HIGH, MEDIUM

    def __str__(self) -> str:
        return f"{self.severity}: {self.pattern_name} in {self.file_path}:{self.line_number}"


@dataclass
class ScanResult:
    """Overall scan result."""

    violations: list[SecurityViolation] = field(default_factory=list)
    files_scanned: int = 0
    env_files_checked: int = 0

    @property
    def is_clean(self) -> bool:
        return len(self.violations) == 0

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "HIGH")


# =============================================================================
# Forbidden Patterns
# =============================================================================

# Patterns that indicate OpenAI SDK/API usage in frontend code
FORBIDDEN_PATTERNS = [
    # OpenAI SDK imports
    {
        "name": "OpenAI SDK Import",
        "pattern": r"^\s*import\s+openai\b",
        "severity": "CRITICAL",
        "description": "Direct OpenAI SDK import detected",
    },
    {
        "name": "OpenAI SDK From-Import",
        "pattern": r"^\s*from\s+openai\b",
        "severity": "CRITICAL",
        "description": "OpenAI SDK from-import detected",
    },
    # OpenAI API key patterns
    {
        "name": "OpenAI API Key Variable",
        "pattern": r"\bOPENAI_API_KEY\b",
        "severity": "CRITICAL",
        "description": "OpenAI API key variable reference",
    },
    {
        "name": "OpenAI API Key Literal (sk-proj-)",
        "pattern": r"\bsk-proj-[a-zA-Z0-9]{20,}",
        "severity": "CRITICAL",
        "description": "OpenAI API key literal detected (sk-proj-...)",
    },
    {
        "name": "OpenAI API Key Literal (sk-)",
        "pattern": r"\bsk-[a-zA-Z0-9]{20,}",
        "severity": "CRITICAL",
        "description": "OpenAI API key literal detected (sk-...)",
    },
    # Additional patterns for thoroughness
    {
        "name": "OpenAI API Endpoint",
        "pattern": r"api\.openai\.com",
        "severity": "HIGH",
        "description": "Direct OpenAI API endpoint reference",
    },
    {
        "name": "OpenAI Constructor",
        "pattern": r"\bnew\s+OpenAI\s*\(",
        "severity": "CRITICAL",
        "description": "OpenAI client constructor detected",
    },
    {
        "name": "OpenAI Chat Completion",
        "pattern": r"openai\.chat\.completions",
        "severity": "CRITICAL",
        "description": "OpenAI chat completions API usage",
    },
    {
        "name": "createChatCompletion",
        "pattern": r"createChatCompletion",
        "severity": "HIGH",
        "description": "OpenAI chat completion function call",
    },
]

# Environment variable patterns (for .env files)
ENV_FORBIDDEN_PATTERNS = [
    {
        "name": "VITE_OPENAI_API_KEY",
        "pattern": r"^\s*VITE_OPENAI_API_KEY\s*=",
        "severity": "CRITICAL",
        "description": "Vite-exposed OpenAI API key",
    },
    {
        "name": "REACT_APP_OPENAI_API_KEY",
        "pattern": r"^\s*REACT_APP_OPENAI_API_KEY\s*=",
        "severity": "CRITICAL",
        "description": "React-exposed OpenAI API key",
    },
    {
        "name": "NEXT_PUBLIC_OPENAI_API_KEY",
        "pattern": r"^\s*NEXT_PUBLIC_OPENAI_API_KEY\s*=",
        "severity": "CRITICAL",
        "description": "Next.js-exposed OpenAI API key",
    },
    {
        "name": "Any Exposed OpenAI Key",
        "pattern": r"^\s*[A-Z_]*OPENAI[A-Z_]*\s*=\s*sk-",
        "severity": "CRITICAL",
        "description": "Exposed OpenAI key in environment file",
    },
]

# File extensions to scan
SCANNABLE_EXTENSIONS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".vue",
    ".svelte",
    ".astro",
}

# Directories to skip
SKIP_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".output",
    "coverage",
    ".turbo",
}


def find_frontend_dir() -> Path | None:
    """Find the frontend directory in the project."""
    possible_names = [
        "dragonfly-dashboard",
        "frontend",
        "client",
        "web",
        "app",
    ]

    for name in possible_names:
        path = PROJECT_ROOT / name
        if path.is_dir() and (path / "package.json").exists():
            return path

    return None


def scan_file_for_patterns(
    file_path: Path,
    patterns: list[dict],
    relative_to: Path,
) -> list[SecurityViolation]:
    """Scan a single file for forbidden patterns."""
    violations = []

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        for line_num, line in enumerate(lines, start=1):
            for pattern_def in patterns:
                regex = re.compile(pattern_def["pattern"], re.IGNORECASE)
                match = regex.search(line)
                if match:
                    violations.append(
                        SecurityViolation(
                            file_path=str(file_path.relative_to(relative_to)),
                            line_number=line_num,
                            pattern_name=pattern_def["name"],
                            matched_text=match.group(0)[:50],  # Truncate for display
                            severity=pattern_def["severity"],
                        )
                    )
    except Exception as e:
        print(f"  ⚠️  Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return violations


def scan_env_files(frontend_dir: Path) -> list[SecurityViolation]:
    """Scan environment files for exposed OpenAI keys."""
    violations = []

    env_files = [
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.development.local",
        ".env.production.local",
    ]

    for env_file in env_files:
        env_path = frontend_dir / env_file
        if env_path.exists():
            violations.extend(
                scan_file_for_patterns(env_path, ENV_FORBIDDEN_PATTERNS, frontend_dir)
            )

    return violations


def scan_frontend(
    frontend_dir: Path,
    verbose: bool = False,
) -> ScanResult:
    """
    Scan the frontend directory for OpenAI-related security violations.

    Args:
        frontend_dir: Path to the frontend directory
        verbose: If True, print detailed progress

    Returns:
        ScanResult with all violations found
    """
    result = ScanResult()

    if not frontend_dir.exists():
        raise FileNotFoundError(f"Frontend directory not found: {frontend_dir}")

    src_dir = frontend_dir / "src"
    if not src_dir.exists():
        print(f"  ⚠️  Warning: No src/ directory found in {frontend_dir}", file=sys.stderr)
        src_dir = frontend_dir  # Fall back to scanning the whole frontend dir

    if verbose:
        print(f"  📂 Scanning: {frontend_dir}")
        print(f"  📂 Source directory: {src_dir}")

    # Scan source files
    for root, dirs, files in os.walk(src_dir):
        # Skip forbidden directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in files:
            file_path = Path(root) / filename

            # Only scan relevant file types
            if file_path.suffix.lower() not in SCANNABLE_EXTENSIONS:
                continue

            result.files_scanned += 1

            if verbose and result.files_scanned % 100 == 0:
                print(f"    ... scanned {result.files_scanned} files")

            violations = scan_file_for_patterns(file_path, FORBIDDEN_PATTERNS, frontend_dir)
            result.violations.extend(violations)

    # Scan environment files
    env_violations = scan_env_files(frontend_dir)
    result.violations.extend(env_violations)
    result.env_files_checked = len(
        [
            f
            for f in [".env", ".env.local", ".env.development", ".env.production"]
            if (frontend_dir / f).exists()
        ]
    )

    return result


def print_report(result: ScanResult, frontend_dir: Path) -> None:
    """Print the scan report."""
    print("\n" + "═" * 60)
    print("  FRONTEND SECURITY SCAN REPORT")
    print("═" * 60)
    print(f"  Directory:       {frontend_dir}")
    print(f"  Files Scanned:   {result.files_scanned}")
    print(f"  Env Files:       {result.env_files_checked}")
    print("─" * 60)

    if result.is_clean:
        print("\n  ✅ FRONTEND IS STRICTLY DECOUPLED FROM OPENAI")
        print("     No forbidden patterns detected.")
        print("     RAG Safety Policy #1 is enforced.")
    else:
        print(f"\n  🚨 SECURITY VIOLATIONS DETECTED: {len(result.violations)}")
        print(f"     CRITICAL: {result.critical_count}")
        print(f"     HIGH:     {result.high_count}")
        print("\n  Violations:")
        print("  " + "─" * 56)

        # Group by file
        by_file: dict[str, list[SecurityViolation]] = {}
        for v in result.violations:
            by_file.setdefault(v.file_path, []).append(v)

        for file_path, violations in sorted(by_file.items()):
            print(f"\n  📄 {file_path}")
            for v in violations:
                icon = "🔴" if v.severity == "CRITICAL" else "🟠"
                print(f"     {icon} Line {v.line_number}: {v.pattern_name}")
                print(f"        Matched: {v.matched_text}")

    print("\n" + "═" * 60)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scan frontend for OpenAI security violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
RAG Safety Policy #1: Frontend NEVER talks to OpenAI directly.

Examples:
    python -m tools.scan_frontend_security
    python -m tools.scan_frontend_security --frontend-dir ./dragonfly-dashboard
    python -m tools.scan_frontend_security --verbose
        """,
    )
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=None,
        help="Path to frontend directory (auto-detected if not specified)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed progress",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any finding (including HIGH severity)",
    )

    args = parser.parse_args()

    # Find or use specified frontend directory
    if args.frontend_dir:
        frontend_dir = args.frontend_dir.resolve()
    else:
        frontend_dir = find_frontend_dir()
        if frontend_dir is None:
            print("❌ Error: Could not find frontend directory.", file=sys.stderr)
            print("   Use --frontend-dir to specify the path.", file=sys.stderr)
            return 2

    print("🔍 Frontend Security Scanner")
    print("   RAG Safety Policy #1: Frontend NEVER talks to OpenAI")

    try:
        result = scan_frontend(frontend_dir, verbose=args.verbose)
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 2

    if args.json:
        import json

        output = {
            "frontend_dir": str(frontend_dir),
            "is_clean": result.is_clean,
            "files_scanned": result.files_scanned,
            "env_files_checked": result.env_files_checked,
            "violations": [
                {
                    "file": v.file_path,
                    "line": v.line_number,
                    "pattern": v.pattern_name,
                    "matched": v.matched_text,
                    "severity": v.severity,
                }
                for v in result.violations
            ],
            "summary": {
                "critical": result.critical_count,
                "high": result.high_count,
            },
        }
        print(json.dumps(output, indent=2))
    else:
        print_report(result, frontend_dir)

    # Exit code
    if result.critical_count > 0:
        return 1
    if args.strict and result.high_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
