"""Enforcement action handler for PGMQ workers.

This handler processes enforcement_action jobs from the PGMQ queue. After a
judgment has been enriched with debtor intelligence, this worker determines
the appropriate enforcement actions and logs them via RPC.

The handler:
1. Fetches the judgment and its debtor intelligence
2. Determines which enforcement actions are appropriate based on intelligence
3. Logs each planned action via log_enforcement_action RPC
4. Queues follow-up jobs (e.g., document generation) as needed

Job Payload Format:
    {
        "judgment_id": "<uuid>"  # Required: core_judgments.id
    }

Queue Kind: enforcement_action

Action Planning Logic:
- Income execution if employer data available and income >= MED
- Bank levy if bank data available and not benefits-only
- Information subpoena if confidence_score < 70 (need more data)
- Asset search if no bank/employer data
- Demand letter always (first step in enforcement)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.supabase_client import create_supabase_client

logger = logging.getLogger(__name__)

# Minimum confidence for skipping information subpoena
MIN_CONFIDENCE_FOR_DIRECT_ACTION = 70

# Income bands that warrant wage garnishment
GARNISHMENT_INCOME_BANDS = {"HIGH", "MED"}


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


def _determine_enforcement_actions(
    judgment: Dict[str, Any],
    intelligence: Optional[Dict[str, Any]],
) -> List[Tuple[str, str, bool, Optional[str]]]:
    """Determine which enforcement actions to plan based on intelligence.

    Returns list of tuples: (action_type, notes, requires_attorney_signature, metadata_json)
    """
    actions: List[Tuple[str, str, bool, Optional[str]]] = []

    if not intelligence:
        # No intelligence - start with asset search and subpoena
        actions.append(
            (
                "asset_search",
                "No debtor intelligence available - initiate asset search",
                False,
                None,
            )
        )
        actions.append(
            (
                "information_subpoena",
                "No debtor intelligence - issue information subpoena to discover assets",
                True,  # Attorney signature required
                None,
            )
        )
        return actions

    # Always start with demand letter
    debtor_name = judgment.get("debtor_name") or "Debtor"
    actions.append(
        (
            "demand_letter",
            f"Initial demand letter to {debtor_name}",
            False,
            None,
        )
    )

    confidence = intelligence.get("confidence_score") or 0
    employer_name = intelligence.get("employer_name")
    bank_name = intelligence.get("bank_name")
    income_band = intelligence.get("income_band")
    has_benefits_only = intelligence.get("has_benefits_only_account", False)

    # Low confidence - need more data via subpoena
    if confidence < MIN_CONFIDENCE_FOR_DIRECT_ACTION:
        actions.append(
            (
                "information_subpoena",
                f"Confidence score {confidence} < {MIN_CONFIDENCE_FOR_DIRECT_ACTION} - issue subpoena for discovery",
                True,
                None,
            )
        )

    # Wage garnishment if employer known and income adequate
    if employer_name and income_band in GARNISHMENT_INCOME_BANDS:
        actions.append(
            (
                "income_execution",
                f"Employer found: {employer_name}. Income band: {income_band}. Initiate wage garnishment.",
                True,  # Attorney signature required for income execution
                f'{{"employer_name": "{employer_name}", "income_band": "{income_band}"}}',
            )
        )

    # Bank levy if bank known and not benefits-only
    if bank_name and not has_benefits_only:
        actions.append(
            (
                "bank_levy",
                f"Bank found: {bank_name}. Initiate bank levy.",
                True,  # Attorney signature required
                f'{{"bank_name": "{bank_name}"}}',
            )
        )
    elif bank_name and has_benefits_only:
        # Benefits-only account - can still restrain, but levy may be exempt
        actions.append(
            (
                "restraining_notice",
                f"Bank {bank_name} flagged as benefits-only. Issue restraining notice first.",
                False,
                f'{{"bank_name": "{bank_name}", "benefits_only": true}}',
            )
        )

    # If we have neither employer nor bank, request asset search
    if not employer_name and not bank_name:
        actions.append(
            (
                "asset_search",
                "No employer or bank data - initiate comprehensive asset search",
                False,
                None,
            )
        )

    return actions


async def handle_enforcement_action(job: Dict[str, Any]) -> bool:
    """Process an enforcement action planning job.

    Args:
        job: Job payload containing judgment_id.

    Returns:
        True if action planning succeeded, False otherwise.
    """
    msg_id = job.get("msg_id") if isinstance(job, dict) else None
    idempotency_key = _extract_idempotency_key(job)

    # Handle health check jobs from doctor
    if isinstance(idempotency_key, str) and idempotency_key.startswith("doctor:"):
        logger.info(
            "enforcement_action_healthcheck_ignored kind=enforcement_action msg_id=%s idempotency_key=%s",
            msg_id,
            idempotency_key,
        )
        return True

    # Extract judgment_id
    judgment_id = _extract_judgment_id(job)
    if not judgment_id:
        logger.error(
            "enforcement_action_missing_id kind=enforcement_action msg_id=%s idempotency_key=%s job=%s",
            msg_id,
            idempotency_key,
            job,
        )
        return False

    logger.info(
        "enforcement_action_start kind=enforcement_action msg_id=%s judgment_id=%s",
        msg_id,
        judgment_id,
    )

    client = create_supabase_client()

    try:
        # 1. Fetch the judgment
        response = (
            client.table("core_judgments")
            .select(
                "id, case_index_number, debtor_name, status, collectability_score, principal_amount"
            )
            .eq("id", judgment_id)
            .execute()
        )

        if not response.data:
            logger.warning(
                "enforcement_action_judgment_not_found kind=enforcement_action msg_id=%s judgment_id=%s",
                msg_id,
                judgment_id,
            )
            return True  # Don't retry for missing judgments

        judgment = response.data[0]

        # 2. Fetch debtor intelligence (if any)
        intel_response = (
            client.table("debtor_intelligence")
            .select("*")
            .eq("judgment_id", judgment_id)
            .order("last_updated", desc=True)
            .limit(1)
            .execute()
        )

        intelligence = intel_response.data[0] if intel_response.data else None

        # 3. Check if we already have actions for this judgment
        existing_response = (
            client.table("enforcement_actions")
            .select("id, action_type, status")
            .eq("judgment_id", judgment_id)
            .in_("status", ["planned", "pending"])
            .execute()
        )

        existing_action_types = {
            row.get("action_type") for row in (existing_response.data or [])
        }

        if existing_action_types:
            logger.info(
                "enforcement_action_existing kind=enforcement_action msg_id=%s judgment_id=%s existing=%s",
                msg_id,
                judgment_id,
                existing_action_types,
            )

        # 4. Determine which actions to plan
        planned_actions = _determine_enforcement_actions(judgment, intelligence)

        # 5. Log each new action via RPC
        actions_created = 0
        for action_type, notes, requires_sig, metadata_str in planned_actions:
            # Skip if we already have this action type planned/pending
            if action_type in existing_action_types:
                logger.debug(
                    "enforcement_action_skip_existing kind=enforcement_action judgment_id=%s action_type=%s",
                    judgment_id,
                    action_type,
                )
                continue

            # Parse metadata JSON if provided
            import json

            metadata = json.loads(metadata_str) if metadata_str else {}

            try:
                rpc_response = client.rpc(
                    "log_enforcement_action",
                    {
                        "_judgment_id": judgment_id,
                        "_action_type": action_type,
                        "_status": "planned",
                        "_requires_attorney_signature": requires_sig,
                        "_notes": notes,
                        "_metadata": metadata,
                    },
                ).execute()

                action_id = rpc_response.data if rpc_response.data else None
                logger.info(
                    "enforcement_action_created kind=enforcement_action msg_id=%s judgment_id=%s "
                    "action_type=%s action_id=%s requires_signature=%s",
                    msg_id,
                    judgment_id,
                    action_type,
                    action_id,
                    requires_sig,
                )
                actions_created += 1

            except Exception as rpc_err:
                logger.error(
                    "enforcement_action_rpc_failed kind=enforcement_action msg_id=%s judgment_id=%s "
                    "action_type=%s error=%s",
                    msg_id,
                    judgment_id,
                    action_type,
                    rpc_err,
                )
                # Continue with other actions even if one fails

        logger.info(
            "enforcement_action_complete kind=enforcement_action msg_id=%s judgment_id=%s "
            "actions_created=%s total_planned=%s",
            msg_id,
            judgment_id,
            actions_created,
            len(planned_actions),
        )

        return True

    except Exception:
        logger.exception(
            "enforcement_action_failed kind=enforcement_action msg_id=%s judgment_id=%s",
            msg_id,
            judgment_id,
        )
        raise
