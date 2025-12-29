#!/usr/bin/env python
"""Quick database connection test, bypassing settings cache."""

import psycopg

# Direct connection string - dev project
DB_URL = "postgresql://postgres.ejiddanxtqcleyswqvkc:Norwaykmt99!!@aws-1-us-east-2.pooler.supabase.com:6543/postgres"

if __name__ == "__main__":
    print("Testing direct connection to dev Supabase...")
    print("Host: aws-1-us-east-2.pooler.supabase.com:6543")
    print("Project: ejiddanxtqcleyswqvkc")
    try:
        conn = psycopg.connect(DB_URL)
        print("✓ Connected successfully!")
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user, version()")
            row = cur.fetchone()
            print(f"  Database: {row[0]}")
            print(f"  User: {row[1]}")
            print(f"  Version: {row[2][:50]}...")
        conn.close()
    except Exception as e:
        print(f"✗ Connection failed: {e}")
