#!/usr/bin/env python3
"""
REST-based migration status checker for Dragonfly Civil.

Queries the v_migration_status view via Supabase REST API, compares against
local migration files, and reports applied vs pending migrations.

Usage:
    $env:SUPABASE_MODE = 'dev'
    python -m tools.migration_status

    # Or with explicit environment
    python -m tools.migration_status --env prod

This replaces `supabase migration list --linked` which doesn't work reliably
on Windows due to pooler DNS issues.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
VIEW_ENDPOINT = "/rest/v1/v_migration_status"


@dataclass
class MigrationRecord:
    """A single migration row from the database."""

    source: str
    version: str
    name: str
    executed_at: datetime | None
    success: bool


@dataclass
class LocalFile:
    """A local migration file."""

    filename: str
    version: str
    full_path: Path


# ---------------------------------------------------------------------------
# Environment & Credentials
# ---------------------------------------------------------------------------


def get_env() -> Literal["dev", "prod"]:
    """Determine target environment from SUPABASE_MODE or default to dev."""
    mode = os.getenv("SUPABASE_MODE", "dev").strip().lower()
    if mode in ("prod", "production"):
        return "prod"
    return "dev"


def get_credentials(env: Literal["dev", "prod"]) -> tuple[str, str]:
    """
    Get Supabase URL and service role key for the given environment.

    Supports both direct env vars and settings-based loading.
    """
    if env == "prod":
        url = os.getenv("SUPABASE_URL_PROD", "").strip()
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY_PROD", "").strip()
    else:
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not key:
        # Try loading from settings
        try:
            from src.supabase_client import get_supabase_credentials

            url, key = get_supabase_credentials(env)
        except Exception:
            pass

    if not url:
        print(
            f"❌ SUPABASE_URL{'_PROD' if env == 'prod' else ''} not set",
            file=sys.stderr,
        )
        sys.exit(1)
    if not key:
        print(
            f"❌ SUPABASE_SERVICE_ROLE_KEY{'_PROD' if env == 'prod' else ''} not set",
            file=sys.stderr,
        )
        sys.exit(1)

    return url, key


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------


def fetch_migration_status(
    url: str, key: str, limit: int = 200
) -> list[MigrationRecord]:
    """
    Fetch migration status from the v_migration_status view via REST.

    Returns empty list if view doesn't exist (migration not yet applied).
    """
    endpoint = f"{url.rstrip('/')}{VIEW_ENDPOINT}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    params = {
        "order": "executed_at.desc",
        "limit": str(limit),
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(endpoint, headers=headers, params=params)

            if resp.status_code == 404:
                # View doesn't exist yet
                return []

            if resp.status_code == 400 and "does not exist" in resp.text.lower():
                # View doesn't exist yet (PostgREST returns 400 sometimes)
                return []

            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        print(
            f"❌ REST API error: {e.response.status_code} - {e.response.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"❌ Network error: {e}", file=sys.stderr)
        sys.exit(1)

    records = []
    for row in data:
        executed_at = None
        if row.get("executed_at"):
            try:
                # Parse ISO timestamp
                ts = row["executed_at"]
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                executed_at = datetime.fromisoformat(ts)
            except ValueError:
                pass

        records.append(
            MigrationRecord(
                source=row.get("source", "unknown"),
                version=row.get("version", ""),
                name=row.get("name", ""),
                executed_at=executed_at,
                success=row.get("success", True),
            )
        )

    return records


# ---------------------------------------------------------------------------
# Local Files
# ---------------------------------------------------------------------------


def scan_local_migrations() -> list[LocalFile]:
    """Scan local migration files and extract version info."""
    if not MIGRATIONS_DIR.exists():
        print(f"⚠️  Migrations directory not found: {MIGRATIONS_DIR}", file=sys.stderr)
        return []

    files = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        filename = path.name
        # Extract version prefix (either numeric like "0001" or timestamp like "20251209000000")
        parts = filename.split("_", 1)
        version = parts[0] if parts else filename

        files.append(
            LocalFile(
                filename=filename,
                version=version,
                full_path=path,
            )
        )

    return files


# ---------------------------------------------------------------------------
# Comparison & Reporting
# ---------------------------------------------------------------------------


def compare_migrations(
    applied: list[MigrationRecord],
    local: list[LocalFile],
) -> tuple[list[LocalFile], list[MigrationRecord]]:
    """
    Compare applied migrations to local files.

    Returns:
        - pending: local files not found in applied list
        - failed: applied migrations with success=False
    """
    # Build set of applied migration names
    applied_names = {rec.name for rec in applied}

    # Find pending (local files not in applied)
    pending = [f for f in local if f.filename not in applied_names]

    # Find failed migrations
    failed = [rec for rec in applied if not rec.success]

    return pending, failed


def print_table(
    applied: list[MigrationRecord],
    pending: list[LocalFile],
    failed: list[MigrationRecord],
) -> None:
    """Print a formatted table of migration status."""

    # Group by source
    legacy = [r for r in applied if r.source == "legacy"]
    supabase = [r for r in applied if r.source == "supabase"]

    # Header
    print("\n" + "=" * 80)
    print("MIGRATION STATUS")
    print("=" * 80)

    # Supabase migrations (newer)
    if supabase:
        print("\n📦 Supabase CLI Migrations (schema_migrations)")
        print("-" * 70)
        print(f"{'Version':<20} {'Name':<40} {'Status':<10}")
        print("-" * 70)
        for rec in sorted(supabase, key=lambda r: r.version, reverse=True)[:20]:
            status = "✅ APPLIED" if rec.success else "❌ FAILED"
            # Truncate name for display
            name = rec.name[:38] + ".." if len(rec.name) > 40 else rec.name
            print(f"{rec.version:<20} {name:<40} {status:<10}")
        if len(supabase) > 20:
            print(f"  ... and {len(supabase) - 20} more applied migrations")
    else:
        print("\n📦 Supabase CLI Migrations: None found")

    # Legacy migrations
    if legacy:
        print(f"\n📁 Legacy Migrations (dragonfly_migrations): {len(legacy)} applied")

    # Pending migrations
    if pending:
        print("\n⏳ PENDING MIGRATIONS (not yet applied)")
        print("-" * 70)
        for f in pending[:20]:
            print(f"   🔸 {f.filename}")
        if len(pending) > 20:
            print(f"   ... and {len(pending) - 20} more pending")

    # Failed migrations
    if failed:
        print("\n🚨 FAILED MIGRATIONS")
        print("-" * 70)
        for rec in failed:
            print(f"   ❌ {rec.name}")

    print()


def print_summary(
    applied: list[MigrationRecord],
    pending: list[LocalFile],
    failed: list[MigrationRecord],
) -> None:
    """Print a one-line summary."""
    legacy_count = len([r for r in applied if r.source == "legacy"])
    supabase_count = len([r for r in applied if r.source == "supabase"])

    summary = f"Legacy: {legacy_count} applied. Supabase: {supabase_count} applied, {len(pending)} pending, {len(failed)} failed."

    if pending or failed:
        print(f"⚠️  {summary}")
    else:
        print(f"✅ {summary}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check migration status via REST API (no direct DB connection needed)"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Target environment (default: from SUPABASE_MODE or 'dev')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum rows to fetch from view (default: 200)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted table",
    )
    args = parser.parse_args()

    # Determine environment
    env = args.env or get_env()
    print(f"🔍 Checking migration status for: {env.upper()}")

    # Get credentials
    url, key = get_credentials(env)

    # Fetch applied migrations from REST
    print(f"📡 Fetching from: {url}{VIEW_ENDPOINT}")
    applied = fetch_migration_status(url, key, limit=args.limit)

    if not applied:
        print("\n⚠️  No migrations found in v_migration_status view.")
        print("   The view may not exist yet. Push this migration first:")
        print("   supabase/migrations/20251209000000_migration_status_view.sql")
        print("\n   Or run: git push origin main → let CI apply it")
        return 1

    # Scan local files
    local = scan_local_migrations()
    print(f"📂 Found {len(local)} local migration files in {MIGRATIONS_DIR}")

    # Compare
    pending, failed = compare_migrations(applied, local)

    # Output
    if args.json:
        import json

        output = {
            "applied": [
                {
                    "source": r.source,
                    "version": r.version,
                    "name": r.name,
                    "success": r.success,
                }
                for r in applied
            ],
            "pending": [f.filename for f in pending],
            "failed": [r.name for r in failed],
        }
        print(json.dumps(output, indent=2))
    else:
        print_table(applied, pending, failed)
        print_summary(applied, pending, failed)

    # Exit code
    if failed:
        return 2  # Failed migrations
    if pending:
        return 0  # Pending is normal during development
    return 0


if __name__ == "__main__":
    sys.exit(main())
