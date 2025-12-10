"""Bulk intake helper for ~900 plaintiff CSV uploads.

Expected CSV columns (case-insensitive):

- ``case_number`` (required, non-empty)
- ``court``
- ``plaintiff_name``
- ``defendant_name``
- ``judgment_amount`` (decimal string, e.g. ``18750.00``)
- ``judgment_date`` (ISO format ``YYYY-MM-DD``)
- ``source`` (optional when ``--source-tag`` is provided)

Each row is normalized into the payload shape that ``etl.src.collector_v1``
submits to the ``insert_or_get_case`` RPC. When ``--enqueue-enrich`` remains
enabled (default), the script also queues a follow-up ``enrich`` job per case
using the existing ``queue_job`` RPC contract.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.src.models import CaseIn
from src.supabase_client import create_supabase_client, get_supabase_env

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImportConfig:
    csv_path: Path
    dry_run: bool
    source_tag: str | None
    enqueue_enrich: bool


@dataclass(slots=True)
class ImportSummary:
    total_rows: int = 0
    inserted: int = 0
    reused: int = 0
    errors: int = 0
    queued: int = 0

    def log(self, env: str) -> None:
        logger.info(
            "import_summary env=%s total=%d inserted=%d reused=%d errors=%d queued=%d",
            env,
            self.total_rows,
            self.inserted,
            self.reused,
            self.errors,
            self.queued,
        )


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk import cases from a CSV file.")
    parser.add_argument(
        "--csv",
        dest="csv_path",
        required=True,
        help="Path to the CSV file to import",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse rows and log the intended actions without calling Supabase RPCs",
    )
    parser.add_argument(
        "--source-tag",
        default=None,
        help="Override the source column for all rows (default: use CSV source column)",
    )
    enqueue_action = getattr(argparse, "BooleanOptionalAction", None)
    if enqueue_action:
        parser.add_argument(
            "--enqueue-enrich",
            action=enqueue_action,
            default=True,
            help="Queue enrichment jobs for each case (default: enabled)",
        )
    else:  # pragma: no cover - Python < 3.9 safeguard
        parser.add_argument(
            "--enqueue-enrich",
            dest="enqueue_enrich",
            action="store_true",
            default=True,
            help="Queue enrichment jobs for each case (default: enabled)",
        )
        parser.add_argument(
            "--no-enqueue-enrich",
            dest="enqueue_enrich",
            action="store_false",
            help="Skip queueing enrichment jobs",
        )
    return parser.parse_args(argv)


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def _parse_amount(raw: str | None) -> float | None:
    cleaned = _clean(raw)
    if not cleaned:
        return None
    try:
        normalized = cleaned.replace(",", "")
        return float(Decimal(normalized))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid judgment_amount value: {raw!r}") from exc


def _parse_judgment_date(raw: str | None) -> date | None:
    cleaned = _clean(raw)
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid judgment_date value: {raw!r}") from exc


def _build_case_payload(
    row: dict[str, str], config: ImportConfig
) -> tuple[dict[str, Any], str, str]:
    case_number = _clean(row.get("case_number"))
    if not case_number:
        raise ValueError("case_number is required")

    csv_source = _clean(row.get("source"))
    source = config.source_tag or csv_source
    if not source:
        raise ValueError("source is required (provide --source-tag to override)")

    court = _clean(row.get("court")) or None
    plaintiff = _clean(row.get("plaintiff_name")) or None
    defendant = _clean(row.get("defendant_name")) or None
    amount = _parse_amount(row.get("judgment_amount"))
    judgment_date = _parse_judgment_date(row.get("judgment_date"))

    title_parts = [name for name in (plaintiff, defendant) if name]
    title = " v. ".join(title_parts) if title_parts else None

    case = CaseIn(
        case_number=case_number,
        source=source,
        court=court,
        title=title,
        judgment_date=judgment_date,
        amount_awarded=amount,
    )
    payload = case.model_dump(mode="json", exclude_none=True)

    metadata: dict[str, Any] = {"importer": "bulk_csv"}
    if plaintiff:
        metadata["plaintiff_name"] = plaintiff
    if defendant:
        metadata["defendant_name"] = defendant
    if metadata:
        payload["metadata"] = metadata

    return payload, case_number, source


def _extract_case_id(data: Any) -> str | None:
    if not data:
        return None
    if isinstance(data, dict):
        for key in ("case_id", "insert_or_get_case", "id", "caseId"):
            value = data.get(key)  # type: ignore[arg-type]
            if value:
                return str(value)
        nested = data.get("data")
        if isinstance(nested, (dict, list)):
            return _extract_case_id(nested)
        payload = data.get("payload")
        if isinstance(payload, (dict, list)):
            return _extract_case_id(payload)
    if isinstance(data, list) and data:
        return _extract_case_id(data[0])
    if isinstance(data, str):
        return data
    return None


def _classify_status(data: Any) -> str:
    if isinstance(data, dict):
        for key in (
            "status",
            "result",
            "outcome",
            "was_created",
            "was_inserted",
            "created",
        ):
            if key in data:
                value = data[key]
                if isinstance(value, bool):
                    return "inserted" if value else "reused"
                if isinstance(value, str):
                    lowered = value.lower()
                    if lowered in {"existing", "exists", "reused", "duplicate"}:
                        return "reused"
                    if lowered in {"inserted", "created", "new"}:
                        return "inserted"
    return "inserted"


def _queue_enrich(client: Any, case_number: str, case_id: str | None, source: str) -> None:
    envelope = {
        "payload": {
            "kind": "enrich",
            "payload": {
                k: v for k, v in {"case_number": case_number, "case_id": case_id}.items() if v
            },
            "idempotency_key": f"{source}:{case_number}",
        }
    }
    client.rpc("queue_job", envelope).execute()


def _normalize_headers(fieldnames: list[str] | None) -> list[str] | None:
    if not fieldnames:
        return None
    return [(_clean(name).lower()) for name in fieldnames if name]


def _normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return {(_clean(key).lower() if key else ""): (value or "") for key, value in row.items()}


def import_cases(config: ImportConfig, env: str, *, client: Any | None = None) -> ImportSummary:
    summary = ImportSummary()

    if not config.csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {config.csv_path}")

    if config.dry_run:
        logger.info("Dry run enabled; Supabase RPC calls will be skipped")

    supabase = client
    if not config.dry_run:
        if supabase is None:
            supabase = create_supabase_client(env=env)
        if supabase is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Supabase client not initialized")

    with config.csv_path.open(mode="r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        reader.fieldnames = _normalize_headers(reader.fieldnames)
        if reader.fieldnames is None:
            logger.error("CSV file %s has no header row", config.csv_path)
            summary.errors += 1
            summary.log(env)
            return summary

        for row_number, raw_row in enumerate(reader, start=2):
            row = _normalize_row(raw_row)
            summary.total_rows += 1

            try:
                payload, case_number, source = _build_case_payload(row, config)
            except ValueError as exc:
                logger.error("row_invalid row=%d error=%s", row_number, exc)
                summary.errors += 1
                continue

            if config.dry_run:
                logger.info(
                    "dry_run row=%d case=%s payload=%s",
                    row_number,
                    case_number,
                    payload,
                )
                continue

            try:
                response = supabase.rpc("insert_or_get_case", {"payload": payload}).execute()
                data = getattr(response, "data", None)
                case_id = _extract_case_id(data)
                status = _classify_status(data)
                if status == "reused":
                    summary.reused += 1
                else:
                    summary.inserted += 1
                logger.info(
                    "case_processed row=%d case=%s status=%s case_id=%s",
                    row_number,
                    case_number,
                    status,
                    case_id,
                )

                if config.enqueue_enrich:
                    try:
                        _queue_enrich(supabase, case_number, case_id, source)
                        summary.queued += 1
                        logger.info(
                            "enrich_enqueued case=%s case_id=%s idempotency=%s",
                            case_number,
                            case_id,
                            f"{source}:{case_number}",
                        )
                    except Exception as exc:  # pragma: no cover - queue RPC issues
                        summary.errors += 1
                        logger.warning("enrich_queue_failed case=%s error=%s", case_number, exc)
            except Exception as exc:  # pragma: no cover - Supabase/network errors
                logger.error("row_failed row=%d case=%s error=%s", row_number, case_number, exc)
                summary.errors += 1

    summary.log(env)
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(argv)
    config = ImportConfig(
        csv_path=Path(args.csv_path),
        dry_run=args.dry_run,
        source_tag=_clean(args.source_tag) or None,
        enqueue_enrich=getattr(args, "enqueue_enrich", True),
    )

    env = get_supabase_env()
    logger.info(
        "starting_bulk_import csv=%s dry_run=%s enqueue_enrich=%s supabase_env=%s",
        config.csv_path,
        config.dry_run,
        config.enqueue_enrich,
        env,
    )

    try:
        summary = import_cases(config, env, client=None)
    except Exception as exc:  # pragma: no cover - CLI level guard
        logger.error("bulk_import_failed error=%s", exc)
        return 1

    print(
        "Summary: total={total} inserted={inserted} reused={reused} errors={errors} queued={queued}".format(
            total=summary.total_rows,
            inserted=summary.inserted,
            reused=summary.reused,
            errors=summary.errors,
            queued=summary.queued,
        )
    )

    return 0 if summary.errors == 0 else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    exit_code = main()
    # Demo validation commands (PowerShell):
    #   $env:SUPABASE_MODE='demo'; python scripts/import_cases_from_csv.py --csv intake_900.csv --dry-run
    #   $env:SUPABASE_MODE='demo'; python scripts/import_cases_from_csv.py --csv intake_900.csv --enqueue-enrich
    raise SystemExit(exit_code)
