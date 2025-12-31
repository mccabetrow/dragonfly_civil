#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════
tools/verify_schema_sync.py - Schema Drift Detection & Verification
═══════════════════════════════════════════════════════════════════════════

Purpose:
    Verify that critical schema elements exist and are properly configured.
    Detects drift between migration history and actual database state.

Checks:
    1. FUNCTIONS: normalize_party_name, compute_judgment_dedupe_key exist
    2. COLUMNS: dedupe_key exists on plaintiffs and judgments tables
    3. INDEXES: Unique indexes on dedupe_key columns are VALID

Usage:
    # Verify dev schema
    SUPABASE_MODE=dev python -m tools.verify_schema_sync

    # Verify prod schema
    SUPABASE_MODE=prod python -m tools.verify_schema_sync --env prod

    # JSON output for CI
    python -m tools.verify_schema_sync --json

Exit Codes:
    0 = All schema elements verified (GREEN)
    1 = One or more missing/invalid elements (RED)

Author: Dragonfly Reliability Engineering
Created: 2025-01-06
═══════════════════════════════════════════════════════════════════════════
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# ═══════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class SchemaCheck:
    """Result of a single schema verification check."""

    name: str
    category: str  # 'function', 'column', 'index'
    exists: bool
    valid: bool
    details: str


@dataclass
class SchemaVerification:
    """Overall schema verification report."""

    environment: str
    all_green: bool
    checks: list[SchemaCheck]
    summary: dict[str, int]


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE CHECKS
# ═══════════════════════════════════════════════════════════════════════════


def check_function_exists(cur, function_name: str, arg_types: str) -> SchemaCheck:
    """Check if a function exists with correct signature."""
    cur.execute(
        """
        SELECT p.proname, pg_get_function_identity_arguments(p.oid) as args
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public'
          AND p.proname = %s
        """,
        (function_name,),
    )
    row = cur.fetchone()

    if not row:
        return SchemaCheck(
            name=f"public.{function_name}({arg_types})",
            category="function",
            exists=False,
            valid=False,
            details="Function not found",
        )

    actual_args = row[1] if row[1] else ""
    # Normalize for comparison
    expected_norm = arg_types.lower().replace(" ", "")
    actual_norm = actual_args.lower().replace(" ", "")

    matches = expected_norm == actual_norm
    return SchemaCheck(
        name=f"public.{function_name}({arg_types})",
        category="function",
        exists=True,
        valid=matches,
        details=(
            f"Found with args: {actual_args}"
            if matches
            else f"Signature mismatch: expected ({arg_types}), got ({actual_args})"
        ),
    )


def check_column_exists(cur, table_name: str, column_name: str) -> SchemaCheck:
    """Check if a column exists on a table."""
    cur.execute(
        """
        SELECT column_name, data_type, is_nullable, generation_expression
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        """,
        (table_name, column_name),
    )
    row = cur.fetchone()

    if not row:
        return SchemaCheck(
            name=f"public.{table_name}.{column_name}",
            category="column",
            exists=False,
            valid=False,
            details="Column not found",
        )

    # Check if it's a generated column
    is_generated = row[3] is not None
    return SchemaCheck(
        name=f"public.{table_name}.{column_name}",
        category="column",
        exists=True,
        valid=True,
        details=f"Type: {row[1]}, Generated: {is_generated}",
    )


def check_index_exists(cur, index_name: str, table_name: str) -> SchemaCheck:
    """Check if an index exists and is valid/unique."""
    cur.execute(
        """
        SELECT
            i.indexrelid::regclass::text AS index_name,
            i.indisvalid AS is_valid,
            i.indisunique AS is_unique,
            pg_get_indexdef(i.indexrelid) AS definition
        FROM pg_index i
        JOIN pg_class c ON i.indexrelid = c.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = 'public'
          AND c.relname = %s
        """,
        (index_name,),
    )
    row = cur.fetchone()

    if not row:
        return SchemaCheck(
            name=f"public.{index_name} ON {table_name}",
            category="index",
            exists=False,
            valid=False,
            details="Index not found",
        )

    is_valid = row[1]
    is_unique = row[2]

    return SchemaCheck(
        name=f"public.{index_name} ON {table_name}",
        category="index",
        exists=True,
        valid=is_valid and is_unique,
        details=f"Valid: {is_valid}, Unique: {is_unique}",
    )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════


def run_schema_verification(env: str) -> SchemaVerification:
    """Run all schema verification checks."""
    import psycopg

    db_url = get_supabase_db_url(env)
    checks: list[SchemaCheck] = []

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # ─────────────────────────────────────────────────────────────────
            # FUNCTIONS
            # ─────────────────────────────────────────────────────────────────
            checks.append(check_function_exists(cur, "normalize_party_name", "p_name text"))
            checks.append(
                check_function_exists(
                    cur,
                    "compute_judgment_dedupe_key",
                    "p_case_number text, p_defendant_name text",
                )
            )

            # ─────────────────────────────────────────────────────────────────
            # COLUMNS
            # ─────────────────────────────────────────────────────────────────
            checks.append(check_column_exists(cur, "plaintiffs", "dedupe_key"))
            checks.append(check_column_exists(cur, "judgments", "dedupe_key"))

            # ─────────────────────────────────────────────────────────────────
            # INDEXES
            # ─────────────────────────────────────────────────────────────────
            checks.append(check_index_exists(cur, "idx_plaintiffs_dedupe_key", "plaintiffs"))
            checks.append(check_index_exists(cur, "idx_judgments_dedupe_key", "judgments"))

    # Calculate summary
    all_green = all(c.exists and c.valid for c in checks)
    summary = {
        "total": len(checks),
        "green": sum(1 for c in checks if c.exists and c.valid),
        "red": sum(1 for c in checks if not c.exists or not c.valid),
    }

    return SchemaVerification(
        environment=env,
        all_green=all_green,
        checks=checks,
        summary=summary,
    )


def print_report(verification: SchemaVerification, json_output: bool = False) -> None:
    """Print the verification report."""
    if json_output:
        output = {
            "environment": verification.environment,
            "all_green": verification.all_green,
            "summary": verification.summary,
            "checks": [asdict(c) for c in verification.checks],
        }
        print(json.dumps(output, indent=2))
        return

    # Human-readable output
    print()
    print("═" * 72)
    print(f" SCHEMA VERIFICATION: {verification.environment.upper()}")
    print("═" * 72)
    print()

    # Group by category
    by_category: dict[str, list[SchemaCheck]] = {}
    for check in verification.checks:
        by_category.setdefault(check.category.upper(), []).append(check)

    for category, items in by_category.items():
        print(f"┌─ {category} ─" + "─" * (60 - len(category)))
        for item in items:
            if item.exists and item.valid:
                status = "✅ GREEN"
            elif item.exists:
                status = "⚠️  WARN "
            else:
                status = "❌ RED  "
            print(f"│ {status}  {item.name}")
            print(f"│          {item.details}")
        print("└" + "─" * 70)
        print()

    # Summary
    print("─" * 72)
    s = verification.summary
    if verification.all_green:
        print(f" ✅ ALL GREEN: {s['green']}/{s['total']} checks passed")
    else:
        print(f" ❌ SCHEMA DRIFT DETECTED: {s['red']}/{s['total']} checks failed")
    print("─" * 72)
    print()


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify schema synchronization between migration history and database"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Target environment (default: from SUPABASE_MODE)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (for CI integration)",
    )
    args = parser.parse_args()

    # Resolve environment
    env = args.env or get_supabase_env()
    if env not in ("dev", "prod"):
        print(f"ERROR: Invalid environment '{env}'. Use --env dev|prod or set SUPABASE_MODE.")
        return 2

    try:
        verification = run_schema_verification(env)
        print_report(verification, json_output=args.json)
        return 0 if verification.all_green else 1
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"❌ ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
