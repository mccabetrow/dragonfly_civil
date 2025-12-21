#!/usr/bin/env python3
"""
Dragonfly Contract Truth Verification

Verifies the canonical RPC function signatures directly from the database
using psycopg (no psql binary required). This serves as the Phase 2 Gate
for B3 deployment control.

Usage:
    python scripts/verify_db_contract.py              # Verify using default env
    python scripts/verify_db_contract.py --env prod   # Verify production
    python scripts/verify_db_contract.py --json       # Output as JSON

Exit Codes:
    0 - All canonical RPCs exist with exactly 1 overload each
    1 - Missing RPCs or multiple overloads detected
    2 - Database connection failed

Contract Truth Query:
    Inspects pg_proc to get function signatures for ops schema RPCs.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import psycopg
from psycopg.rows import dict_row

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Canonical RPC functions that must exist with exactly 1 signature
CANONICAL_RPCS = [
    "claim_pending_job",
    "queue_job",
    "register_heartbeat",
    "update_job_status",
    "reap_stuck_jobs",
]

# Contract Truth Query - inspects pg_proc for function signatures
CONTRACT_TRUTH_QUERY = """
SELECT
    p.proname AS function_name,
    pg_get_function_identity_arguments(p.oid) AS args,
    CASE p.prosecdef
        WHEN true THEN 'SECURITY DEFINER'
        ELSE 'SECURITY INVOKER'
    END AS security_type,
    pg_get_function_result(p.oid) AS return_type
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops'
  AND p.proname = ANY(%s)
ORDER BY p.proname, pg_get_function_identity_arguments(p.oid)
"""


@dataclass
class RPCSignature:
    """Represents a function signature from the database."""

    function_name: str
    args: str
    security_type: str
    return_type: str


def get_contract_truth(db_url: str) -> tuple[list[RPCSignature], str | None]:
    """
    Query the database for canonical RPC signatures.

    Returns:
        Tuple of (list of signatures, error message if any)
    """
    try:
        with psycopg.connect(
            db_url,
            row_factory=dict_row,
            connect_timeout=10,
            application_name="dragonfly_contract_verify",
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(CONTRACT_TRUTH_QUERY, (list(CANONICAL_RPCS),))
                rows = cur.fetchall()

                signatures = [
                    RPCSignature(
                        function_name=row["function_name"],
                        args=row["args"],
                        security_type=row["security_type"],
                        return_type=row["return_type"],
                    )
                    for row in rows
                ]

                return signatures, None

    except psycopg.OperationalError as e:
        return [], f"Database connection failed: {e}"
    except Exception as e:
        return [], f"Query failed: {e}"


def analyze_signatures(
    signatures: list[RPCSignature],
) -> tuple[dict[str, list[RPCSignature]], list[str], list[str]]:
    """
    Analyze signatures for contract compliance.

    Returns:
        Tuple of (grouped signatures, missing RPCs, RPCs with multiple overloads)
    """
    # Group by function name
    grouped: dict[str, list[RPCSignature]] = {}
    for sig in signatures:
        if sig.function_name not in grouped:
            grouped[sig.function_name] = []
        grouped[sig.function_name].append(sig)

    # Find missing RPCs
    missing = [name for name in CANONICAL_RPCS if name not in grouped]

    # Find RPCs with multiple overloads
    overloaded = [name for name, sigs in grouped.items() if len(sigs) > 1]

    return grouped, missing, overloaded


def print_contract_table(
    signatures: list[RPCSignature], grouped: dict[str, list[RPCSignature]]
) -> None:
    """Print signatures in a formatted table."""
    click.echo("")
    click.echo("=" * 80)
    click.echo("  CONTRACT TRUTH - ops schema RPC signatures")
    click.echo("=" * 80)
    click.echo("")

    if not signatures:
        click.echo("  No signatures found!")
        click.echo("")
        return

    # Column widths
    name_width = max(len(sig.function_name) for sig in signatures) + 2
    args_width = max(len(sig.args) for sig in signatures) + 2
    sec_width = 18
    ret_width = 30

    # Header
    header = (
        f"{'Function':<{name_width}} | "
        f"{'Arguments':<{args_width}} | "
        f"{'Security':<{sec_width}} | "
        f"{'Returns':<{ret_width}}"
    )
    click.echo(header)
    click.echo("-" * len(header))

    # Rows
    for sig in signatures:
        # Truncate return type if too long
        ret = sig.return_type
        if len(ret) > ret_width:
            ret = ret[: ret_width - 3] + "..."

        row = (
            f"{sig.function_name:<{name_width}} | "
            f"{sig.args:<{args_width}} | "
            f"{sig.security_type:<{sec_width}} | "
            f"{ret:<{ret_width}}"
        )
        click.echo(row)

    click.echo("")

    # Overload analysis
    click.echo("Overload Analysis:")
    for name in CANONICAL_RPCS:
        count = len(grouped.get(name, []))
        if count == 0:
            click.echo(click.style(f"  [MISSING] {name}", fg="red"))
        elif count == 1:
            click.echo(click.style(f"  [OK]      {name}: 1 signature", fg="green"))
        else:
            click.echo(
                click.style(f"  [ERROR]   {name}: {count} overloads (must be exactly 1)", fg="red")
            )

    click.echo("")


def print_json_output(
    signatures: list[RPCSignature],
    missing: list[str],
    overloaded: list[str],
    env: str,
) -> None:
    """Print output as JSON."""
    output = {
        "environment": env,
        "signatures": [
            {
                "function_name": sig.function_name,
                "args": sig.args,
                "security_type": sig.security_type,
                "return_type": sig.return_type,
            }
            for sig in signatures
        ],
        "missing_rpcs": missing,
        "overloaded_rpcs": overloaded,
        "contract_valid": len(missing) == 0 and len(overloaded) == 0,
    }
    click.echo(json.dumps(output, indent=2))


@click.command()
@click.option(
    "--env",
    type=click.Choice(["dev", "prod"]),
    help="Target environment",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
def main(env: str | None, output_json: bool) -> None:
    """Verify Dragonfly RPC contract truth from the database."""
    if env:
        os.environ["SUPABASE_MODE"] = env

    current_env = get_supabase_env()

    if not output_json:
        click.echo(f"Environment: {current_env.upper()}")
        click.echo(f"Canonical RPCs: {', '.join(CANONICAL_RPCS)}")

    # Get database URL
    try:
        db_url = get_supabase_db_url()
    except RuntimeError as e:
        if output_json:
            click.echo(json.dumps({"error": str(e), "contract_valid": False}))
        else:
            click.echo(click.style(f"ERROR: {e}", fg="red"))
        raise SystemExit(2)

    # Query contract truth
    signatures, error = get_contract_truth(db_url)

    if error:
        if output_json:
            click.echo(json.dumps({"error": error, "contract_valid": False}))
        else:
            click.echo(click.style(f"ERROR: {error}", fg="red"))
        raise SystemExit(2)

    # Analyze signatures
    grouped, missing, overloaded = analyze_signatures(signatures)

    # Output results
    if output_json:
        print_json_output(signatures, missing, overloaded, current_env)
    else:
        print_contract_table(signatures, grouped)

        # Summary
        if missing or overloaded:
            click.echo("=" * 80)
            click.echo(click.style("  CONTRACT VERIFICATION FAILED", fg="red", bold=True))
            if missing:
                click.echo(f"  Missing RPCs: {', '.join(missing)}")
            if overloaded:
                click.echo(f"  Overloaded RPCs: {', '.join(overloaded)}")
            click.echo("=" * 80)
            raise SystemExit(1)
        else:
            click.echo("=" * 80)
            click.echo(
                click.style(
                    f"  CONTRACT VERIFIED: All {len(CANONICAL_RPCS)} RPCs have exactly 1 signature",
                    fg="green",
                    bold=True,
                )
            )
            click.echo("=" * 80)
            raise SystemExit(0)

    # JSON output exit code
    if missing or overloaded:
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
