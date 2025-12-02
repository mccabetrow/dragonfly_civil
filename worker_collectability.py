"""Dedicated worker loop for collectability scoring jobs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from etl.collector_intel import CollectorIntelEngine
from workers.runner import worker_loop

logger = logging.getLogger(__name__)
_ENGINE: Optional[CollectorIntelEngine] = None


def _get_engine() -> CollectorIntelEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = CollectorIntelEngine()
    return _ENGINE


def _extract_payload(job: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(job, dict):
        return {}
    payload = job.get("payload")
    if isinstance(payload, dict):
        nested = payload.get("payload")
        if isinstance(nested, dict):
            return nested
        return payload
    return {}


async def handle_collectability(job: Dict[str, Any]) -> bool:
    payload = _extract_payload(job)
    case_id_raw = payload.get("case_id") or payload.get("caseId")
    plaintiff_id_raw = payload.get("plaintiff_id") or payload.get("plaintiffId")
    if not case_id_raw:
        raise ValueError("collectability job missing case_id")
    if not plaintiff_id_raw:
        raise ValueError("collectability job missing plaintiff_id")

    case_id = str(case_id_raw).strip()
    plaintiff_id = str(plaintiff_id_raw).strip()
    engine = _get_engine()
    score = engine.score_case(case_id, plaintiff_id=plaintiff_id)
    target_case_id = score.case_id or case_id
    engine.persist_case_score(target_case_id, score)

    logger.info(
        "collectability_scored case_id=%s plaintiff_id=%s score=%.2f",
        target_case_id,
        plaintiff_id,
        score.total_score,
    )
    return True


if __name__ == "__main__":
    asyncio.run(worker_loop("collectability", handle_collectability))
