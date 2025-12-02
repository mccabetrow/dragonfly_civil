#!/usr/bin/env python3
"""Smoke test for call queue sync functionality.

Verifies:
1. Can read from v_plaintiff_call_queue view
2. Can call upsert_plaintiff_task RPC
3. Idempotency: re-running doesn't create duplicates
4. One plaintiff → one call task

Usage:
    python -m tools.call_queue_smoke --env dev
    python -m tools.call_queue_smoke --env prod --verbose
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Smoke test for call queue sync")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    return parser.parse_args()


def smoke_test() -> int:
    """Run smoke tests. Returns 0 on success, 1 on failure."""
    logger = logging.getLogger(__name__)
    failures = []

    from src.supabase_client import create_supabase_client

    client = create_supabase_client()
    env = os.environ.get("SUPABASE_MODE", "dev")

    logger.info("=" * 60)
    logger.info("CALL QUEUE SYNC SMOKE TEST - %s", env.upper())
    logger.info("=" * 60)

    # Test 1: Read from v_plaintiff_call_queue view
    logger.info("")
    logger.info("TEST 1: Read v_plaintiff_call_queue view")
    logger.info("-" * 40)
    try:
        response = (
            client.table("v_plaintiff_call_queue")
            .select("plaintiff_id, plaintiff_name, status, task_status, due_at")
            .limit(5)
            .execute()
        )
        rows = response.data or []
        logger.info("✓ View accessible, found %d rows", len(rows))
        for row in rows[:3]:
            logger.info(
                "  - %s: status=%s task_status=%s",
                row.get("plaintiff_name", row["plaintiff_id"][:8]),
                row.get("status"),
                row.get("task_status"),
            )
        if len(rows) > 3:
            logger.info("  ... and %d more", len(rows) - 3)
    except Exception as e:
        logger.error("✗ View read failed: %s", e)
        failures.append(("v_plaintiff_call_queue read", str(e)))

    # Test 2: Verify plaintiffs table is readable
    logger.info("")
    logger.info("TEST 2: Read plaintiffs table")
    logger.info("-" * 40)
    test_plaintiff_id = None
    try:
        response = (
            client.table("plaintiffs").select("id, name, status").limit(1).execute()
        )
        if response.data:
            test_plaintiff_id = response.data[0]["id"]
            logger.info(
                "✓ Found test plaintiff: %s (status=%s)",
                response.data[0].get("name", test_plaintiff_id[:8]),
                response.data[0].get("status"),
            )
        else:
            logger.warning("⚠ No plaintiffs found in database")
    except Exception as e:
        logger.error("✗ Plaintiffs read failed: %s", e)
        failures.append(("plaintiffs read", str(e)))

    # Test 3: Test upsert_plaintiff_task RPC (idempotency)
    if test_plaintiff_id:
        logger.info("")
        logger.info("TEST 3: upsert_plaintiff_task RPC (idempotency)")
        logger.info("-" * 40)

        try:
            # First call
            rpc_params = {
                "p_plaintiff_id": test_plaintiff_id,
                "p_kind": "call",
                "p_due_at": datetime.now(timezone.utc).isoformat(),
                "p_metadata": {"smoke_test": True},
                "p_created_by": "call_queue_smoke",
            }

            response1 = client.rpc("upsert_plaintiff_task", rpc_params).execute()
            result1 = response1.data

            if result1 and result1.get("success"):
                task_id_1 = result1.get("task_id")
                is_new_1 = result1.get("is_new")
                logger.info(
                    "✓ First upsert: task_id=%s is_new=%s",
                    task_id_1,
                    is_new_1,
                )

                # Second call (should return same task)
                response2 = client.rpc("upsert_plaintiff_task", rpc_params).execute()
                result2 = response2.data

                if result2 and result2.get("success"):
                    task_id_2 = result2.get("task_id")
                    is_new_2 = result2.get("is_new")

                    if task_id_1 == task_id_2:
                        logger.info(
                            "✓ Idempotent: same task_id=%s is_new=%s",
                            task_id_2,
                            is_new_2,
                        )
                    else:
                        logger.error(
                            "✗ NOT idempotent: got different task_id %s vs %s",
                            task_id_1,
                            task_id_2,
                        )
                        failures.append(("idempotency", f"{task_id_1} != {task_id_2}"))
                else:
                    logger.error("✗ Second upsert failed: %s", result2)
                    failures.append(("upsert 2", str(result2)))
            else:
                logger.error("✗ First upsert failed: %s", result1)
                failures.append(("upsert 1", str(result1)))

        except Exception as e:
            logger.error("✗ RPC call failed: %s", e)
            failures.append(("upsert_plaintiff_task RPC", str(e)))

    # Test 4: Verify plaintiff_tasks table structure
    logger.info("")
    logger.info("TEST 4: Read plaintiff_tasks table")
    logger.info("-" * 40)
    try:
        response = (
            client.table("plaintiff_tasks")
            .select("id, plaintiff_id, kind, status, due_at")
            .eq("kind", "call")
            .limit(5)
            .execute()
        )
        rows = response.data or []
        logger.info("✓ plaintiff_tasks accessible, %d call tasks found", len(rows))
        for row in rows[:3]:
            logger.info(
                "  - task_id=%s status=%s due=%s",
                row["id"][:8],
                row.get("status"),
                row.get("due_at"),
            )
    except Exception as e:
        logger.error("✗ plaintiff_tasks read failed: %s", e)
        failures.append(("plaintiff_tasks read", str(e)))

    # Test 5: Test handler import and sync function
    logger.info("")
    logger.info("TEST 5: Handler module import")
    logger.info("-" * 40)
    try:
        from workers.call_queue_sync_handler import (
            handle_call_queue_sync,
            sync_all_call_tasks,
            fetch_plaintiffs_needing_calls,
            upsert_call_task,
        )

        logger.info("✓ Handler module imports successfully")

        # Quick test of fetch function
        plaintiffs = fetch_plaintiffs_needing_calls(client)
        logger.info(
            "✓ fetch_plaintiffs_needing_calls returned %d plaintiffs", len(plaintiffs)
        )

    except Exception as e:
        logger.error("✗ Handler import failed: %s", e)
        failures.append(("handler import", str(e)))

    # Summary
    logger.info("")
    logger.info("=" * 60)
    if failures:
        logger.error("SMOKE TEST FAILED - %d failures:", len(failures))
        for name, error in failures:
            logger.error("  - %s: %s", name, error)
        return 1
    else:
        logger.info("✓ ALL SMOKE TESTS PASSED")
        return 0


def main() -> int:
    """Main entry point."""
    args = parse_args()
    setup_logging(args.verbose)

    os.environ["SUPABASE_MODE"] = args.env

    return smoke_test()


if __name__ == "__main__":
    sys.exit(main())
