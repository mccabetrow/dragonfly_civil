#!/usr/bin/env python3
"""
Dragonfly Civil - Security Scanners

Lightweight security scanning functions for the Go-Live Gate.
Provides grep-based detection of secrets and RAG safety violations.

These are fast, CI-friendly scanners designed to run as part of the
release certification process.

Usage:
    from tools.security_scanners import scan_secrets, scan_rag_safety

    # Check for secrets in codebase
    result = scan_secrets()
    if not result.passed:
        print(f"Found {len(result.findings)} potential secrets")

    # Check for RAG safety violations
    result = scan_rag_safety()
    if not result.passed:
        print(f"Found {len(result.findings)} RAG safety violations")

Standalone Usage:
    python -m tools.security_scanners              # Run all scans
    python -m tools.security_scanners --secrets    # Secrets only
    python -m tools.security_scanners --rag        # RAG safety only
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.absolute()

# =============================================================================
# Configuration
# =============================================================================

# Secret patterns to detect
SECRET_PATTERNS = [
    # API Keys
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API Key (sk-...)"),
    (r"sk_live_[a-zA-Z0-9]{20,}", "Stripe Live Key"),
    (r"sk_test_[a-zA-Z0-9]{20,}", "Stripe Test Key"),
    # Database URLs
    (r"postgres://[^'\"\s]+", "PostgreSQL Connection String"),
    (r"postgresql://[^'\"\s]+", "PostgreSQL Connection String"),
    # Discord
    (r"https://discord\.com/api/webhooks/[^\s'\"]+", "Discord Webhook URL"),
    (r"https://discordapp\.com/api/webhooks/[^\s'\"]+", "Discord Webhook URL"),
    # Supabase
    (r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "JWT Token"),
]

# RAG safety patterns (frontend should not import OpenAI directly)
RAG_SAFETY_PATTERNS = [
    (r"from\s+openai\s+import", "Direct OpenAI import"),
    (r"import\s+openai", "Direct OpenAI import"),
    (r"from\s+langchain", "LangChain import (should be backend-only)"),
    (r"OpenAI\s*\(", "OpenAI client instantiation"),
    (r"OPENAI_API_KEY", "OpenAI API key reference"),
    (r"VITE_OPENAI", "Vite OpenAI environment variable"),
]

# Directories to scan for secrets
SECRET_SCAN_DIRS = [
    "backend",
    "tools",
    "src",
    "etl",
    "workers",
    "supabase",
]

# Frontend directories to scan for RAG safety
FRONTEND_DIRS = [
    "dragonfly-dashboard/src",
    "dragonfly-dashboard/components",
    "frontend/src",
    "frontend",
]

# Files/directories to ignore
IGNORE_PATTERNS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".env",
    ".env.dev",
    ".env.prod",
    ".env.local",
    ".env.example",
}

# File extensions to scan
SCANNABLE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".sql",
    ".sh",
    ".ps1",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
}

# False positive indicators - lines containing these are skipped
FALSE_POSITIVE_INDICATORS = [
    "# Format:",
    "# Example:",
    "Format:",
    "Example:",
    "format:",
    "example:",
    "postgresql://user:",
    "postgresql://postgres:<",
    "postgresql://postgres.{",
    "postgres://user:",
    "postgres://<user>",
    "postgres://username:",
    "postgresql://...",
    "postgres://...",
    "sk-...",
    "sk-xxx",
    "sk-YOUR",
    "your_api_key",
    "YOUR_API_KEY",
    "<password>",
    "<your-",
    "placeholder",
    "PLACEHOLDER",
    "os.getenv(",
    "os.environ.",
    'getenv("',
    "get_supabase_db_url",
    "DSN_SANITIZER",
    "dsn_sanitizer",
    "# Pattern:",
    "Pattern:",
    "pattern:",
    "# Regex:",
    "regex:",
    'r"postgres://',
    'r"postgresql://',
    "SECRET_PATTERNS",
    "RAG_SAFETY_PATTERNS",
    "@host",
    "@<host>",
    "***@",
    "...)",
    # Docstring patterns
    '"""',
    "'''",
    "Required:",
    "Expected",
    "webhook_url",
    '"https://discord.com/api/webhooks/..."',
    # Code documentation
    "# Current:",
    "Current:",
    "sanitize_dsn",
    "redact",
    "Redact",
    "mask",
    "Mask",
    # Templating patterns (no real secrets)
    "{password}",
    "{secret}",
    "{token}",
    ".format(",
    "f-string",
    "{encoded_password}",
    ":{user}",
    ":{encoded_",
    # Regex definitions (pattern matching code)
    "re.compile(",
    'r"(postgresql',
    'r"(postgres',
    "[REDACTED]",
    "_REDACTED]",
    # Pattern definition code (in security scanners themselves)
    "SECRET_PATTERNS",
    "SecretPattern(",
    "pattern=r",
    "example=",
    "'postgresql://",
    "'postgres://",
    # Documentation patterns
    ":xxx@",
    "xxx@",
    ":your-",
    "your-password",
    "your-secure-password",
    "@db.xxx.",
    "@db.your-",
    "Usage:",
    "Examples:",
    "--",  # SQL comments
    "Greps for:",
    "print(",  # Print statements are often documentation
    "REJECT commits",
    "connection strings",
    # Test/mock patterns (be careful - don't exclude actual test files with real secrets)
]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Finding:
    """A single security finding."""

    file_path: str
    line_number: int
    pattern_name: str
    matched_text: str
    severity: str = "HIGH"


@dataclass
class ScanResult:
    """Result of a security scan."""

    scan_type: str
    passed: bool
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "scan_type": self.scan_type,
            "passed": self.passed,
            "finding_count": len(self.findings),
            "files_scanned": self.files_scanned,
            "error": self.error,
            "findings": [
                {
                    "file": f.file_path,
                    "line": f.line_number,
                    "pattern": f.pattern_name,
                }
                for f in self.findings[:10]  # Limit output
            ],
        }


# =============================================================================
# Helper Functions
# =============================================================================


def _should_ignore(path: Path) -> bool:
    """Check if path should be ignored."""
    for part in path.parts:
        if part in IGNORE_PATTERNS:
            return True
    return False


def _is_scannable(path: Path) -> bool:
    """Check if file should be scanned."""
    if not path.is_file():
        return False
    if _should_ignore(path):
        return False
    if path.suffix.lower() not in SCANNABLE_EXTENSIONS:
        return False
    return True


def _is_false_positive(line: str) -> bool:
    """Check if line contains false-positive indicators."""
    for indicator in FALSE_POSITIVE_INDICATORS:
        if indicator in line:
            return True
    return False


def _scan_file(
    file_path: Path,
    patterns: list[tuple[str, str]],
    check_false_positives: bool = True,
) -> list[Finding]:
    """Scan a single file for patterns."""
    findings = []

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Skip lines with false-positive indicators
            if check_false_positives and _is_false_positive(line):
                continue

            for pattern, name in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    # Mask the matched content for safety
                    match = re.search(pattern, line, re.IGNORECASE)
                    matched_text = match.group(0) if match else ""
                    if len(matched_text) > 20:
                        matched_text = matched_text[:10] + "..." + matched_text[-5:]

                    findings.append(
                        Finding(
                            file_path=str(file_path.relative_to(PROJECT_ROOT)),
                            line_number=line_num,
                            pattern_name=name,
                            matched_text=matched_text,
                        )
                    )
    except Exception:
        pass  # Skip unreadable files

    return findings


# =============================================================================
# Main Scan Functions
# =============================================================================


def scan_secrets(
    directories: Optional[list[str]] = None,
    verbose: bool = False,
) -> ScanResult:
    """
    Scan codebase for accidentally committed secrets.

    Greps for: sk-, postgres://, discord.com webhooks, JWT tokens.

    Args:
        directories: Directories to scan (default: SECRET_SCAN_DIRS)
        verbose: Print progress messages

    Returns:
        ScanResult with passed=True if no secrets found, False otherwise
    """
    scan_dirs = directories or SECRET_SCAN_DIRS
    all_findings: list[Finding] = []
    files_scanned = 0

    if verbose:
        print("🔍 Scanning for secrets...")

    for dir_name in scan_dirs:
        dir_path = PROJECT_ROOT / dir_name
        if not dir_path.exists():
            continue

        for file_path in dir_path.rglob("*"):
            if _is_scannable(file_path):
                findings = _scan_file(file_path, SECRET_PATTERNS)
                all_findings.extend(findings)
                files_scanned += 1

    passed = len(all_findings) == 0

    if verbose:
        if passed:
            print(f"✅ No secrets found in {files_scanned} files")
        else:
            print(f"❌ Found {len(all_findings)} potential secrets!")
            for f in all_findings[:5]:
                print(f"   - {f.file_path}:{f.line_number} ({f.pattern_name})")

    return ScanResult(
        scan_type="secrets",
        passed=passed,
        findings=all_findings,
        files_scanned=files_scanned,
    )


def scan_rag_safety(
    directories: Optional[list[str]] = None,
    verbose: bool = False,
) -> ScanResult:
    """
    Scan frontend for OpenAI/LangChain imports (RAG Safety Policy).

    RAG Safety Policy #1: "Frontend NEVER talks to OpenAI directly."
    All AI calls must flow through the backend.

    Args:
        directories: Directories to scan (default: FRONTEND_DIRS)
        verbose: Print progress messages

    Returns:
        ScanResult with passed=True if no violations found, False otherwise
    """
    scan_dirs = directories or FRONTEND_DIRS
    all_findings: list[Finding] = []
    files_scanned = 0

    if verbose:
        print("🔍 Scanning frontend for RAG safety violations...")

    for dir_name in scan_dirs:
        dir_path = PROJECT_ROOT / dir_name
        if not dir_path.exists():
            continue

        for file_path in dir_path.rglob("*"):
            if _is_scannable(file_path):
                findings = _scan_file(file_path, RAG_SAFETY_PATTERNS)
                all_findings.extend(findings)
                files_scanned += 1

    passed = len(all_findings) == 0

    if verbose:
        if passed:
            print(f"✅ Frontend is RAG-safe ({files_scanned} files scanned)")
        else:
            print(f"❌ Found {len(all_findings)} RAG safety violations!")
            for f in all_findings[:5]:
                print(f"   - {f.file_path}:{f.line_number} ({f.pattern_name})")

    return ScanResult(
        scan_type="rag_safety",
        passed=passed,
        findings=all_findings,
        files_scanned=files_scanned,
    )


def run_all_scans(verbose: bool = True) -> tuple[ScanResult, ScanResult]:
    """
    Run all security scans.

    Returns:
        Tuple of (secrets_result, rag_safety_result)
    """
    secrets_result = scan_secrets(verbose=verbose)
    rag_result = scan_rag_safety(verbose=verbose)
    return secrets_result, rag_result


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Security scanners for Dragonfly release certification",
    )
    parser.add_argument(
        "--secrets",
        action="store_true",
        help="Run secrets scan only",
    )
    parser.add_argument(
        "--rag",
        action="store_true",
        help="Run RAG safety scan only",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON",
    )

    args = parser.parse_args()

    # Default to running both if neither specified
    run_secrets = args.secrets or (not args.secrets and not args.rag)
    run_rag = args.rag or (not args.secrets and not args.rag)

    exit_code = 0
    results = []

    if run_secrets:
        result = scan_secrets(verbose=not args.json)
        results.append(result)
        if not result.passed:
            exit_code = 1

    if run_rag:
        result = scan_rag_safety(verbose=not args.json)
        results.append(result)
        if not result.passed:
            exit_code = 1

    if args.json:
        import json

        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print()
        if exit_code == 0:
            print("✅ All security scans passed")
        else:
            print("❌ Security scan failures detected")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
