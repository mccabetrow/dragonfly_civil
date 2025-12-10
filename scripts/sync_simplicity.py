"""Sync Simplicity CSV exports into Supabase."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from uuid import UUID

import httpx
import typer

from src.db.supabase_client import postgrest
from src.transforms.models_cases import CaseRecord, PartyRecord, parse_rows

app = typer.Typer(help="Synchronize Simplicity data into Supabase")

JUDGMENTS_HEADERS = {
    "Accept-Profile": "judgments",
    "Content-Profile": "judgments",
}
PARTIES_HEADERS = {
    "Accept-Profile": "parties",
    "Content-Profile": "parties",
}
MERGE_PREFER_RETURN = "resolution=merge-duplicates,return=representation"
MERGE_PREFER_MINIMAL = "resolution=merge-duplicates,return=minimal"


def _load_cases(csv_path: Path, limit: Optional[int]) -> tuple[list[CaseRecord], list[str]]:
    with csv_path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows_iter = reader if limit is None else (row for _, row in zip(range(limit), reader))
        return parse_rows(rows_iter)


def _fetch_case_id(client: httpx.Client, case: CaseRecord) -> Optional[str]:
    params = {
        "court": f"eq.{case.court}",
        "county": f"eq.{case.county}",
        "index_no": f"eq.{case.index_number}",
        "select": "case_id",
        "limit": 1,
    }
    response = client.get("/cases", params=params, headers=JUDGMENTS_HEADERS)
    response.raise_for_status()
    data = response.json()
    if data:
        return data[0]["case_id"]
    return None


def _upsert_case(client: httpx.Client, case: CaseRecord) -> str:
    payload = [case.case_payload()]
    response = client.post(
        "/cases?on_conflict=court,county,index_no",
        json=payload,
        headers={**JUDGMENTS_HEADERS, "Prefer": MERGE_PREFER_RETURN},
    )
    response.raise_for_status()
    body = response.json()
    if body:
        return body[0]["case_id"]
    existing_id = _fetch_case_id(client, case)
    if existing_id is None:
        raise RuntimeError("Supabase did not return case representation")
    return existing_id


def _upsert_entities(client: httpx.Client, parties: Iterable[PartyRecord]) -> None:
    payload = [party.entity_payload() for party in parties]
    if not payload:
        return
    response = client.post(
        "/entities?on_conflict=entity_id",
        json=payload,
        headers={**PARTIES_HEADERS, "Prefer": MERGE_PREFER_MINIMAL},
    )
    response.raise_for_status()


def _upsert_roles(client: httpx.Client, case_id: UUID, parties: Iterable[PartyRecord]) -> None:
    payload = [party.role_payload(case_id) for party in parties]
    if not payload:
        return
    response = client.post(
        "/roles?on_conflict=case_id,entity_id,role",
        json=payload,
        headers={**PARTIES_HEADERS, "Prefer": MERGE_PREFER_MINIMAL},
    )
    response.raise_for_status()


def _process_case(
    client: httpx.Client,
    case: CaseRecord,
    commit: bool,
) -> dict[str, Any]:
    existing_id = _fetch_case_id(client, case)
    was_existing = existing_id is not None

    result: Dict[str, Any] = {
        "case": case.index_number,
        "existing": was_existing,
    }

    if commit:
        case_id_str = _upsert_case(client, case)
        result["case_id"] = case_id_str
        parties = list(case.parties())
        _upsert_entities(client, parties)
        _upsert_roles(client, UUID(case_id_str), parties)
    else:
        result["case_id"] = existing_id

    return result


def _assert_commit_allowed(commit: bool, i_understand: bool) -> None:
    if not commit:
        return
    env = os.getenv("ENV", "dev")
    if env.lower() == "prod" and not i_understand:
        raise typer.BadParameter(
            "Production commits require --i-understand to acknowledge the risk.",
            param_hint="--commit",
        )


@app.command("import")
def import_command(
    file: Path = typer.Argument(..., exists=True, readable=True, resolve_path=True),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum rows to process"),
    commit: bool = typer.Option(False, "--commit", help="Persist changes to Supabase"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without writes"),
    i_understand: bool = typer.Option(
        False,
        "--i-understand",
        help="Acknowledge production writes when ENV=prod",
    ),
) -> None:
    if commit and dry_run:
        raise typer.BadParameter("Use either --commit or --dry-run, not both.")
    if not commit:
        dry_run = True

    _assert_commit_allowed(commit, i_understand)

    cases, parse_errors = _load_cases(file, limit)

    summary = {
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "errors": len(parse_errors),
    }

    if parse_errors:
        for error in parse_errors:
            typer.echo(f"Parse error: {error}", err=True)

    with postgrest() as client:
        for case in cases:
            summary["processed"] += 1
            try:
                result = _process_case(client, case, commit)
                if result["existing"]:
                    summary["updated"] += 1
                else:
                    summary["inserted"] += 1
                if dry_run:
                    typer.echo(f"DRY RUN -> {json.dumps(result)}")
            except httpx.HTTPError as exc:
                summary["errors"] += 1
                typer.echo(f"HTTP error for case {case.index_number}: {exc}", err=True)
            except Exception as exc:  # noqa: BLE001
                summary["errors"] += 1
                typer.echo(f"Unexpected error for case {case.index_number}: {exc}", err=True)

    typer.echo(json.dumps(summary, indent=2))


if __name__ == "__main__":
    app()
