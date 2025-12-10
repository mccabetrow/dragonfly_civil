from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from src.logging_setup import configure_logging

from .handlers import (
    extract_case_number,
    handle_enforce,
    handle_enrich,
    handle_outreach,
    update_case_status,
)
from .queue_client import QueueClient, QueueRpcNotFound

configure_logging()
logger = logging.getLogger(__name__)

JobHandler = Callable[[Dict[str, Any]], Awaitable[bool]]


async def worker_loop(kind: str, handler: JobHandler, poll_interval: float = 1.0) -> None:
    client = QueueClient()
    failure_counts: Dict[int, int] = {}

    try:
        logger.info("Starting worker loop for kind=%s, poll_interval=%.2fs", kind, poll_interval)
        while True:
            try:
                job = client.dequeue(kind)
            except QueueRpcNotFound:
                logger.critical(
                    "Queue RPC dequeue_job/queue_job missing for kind=%s. Apply migrations and restart.",
                    kind,
                )
                break
            except Exception as exc:
                logger.exception("Error dequeuing %s job: %s", kind, exc)
                await asyncio.sleep(5.0)
                continue

            if not job:
                await asyncio.sleep(poll_interval)
                continue

            msg_id_raw = job.get("msg_id") if isinstance(job, dict) else None
            msg_id: Optional[int] = None
            if msg_id_raw is not None:
                try:
                    msg_id = int(msg_id_raw)
                except (TypeError, ValueError):
                    logger.warning("Job %s has non-integer msg_id=%s", job, msg_id_raw)

            def record_failure(job_dict: Dict[str, Any]) -> None:
                if msg_id is None:
                    logger.warning("Cannot track retries for job without msg_id: %s", job_dict)
                    return

                attempts = failure_counts.get(msg_id, 0) + 1
                failure_counts[msg_id] = attempts
                logger.warning("Job %s on queue %s attempt %s failed", msg_id, kind, attempts)

                if attempts >= 5:
                    logger.error(
                        "Job %s on queue %s exceeded retry limit; acknowledging to avoid poison loop",
                        msg_id,
                        kind,
                    )
                    if kind == "enrich":
                        case_number = extract_case_number(job_dict)
                        if case_number:
                            try:
                                update_case_status(case_number, "enrich_failed")
                            except Exception:
                                logger.exception(
                                    "Failed to mark case %s as enrich_failed",
                                    case_number,
                                )
                    try:
                        client.ack(kind, msg_id)
                    except Exception:
                        logger.exception(
                            "Failed to acknowledge job %s after retry exhaustion",
                            msg_id,
                        )
                    else:
                        failure_counts.pop(msg_id, None)

            try:
                success = bool(await handler(job))
            except Exception:
                logger.exception("Worker %s failed to handle job %s", kind, job)
                record_failure(job)
                await asyncio.sleep(poll_interval)
                continue

            if success and msg_id is not None:
                try:
                    client.ack(kind, msg_id)
                    failure_counts.pop(msg_id, None)
                except Exception:
                    logger.exception("Failed to acknowledge job %s on %s", msg_id, kind)
                continue

            record_failure(job)
            await asyncio.sleep(poll_interval)
    finally:
        client.close()


async def main() -> None:
    await asyncio.gather(
        worker_loop("enrich", handle_enrich),
        worker_loop("outreach", handle_outreach),
        worker_loop("enforce", handle_enforce),
    )


if __name__ == "__main__":
    asyncio.run(main())
