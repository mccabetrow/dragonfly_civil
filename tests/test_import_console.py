from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from typer.testing import CliRunner

from tools import import_console


class _DummyCursor:
    def __init__(self, rows: list[tuple[str | None, str | None]]):
        self._rows = rows

    def __enter__(self) -> "_DummyCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def execute(
        self, query: Any, params: Any
    ) -> None:  # pragma: no cover - placeholder
        self.query = query
        self.params = params

    def fetchall(self) -> list[tuple[str | None, str | None]]:
        return self._rows


class _DummyConnection:
    def __init__(self, rows: list[tuple[str | None, str | None]] | None = None) -> None:
        self._rows = rows or []
        self.rollback_called = False

    def __enter__(self) -> "_DummyConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def cursor(self):
        return _DummyCursor(self._rows)

    def rollback(self) -> None:
        self.rollback_called = True


class _DummyWriter:
    def __init__(self, conn: Any) -> None:  # noqa: D401 - simple stub
        self.conn = conn
        self.enabled = True
        self.table = ("public", "raw_import_log")

    @property
    def table_fqn(self) -> str:
        return "public.raw_import_log"


def test_collect_resume_rows_skips_error_rows(monkeypatch):
    rows = [("1", "inserted"), ("2", "error"), ("3", "skipped")]
    conn = _DummyConnection(rows)
    monkeypatch.setattr(import_console, "RawImportWriter", _DummyWriter)

    plan = import_console._collect_resume_rows(  # type: ignore[attr-defined]
        conn,
        batch_name="batch-1",
        source_system="simplicity",
        source_reference="batch-1",
    )

    assert plan.table_name == "public.raw_import_log"
    assert plan.rows == {1, 3}


def test_simplicity_command_uses_resume_plan(tmp_path: Path, monkeypatch):
    csv_path = tmp_path / "simplicity.csv"
    csv_path.write_text("LeadID,JudgmentAmount\n1,1000\n", encoding="utf-8")

    dummy_conn = _DummyConnection()
    monkeypatch.setattr(import_console, "_connect_db", lambda env=None: dummy_conn)

    plan = import_console.ResumePlan(rows={5, 7}, table_name="public.raw_import_log")
    monkeypatch.setattr(
        import_console,
        "_collect_resume_rows",
        lambda *args, **kwargs: plan,
    )

    captured: dict[str, Any] = {}

    def fake_runner(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {
            "metadata": {
                "row_operations": [
                    {"status": "inserted"},
                    {"status": "inserted"},
                ]
            }
        }

    monkeypatch.setattr(import_console, "run_simplicity_import", fake_runner)

    runner = CliRunner()
    result = runner.invoke(
        import_console.app,
        ["import", "simplicity", str(csv_path), "--resume"],
    )

    assert result.exit_code == 0
    assert dummy_conn.rollback_called is True
    assert captured["kwargs"]["skip_row_numbers"] == {5, 7}
    assert captured["kwargs"]["dry_run"] is True


def _command_invoker(
    monkeypatch, fetch_map: dict[str, Callable[[Any], list[dict[str, Any]]]]
):
    dummy_conn = _DummyConnection()
    monkeypatch.setattr(import_console, "_connect_db", lambda env=None: dummy_conn)

    for name, func in fetch_map.items():
        monkeypatch.setattr(import_console, name, func)

    titles: list[str] = []

    def fake_print(title: str, *_args, **_kwargs) -> None:
        titles.append(title)

    monkeypatch.setattr(import_console, "_print_table", fake_print)

    return titles


def test_runs_command_calls_fetch(monkeypatch):
    fetched: dict[str, Any] = {}

    def fake_fetch(conn, *, limit, source_system):
        fetched["limit"] = limit
        fetched["source_system"] = source_system
        return [
            {
                "id": "run-1",
                "batch_name": "batch",
                "import_kind": "simplicity",
                "source_system": "simplicity",
                "status": "completed",
                "row_count": 2,
                "insert_count": 2,
                "error_count": 0,
                "started_at": None,
                "finished_at": None,
            }
        ]

    titles = _command_invoker(
        monkeypatch,
        {"_fetch_import_runs": fake_fetch},
    )

    runner = CliRunner()
    result = runner.invoke(
        import_console.app,
        ["import", "runs", "3", "--source-system", "simplicity"],
    )

    assert result.exit_code == 0
    assert fetched == {"limit": 3, "source_system": "simplicity"}
    assert titles == ["import_runs"]


def test_status_command_fetches_all_tables(monkeypatch):
    fetch_calls: dict[str, dict[str, Any]] = {}

    def _build_fetch(name: str):
        def _runner(conn, *, limit, source_system):
            fetch_calls[name] = {"limit": limit, "source_system": source_system}
            return [
                {
                    "id": f"{name}-row",
                    "case_id": "case-1",
                    "judgment_number": "J-1",
                    "judgment_amount": 1000,
                    "status": "completed",
                    "source_system": source_system,
                    "created_at": None,
                    "batch_name": "batch",
                    "import_kind": "simplicity",
                    "row_count": 1,
                    "insert_count": 1,
                    "error_count": 0,
                }
            ]

        return _runner

    titles = _command_invoker(
        monkeypatch,
        {
            "_fetch_import_runs": _build_fetch("runs"),
            "_fetch_plaintiffs": _build_fetch("plaintiffs"),
            "_fetch_cases": _build_fetch("cases"),
            "_fetch_judgments": _build_fetch("judgments"),
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        import_console.app,
        ["import", "status", "--limit", "5", "--source-system", "jbi_900"],
    )

    assert result.exit_code == 0
    assert titles == [
        "import_runs",
        "plaintiffs",
        "cases",
        "judgments",
    ]
    for entry in fetch_calls.values():
        assert entry == {"limit": 5, "source_system": "jbi_900"}
