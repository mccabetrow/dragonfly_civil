"""
Dev Smoke: Queue a job for simplicity_ingest_worker using file:// paths.

This script bypasses cloud storage and tests worker logic locally.
Use this in dev environments to validate the job queue -> worker pipeline
without requiring Supabase Storage connectivity.

Usage:
    python -m tools.queue_local_job
    python -m tools.queue_local_job --file-path ./data_in/smoke_test.csv
    python -m tools.queue_local_job --job-type simplicity_ingest --dry-run
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

import click
import psycopg

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import get_supabase_db_url, get_supabase_env


def _resolve_absolute_path(file_path: str) -> Path:
    """Resolve file path to absolute, validating it exists."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise click.ClickException(f"File not found: {path}")
    if not path.is_file():
        raise click.ClickException(f"Not a file: {path}")
    return path


def _build_file_uri(absolute_path: Path) -> str:
    """Build a file:// URI from an absolute path."""
    # On Windows, paths like C:\foo become file:///C:/foo
    posix_path = absolute_path.as_posix()
    if not posix_path.startswith("/"):
        # Windows absolute path: C:/foo -> /C:/foo
        posix_path = "/" + posix_path
    return f"file://{posix_path}"


def _generate_source_reference() -> str:
    """Generate a unique source reference for dev smoke tests."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"dev-smoke-{ts}"


def queue_job_via_rpc(
    conn: psycopg.Connection,
    job_type: str,
    payload: dict,
    priority: int = 0,
) -> UUID | None:
    """Queue a job using ops.queue_job RPC (not raw SQL)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ops.queue_job(
                    p_type := %s,
                    p_payload := %s::jsonb,
                    p_priority := %s,
                    p_run_at := now()
                )
                """,
                (job_type, json.dumps(payload), priority),
            )
            result = cur.fetchone()
            conn.commit()
            return UUID(str(result[0])) if result and result[0] else None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise click.ClickException(f"Failed to queue job via RPC: {e}") from e


@click.command()
@click.option(
    "--file-path",
    default="./data_in/smoke_test.csv",
    help="Path to CSV file (will be converted to file:// URI)",
)
@click.option(
    "--job-type",
    default="simplicity_ingest",
    help="Job type to queue (default: simplicity_ingest)",
)
@click.option(
    "--priority",
    default=0,
    type=int,
    help="Job priority (higher = more urgent)",
)
@click.option(
    "--source-reference",
    default=None,
    help="Override source reference (default: auto-generated dev-smoke-<timestamp>)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print payload without queuing",
)
def main(
    file_path: str,
    job_type: str,
    priority: int,
    source_reference: str | None,
    dry_run: bool,
) -> None:
    """Queue a job for the simplicity_ingest_worker using file:// paths.

    This is a DEV SMOKE tool for testing the job queue -> worker pipeline
    without requiring Supabase Storage connectivity.

    The worker must support file:// URIs in the payload (most ingest workers do).
    """
    env = get_supabase_env()
    click.echo(f"[queue_local_job] Environment: {env}")

    # Validate and resolve file path
    absolute_path = _resolve_absolute_path(file_path)
    file_uri = _build_file_uri(absolute_path)
    click.echo(f"[queue_local_job] File: {absolute_path}")
    click.echo(f"[queue_local_job] URI:  {file_uri}")

    # Build source reference
    src_ref = source_reference or _generate_source_reference()

    # Build payload
    payload = {
        "file_path": file_uri,
        "source_reference": src_ref,
        # Include metadata for debugging
        "_smoke_test": True,
        "_queued_at": datetime.utcnow().isoformat(),
    }

    click.echo(f"[queue_local_job] Payload: {json.dumps(payload, indent=2)}")

    if dry_run:
        click.echo("[queue_local_job] DRY RUN - job not queued")
        return

    # Get DB URL and connect
    try:
        db_url = get_supabase_db_url()
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    click.echo("[queue_local_job] Connecting to database...")

    with psycopg.connect(db_url) as conn:
        job_id = queue_job_via_rpc(conn, job_type, payload, priority)

    if job_id:
        click.echo("[queue_local_job] ✅ Job queued successfully!")
        click.echo(f"[queue_local_job] Job ID: {job_id}")
        click.echo(f"[queue_local_job] Job Type: {job_type}")
        click.echo(f"[queue_local_job] Source Ref: {src_ref}")
        click.echo("")
        click.echo("Next steps:")
        click.echo("  1. Start the worker: python -m workers.runner --kind simplicity_ingest")
        click.echo("  2. Watch for job completion in worker logs")
        click.echo(f"  3. Verify: SELECT * FROM ops.job_queue WHERE id = '{job_id}'")
    else:
        raise click.ClickException("Job queue returned None - check RPC function")


if __name__ == "__main__":
    main()
