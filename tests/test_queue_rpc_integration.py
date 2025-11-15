import os
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import errors
from pydantic import ValidationError

from src.settings import get_settings
from workers.queue_client import QueueClient


QUEUE_KIND = "enforce"
MIGRATION_NAMES = (
    "0062_queue_dequeue_job.sql",
    "0063_queue_dequeue_job_fix.sql",
    "0064_queue_bootstrap_refresh.sql",
)


def _resolve_db_url() -> str:
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit
    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if not project_ref or not password:
        pytest.skip("Supabase database credentials not configured")
    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def _ensure_migration_applied(db_url: str) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    up_statements: list[str] = []

    for name in MIGRATION_NAMES:
        migration_path = migrations_dir / name
        sql_text = migration_path.read_text(encoding="utf-8")
        up_section = sql_text.split("-- migrate:down", 1)[0]
        if "-- migrate:up" in up_section:
            up_section = up_section.split("-- migrate:up", 1)[1]
        up_sql = up_section.strip()
        if not up_sql:
            raise AssertionError(f"Migration {name} missing migrate:up SQL")
        up_statements.append(up_sql)

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            for statement in up_statements:
                cur.execute(statement)  # type: ignore[arg-type]


def _ensure_queue_exists(db_url: str, kind: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("create extension if not exists pgmq")
            queue_regclass = f"pgmq.q_{kind}"
            cur.execute("select to_regclass(%s)", (queue_regclass,))
            existing = cur.fetchone()
            if existing and existing[0] is not None:
                return

            creation_attempts = (
                "select pgmq.create(%s)",
                "select pgmq.create_queue(%s)",
            )

            for statement in creation_attempts:
                try:
                    cur.execute(statement, (kind,))
                    break
                except errors.UndefinedFunction:
                    continue
                except psycopg.Error as exc:  # pragma: no cover - duplicate queue or unexpected error
                    if exc.sqlstate in {"42710", "42P07"}:
                        break
                    raise
            else:  # pragma: no cover - bail if no creation function is available
                pytest.skip("pgmq create functions are unavailable; queue bootstrap requires manual setup")

            cur.execute("select to_regclass(%s)", (queue_regclass,))
            created = cur.fetchone()
            if not created or created[0] is None:  # pragma: no cover - guard against bootstrap drift
                pytest.skip(f"Queue {kind} is not available even after bootstrap attempts")


def _drain_queue(db_url: str, kind: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            while True:
                try:
                    cur.execute("select msg_id from pgmq.read(%s, 50, 60)", (kind,))  # type: ignore[arg-type]
                except psycopg.errors.UndefinedTable:
                    break
                rows = cur.fetchall()
                if not rows:
                    break
                for (msg_id,) in rows:
                    cur.execute("select pgmq.delete(%s, %s)", (kind, msg_id))


def _require_settings() -> None:
    try:
        settings = get_settings()
    except ValidationError:
        pytest.skip("Supabase settings not configured for queue integration test")
    if not settings.supabase_url or not settings.supabase_service_role_key:
        pytest.skip("Supabase URL or service role key missing for queue integration test")


def test_queue_job_round_trip_via_rpc() -> None:
    _require_settings()
    db_url = _resolve_db_url()
    _ensure_migration_applied(db_url)
    _ensure_queue_exists(db_url, QUEUE_KIND)
    _drain_queue(db_url, QUEUE_KIND)

    payload = {"case_number": f"TEST-{uuid.uuid4().hex[:8].upper()}"}
    idempotency_key = f"pytest:{uuid.uuid4()}"

    client: QueueClient | None = None
    try:
        client = QueueClient()
    except RuntimeError as exc:  # pragma: no cover - configuration guardrail
        message = str(exc)
        if "Service role key" in message or "Invalid SUPABASE_SERVICE_ROLE_KEY" in message:
            pytest.skip("Supabase service role key is not available for integration test")
        raise
    job = None
    queued_msg_id: int | None = None
    acknowledged = False

    try:
        queued_msg_id = client.enqueue(QUEUE_KIND, payload, idempotency_key)

        for _ in range(30):
            candidate = client.dequeue(QUEUE_KIND)
            if candidate is None:
                time.sleep(0.5)
                continue

            envelope = candidate.get("payload") if isinstance(candidate, dict) else None
            if isinstance(envelope, dict) and envelope.get("idempotency_key") == idempotency_key:
                job = candidate
                break

            if isinstance(candidate, dict) and candidate.get("msg_id") is not None:
                try:
                    client.ack(QUEUE_KIND, int(candidate["msg_id"]))
                except Exception:  # pragma: no cover - ignore transient ack errors
                    pass
            time.sleep(0.5)

        assert job is not None, "Expected to dequeue the job that was just enqueued"
        assert isinstance(job.get("msg_id"), (int, float))
        if queued_msg_id is not None:
            assert int(job["msg_id"]) == int(queued_msg_id)

        envelope = job.get("payload")
        assert isinstance(envelope, dict)
        assert envelope.get("payload") == payload
        assert envelope.get("idempotency_key") == idempotency_key
        assert envelope.get("kind") == QUEUE_KIND
    finally:
        if job and "msg_id" in job:
            try:
                assert client is not None
                client.ack(QUEUE_KIND, int(job["msg_id"]))
                acknowledged = True
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
        if not acknowledged and queued_msg_id is not None:
            try:
                with psycopg.connect(db_url, autocommit=True) as cleanup_conn:
                    with cleanup_conn.cursor() as cleanup_cur:
                        cleanup_cur.execute("select pgmq.delete(%s, %s)", (QUEUE_KIND, queued_msg_id))
            except Exception:  # pragma: no cover
                pass
        _drain_queue(db_url, QUEUE_KIND)
        if client is not None:
            client.close()
