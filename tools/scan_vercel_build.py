#!/usr/bin/env python3
"""
Dragonfly Vercel Build Security Scanner

This script runs during the Vercel build process to prevent secrets from being
exposed in the browser bundle. It performs three critical checks:

1. Environment Variable Hygiene – Detects forbidden VITE_* keywords, whitespace issues, and service_role leaks
2. Source Code Scan & Dependency Audit – Finds hardcoded secrets/DSNs and blocks OpenAI SDK imports
3. Supabase Key Validation – Ensures VITE_SUPABASE_ANON_KEY is never a service_role token

Usage:
    python tools/scan_vercel_build.py [--strict] [--src-dir PATH]

Exit Codes:
    0 - All checks passed
    1 - Security violation detected (build MUST fail)
    2 - Script error

Integration (vercel.json or package.json):
    "build": "pip install -r requirements.txt && python tools/scan_vercel_build.py && npm run build"
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

# =============================================================================
# CONFIGURATION
# =============================================================================

# VITE_ keys that are explicitly ALLOWED (safe for browser exposure)
ALLOWED_VITE_KEYS = frozenset(
    [
        "VITE_API_BASE_URL",  # Public API endpoint URL
        "VITE_SUPABASE_URL",  # Supabase project URL (public)
        "VITE_SUPABASE_ANON_KEY",  # Supabase anon key (RLS-protected, safe)
        "VITE_DRAGONFLY_API_KEY",  # API key used for backend auth headers
        "VITE_DEMO_MODE",  # Feature flag
        "VITE_IS_DEMO",  # Deprecated demo flag
        "VITE_DASHBOARD_SOURCE",  # Data source selector
        "VITE_DEBUG",  # Debug mode flag
        "VITE_LOG_LEVEL",  # Logging level
        "VITE_MOCK_MODE",  # Mock mode for testing
    ]
)

# Keywords that indicate a VITE_ key should NOT exist
FORBIDDEN_KEYWORDS = frozenset(
    [
        "SECRET",
        "KEY",  # Catches API keys, but allowlist overrides
        "SERVICE",  # service_role, service account
        "OPENAI",
        "ADMIN",
        "PASSWORD",
        "PRIVATE",
        "TOKEN",
    ]
)

# Regex patterns for hardcoded secrets in source code
SOURCE_SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "OpenAI API key pattern (sk-...)"),
    (re.compile(r'postgres(ql)?://[^\s"\']+'), "PostgreSQL connection string"),
    (re.compile(r'mysql://[^\s"\']+'), "MySQL connection string"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID (AKIA...)"),
    (re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), "Private key block"),
]

BLOCKED_IMPORT_PATTERNS = [
    (re.compile(r"from\s+['\"]openai['\"]"), "OpenAI SDK import is forbidden in the frontend"),
    (re.compile(r"import\s+openai\b"), "OpenAI SDK import is forbidden in the frontend"),
    (
        re.compile(r"require\(\s*['\"]openai['\"]\s*\)"),
        "OpenAI SDK import is forbidden in the frontend",
    ),
    (
        re.compile(r"import\(\s*['\"]openai['\"]\s*\)"),
        "OpenAI SDK import is forbidden in the frontend",
    ),
]

# File extensions to scan
SOURCE_EXTENSIONS = frozenset([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte"])

# Directories to skip
SKIP_DIRS = frozenset(["node_modules", ".git", "dist", "build", ".next", ".cache", "coverage"])


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class Violation:
    """A security violation that blocks the build."""

    check: str
    location: str
    message: str
    value: str = ""


@dataclass
class Warning:
    """A warning that doesn't block the build (unless strict mode)."""

    check: str
    location: str
    message: str


@dataclass
class ScanResult:
    """Results of the security scan."""

    violations: list[Violation] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def add_violation(self, check: str, location: str, message: str, value: str = "") -> None:
        self.violations.append(Violation(check, location, message, value))

    def add_warning(self, check: str, location: str, message: str) -> None:
        self.warnings.append(Warning(check, location, message))


# =============================================================================
# CHECK 1: ENVIRONMENT VARIABLE HYGIENE
# =============================================================================


def check_env_hygiene(result: ScanResult, strict: bool = False) -> None:
    """
    Inspect os.environ for VITE_* keys.

    - Forbidden patterns: If a VITE_ key contains forbidden keywords, fail
    - Whitespace check: If any value has leading/trailing whitespace, warn or fail
    """
    for key, value in os.environ.items():
        if not key.startswith("VITE_"):
            continue

        # Skip explicitly allowed keys
        if key in ALLOWED_VITE_KEYS:
            # Still check for whitespace issues in allowed keys
            _check_whitespace(result, key, value, strict)
            continue

        # Check for forbidden keywords
        key_upper = key.upper()
        for keyword in FORBIDDEN_KEYWORDS:
            if keyword in key_upper:
                result.add_violation(
                    check="env_hygiene",
                    location=f"env:{key}",
                    message=f"VITE_ variable contains forbidden keyword '{keyword}' - this would expose a secret to the browser",
                    value=f"{key}=<redacted>",
                )
                break  # One violation per key is enough

        if isinstance(value, str) and "service_role" in value.lower():
            result.add_violation(
                check="env_hygiene",
                location=f"env:{key}",
                message="VITE_ variable value contains 'service_role' - never expose privileged JWTs to the browser",
                value=f"{key}=<redacted>",
            )

        # Check for whitespace issues
        _check_whitespace(result, key, value, strict)


def _check_whitespace(result: ScanResult, key: str, value: str, strict: bool) -> None:
    """Check for whitespace issues in environment variable values."""
    if not value:
        return

    has_leading = value != value.lstrip()
    has_trailing = value != value.rstrip()
    has_newline = "\n" in value or "\r" in value

    if has_leading or has_trailing or has_newline:
        issues = []
        if has_leading:
            issues.append("leading whitespace")
        if has_trailing:
            issues.append("trailing whitespace")
        if has_newline:
            issues.append("embedded newlines")

        message = f"Hidden whitespace detected: {', '.join(issues)}"

        if strict:
            result.add_violation(
                check="env_whitespace",
                location=f"env:{key}",
                message=message,
                value=f"{key}=<value with whitespace issues>",
            )
        else:
            result.add_warning(check="env_whitespace", location=f"env:{key}", message=message)


# =============================================================================
# CHECK 2: SOURCE CODE SCAN
# =============================================================================


def iter_source_files(src_dir: Path) -> Generator[Path, None, None]:
    """Iterate over all source files in the given directory."""
    if not src_dir.exists():
        return

    for root, dirs, files in os.walk(src_dir):
        # Skip ignored directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in files:
            filepath = Path(root) / filename
            if filepath.suffix in SOURCE_EXTENSIONS:
                yield filepath


def check_source_code(result: ScanResult, src_dir: Path) -> None:
    """
    Walk source directory and grep for hardcoded secret patterns.

    Detects:
    - OpenAI API keys (sk-...)
    - Database connection strings (postgres://, mysql://)
    - AWS credentials (AKIA...)
    - Private key blocks
    """
    files_scanned = 0

    for filepath in iter_source_files(src_dir):
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            files_scanned += 1
        except Exception:
            continue

        lines = content.split("\n")
        for line_num, line in enumerate(lines, start=1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("#"):
                continue

            for pattern, description in SOURCE_SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    # Redact the matched value for safe logging
                    matched_text = match.group(0)
                    redacted = matched_text[:8] + "..." if len(matched_text) > 8 else matched_text

                    result.add_violation(
                        check="source_scan",
                        location=f"{filepath.relative_to(src_dir.parent)}:{line_num}",
                        message=f"Hardcoded secret detected: {description}",
                        value=redacted,
                    )

            for pattern, description in BLOCKED_IMPORT_PATTERNS:
                if pattern.search(line):
                    result.add_violation(
                        check="dependency_audit",
                        location=f"{filepath.relative_to(src_dir.parent)}:{line_num}",
                        message=description,
                    )

    print(f"   Scanned {files_scanned} source files")


# =============================================================================
# ADDITIONAL CHECKS
# =============================================================================


def check_supabase_anon_key(result: ScanResult) -> None:
    """
    If VITE_SUPABASE_ANON_KEY is set, verify it's actually an anon key,
    not a service_role key (which would be a critical security issue).
    """
    anon_key = os.environ.get("VITE_SUPABASE_ANON_KEY", "")
    if not anon_key:
        return

    # Supabase JWTs have format: header.payload.signature
    parts = anon_key.split(".")
    if len(parts) != 3:
        return  # Not a JWT, skip

    try:
        import base64

        # Decode the payload (add padding if needed)
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload = base64.urlsafe_b64decode(payload_b64).decode("utf-8")

        if "service_role" in payload:
            result.add_violation(
                check="supabase_key",
                location="env:VITE_SUPABASE_ANON_KEY",
                message=(
                    "VITE_SUPABASE_ANON_KEY contains a service_role JWT! "
                    "This grants FULL DATABASE ACCESS and must NEVER be exposed to the browser. "
                    "Use the 'anon' key from Supabase Dashboard → Settings → API."
                ),
                value="<service_role JWT detected>",
            )
    except Exception:
        pass  # Decoding failed, not a valid JWT


# =============================================================================
# REPORTING
# =============================================================================


def print_banner() -> None:
    """Print the scanner banner."""
    print()
    print("═" * 75)
    print("  🔒 Dragonfly Vercel Build Security Scanner")
    print("═" * 75)
    print()


def print_results(result: ScanResult) -> None:
    """Print the scan results."""
    print()
    print("═" * 75)

    # Print warnings
    if result.warnings:
        print()
        print(f"⚠️  WARNINGS ({len(result.warnings)}):")
        print()
        for w in result.warnings:
            print(f"   [{w.check}] {w.location}")
            print(f"      {w.message}")
            print()

    # Print violations
    if result.violations:
        print()
        print(f"❌ SECURITY VIOLATIONS ({len(result.violations)}):")
        print()
        for v in result.violations:
            print(f"   [{v.check}] {v.location}")
            print(f"      {v.message}")
            if v.value:
                print(f"      Value: {v.value}")
            print()

        print("═" * 75)
        print()
        print("❌ BUILD BLOCKED: Fix the security violations above before deploying.")
        print()
        print("   Common fixes:")
        print("   • Remove forbidden VITE_* variables from Vercel environment")
        print("   • Move secrets to backend-only (Railway) environment")
        print("   • Use Supabase Auth instead of static API keys")
        print()
    else:
        print()
        print("✅ SECURITY SCAN PASSED")
        print()
        print("   No security violations detected. Build may proceed.")
        print()


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    """Run the security scanner."""
    parser = argparse.ArgumentParser(
        description="Dragonfly Vercel Build Security Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as errors (fail on whitespace issues)"
    )
    parser.add_argument(
        "--src-dir",
        type=Path,
        default=None,
        help="Source directory to scan (default: auto-detect frontend/src or src)",
    )
    args = parser.parse_args()

    print_banner()

    result = ScanResult()

    # Determine source directory
    src_dir = args.src_dir
    if src_dir is None:
        # Auto-detect common frontend source directories
        candidates = [
            Path("dragonfly-dashboard/src"),
            Path("frontend/src"),
            Path("src"),
        ]
        for candidate in candidates:
            if candidate.exists():
                src_dir = candidate
                break

    # Check 1: Environment Variable Hygiene
    print("🔍 Check 1: Environment Variable Hygiene")
    check_env_hygiene(result, strict=args.strict)
    vite_count = sum(1 for k in os.environ if k.startswith("VITE_"))
    print(f"   Found {vite_count} VITE_* environment variables")

    # Check 2: Source Code Scan & Dependency Audit
    print()
    print("🔍 Check 2: Source Code Scan & Dependency Audit")
    if src_dir and src_dir.exists():
        print(f"   Scanning: {src_dir}")
        check_source_code(result, src_dir)
    else:
        print("   ⚠️  No source directory found (tried dragonfly-dashboard/src, frontend/src, src)")

    # Check 3: Supabase Anon Key Validation
    print()
    print("🔍 Check 3: Supabase Key Validation")
    check_supabase_anon_key(result)
    if "VITE_SUPABASE_ANON_KEY" in os.environ:
        has_violation = any(v.check == "supabase_key" for v in result.violations)
        if has_violation:
            print("   ❌ Detected service_role payload in VITE_SUPABASE_ANON_KEY")
        else:
            print("   Verified: VITE_SUPABASE_ANON_KEY is not a service_role key")
    else:
        print("   Skipped: VITE_SUPABASE_ANON_KEY not set")

    # Print results
    print_results(result)

    # In strict mode, warnings become errors
    if args.strict and result.warnings:
        print("   [strict mode] Treating warnings as errors")
        return 1

    return 0 if result.passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nScan interrupted.")
        sys.exit(2)
    except Exception as e:
        print(f"\n\n❌ Scanner error: {e}")
        sys.exit(2)
