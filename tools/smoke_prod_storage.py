"""
Prod Smoke: Exercise the full cloud path with Supabase Storage.

This script tests the complete production pipeline:
  1. Upload a CSV to Supabase Storage
  2. Queue a job via RPC with the storage path
  3. Poll ops.job_queue until job completes or fails

Use this to validate that workers can successfully:
  - Download files from Supabase Storage
  - Process them correctly
  - Update job status appropriately

Usage:
    python -m tools.smoke_prod_storage --file-path ./data_in/smoke_test.csv
    python -m tools.smoke_prod_storage --bucket intake-batch --file-path ./data.csv
    python -m tools.smoke_prod_storage --file-path ./test.csv --timeout 120
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

import click
import psycopg

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import create_supabase_client, get_supabase_db_url, get_supabase_env


def _resolve_file(file_path: str) -> Path:
    """Resolve and validate file path."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise click.ClickException(f"File not found: {path}")
    if not path.is_file():
        raise click.ClickException(f"Not a file: {path}")
    return path


def _generate_storage_key(filename: str) -> str:
    """Generate a unique storage key for smoke tests."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return f"smoke_tests/{ts}_{filename}"


def upload_to_storage(client, bucket: str, local_path: Path) -> str:
    """Upload file to Supabase Storage and return the storage key."""
    storage_key = _generate_storage_key(local_path.name)
    click.echo(f"[smoke_prod] Uploading to {bucket}/{storage_key}...")

    try:
        with open(local_path, "rb") as f:
            content = f.read()

        # Determine content type
        suffix = local_path.suffix.lower()
        content_type = "text/csv" if suffix == ".csv" else "application/octet-stream"

        client.storage.from_(bucket).upload(
            storage_key,
            content,
            file_options={"content-type": content_type, "upsert": "true"},
        )

        click.echo(f"[smoke_prod] ✅ Upload successful: {storage_key}")
        return storage_key

    except Exception as e:
        # Try to provide helpful diagnostics
        error_msg = str(e)
        if "Bucket not found" in error_msg or "404" in error_msg:
            try:
                buckets = client.storage.list_buckets()
                bucket_names = [b.name for b in buckets]
                raise click.ClickException(
                    f"Bucket '{bucket}' not found. Available buckets: {bucket_names}"
                ) from e
            except click.ClickException:
                raise
            except Exception:
                pass
        raise click.ClickException(f"Upload failed: {e}") from e


def queue_job_via_rpc(
    conn: psycopg.Connection,
    job_type: str,
    payload: dict,
) -> UUID:
    """Queue a job using ops.queue_job RPC."""
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
                (job_type, json.dumps(payload), 10),  # High priority for smoke tests
            )
            result = cur.fetchone()
            conn.commit()
            if result and result[0]:
                return UUID(str(result[0]))
            raise click.ClickException("queue_job RPC returned NULL")
    except click.ClickException:
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise click.ClickException(f"Failed to queue job: {e}") from e


def poll_job_status(
    conn: psycopg.Connection,
    job_id: UUID,
    timeout_seconds: int,
    poll_interval: float = 2.0,
) -> tuple[str, dict | None]:
    """
    Poll ops.job_queue for job completion.

    Returns:
        Tuple of (status, error_dict or None)
    """
    start_time = time.time()
    last_status = "unknown"

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise click.ClickException(
                f"Timeout after {timeout_seconds}s - job still in '{last_status}' state"
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, error, updated_at
                FROM ops.job_queue
                WHERE id = %s
                """,
                (str(job_id),),
            )
            row = cur.fetchone()

        if not row:
            raise click.ClickException(f"Job {job_id} not found in ops.job_queue")

        status, error, updated_at = row
        last_status = status

        if status == "completed":
            return status, None
        elif status == "failed":
            return status, error if isinstance(error, dict) else {"message": str(error)}
        elif status in ("pending", "processing"):
            click.echo(
                f"[smoke_prod] Status: {status} (elapsed: {elapsed:.1f}s, "
                f"updated: {updated_at})"
            )
            time.sleep(poll_interval)
        else:
            # Unknown status - keep polling but warn
            click.echo(f"[smoke_prod] ⚠️ Unexpected status: {status}")
            time.sleep(poll_interval)


def cleanup_storage(client, bucket: str, storage_key: str) -> None:
    """Attempt to remove uploaded file from storage."""
    try:
        client.storage.from_(bucket).remove([storage_key])
        click.echo(f"[smoke_prod] Cleaned up: {bucket}/{storage_key}")
    except Exception as e:
        click.echo(f"[smoke_prod] ⚠️ Cleanup failed: {e}")


@click.command()
@click.option(
    "--bucket",
    default="intake-batch",
    help="Supabase Storage bucket name",
)
@click.option(
    "--file-path",
    required=True,
    help="Path to CSV file to upload",
)
@click.option(
    "--job-type",
    default="simplicity_ingest",
    help="Job type to queue (default: simplicity_ingest)",
)
@click.option(
    "--timeout",
    default=60,
    type=int,
    help="Max seconds to wait for job completion",
)
@click.option(
    "--no-cleanup",
    is_flag=True,
    help="Don't remove uploaded file after test",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Upload only, don't queue job",
)
def main(
    bucket: str,
    file_path: str,
    job_type: str,
    timeout: int,
    no_cleanup: bool,
    dry_run: bool,
) -> None:
    """Prod Smoke: Test the full cloud path with Supabase Storage.

    This uploads a file to Supabase Storage, queues a job via RPC,
    and polls until the job completes or fails.

    Requires:
      - SUPABASE_URL
      - SUPABASE_SERVICE_ROLE_KEY
      - SUPABASE_DB_URL
      - Workers running in production (or locally pointing to same DB)
    """
    env = get_supabase_env()
    click.echo(f"[smoke_prod] Environment: {env}")
    click.echo(f"[smoke_prod] Bucket: {bucket}")

    # Validate file
    local_path = _resolve_file(file_path)
    click.echo(f"[smoke_prod] File: {local_path} ({local_path.stat().st_size} bytes)")

    # Create Supabase client for storage
    client = create_supabase_client()

    # Step 1: Upload to storage
    storage_key = upload_to_storage(client, bucket, local_path)

    if dry_run:
        click.echo("[smoke_prod] DRY RUN - job not queued")
        if not no_cleanup:
            cleanup_storage(client, bucket, storage_key)
        return

    # Step 2: Queue job via RPC
    payload = {
        "bucket": bucket,
        "key": storage_key,
        "source_reference": "prod-smoke",
        "_smoke_test": True,
        "_queued_at": datetime.utcnow().isoformat(),
    }

    click.echo("[smoke_prod] Queuing job with payload:")
    click.echo(f"  {json.dumps(payload, indent=2)}")

    db_url = get_supabase_db_url()

    with psycopg.connect(db_url) as conn:
        job_id = queue_job_via_rpc(conn, job_type, payload)
        click.echo(f"[smoke_prod] ✅ Job queued: {job_id}")

        # Step 3: Poll for completion
        click.echo(f"[smoke_prod] Polling for completion (timeout: {timeout}s)...")
        try:
            status, error = poll_job_status(conn, job_id, timeout)
        except click.ClickException:
            # On timeout, still try cleanup
            if not no_cleanup:
                cleanup_storage(client, bucket, storage_key)
            raise

    # Report result
    if status == "completed":
        click.echo(f"[smoke_prod] ✅ [PASS] Job {job_id} completed successfully!")
    else:
        click.echo(f"[smoke_prod] ❌ [FAIL] Job {job_id} failed!")
        if error:
            click.echo(f"[smoke_prod] Error: {json.dumps(error, indent=2)}")
        if not no_cleanup:
            cleanup_storage(client, bucket, storage_key)
        raise SystemExit(1)

    # Cleanup
    if not no_cleanup:
        cleanup_storage(client, bucket, storage_key)

    click.echo("")
    click.echo("Prod smoke test passed! ✅")


if __name__ == "__main__":
    main()
