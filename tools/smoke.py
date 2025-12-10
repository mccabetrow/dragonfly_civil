"""Simple smoke probe for Supabase judgments endpoint."""

import json
import os
import subprocess
import sys

from dotenv import load_dotenv

from src.db_upload_safe import upsert_public_judgments


def run_curl(row: dict) -> None:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    endpoint = url.rstrip("/") + "/rest/v1/judgments?on_conflict=case_number"
    payload = json.dumps([row], separators=(",", ":"))

    command = [
        "curl",
        "-i",
        "-H",
        f"apikey: {key}",
        "-H",
        f"Authorization: Bearer {key}",
        "-H",
        "Content-Type: application/json",
        "-H",
        "Prefer: return=representation,count=exact",
        "-H",
        "Prefer: resolution=merge-duplicates",
        "-d",
        payload,
        endpoint,
    ]

    print("Executing curl smoke test...")
    process = subprocess.run(command, capture_output=True, text=True)

    if process.stdout:
        print(process.stdout.rstrip())
    if process.stderr:
        print(process.stderr.rstrip(), file=sys.stderr)

    if process.returncode != 0:
        raise RuntimeError(f"curl exited with status {process.returncode}")


def main() -> None:
    load_dotenv()
    row = {"case_number": "SMOKE-CURL-1", "source_file": "smoke"}

    run_curl(row)

    print("Invoking upsert_public_judgments...")
    upsert_result = upsert_public_judgments([row])
    print(f"upsert_public_judgments returned: {upsert_result}")

    print("SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - smoke utility
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
