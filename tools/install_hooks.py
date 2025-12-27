#!/usr/bin/env python3
"""
SEV-1 Security: Install Git pre-commit hook to block secrets.

This script installs a native Git hook that:
1. Blocks commits containing .env* files
2. Scans staged content for postgres:// URLs and API keys
3. Exits with code 1 to prevent the commit

Usage:
    python tools/install_hooks.py

The hook is installed to .git/hooks/pre-commit and runs automatically
before every commit.
"""

import os
import stat
import sys
from pathlib import Path

# Find repo root (where .git is)
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
GIT_HOOKS_DIR = REPO_ROOT / ".git" / "hooks"
PRE_COMMIT_PATH = GIT_HOOKS_DIR / "pre-commit"

# =============================================================================
# PRE-COMMIT HOOK CONTENT
# =============================================================================
PRE_COMMIT_HOOK = r"""#!/bin/bash
# ============================================================================
# DRAGONFLY CIVIL - PRE-COMMIT SECURITY HOOK
# ============================================================================
# Installed by: python tools/install_hooks.py
# Purpose: Block commits containing secrets (SEV-1 prevention)
# ============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo -e "${YELLOW}🔒 Running security pre-commit checks...${NC}"

# Track if we should block
BLOCK_COMMIT=0

# ============================================================================
# CHECK 1: Block .env files
# ============================================================================
ENV_FILES=$(git diff --cached --name-only | grep -E '\.env$|\.env\.|^\.env' || true)

if [ -n "$ENV_FILES" ]; then
    echo ""
    echo -e "${RED}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ⛔ SECURITY BLOCK: .env file detected in commit!                ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${RED}Blocked files:${NC}"
    echo "$ENV_FILES" | while read -r file; do
        echo -e "  ${RED}✗ $file${NC}"
    done
    echo ""
    echo -e "${YELLOW}To fix: git reset HEAD <file> && git rm --cached <file>${NC}"
    BLOCK_COMMIT=1
fi

# ============================================================================
# CHECK 2: Scan content for secrets patterns
# ============================================================================
# Get list of staged files (excluding binary and deleted)
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.(py|js|ts|json|yaml|yml|sh|ps1|sql|md|txt|toml|env)$' || true)

if [ -n "$STAGED_FILES" ]; then
    # Patterns to detect (case insensitive where applicable)
    SECRET_PATTERNS=(
        'postgresql://[^[:space:]]+'
        'postgres://[^[:space:]]+'
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
        'SUPABASE_SERVICE_ROLE_KEY=[^[:space:]]+'
        'SUPABASE_DB_URL=[^[:space:]]+'
        'sk-[A-Za-z0-9]{20,}'
        'sk-ant-[A-Za-z0-9-]+'
        'discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+'
    )
    
    for file in $STAGED_FILES; do
        # Skip if file doesn't exist (deleted)
        [ -f "$file" ] || continue
        
        # Get staged content (not working tree)
        CONTENT=$(git show ":$file" 2>/dev/null || cat "$file")
        
        for pattern in "${SECRET_PATTERNS[@]}"; do
            # Check for pattern, excluding comments and example files
            if echo "$CONTENT" | grep -v '^[[:space:]]*#' | grep -v 'example' | grep -v 'placeholder' | grep -qE "$pattern"; then
                # Extra check: skip if it's in .env.example
                if [[ "$file" == *".example"* ]]; then
                    continue
                fi
                
                echo ""
                echo -e "${RED}╔══════════════════════════════════════════════════════════════════╗${NC}"
                echo -e "${RED}║  ⛔ SECURITY BLOCK: Secret pattern detected in staged file!      ║${NC}"
                echo -e "${RED}╚══════════════════════════════════════════════════════════════════╝${NC}"
                echo ""
                echo -e "${RED}File: $file${NC}"
                echo -e "${RED}Pattern: $pattern${NC}"
                echo ""
                echo -e "${YELLOW}This looks like a credential or API key.${NC}"
                echo -e "${YELLOW}If this is intentional (e.g., in documentation), use:${NC}"
                echo -e "${YELLOW}  git commit --no-verify${NC}"
                echo ""
                BLOCK_COMMIT=1
                break 2  # Exit both loops
            fi
        done
    done
fi

# ============================================================================
# CHECK 3: Block private keys
# ============================================================================
KEY_FILES=$(git diff --cached --name-only | grep -E '\.(pem|key)$|_rsa$|_dsa$|_ed25519$|_ecdsa$' || true)

if [ -n "$KEY_FILES" ]; then
    echo ""
    echo -e "${RED}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ⛔ SECURITY BLOCK: Private key file detected in commit!         ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${RED}Blocked files:${NC}"
    echo "$KEY_FILES" | while read -r file; do
        echo -e "  ${RED}✗ $file${NC}"
    done
    BLOCK_COMMIT=1
fi

# ============================================================================
# RESULT
# ============================================================================
if [ $BLOCK_COMMIT -eq 1 ]; then
    echo ""
    echo -e "${RED}Commit blocked. Fix the issues above and try again.${NC}"
    echo -e "${YELLOW}If you MUST bypass (danger!): git commit --no-verify${NC}"
    echo ""
    exit 1
fi

echo -e "${GREEN}✅ Security checks passed${NC}"
exit 0
"""


def main() -> int:
    """Install the pre-commit hook."""
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  DRAGONFLY CIVIL - Installing Security Pre-Commit Hook           ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # Check we're in a git repo
    if not (REPO_ROOT / ".git").is_dir():
        print("❌ ERROR: Not a git repository (no .git directory found)")
        print(f"   Looked in: {REPO_ROOT}")
        return 1

    # Create hooks directory if needed
    GIT_HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    # Check for existing hook
    if PRE_COMMIT_PATH.exists():
        print(f"⚠️  Existing pre-commit hook found at: {PRE_COMMIT_PATH}")

        # Check if it's our hook
        existing_content = PRE_COMMIT_PATH.read_text(encoding="utf-8", errors="replace")
        if "DRAGONFLY CIVIL - PRE-COMMIT SECURITY HOOK" in existing_content:
            print("   This is our security hook. Updating...")
        else:
            print("   This is a different hook. Backing up...")
            backup_path = PRE_COMMIT_PATH.with_suffix(".backup")
            PRE_COMMIT_PATH.rename(backup_path)
            print(f"   Backed up to: {backup_path}")

    # Write the hook
    print(f"📝 Installing hook to: {PRE_COMMIT_PATH}")
    PRE_COMMIT_PATH.write_text(PRE_COMMIT_HOOK, encoding="utf-8")

    # Make executable (Unix)
    if os.name != "nt":
        current_mode = PRE_COMMIT_PATH.stat().st_mode
        PRE_COMMIT_PATH.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print("   Made executable (chmod +x)")

    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  ✅ SECURITY HOOKS INSTALLED                                     ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()
    print("Git will now REJECT commits that contain:")
    print("  • .env files (any variation)")
    print("  • PostgreSQL connection strings (postgres://)")
    print("  • Supabase service role keys (eyJ...)")
    print("  • OpenAI/Anthropic API keys (sk-...)")
    print("  • Discord webhook URLs")
    print("  • Private key files (.pem, .key, _rsa, etc.)")
    print()
    print("To bypass in emergencies: git commit --no-verify")
    print("  (But seriously, don't do that)")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
