"""Smoke test for tier assignment pipeline.

Creates a test judgment, queues a tier_assignment job, processes it,
and verifies the tier was computed correctly.

Usage:
    python -m tools.smoke_tier_assignment --env dev [--verbose] [--judgment-id UUID]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.supabase_client import create_supabase_client
from workers.tier_assignment_handler import handle_tier_assignment

logger = logging.getLogger(__name__)


def configure_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def create_test_judgment(client, judgment_id: str | None = None) -> dict:
    """Create a test judgment with known collectability data."""
    test_id = judgment_id or str(uuid.uuid4())

    # Create a judgment with score 65 and $25k balance -> should be Tier 2
    judgment_data = {
        "id": test_id,
        "case_index_number": f"TIER-TEST-{test_id[:8].upper()}",
        "court_name": "Test Court",
        "county": "Test County",
        "original_creditor": "Test Plaintiff LLC",
        "debtor_name": "Test Defendant",
        "principal_amount": 25000,
        "collectability_score": 65,
        "status": "unsatisfied",
    }

    try:
        response = client.table("core_judgments").upsert(judgment_data).execute()
        logger.info("Created/updated test judgment id=%s", test_id)
        return response.data[0] if response.data else judgment_data
    except Exception as e:
        logger.error("Failed to create test judgment: %s", e)
        raise


def create_test_intelligence(client, judgment_id: str) -> dict:
    """Create debtor intelligence with employer and bank."""
    intel_data = {
        "judgment_id": judgment_id,
        "employer_name": "Acme Corporation",
        "bank_name": "Chase Bank",
        "data_source": "smoke_test",
        "is_verified": True,
    }

    try:
        # Delete existing intelligence first
        client.table("debtor_intelligence").delete().eq("judgment_id", judgment_id).execute()

        response = client.table("debtor_intelligence").insert(intel_data).execute()
        logger.info("Created debtor intelligence for judgment_id=%s", judgment_id)
        return response.data[0] if response.data else intel_data
    except Exception as e:
        logger.error("Failed to create intelligence: %s", e)
        raise


def queue_tier_job(client, judgment_id: str) -> int:
    """Queue a tier_assignment job via RPC."""
    payload = {
        "kind": "tier_assignment",
        "idempotency_key": f"tier:smoke:{judgment_id}",
        "payload": {"judgment_id": judgment_id},
    }

    try:
        response = client.rpc("queue_job", {"payload": payload}).execute()
        msg_id = response.data
        logger.info("Queued tier_assignment job msg_id=%s", msg_id)
        return msg_id
    except Exception as e:
        logger.error("Failed to queue job: %s", e)
        raise


def dequeue_tier_job(client) -> dict | None:
    """Dequeue a tier_assignment job."""
    try:
        response = client.rpc("dequeue_job", {"kind": "tier_assignment"}).execute()
        return response.data
    except Exception as e:
        logger.error("Failed to dequeue job: %s", e)
        return None


def ack_job(client, msg_id: int):
    """Acknowledge a processed job by deleting from queue."""
    try:
        client.rpc("pgmq_delete", {"queue_name": "tier_assignment", "msg_id": msg_id}).execute()
        logger.info("Acknowledged job msg_id=%s", msg_id)
    except Exception as e:
        logger.warning("Failed to ack job: %s", e)


def verify_tier_assignment(client, judgment_id: str) -> dict | None:
    """Fetch the judgment and verify tier was assigned."""
    response = (
        client.table("core_judgments")
        .select("id, tier, tier_reason, tier_as_of, collectability_score, principal_amount")
        .eq("id", judgment_id)
        .execute()
    )

    if response.data:
        return response.data[0]
    return None


def check_tier_overview(client):
    """Check the v_enforcement_tier_overview view."""
    try:
        response = client.table("v_enforcement_tier_overview").select("*").execute()
        if response.data:
            logger.info("Tier overview:")
            for row in response.data:
                tier = row.get("tier")
                label = row.get("tier_label", "Unknown")
                count = row.get("judgment_count", 0)
                total = row.get("total_principal", 0)
                logger.info(
                    "  Tier %s (%s): %d judgments, $%s total",
                    tier,
                    label,
                    count,
                    f"{total:,.0f}" if total else "0",
                )
        return response.data
    except Exception as e:
        logger.warning("Could not read tier overview: %s", e)
        return None


async def run_smoke_test(judgment_id: str | None = None, verbose: bool = False):
    """Run the full tier assignment smoke test."""
    client = create_supabase_client()

    print("\n=== Tier Assignment Smoke Test ===\n")

    # 1. Create test judgment (or use existing)
    if judgment_id:
        print(f"[1/5] Using existing judgment: {judgment_id}")
        judgment = verify_tier_assignment(client, judgment_id)
        if not judgment:
            print(f"  ERROR: Judgment {judgment_id} not found")
            return False
    else:
        print("[1/5] Creating test judgment...")
        judgment = create_test_judgment(client)
        judgment_id = judgment["id"]
        print(f"  Created judgment {judgment_id}")
        print(
            f"  Score: {judgment.get('collectability_score')}, Balance: ${judgment.get('principal_amount', 0):,}"
        )

    # 2. Create intelligence
    print("\n[2/5] Creating debtor intelligence...")
    intel = create_test_intelligence(client, judgment_id)
    print(f"  Employer: {intel.get('employer_name')}")
    print(f"  Bank: {intel.get('bank_name')}")

    # 3. Queue tier job
    print("\n[3/5] Queuing tier_assignment job...")
    msg_id = queue_tier_job(client, judgment_id)
    print(f"  Queued job msg_id={msg_id}")

    # 4. Process jobs until we find ours or queue is empty
    print("\n[4/5] Processing tier jobs...")
    processed_target = False
    max_jobs = 10  # Safety limit

    for i in range(max_jobs):
        job = dequeue_tier_job(client)
        if not job:
            print(f"  Queue empty after processing {i} jobs")
            break

        job_msg_id = job.get("msg_id")
        job_judgment_id = None

        # Extract judgment_id from nested payload
        payload = job.get("payload", {})
        if isinstance(payload, dict):
            nested = payload.get("payload", {})
            if isinstance(nested, dict):
                job_judgment_id = nested.get("judgment_id")
            else:
                job_judgment_id = payload.get("judgment_id")

        print(f"  Processing job msg_id={job_msg_id} judgment_id={job_judgment_id}")

        success = await handle_tier_assignment(job)
        if success:
            ack_job(client, job_msg_id)

        if job_judgment_id == judgment_id:
            processed_target = True
            print("  Found and processed target job!")
            break

    if not processed_target:
        print("  WARNING: Target job not found in queue, checking tier anyway")

    # 5. Verify tier assignment
    print("\n[5/5] Verifying tier assignment...")
    result = verify_tier_assignment(client, judgment_id)
    if result:
        tier = result.get("tier")
        reason = result.get("tier_reason")
        tier_as_of = result.get("tier_as_of")

        print(f"  Tier: {tier}")
        print(f"  Reason: {reason}")
        print(f"  As of: {tier_as_of}")

        # Validate expected tier (score 65, balance $25k, 2 assets = Tier 2)
        expected_tier = 2
        if tier == expected_tier:
            print(f"\n✓ PASS: Tier {tier} matches expected Tier {expected_tier}")
        else:
            print(f"\n✗ FAIL: Got Tier {tier}, expected Tier {expected_tier}")
            return False
    else:
        print("  ERROR: Could not fetch judgment")
        return False

    # Bonus: Show tier overview
    print("\n--- Tier Overview ---")
    check_tier_overview(client)

    return True


def main():
    parser = argparse.ArgumentParser(description="Smoke test for tier assignment")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--judgment-id", help="Use existing judgment ID")

    args = parser.parse_args()

    os.environ["SUPABASE_MODE"] = args.env

    configure_logging(args.verbose)

    print(f"Environment: {args.env}")

    success = asyncio.run(run_smoke_test(args.judgment_id, args.verbose))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
