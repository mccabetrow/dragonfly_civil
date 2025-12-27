"""Smoke test for the enforcement action worker.

This script validates the enforcement action pipeline end-to-end:
1. Creates a test judgment in core_judgments (or uses existing)
2. Creates mock debtor intelligence
3. Queues an enforcement_action job
4. Optionally runs the worker to process it
5. Verifies enforcement_actions were created

Usage::

    # Dry run - just queue the job
    python -m tools.smoke_enforcement_action --env dev

    # Process the job immediately
    python -m tools.smoke_enforcement_action --env dev --process

    # Verbose output
    python -m tools.smoke_enforcement_action --env dev --process --verbose

    # Use existing judgment
    python -m tools.smoke_enforcement_action --env dev --judgment-id <uuid>

"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test the enforcement action worker pipeline.",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Supabase environment (default: dev).",
    )
    parser.add_argument(
        "--judgment-id",
        type=str,
        default=None,
        help="Use existing judgment UUID instead of creating one.",
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="Also run the worker to process the queued job.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete test data after verification.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    from src.supabase_client import create_supabase_client, get_supabase_env

    env = get_supabase_env()
    client = create_supabase_client()

    print(f"\n{'=' * 60}")
    print("  ENFORCEMENT ACTION SMOKE TEST")
    print(f"  Environment: {env}")
    print(f"{'=' * 60}\n")

    test_case_index = f"SMOKE-EA-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    judgment_id = args.judgment_id
    created_judgment = False
    created_intelligence = False

    try:
        # Step 1: Get or create judgment
        if judgment_id:
            print(f"[1/5] Using existing judgment: {judgment_id}")
            response = (
                client.table("core_judgments")
                .select("id, case_index_number, debtor_name, status")
                .eq("id", judgment_id)
                .execute()
            )
            if not response.data:
                print(f"  [FAIL] Judgment {judgment_id} not found")
                return 1
            judgment = response.data[0]
            print(
                f"  [OK] Found: {judgment.get('case_index_number')} - {judgment.get('debtor_name')}"
            )
        else:
            print(f"[1/5] Creating test judgment: {test_case_index}")
            judgment_data = {
                "case_index_number": test_case_index,
                "debtor_name": "Smoke Test Debtor",
                "principal_amount": 15000.00,
                "judgment_date": "2024-06-15",
                "court_name": "Smoke Test Court",
                "county": "Test County",
                "status": "unsatisfied",
                "collectability_score": 75,
            }
            response = client.table("core_judgments").insert(judgment_data).execute()
            if not response.data:
                print("  [FAIL] Could not create judgment")
                return 1
            judgment = response.data[0]
            judgment_id = judgment["id"]
            created_judgment = True
            print(f"  [OK] Created judgment: {judgment_id}")

        # Step 2: Create or verify debtor intelligence
        print("[2/5] Checking debtor intelligence for judgment...")
        intel_response = (
            client.table("debtor_intelligence")
            .select("id, employer_name, bank_name, income_band, confidence_score")
            .eq("judgment_id", judgment_id)
            .execute()
        )

        if intel_response.data:
            intel = intel_response.data[0]
            print(
                f"  [OK] Found existing intelligence: employer={intel.get('employer_name')}, bank={intel.get('bank_name')}"
            )
        else:
            print("  [INFO] No intelligence found, creating mock data...")
            # Use the RPC to create intelligence
            try:
                rpc_response = client.rpc(
                    "upsert_debtor_intelligence",
                    {
                        "_judgment_id": judgment_id,
                        "_data_source": "smoke_test",
                        "_employer_name": "Acme Corp",
                        "_employer_address": "123 Test Street, NY 10001",
                        "_income_band": "MED",
                        "_bank_name": "Test National Bank",
                        "_bank_address": "456 Bank Ave, NY 10002",
                        "_home_ownership": "renter",
                        "_has_benefits_only": False,
                        "_confidence_score": 80.0,
                        "_is_verified": False,
                    },
                ).execute()
                intel_id = rpc_response.data
                created_intelligence = True
                print(f"  [OK] Created intelligence: {intel_id}")
            except Exception as e:
                print(f"  [WARN] Could not create intelligence via RPC: {e}")
                print("  [INFO] Proceeding without intelligence (will trigger asset search)")

        # Step 3: Check existing enforcement actions
        print("[3/5] Checking existing enforcement actions...")
        actions_response = (
            client.table("enforcement_actions")
            .select("id, action_type, status, created_at")
            .eq("judgment_id", judgment_id)
            .execute()
        )
        existing_actions = actions_response.data or []
        if existing_actions:
            print(f"  [INFO] Found {len(existing_actions)} existing action(s):")
            for action in existing_actions:
                print(f"    - {action.get('action_type')}: {action.get('status')}")
        else:
            print("  [OK] No existing actions (clean slate)")

        # Step 4: Queue the enforcement_action job
        print("[4/5] Queueing enforcement_action job...")
        idempotency_key = f"smoke_enforcement_action:{judgment_id}:{uuid.uuid4().hex[:8]}"

        try:
            queue_response = client.rpc(
                "queue_job",
                {
                    "payload": {
                        "kind": "enforcement_action",
                        "idempotency_key": idempotency_key,
                        "payload": {"judgment_id": judgment_id},
                    }
                },
            ).execute()
            msg_id = queue_response.data
            print(f"  [OK] Queued job: msg_id={msg_id}, idempotency_key={idempotency_key}")
        except Exception as e:
            error_msg = str(e)
            if "unsupported kind" in error_msg.lower():
                print("  [FAIL] Queue RPC doesn't recognize 'enforcement_action' kind")
                print("  [INFO] Run migration 0209_add_enforcement_action_queue_kind.sql first")
                return 1
            raise

        # Step 5: Optionally process the job
        if args.process:
            print("[5/5] Processing queued job...")
            from workers.enforcement_action_handler import handle_enforcement_action
            from workers.queue_client import QueueClient

            with QueueClient() as qc:
                job = qc.dequeue("enforcement_action")
                if not job:
                    print("  [WARN] No job found in queue (may have been processed)")
                else:
                    job_msg_id = job.get("msg_id")
                    print(f"  [INFO] Dequeued job: {job_msg_id}")
                    try:
                        asyncio.run(handle_enforcement_action(job))
                        qc.ack("enforcement_action", job_msg_id)
                        print("  [OK] Job processed and acknowledged")
                    except Exception as e:
                        print(f"  [FAIL] Job processing failed: {e}")
                        return 1

            # Verify actions were created
            print("\n[VERIFICATION] Checking enforcement actions created...")
            final_response = (
                client.table("enforcement_actions")
                .select("id, action_type, status, notes, requires_attorney_signature, created_at")
                .eq("judgment_id", judgment_id)
                .order("created_at", desc=False)
                .execute()
            )
            final_actions = final_response.data or []
            new_count = len(final_actions) - len(existing_actions)

            if new_count > 0:
                print(f"  [OK] {new_count} new action(s) created:")
                for action in final_actions:
                    sig_marker = "[ATTY]" if action.get("requires_attorney_signature") else ""
                    print(f"    - {action.get('action_type')}: {action.get('status')} {sig_marker}")
                    if action.get("notes"):
                        print(f"      Notes: {action.get('notes')[:80]}...")
            else:
                print("  [WARN] No new actions created (may already exist)")
        else:
            print("[5/5] Skipping processing (use --process to run worker)")
            print("  [INFO] Job queued. Run worker manually:")
            print(f"         python -m tools.enforcement_action_worker --env {env} --once")

        # Cleanup if requested
        if args.cleanup and (created_judgment or created_intelligence):
            print("\n[CLEANUP] Removing test data...")
            if created_judgment:
                client.table("core_judgments").delete().eq("id", judgment_id).execute()
                print(f"  [OK] Deleted judgment {judgment_id}")

        print(f"\n{'=' * 60}")
        print("  SMOKE TEST COMPLETE")
        print(f"{'=' * 60}\n")
        return 0

    except Exception as e:
        logger.exception("Smoke test failed")
        print(f"\n[FAIL] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
