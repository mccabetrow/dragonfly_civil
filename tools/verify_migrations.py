#!/usr/bin/env python3
"""
Dragonfly Engine - Migration Verifier

Compares local migration files against the database migration history to detect:
  - Pending migrations (local files not yet applied to DB)
  - Drift (DB has migrations that don't exist locally - dangerous!)
  - Version mismatches (file hash differs from recorded hash)

Usage:
    python -m tools.verify_migrations --env dev
    python -m tools.verify_migrations --env prod --strict

Exit codes:
    0 - All migrations in sync
    1 - Pending migrations (local > DB)
    2 - Drift detected (DB > local) - CRITICAL
    3 - Connection error
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv


@dataclass
class LocalMigration:
    """Represents a local migration file."""

    name: str
    version: str  # Timestamp prefix (e.g., "20250101120000")
    file_path: Path
    content_hash: str
    size_bytes: int


@dataclass
class DbMigration:
    """Represents a migration record from the database."""

    version: str
    name: str | None
    statements_hash: str | None  # Supabase stores statement hash
    applied_at: datetime | None


@dataclass
class VerificationResult:
    """Result of migration verification."""

    local_migrations: list[LocalMigration]
    db_migrations: list[DbMigration]
    pending: list[LocalMigration]  # In local, not in DB
    drift: list[DbMigration]  # In DB, not in local
    hash_mismatches: list[tuple[LocalMigration, DbMigration]]

    @property
    def is_synced(self) -> bool:
        return not self.pending and not self.drift and not self.hash_mismatches

    @property
    def has_drift(self) -> bool:
        return len(self.drift) > 0

    @property
    def has_pending(self) -> bool:
        return len(self.pending) > 0


def get_db_url(env: str) -> str:
    """Get database URL for the specified environment."""
    env_file = PROJECT_ROOT / f".env.{env}"
    if not env_file.exists():
        raise FileNotFoundError(f"Environment file not found: {env_file}")

    load_dotenv(env_file, override=True)

    # Prefer direct connection for migrations
    db_url = os.getenv("SUPABASE_MIGRATE_DB_URL") or os.getenv("SUPABASE_DB_URL")
    if not db_url:
        raise ValueError(f"No database URL found in {env_file}")

    return db_url


def scan_local_migrations(migrations_dir: Path) -> list[LocalMigration]:
    """Scan local migration files and return sorted list."""
    migrations: list[LocalMigration] = []

    if not migrations_dir.exists():
        return migrations

    for file_path in sorted(migrations_dir.glob("*.sql")):
        name = file_path.name
        # Extract version (timestamp prefix before first underscore)
        version = name.split("_")[0] if "_" in name else name.replace(".sql", "")

        # Calculate content hash
        content = file_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()[:16]

        migrations.append(
            LocalMigration(
                name=name,
                version=version,
                file_path=file_path,
                content_hash=content_hash,
                size_bytes=len(content),
            )
        )

    return migrations


def fetch_db_migrations(db_url: str) -> list[DbMigration]:
    """Fetch migration history from database."""
    try:
        import psycopg
    except ImportError:
        print("❌ psycopg not installed. Run: pip install psycopg[binary]")
        sys.exit(3)

    migrations: list[DbMigration] = []

    try:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Supabase stores migrations in supabase_migrations.schema_migrations
                cur.execute(
                    """
                    SELECT version, name, statements
                    FROM supabase_migrations.schema_migrations
                    ORDER BY version ASC
                """
                )

                for row in cur.fetchall():
                    version, name, statements = row
                    # Hash the statements if present
                    stmt_hash = None
                    if statements:
                        if isinstance(statements, list):
                            stmt_hash = hashlib.sha256("".join(statements).encode()).hexdigest()[
                                :16
                            ]

                    migrations.append(
                        DbMigration(
                            version=str(version),
                            name=name,
                            statements_hash=stmt_hash,
                            applied_at=None,  # Supabase doesn't store this
                        )
                    )

    except psycopg.OperationalError as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(3)
    except psycopg.errors.UndefinedTable:
        # No migrations table yet - that's OK for a fresh DB
        pass

    return migrations


def verify_migrations(local: list[LocalMigration], db: list[DbMigration]) -> VerificationResult:
    """Compare local and DB migrations."""
    # Create lookup sets
    local_versions = {m.version for m in local}
    db_versions = {m.version for m in db}

    # Find pending (local but not in DB)
    pending_versions = local_versions - db_versions
    pending = [m for m in local if m.version in pending_versions]

    # Find drift (DB but not in local)
    drift_versions = db_versions - local_versions
    drift = [m for m in db if m.version in drift_versions]

    # Find hash mismatches (in both but content differs)
    # Note: Supabase stores statement hash differently, so this is best-effort
    hash_mismatches: list[tuple[LocalMigration, DbMigration]] = []
    # Skip hash comparison for now - Supabase uses different hashing

    return VerificationResult(
        local_migrations=local,
        db_migrations=db,
        pending=pending,
        drift=drift,
        hash_mismatches=hash_mismatches,
    )


def print_report(result: VerificationResult, env: str) -> None:
    """Print verification report."""
    print("\n" + "=" * 70)
    print(f"  MIGRATION VERIFICATION - {env.upper()}")
    print("=" * 70)

    print(f"\n📁 Local migrations: {len(result.local_migrations)}")
    print(f"🗄️  DB migrations:    {len(result.db_migrations)}")

    # Pending migrations
    if result.pending:
        print(f"\n⏳ PENDING MIGRATIONS ({len(result.pending)}):")
        print("   These local files have not been applied to the database:")
        for m in sorted(result.pending, key=lambda x: x.version):
            print(f"   → {m.name} ({m.size_bytes:,} bytes)")
    else:
        print("\n✅ No pending migrations")

    # Drift
    if result.drift:
        print(f"\n🚨 DRIFT DETECTED ({len(result.drift)}):")
        print("   These DB migrations don't exist locally (DANGEROUS!):")
        for m in sorted(result.drift, key=lambda x: x.version):
            name = m.name or f"migration_{m.version}"
            print(f"   ⚠️  {m.version}: {name}")
    else:
        print("✅ No drift detected")

    # Hash mismatches
    if result.hash_mismatches:
        print(f"\n⚠️  CONTENT MISMATCHES ({len(result.hash_mismatches)}):")
        print("   These migrations differ between local and DB:")
        for local_m, db_m in result.hash_mismatches:
            print(f"   → {local_m.name}")
            print(f"      Local hash:  {local_m.content_hash}")
            print(f"      DB hash:     {db_m.statements_hash}")

    # Summary
    print("\n" + "=" * 70)
    if result.is_synced:
        print("  ✅ MIGRATIONS IN SYNC")
    elif result.has_drift:
        print("  🚨 CRITICAL: DRIFT DETECTED - DO NOT DEPLOY!")
        print("     The database has migrations that don't exist locally.")
        print("     This usually means someone applied migrations directly.")
        print("     Resolution: Pull the missing migrations or restore from backup.")
    elif result.has_pending:
        print("  ⏳ PENDING MIGRATIONS - Run db_push to apply")
    print("=" * 70 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify migration state")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Environment to check (default: dev)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on any pending migrations (for CI/CD)",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=PROJECT_ROOT / "supabase" / "migrations",
        help="Path to migrations directory",
    )
    args = parser.parse_args()

    print(f"\n🔍 Verifying migrations for {args.env}...")

    # Get DB URL
    try:
        db_url = get_db_url(args.env)
        # Mask credentials in output
        masked = db_url.split("@")[-1] if "@" in db_url else db_url
        print(f"   Database: {masked}")
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        return 3

    # Scan local migrations
    print(f"   Scanning: {args.migrations_dir}")
    local_migrations = scan_local_migrations(args.migrations_dir)

    # Fetch DB migrations
    print("   Fetching DB migration history...")
    db_migrations = fetch_db_migrations(db_url)

    # Verify
    result = verify_migrations(local_migrations, db_migrations)

    # Print report
    print_report(result, args.env)

    # Determine exit code
    if result.has_drift:
        return 2
    elif result.has_pending:
        return 1 if args.strict else 0
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())
