"""Compute enrichment collectability scores and persist them via Supabase."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

import httpx
import typer

from src.config.api_surface import SCHEMA_PROFILE
from src.db.supabase_client import COMMON, postgrest

app = typer.Typer(help="Score cases for enrichment collectability")

STATUS_FILTER = "in.(new,enriched,contacting)"
JUDGMENTS_HEADERS = {
    "Accept": "application/json",
    "Accept-Profile": SCHEMA_PROFILE,
    "Content-Profile": SCHEMA_PROFILE,
}
PARTIES_HEADERS = {
    "Accept": "application/json",
    "Accept-Profile": "parties",
    "Content-Profile": "parties",
}
ENRICHMENT_HEADERS = {
    "Accept": "application/json",
    "Accept-Profile": "enrichment",
    "Content-Profile": "enrichment",
}
MERGE_MINIMAL = "resolution=merge-duplicates,return=minimal"
ADDRESS_REGEX = re.compile(r"\d+\s+.+\s+[A-Z]{2}\s+\d{5}")
RECENCY_WINDOW = timedelta(days=7)


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _fetch_cases(client: httpx.Client, limit: Optional[int]) -> List[dict]:
    params = {
        "status": STATUS_FILTER,
        "select": "case_id,index_no,status,principal_amt,judgment_at,created_at",
        "order": "updated_at.asc",
    }
    if limit is not None:
        params["limit"] = str(limit)
    response = client.get("/v_cases", params=params, headers=JUDGMENTS_HEADERS)
    response.raise_for_status()
    return response.json()


def _fetch_collectability(client: httpx.Client, case_ids: Iterable[str]) -> Dict[str, dict]:
    ids = [case_id for case_id in case_ids]
    if not ids:
        return {}
    params = {
        "case_id": f"in.({','.join(ids)})",
        "select": "case_id,updated_at,total_score,tier",
    }
    response = client.get("/collectability", params=params, headers=ENRICHMENT_HEADERS)
    response.raise_for_status()
    records = response.json()
    return {row["case_id"]: row for row in records}


def _filter_stale_cases(cases: List[dict], collectability: Dict[str, dict]) -> List[dict]:
    now = datetime.now(timezone.utc)
    stale_cases: List[dict] = []
    for case in cases:
        record = collectability.get(case["case_id"])
        if record is None:
            stale_cases.append(case)
            continue
        updated_at = _parse_timestamp(record.get("updated_at"))
        if updated_at is None or updated_at < now - RECENCY_WINDOW:
            stale_cases.append(case)
    return stale_cases


def _fetch_roles(client: httpx.Client, case_ids: Iterable[str]) -> Dict[str, List[dict]]:
    ids = list(case_ids)
    if not ids:
        return {}
    params = {
        "case_id": f"in.({','.join(ids)})",
        "select": "case_id,entity_id,role",
    }
    response = client.get("/roles", params=params, headers=PARTIES_HEADERS)
    response.raise_for_status()
    roles_by_case: Dict[str, List[dict]] = defaultdict(list)
    for row in response.json():
        roles_by_case[row["case_id"]].append(row)
    return roles_by_case


def _fetch_entities(client: httpx.Client, entity_ids: Iterable[str]) -> Dict[str, dict]:
    ids = list(entity_ids)
    if not ids:
        return {}
    params = {
        "entity_id": f"in.({','.join(ids)})",
        "select": "entity_id,name_norm",
    }
    response = client.get("/entities", params=params, headers=PARTIES_HEADERS)
    response.raise_for_status()
    return {row["entity_id"]: row for row in response.json()}


def _fetch_contacts(client: httpx.Client, entity_ids: Iterable[str]) -> Dict[str, List[dict]]:
    ids = list(entity_ids)
    if not ids:
        return {}
    params = {
        "entity_id": f"in.({','.join(ids)})",
        "select": "entity_id,kind,value,validated_bool",
    }
    response = client.get("/contacts", params=params, headers=ENRICHMENT_HEADERS)
    response.raise_for_status()
    contacts: Dict[str, List[dict]] = defaultdict(list)
    for row in response.json():
        contacts[row["entity_id"]].append(row)
    return contacts


def _fetch_assets(client: httpx.Client, entity_ids: Iterable[str]) -> Dict[str, List[dict]]:
    ids = list(entity_ids)
    if not ids:
        return {}
    params = {
        "entity_id": f"in.({','.join(ids)})",
        "select": "entity_id,asset_type",
    }
    response = client.get("/assets", params=params, headers=ENRICHMENT_HEADERS)
    response.raise_for_status()
    assets: Dict[str, List[dict]] = defaultdict(list)
    for row in response.json():
        assets[row["entity_id"]].append(row)
    return assets


def _identity_score(roles: List[dict], entities: Dict[str, dict]) -> float:
    score = 0.0
    has_plaintiff = any(role["role"] == "plaintiff" for role in roles)
    has_defendant = any(role["role"] == "defendant" for role in roles)
    if has_plaintiff and has_defendant:
        score += 25.0
    defendant_entities = [role["entity_id"] for role in roles if role["role"] == "defendant"]
    for entity_id in defendant_entities:
        entity = entities.get(entity_id)
        if entity and entity.get("name_norm") and len(entity["name_norm"]) > 10:
            score += 15.0
            break
    return _clamp(score)


def _contactability_score(defendant_ids: Iterable[str], contacts: Dict[str, List[dict]]) -> float:
    score = 0.0
    for entity_id in defendant_ids:
        for contact in contacts.get(entity_id, []):
            kind = contact.get("kind")
            validated = bool(contact.get("validated_bool"))
            value = contact.get("value") or ""
            if validated and kind in {"phone", "email"}:
                score += 30.0
            if kind == "address" and ADDRESS_REGEX.search(value.upper()):
                score += 10.0
        if score >= 100.0:
            break
    return _clamp(score)


def _asset_score(defendant_ids: Iterable[str], assets: Dict[str, List[dict]]) -> float:
    weight_per_type = 20.0
    valuable_types = {"bank_hint", "employment", "real_property"}
    found_types = set()
    for entity_id in defendant_ids:
        for asset in assets.get(entity_id, []):
            asset_type = asset.get("asset_type")
            if asset_type in valuable_types:
                found_types.add(asset_type)
    return _clamp(len(found_types) * weight_per_type, maximum=80.0)


def _recency_amount_score(case: dict) -> float:
    base = 20.0
    judgment_at = case.get("judgment_at")
    principal_raw = case.get("principal_amt")
    principal = float(principal_raw) if principal_raw is not None else 0.0
    reference_date = None
    if judgment_at:
        try:
            reference_date = datetime.fromisoformat(judgment_at.replace("Z", "+00:00"))
        except ValueError:
            pass
    if reference_date is None and case.get("created_at"):
        try:
            reference_date = datetime.fromisoformat(case["created_at"].replace("Z", "+00:00"))
        except ValueError:
            reference_date = None
    if reference_date is not None:
        age_years = (datetime.now(timezone.utc) - reference_date).days / 365.25
        if age_years <= 2:
            base = 60.0
        elif age_years <= 5:
            base = 40.0
    additional = 0.0
    if principal > 10_000:
        additional = min(20.0, (principal - 10_000) / 500.0)
    return _clamp(base + additional)


def _total_score(
    identity: float, contact: float, assets: float, recency: float, adverse: float
) -> float:
    total = identity * 0.30 + contact * 0.25 + assets * 0.25 + recency * 0.10 - adverse
    return _clamp(total)


def _tier(total: float) -> str:
    if total >= 80:
        return "A"
    if total >= 60:
        return "B"
    if total >= 40:
        return "C"
    return "D"


def _upsert_collectability(client: httpx.Client, payload: dict) -> None:
    headers = {
        **COMMON,
        "Accept-Profile": "enrichment",
        "Content-Profile": "enrichment",
        "Prefer": MERGE_MINIMAL,
    }
    response = client.post(
        "/enrichment.collectability?on_conflict=case_id",
        json=[payload],
        headers=headers,
    )
    response.raise_for_status()


def _print_table(results: List[dict]) -> None:
    if not results:
        typer.echo("No cases required scoring.")
        return
    headers = ["case_id", "total_score", "tier"]
    widths = {
        "case_id": max(len("case_id"), *(len(row["case_id"]) for row in results)),
        "total_score": len("total_score"),
        "tier": len("tier"),
    }
    typer.echo(" | ".join(title.ljust(widths[title]) for title in headers))
    typer.echo("-+-".join("-" * widths[title] for title in headers))
    for row in results:
        typer.echo(
            " | ".join(
                [
                    row["case_id"].ljust(widths["case_id"]),
                    f"{row['total_score']:.2f}".ljust(widths["total_score"]),
                    row["tier"].ljust(widths["tier"]),
                ]
            )
        )


@app.command()
def main(
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum cases to evaluate"),
) -> None:
    with postgrest() as client:
        cases = _fetch_cases(client, limit)
        if not cases:
            typer.echo("No cases match the status filter.")
            return
        collectability = _fetch_collectability(client, (case["case_id"] for case in cases))
        stale_cases = _filter_stale_cases(cases, collectability)
        if not stale_cases:
            typer.echo("All cases have recent collectability scores.")
            return
        case_ids = [case["case_id"] for case in stale_cases]
        roles = _fetch_roles(client, case_ids)
        defendant_entities = {
            case_id: [
                role["entity_id"] for role in roles.get(case_id, []) if role["role"] == "defendant"
            ]
            for case_id in case_ids
        }
        all_entity_ids = sorted(
            {entity for entities in defendant_entities.values() for entity in entities}
        )
        entities = _fetch_entities(client, all_entity_ids)
        contacts = _fetch_contacts(client, all_entity_ids)
        assets = _fetch_assets(client, all_entity_ids)

        results: List[dict] = []
        for case in stale_cases:
            case_id = case["case_id"]
            entity_ids = defendant_entities.get(case_id, [])
            identity = _identity_score(roles.get(case_id, []), entities)
            contactability = _contactability_score(entity_ids, contacts)
            asset_score = _asset_score(entity_ids, assets)
            recency_score = _recency_amount_score(case)
            adverse_penalty = 0.0
            total = _total_score(
                identity, contactability, asset_score, recency_score, adverse_penalty
            )
            tier = _tier(total)
            payload = {
                "case_id": case_id,
                "identity_score": round(identity, 2),
                "contactability_score": round(contactability, 2),
                "asset_score": round(asset_score, 2),
                "recency_amount_score": round(recency_score, 2),
                "adverse_penalty": round(adverse_penalty, 2),
            }
            _upsert_collectability(client, payload)
            results.append({"case_id": case_id, "total_score": total, "tier": tier})
        typer.echo(json.dumps({"processed": len(results)}, indent=2))
        _print_table(results)


if __name__ == "__main__":
    app()
