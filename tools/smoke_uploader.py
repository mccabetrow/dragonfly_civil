#!/usr/bin/env python3
"""
Smoke Uploader - Robust multipart file upload for smoke testing.

This script replaces PowerShell's Invoke-RestMethod for file uploads,
avoiding encoding and multipart boundary issues.

Usage:
    python -m tools.smoke_uploader --api-url <URL> --api-key <KEY> --file-path <PATH>
    python -m tools.smoke_uploader --api-url https://api.example.com/upload --api-key secret --file-path data.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not installed. Run: pip install requests")
    sys.exit(1)


def upload_file(api_url: str, api_key: str, file_path: str) -> dict:
    """
    Upload a file using multipart/form-data.

    Args:
        api_url: The API endpoint URL
        api_key: The API key for authentication
        file_path: Path to the file to upload

    Returns:
        dict with 'success', 'batch_id' (if successful), and 'error' (if failed)
    """
    path = Path(file_path)

    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    if not path.is_file():
        return {"success": False, "error": f"Not a file: {file_path}"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "apikey": api_key,  # Supabase format
    }

    try:
        with open(path, "rb") as f:
            files = {"file": (path.name, f, "text/csv")}

            response = requests.post(
                api_url,
                headers=headers,
                files=files,
                timeout=60,
            )

        # Check status code
        if response.status_code in (200, 201):
            try:
                data = response.json()
                batch_id = data.get("batch_id") or data.get("id") or data.get("Key")
                return {
                    "success": True,
                    "batch_id": batch_id,
                    "status_code": response.status_code,
                    "response": data,
                }
            except json.JSONDecodeError:
                # Non-JSON success response
                return {
                    "success": True,
                    "batch_id": None,
                    "status_code": response.status_code,
                    "response": response.text[:200],
                }
        else:
            try:
                error_data = response.json()
                error_msg = error_data.get("error") or error_data.get("message") or str(error_data)
            except json.JSONDecodeError:
                error_msg = response.text[:200]

            return {
                "success": False,
                "status_code": response.status_code,
                "error": error_msg,
            }

    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out after 60 seconds"}
    except requests.exceptions.ConnectionError as e:
        return {"success": False, "error": f"Connection error: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {e}"}


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Upload a file to an API endpoint for smoke testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--api-url",
        required=True,
        help="The API endpoint URL for file upload",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="The API key for authentication",
    )
    parser.add_argument(
        "--file-path",
        required=True,
        help="Path to the file to upload",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show verbose output",
    )

    args = parser.parse_args()

    if args.verbose:
        print(f"API URL:   {args.api_url}")
        print(f"API Key:   {args.api_key[:8]}...")
        print(f"File:      {args.file_path}")
        print()

    result = upload_file(args.api_url, args.api_key, args.file_path)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            batch_id = result.get("batch_id", "N/A")
            print(f"SUCCESS: Batch {batch_id} created")
            if args.verbose and result.get("response"):
                print(f"Response: {result['response']}")
        else:
            error = result.get("error", "Unknown error")
            status = result.get("status_code", "N/A")
            print(f"FAILURE: {error}")
            if status != "N/A":
                print(f"Status Code: {status}")

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
