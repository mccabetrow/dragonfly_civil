# tools/generate_db_urls.py
"""Generate correct Supabase connection strings."""

import getpass
from urllib.parse import quote_plus


def generate():
    print("\n🔗 Supabase Connection String Generator")
    print("=======================================")

    project_ref = input("Enter Project Reference (e.g. iakets...): ").strip()
    if not project_ref:
        print("❌ Project reference is required.")
        return

    password = getpass.getpass("Enter Database Password: ").strip()
    if not password:
        print("❌ Password is required.")
        return

    region = input("Enter Region (default: aws-0-us-east-1): ").strip()
    if not region:
        region = "aws-0-us-east-1"

    # URL-encode the password to handle special characters like ! @ #
    encoded_password = quote_plus(password)

    print("\n✅ Copy these lines into your .env.prod (or .env.dev):")
    print("-" * 60)

    # 1. Runtime / App (Pooler) -> Port 6543
    # User: postgres.<project_ref>
    pooler_url = f"postgresql://postgres.{project_ref}:{encoded_password}@{region}.pooler.supabase.com:6543/postgres"
    print(f"SUPABASE_DB_URL={pooler_url}")

    # 2. Migrations / Admin (Direct) -> Port 5432
    # User: postgres
    direct_url = (
        f"postgresql://postgres:{encoded_password}@db.{project_ref}.supabase.co:5432/postgres"
    )
    print(f"SUPABASE_MIGRATE_DB_URL={direct_url}")

    print("-" * 60)
    print("ℹ️  SUPABASE_DB_URL is for the App (Transaction Pooler).")
    print("ℹ️  SUPABASE_MIGRATE_DB_URL is for Admin/Migrations (Direct).")


if __name__ == "__main__":
    generate()
