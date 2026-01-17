#!/usr/bin/env python3
"""Quick demo of DSN generation with URL encoding."""

import sys

sys.path.insert(0, ".")

from urllib.parse import quote_plus

from tools.generate_prod_dsn import generate_dsn

# Your actual pooler host (from Supabase Dashboard > Settings > Database)
host = "aws-0-us-east-1.pooler.supabase.com"

# Example password with special characters
example_pwd = "billiondollarsystem!!"

print()
print("=" * 60)
print("  DSN GENERATOR DEMO")
print("=" * 60)
print()

print("STEP 1: Password Analysis")
print(f"  Raw password: {example_pwd}")
print(f"  URL-encoded:  {quote_plus(example_pwd)}")
print()

# Note: !! encodes to %21%21
print("  URL Encoding Examples:")
print("    !  → %21")
print("    @  → %40")
print("    #  → %23")
print("    $  → %24")
print("    %  → %25")
print()

# Generate the full DSN
dsn = generate_dsn(host, example_pwd)

print("=" * 60)
print("STEP 2: Generated DSN (copy to Railway DATABASE_URL)")
print("=" * 60)
print()
print(f"  {dsn}")
print()

print("=" * 60)
print("STEP 3: Verification Command (test locally first!)")
print("=" * 60)
print()
print(f'  psql "{dsn}"')
print()

print("=" * 60)
print("NEXT STEPS:")
print("=" * 60)
print()
print("  1. Copy the psql command above")
print("  2. Run it in your terminal to verify connectivity")
print("  3. If it connects: paste the DSN into Railway")
print("  4. If it fails: check credentials/network before touching prod")
print()
