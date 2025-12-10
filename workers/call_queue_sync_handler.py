"""Call queue sync handler for PGMQ workers.

This handler ensures every plaintiff who needs a call has an open 'call' task.
It reads from v_plaintiff_call_queue and uses the upsert_plaintiff_task RPC
to create tasks idempotently without direct table writes.

The handler:
1. Fetches plaintiffs needing calls from v_plaintiff_call_queue (or all active plaintiffs)
2. For each plaintiff, calls upsert_plaintiff_task RPC with kind='call'
3. On failures, queues a notify_ops job for ops team attention

Job Payload Format:
    {
        "plaintiff_id": "<uuid>"   # Optional: sync single plaintiff
        "batch": true              # Optional: sync all plaintiffs needing calls
    }

Queue Kind: call_queue_sync
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.supabase_client import create_supabase_client

logger = logging.getLogger(__name__)


def _extract_plaintiff_id(job: Dict[str, Any]) -> Optional[str]:
    """Extract plaintiff_id from job payload.

    Handles nested payload structure from PGMQ.
    """
    if not isinstance(job, dict):
        return None

    # Try direct access first
    plaintiff_id = job.get("plaintiff_id")
    if plaintiff_id:
        return str(plaintiff_id).strip()

    # Check nested payload
    payload = job.get("payload")
    if isinstance(payload, dict):
        # Double-nested payload (from queue_job RPC)
        nested = payload.get("payload")
        if isinstance(nested, dict):
            plaintiff_id = nested.get("plaintiff_id")
            if plaintiff_id:
                return str(plaintiff_id).strip()

        # Single-nested payload
        plaintiff_id = payload.get("plaintiff_id")
        if plaintiff_id:
            return str(plaintiff_id).strip()

    return None


def _is_batch_job(job: Dict[str, Any]) -> bool:
    """Check if job is a batch sync request."""
    if not isinstance(job, dict):
        return False

    # Direct access
    if job.get("batch"):
        return True

    # Nested payload
    payload = job.get("payload")
    if isinstance(payload, dict):
        nested = payload.get("payload")
        if isinstance(nested, dict) and nested.get("batch"):
            return True
        if payload.get("batch"):
            return True

    return False


def fetch_plaintiffs_needing_calls(client) -> List[Dict[str, Any]]:
    """Fetch all plaintiffs who need call tasks from the view.

    Returns plaintiffs from v_plaintiff_call_queue which shows those
    with open call tasks. We also want to find plaintiffs WITHOUT
    call tasks who are in call-worthy statuses.
    """
    # First, get plaintiffs with open call tasks (to update/refresh)
    existing_response = (
        client.table("v_plaintiff_call_queue")
        .select("plaintiff_id, plaintiff_name, status, tier")
        .execute()
    )

    plaintiffs_with_tasks = {row["plaintiff_id"] for row in (existing_response.data or [])}

    # Then, get active plaintiffs who may need call tasks
    # Status values that warrant outreach calls
    call_worthy_statuses = [
        "new",
        "contacted",
        "qualified",
        "follow_up",
        "pending_docs",
    ]

    plaintiffs_response = (
        client.table("plaintiffs")
        .select("id, name, status")
        .in_("status", call_worthy_statuses)
        .execute()
    )

    all_plaintiffs = []

    # Add plaintiffs needing new tasks
    for plaintiff in plaintiffs_response.data or []:
        all_plaintiffs.append(
            {
                "plaintiff_id": plaintiff["id"],
                "plaintiff_name": plaintiff.get("name"),
                "status": plaintiff.get("status"),
                "has_existing_task": plaintiff["id"] in plaintiffs_with_tasks,
            }
        )

    return all_plaintiffs


def fetch_single_plaintiff(client, plaintiff_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single plaintiff by ID."""
    response = (
        client.table("plaintiffs").select("id, name, status").eq("id", plaintiff_id).execute()
    )

    if not response.data:
        return None

    plaintiff = response.data[0]
    return {
        "plaintiff_id": plaintiff["id"],
        "plaintiff_name": plaintiff.get("name"),
        "status": plaintiff.get("status"),
    }


def upsert_call_task(
    client,
    plaintiff_id: str,
    due_at: Optional[datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Use RPC to upsert a call task for a plaintiff.

    This is idempotent - if an open call task exists, it updates it;
    otherwise creates a new one.
    """
    if due_at is None:
        # Default to tomorrow at 9 AM
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        due_at = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)  # 9 AM EST = 14 UTC

    rpc_params = {
        "p_plaintiff_id": plaintiff_id,
        "p_kind": "call",
        "p_due_at": due_at.isoformat(),
        "p_metadata": metadata or {},
        "p_created_by": "call_queue_sync",
    }

    try:
        response = client.rpc("upsert_plaintiff_task", rpc_params).execute()
        return response.data if response.data else {"success": False, "error": "empty_response"}
    except Exception as e:
        logger.error(
            "upsert_call_task_rpc_failed plaintiff_id=%s error=%s",
            plaintiff_id,
            str(e),
        )
        return {"success": False, "error": str(e)}


def queue_notify_ops(client, message: str, context: Dict[str, Any]) -> bool:
    """Queue a notify_ops job for ops team attention on failures."""
    try:
        payload = {
            "kind": "notify_ops",
            "idempotency_key": f"notify_ops:call_queue:{context.get('plaintiff_id', 'batch')}:{datetime.now(timezone.utc).date()}",
            "payload": {
                "source": "call_queue_sync",
                "message": message,
                "context": context,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        client.rpc("queue_job", {"payload": payload}).execute()
        logger.info("notify_ops_queued message=%s", message[:50])
        return True
    except Exception as e:
        # notify_ops might not be a registered queue kind yet - log but don't fail
        logger.warning("notify_ops_queue_failed error=%s", e)
        return False


async def handle_call_queue_sync(job: Dict[str, Any]) -> bool:
    """Handle a call_queue_sync job from the PGMQ queue.

    Args:
        job: The job dict from dequeue_job RPC

    Returns:
        True if job processed successfully (delete from queue)
        False if job should be retried
    """
    msg_id = job.get("msg_id", "?")
    is_batch = _is_batch_job(job)
    plaintiff_id = _extract_plaintiff_id(job)

    if not is_batch and not plaintiff_id:
        logger.error(
            "call_queue_sync_invalid_payload kind=call_queue_sync msg_id=%s",
            msg_id,
        )
        return True  # Don't retry invalid payloads

    logger.info(
        "call_queue_sync_start kind=call_queue_sync msg_id=%s batch=%s plaintiff_id=%s",
        msg_id,
        is_batch,
        plaintiff_id or "all",
    )

    client = create_supabase_client()

    try:
        if is_batch:
            # Batch mode: sync all plaintiffs needing calls
            plaintiffs = fetch_plaintiffs_needing_calls(client)
            logger.info(
                "call_queue_sync_batch_found kind=call_queue_sync msg_id=%s count=%d",
                msg_id,
                len(plaintiffs),
            )
        else:
            # Single plaintiff mode
            plaintiff = fetch_single_plaintiff(client, plaintiff_id)
            if not plaintiff:
                logger.warning(
                    "call_queue_sync_plaintiff_not_found kind=call_queue_sync msg_id=%s plaintiff_id=%s",
                    msg_id,
                    plaintiff_id,
                )
                return True  # Don't retry for missing plaintiff

            plaintiffs = [plaintiff]

        # Process each plaintiff
        success_count = 0
        failure_count = 0
        failures = []

        for plaintiff in plaintiffs:
            pid = plaintiff["plaintiff_id"]
            result = upsert_call_task(client, pid)

            if result.get("success"):
                is_new = result.get("is_new", False)
                task_id = result.get("task_id")
                logger.debug(
                    "call_queue_sync_task_upserted plaintiff_id=%s task_id=%s is_new=%s",
                    pid,
                    task_id,
                    is_new,
                )
                success_count += 1
            else:
                error = result.get("error", "unknown")
                logger.warning(
                    "call_queue_sync_task_failed plaintiff_id=%s error=%s",
                    pid,
                    error,
                )
                failure_count += 1
                failures.append({"plaintiff_id": pid, "error": error})

        # Queue notify_ops for failures if any
        if failures:
            queue_notify_ops(
                client,
                f"Call queue sync had {failure_count} failures",
                {
                    "msg_id": msg_id,
                    "total": len(plaintiffs),
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "failures": failures[:10],  # Limit to first 10
                },
            )

        logger.info(
            "call_queue_sync_complete kind=call_queue_sync msg_id=%s success=%d failed=%d",
            msg_id,
            success_count,
            failure_count,
        )

        return True

    except Exception as e:
        logger.exception(
            "call_queue_sync_failed kind=call_queue_sync msg_id=%s",
            msg_id,
        )
        # Queue notify for unexpected errors
        queue_notify_ops(
            client,
            f"Call queue sync crashed: {str(e)[:100]}",
            {"msg_id": msg_id, "error": str(e)},
        )
        raise


async def sync_all_call_tasks() -> Dict[str, Any]:
    """Synchronous entry point to sync all plaintiffs.

    Can be called directly without going through the queue.
    Returns summary of sync operation.
    """
    client = create_supabase_client()

    plaintiffs = fetch_plaintiffs_needing_calls(client)

    success_count = 0
    failure_count = 0
    created_count = 0
    updated_count = 0

    for plaintiff in plaintiffs:
        pid = plaintiff["plaintiff_id"]
        result = upsert_call_task(client, pid)

        if result.get("success"):
            success_count += 1
            if result.get("is_new"):
                created_count += 1
            else:
                updated_count += 1
        else:
            failure_count += 1

    return {
        "total_plaintiffs": len(plaintiffs),
        "success_count": success_count,
        "failure_count": failure_count,
        "created_count": created_count,
        "updated_count": updated_count,
    }
