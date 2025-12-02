"""Import helpers for the JBI 900-case intake CSV."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import psycopg
from pydantic import ValidationError

from src.supabase_client import (
    create_supabase_client,
    get_supabase_db_url,
    get_supabase_env,
)

from .core_judgment_bridge import CoreJudgmentBridge
from .pipeline_support import (
    ContactSync,
    QueueJobManager,
    RawImportWriter,
    ensure_follow_up_task,
    initialize_enforcement_stage,
    sync_row_contacts,
)
from .simplicity_plaintiffs import (
    ParseIssue,
    SimplicityImportRow,
    _fetch_columns,
    _finalize_import_run,
    _find_existing_plaintiff,
    _insert_judgment,
    _insert_status_history,
    _judgment_exists,
    _start_import_run,
    _upload_csv_to_storage,
    _upsert_plaintiff,
)

logger = logging.getLogger(__name__)

JBI_LAST_PARSE_ERRORS: List[ParseIssue] = []
JBI_SOURCE_SYSTEM = "jbi_900"
JBI_IMPORT_KIND = "jbi_900_plaintiffs"
JBI_CREATED_BY = "jbi_900_import"
JBI_STORAGE_PREFIX = "jbi_900_imports"
STORAGE_BUCKET = "imports"

REQUIRED_HEADERS = {
    "case_number",
    "party_name",
    "judgment_amount",
}

OPTIONAL_HEADERS = {
    "case_status",
    "court_name",
    "county",
    "state",
    "filing_date",
    "judgment_date",
    "judgment_balance",
    "party_role",
    "party_type",
    "party_phone",
    "contact_type",
    "party_email",
}

HEADER_ALIASES = {
    "plaintiff_name": "party_name",
    "plaintiffname": "party_name",
    "plaintiff": "party_name",
    "creditor": "party_name",
    "creditor_name": "party_name",
    "creditor_full_name": "party_name",
    "casenumber": "case_number",
    "case_no": "case_number",
    "case": "case_number",
    "judgmentamount": "judgment_amount",
    "totaljudgmentamount": "judgment_amount",
    "total_judgment_amount": "judgment_amount",
    "judgementamount": "judgment_amount",
    "totaljudgementamount": "judgment_amount",
}


def _normalize_header(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip().lower()
    return text or None


def _canonicalize_header(value: Optional[str]) -> Optional[str]:
    normalized = _normalize_header(value)
    if normalized is None:
        return None
    return HEADER_ALIASES.get(normalized, normalized)


def _clean_cell(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _build_header_map(raw_headers: Sequence[str]) -> Dict[str, str]:
    header_map: Dict[str, str] = {}
    for raw in raw_headers:
        canonical = _canonicalize_header(raw)
        if canonical is None:
            continue
        header_map[raw] = canonical
    return header_map


def _format_missing_headers_message(
    missing: set[str], raw_headers: Sequence[str]
) -> str:
    provided = ", ".join(raw_headers) if raw_headers else "<none>"
    missing_list = ", ".join(sorted(missing))
    return (
        f"CSV is missing required logical column(s): {missing_list}. "
        f"Provided headers: {provided}"
    )


def _construct_payload(row: Dict[str, Optional[str]]) -> Dict[str, Any]:
    case_number = row.get("case_number")
    plaintiff_name = row.get("party_name")
    judgment_amount = row.get("judgment_amount")

    if not case_number:
        raise ValueError("case_number is required")
    if not plaintiff_name:
        raise ValueError("party_name is required")
    if not judgment_amount:
        raise ValueError("judgment_amount is required")

    payload: Dict[str, Any] = {
        "plaintiff_name": plaintiff_name,
        "plaintiff_phone": row.get("party_phone"),
        "plaintiff_email": row.get("party_email"),
        "judgment_number": case_number,
        "case_number": case_number,
        "judgment_amount": judgment_amount,
        "judgment_date": row.get("judgment_date"),
        "filing_date": row.get("filing_date"),
        "court_name": row.get("court_name"),
        "county": row.get("county"),
        "state": row.get("state"),
        "status": row.get("case_status"),
        "best_contact_method": row.get("contact_type"),
    }
    return payload


def parse_jbi_900_csv(path: str) -> List[SimplicityImportRow]:
    """Parse a JBI 900 intake CSV into the canonical plaintiff row model."""

    JBI_LAST_PARSE_ERRORS[:] = []
    rows: List[SimplicityImportRow] = []
    csv_path = Path(path)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file is missing a header row")

        raw_headers = reader.fieldnames
        header_map = _build_header_map(raw_headers)
        canonical_headers = set(header_map.values())
        missing = REQUIRED_HEADERS - canonical_headers
        if missing:
            raise ValueError(_format_missing_headers_message(missing, raw_headers))

        for index, raw_row in enumerate(reader, start=2):
            if raw_row is None:
                continue

            normalized_row: Dict[str, Optional[str]] = {}
            for key, value in raw_row.items():
                canonical_key = header_map.get(key)
                if canonical_key is None:
                    canonical_key = _canonicalize_header(key)
                    if canonical_key is not None:
                        header_map[key] = canonical_key
                if canonical_key is None:
                    continue
                cleaned_value = _clean_cell(value)
                if cleaned_value is None:
                    continue
                if canonical_key in normalized_row:
                    continue
                normalized_row[canonical_key] = cleaned_value

            if not any(normalized_row.get(header) for header in REQUIRED_HEADERS):
                continue

            try:
                payload = _construct_payload(normalized_row)
                payload["raw_row_number"] = index
                model = SimplicityImportRow.model_validate(payload)
                rows.append(model)
            except (ValidationError, ValueError) as exc:
                JBI_LAST_PARSE_ERRORS.append(
                    ParseIssue(
                        row_number=index,
                        error=str(exc),
                        raw=dict(raw_row),
                    )
                )

    return rows


def run_jbi_900_import(
    csv_path: str,
    batch_name: str,
    dry_run: bool = True,
    source_reference: str | None = None,
    *,
    connection: psycopg.Connection | None = None,
    storage_client: Any | None = None,
    enqueue_jobs: bool = True,
    skip_row_numbers: set[int] | None = None,
    enable_new_pipeline: bool = False,
) -> dict[str, Any]:
    """Ingest a JBI 900 CSV into Supabase plaintiffs/judgments.

    Args:
        csv_path: Path to the JBI 900 CSV file.
        batch_name: Label for this import batch.
        dry_run: If True, don't write to the database.
        source_reference: External reference for the import.
        connection: Optional psycopg connection to reuse.
        storage_client: Optional Supabase client for storage uploads.
        enqueue_jobs: If True, enqueue queue_job RPC calls.
        skip_row_numbers: Set of row numbers to skip (for resume support).
        enable_new_pipeline: If True, also insert into core_judgments to
            trigger the new enrichment pipeline via the judgment_enrich queue.
    """

    good_rows = parse_jbi_900_csv(csv_path)
    resume_hint: Dict[str, int] | None = None
    requested_skip_rows = {
        row_number
        for row_number in (skip_row_numbers or set())
        if isinstance(row_number, int) and row_number > 0
    }
    if requested_skip_rows:
        original_count = len(good_rows)
        good_rows = [
            row
            for row in good_rows
            if (row.raw_row_number or 0) not in requested_skip_rows
        ]
        resume_hint = {
            "requested_skip_rows": len(requested_skip_rows),
            "rows_dropped": max(original_count - len(good_rows), 0),
        }
    source_ref = source_reference or batch_name

    row_operations: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {
        "batch_name": batch_name,
        "source_reference": source_ref,
        "dry_run": dry_run,
        "row_operations": row_operations,
        "source_system": JBI_SOURCE_SYSTEM,
        "enable_new_pipeline": enable_new_pipeline,
    }
    if resume_hint:
        metadata["resume"] = resume_hint
    metadata["parse_errors"] = [
        {"row_number": issue.row_number, "error": issue.error}
        for issue in JBI_LAST_PARSE_ERRORS
    ]
    parse_errors = metadata["parse_errors"]

    metadata["queued_jobs"] = []
    metadata["raw_import_log"] = {"enabled": False}
    metadata["contact_inserts"] = {"primary": 0, "address": 0}
    metadata["follow_up_tasks"] = {"created": 0, "existing": 0}
    metadata["enforcement_initializations"] = 0
    metadata["core_judgments_bridge"] = {"enabled": enable_new_pipeline}

    if dry_run:
        metadata["planned_storage_path"] = (
            f"{JBI_STORAGE_PREFIX}/DRY_RUN/{Path(csv_path).name}"
        )

    row_count = len(good_rows) + len(parse_errors)
    insert_count = 0
    update_count = 0
    skipped_rows = 0
    row_failure_count = 0
    error_count = len(parse_errors)

    db_conn = connection
    managed_connection = False
    if db_conn is None:
        env = get_supabase_env()
        db_url = get_supabase_db_url(env)
        db_conn = psycopg.connect(db_url, autocommit=False)
        managed_connection = True

    import_run_id: Optional[str] = None

    raw_writer: RawImportWriter | None = None
    contact_sync: ContactSync | None = None
    queue_manager: QueueJobManager | None = None
    core_judgment_bridge: CoreJudgmentBridge | None = None

    contact_totals = {"primary": 0, "address": 0}
    follow_up_totals = {"created": 0, "existing": 0}
    enforcement_initializations = 0
    core_judgments_stats = {"inserted": 0, "skipped": 0, "errors": 0}

    def _record_row_status(
        row_model: SimplicityImportRow,
        status: str,
        error: Optional[str] = None,
    ) -> Optional[int]:
        if raw_writer is None:
            return None
        return raw_writer.record(
            row_number=row_model.raw_row_number or 0,
            payload=row_model.model_dump(mode="json"),
            status=status,
            batch_name=batch_name,
            source_system=JBI_SOURCE_SYSTEM,
            source_reference=source_ref,
            error=error,
        )

    def _refresh_runtime_metadata() -> None:
        metadata["contact_inserts"] = dict(contact_totals)
        metadata["follow_up_tasks"] = dict(follow_up_totals)
        metadata["enforcement_initializations"] = enforcement_initializations
        metadata["queued_jobs"] = (
            queue_manager.summary() if queue_manager is not None else []
        )
        metadata["raw_import_log"] = (
            raw_writer.summary() if raw_writer is not None else {"enabled": False}
        )
        if core_judgment_bridge is not None:
            metadata["core_judgments_bridge"] = core_judgment_bridge.summary()
        else:
            metadata["core_judgments_bridge"] = {
                "enabled": enable_new_pipeline,
                **core_judgments_stats,
            }

    try:
        if not dry_run:
            with db_conn.cursor() as cur:
                import_run_id = _start_import_run(
                    cur,
                    csv_path=Path(csv_path),
                    batch_name=batch_name,
                    dry_run=dry_run,
                    source_reference=source_ref,
                    import_kind=JBI_IMPORT_KIND,
                    source_system=JBI_SOURCE_SYSTEM,
                    created_by=JBI_CREATED_BY,
                )
            db_conn.commit()

            supabase_client = storage_client or create_supabase_client(
                get_supabase_env()
            )
            storage_path = f"{JBI_STORAGE_PREFIX}/{import_run_id}/{Path(csv_path).name}"
            try:
                _upload_csv_to_storage(
                    supabase_client=supabase_client,
                    bucket=STORAGE_BUCKET,
                    storage_path=storage_path,
                    csv_path=Path(csv_path),
                )
            except Exception as exc:  # noqa: BLE001
                metadata["upload_error"] = str(exc)
                raise
            else:
                metadata["storage_path"] = storage_path
                with db_conn.cursor() as cur:
                    cur.execute(
                        "update public.import_runs set storage_path = %s where id = %s",
                        (storage_path, import_run_id),
                    )
                db_conn.commit()

            raw_writer = RawImportWriter(db_conn)
            contact_sync = ContactSync(db_conn)
            queue_manager = QueueJobManager(db_conn) if enqueue_jobs else None

            # Initialize core_judgments bridge if new pipeline is enabled
            if enable_new_pipeline:
                core_judgment_bridge = CoreJudgmentBridge(db_conn)
                logger.info(
                    "core_judgments_bridge_enabled batch=%s source=%s",
                    batch_name,
                    JBI_SOURCE_SYSTEM,
                )

            if JBI_LAST_PARSE_ERRORS:
                for idx, issue in enumerate(JBI_LAST_PARSE_ERRORS):
                    record_id = raw_writer.record(
                        row_number=issue.row_number,
                        payload=issue.raw or {},
                        status="parse_error",
                        batch_name=batch_name,
                        source_system=JBI_SOURCE_SYSTEM,
                        source_reference=source_ref,
                        error=issue.error,
                    )
                    if idx < len(parse_errors):
                        parse_errors[idx]["raw_import_id"] = record_id

        judgment_columns: set[str] = set()
        if not dry_run:
            judgment_columns = _fetch_columns(db_conn, "judgments")
            if not judgment_columns:
                raise RuntimeError("public.judgments table is not accessible")

        for row in good_rows:
            case_number = row.case_number or row.judgment_number
            operation: Dict[str, Any] = {
                "row_number": row.raw_row_number,
                "case_number": case_number,
                "judgment_number": row.judgment_number,
            }

            with db_conn.cursor() as cur:
                duplicate = _judgment_exists(
                    cur,
                    judgment_number=row.judgment_number,
                    case_number=case_number,
                )
                existing_plaintiff = _find_existing_plaintiff(
                    cur,
                    name=row.plaintiff_name,
                    email=row.plaintiff_email,
                    phone=row.plaintiff_phone,
                )

            if duplicate:
                skipped_rows += 1
                operation["action"] = "skip_existing_judgment"
                operation["status"] = "skipped"
                if not dry_run:
                    operation["raw_import_id"] = _record_row_status(row, "skipped")
                row_operations.append(operation)
                continue

            action_name = (
                "attach_judgment_to_existing_plaintiff"
                if existing_plaintiff
                else "create_plaintiff_and_judgment"
            )
            operation["action"] = action_name
            operation["new_plaintiff"] = existing_plaintiff is None
            if existing_plaintiff:
                operation["existing_plaintiff_id"] = existing_plaintiff["id"]

            if dry_run:
                operation["status"] = "planned"
                row_operations.append(operation)
                continue

            contacts_info: Optional[Dict[str, int]] = None
            follow_up_result: Optional[Dict[str, Any]] = None
            enforcement_set = False
            queued_jobs: List[Dict[str, Any]] = []

            try:
                with db_conn.transaction():
                    with db_conn.cursor() as cur:
                        plaintiff_id, created = _upsert_plaintiff(
                            cur,
                            row,
                            dry_run=False,
                            existing=existing_plaintiff,
                            source_system=JBI_SOURCE_SYSTEM,
                        )
                        judgment_id = _insert_judgment(
                            cur,
                            row=row,
                            plaintiff_id=plaintiff_id,
                            judgment_columns=judgment_columns,
                        )
                        if plaintiff_id is not None:
                            _insert_status_history(
                                cur,
                                plaintiff_id=plaintiff_id,
                                batch_name=batch_name,
                                note_prefix="JBI 900 intake",
                                changed_by=JBI_CREATED_BY,
                            )

                if contact_sync is not None and plaintiff_id is not None:
                    contacts_info = sync_row_contacts(
                        contact_sync,
                        plaintiff_id=plaintiff_id,
                        row=row,
                    )
                    for key, value in contacts_info.items():
                        contact_totals[key] += value

                if plaintiff_id is not None:
                    follow_up_result = ensure_follow_up_task(
                        db_conn,
                        plaintiff_id=plaintiff_id,
                        batch_name=batch_name,
                        created_by=JBI_CREATED_BY,
                    )
                    if follow_up_result.get("created"):
                        follow_up_totals["created"] += 1
                    else:
                        follow_up_totals["existing"] += 1

                if judgment_id is not None:
                    enforcement_set = initialize_enforcement_stage(
                        db_conn,
                        judgment_id=judgment_id,
                        actor=JBI_CREATED_BY,
                        note="JBI importer initialization",
                    )
                    if enforcement_set:
                        enforcement_initializations += 1

                # Insert into core_judgments if new pipeline is enabled
                # This triggers the judgment_enrich queue via DB trigger
                core_judgment_result = None
                if core_judgment_bridge is not None and judgment_id is not None:
                    core_judgment_result = core_judgment_bridge.insert_judgment(
                        case_index_number=case_number,
                        debtor_name=row.defendant_name,
                        original_creditor=row.plaintiff_name,
                        judgment_date=row.judgment_date or row.filing_date,
                        principal_amount=row.judgment_amount,
                        court_name=row.court_name,
                        county=row.county,
                    )
                    if core_judgment_result.inserted:
                        core_judgments_stats["inserted"] += 1
                        operation["core_judgment_id"] = core_judgment_result.judgment_id
                    elif core_judgment_result.skipped:
                        core_judgments_stats["skipped"] += 1
                        operation["core_judgment_skipped"] = True
                        if core_judgment_result.judgment_id:
                            operation["core_judgment_id"] = (
                                core_judgment_result.judgment_id
                            )
                    elif core_judgment_result.error:
                        core_judgments_stats["errors"] += 1
                        operation["core_judgment_error"] = core_judgment_result.error

                if queue_manager is not None and judgment_id is not None:
                    queued_jobs.append(
                        queue_manager.enqueue(
                            kind="enrich",
                            payload={
                                "plaintiff_id": plaintiff_id,
                                "judgment_id": judgment_id,
                                "source": JBI_SOURCE_SYSTEM,
                                "batch_name": batch_name,
                                "source_reference": source_ref,
                            },
                            idempotency_key=f"jbi:enrich:{judgment_id}",
                        )
                    )
                    queued_jobs.append(
                        queue_manager.enqueue(
                            kind="enforce",
                            payload={
                                "plaintiff_id": plaintiff_id,
                                "judgment_id": judgment_id,
                                "source": JBI_SOURCE_SYSTEM,
                                "batch_name": batch_name,
                                "source_reference": source_ref,
                            },
                            idempotency_key=f"jbi:enforce:{judgment_id}",
                        )
                    )

                insert_count += 1
                operation["status"] = "inserted"
                operation["plaintiff_id"] = plaintiff_id
                operation["judgment_id"] = judgment_id
                operation["new_plaintiff"] = created
            except Exception as exc:  # noqa: BLE001
                row_failure_count += 1
                error_count += 1
                operation["status"] = "error"
                operation["error"] = str(exc)
                logger.exception("jbi 900 import row failure", exc_info=exc)
            finally:
                if not dry_run:
                    raw_id = _record_row_status(
                        row,
                        operation.get("status", "error"),
                        operation.get("error"),
                    )
                    if raw_id is not None:
                        operation["raw_import_id"] = raw_id

            if contacts_info is not None:
                operation["contacts"] = contacts_info
            if follow_up_result:
                operation["follow_up_task"] = follow_up_result
            operation["enforcement_stage_initialized"] = enforcement_set
            if queued_jobs:
                operation["queued_jobs"] = queued_jobs

            row_operations.append(operation)

        metadata["summary"] = {
            "row_count": row_count,
            "insert_count": insert_count,
            "update_count": update_count,
            "error_count": error_count,
            "skipped_rows": skipped_rows,
            "row_failures": row_failure_count,
            "total_rows": row_count,
            "inserted_rows": insert_count,
            "error_rows": error_count,
        }

        summary_block: Dict[str, Any] = metadata["summary"]
        summary_block["contact_inserts"] = dict(contact_totals)
        summary_block["follow_up_tasks"] = dict(follow_up_totals)
        summary_block["enforcement_initializations"] = enforcement_initializations

        _refresh_runtime_metadata()

        if not dry_run and import_run_id is not None:
            status = "completed"
            with db_conn.cursor() as cur:
                _finalize_import_run(
                    cur,
                    import_run_id=import_run_id,
                    batch_name=batch_name,
                    dry_run=dry_run,
                    status=status,
                    row_count=row_count,
                    insert_count=insert_count,
                    update_count=update_count,
                    error_count=error_count,
                    source_reference=source_ref,
                    metadata=metadata,
                )
            db_conn.commit()
        elif dry_run and managed_connection:
            db_conn.rollback()
    except Exception as exc:
        if managed_connection:
            db_conn.rollback()
            if import_run_id is not None and not dry_run:
                metadata["exception"] = str(exc)
                metadata.setdefault(
                    "summary",
                    {
                        "row_count": row_count,
                        "insert_count": insert_count,
                        "update_count": update_count,
                        "error_count": error_count,
                        "skipped_rows": skipped_rows,
                        "row_failures": row_failure_count,
                        "total_rows": row_count,
                        "inserted_rows": insert_count,
                        "error_rows": error_count,
                    },
                )
                _refresh_runtime_metadata()
                try:
                    with db_conn.cursor() as cur:
                        _finalize_import_run(
                            cur,
                            import_run_id=import_run_id,
                            batch_name=batch_name,
                            dry_run=dry_run,
                            status="failed",
                            row_count=row_count,
                            insert_count=insert_count,
                            update_count=update_count,
                            error_count=error_count,
                            source_reference=source_ref,
                            metadata=metadata,
                        )
                    db_conn.commit()
                except Exception:
                    db_conn.rollback()
        raise
    finally:
        if managed_connection:
            db_conn.close()

    _refresh_runtime_metadata()

    return {
        "import_run_id": import_run_id,
        "total_rows": row_count,
        "inserted_rows": insert_count,
        "skipped_rows": skipped_rows,
        "error_rows": error_count,
        "row_count": row_count,
        "insert_count": insert_count,
        "update_count": update_count,
        "error_count": error_count,
        "dry_run": dry_run,
        "metadata": metadata,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import the 900-case JBI intake CSV into Supabase plaintiffs/judgments",
    )
    parser.add_argument("csv", help="Path to the JBI export CSV")
    parser.add_argument(
        "--batch-name",
        help="Label recorded in import_runs metadata (defaults to CSV stem)",
    )
    parser.add_argument(
        "--source-reference",
        help="External identifier describing the file (defaults to batch name)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Apply changes instead of running in dry-run mode",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        parser.error(f"CSV file not found: {csv_path}")

    batch_name = args.batch_name or csv_path.stem
    result = run_jbi_900_import(
        str(csv_path),
        batch_name=batch_name,
        dry_run=not args.commit,
        source_reference=args.source_reference,
    )
    json.dump(result, sys.stdout, indent=2, sort_keys=True, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI passthrough
    raise SystemExit(main())
