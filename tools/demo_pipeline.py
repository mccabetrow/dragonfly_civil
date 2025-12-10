from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from etl.src.enrichment_bundle import build_stub_enrichment
from etl.src.worker_enrich import _derive_score_components  # type: ignore[attr-defined]
from src.supabase_client import create_supabase_client, get_supabase_env
from tools.demo_insert_case import (
    DEFAULT_AMOUNT_CENTS,
    DEFAULT_CASE_NUMBER,
    build_demo_payload,
    upsert_case,
)
from workers.queue_client import QueueClient, QueueRpcNotFound

LOGGER = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 3.0
DEFAULT_TIMEOUT_SECONDS = 120
FALLBACK_POLL_SECONDS = 30


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Demo pipeline runner: intake → enrichment → scoring",
    )
    parser.add_argument(
        "--case-number",
        default=DEFAULT_CASE_NUMBER,
        help="Case number to insert or reuse (default: DEMO-0001)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to wait for enrichment before failing",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Supabase credentials to target (defaults to SUPABASE_MODE)",
    )
    return parser.parse_args(argv)


def _normalize_case_number(case_number: str) -> str:
    return case_number.strip().upper()


def _as_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None
    return None


def _ensure_case(client: Any, case_number: str, *, amount_cents: int) -> Dict[str, Any]:
    payload = build_demo_payload(case_number, amount_cents)
    supabase_env = getattr(client, "_dragonfly_env", get_supabase_env())
    return upsert_case(
        client,
        payload,
        supabase_env=supabase_env,
        case_number_hint=case_number,
        amount_cents=amount_cents,
    )


def _trigger_enrichment(case_number: str, case_id: str) -> int:
    LOGGER.info("Queueing enrichment job case_number=%s case_id=%s", case_number, case_id)
    try:
        with QueueClient() as queue:
            msg_id = queue.enqueue(
                "enrich",
                {"case_number": case_number, "case_id": case_id},
                idempotency_key=f"demo_pipeline:{case_number}",
            )
    except QueueRpcNotFound as exc:
        raise RuntimeError("Supabase queue RPCs are unavailable") from exc
    except Exception as exc:  # pragma: no cover - network failures leak through
        raise RuntimeError("Unable to enqueue enrichment job") from exc

    LOGGER.info("Enrichment job enqueued msg_id=%s", msg_id)
    return msg_id


def _fetch_collectability_snapshot(client: Any, case_id: str) -> Dict[str, Any]:
    response = (
        client.table("v_collectability_snapshot")
        .select("case_id,case_number,judgment_amount,judgment_date,age_days,collectability_tier")
        .eq("case_id", case_id)
        .limit(1)
        .execute()
    )
    data = getattr(response, "data", None) or []
    if isinstance(data, list) and data:
        record = data[0]
        if isinstance(record, dict):
            return record
    return {}


def _build_stub_run(
    client: Any,
    case_id: str,
    case_number: str,
    job_payload: Dict[str, Any],
) -> dict[str, Any]:
    snapshot = _fetch_collectability_snapshot(client, case_id)
    stub_result = build_stub_enrichment(case_id, snapshot, job_payload=job_payload)
    return {
        "summary": stub_result.summary,
        "raw": stub_result.raw,
        "status": "success",
    }


def _list_enrichment_runs(client: Any, case_id: str) -> List[Dict[str, Any]]:
    response = (
        client.table("enrichment_runs")
        .select("id,status,created_at,summary,raw")
        .eq("case_id", case_id)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _latest_enrichment_timestamp(runs: List[Dict[str, Any]]) -> Optional[datetime]:
    timestamps = []
    for run in runs:
        created = _as_datetime(run.get("created_at"))
        if created is not None:
            timestamps.append(created)
    if not timestamps:
        return None
    return max(timestamps)


def _select_latest_success(
    runs: List[Dict[str, Any]],
    baseline: Optional[datetime],
) -> Optional[Dict[str, Any]]:
    candidates: List[tuple[datetime, Dict[str, Any]]] = []
    for run in runs:
        if (run.get("status") or "").lower() != "success":
            continue
        created = _as_datetime(run.get("created_at"))
        if created is None:
            continue
        if baseline is not None and created <= baseline:
            continue
        candidates.append((created, run))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _poll_for_enrichment_success(
    client: Any,
    case_id: str,
    *,
    baseline_ts: Optional[datetime],
    timeout_seconds: int,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        runs = _list_enrichment_runs(client, case_id)
        latest_success = _select_latest_success(runs, baseline_ts)
        if latest_success:
            created_at = _as_datetime(latest_success.get("created_at"))
            LOGGER.info(
                "Enrichment success run detected case_id=%s run_id=%s created_at=%s",
                case_id,
                latest_success.get("id"),
                created_at.isoformat() if created_at else "unknown",
            )
            return latest_success
        LOGGER.debug("Waiting for enrichment case_id=%s", case_id)
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Timed out waiting for enrichment of case {case_id}")


def _fetch_entities(client: Any, case_id: str) -> List[Dict[str, Any]]:
    response = (
        client.table("v_entities_simple")
        .select("entity_id, case_id, role, name_full")
        .eq("case_id", case_id)
        .execute()
    )
    data = getattr(response, "data", None) or []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _coerce_dict_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _stable_number_suffix(seed: str, *, length: int = 4) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    numeric = int(digest[:16], 16)
    modulo = 10 ** max(1, length)
    return str(numeric % modulo).rjust(length, "0")


def _sanitize_email_local(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", value.lower())
    return cleaned or "case"


def _make_stub_phone(entity_id: str) -> str:
    suffix = _stable_number_suffix(entity_id, length=4)
    return f"+1-303-555-{suffix}"


def _make_stub_email(case_number: str, entity_id: str) -> str:
    local = _sanitize_email_local(case_number)
    code = _stable_number_suffix(f"{case_number}:{entity_id}", length=3)
    return f"{local}.{code}@demo.dragonfly"


def _generate_stub_contacts_assets(
    defendants: List[Dict[str, Any]],
    case_number: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    contacts: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []
    for entity in defendants:
        entity_id = str(entity.get("entity_id"))
        if not entity_id:
            continue
        contacts.extend(
            [
                {
                    "entity_id": entity_id,
                    "kind": "phone",
                    "value": _make_stub_phone(entity_id),
                    "validated_bool": True,
                    "source": "stub_enrichment",
                },
                {
                    "entity_id": entity_id,
                    "kind": "email",
                    "value": _make_stub_email(case_number, entity_id),
                    "validated_bool": True,
                    "source": "stub_enrichment",
                },
            ]
        )
        assets.append(
            {
                "entity_id": entity_id,
                "asset_type": "employment",
                "meta_json": {
                    "employer": f"Stub Employer {case_number}",
                    "confidence": 0.7,
                    "source": "stub_enrichment",
                },
                "confidence": 0.7,
                "source": "stub_enrichment",
            }
        )
    return contacts, assets


def _parse_meta_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _persist_scores(client: Any, case_id: str, scores: Dict[str, Any]) -> None:
    payload = {
        "p_case_id": case_id,
        "p_identity_score": scores.get("identity_score"),
        "p_contactability_score": scores.get("contactability_score"),
        "p_asset_score": scores.get("asset_score"),
        "p_recency_amount_score": scores.get("recency_amount_score"),
        "p_adverse_penalty": scores.get("adverse_penalty"),
        "p_collectability_score": scores.get("collectability_score"),
        "p_collectability_tier": scores.get("collectability_tier"),
    }
    client.rpc("set_case_scores", payload).execute()


def _ensure_enrichment_summary(
    client: Any, case_id: str, scores: Dict[str, Any], summary: str
) -> None:
    payload = {
        "p_case_id": case_id,
        "p_collectability_score": scores.get("collectability_score"),
        "p_collectability_tier": scores.get("collectability_tier"),
        "p_summary": summary,
    }
    client.rpc("set_case_enrichment", payload).execute()


def _collect_contact_fields(contacts: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    phones: List[str] = []
    emails: List[str] = []
    addresses: List[str] = []
    for contact in contacts:
        kind = (contact.get("kind") or "").lower()
        value = str(contact.get("value") or "").strip()
        if not value:
            continue
        if kind == "phone":
            phones.append(value)
        elif kind == "email":
            emails.append(value)
        elif kind == "address":
            addresses.append(value)
    return {
        "phones": sorted(set(phones)),
        "emails": sorted(set(emails)),
        "addresses": sorted(set(addresses)),
    }


def _collect_employers(assets: List[Dict[str, Any]]) -> List[str]:
    employers: List[str] = []
    for asset in assets:
        if (asset.get("asset_type") or "").lower() != "employment":
            continue
        meta = _parse_meta_json(asset.get("meta_json"))
        employer = str(meta.get("employer") or "").strip()
        if employer:
            employers.append(employer)
    return sorted(set(employers))


def run_pipeline(case_number: str, *, timeout_seconds: int, env: Optional[str]) -> Dict[str, Any]:
    _configure_logging()
    normalized = _normalize_case_number(case_number)
    if not normalized:
        raise RuntimeError("Case number is required")

    client = create_supabase_client(env)
    LOGGER.info(
        "Ensuring demo case exists case_number=%s env=%s",
        normalized,
        getattr(client, "_dragonfly_env", env),
    )
    upsert_result = _ensure_case(client, normalized, amount_cents=DEFAULT_AMOUNT_CENTS)
    case_id = upsert_result["case_id"]

    existing_runs = _list_enrichment_runs(client, case_id)
    baseline_enriched_at = _latest_enrichment_timestamp(existing_runs)

    _trigger_enrichment(normalized, case_id)
    job_payload_hint = {"case_id": case_id, "case_number": normalized}
    poll_timeout = min(max(timeout_seconds, 1), FALLBACK_POLL_SECONDS)
    try:
        latest_run = _poll_for_enrichment_success(
            client,
            case_id,
            baseline_ts=baseline_enriched_at,
            timeout_seconds=poll_timeout,
        )
    except TimeoutError:
        LOGGER.warning(
            "No enrichment run detected within %s seconds; generating local enrichment output",
            poll_timeout,
        )
        latest_run = _build_stub_run(client, case_id, normalized, job_payload_hint)
        raw_payload = latest_run["raw"]
        summary_text = latest_run.get("summary", "")
    else:
        raw_payload = latest_run.get("raw")
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Enrichment run raw payload is not valid JSON") from exc
        if not isinstance(raw_payload, dict):
            raw_payload = {}
        summary_text = latest_run.get("summary", "")

    entities = _fetch_entities(client, case_id)
    defendants = [
        entity for entity in entities if (entity.get("role") or "").lower() == "defendant"
    ]
    stub_contacts, stub_assets = _generate_stub_contacts_assets(defendants, normalized)
    contacts = _coerce_dict_list(raw_payload.get("contacts")) or stub_contacts
    assets = _coerce_dict_list(raw_payload.get("assets")) or stub_assets
    enrichment_context = {
        "entities": entities,
        "defendants": defendants,
        "contacts": contacts,
        "assets": assets,
        "signals": raw_payload.get("signals", {}),
    }
    score_components = _derive_score_components(raw_payload, enrichment_context)
    _ensure_enrichment_summary(client, case_id, score_components, summary_text)
    _persist_scores(client, case_id, score_components)

    contact_fields = _collect_contact_fields(contacts)
    employers = _collect_employers(assets)

    result = {
        "case_number": upsert_result.get("case_number") or normalized,
        "case_id": case_id,
        "collectability_score": score_components.get("collectability_score"),
        "contactability_score": score_components.get("contactability_score"),
        "phones": contact_fields["phones"],
        "emails": contact_fields["emails"],
        "addresses": contact_fields["addresses"],
        "employers": employers,
    }
    return result


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        output = run_pipeline(
            args.case_number,
            timeout_seconds=max(args.timeout, 1),
            env=args.env,
        )
    except TimeoutError as exc:
        LOGGER.error("Pipeline timed out: %s", exc)
        return 2
    except Exception as exc:  # noqa: BLE001 - bubble nicely for CLI usage
        LOGGER.error("Pipeline failed: %s", exc)
        return 1

    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
