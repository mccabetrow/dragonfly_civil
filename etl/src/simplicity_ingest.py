"""Load Simplicity CSV exports into Supabase via insert_case."""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Sequence

import psycopg
from psycopg import Connection
from psycopg.types.json import Json

from .foil_utils import _resolve_db_url

# Column aliases let us tolerate different Simplicity headers until we see a sample export.
# Each entry should list every header variant we expect to encounter; update the TODO notes once
# the actual column names are confirmed.
FIELD_ALIASES: dict[str, list[str]] = {
    # TODO: confirm this maps from the Simplicity "Case Number" column.
    "case_number": ["case_number", "case_no", "index_number", "case"],
    # TODO: confirm this maps from the Simplicity docket number column.
    "docket_number": ["docket_number", "docket_no", "docket"],
    # TODO: confirm this maps from the Simplicity case title / caption column.
    "title": ["title", "case_title"],
    # TODO: confirm this maps from the Simplicity court name column.
    "court": ["court", "court_name"],
    # TODO: confirm this maps from the Simplicity filing date column.
    "filing_date": ["filing_date", "filed", "filing"],
    # TODO: confirm this maps from the Simplicity judgment date column.
    "judgment_date": ["judgment_date", "judgement_date", "judgmentdate", "judgment"],
    # TODO: confirm this maps from the Simplicity amount awarded column.
    "amount_awarded": ["amount_awarded", "judgment_amount", "amount"],
}

DEFAULT_SOURCE = "simplicity"


@dataclass(slots=True)
class IngestResult:
    """Summary of a Simplicity ingest run."""

    processed: int = 0
    inserted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "processed": self.processed,
            "inserted": self.inserted,
            "failed": self.failed,
            "errors": list(self.errors),
        }


def _normalise_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_")


def _coerce_row(row: dict[str, str | None]) -> dict[str, str]:
    normalised: dict[str, str] = {}
    for raw_key, raw_value in row.items():
        if raw_key is None:
            continue
        key = _normalise_key(raw_key)
        value = (raw_value or "").strip()
        normalised[key] = value
    return normalised


def _first_value(row: dict[str, str], aliases: Iterable[str]) -> str:
    for alias in aliases:
        key = _normalise_key(alias)
        value = row.get(key)
        if value:
            return value
    return ""


def _normalise_date(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unable to parse date '{value}'")


def _normalise_amount(value: str) -> str | None:
    text = value.replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return str(Decimal(text))
    except InvalidOperation as exc:
        raise ValueError(f"Unable to parse amount '{value}'") from exc


def map_row_to_insert_case_payload(row: dict[str, str], *, source: str) -> dict[str, object]:
    """Translate a normalised CSV row (see :func:`_coerce_row`) into the public.insert_case payload."""

    case_number = _first_value(row, FIELD_ALIASES["case_number"])
    if not case_number:
        raise ValueError("Missing case_number")

    docket_number = _first_value(row, FIELD_ALIASES["docket_number"])
    # TODO: confirm this maps from the Simplicity docket number column.
    title = _first_value(row, FIELD_ALIASES["title"])
    # TODO: confirm this maps from the Simplicity case title / caption column.
    court = _first_value(row, FIELD_ALIASES["court"])
    # TODO: confirm this maps from the Simplicity court name column.
    filing_raw = _first_value(row, FIELD_ALIASES["filing_date"])
    # TODO: confirm this maps from the Simplicity filing date column.
    judgment_raw = _first_value(row, FIELD_ALIASES["judgment_date"])
    # TODO: confirm this maps from the Simplicity judgment date column.
    amount_raw = _first_value(row, FIELD_ALIASES["amount_awarded"])
    # TODO: confirm this maps from the Simplicity amount awarded column.

    payload: dict[str, object] = {
        "case_number": case_number,
        "source": source,
        "docket_number": docket_number or None,
        "title": title or None,
        "court": court or None,
        "filing_date": _normalise_date(filing_raw) if filing_raw else None,
        "judgment_date": _normalise_date(judgment_raw) if judgment_raw else None,
        "amount_awarded": _normalise_amount(amount_raw),
    }

    return payload


def _insert_case(
    conn: Connection,
    row: dict[str, str],
    *,
    source: str,
    savepoint: str | None,
) -> None:
    payload = map_row_to_insert_case_payload(row, source=source)
    with conn.cursor() as cur:
        if not conn.autocommit and savepoint:
            cur.execute(f"SAVEPOINT {savepoint}")  # type: ignore[arg-type]
        try:
            # Go through the canonical RPC so downstream casing/party logic stays consistent.
            cur.execute("select public.insert_case(%s::jsonb)", (Json(payload),))
        except Exception:
            if not conn.autocommit and savepoint:
                cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")  # type: ignore[arg-type]
                cur.execute(f"RELEASE SAVEPOINT {savepoint}")  # type: ignore[arg-type]
            raise
        else:
            if not conn.autocommit and savepoint:
                cur.execute(f"RELEASE SAVEPOINT {savepoint}")  # type: ignore[arg-type]


def ingest_file(
    input_path: Path,
    *,
    source: str = DEFAULT_SOURCE,
    conn: Connection | None = None,
) -> IngestResult:
    if not input_path.exists():
        raise FileNotFoundError(f"CSV file not found: {input_path}")

    owned_conn: Connection | None = None
    if conn is None:
        db_url = _resolve_db_url()
        owned_conn = psycopg.connect(db_url, autocommit=True)
        conn = owned_conn

    result = IngestResult()

    try:
        with input_path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("CSV file is missing a header row")

            for index, raw_row in enumerate(reader, start=1):
                if not raw_row or all((value or "").strip() == "" for value in raw_row.values()):
                    continue

                result.processed += 1

                normalised = _coerce_row(raw_row)
                savepoint_name = None if conn.autocommit else f"simplicity_ingest_{index}"

                try:
                    _insert_case(conn, normalised, source=source, savepoint=savepoint_name)
                except ValueError as exc:  # Raised by map_row_to_insert_case_payload
                    result.failed += 1
                    result.errors.append(f"row {index}: {exc}")
                    continue
                except Exception as exc:  # noqa: BLE001 - capture errors per row
                    result.failed += 1
                    result.errors.append(f"row {index}: {exc}")
                    continue

                result.inserted += 1
    finally:
        if owned_conn is not None:
            owned_conn.close()

    return result


def _default_input_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    candidate = root / "data_in" / "simplicity_export.csv"
    return candidate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Simplicity CSV exports into Supabase")
    parser.add_argument(
        "--input",
        dest="input_path",
        default=str(_default_input_path()),
        help="Path to Simplicity CSV export (default: data_in/simplicity_export.csv)",
    )
    parser.add_argument(
        "--source",
        dest="source",
        default=DEFAULT_SOURCE,
        help="Override source name stored on cases (default: simplicity)",
    )
    args = parser.parse_args(argv)

    result = ingest_file(Path(args.input_path), source=args.source)

    print(
        f"Processed {result.processed} rows; inserted {result.inserted}; failed {result.failed}",
        file=sys.stdout,
    )
    if result.errors:
        for message in result.errors:
            print(f"ERROR: {message}", file=sys.stderr)
    return 0 if result.success else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
