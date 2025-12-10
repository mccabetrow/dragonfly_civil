from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import psycopg2
import typer
from dotenv import load_dotenv
from loguru import logger

from etl import transforms
from etl.loaders import upsert_case, upsert_contact, upsert_judgment, upsert_party
from integration.simplicity import csv_reader

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
    logger.success("[OK] Connected to Postgres")
    return conn


def parse_since(since_str: str) -> datetime:
    """Parse ISO8601 or relative strings like '24h' or '7d'."""
    token = since_str.strip().lower()
    if token.endswith("h") and token[:-1].isdigit():
        hours = int(token[:-1])
        return datetime.utcnow() - timedelta(hours=hours)
    if token.endswith("d") and token[:-1].isdigit():
        days = int(token[:-1])
        return datetime.utcnow() - timedelta(days=days)
    try:
        return datetime.fromisoformat(since_str)
    except ValueError as exc:
        raise typer.BadParameter(
            f"Invalid --since format: {since_str}. Use ISO8601 or values like '24h', '7d'."
        ) from exc


def load_status_mapping(path: Path) -> Dict[str, str]:
    """Load status mapping CSV into a dict."""
    if not path.is_file():
        logger.warning(f"Status mapping not found: {path}, using empty mapping")
        return {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")
    mapping: Dict[str, str] = {}
    for _, row in df.iterrows():
        simplicity = row.get("simplicity_status", "").strip()
        internal = row.get("internal_status", "").strip()
        if simplicity and internal:
            mapping[simplicity] = internal
    logger.debug(f"Loaded {len(mapping)} status mappings")
    return mapping


def reverse_status_mapping(mapping: Dict[str, str]) -> Dict[str, str]:
    return {value: key for key, value in mapping.items()}


def normalize_party_name(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[^0-9a-z]", "", value.lower())


def _parse_amount(raw: str) -> Optional[float]:
    if not raw:
        return None
    normalized = raw.replace(",", "").replace("$", "").strip()
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        logger.warning(f"Unable to parse judgment amount '{raw}'")
        return None


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
    logger.info(f"[IMPORT] Found {len(rows)} new leads")

    for idx, row in enumerate(rows, start=1):
        row_inserted = False
        row_updated = False
        try:
            with conn.cursor() as cur:
                cur.execute("SAVEPOINT simplicity_row")
            logger.info("[UPSERT] Savepoint created")

            case_payload: Dict[str, Any] = {
                "state": (row.get("State") or "CA").strip().upper(),
                "county": (row.get("County") or "").strip(),
                "case_number": transforms.normalize_docket(row.get("IndexNumber", "")),
                "court_name": row.get("Court", ""),
                "case_type": row.get("CaseType", ""),
                "case_status": status_mapping.get(row.get("Status", ""), row.get("Status", "")),
                "case_url": row.get("CaseURL", ""),
                "filing_date": transforms.to_date(row.get("FilingDate", "")),
                "metadata": {"source": "simplicity_import", "lead_id": row.get("LeadID", "")},
                "ingestion_run_id": None,
            }

            case_id, case_inserted = upsert_case(conn, case_payload)
            row_inserted = case_inserted
            row_updated = not case_inserted

            judgment_date = transforms.to_date(row.get("JudgmentDate", ""))
            amount = _parse_amount(row.get("JudgmentAmount", ""))
            if judgment_date and amount is not None:
                judgment_payload: Dict[str, Any] = {
                    "case_id": case_id,
                    "judgment_number": row.get("JudgmentNumber") or None,
                    "judgment_date": judgment_date,
                    "amount_awarded": amount,
                    "amount_remaining": amount,
                    "interest_rate": row.get("InterestRate"),
                    "judgment_type": row.get("JudgmentType"),
                    "judgment_status": status_mapping.get(row.get("Status", ""), "unsatisfied"),
                    "renewal_date": transforms.to_date(row.get("RenewalDate", "")),
                    "expiration_date": transforms.to_date(row.get("ExpirationDate", "")),
                    "notes": row.get("Notes"),
                    "metadata": {"source": "simplicity_import"},
                    "ingestion_run_id": None,
                }
                upsert_judgment(conn, judgment_payload)

            defendant_name = row.get("DefendantName", "").strip()
            if defendant_name:
                defendant_payload: Dict[str, Any] = {
                    "case_id": case_id,
                    "party_type": "defendant",
                    "party_role": "judgment debtor",
                    "is_business": False,
                    "name_full": defendant_name,
                    "name_first": None,
                    "name_last": None,
                    "name_business": None,
                    "name_normalized": normalize_party_name(defendant_name),
                    "address_line1": row.get("DefendantAddress", ""),
                    "address_line2": None,
                    "city": row.get("County", ""),
                    "state": (row.get("State") or "").strip().upper(),
                    "zip": None,
                    "phone": None,
                    "email": None,
                    "metadata": {"source": "simplicity_import"},
                    "ingestion_run_id": None,
                }
                party_id, _ = upsert_party(conn, defendant_payload)

                phone = row.get("Phone", "").strip()
                if phone:
                    contact_payload: Dict[str, Any] = {
                        "party_id": party_id,
                        "contact_type": "phone",
                        "contact_value": transforms.normalize_phone(phone) or phone,
                        "contact_label": None,
                        "is_verified": False,
                        "is_primary": row.get("BestContactMethod", "").lower() == "phone",
                        "source": "simplicity_import",
                        "last_verified_at": None,
                        "notes": None,
                        "metadata": {},
                        "ingestion_run_id": None,
                    }
                    upsert_contact(conn, contact_payload)

                email = row.get("Email", "").strip()
                if email:
                    contact_payload = {
                        "party_id": party_id,
                        "contact_type": "email",
                        "contact_value": email,
                        "contact_label": None,
                        "is_verified": False,
                        "is_primary": row.get("BestContactMethod", "").lower() == "email",
                        "source": "simplicity_import",
                        "last_verified_at": None,
                        "notes": None,
                        "metadata": {},
                        "ingestion_run_id": None,
                    }
                    upsert_contact(conn, contact_payload)

            plaintiff_name = row.get("PlaintiffName", "").strip()
            if plaintiff_name:
                plaintiff_payload: Dict[str, Any] = {
                    "case_id": case_id,
                    "party_type": "plaintiff",
                    "party_role": "judgment creditor",
                    "is_business": True,
                    "name_full": plaintiff_name,
                    "name_first": None,
                    "name_last": None,
                    "name_business": plaintiff_name,
                    "name_normalized": normalize_party_name(plaintiff_name),
                    "address_line1": row.get("PlaintiffAddress", ""),
                    "address_line2": None,
                    "city": row.get("County", ""),
                    "state": (row.get("State") or "").strip().upper(),
                    "zip": None,
                    "phone": None,
                    "email": None,
                    "metadata": {"source": "simplicity_import"},
                    "ingestion_run_id": None,
                }
                upsert_party(conn, plaintiff_payload)

            stats.processed += 1
            if row_inserted:
                stats.inserted += 1
            elif row_updated:
                stats.updated += 1

            with conn.cursor() as cur:
                if dry_run:
                    cur.execute("ROLLBACK TO SAVEPOINT simplicity_row")
                    logger.info("[UPSERT] Rolling back due to dry-run")
                cur.execute("RELEASE SAVEPOINT simplicity_row")

        except Exception as exc:
            stats.errors += 1
            logger.exception(f"Row {idx} error: {exc}")
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

    export_data = []
    for (
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
    ) in rows:
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
    logger.success(f"[OK] Exported {len(export_data)} rows to {out_path}")
    return len(export_data)


def _mapping_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "status_mapping.csv"


@app.command("import")
def import_command(
    file: Path = typer.Option(..., "--file", help="CSV file exported from Simplicity"),
    dry_run: bool = typer.Option(
        True, "--dry-run/--commit", help="Dry-run by default; use --commit to persist"
    ),
    limit: Optional[int] = typer.Option(None, "--limit", help="Limit rows processed"),
    i_understand: bool = typer.Option(
        False,
        "--i-understand",
        help="Acknowledge irreversible writes when ENV=prod",
    ),
) -> None:
    """Import Simplicity CSV into Dragonfly."""
    configure_logging()
    load_env()
    status_mapping = load_status_mapping(_mapping_path())
    conn = get_conn(get_pg_url())

    env_name = (os.getenv("ENV") or os.getenv("ENVIRONMENT") or "").lower()
    if not dry_run and env_name == "prod" and not i_understand:
        raise RuntimeError("Refusing to commit without --i-understand flag in prod")

    try:
        stats = run_import(file, status_mapping, conn, dry_run, limit)
        typer.echo(
            f"[OK] Import complete: processed={stats.processed}, inserted={stats.inserted}, updated={stats.updated}, errors={stats.errors}"
        )
        if dry_run:
            typer.echo("[INFO] DRY-RUN mode: no changes committed")
        else:
            typer.echo("Changes committed successfully.")
    finally:
        conn.close()


@app.command("export")
def export_command(
    out: Path = typer.Option(..., "--out", help="Output CSV path"),
    since: str = typer.Option("24h", "--since", help="Time window (ISO8601 or '24h', '7d')"),
) -> None:
    """Export Dragonfly records back to Simplicity."""
    configure_logging()
    load_env()
    status_mapping = load_status_mapping(_mapping_path())
    conn = get_conn(get_pg_url())

    try:
        since_dt = parse_since(since)
        count = run_export(out, since_dt, status_mapping, conn)
        typer.echo(f"[OK] Export complete: {count} rows written to {out}")
    finally:
        conn.close()


@app.command("map-status")
def map_status_command(
    value: str = typer.Argument(..., help="Status value to translate"),
    reverse: bool = typer.Option(False, "--reverse", help="Map internal status back to Simplicity"),
) -> None:
    """Translate status values between Simplicity and internal codes."""
    configure_logging()
    load_env()
    status_mapping = load_status_mapping(_mapping_path())

    if reverse:
        reverse_map = {k.lower(): v for k, v in reverse_status_mapping(status_mapping).items()}
        result = reverse_map.get(value.lower())
        if result is None:
            typer.echo("[WARN] Status mapping not found", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"-> external: {result}")
        return

    normalized = {k.lower(): v for k, v in status_mapping.items()}
    result = normalized.get(value.lower())
    if result is None:
        typer.echo("[WARN] Status mapping not found", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"-> internal: {result}")


if __name__ == "__main__":
    app()
