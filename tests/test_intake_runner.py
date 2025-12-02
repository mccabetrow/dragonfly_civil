from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, cast

import click
import pytest

from tools import intake_runner


class _FakeRepo:
    def __init__(self, seen: Iterable[str] | None = None) -> None:
        self.seen = set(seen or [])
        self.records: list[dict[str, object | None]] = []
        self.fetch_calls: list[str] = []

    def fetch_seen_files(self, source: str) -> set[str]:
        self.fetch_calls.append(source)
        return set(self.seen)

    def record_result(
        self,
        *,
        source: str,
        file_name: str,
        batch_name: str,
        status: str,
        import_run_id: str | None,
        metadata: dict[str, object] | None,
        error_message: str | None,
    ) -> None:
        self.records.append(
            {
                "source": source,
                "file_name": file_name,
                "batch_name": batch_name,
                "status": status,
                "import_run_id": import_run_id,
                "metadata": metadata,
                "error_message": error_message,
            }
        )
        self.seen.add(file_name)


class _RepoContext(AbstractContextManager[intake_runner.DatabaseIntakeRepository]):
    def __init__(self, repo: _FakeRepo) -> None:
        self.repo = repo

    def __enter__(self) -> intake_runner.DatabaseIntakeRepository:
        return cast(intake_runner.DatabaseIntakeRepository, self.repo)

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001 - context protocol
        return None


def _repo_factory(repo: _FakeRepo):
    def _factory(_: str) -> _RepoContext:
        return _RepoContext(repo)

    return _factory


def _make_spec(name: str, importer):
    return intake_runner.SourceSpec(
        name=name,
        importer=importer,
        default_subdir=name,
        file_glob="*.csv",
        env_var=f"INTAKE_{name.upper()}_PATH",
        description=f"{name} imports",
    )


def test_runner_processes_new_file_and_records_result(tmp_path):
    incoming = tmp_path / "simplicity"
    incoming.mkdir()
    file_path = incoming / "simplicity_drop.csv"
    file_path.write_text("case,jurisdiction\n1,NY\n", encoding="utf-8")

    calls: list[tuple[str, str, bool]] = []

    def fake_importer(csv_path: str, batch_name: str, dry_run: bool):
        calls.append((csv_path, batch_name, dry_run))
        return {
            "import_run_id": "run-123",
            "metadata": {"summary": {"row_count": 1}},
            "row_count": 1,
            "insert_count": 1,
            "error_count": 0,
        }

    spec = _make_spec("simplicity", fake_importer)
    repo = _FakeRepo()
    runner = intake_runner.IntakeRunner(
        target_env="dev",
        sources=[spec],
        dry_run=False,
        once=True,
        interval_seconds=5,
        path_overrides={"simplicity": str(incoming)},
        repo_factory=_repo_factory(repo),
        now_fn=lambda: datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    processed_count = runner.process_once()

    assert processed_count == 1
    assert calls[0][0] == str(file_path)
    assert calls[0][2] is False
    assert repo.records[0]["status"] == "completed"
    assert repo.records[0]["import_run_id"] == "run-123"


def test_runner_skips_seen_files(tmp_path):
    incoming = tmp_path / "simplicity"
    incoming.mkdir()
    file_path = incoming / "simplicity_drop.csv"
    file_path.write_text("case,jurisdiction\n1,NY\n", encoding="utf-8")

    spec = _make_spec("simplicity", lambda *args, **kwargs: {})
    repo = _FakeRepo(seen={file_path.name})
    runner = intake_runner.IntakeRunner(
        target_env="dev",
        sources=[spec],
        dry_run=False,
        once=True,
        interval_seconds=5,
        path_overrides={"simplicity": str(incoming)},
        repo_factory=_repo_factory(repo),
    )

    processed_count = runner.process_once()

    assert processed_count == 0
    assert repo.records == []


def test_runner_records_failure_on_exception(tmp_path):
    incoming = tmp_path / "simplicity"
    incoming.mkdir()
    file_path = incoming / "simplicity_drop.csv"
    file_path.write_text("case,jurisdiction\n1,NY\n", encoding="utf-8")

    def failing_importer(*_args, **_kwargs):
        raise RuntimeError("boom")

    spec = _make_spec("simplicity", failing_importer)
    repo = _FakeRepo()
    runner = intake_runner.IntakeRunner(
        target_env="dev",
        sources=[spec],
        dry_run=False,
        once=True,
        interval_seconds=5,
        path_overrides={"simplicity": str(incoming)},
        repo_factory=_repo_factory(repo),
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    runner.process_once()

    assert repo.records[0]["status"] == "failed"
    error_message = str(repo.records[0]["error_message"] or "")
    assert "boom" in error_message


def test_derive_batch_name_sanitizes_characters():
    now = datetime(2025, 1, 1, 8, 30, tzinfo=timezone.utc)
    batch = intake_runner.derive_batch_name("simplicity", "Messy Name!.csv", now=now)
    assert batch.startswith("202501010830-simplicity-Messy-Name")


def test_parse_path_overrides_validates_source():
    with pytest.raises(click.BadParameter):
        intake_runner._parse_path_overrides(["unknown=C:/tmp"])

    overrides = intake_runner._parse_path_overrides(["simplicity=C:/drop"])
    assert overrides["simplicity"] == "C:/drop"
