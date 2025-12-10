"""End-to-end smoke test for the import → enrichment pipeline.

This test validates the complete flow when --enable-new-pipeline is used:
1. Runs the JBI importer with a small fixture CSV
2. Verifies legacy tables (plaintiffs, judgments) were populated
3. Verifies core_judgments has rows inserted via bridge
4. Runs the enrichment worker once to process enqueued jobs
5. Verifies debtor_intelligence, external_data_calls, and collectability_score

Usage::

    python -m tools.import_900_smoke --env dev
    python -m tools.import_900_smoke --env dev --skip-cleanup --verbose

Exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run end-to-end smoke test for import + enrichment pipeline.",
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


def _create_fixture_csv(test_id: str) -> Path:
    """Create a small fixture CSV for testing."""
    # Create temp file that won't be deleted automatically
    fd, path = tempfile.mkstemp(suffix=".csv", prefix=f"smoke_test_{test_id}_")
    csv_path = Path(path)

    # JBI 900 format CSV
    rows = [
        {
            "case_number": f"SMOKE-{test_id}-001",
            "party_name": "Smoke Test Creditor",
            "party_role": "Plaintiff",
            "judgment_amount": "1000.00",
            "judgment_date": "2024-01-15",
            "court_name": "Smoke Test Court",
            "county": "Test County",
            "state": "NY",
        },
        {
            "case_number": f"SMOKE-{test_id}-002",
            "party_name": "Smoke Test Creditor 2",
            "party_role": "Plaintiff",
            "judgment_amount": "2500.50",
            "judgment_date": "2024-02-20",
            "court_name": "Smoke Test Court",
            "county": "Test County",
            "state": "NY",
        },
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    os.close(fd)
    return csv_path


async def run_import_enrichment_smoke(skip_cleanup: bool = False, verbose: bool = False) -> bool:
    """Execute the import + enrichment smoke test.

    Returns True on success, False on failure.
    """
    from etl.src.importers.jbi_900 import run_jbi_900_import
    from src.supabase_client import create_supabase_client, get_supabase_env
    from workers.judgment_enrich_handler import handle_judgment_enrich

    env = get_supabase_env()
    client = create_supabase_client(env)
    test_id = uuid.uuid4().hex[:8].upper()
    csv_path: Optional[Path] = None
    core_judgment_ids: List[str] = []
    legacy_judgment_ids: List[str] = []
    plaintiff_ids: List[str] = []
    test_passed = False

    logger.info("=== Import + Enrichment Smoke Test (env=%s, test_id=%s) ===", env, test_id)

    try:
        # Step 1: Create fixture CSV
        logger.info("Step 1: Creating fixture CSV")
        csv_path = _create_fixture_csv(test_id)
        logger.info("  Created: %s", csv_path)

        # Step 2: Run JBI importer with --enable-new-pipeline
        logger.info("Step 2: Running JBI importer with enable_new_pipeline=True")
        result = run_jbi_900_import(
            str(csv_path),
            batch_name=f"smoke-test-{test_id}",
            dry_run=False,
            source_reference=f"smoke-test-{test_id}",
            enqueue_jobs=False,  # We'll run enrichment manually
            enable_new_pipeline=True,
        )

        if result.get("error_count", 0) > 0:
            logger.error("  FAIL: Import had errors: %s", result)
            return False

        insert_count = result.get("insert_count", 0)
        logger.info("  Imported %d rows", insert_count)

        # Extract IDs for cleanup
        for op in result.get("metadata", {}).get("row_operations", []):
            if op.get("judgment_id"):
                legacy_judgment_ids.append(op["judgment_id"])
            if op.get("plaintiff_id"):
                plaintiff_ids.append(op["plaintiff_id"])
            if op.get("core_judgment_id"):
                core_judgment_ids.append(op["core_judgment_id"])

        # Step 3: Verify legacy tables populated
        logger.info("Step 3: Verifying legacy tables")
        failures: List[str] = []

        # Check plaintiffs
        plaintiffs_resp = (
            client.table("plaintiffs")
            .select("id, name")
            .ilike("name", "%Smoke Test Creditor%")
            .execute()
        )
        if not plaintiffs_resp.data:
            failures.append("No plaintiffs found")
        else:
            logger.info("  ✓ plaintiffs: %d rows", len(plaintiffs_resp.data))

        # Check legacy judgments
        judgments_resp = (
            client.table("judgments")
            .select("id, case_number")
            .ilike("case_number", f"%SMOKE-{test_id}%")
            .execute()
        )
        if not judgments_resp.data:
            failures.append("No legacy judgments found")
        else:
            logger.info("  ✓ judgments (legacy): %d rows", len(judgments_resp.data))

        # Step 4: Verify core_judgments populated via bridge
        logger.info("Step 4: Verifying core_judgments (new pipeline)")
        core_resp = (
            client.table("core_judgments")
            .select("id, case_index_number, debtor_name, collectability_score")
            .ilike("case_index_number", f"%SMOKE-{test_id}%")
            .execute()
        )
        if not core_resp.data:
            failures.append("No core_judgments found - bridge may have failed")
        else:
            logger.info("  ✓ core_judgments: %d rows", len(core_resp.data))
            # Store IDs for enrichment and cleanup
            for row in core_resp.data:
                if row["id"] not in core_judgment_ids:
                    core_judgment_ids.append(row["id"])

        # Step 5: Run enrichment handler for each core_judgment
        logger.info("Step 5: Running enrichment handler for core_judgments")
        if not core_judgment_ids:
            logger.warning("  SKIP: No core_judgment_ids to enrich")
        else:
            for cj_id in core_judgment_ids:
                job = {"judgment_id": cj_id}
                enrich_result = await handle_judgment_enrich(job)
                if not enrich_result:
                    failures.append(f"Enrichment failed for {cj_id}")
                else:
                    logger.info("  ✓ Enriched: %s", cj_id)

        # Step 6: Verify enrichment results
        logger.info("Step 6: Verifying enrichment results")

        # Check debtor_intelligence
        intel_resp = (
            client.table("debtor_intelligence")
            .select("id, judgment_id, data_source, confidence_score")
            .in_("judgment_id", core_judgment_ids)
            .execute()
        )
        if not intel_resp.data:
            failures.append("No debtor_intelligence records found")
        else:
            logger.info("  ✓ debtor_intelligence: %d rows", len(intel_resp.data))

        # Check external_data_calls (FCRA audit)
        fcra_resp = (
            client.table("external_data_calls")
            .select("id, judgment_id, provider, status")
            .in_("judgment_id", core_judgment_ids)
            .execute()
        )
        if not fcra_resp.data:
            failures.append("No external_data_calls (FCRA audit) records found")
        else:
            logger.info("  ✓ external_data_calls: %d rows", len(fcra_resp.data))

        # Check collectability_score updated
        updated_core_resp = (
            client.table("core_judgments")
            .select("id, collectability_score")
            .in_("id", core_judgment_ids)
            .execute()
        )
        scores_updated = sum(
            1 for r in updated_core_resp.data if r.get("collectability_score") is not None
        )
        if scores_updated == 0:
            failures.append("No collectability_score values set")
        else:
            logger.info(
                "  ✓ collectability_score: %d/%d updated",
                scores_updated,
                len(core_judgment_ids),
            )

        # Step 7: Summary
        logger.info("Step 7: Summary")
        if failures:
            logger.error("  FAILURES:")
            for f in failures:
                logger.error("    - %s", f)
            test_passed = False
        else:
            logger.info("  ✓ All checks passed!")
            test_passed = True

        return test_passed

    except Exception as e:
        logger.exception("Smoke test failed with exception: %s", e)
        return False

    finally:
        # Cleanup
        if not skip_cleanup:
            logger.info("Cleanup: Removing test data")
            try:
                # Clean up in reverse dependency order
                if core_judgment_ids:
                    # debtor_intelligence and external_data_calls have CASCADE on judgment_id
                    client.table("core_judgments").delete().in_("id", core_judgment_ids).execute()
                    logger.info("  Deleted %d core_judgments", len(core_judgment_ids))

                if legacy_judgment_ids:
                    client.table("judgments").delete().in_("id", legacy_judgment_ids).execute()
                    logger.info("  Deleted %d legacy judgments", len(legacy_judgment_ids))

                if plaintiff_ids:
                    # Need to delete status history first
                    client.table("plaintiff_status_history").delete().in_(
                        "plaintiff_id", plaintiff_ids
                    ).execute()
                    # Then contacts
                    client.table("plaintiff_contacts").delete().in_(
                        "plaintiff_id", plaintiff_ids
                    ).execute()
                    # Then plaintiffs
                    client.table("plaintiffs").delete().in_("id", plaintiff_ids).execute()
                    logger.info("  Deleted %d plaintiffs", len(plaintiff_ids))

            except Exception as cleanup_err:
                logger.warning("Cleanup error (non-fatal): %s", cleanup_err)

        # Clean up temp CSV
        if csv_path and csv_path.exists():
            try:
                csv_path.unlink()
                logger.info("  Deleted temp CSV")
            except Exception:
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    # Set environment
    os.environ["SUPABASE_MODE"] = args.env

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    success = asyncio.run(
        run_import_enrichment_smoke(
            skip_cleanup=args.skip_cleanup,
            verbose=args.verbose,
        )
    )

    if success:
        logger.info("=== SMOKE TEST PASSED ===")
        return 0
    else:
        logger.error("=== SMOKE TEST FAILED ===")
        return 1


if __name__ == "__main__":
    sys.exit(main())
