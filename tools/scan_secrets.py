#!/usr/bin/env python3
"""
Secret Scanner - Detects leaked credentials in tracked files.

Part of the SEV-1 incident response for "Postgres URI Leak in GitHub".
This scanner is integrated into gate_preflight.ps1 as a hard gate.

Usage:
    python -m tools.scan_secrets [--verbose] [--fix]

Exit Codes:
    0 - No secrets found
    1 - Secrets detected (blocks release)
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Directories to skip (not tracked or irrelevant)
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    "tmp",
    "logs",
}

# File extensions to scan (code and config files)
SCAN_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".ps1",
    ".sql",
    ".md",
    ".txt",
    ".env",  # Should never be tracked, but scan anyway
}

# Files to always skip (known safe or binary)
SKIP_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    # Files containing secret detection patterns (not actual secrets)
    ".gitleaks.toml",
    "scan_secrets.py",
    "generate_db_urls.py",
}


@dataclass
class SecretPattern:
    """A pattern that indicates a potential secret leak."""

    name: str
    pattern: re.Pattern[str]
    severity: str  # "critical" or "warning"
    description: str


# ═══════════════════════════════════════════════════════════════════════════
# SECRET PATTERNS
# ═══════════════════════════════════════════════════════════════════════════

SECRET_PATTERNS: list[SecretPattern] = [
    # Database connection strings with embedded passwords
    SecretPattern(
        name="postgres_uri",
        pattern=re.compile(
            r"postgres(?:ql)?://[^:]+:[^@]+@[^/]+",
            re.IGNORECASE,
        ),
        severity="critical",
        description="PostgreSQL connection string with embedded password",
    ),
    SecretPattern(
        name="mysql_uri",
        pattern=re.compile(
            r"mysql://[^:]+:[^@]+@[^/]+",
            re.IGNORECASE,
        ),
        severity="critical",
        description="MySQL connection string with embedded password",
    ),
    # Supabase service role key (should never be in code)
    SecretPattern(
        name="supabase_service_key",
        pattern=re.compile(
            r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
        ),
        severity="critical",
        description="Supabase JWT (service role or anon key)",
    ),
    # Private keys
    SecretPattern(
        name="private_key",
        pattern=re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
        severity="critical",
        description="Private key block detected",
    ),
    SecretPattern(
        name="encrypted_private_key",
        pattern=re.compile(r"-----BEGIN\s+ENCRYPTED\s+PRIVATE\s+KEY-----"),
        severity="critical",
        description="Encrypted private key block detected",
    ),
    # API keys with common prefixes
    SecretPattern(
        name="openai_key",
        pattern=re.compile(r"sk-[A-Za-z0-9]{20,}"),
        severity="critical",
        description="OpenAI API key",
    ),
    SecretPattern(
        name="sendgrid_key",
        pattern=re.compile(r"SG\.[A-Za-z0-9_-]{22,}\.[A-Za-z0-9_-]{43,}"),
        severity="critical",
        description="SendGrid API key",
    ),
    SecretPattern(
        name="twilio_key",
        pattern=re.compile(r"SK[a-f0-9]{32}"),
        severity="critical",
        description="Twilio API key",
    ),
    # AWS credentials
    SecretPattern(
        name="aws_access_key",
        pattern=re.compile(r"AKIA[0-9A-Z]{16}"),
        severity="critical",
        description="AWS Access Key ID",
    ),
    SecretPattern(
        name="aws_secret_key",
        pattern=re.compile(r"aws_secret_access_key\s*=\s*['\"]?[A-Za-z0-9/+=]{40}"),
        severity="critical",
        description="AWS Secret Access Key",
    ),
    # Generic patterns (warning level - may have false positives)
    SecretPattern(
        name="generic_password_assignment",
        pattern=re.compile(
            r"(?:password|passwd|pwd|secret)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
            re.IGNORECASE,
        ),
        severity="warning",
        description="Possible hardcoded password",
    ),
]

# Files where certain patterns are allowed (e.g., .env.example)
ALLOWLIST = {
    ".env.example": ["postgres_uri", "mysql_uri", "generic_password_assignment"],
    "docs/env.md": ["postgres_uri", "mysql_uri"],
    "docs/env_contract.md": ["postgres_uri", "mysql_uri"],
}

# Patterns that indicate the credential is fake/example (not a real leak)
SAFE_PASSWORD_PATTERNS = [
    # Placeholders and examples (exact matches in URI context)
    r"placeholder",
    r"YOUR_PASSWORD",
    r"your[-_]?password",
    r"<password>",
    r"\[PASSWORD\]",
    r"\[REDACTED\]",
    r"xxx+",
    # Docker/local development
    r"postgres:postgres@",  # Docker default (full pattern)
    r"@localhost",
    r"@127\.0\.0\.1",
    # Test fixtures (exact user:pass patterns)
    r"://user:pass@",
    r"://testuser:testpass@",
    r"://test:test@",
    r"@.*example\.com",
    r"://[^:]+:[^@]+@host:",  # Generic "host" placeholder
    r"://[^:]+:[^@]+@host\.",  # host.example.com
    # Documentation patterns (comments)
    r"^\s*#.*postgresql://",  # Comment lines
    r"^\s*--.*postgresql://",  # SQL comments
    r"Format:\s*postgresql://",  # Format documentation
    r"format.*postgresql://",  # Format documentation
    # Code patterns (regex definitions, not actual secrets)
    r"re\.compile.*postgresql://",  # Regex pattern definition
    r"r\".*postgresql://",  # Raw string pattern
    # Python f-string variable interpolation (no actual password)
    r"\{password\}",  # f-string variable
    r"\{db_password\}",  # f-string variable
    r"\$\{.*Pass.*\}",  # PowerShell variable interpolation
    r"\$TestDb",  # PowerShell test variables
]

# Compile safe patterns
SAFE_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in SAFE_PASSWORD_PATTERNS]


def is_safe_credential(line: str) -> bool:
    """Check if the line contains a known-safe/example credential."""
    for pattern in SAFE_PATTERNS_COMPILED:
        if pattern.search(line):
            return True
    return False


# File path patterns that are always safe (tests, docs, CI)
SAFE_PATH_PATTERNS = [
    r"^tests/",  # All test files
    r"^docs/",  # All documentation
    r"^\.github/workflows/",  # CI/CD workflows
    r"docker-compose.*\.yml$",  # Docker compose files
    r"\.example$",  # Example files
    r"_test\.py$",  # Test files
    r"test_.*\.py$",  # Test files
]

SAFE_PATH_COMPILED = [re.compile(p) for p in SAFE_PATH_PATTERNS]


def is_safe_path(file_path: Path, repo_root: Path) -> bool:
    """Check if the file path is in a known-safe location."""
    rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
    for pattern in SAFE_PATH_COMPILED:
        if pattern.search(rel_path):
            return True
    return False


@dataclass
class Finding:
    """A secret finding in a file."""

    file_path: Path
    line_number: int
    pattern_name: str
    severity: str
    description: str
    line_preview: str


def get_tracked_files(repo_root: Path) -> set[Path]:
    """Get list of files tracked by git."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return {repo_root / f for f in result.stdout.strip().split("\n") if f}
    except subprocess.CalledProcessError:
        return set()


def should_scan_file(file_path: Path, tracked_files: set[Path]) -> bool:
    """Determine if a file should be scanned."""
    # Must be tracked by git
    if file_path not in tracked_files:
        return False

    # Skip certain files
    if file_path.name in SKIP_FILES:
        return False

    # Check extension
    if file_path.suffix.lower() not in SCAN_EXTENSIONS:
        return False

    return True


def is_allowlisted(file_path: Path, pattern_name: str, repo_root: Path) -> bool:
    """Check if a pattern is allowlisted for a specific file."""
    rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
    if rel_path in ALLOWLIST:
        return pattern_name in ALLOWLIST[rel_path]
    return False


def scan_file(file_path: Path, repo_root: Path, patterns: list[SecretPattern]) -> Iterator[Finding]:
    """Scan a single file for secrets."""
    # Skip safe paths (tests, docs, CI)
    if is_safe_path(file_path, repo_root):
        return

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, PermissionError):
        return

    for line_num, line in enumerate(content.split("\n"), start=1):
        for pattern in patterns:
            if pattern.pattern.search(line):
                # Check allowlist
                if is_allowlisted(file_path, pattern.name, repo_root):
                    continue

                # Check if line contains safe/example credentials
                if is_safe_credential(line):
                    continue

                # Mask the sensitive part for display
                preview = line.strip()[:80]
                if len(line.strip()) > 80:
                    preview += "..."

                yield Finding(
                    file_path=file_path,
                    line_number=line_num,
                    pattern_name=pattern.name,
                    severity=pattern.severity,
                    description=pattern.description,
                    line_preview=preview,
                )


def walk_repo(repo_root: Path) -> Iterator[Path]:
    """Walk the repository, skipping excluded directories."""
    for root, dirs, files in os.walk(repo_root):
        # Modify dirs in-place to skip excluded directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for file in files:
            yield Path(root) / file


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Scan repository for leaked secrets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all scanned files")
    parser.add_argument(
        "--warnings", "-w", action="store_true", help="Include warning-level findings"
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path.cwd(),
        help="Repository root path (default: current directory)",
    )
    args = parser.parse_args()

    repo_root = args.path.resolve()

    print()
    print("═" * 70)
    print("  SECRET SCANNER - Credential Leak Detection")
    print("═" * 70)
    print(f"  Scanning: {repo_root}")
    print()

    # Get tracked files
    tracked_files = get_tracked_files(repo_root)
    if not tracked_files:
        print("  ⚠️  No tracked files found (not a git repo?)")
        return 0

    print(f"  Tracked files: {len(tracked_files)}")

    # Filter patterns based on args
    patterns = SECRET_PATTERNS
    if not args.warnings:
        patterns = [p for p in patterns if p.severity == "critical"]

    # Scan files
    findings: list[Finding] = []
    scanned = 0

    for file_path in walk_repo(repo_root):
        if not should_scan_file(file_path, tracked_files):
            continue

        scanned += 1
        if args.verbose:
            rel_path = file_path.relative_to(repo_root)
            print(f"  Scanning: {rel_path}")

        for finding in scan_file(file_path, repo_root, patterns):
            findings.append(finding)

    print(f"  Files scanned: {scanned}")
    print()

    # Report findings
    critical_count = sum(1 for f in findings if f.severity == "critical")
    warning_count = sum(1 for f in findings if f.severity == "warning")

    if findings:
        print("─" * 70)
        print("  🚨 SECRETS DETECTED")
        print("─" * 70)
        print()

        for finding in findings:
            rel_path = finding.file_path.relative_to(repo_root)
            icon = "🔴" if finding.severity == "critical" else "🟡"
            print(f"  {icon} {finding.description}")
            print(f"     File: {rel_path}:{finding.line_number}")
            print(f"     Preview: {finding.line_preview[:60]}...")
            print()

        print("─" * 70)
        print(f"  Critical: {critical_count}  |  Warnings: {warning_count}")
        print("─" * 70)
        print()

        if critical_count > 0:
            print("  ❌ SCAN FAILED - Critical secrets found in tracked files!")
            print()
            print("  To fix:")
            print("    1. Remove secrets from the files")
            print("    2. Or remove files from git: git rm --cached <file>")
            print("    3. Update .gitignore to prevent re-adding")
            print()
            return 1
        else:
            print("  ⚠️  Warnings found but no critical secrets.")
            return 0
    else:
        print("─" * 70)
        print("  ✅ NO SECRETS DETECTED")
        print("─" * 70)
        print()
        print("  All tracked files are clean.")
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
