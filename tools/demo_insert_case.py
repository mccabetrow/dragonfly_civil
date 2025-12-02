from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from src.supabase_client import create_supabase_client
from supabase import Client

logger = logging.getLogger(__name__)

DEFAULT_CASE_NUMBER = "DEMO-0001"
DEFAULT_AMOUNT_CENTS = 123_456

__all__ = ["build_demo_payload", "upsert_case"]


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Insert or upsert an idempotent demo case via Supabase RPC",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.getenv("DEMO_CASE_SUPABASE_ENV", "prod"),
        help="Supabase credential set to target",
    )
    parser.add_argument(
        "--case-number",
        default=os.getenv("DEMO_CASE_NUMBER", DEFAULT_CASE_NUMBER),
        help="Case number to upsert (defaults to DEMO-0001)",
    )
    parser.add_argument(
        "--amount-cents",
        type=int,
        default=int(os.getenv("DEMO_CASE_AMOUNT_CENTS", DEFAULT_AMOUNT_CENTS)),
        help="Judgment amount in cents",
    )
    return parser.parse_args(argv)


def build_demo_payload(case_number: str, amount_cents: int) -> Dict[str, Any]:
    amount_dollars = round(amount_cents / 100.0, 2)
    timestamp = datetime.now(timezone.utc).isoformat()
    title = "Demo Plaintiff LLC v. Demo Debtor"
    return {
        "case": {
            "case_number": case_number,
            "source": "demo_smoke_prod",
            "title": title,
            "court": "NYC Civil Court",
            "amount_awarded": amount_dollars,
            "judgment_amount_cents": amount_cents,
            "metadata": {
                "demo": True,
                "smoke_test": "demo_smoke_prod",
                "run_at": timestamp,
            },
        },
        "entities": [
            {
                "role": "plaintiff",
                "name_full": "Demo Plaintiff LLC",
                "is_business": True,
                "emails": ["demo.plaintiff@example.com"],
            },
            {
                "role": "defendant",
                "name_full": "Demo Debtor",
                "phones": ["+12125550000"],
            },
        ],
    }


def _first_dict(value: Any) -> Dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return None


def _extract_case(entry: Dict[str, Any]) -> Dict[str, Any]:
    if not entry:
        return {}
    if isinstance(entry.get("case"), dict):
        return dict(entry["case"])
    return entry


def _safe_fetch_case_row(client: Any, case_number: str) -> Dict[str, Any] | None:
    try:
        response = (
            client.table("v_cases_with_org")
            .select("case_id,case_number,title")
            .eq("case_number", case_number)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # pragma: no cover - defensive path for restricted views
        logger.info("Skipping case confirmation query: %s", exc)
        return None

    return _first_dict(getattr(response, "data", None))


def upsert_case(
    client: Client,
    payload: Dict[str, Any],
    *,
    supabase_env: str | None = None,
    case_number_hint: str | None = None,
    amount_cents: int | None = None,
) -> Dict[str, Any]:
    supabase_env = supabase_env or getattr(client, "_dragonfly_env", "unknown")
    case_number_hint_normalized = (case_number_hint or "").strip().upper()
    case_section = payload.get("case") if isinstance(payload, dict) else None

    try:
        rpc_response = client.rpc(
            "insert_or_get_case_with_entities", {"payload": payload}
        ).execute()
    except Exception as exc:  # pragma: no cover - network/service dependency
        raise RuntimeError("Supabase RPC failed") from exc

    rpc_entry = _first_dict(getattr(rpc_response, "data", None))
    if not rpc_entry:
        raise RuntimeError(
            f"Supabase RPC returned no usable payload: {getattr(rpc_response, 'data', None)!r}"
        )

    case_bundle = _extract_case(rpc_entry)
    case_id_value = case_bundle.get("case_id")
    case_id = str(case_id_value) if case_id_value else None

    case_number = (
        str(
            case_bundle.get(
                "case_number",
                case_number_hint_normalized
                or (case_section or {}).get("case_number", ""),
            )
        )
        .strip()
        .upper()
    )
    if not case_number and case_number_hint_normalized:
        case_number = case_number_hint_normalized

    if not case_id and case_number:
        case_row = _safe_fetch_case_row(client, case_number)
        if case_row and case_row.get("case_id"):
            case_id = str(case_row["case_id"])

    if not case_id:
        raise RuntimeError("Unable to determine case_id from Supabase response")

    entities_detail = rpc_entry.get("entities") or []
    if isinstance(entities_detail, dict):
        entities_detail = [entities_detail]

    entity_ids = rpc_entry.get("entity_ids") or []
    if isinstance(entity_ids, str):
        try:
            entity_ids = json.loads(entity_ids)
        except json.JSONDecodeError:
            entity_ids = [entity_ids]
    if not isinstance(entity_ids, list):
        entity_ids = [entity_ids]

    if not entity_ids:
        entity_ids = [
            str(entity.get("entity_id"))
            for entity in entities_detail
            if entity.get("entity_id")
        ]

    entity_ids = [str(entity_id) for entity_id in entity_ids if entity_id]

    if amount_cents is None and isinstance(case_section, dict):
        judgment_amount = case_section.get("judgment_amount_cents")
        if isinstance(judgment_amount, int):
            amount_cents = judgment_amount
        elif isinstance(judgment_amount, str):
            try:
                amount_cents = int(judgment_amount)
            except ValueError:
                amount_cents = None
        amount_awarded = case_section.get("amount_awarded")
    else:
        amount_awarded = None

    if amount_cents is None and amount_awarded is not None:
        try:
            amount_cents = int(round(float(amount_awarded) * 100))
        except (TypeError, ValueError):
            amount_cents = None

    case_source = case_bundle.get("source")
    case_title = case_bundle.get("title")
    amount_awarded = case_bundle.get("amount_awarded", amount_awarded)

    if isinstance(case_section, dict):
        if not case_source:
            case_source = case_section.get("source")
        if not case_title:
            case_title = case_section.get("title")
        if amount_awarded is None:
            amount_awarded = case_section.get("amount_awarded")

    output = {
        "case_number": case_number,
        "case_id": case_id,
        "amount_cents": amount_cents,
        "amount_dollars": amount_awarded,
        "supabase_env": supabase_env,
        "source": case_source,
        "title": case_title,
        "entity_ids": entity_ids,
        "entity_count": len(entity_ids),
        "entities": entities_detail,
        "meta": rpc_entry.get("meta") or {},
    }

    return output


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging()

    case_number = args.case_number.strip().upper()
    if not case_number:
        logger.error("Case number is required")
        return 1

    amount_cents = max(args.amount_cents, 0)
    payload = build_demo_payload(case_number, amount_cents)

    logger.info("Upserting demo case %s in Supabase env=%s", case_number, args.env)

    try:
        client = create_supabase_client(args.env)
    except Exception as exc:
        logger.error("Failed to create Supabase client: %s", exc)
        return 1

    try:
        output = upsert_case(
            client,
            payload,
            supabase_env=args.env,
            case_number_hint=case_number,
            amount_cents=amount_cents,
        )
    except Exception as exc:
        logger.error("Supabase case insert failed: %s", exc)
        return 1

    print(json.dumps(output, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
