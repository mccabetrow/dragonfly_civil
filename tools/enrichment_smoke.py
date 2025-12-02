"""End-to-end smoke test for the judgment enrichment pipeline.

This test validates the complete enrichment flow:
1. Inserts a test judgment into core_judgments (triggers auto-enqueue)
2. Processes the enqueued job via the handler
3. Verifies:
   - debtor_intelligence has a row for the judgment
   - external_data_calls has an FCRA audit row
   - core_judgments has a non-null collectability_score
4. Cleans up test data (unless --skip-cleanup)

Usage::

    python -m tools.enrichment_smoke --env dev
    python -m tools.enrichment_smoke --env dev --skip-cleanup --verbose

Exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from typing import Optional, Sequence

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run end-to-end smoke test for judgment enrichment.",
        epilog="Set SUPABASE_MODE=dev|prod or use --env to target an environment.",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Supabase environment to target (default: dev).",
    )
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Leave test data in place after the test.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


async def run_smoke_test(skip_cleanup: bool = False) -> bool:
    """Execute the enrichment smoke test.

    Returns True on success, False on failure.
    """
    from src.supabase_client import create_supabase_client, get_supabase_env
    from workers.judgment_enrich_handler import handle_judgment_enrich

    env = get_supabase_env()
    client = create_supabase_client(env)
    test_case_index = f"SMOKE-TEST-{uuid.uuid4().hex[:8].upper()}"
    judgment_id: Optional[str] = None
    test_passed = False

    logger.info("=== Enrichment Smoke Test (env=%s) ===", env)

    try:
        # Step 1: Insert a test judgment (trigger auto-enqueues enrichment job)
        logger.info("Step 1: Inserting test judgment (case_index=%s)", test_case_index)
        response = (
            client.table("core_judgments")
            .insert(
                {
                    "case_index_number": test_case_index,
                    "debtor_name": "John Smoke Doe",
                    "original_creditor": "Smoke Test Creditor",
                    "principal_amount": 1000.00,
                    "court_name": "Smoke Test Court",
                    "county": "Test County",
                    "status": "unsatisfied",
                }
            )
            .execute()
        )
        if not response.data:
            logger.error("Failed to insert test judgment")
            return False
        judgment_id = response.data[0]["id"]
        logger.info("  Inserted judgment: %s", judgment_id)

        # Step 2: Process the job via handler (job was auto-enqueued by trigger)
        logger.info("Step 2: Processing enrichment job via handler")
        result = await handle_judgment_enrich({"judgment_id": judgment_id})
        if not result:
            logger.error("  FAIL: Handler returned False")
            return False
        logger.info("  Handler completed successfully")

        # Step 3: Verify results
        logger.info("Step 3: Verifying enrichment results")
        failures = []

        # Check 3a: debtor_intelligence row exists
        intel_resp = (
            client.table("debtor_intelligence")
            .select(
                "id, judgment_id, data_source, employer_name, bank_name, confidence_score"
            )
            .eq("judgment_id", judgment_id)
            .execute()
        )
        if not intel_resp.data:
            failures.append("No debtor_intelligence record found")
        else:
            intel = intel_resp.data[0]
            logger.info(
                "  ✓ debtor_intelligence: id=%s, employer=%s, bank=%s, confidence=%s",
                intel.get("id"),
                intel.get("employer_name"),
                intel.get("bank_name"),
                intel.get("confidence_score"),
            )

        # Check 3b: external_data_calls (FCRA audit) row exists
        fcra_resp = (
            client.table("external_data_calls")
            .select("id, judgment_id, provider, status, http_code")
            .eq("judgment_id", judgment_id)
            .execute()
        )
        if not fcra_resp.data:
            failures.append("No external_data_calls (FCRA audit) record found")
        else:
            fcra = fcra_resp.data[0]
            logger.info(
                "  ✓ external_data_calls: id=%s, provider=%s, status=%s, http_code=%s",
                fcra.get("id"),
                fcra.get("provider"),
                fcra.get("status"),
                fcra.get("http_code"),
            )

        # Check 3c: core_judgments collectability_score updated
        judgment_resp = (
            client.table("core_judgments")
            .select("collectability_score, status")
            .eq("id", judgment_id)
            .execute()
        )
        if judgment_resp.data:
            judgment = judgment_resp.data[0]
            score = judgment.get("collectability_score")
            status = judgment.get("status")
            if score is None:
                failures.append("collectability_score not updated (is NULL)")
            else:
                logger.info("  ✓ collectability_score: %s, status: %s", score, status)
        else:
            failures.append("Judgment not found after enrichment")

        # Report results
        if failures:
            for failure in failures:
                logger.error("  FAIL: %s", failure)
            return False

        logger.info("=== SMOKE TEST PASSED ===")
        test_passed = True
        return True

    except Exception as exc:
        logger.exception("Smoke test failed with exception: %s", exc)
        return False

    finally:
        # Step 4: Cleanup (unless --skip-cleanup or test failed and we want to inspect)
        if judgment_id and not skip_cleanup:
            logger.info("Step 4: Cleaning up test data")
            try:
                # Delete in reverse dependency order
                client.table("external_data_calls").delete().eq(
                    "judgment_id", judgment_id
                ).execute()
                client.table("debtor_intelligence").delete().eq(
                    "judgment_id", judgment_id
                ).execute()
                client.table("core_judgments").delete().eq("id", judgment_id).execute()
                logger.info("  Cleanup complete")
            except Exception as cleanup_exc:
                logger.warning(
                    "  Cleanup failed (may require manual cleanup): %s", cleanup_exc
                )
        elif skip_cleanup and judgment_id:
            logger.info(
                "Skipping cleanup (--skip-cleanup). Test judgment: %s", judgment_id
            )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    # Set environment before imports
    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    success = asyncio.run(run_smoke_test(skip_cleanup=args.skip_cleanup))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
