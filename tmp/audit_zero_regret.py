"""Audit current grants to anon/authenticated for Zero Regret planning."""

import os

import psycopg
from psycopg.rows import dict_row

dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL")
if not dsn:
    print("❌ SUPABASE_MIGRATE_DB_URL not set")
    exit(1)

conn = psycopg.connect(dsn, row_factory=dict_row)

# 1. Table/View grants to anon/authenticated
print("=" * 70)
print("TABLE/VIEW GRANTS to anon/authenticated")
print("=" * 70)
result = conn.execute(
    """
    SELECT 
        table_schema,
        table_name,
        grantee,
        privilege_type
    FROM information_schema.role_table_grants
    WHERE grantee IN ('anon', 'authenticated')
    AND table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name, grantee
"""
)
for row in result:
    print(
        f"  {row['grantee']:15} | {row['table_schema']}.{row['table_name']:40} | {row['privilege_type']}"
    )

# 2. Function/RPC grants to anon/authenticated
print("\n" + "=" * 70)
print("FUNCTION/RPC GRANTS to anon/authenticated")
print("=" * 70)
result = conn.execute(
    """
    SELECT 
        routine_schema,
        routine_name,
        grantee,
        privilege_type
    FROM information_schema.role_routine_grants
    WHERE grantee IN ('anon', 'authenticated')
    AND routine_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY routine_schema, routine_name, grantee
"""
)
for row in result:
    print(
        f"  {row['grantee']:15} | {row['routine_schema']}.{row['routine_name']:40} | {row['privilege_type']}"
    )

# 3. Check for toxic columns in views
print("\n" + "=" * 70)
print("TOXIC COLUMN SCAN (ssn, password, secret, token, dob, address)")
print("=" * 70)
result = conn.execute(
    """
    SELECT 
        c.table_schema,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    JOIN information_schema.role_table_grants g 
        ON c.table_schema = g.table_schema AND c.table_name = g.table_name
    WHERE g.grantee IN ('anon', 'authenticated')
    AND g.table_schema NOT IN ('pg_catalog', 'information_schema')
    AND (
        c.column_name ILIKE '%ssn%'
        OR c.column_name ILIKE '%password%'
        OR c.column_name ILIKE '%secret%'
        OR c.column_name ILIKE '%token%'
        OR c.column_name ILIKE '%dob%'
        OR c.column_name ILIKE '%address%'
    )
    ORDER BY c.table_schema, c.table_name
"""
)
toxic_found = False
for row in result:
    toxic_found = True
    print(f"  ⚠️ {row['table_schema']}.{row['table_name']}.{row['column_name']}")

if not toxic_found:
    print("  ✅ No toxic columns found in accessible objects")

conn.close()
