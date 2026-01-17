#!/usr/bin/env python3
"""
tools/encode_password.py
========================
URL-encode passwords for safe inclusion in PostgreSQL DSNs.

Special characters in passwords MUST be URL-encoded before embedding in a DSN.
For example:
    billiondollarsystem!!  →  billiondollarsystem%21%21

Usage:
    # From CLI argument (visible in shell history)
    python -m tools.encode_password "mypassword!!"

    # Interactive mode (hidden input, recommended)
    python -m tools.encode_password

Examples:
    $ python -m tools.encode_password
    Enter password (hidden): [user types: billiondollarsystem!!]

    URL-encoded password:
    billiondollarsystem%21%21

Common special characters and their encodings:
    !  →  %21
    @  →  %40
    #  →  %23
    $  →  %24
    %  →  %25
    ^  →  %5E
    &  →  %26
    *  →  %2A
    (  →  %28
    )  →  %29
    =  →  %3D
    +  →  %2B
    [  →  %5B
    ]  →  %5D
    {  →  %7B
    }  →  %7D
    |  →  %7C
    \\  →  %5C
    :  →  %3A
    ;  →  %3B
    "  →  %22
    '  →  %27
    <  →  %3C
    >  →  %3E
    ,  →  %2C
    /  →  %2F
    ?  →  %3F

Author: Principal Database Reliability Engineer
Date: 2026-01-14
"""

from __future__ import annotations

import argparse
import getpass
import sys
from urllib.parse import quote


def encode_password(password: str, safe: str = "") -> str:
    """
    URL-encode a password for DSN use.

    Args:
        password: The raw password string
        safe: Characters that should NOT be encoded (default: none)

    Returns:
        URL-encoded password safe for DSN inclusion
    """
    # quote() with empty safe encodes everything except ASCII letters, digits, and _.-~
    # We use safe="" to be maximally safe for DSN passwords
    return quote(password, safe=safe)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="URL-encode passwords for PostgreSQL DSNs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Interactive mode (recommended - password is hidden)
    python -m tools.encode_password

    # From argument (visible in shell history!)
    python -m tools.encode_password "mypassword!!"

    # Pipe to clipboard (PowerShell)
    python -m tools.encode_password --raw | Set-Clipboard

Why encode?
    Special characters (!@#$%^&*) in DSN passwords will break URL parsing.
    Always encode before inserting into: postgresql://user:PASSWORD@host/db
""",
    )

    parser.add_argument(
        "password",
        nargs="?",
        help="Password to encode (if omitted, prompts interactively)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Output only the encoded password (no formatting)",
    )

    args = parser.parse_args()

    # Get password
    if args.password:
        password = args.password
    else:
        if not args.raw:
            print()
            print("=" * 50)
            print("  PASSWORD URL ENCODER")
            print("=" * 50)
            print()
        password = getpass.getpass("Enter password (hidden): ")

        if not password:
            print("ERROR: No password provided", file=sys.stderr)
            return 1

    # Encode
    encoded = encode_password(password)

    # Output
    if args.raw:
        print(encoded, end="")  # No newline for piping
    else:
        print()
        print("-" * 50)
        print("URL-encoded password:")
        print()
        print(f"  {encoded}")
        print()

        # Show if anything changed
        if encoded != password:
            print(f"  ({len(encoded) - len(password)} characters were encoded)")
        else:
            print("  (no special characters needed encoding)")
        print("-" * 50)
        print()

        # Build example DSN
        print("Example DSN:")
        print(f"  postgresql://postgres:{encoded}@host:6543/postgres?sslmode=require")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
