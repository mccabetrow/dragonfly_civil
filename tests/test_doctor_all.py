from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List

from click.testing import CliRunner

from tools import doctor_all


def _patch_common_success(
    monkeypatch, env: str = "dev", patch_config: bool = True, patch_schema_guard: bool = True
) -> None:
    monkeypatch.setattr(doctor_all, "_bootstrap_env", lambda requested: env)
    if patch_config:
        # Runner functions now accept tolerant kwarg
        monkeypatch.setattr(
            doctor_all, "_config_check_runner", lambda env, tolerant=False: (lambda: None)
        )
    monkeypatch.setattr(doctor_all, "_doctor_runner", lambda env: lambda: None)
    monkeypatch.setattr(doctor_all, "_security_audit_runner", lambda env: (lambda: None))
    # Mock external API/storage checks
    monkeypatch.setattr(
        doctor_all, "_check_storage_runner", lambda env, tolerant=False: (lambda: None)
    )
    monkeypatch.setattr(
        doctor_all, "_check_api_health_runner", lambda env, tolerant=False: (lambda: None)
    )
    if patch_schema_guard:
        monkeypatch.setattr(
            doctor_all, "_prod_schema_guard_runner", lambda env, tolerant=False: (lambda: None)
        )
    monkeypatch.setattr(doctor_all.smoke_plaintiffs, "main", lambda: None)
    monkeypatch.setattr(doctor_all.smoke_enforcement, "main", lambda: None)


def _make_run_query_stub(
    responses: Dict[str, List[tuple]],
) -> Callable[[str, object, object], List[tuple]]:
    def _fake_run_query(env: str, query: object, params: object = None) -> List[tuple]:
        text = str(query).lower()
        if "import_runs" in text:
            return responses.get("import_runs", [])
        if "plaintiff_tasks" in text:
            return responses.get("plaintiff_tasks", [])
        if "enforcement_cases" in text:
            return responses.get("enforcement_cases", [])
        return []

    return _fake_run_query


def test_doctor_all_all_clear(monkeypatch):
    _patch_common_success(monkeypatch)
    monkeypatch.setattr(
        doctor_all,
        "_run_query",
        _make_run_query_stub({}),
    )

    runner = CliRunner()
    result = runner.invoke(doctor_all.main, ["--env", "dev"])

    assert result.exit_code == 0
    assert "All checks passed" in result.output


def test_doctor_all_reports_recent_failed_import(monkeypatch):
    _patch_common_success(monkeypatch)
    failure_row = (
        "run-123",
        "simplicity",
        "vendor_a",
        "failed",
        datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc),
        datetime(2025, 1, 1, 9, 5, tzinfo=timezone.utc),
        "batch-99",
    )
    monkeypatch.setattr(
        doctor_all,
        "_run_query",
        _make_run_query_stub({"import_runs": [failure_row]}),
    )

    runner = CliRunner()
    result = runner.invoke(doctor_all.main, ["--env", "dev"])

    assert result.exit_code == 1
    assert "import_runs: failed jobs detected" in result.output
    assert "run-123" in result.output
    assert "Failures detected: import_runs_recent_failures" in result.output


def test_doctor_all_reports_orphaned_tasks_and_cases(monkeypatch):
    _patch_common_success(monkeypatch)
    orphan_task = (
        "task-1",
        "plaintiff-1",
        "call",
        "open",
        datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc),
    )
    orphan_case = (
        "case-1",
        123,
        "CN-1",
        "open",
        "paperwork",
    )
    monkeypatch.setattr(
        doctor_all,
        "_run_query",
        _make_run_query_stub(
            {
                "plaintiff_tasks": [orphan_task],
                "enforcement_cases": [orphan_case],
            }
        ),
    )

    runner = CliRunner()
    result = runner.invoke(doctor_all.main, ["--env", "dev"])

    assert result.exit_code == 1
    assert "plaintiff_tasks: orphaned tasks detected" in result.output
    assert "enforcement_cases: invalid judgment references detected" in result.output
    assert "Failures detected" in result.output


def test_doctor_all_runs_prod_schema_guard(monkeypatch):
    _patch_common_success(monkeypatch, env="prod", patch_schema_guard=False)
    guard_calls: list[list[str]] = []
    monkeypatch.setattr(
        doctor_all.check_prod_schema,
        "main",
        lambda args: guard_calls.append(list(args)) or 0,
    )
    monkeypatch.setattr(
        doctor_all,
        "_run_query",
        _make_run_query_stub({}),
    )

    runner = CliRunner()
    result = runner.invoke(doctor_all.main, ["--env", "prod"])

    assert result.exit_code == 0
    assert guard_calls == [["--env", "prod"]]
    assert "All checks passed" in result.output


def test_doctor_all_schema_guard_failure_reports(monkeypatch):
    _patch_common_success(monkeypatch, env="prod", patch_schema_guard=False)
    guard_calls: list[list[str]] = []

    def _failing_guard(args: list[str]) -> int:
        guard_calls.append(list(args))
        return 2

    monkeypatch.setattr(doctor_all.check_prod_schema, "main", _failing_guard)
    monkeypatch.setattr(
        doctor_all,
        "_run_query",
        _make_run_query_stub({}),
    )

    runner = CliRunner()
    result = runner.invoke(doctor_all.main, ["--env", "prod"])

    assert result.exit_code == 1
    assert guard_calls == [["--env", "prod"]]
    assert "Failures detected: prod_schema_guard (exit 2)" in result.output


def test_doctor_all_dev_warns_missing_keys(monkeypatch):
    _patch_common_success(monkeypatch, env="dev", patch_config=False)

    def _fake_check_environment(requested_env: str | None = None):
        assert requested_env == "dev"
        return [doctor_all.config_check.CheckResult("OPENAI_API_KEY", "WARN", "dev optional")]

    monkeypatch.setattr(doctor_all.config_check, "check_environment", _fake_check_environment)
    monkeypatch.setattr(
        doctor_all.config_check,
        "has_failures",
        lambda results, tolerant=False: any(result.status == "FAIL" for result in results),
    )
    monkeypatch.setattr(
        doctor_all,
        "_run_query",
        _make_run_query_stub({}),
    )

    runner = CliRunner()
    result = runner.invoke(doctor_all.main, ["--env", "dev"])

    assert result.exit_code == 0
    assert "All checks passed" in result.output


def test_doctor_all_prod_missing_keys_fails(monkeypatch):
    _patch_common_success(monkeypatch, env="prod", patch_config=False)

    def _fake_check_environment(requested_env: str | None = None):
        assert requested_env == "prod"
        return [doctor_all.config_check.CheckResult("OPENAI_API_KEY", "FAIL", "missing")]

    monkeypatch.setattr(doctor_all.config_check, "check_environment", _fake_check_environment)
    monkeypatch.setattr(
        doctor_all.config_check,
        "has_failures",
        lambda results, tolerant=False: any(result.status == "FAIL" for result in results),
    )
    monkeypatch.setattr(
        doctor_all,
        "_run_query",
        _make_run_query_stub({}),
    )
    monkeypatch.setattr(doctor_all.check_prod_schema, "main", lambda args: 0)

    runner = CliRunner()
    result = runner.invoke(doctor_all.main, ["--env", "prod"])

    assert result.exit_code == 1
    assert "Failures detected: config_check (exit 1)" in result.output
