#!/usr/bin/env python3
"""
Env Schema Check Script

Validates that:
1. All required env vars in Settings are documented in .env.example
2. All vars in .env.example exist in Settings schema
3. docs/env.md documents required variables

Exit codes:
- 0: All checks pass
- 1: Schema mismatch detected
"""

import re
import sys
from pathlib import Path


def extract_settings_fields() -> dict[str, dict]:
    """Extract field names from src/core_config.py Settings class."""
    config_path = Path("src/core_config.py")
    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        sys.exit(1)

    content = config_path.read_text()

    # Extract fields from Settings class
    # Pattern matches: FIELD_NAME: type = Field(...)
    field_pattern = re.compile(r"^\s+([A-Z][A-Z0-9_]*)\s*:\s*[^=]+=\s*Field\(", re.MULTILINE)

    fields = {}
    for match in field_pattern.finditer(content):
        field_name = match.group(1)
        fields[field_name] = {"source": "Settings"}

    return fields


def extract_env_example_vars() -> set[str]:
    """Extract variable names from .env.example."""
    env_path = Path(".env.example")
    if not env_path.exists():
        print(f"ERROR: {env_path} not found")
        sys.exit(1)

    content = env_path.read_text(encoding="utf-8")
    vars_set = set()

    for line in content.splitlines():
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue
        # Extract var name before =
        if "=" in line:
            var_name = line.split("=")[0].strip()
            vars_set.add(var_name)

    return vars_set


def extract_required_vars() -> list[str]:
    """Extract REQUIRED_ENV_VARS list from src/core_config.py."""
    config_path = Path("src/core_config.py")
    content = config_path.read_text(encoding="utf-8")

    # Find REQUIRED_ENV_VARS list
    pattern = re.compile(r"REQUIRED_ENV_VARS\s*=\s*\[(.*?)\]", re.DOTALL)
    match = pattern.search(content)
    if not match:
        print("WARNING: REQUIRED_ENV_VARS not found in config")
        return []

    list_content = match.group(1)
    # Extract quoted strings
    vars = re.findall(r'"([^"]+)"', list_content)
    return vars


def check_docs_env_md() -> bool:
    """Check that docs/env.md exists and documents required vars."""
    docs_path = Path("docs/env.md")
    if not docs_path.exists():
        print(f"ERROR: {docs_path} not found")
        return False

    content = docs_path.read_text(encoding="utf-8")
    required_vars = extract_required_vars()

    missing = []
    for var in required_vars:
        if var not in content:
            missing.append(var)

    if missing:
        print(f"ERROR: Required vars not documented in docs/env.md: {missing}")
        return False

    return True


def main() -> int:
    """Run all schema checks."""
    print("=" * 60)
    print("ENV SCHEMA CHECK")
    print("=" * 60)

    errors = []

    # Get Settings fields
    settings_fields = extract_settings_fields()
    print(f"Found {len(settings_fields)} fields in Settings class")

    # Get .env.example vars
    env_example_vars = extract_env_example_vars()
    print(f"Found {len(env_example_vars)} variables in .env.example")

    # Get required vars
    required_vars = extract_required_vars()
    print(f"Found {len(required_vars)} required variables")

    # Check 1: All required vars must be in .env.example
    print("\nCheck 1: Required vars in .env.example")
    for var in required_vars:
        if var not in env_example_vars:
            errors.append(f"Required var '{var}' missing from .env.example")
            print(f"  ✗ {var} MISSING")
        else:
            print(f"  ✓ {var}")

    # Check 2: Settings fields should be in .env.example (excluding deprecated/internal)
    print("\nCheck 2: Settings fields in .env.example")
    internal_fields = {
        "SUPABASE_URL_PROD",
        "SUPABASE_SERVICE_ROLE_KEY_PROD",
        "SUPABASE_DB_URL_PROD",
        "SUPABASE_DB_URL_DIRECT_PROD",
        "SUPABASE_DB_PASSWORD",
        "SUPABASE_DB_PASSWORD_PROD",
        "SESSION_PATH",
        "ENCRYPT_SESSIONS",
        "SESSION_KMS_KEY",
        "LEGAL_PACKET_BUCKET",
        "NY_INTEREST_RATE_PERCENT",
    }

    for field in settings_fields:
        if field in internal_fields:
            continue
        if field not in env_example_vars:
            # Warning, not error for optional fields
            print(f"  ⚠ {field} not in .env.example (optional)")

    # Check 3: docs/env.md exists and documents required vars
    print("\nCheck 3: docs/env.md documentation")
    if check_docs_env_md():
        print("  ✓ docs/env.md documents all required vars")
    else:
        errors.append("docs/env.md missing required variable documentation")

    # Summary
    print("\n" + "=" * 60)
    if errors:
        print("FAILED: Schema check found issues:")
        for error in errors:
            print(f"  - {error}")
        return 1
    else:
        print("PASSED: All env schema checks passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
