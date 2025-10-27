from __future__ import annotations

import os
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import pandas as pd
import psycopg2
import typer
from dotenv import load_dotenv
from loguru import logger

from integration.simplicity import csv_reader
from etl import transforms
from etl.loaders import upsert_case, upsert_judgment, upsert_party, upsert_contact

app = typer.Typer(add_completion=False, help="Simplicity bi-directional sync CLI")


@dataclass
class SyncStats:
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


def configure_logging() -> None:
    logger.remove()
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.add(sys.stderr, level=level, serialize=False, diagnose=False, backtrace=False)


def load_env() -> None:
    load_dotenv(override=False)


def get_pg_url() -> str:
    pg_url = os.getenv("PG_URL") or os.getenv("DATABASE_URL")
    if not pg_url:
        raise typer.BadParameter("PG_URL (or DATABASE_URL) must be set in environment or .env")
    return pg_url


def get_conn(pg_url: str) -> psycopg2.extensions.connection:
    conn = psycopg2.connect(pg_url)
    logger.success("✅ Connected to Postgres")
    return conn


def parse_since(since_str: str) -> datetime:
    """Parse ISO8601 or human strings like '24h', '7d' into datetime."""
    if since_str.lower().endswith("h"):
        hours = int(since_str[:-1])
        return datetime.utcnow() - timedelta(hours=hours)
    if since_str.lower().endswith("d"):
        days = int(since_str[:-1])
        return datetime.utcnow() - timedelta(days=days)
    # Try ISO8601
    try:
        return datetime.fromisoformat(since_str)
    except ValueError:
        raise typer.BadParameter(f"Invalid --since format: {since_str}. Use ISO8601 or '24h', '7d'.")


def load_status_mapping(path: Path) -> Dict[str, str]:
    """Load status_mapping.csv: simplicity_status -> internal_status."""
    if not path.is_file():
        logger.warning(f"Status mapping not found: {path}, using empty mapping")
        return {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
    mapping = {}
    for _, row in df.iterrows():
        simplicity = row.get("simplicity_status", "").strip()
        internal = row.get("internal_status", "").strip()
        if simplicity and internal:
            mapping[simplicity] = internal
    logger.debug(f"Loaded {len(mapping)} status mappings")
    return mapping


def reverse_status_mapping(mapping: Dict[str, str]) -> Dict[str, str]:
    """Reverse status mapping: internal_status -> simplicity_status."""
    return {v: k for k, v in mapping.items()}


def normalize_party_name(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[^0-9a-z]", "", value.lower())


def run_import(
    file_path: Path,
    status_mapping: Dict[str, str],
    conn: psycopg2.extensions.connection,
    dry_run: bool,
    limit: Optional[int],
) -> SyncStats:
    """Import Simplicity CSV into the database."""
    stats = SyncStats()
    rows = list(csv_reader.read_csv(str(file_path)))
    if limit:
        rows = rows[:limit]

    logger.info(f"Processing {len(rows)} rows from {file_path} (dry_run={dry_run})")

    for idx, row in enumerate(rows, start=1):
        try:
            with conn.cursor() as cur:
                cur.execute("SAVEPOINT simplicity_row")

            # Build case payload
            case_payload = {
                "state": (row.get("State") or "CA").strip().upper(),
                "county": (row.get("County") or "").strip(),
                "case_number": transforms.normalize_docket(row.get("IndexNumber", "")),
                "court_name": row.get("Court", ""),
                "case_type": row.get("CaseType", ""),
                "case_status": status_mapping.get(row.get("Status", ""), row.get("Status", "")),
                "filing_date": transforms.to_date(row.get("FilingDate", "")),
                "metadata": {"source": "simplicity_import", "lead_id": row.get("LeadID", "")},
                "ingestion_run_id": None,
            }

            case_id, case_inserted = upsert_case(conn, case_payload)
            if case_inserted:
                stats.inserted += 1
            else:
                stats.updated += 1

            # Build judgment payload
            judgment_date = transforms.to_date(row.get("JudgmentDate", ""))
            amount_str = row.get("JudgmentAmount", "").replace(",", "").replace("$", "").strip()
            amount = float(amount_str) if amount_str else None

            if judgment_date and amount:
                judgment_payload = {
                    "case_id": case_id,
                    "judgment_date": judgment_date,
                    "amount_awarded": amount,
                    "amount_remaining": amount,
                    "judgment_status": status_mapping.get(row.get("Status", ""), "unsatisfied"),
                    "metadata": {"source": "simplicity_import"},
                    "ingestion_run_id": None,
                }
                upsert_judgment(conn, judgment_payload)

            # Build party payloads (defendant)
            defendant_name = row.get("DefendantName", "").strip()
            if defendant_name:
                party_payload = {
                    "case_id": case_id,
                    "party_type": "defendant",
                    "party_role": "judgment debtor",
                    "name_full": defendant_name,
                    "name_normalized": normalize_party_name(defendant_name),
                    "address_raw": row.get("DefendantAddress", ""),
                    "metadata": {"source": "simplicity_import"},
                    "ingestion_run_id": None,
                }
                party_id, _ = upsert_party(conn, party_payload)

                # Build contact payloads
                phone = row.get("Phone", "").strip()
                email = row.get("Email", "").strip()
                if phone:
                    contact_payload = {
                        "party_id": party_id,
                        "contact_type": "phone",
                        "contact_value": transforms.normalize_phone(phone) or phone,
                        "source": "simplicity_import",
                        "is_verified": False,
                        "is_primary": row.get("BestContactMethod", "").lower() == "phone",
                        "metadata": {},
                        "ingestion_run_id": None,
                    }
                    upsert_contact(conn, contact_payload)
                if email:
                    contact_payload = {
                        "party_id": party_id,
                        "contact_type": "email",
                        "contact_value": email,
                        "source": "simplicity_import",
                        "is_verified": False,
                        "is_primary": row.get("BestContactMethod", "").lower() == "email",
                        "metadata": {},
                        "ingestion_run_id": None,
                    }
                    upsert_contact(conn, contact_payload)

            # Plaintiff
            plaintiff_name = row.get("PlaintiffName", "").strip()
            if plaintiff_name:
                party_payload = {
                    "case_id": case_id,
                    "party_type": "plaintiff",
                    "party_role": "judgment creditor",
                    "name_full": plaintiff_name,
                    "name_normalized": normalize_party_name(plaintiff_name),
                    "address_raw": row.get("PlaintiffAddress", ""),
                    "metadata": {"source": "simplicity_import"},
                    "ingestion_run_id": None,
                }
                upsert_party(conn, party_payload)

            stats.processed += 1

            with conn.cursor() as cur:
                if dry_run:
                    cur.execute("ROLLBACK TO SAVEPOINT simplicity_row")
                cur.execute("RELEASE SAVEPOINT simplicity_row")

        except Exception as exc:
            stats.errors += 1
            logger.error(f"Row {idx} error: {exc}")
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT simplicity_row")
                cur.execute("RELEASE SAVEPOINT simplicity_row")

    if dry_run:
        conn.rollback()
    else:
        conn.commit()

    return stats


def run_export(
    out_path: Path,
    since: datetime,
    status_mapping: Dict[str, str],
    conn: psycopg2.extensions.connection,
) -> int:
    """Export changed records to a CSV."""
    reverse_map = reverse_status_mapping(status_mapping)

    # Query for changed judgments since timestamp
    query = """
        SELECT 
            j.id as judgment_id,
            c.case_number,
            c.county,
            c.state,
            c.case_status,
            j.judgment_date,
            j.amount_awarded,
            j.judgment_status,
            COALESCE(j.updated_at, j.created_at) as last_updated,
            c.metadata->>'lead_id' as lead_id
        FROM judgments.judgments j
        JOIN judgments.cases c ON c.id = j.case_id
        WHERE COALESCE(j.updated_at, j.created_at) >= %s
        ORDER BY COALESCE(j.updated_at, j.created_at) DESC
    """

    with conn.cursor() as cur:
        cur.execute(query, (since,))
        rows = cur.fetchall()

    if not rows:
        logger.info(f"No records changed since {since}")
        return 0

    # Build export CSV
    export_data = []
    for row in rows:
        (
            judgment_id,
            case_number,
            county,
            state,
            case_status,
            judgment_date,
            amount_awarded,
            judgment_status,
            last_updated,
            lead_id,
        ) = row
        export_data.append(
            {
                "LeadID": lead_id or "",
                "Status": reverse_map.get(judgment_status, judgment_status),
                "UpdatedAt": last_updated.isoformat() if last_updated else "",
                "Docket": case_number or "",
                "County": county or "",
                "State": state or "",
                "JudgmentDate": judgment_date.isoformat() if judgment_date else "",
                "Amount": f"{amount_awarded:.2f}" if amount_awarded else "",
            }
        )

    df = pd.DataFrame(export_data)
    df.to_csv(out_path, index=False)
    logger.success(f"✅ Exported {len(export_data)} rows to {out_path}")
    return len(export_data)


@app.command()
def main(
    direction: str = typer.Option(..., "--direction", help="'import' or 'export'"),
    since: str = typer.Option("24h", "--since", help="Time window (ISO8601 or '24h', '7d')"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Import: rollback changes"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Import: limit rows"),
    file: Optional[Path] = typer.Option(None, "--file", help="Import: CSV path"),
    out: Optional[Path] = typer.Option(None, "--out", help="Export: output CSV path"),
) -> None:
    """Simplicity bi-directional sync."""
    configure_logging()
    load_env()
    pg_url = get_pg_url()
    conn = get_conn(pg_url)

    mapping_path = Path(__file__).resolve().parents[1] / "data" / "status_mapping.csv"
    status_mapping = load_status_mapping(mapping_path)

    try:
        if direction == "import":
            if not file:
                raise typer.BadParameter("--file required for import")
            stats = run_import(file, status_mapping, conn, dry_run, limit)
            typer.echo(f"✅ Import complete: processed={stats.processed}, inserted={stats.inserted}, updated={stats.updated}, errors={stats.errors}")
            if dry_run:
                typer.echo("ℹ️  DRY-RUN mode: no changes committed")
        elif direction == "export":
            if not out:
                raise typer.BadParameter("--out required for export")
            since_dt = parse_since(since)
            count = run_export(out, since_dt, status_mapping, conn)
            typer.echo(f"✅ Export complete: {count} rows written to {out}")
        else:
            raise typer.BadParameter("--direction must be 'import' or 'export'")
    finally:
        conn.close()


if __name__ == "__main__":
    app()
