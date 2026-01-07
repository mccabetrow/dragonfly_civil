#!/usr/bin/env python3
"""
Dragonfly Civil - Evidence Hash Verifier

Verifies the integrity of files in the Evidence Vault by comparing
stored SHA-256 hashes against computed hashes from Supabase Storage.

This tool detects tampering or corruption in evidence files.

Usage:
    python -m tools.verify_evidence_hash --env dev
    python -m tools.verify_evidence_hash --env prod --sample 50
    python -m tools.verify_evidence_hash --env prod --all

Exit Codes:
    0 - All verified files match
    1 - Hash mismatch detected (TAMPERING ALERT)
    2 - Configuration/connection error
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class EvidenceFile:
    """Evidence file record from database."""

    id: str
    org_id: str
    bucket_path: str
    file_name: str
    sha256_hash: str
    size_bytes: int
    verified_at: datetime | None
    verified_hash_match: bool | None


@dataclass
class VerificationResult:
    """Result of a single file verification."""

    file: EvidenceFile
    computed_hash: str | None
    matches: bool
    error: str | None = None
    download_time_ms: float = 0.0
    hash_time_ms: float = 0.0


def compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hash of data."""
    return hashlib.sha256(data).hexdigest()


def fetch_evidence_files(env: str, sample_size: int | None = None) -> list[EvidenceFile]:
    """
    Fetch evidence files from database.

    Args:
        env: Target environment
        sample_size: If provided, fetch random sample. None = all files.

    Returns:
        List of EvidenceFile records
    """
    import psycopg

    from src.supabase_client import get_supabase_db_url

    db_url = get_supabase_db_url(env)

    query = """
        SELECT
            id::text,
            org_id::text,
            bucket_path,
            file_name,
            sha256_hash,
            size_bytes,
            verified_at,
            verified_hash_match
        FROM evidence.files
    """

    if sample_size:
        query += f" ORDER BY random() LIMIT {sample_size}"
    else:
        query += " ORDER BY uploaded_at DESC"

    files = []

    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            for row in cur.fetchall():
                files.append(
                    EvidenceFile(
                        id=row[0],
                        org_id=row[1],
                        bucket_path=row[2],
                        file_name=row[3],
                        sha256_hash=row[4],
                        size_bytes=row[5],
                        verified_at=row[6],
                        verified_hash_match=row[7],
                    )
                )

    return files


def download_from_storage(env: str, bucket_path: str) -> bytes | None:
    """
    Download file from Supabase Storage.

    Args:
        env: Target environment
        bucket_path: Full path including bucket name (e.g., 'evidence/org-123/file.pdf')

    Returns:
        File bytes or None if error
    """
    from src.supabase_client import get_supabase_client

    client = get_supabase_client(env)

    # Parse bucket and path
    parts = bucket_path.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid bucket_path format: {bucket_path}")

    bucket_name = parts[0]
    file_path = parts[1]

    try:
        response = client.storage.from_(bucket_name).download(file_path)
        return response
    except Exception as e:
        raise RuntimeError(f"Storage download failed: {e}") from e


def update_verification_status(
    env: str,
    file_id: str,
    matches: bool,
) -> None:
    """
    Update the verification status in the database.

    Args:
        env: Target environment
        file_id: Evidence file ID
        matches: Whether hash matched
    """
    import psycopg

    from src.supabase_client import get_supabase_db_url

    db_url = get_supabase_db_url(env)

    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE evidence.files
                SET verified_at = now(),
                    verified_hash_match = %s
                WHERE id = %s::uuid
                """,
                (matches, file_id),
            )

            # Log verification event
            cur.execute(
                """
                INSERT INTO evidence.file_events (file_id, event_type, details)
                VALUES (%s::uuid, 'verified', %s)
                """,
                (
                    file_id,
                    f'{{"hash_match": {str(matches).lower()}}}',
                ),
            )

        conn.commit()


def verify_file(env: str, file: EvidenceFile) -> VerificationResult:
    """
    Verify a single evidence file.

    Args:
        env: Target environment
        file: Evidence file to verify

    Returns:
        VerificationResult
    """
    import time

    try:
        # Download file
        start_download = time.monotonic()
        data = download_from_storage(env, file.bucket_path)
        download_time = (time.monotonic() - start_download) * 1000

        if data is None:
            return VerificationResult(
                file=file,
                computed_hash=None,
                matches=False,
                error="File not found in storage",
            )

        # Verify size
        if len(data) != file.size_bytes:
            return VerificationResult(
                file=file,
                computed_hash=None,
                matches=False,
                error=f"Size mismatch: expected {file.size_bytes}, got {len(data)}",
            )

        # Compute hash
        start_hash = time.monotonic()
        computed_hash = compute_sha256(data)
        hash_time = (time.monotonic() - start_hash) * 1000

        # Compare
        matches = computed_hash.lower() == file.sha256_hash.lower()

        # Update database
        update_verification_status(env, file.id, matches)

        return VerificationResult(
            file=file,
            computed_hash=computed_hash,
            matches=matches,
            download_time_ms=download_time,
            hash_time_ms=hash_time,
        )

    except Exception as e:
        return VerificationResult(
            file=file,
            computed_hash=None,
            matches=False,
            error=f"{type(e).__name__}: {e}",
        )


def send_tampering_alert(env: str, mismatches: list[VerificationResult]) -> None:
    """
    Send Discord alert for detected tampering.

    Args:
        env: Target environment
        mismatches: List of files with hash mismatches
    """
    try:
        from backend.utils.discord import AlertColor, send_alert

        file_list = "\n".join(f"- `{r.file.file_name}` (ID: {r.file.id})" for r in mismatches[:10])

        send_alert(
            title="🚨 EVIDENCE TAMPERING DETECTED",
            description=f"{len(mismatches)} file(s) failed hash verification",
            color=AlertColor.FAILURE,
            fields={
                "Environment": env.upper(),
                "Files Affected": str(len(mismatches)),
                "Sample": file_list[:1000],
            },
        )
    except Exception:
        pass  # Never fail on alerting


def run_verification(
    env: str,
    sample_size: int | None = None,
    verbose: bool = False,
) -> tuple[int, int, int]:
    """
    Run verification on evidence files.

    Args:
        env: Target environment
        sample_size: Number of files to sample (None = all)
        verbose: Print detailed output

    Returns:
        Tuple of (total, passed, failed)
    """
    print(f"🔐 Evidence Hash Verification ({env.upper()})")
    print("=" * 70)

    # Fetch files
    print("\nFetching evidence files...")
    files = fetch_evidence_files(env, sample_size)

    if not files:
        print("No evidence files found.")
        return 0, 0, 0

    print(f"Verifying {len(files)} files...")
    print("-" * 70)

    results: list[VerificationResult] = []
    passed = 0
    failed = 0

    for i, file in enumerate(files, 1):
        result = verify_file(env, file)
        results.append(result)

        if result.matches:
            passed += 1
            status = "✅"
        else:
            failed += 1
            status = "❌"

        if verbose or not result.matches:
            print(f"{status} [{i}/{len(files)}] {file.file_name}")
            if result.error:
                print(f"   Error: {result.error}")
            elif not result.matches:
                print(f"   Expected: {file.sha256_hash}")
                print(f"   Computed: {result.computed_hash}")

    # Summary
    print("-" * 70)
    print("\n📊 Verification Summary:")
    print(f"   Total:  {len(files)}")
    print(f"   Passed: {passed} ✅")
    print(f"   Failed: {failed} {'❌' if failed else ''}")

    # Alert on failures
    mismatches = [r for r in results if not r.matches]
    if mismatches:
        print("\n🚨 TAMPERING DETECTED - Sending alert...")
        send_tampering_alert(env, mismatches)

    return len(files), passed, failed


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Verify evidence file integrity via SHA-256 hash comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=10,
        help="Number of files to sample (default: 10)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Verify all files (overrides --sample)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed output for each file",
    )

    args = parser.parse_args()
    os.environ["SUPABASE_MODE"] = args.env

    sample_size = None if args.all else args.sample

    try:
        total, passed, failed = run_verification(
            env=args.env,
            sample_size=sample_size,
            verbose=args.verbose,
        )

        if failed > 0:
            print("\n❌ VERIFICATION FAILED: Evidence tampering detected!")
            return 1
        elif total == 0:
            print("\n⚠️  No files to verify")
            return 0
        else:
            print("\n✅ VERIFICATION PASSED: All files intact")
            return 0

    except Exception as e:
        print(f"\n❌ Verification error: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
