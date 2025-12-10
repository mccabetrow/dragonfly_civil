from __future__ import annotations

import argparse
import logging
import sys
import time
from enum import Enum
from typing import Any, Dict, Optional

from src.supabase_client import create_supabase_client
from workers.queue_client import QueueClient

from .enrichment_bundle import StubEnrichmentResult, build_stub_enrichment

LOGGER = logging.getLogger(__name__)
QUEUE_KIND = "enrich"
DEFAULT_POLL_SECONDS = 2.0


class JobResult(Enum):
    EMPTY = "empty"
    SUCCESS = "success"
    ERROR = "error"


def _extract_payload(job: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(job, dict):
        return {}

    candidates = [job.get("payload"), job.get("body")]

    for candidate in candidates:
        if isinstance(candidate, dict):
            nested = candidate.get("payload")
            if isinstance(nested, dict):
                return nested

    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate

    fallback = {}
    for key in ("case_id", "case_number", "force_error"):
        if key in job:
            fallback[key] = job[key]
    return fallback


def _extract_summary(payload: Dict[str, Any]) -> Optional[str]:
    summary = payload.get("summary") if isinstance(payload, dict) else None
    if summary:
        return str(summary)
    return None


def _fetch_case_snapshot(client: Any, case_id: str) -> Dict[str, Any]:
    """Retrieve the latest collectability snapshot for the case if available."""

    try:
        response = (
            client.table("v_collectability_snapshot")
            .select(
                "case_id, case_number, judgment_amount, judgment_date, age_days, collectability_tier"
            )
            .eq("case_id", case_id)
            .limit(1)
            .execute()
        )
    except Exception:  # pragma: no cover - diagnostic logging only
        LOGGER.exception("Failed to fetch collectability snapshot for case %s", case_id)
        return {}

    data = getattr(response, "data", None)
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
    return {}


def run_enrichment_bundle(case_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    client = create_supabase_client()
    table = client.table("enrichment_runs")

    raw_payload: Dict[str, Any] = payload if isinstance(payload, dict) else {}
    summary_hint = _extract_summary(raw_payload)

    try:
        if raw_payload.get("force_error"):
            raise RuntimeError("force_error flag present for enrichment job")

        snapshot = _fetch_case_snapshot(client, case_id)
        stub: StubEnrichmentResult = build_stub_enrichment(
            case_id, snapshot, job_payload=raw_payload
        )

        summary_text = stub.summary or summary_hint

        record: Dict[str, Any] = {
            "case_id": case_id,
            "status": "success",
            "summary": summary_text,
            "raw": stub.raw,
        }
        table.insert(record).execute()
        return {
            "status": "success",
            "tier_hint": stub.raw.get("tier_hint"),
            "collectability_score": stub.raw.get("collectability_score"),
        }
    except Exception as exc:  # noqa: BLE001 - convert to error return for worker loop
        error_message = str(exc)
        error_record: Dict[str, Any] = {
            "case_id": case_id,
            "status": "error",
            "summary": summary_hint or error_message,
            "raw": {
                "payload": raw_payload,
                "error": error_message,
            },
        }
        try:
            table.insert(error_record).execute()
        except Exception:  # pragma: no cover - diagnostic logging only
            LOGGER.exception("Failed to record error enrichment run for case %s", case_id)
        return {"status": "error", "error": error_message}


def process_once(queue: QueueClient) -> JobResult:
    job = queue.dequeue(QUEUE_KIND)
    if not job:
        return JobResult.EMPTY

    payload = _extract_payload(job)
    case_id = payload.get("case_id")
    if not case_id:
        LOGGER.error("Enrichment job %s missing case_id", job.get("msg_id"))
        return JobResult.ERROR

    try:
        result = run_enrichment_bundle(str(case_id), payload)
    except Exception:  # pragma: no cover - defensive catch
        LOGGER.exception("run_enrichment_bundle failed for job %s", job.get("msg_id"))
        return JobResult.ERROR

    if result.get("status") != "success":
        LOGGER.error(
            "Enrichment bundle returned %s for job %s (case_id=%s)",
            result.get("status"),
            job.get("msg_id"),
            case_id,
        )
        return JobResult.ERROR

    msg_id = job.get("msg_id")
    if msg_id is None:
        LOGGER.warning("Processed enrichment job for case %s without msg_id; skipping ack", case_id)
        return JobResult.SUCCESS

    try:
        acked = queue.ack(QUEUE_KIND, int(msg_id))
    except Exception:  # pragma: no cover - defensive catch
        LOGGER.exception("Failed to acknowledge enrich job %s", msg_id)
        return JobResult.ERROR

    if not acked:
        LOGGER.error("Supabase ack returned falsy for enrich job %s", msg_id)
        return JobResult.ERROR

    LOGGER.info("Enrichment job %s acknowledged", msg_id)
    return JobResult.SUCCESS


def _worker_loop(queue: QueueClient, poll_seconds: float) -> None:
    while True:
        result = process_once(queue)
        if result is JobResult.EMPTY:
            time.sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrichment worker")
    parser.add_argument("--once", action="store_true", help="process a single job and exit")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_SECONDS,
        help="seconds to sleep between dequeue attempts when idle",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    with QueueClient() as queue:
        if args.once:
            result = process_once(queue)
            return 0 if result is not JobResult.ERROR else 1

        try:
            _worker_loop(queue, max(args.poll_interval, 0.1))
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            LOGGER.info("Stopping enrichment worker")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
