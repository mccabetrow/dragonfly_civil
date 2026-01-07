#!/usr/bin/env python3
"""
tools/check_supabase_linked.py - Pre-commit hook for Supabase --linked flag

Prevents use of --linked with Supabase CLI, which causes pooler DNS issues
on Windows. Use --db-url with SUPABASE_DB_URL_DEV/PROD instead.
"""

import re
import sys


def main() -> int:
    """Check files for --linked flag usage."""
    pattern = re.compile(r"supabase\s+(db|migration|link).*--linked")

    for filepath in sys.argv[1:]:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Skip comment lines
            lines = [
                line
                for line in content.split("\n")
                if not line.strip().startswith(("#", "//", "REM"))
            ]

            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    print(f"\n❌ ERROR in {filepath}:{i}")
                    print(f"   Found: {line.strip()[:80]}")
                    print("\n   Use --db-url with SUPABASE_DB_URL_DEV/PROD instead of --linked.")
                    print("   The --linked flag causes pooler DNS issues on Windows.")
                    return 1

        except Exception:
            pass  # Skip files that can't be read

    return 0


if __name__ == "__main__":
    sys.exit(main())
