from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List

import psycopg
from psycopg import errors as psycopg_errors
from psycopg.abc import Query

from etl.src.importers.jbi_900 import run_jbi_900_import
from etl.src.importers.simplicity_plaintiffs import run_simplicity_import


def _resolve_db_url() -> str:
    explicit = Path(".env.test")
    if explicit.is_file():
        for line in explicit.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("SUPABASE_DB_URL="):
                return stripped.split("=", 1)[1]

    env_url = os.getenv("SUPABASE_DB_URL")
    if env_url:
        return env_url

    fallback_url = os.getenv("SUPABASE_URL")
    if fallback_url:
        return fallback_url

    raise RuntimeError(
        "SUPABASE_DB_URL not configured; set SUPABASE_DB_URL or create .env.test."
    )


def _write_csv(tmp_path: Path, rows: List[str]) -> Path:
    csv_path = tmp_path / "simplicity_plaintiffs.csv"
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    return csv_path


def _write_jbi_csv(tmp_path: Path, rows: List[str]) -> Path:
    csv_path = tmp_path / "jbi_900.csv"
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    return csv_path


JBI_HEADER = (
    "case_number,case_status,court_name,county,state,filing_date,judgment_date,"
    "judgment_amount,judgment_balance,party_role,party_type,party_name,party_phone,"
    "contact_type,party_email"
)


class FakeStorageBucket:
    def __init__(self, tracker: list[dict[str, Any]]):
        self._tracker = tracker

    def upload(
        self,
        path: str,
        payload: bytes,
        file_options: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        self._tracker.append(
            {
                "path": path,
                "payload": payload,
                "file_options": file_options or {},
            }
        )
        return SimpleNamespace(status_code=200, error=None)


class FakeStorageManager:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.buckets: list[str] = []

    def from_(self, bucket: str) -> FakeStorageBucket:
        self.buckets.append(bucket)
        return FakeStorageBucket(self.uploads)


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.storage = FakeStorageManager()


def _fetch_scalar(
    conn: psycopg.Connection,
    query: Query,
    params: Iterable[Any] | None = None,
) -> Any:
    with conn.cursor() as cur:
        if params is None:
            cur.execute(query)
        else:
            cur.execute(query, tuple(params))
        row = cur.fetchone()
    assert row is not None
    return row[0]


def _collect_queue_jobs(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = result.get("metadata") or {}
    jobs: List[Dict[str, Any]] = list(metadata.get("queued_jobs") or [])
    for operation in metadata.get("row_operations", []):
        jobs.extend(operation.get("queued_jobs") or [])
    return jobs


def _cleanup_queue_jobs(
    conn: psycopg.Connection,
    jobs: Iterable[Dict[str, Any]],
) -> None:
    queue_map = {
        "enrich": "q_enrich",
        "enforce": "q_enforce",
        "outreach": "q_outreach",
        "case_copilot": "q_case_copilot",
    }
    with conn.cursor() as cur:
        for job in jobs:
            if job.get("status") != "queued":
                continue
            kind = job.get("kind")
            if not isinstance(kind, str):
                continue
            queue_name = queue_map.get(kind)
            message_id = job.get("message_id")
            if not queue_name or message_id is None:
                continue
            try:
                cur.execute(
                    "select public.pgmq_delete(%s, %s)",
                    (queue_name, int(message_id)),
                )
            except (psycopg_errors.UndefinedFunction, psycopg_errors.UndefinedTable):
                conn.rollback()
                return


def test_run_simplicity_import_dry_run_sets_planned_storage(tmp_path: Path) -> None:
    header = (
        "LeadID,LeadSource,Court,IndexNumber,JudgmentDate,JudgmentAmount,"
        "County,State,PlaintiffName,PlaintiffAddress,Phone,Email,BestContactMethod"
    )
    judgment_number = f"DRY-{uuid.uuid4().hex[:8].upper()}"
    csv_rows = [
        header,
        (
            f"{judgment_number},Import,Queens Supreme Court,{judgment_number},03/15/2024,15000.00,"
            'Queens,NY,Dry Run LLC,"123 Main St, Queens, NY",(718)555-0100,'
            "dry.run@example.com,Phone"
        ),
    ]
    csv_path = _write_csv(tmp_path, csv_rows)

    fake_client = FakeSupabaseClient()

    result = run_simplicity_import(
        str(csv_path),
        batch_name="pytest-dry-run",
        dry_run=True,
        source_reference="pytest",
        storage_client=fake_client,
    )

    planned_path = result["metadata"].get("planned_storage_path")
    assert planned_path is not None
    assert planned_path.startswith("simplicity_imports/DRY_RUN/")
    assert result["import_run_id"] is None
    assert fake_client.storage.uploads == []


def test_run_simplicity_import_persists_parse_errors(tmp_path: Path) -> None:
    header = (
        "LeadID,LeadSource,Court,IndexNumber,JudgmentDate,JudgmentAmount,"
        "County,State,PlaintiffName,PlaintiffAddress,Phone,Email,BestContactMethod"
    )
    good_judgment = f"GOOD-{uuid.uuid4().hex[:8].upper()}"
    bad_judgment = f"BAD-{uuid.uuid4().hex[:8].upper()}"
    csv_rows = [
        header,
        (
            f"{good_judgment},Import,Queens Supreme Court,{good_judgment},03/15/2024,15000.00,"
            'Queens,NY,Parse Tester LLC,"123 Main St, Queens, NY",(718)555-0100,'
            "parse.tester@example.com,Phone"
        ),
        (
            f"{bad_judgment},Import,Kings County Court,{bad_judgment},03/20/2024,,"
            'Kings,NY,Broken Amount Inc,"456 Court St, Brooklyn, NY",(347)555-2200,'
            "broken.amount@example.com,Email"
        ),
    ]
    csv_path = _write_csv(tmp_path, csv_rows)

    db_url = _resolve_db_url()
    batch_name = f"pytest-batch-{uuid.uuid4().hex[:8]}"

    plaintiff_ids: set[str] = set()
    judgment_ids: set[str] = set()
    import_run_id: str | None = None
    queued_jobs: List[Dict[str, Any]] = []
    queued_jobs: List[Dict[str, Any]] = []

    fake_client = FakeSupabaseClient()

    with psycopg.connect(db_url, autocommit=False) as conn:
        try:
            result = run_simplicity_import(
                str(csv_path),
                batch_name=batch_name,
                dry_run=False,
                source_reference="pytest",
                connection=conn,
                storage_client=fake_client,
            )

            queued_jobs = _collect_queue_jobs(result)

            parse_errors = result["metadata"]["parse_errors"]
            assert len(parse_errors) == 1
            assert parse_errors[0]["row_number"] == 3

            import_run_id = result["import_run_id"]
            assert import_run_id is not None

            assert "planned_storage_path" not in result["metadata"]
            assert "storage_path" in result["metadata"]
            storage_path = result["metadata"]["storage_path"]
            assert storage_path.startswith("simplicity_imports/")

            assert fake_client.storage.buckets == ["imports"]
            assert fake_client.storage.uploads
            assert fake_client.storage.uploads[0]["path"] == storage_path

            with conn.cursor() as cur:
                cur.execute(
                    "select storage_path, metadata->'parse_errors', metadata->>'storage_path'"
                    " from public.import_runs where id = %s",
                    (import_run_id,),
                )
                row = cur.fetchone()
            assert row is not None
            storage_path_db, db_parse_errors, metadata_storage_path = row
            assert storage_path_db == storage_path
            assert isinstance(db_parse_errors, list)
            assert len(db_parse_errors) == len(parse_errors)
            assert metadata_storage_path == storage_path

            raw_log = result["metadata"].get("raw_import_log", {})
            assert "enabled" in raw_log
            if raw_log.get("enabled"):
                assert raw_log.get("rows_written", 0) >= len(
                    result["metadata"].get("row_operations", [])
                )

            for op in result["metadata"].get("row_operations", []):
                if op.get("status") == "inserted":
                    if op.get("plaintiff_id"):
                        plaintiff_ids.add(op["plaintiff_id"])
                    if op.get("judgment_id"):
                        judgment_ids.add(op["judgment_id"])
        finally:
            if queued_jobs:
                _cleanup_queue_jobs(conn, queued_jobs)
            with conn.cursor() as cur:
                if import_run_id is not None:
                    cur.execute(
                        "delete from public.import_runs where id = %s",
                        (import_run_id,),
                    )
                if judgment_ids:
                    cur.execute(
                        "delete from public.judgments where id = any(%s)",
                        (list(judgment_ids),),
                    )
                if plaintiff_ids:
                    cur.execute(
                        "delete from public.plaintiff_status_history where plaintiff_id = any(%s)",
                        (list(plaintiff_ids),),
                    )
                    cur.execute(
                        "delete from public.plaintiffs where id = any(%s)",
                        (list(plaintiff_ids),),
                    )
            conn.commit()


def test_run_simplicity_import_records_import_and_tasks(tmp_path: Path) -> None:
    header = (
        "LeadID,LeadSource,Court,IndexNumber,JudgmentDate,JudgmentAmount,"
        "County,State,PlaintiffName,PlaintiffAddress,Phone,Email,BestContactMethod"
    )
    judgment_number = f"REAL-{uuid.uuid4().hex[:8].upper()}"
    csv_rows = [
        header,
        (
            f"{judgment_number},Import,Bronx Supreme Court,{judgment_number},04/01/2024,25000.00,"
            'Bronx,NY,Full Run LLC,"789 Grand Concourse, Bronx, NY",(917)555-3300,'
            "full.run@example.com,Phone"
        ),
    ]
    csv_path = _write_csv(tmp_path, csv_rows)

    db_url = _resolve_db_url()
    batch_name = f"pytest-import-{uuid.uuid4().hex[:8]}"

    plaintiff_ids: list[str] = []
    judgment_ids: list[str] = []
    import_run_id: str | None = None
    queued_jobs: List[Dict[str, Any]] = []
    queued_jobs: List[Dict[str, Any]] = []

    with psycopg.connect(db_url, autocommit=False) as conn:
        try:
            result = run_simplicity_import(
                str(csv_path),
                batch_name=batch_name,
                dry_run=False,
                source_reference=batch_name,
                connection=conn,
            )

            import_run_id = result["import_run_id"]
            assert import_run_id is not None

            queued_jobs = _collect_queue_jobs(result)

            import_count = _fetch_scalar(
                conn,
                "select count(*) from public.import_runs "
                "where id = %s and import_kind = 'simplicity_plaintiffs' and status = 'completed'",
                (import_run_id,),
            )
            assert import_count == 1

            inserted_ops = [
                op
                for op in result["metadata"].get("row_operations", [])
                if op.get("status") == "inserted"
            ]
            plaintiff_ids = [
                str(op["plaintiff_id"]) for op in inserted_ops if op.get("plaintiff_id")
            ]
            judgment_ids = [
                str(op["judgment_id"]) for op in inserted_ops if op.get("judgment_id")
            ]
            assert plaintiff_ids
            assert judgment_ids

            for op in inserted_ops:
                assert op.get("follow_up_task")
                assert op.get("contacts")
                assert op.get("enforcement_stage_initialized") is True
                assert op.get("queued_jobs")

            open_tasks = _fetch_scalar(
                conn,
                "select count(*) from public.plaintiff_tasks where plaintiff_id = any(%s)"
                " and kind = 'call' and status = 'open'",
                (plaintiff_ids,),
            )
            assert open_tasks > 0

            contact_count = _fetch_scalar(
                conn,
                "select count(*) from public.plaintiff_contacts where plaintiff_id = any(%s)",
                (plaintiff_ids,),
            )
            assert contact_count >= len(plaintiff_ids)

            enforcement_count = _fetch_scalar(
                conn,
                "select count(*) from public.judgments where id = any(%s)"
                " and enforcement_stage = 'pre_enforcement'",
                (judgment_ids,),
            )
            assert enforcement_count == len(judgment_ids)
        finally:
            if queued_jobs:
                _cleanup_queue_jobs(conn, queued_jobs)
            with conn.cursor() as cur:
                if import_run_id is not None:
                    cur.execute(
                        "delete from public.import_runs where id = %s",
                        (import_run_id,),
                    )
                if judgment_ids:
                    cur.execute(
                        "delete from public.judgments where id = any(%s)",
                        (judgment_ids,),
                    )
                if plaintiff_ids:
                    cur.execute(
                        "delete from public.plaintiff_tasks where plaintiff_id = any(%s)",
                        (plaintiff_ids,),
                    )
                    cur.execute(
                        "delete from public.plaintiff_status_history where plaintiff_id = any(%s)",
                        (plaintiff_ids,),
                    )
                    cur.execute(
                        "delete from public.plaintiffs where id = any(%s)",
                        (plaintiff_ids,),
                    )
            conn.commit()


def test_run_jbi_import_dry_run_sets_planned_storage(tmp_path: Path) -> None:
    case_number = f"JBI-DRY-{uuid.uuid4().hex[:8].upper()}"
    csv_rows = [
        JBI_HEADER,
        (
            f"{case_number},open,Queens Supreme Court,Queens,NY,01/05/2024,02/15/2024,"
            "15000.00,12000.00,judgment debtor,individual,JBI Dry Run LLC,(646)555-0100,phone,"
            "dry.run@example.com"
        ),
    ]
    csv_path = _write_jbi_csv(tmp_path, csv_rows)

    fake_client = FakeSupabaseClient()

    result = run_jbi_900_import(
        str(csv_path),
        batch_name="pytest-jbi-dry-run",
        dry_run=True,
        source_reference="pytest",
        storage_client=fake_client,
    )

    planned_path = result["metadata"].get("planned_storage_path")
    assert planned_path is not None
    assert planned_path.startswith("jbi_900_imports/DRY_RUN/")
    assert result["import_run_id"] is None
    assert fake_client.storage.uploads == []


def test_run_jbi_import_persists_parse_errors(tmp_path: Path) -> None:
    good_case = f"JBI-GOOD-{uuid.uuid4().hex[:8].upper()}"
    bad_case = f"JBI-BAD-{uuid.uuid4().hex[:8].upper()}"
    csv_rows = [
        JBI_HEADER,
        (
            f"{good_case},open,Queens Supreme Court,Queens,NY,03/05/2024,04/15/2024,19500.00,"
            "18000.00,judgment debtor,individual,Good Intake LLC,(917)555-2200,phone,"
            "good.intake@example.com"
        ),
        (
            f"{bad_case},open,Bronx County Civil Court,Bronx,NY,03/07/2024,04/20/2024,,"
            "9000.00,judgment debtor,individual,Bad Intake LLC,(917)555-3300,email,"
            "bad.intake@example.com"
        ),
    ]
    csv_path = _write_jbi_csv(tmp_path, csv_rows)

    db_url = _resolve_db_url()
    batch_name = f"pytest-jbi-{uuid.uuid4().hex[:8]}"

    plaintiff_ids: set[str] = set()
    judgment_ids: set[str] = set()
    import_run_id: str | None = None

    fake_client = FakeSupabaseClient()

    with psycopg.connect(db_url, autocommit=False) as conn:
        try:
            result = run_jbi_900_import(
                str(csv_path),
                batch_name=batch_name,
                dry_run=False,
                source_reference="pytest",
                connection=conn,
                storage_client=fake_client,
            )

            queued_jobs = _collect_queue_jobs(result)

            parse_errors = result["metadata"]["parse_errors"]
            assert len(parse_errors) == 1
            assert parse_errors[0]["row_number"] == 3

            import_run_id = result["import_run_id"]
            assert import_run_id is not None

            assert "planned_storage_path" not in result["metadata"]
            storage_path = result["metadata"].get("storage_path")
            assert isinstance(storage_path, str)
            assert storage_path.startswith("jbi_900_imports/")

            assert fake_client.storage.buckets == ["imports"]
            assert fake_client.storage.uploads
            assert fake_client.storage.uploads[0]["path"] == storage_path

            raw_log = result["metadata"].get("raw_import_log", {})
            assert "enabled" in raw_log

            with conn.cursor() as cur:
                cur.execute(
                    "select import_kind, source_system from public.import_runs where id = %s",
                    (import_run_id,),
                )
                row = cur.fetchone()
            assert row is not None
            assert row[0] == "jbi_900_plaintiffs"
            assert row[1] == "jbi_900"

            for op in result["metadata"].get("row_operations", []):
                if op.get("status") == "inserted":
                    if op.get("plaintiff_id"):
                        plaintiff_ids.add(op["plaintiff_id"])
                    if op.get("judgment_id"):
                        judgment_ids.add(op["judgment_id"])
        finally:
            if queued_jobs:
                _cleanup_queue_jobs(conn, queued_jobs)
            with conn.cursor() as cur:
                if import_run_id is not None:
                    cur.execute(
                        "delete from public.import_runs where id = %s",
                        (import_run_id,),
                    )
                if judgment_ids:
                    cur.execute(
                        "delete from public.judgments where id = any(%s)",
                        (list(judgment_ids),),
                    )
                if plaintiff_ids:
                    cur.execute(
                        "delete from public.plaintiff_tasks where plaintiff_id = any(%s)",
                        (list(plaintiff_ids),),
                    )
                    cur.execute(
                        "delete from public.plaintiff_status_history where plaintiff_id = any(%s)",
                        (list(plaintiff_ids),),
                    )
                    cur.execute(
                        "delete from public.plaintiffs where id = any(%s)",
                        (list(plaintiff_ids),),
                    )
            conn.commit()


def test_run_jbi_import_records_import_and_tasks(tmp_path: Path) -> None:
    case_number = f"JBI-REAL-{uuid.uuid4().hex[:8].upper()}"
    csv_rows = [
        JBI_HEADER,
        (
            f"{case_number},open,Bronx Supreme Court,Bronx,NY,02/10/2024,03/20/2024,24500.00,"
            "24000.00,judgment debtor,individual,Full Intake LLC,(347)555-4400,phone,"
            "full.intake@example.com"
        ),
    ]
    csv_path = _write_jbi_csv(tmp_path, csv_rows)

    db_url = _resolve_db_url()
    batch_name = f"pytest-jbi-live-{uuid.uuid4().hex[:8]}"

    plaintiff_ids: list[str] = []
    judgment_ids: list[str] = []
    import_run_id: str | None = None

    with psycopg.connect(db_url, autocommit=False) as conn:
        try:
            result = run_jbi_900_import(
                str(csv_path),
                batch_name=batch_name,
                dry_run=False,
                source_reference=batch_name,
                connection=conn,
            )

            import_run_id = result["import_run_id"]
            assert import_run_id is not None

            queued_jobs = _collect_queue_jobs(result)

            import_count = _fetch_scalar(
                conn,
                "select count(*) from public.import_runs "
                "where id = %s and import_kind = 'jbi_900_plaintiffs' and status = 'completed'",
                (import_run_id,),
            )
            assert import_count == 1

            inserted_ops = [
                op
                for op in result["metadata"].get("row_operations", [])
                if op.get("status") == "inserted"
            ]
            plaintiff_ids = [
                str(op["plaintiff_id"]) for op in inserted_ops if op.get("plaintiff_id")
            ]
            judgment_ids = [
                str(op["judgment_id"]) for op in inserted_ops if op.get("judgment_id")
            ]
            assert plaintiff_ids
            assert judgment_ids

            for op in inserted_ops:
                assert op.get("follow_up_task")
                assert op.get("contacts")
                assert op.get("enforcement_stage_initialized") is True
                assert op.get("queued_jobs")

            open_tasks = _fetch_scalar(
                conn,
                "select count(*) from public.plaintiff_tasks where plaintiff_id = any(%s)"
                " and kind = 'call' and status = 'open'",
                (plaintiff_ids,),
            )
            assert open_tasks > 0

            source_systems = _fetch_scalar(
                conn,
                "select count(distinct source_system) from public.plaintiffs where id = any(%s)",
                (plaintiff_ids,),
            )
            assert source_systems == 1

            contact_count = _fetch_scalar(
                conn,
                "select count(*) from public.plaintiff_contacts where plaintiff_id = any(%s)",
                (plaintiff_ids,),
            )
            assert contact_count >= len(plaintiff_ids)

            enforcement_count = _fetch_scalar(
                conn,
                "select count(*) from public.judgments where id = any(%s)"
                " and enforcement_stage = 'pre_enforcement'",
                (judgment_ids,),
            )
            assert enforcement_count == len(judgment_ids)
        finally:
            if queued_jobs:
                _cleanup_queue_jobs(conn, queued_jobs)
            with conn.cursor() as cur:
                if import_run_id is not None:
                    cur.execute(
                        "delete from public.import_runs where id = %s",
                        (import_run_id,),
                    )
                if judgment_ids:
                    cur.execute(
                        "delete from public.judgments where id = any(%s)",
                        (judgment_ids,),
                    )
                if plaintiff_ids:
                    cur.execute(
                        "delete from public.plaintiff_tasks where plaintiff_id = any(%s)",
                        (plaintiff_ids,),
                    )
                    cur.execute(
                        "delete from public.plaintiff_status_history where plaintiff_id = any(%s)",
                        (plaintiff_ids,),
                    )
                    cur.execute(
                        "delete from public.plaintiffs where id = any(%s)",
                        (plaintiff_ids,),
                    )
            conn.commit()
