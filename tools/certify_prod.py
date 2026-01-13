#!/usr/bin/env python3
"""Dragonfly production certification harness."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List

import httpx

# Ensure project root modules resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.supabase_client import get_supabase_db_url

TIMEOUT = httpx.Timeout(10.0)
OPS_SCHEMA = "ops"
OPS_TABLE = "import_runs"
REQUIRED_HEADERS = ("X-Dragonfly-SHA-Short", "X-Dragonfly-Env")
BLOCKED_STATUSES = {401, 403, 404}


@dataclass
class CheckResult:
    """Represents the outcome of a certification check."""

    name: str
    passed: bool
    detail: str


class ProdCertifier:
    """Runs deterministic certification checks."""

    def __init__(
        self,
        base_url: str,
        env: str,
        supabase_url: str,
        anon_key: str,
        service_key: str,
        db_url: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.env = env.lower()
        self.supabase_url = supabase_url.rstrip("/")
        self.anon_key = anon_key
        self.service_key = service_key
        self.db_url = db_url

    # ------------------------------------------------------------------
    # HTTP Helpers
    # ------------------------------------------------------------------

    def _api_get(self, path: str) -> httpx.Response:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            return client.get(url)

    def _rest_headers(
        self, key: str, *, profile: str | None = None, auth: str | None = None
    ) -> dict[str, str]:
        headers = {
            "apikey": key,
            "Content-Type": "application/json",
        }
        if auth:
            headers["Authorization"] = auth
        if profile:
            headers["Accept-Profile"] = profile
            headers["Content-Profile"] = profile
        return headers

    # ------------------------------------------------------------------
    # Certification Checks
    # ------------------------------------------------------------------

    def check_health(self) -> CheckResult:
        try:
            resp = self._api_get("/health")
            if resp.status_code == 200:
                return CheckResult("/health", True, "200 OK")
            return CheckResult("/health", False, f"Expected 200, got {resp.status_code}")
        except Exception as exc:  # pragma: no cover - network failure surfaces to operator
            return CheckResult("/health", False, f"Request failed: {exc}")

    def check_readyz(self) -> CheckResult:
        try:
            resp = self._api_get("/readyz")
            if resp.status_code == 200:
                return CheckResult("/readyz", True, "200 OK")
            return CheckResult("/readyz", False, f"Expected 200, got {resp.status_code}")
        except Exception as exc:  # pragma: no cover
            return CheckResult("/readyz", False, f"Request failed: {exc}")

    def check_headers(self) -> CheckResult:
        try:
            resp = self._api_get("/health")
        except Exception as exc:  # pragma: no cover
            return CheckResult("Response headers", False, f"Request failed: {exc}")

        sha = resp.headers.get("X-Dragonfly-SHA-Short", "")
        env_header = resp.headers.get("X-Dragonfly-Env", "")
        sha_ok = bool(sha) and sha.lower() != "unknown"
        env_ok = env_header.lower() == self.env

        passed = sha_ok and env_ok
        detail = f"sha={sha or 'missing'}, env={env_header or 'missing'}"
        return CheckResult("Response headers", passed, detail)

    def _ops_get(self, key: str, auth: str | None = None) -> httpx.Response:
        url = f"{self.supabase_url}/rest/v1/{OPS_TABLE}?select=id&limit=1"
        headers = self._rest_headers(key, profile=OPS_SCHEMA, auth=auth)
        with httpx.Client(timeout=TIMEOUT) as client:
            return client.get(url, headers=headers)

    def check_ops_schema_blocked(self, role: str) -> CheckResult:
        auth_header = None
        if role == "auth":
            auth_header = "Bearer fake-user-jwt"
        try:
            resp = self._ops_get(self.anon_key, auth=auth_header)
            status = resp.status_code
            is_blocked = status in BLOCKED_STATUSES or (status == 200 and resp.json() == [])
            if is_blocked:
                return CheckResult(f"ops schema blocked ({role})", True, f"status={status}")
            return CheckResult(
                f"ops schema blocked ({role})",
                False,
                f"Unexpected access (status={status})",
            )
        except Exception as exc:  # pragma: no cover
            return CheckResult(f"ops schema blocked ({role})", False, f"Request failed: {exc}")

    def check_ops_rpc(self) -> CheckResult:
        url = f"{self.supabase_url}/rest/v1/rpc/get_system_health"
        headers = self._rest_headers(
            self.service_key, profile=OPS_SCHEMA, auth=f"Bearer {self.service_key}"
        )
        payload = {"p_limit": 5}
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return CheckResult("ops.get_system_health", True, "RPC succeeded")
            return CheckResult(
                "ops.get_system_health",
                False,
                f"RPC failed (status={resp.status_code})",
            )
        except Exception as exc:  # pragma: no cover
            return CheckResult("ops.get_system_health", False, f"Request failed: {exc}")

    def check_ingest_idempotency(self) -> CheckResult:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:  # pragma: no cover - psycopg missing in env
            return CheckResult("ingest idempotency", False, f"psycopg missing: {exc}")

        source_batch_id = f"certify_{uuid.uuid4().hex[:12]}"
        file_hash = hashlib.sha256(source_batch_id.encode()).hexdigest()

        try:
            with psycopg.connect(self.db_url, autocommit=True) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "DELETE FROM ingest.import_runs WHERE source_batch_id = %s",
                        (source_batch_id,),
                    )
                    cur.execute(
                        """
                        INSERT INTO ingest.import_runs (
                            source_batch_id, file_hash, status, record_count,
                            started_at, completed_at
                        ) VALUES (%s, %s, 'completed', 0, NOW(), NOW())
                        ON CONFLICT (source_batch_id) DO NOTHING
                        RETURNING id
                        """,
                        (source_batch_id, file_hash),
                    )
                    row = cur.fetchone()
                    first_id = str(row["id"]) if row else ""

                    cur.execute(
                        """
                        INSERT INTO ingest.import_runs (
                            source_batch_id, file_hash, status, record_count,
                            started_at, completed_at
                        ) VALUES (%s, %s, 'completed', 0, NOW(), NOW())
                        ON CONFLICT (source_batch_id) DO NOTHING
                        RETURNING id
                        """,
                        (source_batch_id, file_hash),
                    )
                    duplicate_row = cur.fetchone()

                with conn.cursor() as cleanup:
                    cleanup.execute(
                        "DELETE FROM ingest.import_runs WHERE source_batch_id = %s",
                        (source_batch_id,),
                    )

            skipped = duplicate_row is None
            detail = f"run_id={first_id or 'existing'}, duplicate_skipped={skipped}"
            return CheckResult("ingest idempotency", skipped, detail)
        except Exception as exc:  # pragma: no cover
            return CheckResult("ingest idempotency", False, f"DB error: {exc}")

    def run(self) -> List[CheckResult]:
        return [
            self.check_health(),
            self.check_readyz(),
            self.check_headers(),
            self.check_ops_schema_blocked("anon"),
            self.check_ops_schema_blocked("auth"),
            self.check_ops_rpc(),
            self.check_ingest_idempotency(),
        ]


def _print_report(results: List[CheckResult]) -> bool:
    print("\n" + "=" * 72)
    print("  DRAGONFLY PRODUCTION CERTIFICATION")
    print("=" * 72)
    all_passed = True
    for result in results:
        icon = "✅" if result.passed else "❌"
        print(f"{icon} {result.name} :: {result.detail}")
        if not result.passed:
            all_passed = False
    print("=" * 72)
    status = "GO FOR PLAINTIFFS" if all_passed else "NOT CERTIFIED"
    print(f"  Status: {status}")
    print("=" * 72 + "\n")
    return all_passed


def _print_dry_run(url: str, env: str) -> None:
    print("\n=== DRY RUN: CERTIFICATION PLAN ===")
    print(f"Target URL: {url}")
    print(f"Environment: {env}")
    print("Tests:")
    print("  - /health -> 200")
    print("  - /readyz -> 200")
    print("  - Headers X-Dragonfly-SHA-Short + X-Dragonfly-Env")
    print("  - Ops schema blocked for anon/auth")
    print("  - ops.get_system_health RPC via service_role")
    print("  - ingest.import_runs duplicate guard")
    print("No network or database calls were executed.\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dragonfly production certification")
    parser.add_argument("--url", required=True, help="Base API URL (e.g., https://api.example.com)")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="prod",
        help="Target environment (default: prod)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intended checks without touching the deployment",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.dry_run:
        _print_dry_run(args.url, args.env)
        return 0

    os.environ["SUPABASE_MODE"] = args.env

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    missing = [
        name
        for name, value in (
            ("SUPABASE_URL", supabase_url),
            ("SUPABASE_ANON_KEY", anon_key),
            ("SUPABASE_SERVICE_ROLE_KEY", service_key),
        )
        if not value
    ]
    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}")
        return 1

    try:
        db_url = get_supabase_db_url()
    except Exception as exc:  # pragma: no cover - surfaced to operator
        print(f"❌ Unable to resolve SUPABASE_DB_URL: {exc}")
        return 1

    certifier = ProdCertifier(
        base_url=args.url,
        env=args.env,
        supabase_url=supabase_url,
        anon_key=anon_key,
        service_key=service_key,
        db_url=db_url,
    )

    print(f"\nCertifying {args.url} ({args.env}) @ {datetime.utcnow().isoformat()}Z\n")

    results = certifier.run()
    passed = _print_report(results)
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main())
