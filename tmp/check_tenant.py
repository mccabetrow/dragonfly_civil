#!/usr/bin/env python3
"""Quick script to check tenant schema tables."""
import os

import psycopg

db_url = os.environ.get("SUPABASE_MIGRATE_DB_URL") or os.environ.get("SUPABASE_DB_URL")
if not db_url:
    print("No DB URL found in environment")
    exit(1)

conn = psycopg.connect(db_url)
cur = conn.cursor()

# Check tenant schema tables
cur.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'tenant' ORDER BY table_name"
)
tables = [r[0] for r in cur.fetchall()]
print(f"Tables in tenant schema ({len(tables)}):")
for t in tables:
    print(f"  - {t}")

# Check if org_members exists
has_org_members = "org_members" in tables
print(f"\norg_members exists: {has_org_members}")

if not has_org_members:
    # Check what creates org_members
    print("\nSearching for org_members creation in local migrations...")
    import pathlib

    migrations_dir = pathlib.Path(__file__).parent.parent / "supabase" / "migrations"
    for f in sorted(migrations_dir.glob("*.sql")):
        content = f.read_text(encoding="utf-8", errors="ignore")
        if "org_members" in content:
            print(f"  Found in: {f.name}")

conn.close()
