from __future__ import annotations

import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, cast

import pandas as pd
import psycopg2
import typer
from dotenv import load_dotenv
from loguru import logger
from pandas import errors as pd_errors
from psycopg2 import OperationalError
from psycopg2.extras import Json
from pydantic import BaseModel, Field, validator

from . import transforms
from .loaders import upsert_case, upsert_contact, upsert_judgment, upsert_party

app = typer.Typer(add_completion=False, help="Import JBI/Simplicity CSV exports into Postgres")

SOURCE_NAME = "simplicity_jbi_export"
DEFAULT_MAPPING_FILENAME = "jbi_import_mapping_template.csv"
MAX_RETRIES = 3

TRANSFORM_DISPATCH = {
    "normalize_docket": transforms.normalize_docket,
    "normalize_phone": transforms.normalize_phone,
    "namecase": transforms.namecase,
    "to_date": transforms.to_date,
}


class MappingRule(BaseModel):
    source: str = Field(..., description="Column name in source CSV")
    target: str = Field(..., description="Domain.field path")
    transform: Optional[str] = None
    required: bool = False

    @validator("source", "target", pre=True)
    def _strip(cls, value: Any) -> str:
        return (value or "").strip()

    @validator("target")
    def _require_dot(cls, value: str) -> str:
        if "." not in value:
            raise ValueError("target must be in 'domain.field' format")
        return value

    @validator("transform", pre=True)
    def _empty_transform(cls, value: Any) -> Optional[str]:
        text = (value or "").strip()
        return text if text else None

    @validator("required", pre=True)
    def _boolify(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "y"}


@dataclass
class EntityStats:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    def record(self, inserted_flag: Optional[bool]) -> None:
        if inserted_flag is True:
            self.inserted += 1
        elif inserted_flag is False:
            self.updated += 1
        else:
            self.skipped += 1

    def as_dict(self) -> Dict[str, int]:
        return {
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
        }


@dataclass
class RunStats:
    processed: int = 0
    validation_errors: int = 0
    row_errors: int = 0
    entities: Dict[str, EntityStats] = field(
        default_factory=lambda: {
            "cases": EntityStats(),
            "judgments": EntityStats(),
            "parties": EntityStats(),
            "contacts": EntityStats(),
        }
    )

    def as_metadata(self) -> Dict[str, Any]:
        return {
            "processed": self.processed,
            "validation_errors": self.validation_errors,
            "row_errors": self.row_errors,
            "entities": {name: stats.as_dict() for name, stats in self.entities.items()},
        }


class MappingError(RuntimeError):
    """Raised when mapping configuration is invalid."""


def configure_logging() -> None:
    logger.remove()
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.add(sys.stderr, level=level, serialize=False, diagnose=False, backtrace=False)


def load_env() -> None:
    load_dotenv(override=False)


def get_pg_url() -> str:
    pg_url = os.getenv("PG_URL") or os.getenv("DATABASE_URL")
    if not pg_url:
        raise typer.BadParameter(
            "PG_URL (or DATABASE_URL) must be set in the environment or .env file"
        )
    return pg_url


def get_conn(pg_url: str) -> psycopg2.extensions.connection:
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            conn = psycopg2.connect(pg_url)
            logger.success("✅ Connected to Postgres (attempt {})", attempt)
            return conn
        except OperationalError as exc:
            last_exc = exc
            wait_seconds = min(2**attempt, 10)
            logger.warning(
                "Database connection attempt %s/%s failed: %s — retrying in %ss",
                attempt,
                MAX_RETRIES,
                exc,
                wait_seconds,
            )
            time.sleep(wait_seconds)
    raise RuntimeError(f"Unable to connect to Postgres after {MAX_RETRIES} attempts: {last_exc}")


def _apply_transform(raw_value: Any, transform_spec: Optional[str]) -> Any:
    if raw_value is None:
        return ""
    value = str(raw_value).strip()
    if value == "":
        return ""
    if not transform_spec:
        return value
    name, _, arg = transform_spec.partition(":")
    func = TRANSFORM_DISPATCH.get(name)
    if func is None:
        raise MappingError(f"Unknown transform '{name}'")
    if name == "to_date":
        formats: Iterable[str] | None = [arg] if arg else None
        return func(value, formats=formats)
    return func(value)


def load_mapping(mapping_path: Path) -> List[MappingRule]:
    path_obj = Path(mapping_path)
    if not path_obj.is_file():
        raise typer.BadParameter(f"Mapping file not found: {path_obj}")
    try:
        frame = pd.read_csv(path_obj, dtype=str, keep_default_na=False).fillna("")
    except pd_errors.EmptyDataError as exc:
        raise typer.BadParameter(f"Mapping file {path_obj} is empty") from exc
    if frame.empty:
        raise typer.BadParameter(f"Mapping file {path_obj} has no rows")
    missing = {"source", "target"} - set(frame.columns)
    if missing:
        raise typer.BadParameter(f"Mapping file missing columns: {', '.join(sorted(missing))}")
    records = frame.to_dict(orient="records")
    return [MappingRule(**cast(Dict[str, Any], record)) for record in records]


def read_source_csv(file_path: Path, limit: Optional[int]) -> pd.DataFrame:
    if not file_path.exists():
        raise typer.BadParameter(f"CSV file not found: {file_path}")
    try:
        frame = pd.read_csv(file_path, dtype=str, keep_default_na=False).fillna("")
    except pd_errors.EmptyDataError:
        logger.warning("Source CSV contains no data: %s", file_path)
        frame = pd.DataFrame()
    if frame.empty:
        logger.warning("Source CSV contains no rows: %s", file_path)
    if limit is not None and limit > 0:
        frame = frame.head(limit)
    return frame


def _normalize_party_name(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[^0-9a-z]", "", value.lower())


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    cleaned = str(value).replace(",", "").replace("$", "").strip()
    if cleaned == "":
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        logger.warning("Unable to parse decimal value '%s'", value)
        return None


def build_payloads(
    row: Mapping[str, Any], rules: Sequence[MappingRule]
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    payloads: Dict[str, Dict[str, Any]] = defaultdict(dict)
    required_fields: Dict[str, List[str]] = defaultdict(list)

    for rule in rules:
        domain, field = rule.target.split(".", 1)
        transformed = _apply_transform(row.get(rule.source), rule.transform)
        if transformed not in ("", None):
            payloads[domain][field] = transformed
            if domain == "party" and field == "name_full":
                payloads[domain]["name_normalized"] = _normalize_party_name(str(transformed))
            if domain == "contact" and field == "contact_value":
                lower_source = rule.source.lower()
                if "phone" in lower_source or rule.transform == "normalize_phone":
                    payloads[domain].setdefault("contact_type", "phone")
                elif "email" in lower_source:
                    payloads[domain].setdefault("contact_type", "email")
        if rule.required:
            required_fields[domain].append(field)

    missing: List[str] = []
    for domain, fields in required_fields.items():
        missing_fields = transforms.validate_required(payloads.get(domain, {}), fields)
        missing.extend(f"{domain}.{field}" for field in missing_fields)
    return payloads, missing


def prepare_case_payload(data: Dict[str, Any], run_id: Optional[str]) -> Dict[str, Any]:
    if not data:
        raise ValueError("Missing case data")
    payload = {
        "case_number": data.get("case_number", ""),
        "court_name": data.get("court_name"),
        "county": (data.get("county") or "").strip(),
        "state": (data.get("state") or "CA").strip().upper(),
        "case_type": data.get("case_type"),
        "filing_date": (
            data.get("filing_date")
            if isinstance(data.get("filing_date"), date)
            else transforms.to_date(str(data.get("filing_date", "")))
        ),
        "case_status": data.get("case_status"),
        "case_url": data.get("case_url"),
        "metadata": data.get("metadata"),
        "ingestion_run_id": run_id,
    }
    return payload


def prepare_judgment_payload(
    data: Dict[str, Any], case_id: str, run_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    payload = {
        "case_id": case_id,
        "judgment_number": data.get("judgment_number"),
        "judgment_date": (
            data.get("judgment_date")
            if isinstance(data.get("judgment_date"), date)
            else transforms.to_date(str(data.get("judgment_date", "")))
        ),
        "amount_awarded": _to_decimal(data.get("amount_awarded")),
        "amount_remaining": _to_decimal(data.get("amount_remaining")),
        "interest_rate": _to_decimal(data.get("interest_rate")),
        "judgment_type": data.get("judgment_type"),
        "judgment_status": data.get("judgment_status"),
        "renewal_date": (
            data.get("renewal_date")
            if isinstance(data.get("renewal_date"), date)
            else transforms.to_date(str(data.get("renewal_date", "")))
        ),
        "expiration_date": (
            data.get("expiration_date")
            if isinstance(data.get("expiration_date"), date)
            else transforms.to_date(str(data.get("expiration_date", "")))
        ),
        "notes": data.get("notes"),
        "metadata": data.get("metadata"),
        "ingestion_run_id": run_id,
    }
    return payload


def prepare_party_payload(
    data: Dict[str, Any], case_id: str, run_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    payload = {
        "case_id": case_id,
        "party_type": (data.get("party_type") or "defendant").lower(),
        "party_role": data.get("party_role") or None,
        "is_business": data.get("is_business", False),
        "name_full": data.get("name_full"),
        "name_first": data.get("name_first"),
        "name_last": data.get("name_last"),
        "name_business": data.get("name_business"),
        "name_normalized": data.get("name_normalized"),
        "address_line1": data.get("address_line1"),
        "address_line2": data.get("address_line2"),
        "city": data.get("city"),
        "state": (data.get("state") or "").upper() if data.get("state") else None,
        "zip": data.get("zip"),
        "phone": data.get("phone"),
        "email": data.get("email"),
        "metadata": data.get("metadata"),
        "ingestion_run_id": run_id,
    }
    if not payload.get("name_normalized") and payload.get("name_full"):
        payload["name_normalized"] = _normalize_party_name(payload["name_full"])
    return payload


def prepare_contact_payload(
    data: Dict[str, Any], party_id: str, run_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    if not data:
        return None
    contact_value = str(data.get("contact_value") or "").strip()
    if not contact_value:
        return None
    payload = {
        "party_id": party_id,
        "contact_type": (data.get("contact_type") or "other").lower(),
        "contact_value": contact_value,
        "contact_label": data.get("contact_label"),
        "is_verified": data.get("is_verified", False),
        "is_primary": data.get("is_primary", False),
        "source": data.get("source") or SOURCE_NAME,
        "last_verified_at": data.get("last_verified_at"),
        "notes": data.get("notes"),
        "metadata": data.get("metadata"),
        "ingestion_run_id": run_id,
    }
    if payload["contact_type"] == "phone" and not payload["contact_value"].startswith("+"):
        normalized = transforms.normalize_phone(payload["contact_value"])
        if normalized:
            payload["contact_value"] = normalized
    return payload


def create_ingestion_run(
    conn: psycopg2.extensions.connection,
    file_path: Path,
    mapping_path: Path,
) -> str:
    run_key = f"jbi_import_{datetime.utcnow():%Y%m%d%H%M%S}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion.runs (run_key, source_name, status, metadata)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (
                run_key,
                SOURCE_NAME,
                "running",
                Json({"file": str(file_path), "mapping": str(mapping_path)}),
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to create ingestion run")
    conn.commit()
    return str(row[0])


def finalize_ingestion_run(
    conn: psycopg2.extensions.connection,
    run_id: str,
    status: str,
    stats: RunStats,
    errors: List[str],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion.runs
               SET completed_at = NOW(),
                   status = %s,
                   records_processed = %s,
                   records_inserted = %s,
                   records_updated = %s,
                   records_failed = %s,
                   error_log = %s,
                   metadata = COALESCE(metadata, '{}'::jsonb) || %s
             WHERE id = %s;
            """,
            (
                status,
                stats.processed,
                stats.entities["cases"].inserted
                + stats.entities["judgments"].inserted
                + stats.entities["parties"].inserted
                + stats.entities["contacts"].inserted,
                stats.entities["cases"].updated
                + stats.entities["judgments"].updated
                + stats.entities["parties"].updated
                + stats.entities["contacts"].updated,
                stats.row_errors + stats.validation_errors,
                Json(errors) if errors else None,
                Json({"summary": stats.as_metadata()}),
                run_id,
            ),
        )
    conn.commit()


def run_pipeline(
    file_path: Path,
    mapping_path: Path,
    *,
    dry_run: bool,
    limit: Optional[int],
) -> RunStats:
    configure_logging()
    load_env()
    pg_url = get_pg_url()
    conn = get_conn(pg_url)
    mapping_rules = load_mapping(mapping_path)
    frame = read_source_csv(file_path, limit)
    rows = [cast(Dict[str, Any], record) for record in frame.to_dict(orient="records")]

    stats = RunStats(processed=len(rows))
    row_errors: List[str] = []
    ingestion_run_id: Optional[str] = None

    if not dry_run:
        ingestion_run_id = create_ingestion_run(conn, file_path, mapping_path)

    try:
        for idx, row in enumerate(rows, start=1):
            payloads, missing = build_payloads(row, mapping_rules)
            if missing:
                stats.validation_errors += 1
                row_errors.append(f"row {idx}: missing {', '.join(missing)}")
                logger.error("Row %s validation failed: %s", idx, ", ".join(missing))
                continue

            with conn.cursor() as cur:
                cur.execute("SAVEPOINT jbi_row")

            try:
                case_payload = prepare_case_payload(payloads.get("case", {}), ingestion_run_id)
                case_id, case_inserted = upsert_case(conn, case_payload)
                stats.entities["cases"].record(case_inserted)

                judgment_payload = prepare_judgment_payload(
                    payloads.get("judgment", {}), case_id, ingestion_run_id
                )
                if judgment_payload:
                    _, inserted = upsert_judgment(conn, judgment_payload)
                    stats.entities["judgments"].record(inserted)
                else:
                    stats.entities["judgments"].record(None)

                party_payload = prepare_party_payload(
                    payloads.get("party", {}), case_id, ingestion_run_id
                )
                party_id: Optional[str] = None
                if party_payload:
                    party_id, inserted = upsert_party(conn, party_payload)
                    stats.entities["parties"].record(inserted)
                else:
                    stats.entities["parties"].record(None)

                contact_payload = None
                if party_id:
                    contact_payload = prepare_contact_payload(
                        payloads.get("contact", {}), party_id, ingestion_run_id
                    )
                if contact_payload:
                    _, inserted = upsert_contact(conn, contact_payload)
                    stats.entities["contacts"].record(inserted)
                else:
                    stats.entities["contacts"].record(None)

                with conn.cursor() as cur:
                    if dry_run:
                        cur.execute("ROLLBACK TO SAVEPOINT jbi_row")
                    cur.execute("RELEASE SAVEPOINT jbi_row")

            except Exception as exc:
                stats.row_errors += 1
                row_errors.append(f"row {idx}: {exc}")
                logger.exception("Row %s processing failed", idx)
                with conn.cursor() as cur:
                    cur.execute("ROLLBACK TO SAVEPOINT jbi_row")
                    cur.execute("RELEASE SAVEPOINT jbi_row")
                continue

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
            status = (
                "completed" if stats.row_errors == 0 and stats.validation_errors == 0 else "partial"
            )
            finalize_ingestion_run(conn, ingestion_run_id or "", status, stats, row_errors)
    finally:
        conn.close()

    return stats


def print_summary(stats: RunStats, *, dry_run: bool, file_path: Path, limit: Optional[int]) -> None:
    typer.echo("✅ Connected to Postgres")
    typer.echo(f"✅ Parsed {stats.processed} rows (file={file_path} limit={limit or 'all'})")
    if dry_run:
        typer.echo("DRY-RUN complete; no database changes were made.")
    prefix = "— Would write" if dry_run else "— Wrote"
    typer.echo(
        (
            f"{prefix}: "
            f"cases=I{stats.entities['cases'].inserted}/U{stats.entities['cases'].updated}/S{stats.entities['cases'].skipped}, "
            f"judgments=I{stats.entities['judgments'].inserted}/U{stats.entities['judgments'].updated}/S{stats.entities['judgments'].skipped}, "
            f"parties=I{stats.entities['parties'].inserted}/U{stats.entities['parties'].updated}/S{stats.entities['parties'].skipped}, "
            f"contacts=I{stats.entities['contacts'].inserted}/U{stats.entities['contacts'].updated}/S{stats.entities['contacts'].skipped}"
        )
    )
    if stats.validation_errors or stats.row_errors:
        typer.echo(
            f"⚠️ Validation errors: {stats.validation_errors} rows; row failures: {stats.row_errors} (see logs)",
            err=False,
        )
    else:
        typer.echo("✅ No validation errors")


@app.command()
def main(
    file: Path = typer.Option(..., "--file", "-f", help="Path to JBI export CSV"),
    mapping: Optional[Path] = typer.Option(
        None, "--mapping", help="Override default column mapping"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Process data without committing changes"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Limit number of rows for quick testing"
    ),
) -> None:
    try:
        mapping_path = (
            mapping or Path(__file__).resolve().parents[1] / "data" / DEFAULT_MAPPING_FILENAME
        )
        stats = run_pipeline(file, mapping_path, dry_run=dry_run, limit=limit)
        print_summary(stats, dry_run=dry_run, file_path=file, limit=limit)
    except typer.BadParameter as exc:
        typer.echo(f"❌ {exc}")
        raise typer.Exit(code=2) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("ETL run failed")
        typer.echo(f"❌ ETL failed: {exc}")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
