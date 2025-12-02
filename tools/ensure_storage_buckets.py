from __future__ import annotations

import argparse
import logging
from typing import Iterable

from src.supabase_client import SupabaseEnv, create_supabase_client, get_supabase_env

logger = logging.getLogger(__name__)

_DEFAULT_BUCKETS: tuple[tuple[str, bool], ...] = (
    ("imports", False),
    ("enforcement_evidence", False),
)


def _bucket_matrix(targets: Iterable[str] | None) -> list[tuple[str, bool]]:
    if targets:
        return [(name, False) for name in targets]
    return list(_DEFAULT_BUCKETS)


def ensure_storage_buckets(
    env: SupabaseEnv, bucket_names: Iterable[str] | None = None
) -> list[str]:
    client = create_supabase_client(env)
    existing = {
        bucket.name
        for bucket in client.storage.list_buckets()
        if getattr(bucket, "name", None)
    }

    created: list[str] = []
    for bucket_name, is_public in _bucket_matrix(bucket_names):
        if bucket_name in existing:
            logger.info("Bucket '%s' already exists in %s", bucket_name, env)
            continue
        logger.info("Creating bucket '%s' in %s", bucket_name, env)
        client.storage.create_bucket(bucket_name, options={"public": is_public})
        created.append(bucket_name)
    return created


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ensure Supabase storage buckets exist"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        help="Supabase environment to target",
    )
    parser.add_argument(
        "--bucket",
        dest="buckets",
        action="append",
        help="Explicit bucket names to ensure. Defaults to the canonical list.",
    )
    args = parser.parse_args()

    env = args.env or get_supabase_env()
    created = ensure_storage_buckets(env, bucket_names=args.buckets)
    if created:
        print(f"Created buckets: {', '.join(created)}")
    else:
        print("All buckets already present")


if __name__ == "__main__":
    main()
