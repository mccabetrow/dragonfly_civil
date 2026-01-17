#!/usr/bin/env python3
"""
generate_prod_dsn.py - Generate properly URL-encoded DSN for dragonfly_app role.

This tool eliminates "Fat Finger" errors when configuring Railway or other
deployment environments. It ensures:
  1. Password is properly URL-encoded (handles special chars like @, /, %, etc.)
  2. Uses the correct Supabase Transaction Pooler port (6543)
  3. Requires SSL for security
  4. Outputs ready-to-paste DSN and verification command

Usage:
    python -m tools.generate_prod_dsn

Example Output:
    ─────────────────────────────────────────────────────────────────────
    DSN (copy to Railway DATABASE_URL):
    postgresql://dragonfly_app:P%40ssw0rd%21@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require

    Verification command (test connectivity):
    psql "postgresql://dragonfly_app:P%40ssw0rd%21@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
    ─────────────────────────────────────────────────────────────────────

Author: Principal Database Reliability Engineer
Date: 2026-01-14
"""

from __future__ import annotations

import getpass
import re
import sys
from urllib.parse import quote_plus


def get_pooler_host(project_ref_or_host: str) -> str:
    """
    Convert project ref or hostname to the Transaction Pooler hostname.

    Accepts:
      - Project ref: "ejiddanxtqcleyswqvkc"
      - Full pooler host: "aws-0-us-east-1.pooler.supabase.com"
      - Full DB host: "db.ejiddanxtqcleyswqvkc.supabase.co"

    Returns the Transaction Pooler hostname.
    """
    value = project_ref_or_host.strip()

    # Already a pooler hostname
    if ".pooler.supabase.com" in value:
        return value

    # Direct DB hostname - extract project ref
    if value.startswith("db.") and ".supabase.co" in value:
        # Extract project ref from db.{project_ref}.supabase.co
        match = re.match(r"db\.([a-z0-9]+)\.supabase\.co", value)
        if match:
            project_ref = match.group(1)
            # Default to us-east-1 pooler (most common)
            # User should verify this matches their project region
            return "aws-0-us-east-1.pooler.supabase.com"

    # Assume it's a project ref - user needs to provide full pooler host
    # Since Supabase pooler hostnames are region-specific, we can't auto-generate
    if re.match(r"^[a-z0-9]+$", value) and len(value) == 20:
        print()
        print("⚠️  Project ref detected, but pooler hostnames are region-specific.")
        print("   Please enter the full Transaction Pooler hostname from Supabase Dashboard:")
        print("   (Settings > Database > Connection string > Transaction pooler)")
        print()
        pooler_host = input("   Pooler hostname: ").strip()
        if pooler_host:
            return pooler_host

    # Return as-is and let validation catch issues
    return value


def validate_pooler_host(host: str) -> tuple[bool, str]:
    """Validate that the host looks like a valid Supabase pooler host."""
    if not host:
        return False, "Host cannot be empty"

    if ".pooler.supabase.com" in host:
        return True, ""

    # Also accept db.*.supabase.co for direct connections (though not recommended)
    if ".supabase.co" in host:
        return (
            True,
            "⚠️  Using direct connection (not pooler). Consider using Transaction Pooler for production.",
        )

    return False, f"Host '{host}' doesn't look like a Supabase host"


def generate_dsn(
    host: str,
    password: str,
    user: str = "dragonfly_app",
    port: int = 6543,
    database: str = "postgres",
    sslmode: str = "require",
) -> str:
    """
    Generate a properly URL-encoded PostgreSQL DSN.

    The password is URL-encoded to handle special characters safely.
    """
    encoded_password = quote_plus(password)

    return f"postgresql://{user}:{encoded_password}@{host}:{port}/{database}?sslmode={sslmode}"


def mask_password_in_dsn(dsn: str) -> str:
    """Mask the password in a DSN for safe logging."""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", dsn)


def main() -> int:
    """Interactive DSN generator."""
    print()
    print("=" * 70)
    print("  DRAGONFLY PROD DSN GENERATOR")
    print("  Generates properly URL-encoded DATABASE_URL for Railway")
    print("=" * 70)
    print()

    # Step 1: Get the pooler hostname
    print("Step 1: Enter Supabase Transaction Pooler hostname")
    print("        (Find in: Supabase Dashboard > Settings > Database > Connection string)")
    print("        Example: aws-0-us-east-1.pooler.supabase.com")
    print()

    host_input = input("Pooler hostname (or project ref): ").strip()
    if not host_input:
        print("❌ Error: Hostname is required")
        return 1

    host = get_pooler_host(host_input)

    is_valid, warning = validate_pooler_host(host)
    if not is_valid:
        print(f"❌ Error: {warning}")
        return 1
    if warning:
        print(f"   {warning}")

    print(f"   ✓ Using host: {host}")
    print()

    # Step 2: Get the password (hidden input)
    print("Step 2: Enter the dragonfly_app password")
    print("        (Input is hidden for security)")
    print()

    password = getpass.getpass("Password: ")
    if not password:
        print("❌ Error: Password is required")
        return 1

    # Confirm password
    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        print("❌ Error: Passwords do not match")
        return 1

    print("   ✓ Password captured")
    print()

    # Step 3: Confirm user (default: dragonfly_app)
    print("Step 3: Confirm database user")
    user_input = input("User [dragonfly_app]: ").strip()
    user = user_input if user_input else "dragonfly_app"
    print(f"   ✓ Using user: {user}")
    print()

    # Generate the DSN
    dsn = generate_dsn(host=host, password=password, user=user)

    # Check if password needed encoding
    encoded_password = quote_plus(password)
    password_was_encoded = encoded_password != password

    # Output results
    print()
    print("=" * 70)
    print("  GENERATED DSN")
    print("=" * 70)
    print()

    if password_was_encoded:
        print("⚠️  Password contained special characters and was URL-encoded.")
        print("   Original chars that were encoded:", end=" ")
        # Show which characters were encoded
        encoded_chars = []
        for char in password:
            if quote_plus(char) != char:
                encoded_chars.append(f"'{char}' → '{quote_plus(char)}'")
        print(", ".join(encoded_chars[:5]))  # Show first 5 to avoid leaking too much
        if len(encoded_chars) > 5:
            print(f"   ... and {len(encoded_chars) - 5} more")
        print()

    print("📋 DSN (copy to Railway DATABASE_URL):")
    print()
    print(f"   {dsn}")
    print()

    print("─" * 70)
    print()

    print("🔍 Verification command (test connectivity):")
    print()
    print(f'   psql "{dsn}"')
    print()

    print("─" * 70)
    print()

    print("📝 Python verification snippet:")
    print()
    print("   import psycopg")
    print(f'   conn = psycopg.connect("{mask_password_in_dsn(dsn)}")')
    print("   print(conn.execute('SELECT current_user, current_database()').fetchone())")
    print()

    print("=" * 70)
    print()

    # Offer to copy to clipboard (Windows)
    if sys.platform == "win32":
        try:
            import subprocess

            copy_choice = input("Copy DSN to clipboard? [y/N]: ").strip().lower()
            if copy_choice == "y":
                process = subprocess.Popen(
                    ["clip"],
                    stdin=subprocess.PIPE,
                    shell=True,
                )
                process.communicate(dsn.encode("utf-8"))
                print("✓ DSN copied to clipboard!")
        except Exception:
            pass  # Clipboard copy failed, no big deal

    print()
    print("✅ Done! Use the DSN above for your Railway DATABASE_URL.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
