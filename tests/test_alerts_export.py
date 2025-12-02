from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from typer.testing import CliRunner

from tools import alerts_export


class _DummyConnection:
    def __enter__(self) -> "_DummyConnection":
        return self

    def __exit__(
        self, exc_type, exc, tb
    ) -> None:  # noqa: ANN001 - standard ctx signature
        return None


def test_build_alert_summary_includes_failed_imports_and_stale_tasks(monkeypatch):
    fake_conn = _DummyConnection()
    monkeypatch.setattr(alerts_export, "_connect", lambda env: fake_conn)
    fixed_now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(alerts_export, "_utcnow", lambda: fixed_now)

    captured: dict[str, Any] = {}

    def fake_fetch_failed(conn, since):
        assert conn is fake_conn
        captured["since"] = since
        return [
            {
                "id": "run-1",
                "import_kind": "simplicity",
                "source_system": "vendor-a",
                "status": "failed",
                "file_name": "export.csv",
                "started_at": "2025-01-01T10:00:00Z",
                "finished_at": "2025-01-01T10:05:00Z",
                "error_count": 3,
                "batch_name": "batch-42",
            }
        ]

    def fake_fetch_stale(conn, threshold):
        assert conn is fake_conn
        captured["threshold"] = threshold
        return 7

    monkeypatch.setattr(alerts_export, "_fetch_failed_imports", fake_fetch_failed)
    monkeypatch.setattr(alerts_export, "_fetch_stale_call_task_count", fake_fetch_stale)

    summary = alerts_export.build_alert_summary(env="dev", stale_days=2)

    assert summary["env"] == "dev"
    assert summary["failed_imports"][0]["id"] == "run-1"
    assert summary["open_call_tasks"]["stale_count"] == 7
    assert summary["open_call_tasks"]["stale_days_threshold"] == 2

    # Ensure the time windows align with the configured constants.
    assert captured["since"] == fixed_now - timedelta(
        hours=alerts_export.RECENT_FAILURE_WINDOW_HOURS
    )
    assert captured["threshold"] == fixed_now - timedelta(days=2)


def test_export_command_supports_json_and_pretty(monkeypatch):
    runner = CliRunner()
    summary = {
        "env": "prod",
        "generated_at": "2025-01-01T12:00:00Z",
        "failed_imports": [],
        "open_call_tasks": {
            "stale_days_threshold": 5,
            "reference_timestamp": "2025-01-01T00:00:00Z",
            "stale_count": 0,
        },
    }

    recorded: dict[str, Any] = {}

    def fake_build(env=None, stale_days=alerts_export.DEFAULT_STALE_DAYS):
        recorded["env"] = env
        recorded["stale_days"] = stale_days
        return summary

    monkeypatch.setattr(alerts_export, "build_alert_summary", fake_build)

    json_result = runner.invoke(
        alerts_export.cli,
        [
            "export",
            "--env",
            "prod",
            "--stale-days",
            "5",
            "--json",
        ],
    )

    assert json_result.exit_code == 0
    assert json.loads(json_result.output) == summary
    assert recorded == {"env": "prod", "stale_days": 5}

    pretty_result = runner.invoke(
        alerts_export.cli,
        [
            "export",
            "--env",
            "prod",
            "--stale-days",
            "5",
            "--pretty",
        ],
    )
    assert pretty_result.exit_code == 0
    assert pretty_result.output.startswith('{\n  "env":')
    assert json.loads(pretty_result.output) == summary

    human_result = runner.invoke(alerts_export.cli, ["export", "--env", "dev"])
    assert human_result.exit_code == 0
    assert "[alerts_export] env=" in human_result.output
