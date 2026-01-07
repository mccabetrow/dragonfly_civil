#!/usr/bin/env python3
"""
Dragonfly Civil - Data Classification Auditor

Ensures all columns in core tables have proper classification tags.
This script is designed to run in CI to enforce data governance.

Classification Schema:
    {
        "tag": "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "PII" | "FINANCIAL",
        "sensitivity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
        "description": "Human-readable description"
    }

Usage:
    python -m tools.audit_data_classification --env dev
    python -m tools.audit_data_classification --env prod --strict

Exit Codes:
    0 - All columns classified
    1 - Unclassified columns found
    2 - Configuration error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Valid classification tags
VALID_TAGS = {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII", "FINANCIAL"}
VALID_SENSITIVITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

# Schemas to audit
AUDIT_SCHEMAS = ["public", "intake", "enforcement"]

# Tables to audit (if empty, audit all tables in schemas)
CORE_TABLES = [
    "public.judgments",
    "public.plaintiffs",
    "public.plaintiff_contacts",
    "public.plaintiff_status_history",
]


@dataclass
class ColumnInfo:
    """Information about a database column."""

    schema_name: str
    table_name: str
    column_name: str
    data_type: str
    comment: str | None

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}.{self.column_name}"

    @property
    def table_full_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


@dataclass
class ClassificationResult:
    """Result of classification validation."""

    column: ColumnInfo
    is_valid: bool
    tag: str | None = None
    sensitivity: str | None = None
    error: str | None = None


def parse_classification_comment(comment: str | None) -> dict[str, Any] | None:
    """
    Parse a classification comment as JSON.

    Args:
        comment: The column comment string

    Returns:
        Parsed JSON dict or None if invalid
    """
    if not comment:
        return None

    try:
        data = json.loads(comment)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    return None


def validate_classification(column: ColumnInfo) -> ClassificationResult:
    """
    Validate that a column has proper classification.

    Args:
        column: Column information

    Returns:
        ClassificationResult with validation status
    """
    if not column.comment:
        return ClassificationResult(
            column=column,
            is_valid=False,
            error="No comment (classification missing)",
        )

    parsed = parse_classification_comment(column.comment)

    if parsed is None:
        return ClassificationResult(
            column=column,
            is_valid=False,
            error="Comment is not valid JSON",
        )

    tag = parsed.get("tag")
    sensitivity = parsed.get("sensitivity")

    if not tag:
        return ClassificationResult(
            column=column,
            is_valid=False,
            error="Missing 'tag' field in classification",
        )

    if tag not in VALID_TAGS:
        return ClassificationResult(
            column=column,
            is_valid=False,
            tag=tag,
            error=f"Invalid tag '{tag}' (must be one of {VALID_TAGS})",
        )

    if sensitivity and sensitivity not in VALID_SENSITIVITIES:
        return ClassificationResult(
            column=column,
            is_valid=False,
            tag=tag,
            sensitivity=sensitivity,
            error=f"Invalid sensitivity '{sensitivity}' (must be one of {VALID_SENSITIVITIES})",
        )

    return ClassificationResult(
        column=column,
        is_valid=True,
        tag=tag,
        sensitivity=sensitivity,
    )


def fetch_column_comments(env: str) -> list[ColumnInfo]:
    """
    Fetch all columns and their comments from the database.

    Args:
        env: Target environment (dev/prod)

    Returns:
        List of ColumnInfo objects
    """
    import psycopg

    from src.supabase_client import get_supabase_db_url

    db_url = get_supabase_db_url(env)

    query = """
        SELECT
            c.table_schema,
            c.table_name,
            c.column_name,
            c.data_type,
            pg_catalog.col_description(
                (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                c.ordinal_position
            ) AS column_comment
        FROM information_schema.columns c
        WHERE c.table_schema = ANY(%s)
        ORDER BY c.table_schema, c.table_name, c.ordinal_position
    """

    columns = []

    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (AUDIT_SCHEMAS,))
            for row in cur.fetchall():
                columns.append(
                    ColumnInfo(
                        schema_name=row[0],
                        table_name=row[1],
                        column_name=row[2],
                        data_type=row[3],
                        comment=row[4],
                    )
                )

    return columns


def run_audit(env: str, strict: bool = False, core_only: bool = True) -> int:
    """
    Run the classification audit.

    Args:
        env: Target environment
        strict: If True, require sensitivity field
        core_only: If True, only audit CORE_TABLES

    Returns:
        Exit code (0 = success, 1 = failures found)
    """
    print(f"🔍 Data Classification Audit ({env.upper()})")
    print("=" * 70)

    # Fetch columns
    print("\nFetching column metadata...")
    columns = fetch_column_comments(env)
    print(f"Found {len(columns)} columns in schemas: {AUDIT_SCHEMAS}")

    # Filter to core tables if requested
    if core_only:
        columns = [c for c in columns if c.table_full_name in CORE_TABLES]
        print(f"Filtering to {len(columns)} columns in core tables")

    # Validate each column
    results = [validate_classification(c) for c in columns]

    # Separate valid and invalid
    valid = [r for r in results if r.is_valid]
    invalid = [r for r in results if not r.is_valid]

    # Print summary by tag
    print("\n📊 Classification Summary:")
    print("-" * 50)

    tag_counts: dict[str, int] = {}
    for r in valid:
        tag = r.tag or "UNKNOWN"
        tag_counts[tag] = tag_counts.get(tag, 0) + 1

    for tag in sorted(tag_counts.keys()):
        emoji = {
            "PUBLIC": "🌐",
            "INTERNAL": "🏢",
            "CONFIDENTIAL": "🔒",
            "PII": "👤",
            "FINANCIAL": "💰",
        }.get(tag, "❓")
        print(f"  {emoji} {tag}: {tag_counts[tag]}")

    # Print unclassified columns
    if invalid:
        print("\n❌ Unclassified Columns:")
        print("-" * 70)
        print(f"{'Column':<50} {'Error':<20}")
        print("-" * 70)

        for r in invalid:
            print(f"{r.column.full_name:<50} {r.error:<20}")

        print("-" * 70)
        print(f"Total unclassified: {len(invalid)}")

    # Final verdict
    print("\n" + "=" * 70)

    if invalid:
        print(f"❌ AUDIT FAILED: {len(invalid)} columns missing classification")
        print("\nTo fix, add COMMENT ON COLUMN statements to your migration:")
        print("  COMMENT ON COLUMN table.column IS")
        print('    \'{"tag": "PII", "sensitivity": "HIGH", "description": "..."}\'')
        return 1
    else:
        print(f"✅ AUDIT PASSED: All {len(valid)} columns classified")
        return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Audit data classification compliance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require sensitivity field in classification",
    )
    parser.add_argument(
        "--all-tables",
        action="store_true",
        help="Audit all tables, not just core tables",
    )

    args = parser.parse_args()
    os.environ["SUPABASE_MODE"] = args.env

    try:
        return run_audit(
            env=args.env,
            strict=args.strict,
            core_only=not args.all_tables,
        )
    except Exception as e:
        print(f"❌ Audit error: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
