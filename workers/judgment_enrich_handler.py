"""Judgment enrichment handler for PGMQ workers.

This handler processes judgment_enrich jobs from the PGMQ queue, performing:
1. Skip-trace enrichment via vendor (MockIdiCORE in dev, real vendor in prod)
2. FCRA audit logging via complete_enrichment RPC
3. Debtor intelligence upsert via complete_enrichment RPC
4. Judgment status and collectability score update via complete_enrichment RPC

All mutations are performed atomically through the complete_enrichment RPC,
ensuring FCRA compliance and data consistency.

Job Payload Format:
    {
        "judgment_id": "<uuid>"  # Required: core_judgments.id
    }

Queue Kind: judgment_enrich
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from src.supabase_client import create_supabase_client
from src.vendors import MockIdiCORE, SkipTraceResult, SkipTraceVendor

logger = logging.getLogger(__name__)

# Status value for actionable judgments after enrichment
# Must match judgment_status_enum in 0200_core_judgment_schema.sql
ACTIONABLE_STATUS = "unsatisfied"  # Judgments ready for enforcement remain unsatisfied

# Minimum collectability score threshold for enriched judgments
MIN_COLLECTABILITY_SCORE = 50


def _get_vendor() -> SkipTraceVendor:
    """Get the appropriate vendor based on environment.

    Returns MockIdiCORE for dev/test environments.
    TODO: Return IdiCOREClient for production when implemented.
    """
    env = os.getenv("SUPABASE_MODE", "dev").lower()

    if env in ("prod", "production"):
        # TODO: Return real vendor when implemented
        # from src.vendors.idicore import IdiCOREClient
        # return IdiCOREClient()
        logger.warning("Production vendor not implemented; using MockIdiCORE")
        return MockIdiCORE()

    return MockIdiCORE()


def _extract_judgment_id(job: Dict[str, Any]) -> Optional[str]:
    """Extract judgment_id from job payload.

    Handles nested payload structure from PGMQ.
    """
    if not isinstance(job, dict):
        return None

    # Try direct access first
    judgment_id = job.get("judgment_id")
    if judgment_id:
        return str(judgment_id).strip()

    # Check nested payload
    payload = job.get("payload")
    if isinstance(payload, dict):
        # Double-nested payload (from queue_job RPC)
        nested = payload.get("payload")
        if isinstance(nested, dict):
            judgment_id = nested.get("judgment_id")
            if judgment_id:
                return str(judgment_id).strip()

        # Single-nested payload
        judgment_id = payload.get("judgment_id")
        if judgment_id:
            return str(judgment_id).strip()

    return None


def _extract_idempotency_key(job: Dict[str, Any]) -> Optional[str]:
    """Extract idempotency key from job for logging."""
    if not isinstance(job, dict):
        return None

    key = job.get("idempotency_key")
    if key:
        return str(key)

    payload = job.get("payload")
    if isinstance(payload, dict):
        nested_key = payload.get("idempotency_key")
        if nested_key:
            return str(nested_key)

    return None


def _calculate_collectability_score(result: SkipTraceResult) -> int:
    """Calculate collectability score based on enrichment results.

    Score factors:
    - Base confidence from vendor
    - Bonus for employment data
    - Bonus for banking data
    - Penalty for benefits-only account
    - Bonus for home ownership
    """
    score = result.confidence_score

    # Bonus for employment data
    if result.employer_name:
        score += 10

    # Bonus for banking data
    if result.bank_name:
        score += 10

    # Penalty for benefits-only account (exempt from levy)
    if result.has_benefits_only_account:
        score -= 20

    # Bonus for home ownership (potential lien target)
    if result.home_ownership == "owner":
        score += 15

    # Income band adjustments
    if result.income_band == "HIGH":
        score += 10
    elif result.income_band == "MED":
        score += 5
    elif result.income_band == "LOW":
        score -= 5

    # Clamp to 0-100
    return max(0, min(100, score))


async def handle_judgment_enrich(job: Dict[str, Any]) -> bool:
    """Process a judgment enrichment job.

    Args:
        job: Job payload containing judgment_id.

    Returns:
        True if enrichment succeeded, False otherwise.
    """
    msg_id = job.get("msg_id") if isinstance(job, dict) else None
    idempotency_key = _extract_idempotency_key(job)

    # Handle health check jobs from doctor
    if isinstance(idempotency_key, str) and idempotency_key.startswith("doctor:"):
        logger.info(
            "judgment_enrich_healthcheck_ignored kind=judgment_enrich msg_id=%s idempotency_key=%s",
            msg_id,
            idempotency_key,
        )
        return True

    # Extract judgment_id
    judgment_id = _extract_judgment_id(job)
    if not judgment_id:
        logger.error(
            "judgment_enrich_missing_id kind=judgment_enrich msg_id=%s idempotency_key=%s job=%s",
            msg_id,
            idempotency_key,
            job,
        )
        return False

    logger.info(
        "judgment_enrich_start kind=judgment_enrich msg_id=%s judgment_id=%s",
        msg_id,
        judgment_id,
    )

    client = create_supabase_client()

    try:
        # 1. Fetch the judgment
        response = (
            client.table("core_judgments")
            .select("id, case_index_number, debtor_name, status, collectability_score")
            .eq("id", judgment_id)
            .execute()
        )

        if not response.data:
            logger.warning(
                "judgment_enrich_not_found kind=judgment_enrich msg_id=%s judgment_id=%s",
                msg_id,
                judgment_id,
            )
            return True  # Don't retry for missing judgments

        judgment = response.data[0]

        # 2. Guard: Check if already enriched (has debtor_intelligence row)
        intel_response = (
            client.table("debtor_intelligence")
            .select("id")
            .eq("judgment_id", judgment_id)
            .execute()
        )

        if intel_response.data:
            logger.info(
                "judgment_enrich_already_enriched kind=judgment_enrich msg_id=%s judgment_id=%s",
                msg_id,
                judgment_id,
            )
            return True  # Already enriched, skip

        # 3. Get vendor and perform enrichment
        vendor = _get_vendor()
        debtor_name = judgment.get("debtor_name") or "Unknown"
        case_index = judgment.get("case_index_number") or judgment_id

        try:
            result = await vendor.enrich(debtor_name, case_index)
        except Exception as enrich_err:
            # Log FCRA audit for failed call via RPC
            await _log_fcra_error(
                client=client,
                judgment_id=judgment_id,
                vendor=vendor,
                error=enrich_err,
                msg_id=msg_id,
            )

            logger.exception(
                "judgment_enrich_vendor_failed kind=judgment_enrich msg_id=%s judgment_id=%s vendor=%s",
                msg_id,
                judgment_id,
                vendor.provider_name,
            )
            raise

        # 4. Complete enrichment atomically via RPC
        # This logs FCRA, upserts intelligence, and updates judgment in one transaction
        collectability_score = _calculate_collectability_score(result)

        rpc_response = client.rpc(
            "complete_enrichment",
            {
                "_judgment_id": judgment_id,
                "_provider": vendor.provider_name,
                "_endpoint": vendor.endpoint,
                "_fcra_status": "success",
                "_fcra_http_code": 200,
                "_fcra_meta": _sanitize_meta(result.raw_meta),
                "_data_source": vendor.provider_name,
                "_employer_name": result.employer_name,
                "_employer_address": result.employer_address,
                "_income_band": result.income_band,
                "_bank_name": result.bank_name,
                "_bank_address": result.bank_address,
                "_home_ownership": result.home_ownership,
                "_has_benefits_only": result.has_benefits_only_account,
                "_confidence_score": result.confidence_score,
                "_new_status": ACTIONABLE_STATUS,
                "_new_collectability_score": collectability_score,
            },
        ).execute()

        # Parse RPC response
        rpc_result = rpc_response.data if rpc_response.data else {}
        fcra_log_id = rpc_result.get("fcra_log_id") if isinstance(rpc_result, dict) else None
        intel_id = rpc_result.get("intelligence_id") if isinstance(rpc_result, dict) else None

        logger.info(
            "judgment_enrich_complete kind=judgment_enrich msg_id=%s judgment_id=%s "
            "collectability_score=%s intel_id=%s fcra_log_id=%s vendor=%s",
            msg_id,
            judgment_id,
            collectability_score,
            intel_id,
            fcra_log_id,
            vendor.provider_name,
        )

        return True

    except Exception:
        logger.exception(
            "judgment_enrich_failed kind=judgment_enrich msg_id=%s judgment_id=%s",
            msg_id,
            judgment_id,
        )
        raise


async def _log_fcra_error(
    client: Any,
    judgment_id: str,
    vendor: SkipTraceVendor,
    error: Exception,
    msg_id: Optional[Any] = None,
) -> None:
    """Log FCRA audit for a failed vendor call."""
    try:
        client.rpc(
            "log_external_data_call",
            {
                "_judgment_id": judgment_id,
                "_provider": vendor.provider_name,
                "_endpoint": vendor.endpoint,
                "_status": "error",
                "_http_code": None,
                "_error_message": str(error)[:500],
                "_meta": {"error_type": type(error).__name__},
            },
        ).execute()
    except Exception as log_err:
        logger.error(
            "judgment_enrich_fcra_log_failed kind=judgment_enrich msg_id=%s judgment_id=%s error=%s",
            msg_id,
            judgment_id,
            log_err,
        )


def _sanitize_meta(raw_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Sanitize metadata for FCRA logging - remove any PII."""
    if not raw_meta:
        return {}

    # Only keep safe metadata fields
    safe_keys = {"results_count", "match_score", "timestamp", "request_id"}
    return {k: v for k, v in raw_meta.items() if k in safe_keys}
