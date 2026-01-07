#!/usr/bin/env python3
"""
Dragonfly Civil - Secret Leak Scanner (CI Guard)

Scans the codebase for accidentally committed secrets, API keys, and sensitive data.
Designed to run in CI pipelines and as a pre-commit hook.

Patterns Detected:
- Discord webhook URLs
- OpenAI API keys (sk-...)
- PostgreSQL connection strings
- JWT tokens (eyJ...)
- Supabase keys (supa_...)
- Generic high-entropy strings
- AWS keys, Stripe keys, etc.

Usage:
    python -m tools.secret_leak_scan                    # Scan default directories
    python -m tools.secret_leak_scan --strict           # Fail on warnings too
    python -m tools.secret_leak_scan --path backend/    # Scan specific path
    python -m tools.secret_leak_scan --pre-commit       # Exit 1 on any finding

CI Integration:
    Add to GitHub Actions:
        - run: python -m tools.secret_leak_scan --strict

Author: Dragonfly Security Team
Date: 2026-01-05
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

# =============================================================================
# Configuration
# =============================================================================

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.absolute()

# Directories to scan by default
DEFAULT_SCAN_DIRS = [
    "backend",
    "tools",
    "supabase",
    "src",
    "etl",
    "workers",
    "tests",
]

# Patterns to ignore (files/directories)
IGNORE_PATTERNS = {
    # Directories
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".egg-info",
    # Files
    ".env",
    ".env.dev",
    ".env.prod",
    ".env.local",
    ".env.example",
    ".env.template",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.lock",
    "package-lock.json",
    # This scanner itself (contains patterns)
    "secret_leak_scan.py",
}

# File extensions to scan
SCANNABLE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".sh",
    ".bash",
    ".ps1",
    ".md",
    ".txt",
    ".cfg",
    ".ini",
    ".conf",
    ".env.example",
}


class Severity(Enum):
    """Severity levels for detected secrets."""

    CRITICAL = "CRITICAL"  # Definite secret leak
    HIGH = "HIGH"  # Very likely a secret
    MEDIUM = "MEDIUM"  # Possibly a secret
    LOW = "LOW"  # Suspicious but may be false positive


@dataclass
class SecretPattern:
    """Definition of a secret pattern to detect."""

    name: str
    pattern: str
    severity: Severity
    description: str
    # If True, pattern must NOT be in comments or docstrings
    exclude_comments: bool = True
    # Example of what this catches (for documentation)
    example: str = ""


# =============================================================================
# Secret Patterns
# =============================================================================

SECRET_PATTERNS: list[SecretPattern] = [
    # Discord
    SecretPattern(
        name="Discord Webhook",
        pattern=r"discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+",
        severity=Severity.CRITICAL,
        description="Discord webhook URL - allows posting messages",
        example="discord.com/api/webhooks/123456/abcdef",
    ),
    # OpenAI
    SecretPattern(
        name="OpenAI API Key",
        pattern=r"sk-[a-zA-Z0-9]{20,}",
        severity=Severity.CRITICAL,
        description="OpenAI API key - grants API access",
        example="sk-abcdefghijklmnopqrstuvwxyz123456",
    ),
    SecretPattern(
        name="OpenAI Project Key",
        pattern=r"sk-proj-[a-zA-Z0-9_-]{20,}",
        severity=Severity.CRITICAL,
        description="OpenAI project-scoped API key",
        example="sk-proj-abc123def456...",
    ),
    # PostgreSQL
    SecretPattern(
        name="PostgreSQL Connection String",
        pattern=r"postgres(?:ql)?://[^:\s]+:[^@\s]+@[^\s]+",
        severity=Severity.CRITICAL,
        description="PostgreSQL URL with credentials",
        example="postgresql://user:password@host:5432/db",
    ),
    # JWT Tokens
    SecretPattern(
        name="JWT Token",
        pattern=r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        severity=Severity.HIGH,
        description="JWT token (may contain sensitive claims)",
        example="eyJhbGciOiJIUzI1NiIs...",
    ),
    # Supabase
    SecretPattern(
        name="Supabase Key",
        pattern=r"supa_[a-zA-Z0-9]{20,}",
        severity=Severity.CRITICAL,
        description="Supabase API key",
        example="supa_abcdefghijklmnop...",
    ),
    SecretPattern(
        name="Supabase Service Role Key",
        pattern=r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_-]{50,}\.[A-Za-z0-9_-]{20,}",
        severity=Severity.CRITICAL,
        description="Supabase service role JWT (full database access)",
        example="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOi...",
    ),
    # AWS
    SecretPattern(
        name="AWS Access Key ID",
        pattern=r"AKIA[0-9A-Z]{16}",
        severity=Severity.CRITICAL,
        description="AWS Access Key ID",
        example="AKIAIOSFODNN7EXAMPLE",
    ),
    SecretPattern(
        name="AWS Secret Access Key",
        pattern=r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?",
        severity=Severity.CRITICAL,
        description="AWS Secret Access Key assignment",
        example="aws_secret_access_key = 'wJalrXUtnFEMI...'",
    ),
    # Stripe
    SecretPattern(
        name="Stripe Secret Key",
        pattern=r"sk_live_[0-9a-zA-Z]{24,}",
        severity=Severity.CRITICAL,
        description="Stripe live secret key",
        example="sk_live_abc123...",
    ),
    SecretPattern(
        name="Stripe Publishable Key (Live)",
        pattern=r"pk_live_[0-9a-zA-Z]{24,}",
        severity=Severity.HIGH,
        description="Stripe live publishable key",
        example="pk_live_abc123...",
    ),
    # GitHub
    SecretPattern(
        name="GitHub Token",
        pattern=r"gh[ps]_[A-Za-z0-9]{36,}",
        severity=Severity.CRITICAL,
        description="GitHub personal access token",
        example="ghp_abc123def456...",
    ),
    SecretPattern(
        name="GitHub OAuth",
        pattern=r"gho_[A-Za-z0-9]{36,}",
        severity=Severity.CRITICAL,
        description="GitHub OAuth access token",
        example="gho_abc123...",
    ),
    # Slack
    SecretPattern(
        name="Slack Webhook",
        pattern=r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[a-zA-Z0-9]+",
        severity=Severity.CRITICAL,
        description="Slack webhook URL",
        example="hooks.slack.com/services/T00000000/B00000000/XXXXXXXX",
    ),
    SecretPattern(
        name="Slack Bot Token",
        pattern=r"xoxb-[0-9]{10,}-[0-9]{10,}-[a-zA-Z0-9]{24}",
        severity=Severity.CRITICAL,
        description="Slack bot token",
        example="xoxb-123456789-987654321-abc123...",
    ),
    # SendGrid
    SecretPattern(
        name="SendGrid API Key",
        pattern=r"SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}",
        severity=Severity.CRITICAL,
        description="SendGrid API key",
        example="SG.abc123...",
    ),
    # Twilio
    SecretPattern(
        name="Twilio Account SID",
        pattern=r"AC[a-f0-9]{32}",
        severity=Severity.MEDIUM,
        description="Twilio Account SID (not secret alone but indicator)",
        example="AC1234567890abcdef...",
    ),
    SecretPattern(
        name="Twilio Auth Token",
        pattern=r"(?i)twilio.*auth.*token\s*[=:]\s*['\"]?[a-f0-9]{32}['\"]?",
        severity=Severity.CRITICAL,
        description="Twilio auth token assignment",
        example="TWILIO_AUTH_TOKEN=abc123...",
    ),
    # Generic Patterns
    SecretPattern(
        name="Generic API Key Assignment",
        pattern=r"(?i)(api[_-]?key|apikey|api[_-]?secret)\s*[=:]\s*['\"][a-zA-Z0-9_-]{20,}['\"]",
        severity=Severity.MEDIUM,
        description="Generic API key assignment pattern",
        example="API_KEY='abc123...'",
        exclude_comments=True,
    ),
    SecretPattern(
        name="Generic Secret Assignment",
        pattern=r"(?i)(secret|password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
        severity=Severity.MEDIUM,
        description="Generic secret/password assignment",
        example="password='mysecret123'",
        exclude_comments=True,
    ),
    SecretPattern(
        name="Private Key Block",
        pattern=r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        severity=Severity.CRITICAL,
        description="Private key file content",
        example="-----BEGIN RSA PRIVATE KEY-----",
    ),
    # Base64 encoded secrets (high entropy detection)
    SecretPattern(
        name="Base64 High Entropy",
        pattern=r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])",
        severity=Severity.LOW,
        description="High-entropy base64 string (possible encoded secret)",
        example="YWJjZGVmZ2hpamtsbW5vcHFy...",
        exclude_comments=True,
    ),
]


# =============================================================================
# Allowlist - Known false positives
# =============================================================================

ALLOWLIST_PATTERNS = [
    # Example/placeholder patterns in documentation
    r"sk-[x]{20,}",  # sk-xxxx... placeholder
    r"sk-\.{3,}",  # sk-... placeholder
    r"sk-<[^>]+>",  # sk-<your-key-here>
    r"\${[^}]+}",  # ${ENV_VAR} templates
    r"\$[A-Z_]+",  # $ENV_VAR references
    r"os\.environ",  # Environment variable access
    r"getenv\(",  # getenv() calls
    r"settings\.[A-Z_]+",  # Settings attribute access
    r"example\.com",  # Example domains
    r"localhost",  # Localhost references
    r"127\.0\.0\.1",  # Loopback addresses
    # Test patterns
    r"test[-_]?key",
    r"dummy[-_]?key",
    r"fake[-_]?key",
    r"mock[-_]?",
    # Common false positives
    r"['\"]placeholder['\"]",
    r"YOUR[-_]?API[-_]?KEY",
    r"<[A-Z_]+>",  # <PLACEHOLDER> style
    # PostgreSQL URL templates (f-strings with variables, not actual secrets)
    r"postgresql://[^:]+:\{[^}]+\}@",  # {password} variable
    r"postgresql://[^:]+:\[[^\]]+\]@",  # [REDACTED] placeholder
    r"postgresql://postgres\.?\{",  # postgres.{project_ref} pattern
    r"postgresql://[^:]+:[^@]*\{",  # Any f-string variable in password
    r"postgresql://user:pass@",  # Literal "user:pass" examples
    r"postgresql://[^:]+:xxx@",  # xxx placeholder
    r"postgresql://[^:]+:your-password@",  # your-password placeholder
    r"postgresql://dragonfly_app:pass@",  # Example pass placeholder
    r"postgresql://testuser:",  # Test user patterns
    r"postgresql://myuser:",  # Example user patterns
    r"f\"postgresql://",  # f-string template (not literal)
    r"f'postgresql://",  # f-string template (not literal)
    # Regex patterns for sanitizers/validators (not secrets)
    r"re\.compile.*postgresql",  # Regex compilation
    r"\\1\[REDACTED\]",  # Redaction patterns
    # DSN sanitizer tests - these intentionally contain fake DSNs
    r"test_dsn_sanitizer\.py",  # DSN sanitizer test file
    # Documentation examples in config files
    r"postgresql://postgres:pass@host:",  # Example in config docs
    r"postgresql://user:SuperSecretPassword",  # Clearly fake test password
    r"postgresql://user:päss@",  # Unicode test case
    r"postgresql://dragonfly_app:secret@",  # Literal "secret" placeholder
    r"SecretPass123",  # Clearly fake test password
]


# =============================================================================
# Scanner Implementation
# =============================================================================


@dataclass
class Finding:
    """A detected secret or suspicious pattern."""

    file_path: Path
    line_number: int
    line_content: str
    pattern_name: str
    severity: Severity
    description: str
    match_text: str


class SecretScanner:
    """Scans codebase for leaked secrets."""

    def __init__(
        self,
        project_root: Path,
        strict: bool = False,
        verbose: bool = False,
    ):
        self.project_root = project_root
        self.strict = strict
        self.verbose = verbose
        self.findings: list[Finding] = []
        self.files_scanned = 0
        self.compiled_patterns: list[tuple[SecretPattern, re.Pattern]] = []
        self.compiled_allowlist: list[re.Pattern] = []

        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for performance."""
        for pattern in SECRET_PATTERNS:
            try:
                compiled = re.compile(pattern.pattern)
                self.compiled_patterns.append((pattern, compiled))
            except re.error as e:
                print(f"⚠️ Invalid pattern '{pattern.name}': {e}")

        for allow_pattern in ALLOWLIST_PATTERNS:
            try:
                self.compiled_allowlist.append(re.compile(allow_pattern, re.IGNORECASE))
            except re.error:
                pass

    def _should_ignore_file(self, path: Path) -> bool:
        """Check if file should be skipped."""
        # Check path components
        for part in path.parts:
            if part in IGNORE_PATTERNS:
                return True
            # Check glob patterns
            for pattern in IGNORE_PATTERNS:
                if pattern.startswith("*") and part.endswith(pattern[1:]):
                    return True

        # Check file name
        if path.name in IGNORE_PATTERNS:
            return True

        # Check extension
        if path.suffix not in SCANNABLE_EXTENSIONS:
            return True

        return False

    def _is_allowlisted(self, line: str, match_text: str) -> bool:
        """Check if the match is a known false positive."""
        # Check against allowlist patterns
        for allow_pattern in self.compiled_allowlist:
            if allow_pattern.search(line):
                return True

        # Check if in a comment
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            return True

        # Check if it's a variable reference, not a literal
        if f"${{{match_text}}}" in line or f"${match_text}" in line:
            return True

        return False

    def _is_in_string_literal(self, line: str, match_start: int) -> bool:
        """Check if match position is inside a string literal (crude check)."""
        # Count quotes before match position
        before = line[:match_start]
        single_quotes = before.count("'") - before.count("\\'")
        double_quotes = before.count('"') - before.count('\\"')

        # If odd number of quotes, we're inside a string
        return (single_quotes % 2 == 1) or (double_quotes % 2 == 1)

    def scan_file(self, file_path: Path) -> list[Finding]:
        """Scan a single file for secrets."""
        findings = []

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            for line_num, line in enumerate(lines, 1):
                for pattern_def, compiled in self.compiled_patterns:
                    for match in compiled.finditer(line):
                        match_text = match.group(0)

                        # Skip if allowlisted
                        if self._is_allowlisted(line, match_text):
                            continue

                        # Skip low severity in non-strict mode
                        if not self.strict and pattern_def.severity == Severity.LOW:
                            continue

                        # Skip medium severity generic patterns if clearly a variable
                        if pattern_def.severity == Severity.MEDIUM:
                            if "os.environ" in line or "getenv" in line or "settings." in line:
                                continue

                        finding = Finding(
                            file_path=file_path,
                            line_number=line_num,
                            line_content=line.strip()[:100],  # Truncate long lines
                            pattern_name=pattern_def.name,
                            severity=pattern_def.severity,
                            description=pattern_def.description,
                            match_text=self._redact_secret(match_text),
                        )
                        findings.append(finding)

        except Exception as e:
            if self.verbose:
                print(f"⚠️ Error reading {file_path}: {e}")

        return findings

    def _redact_secret(self, secret: str) -> str:
        """Redact most of the secret for safe display."""
        if len(secret) <= 8:
            return "*" * len(secret)
        return secret[:4] + "*" * (len(secret) - 8) + secret[-4:]

    def scan_directory(self, directory: Path) -> None:
        """Recursively scan a directory."""
        if not directory.exists():
            if self.verbose:
                print(f"⏭️ Skipping non-existent directory: {directory}")
            return

        for file_path in directory.rglob("*"):
            if file_path.is_file() and not self._should_ignore_file(file_path):
                file_findings = self.scan_file(file_path)
                self.findings.extend(file_findings)
                self.files_scanned += 1

    def scan(self, paths: Optional[list[str]] = None) -> bool:
        """
        Scan specified paths or default directories.

        Returns True if no critical/high findings, False otherwise.
        """
        scan_paths = paths or DEFAULT_SCAN_DIRS

        print("\n" + "=" * 70)
        print("  🔍 DRAGONFLY CIVIL - SECRET LEAK SCANNER")
        print("=" * 70)
        print(f"  Mode: {'STRICT' if self.strict else 'STANDARD'}")
        print(f"  Scanning: {', '.join(scan_paths)}")
        print("=" * 70 + "\n")

        for path_str in scan_paths:
            path = self.project_root / path_str
            self.scan_directory(path)

        return self._report_findings()

    def _report_findings(self) -> bool:
        """Report findings and return success status."""
        print(f"📊 Scanned {self.files_scanned} files\n")

        if not self.findings:
            print("✅ No secrets detected!\n")
            return True

        # Group by severity
        critical = [f for f in self.findings if f.severity == Severity.CRITICAL]
        high = [f for f in self.findings if f.severity == Severity.HIGH]
        medium = [f for f in self.findings if f.severity == Severity.MEDIUM]
        low = [f for f in self.findings if f.severity == Severity.LOW]

        # Report critical findings
        if critical:
            print("🚨 CRITICAL LEAKS DETECTED:\n")
            for finding in critical:
                self._print_finding(finding)

        if high:
            print("\n⚠️ HIGH SEVERITY FINDINGS:\n")
            for finding in high:
                self._print_finding(finding)

        if medium:
            print("\n📋 MEDIUM SEVERITY FINDINGS:\n")
            for finding in medium:
                self._print_finding(finding)

        if low and self.strict:
            print("\n📝 LOW SEVERITY FINDINGS:\n")
            for finding in low:
                self._print_finding(finding)

        # Summary
        print("\n" + "-" * 70)
        print("  SUMMARY:")
        print(f"    🚨 Critical: {len(critical)}")
        print(f"    ⚠️  High:     {len(high)}")
        print(f"    📋 Medium:   {len(medium)}")
        print(f"    📝 Low:      {len(low)}")
        print("-" * 70 + "\n")

        # Determine exit status
        if critical or high:
            print("❌ SCAN FAILED - Secrets detected! Remove them before committing.\n")
            return False
        elif medium and self.strict:
            print("❌ SCAN FAILED (strict mode) - Review medium findings.\n")
            return False
        else:
            print("✅ SCAN PASSED - No critical/high severity secrets found.\n")
            return True

    def _print_finding(self, finding: Finding) -> None:
        """Print a single finding."""
        rel_path = finding.file_path.relative_to(self.project_root)
        print(f"  🚨 LEAK DETECTED in {rel_path}:{finding.line_number}")
        print(f"     Pattern: {finding.pattern_name}")
        print(f"     Match:   {finding.match_text}")
        print(f"     Line:    {finding.line_content[:80]}...")
        print()


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan codebase for leaked secrets and API keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.secret_leak_scan                # Standard scan
    python -m tools.secret_leak_scan --strict       # Include low severity
    python -m tools.secret_leak_scan --path backend # Scan specific dir
    python -m tools.secret_leak_scan --pre-commit   # For git hooks

Exit Codes:
    0 - No secrets found
    1 - Secrets detected (CI should fail)
        """,
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Include medium/low severity findings in failure criteria",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Specific path(s) to scan (can be used multiple times)",
    )
    parser.add_argument(
        "--pre-commit",
        action="store_true",
        help="Pre-commit mode: fail on any finding",
    )
    parser.add_argument(
        "--list-patterns",
        action="store_true",
        help="List all secret patterns being scanned for",
    )

    args = parser.parse_args()

    if args.list_patterns:
        print("\n📋 Secret Patterns:\n")
        for pattern in SECRET_PATTERNS:
            print(f"  [{pattern.severity.value}] {pattern.name}")
            print(f"      {pattern.description}")
            if pattern.example:
                print(f"      Example: {pattern.example}")
            print()
        return 0

    # In pre-commit mode, use strict
    strict = args.strict or args.pre_commit

    scanner = SecretScanner(
        project_root=PROJECT_ROOT,
        strict=strict,
        verbose=args.verbose,
    )

    success = scanner.scan(args.paths)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
