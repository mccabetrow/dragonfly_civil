from __future__ import annotations

from typing import Any

import pytest

from tools import config_check


def _base_env() -> dict[str, str]:
    return {
        "SUPABASE_URL": "https://demo.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-key",
        "SUPABASE_ANON_KEY": "anon-key",
        "SUPABASE_PROJECT_REF": "demo123",
        "SUPABASE_DB_PASSWORD": "password",
        "OPENAI_API_KEY": "sk-example",
        "N8N_API_KEY": "n8n-example",
    }


def test_evaluate_env_requirements_okay_for_dev():
    env_values = _base_env()
    results = config_check.evaluate_env_requirements("dev", env_values=env_values)
    statuses = {result.name: result.status for result in results}

    assert statuses["SUPABASE_URL"] == "OK"
    assert statuses["OPENAI_API_KEY"] == "OK"


def test_evaluate_env_requirements_flags_missing_value():
    env_values = _base_env()
    env_values.pop("OPENAI_API_KEY")

    results = config_check.evaluate_env_requirements("dev", env_values=env_values)
    openai_result = next(result for result in results if result.name == "OPENAI_API_KEY")

    assert openai_result.status == "WARN"


def test_evaluate_env_requirements_flags_missing_value_prod():
    env_values = _base_env()
    env_values.pop("OPENAI_API_KEY")

    results = config_check.evaluate_env_requirements("prod", env_values=env_values)
    openai_result = next(result for result in results if result.name == "OPENAI_API_KEY")

    assert openai_result.status == "FAIL"


def test_db_requirement_allows_explicit_url():
    env_values = _base_env()
    env_values.pop("SUPABASE_DB_PASSWORD")
    env_values["SUPABASE_DB_URL"] = "postgresql://example.com/postgres"

    results = config_check.evaluate_env_requirements("dev", env_values=env_values)
    statuses = {result.name: result.status for result in results}

    assert statuses["SUPABASE_DB_URL"] == "OK"


def test_db_requirement_flags_missing_when_no_password_or_url():
    env_values = _base_env()
    env_values.pop("SUPABASE_DB_PASSWORD")

    results = config_check.evaluate_env_requirements("dev", env_values=env_values)
    db_result = next(result for result in results if result.name == "SUPABASE_DB_PASSWORD")

    assert db_result.status == "FAIL"


def test_run_checks_includes_storage_and_db(monkeypatch):
    env_values = _base_env() | {
        "SUPABASE_URL_PROD": "https://prod.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY_PROD": "prod-service",
        "SUPABASE_ANON_KEY_PROD": "prod-anon",
        "SUPABASE_PROJECT_REF_PROD": "prod123",
        "SUPABASE_DB_PASSWORD_PROD": "prod-pass",
    }

    monkeypatch.setattr(
        config_check,
        "get_supabase_db_url",
        lambda env: "postgresql://example.com/postgres",
    )

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query: str) -> None:
            self.query = query

        def fetchone(self) -> tuple[int]:
            return (1,)

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(config_check.psycopg, "connect", lambda *args, **kwargs: _FakeConn())

    class _FakeStorage:
        def list_buckets(self):
            return [
                type("Bucket", (), {"name": "imports"})(),
                type("Bucket", (), {"name": "enforcement_evidence"})(),
            ]

    class _FakeClient:
        def __init__(self):
            self.storage = _FakeStorage()

    monkeypatch.setattr(
        config_check,
        "create_supabase_client",
        lambda env: _FakeClient(),
    )

    results = config_check.run_checks("dev", env_values=env_values)
    names = {result.name for result in results}

    assert "supabase_db_connect" in names
    assert "storage_buckets" in names


def test_storage_bucket_check_reports_missing(monkeypatch):
    class _FakeStorage:
        def list_buckets(self):
            return [type("Bucket", (), {"name": "imports"})()]

    class _FakeClient:
        def __init__(self):
            self.storage = _FakeStorage()

    monkeypatch.setattr(
        config_check,
        "create_supabase_client",
        lambda env: _FakeClient(),
    )

    result = config_check._storage_bucket_check("dev")

    assert result.status == "FAIL"
    assert "enforcement_evidence" in result.detail


def test_has_failures_ignores_warn():
    results = [config_check.CheckResult("OPENAI_API_KEY", "WARN", "missing")]
    assert config_check.has_failures(results) is False


def test_has_failures_detects_fail():
    results = [config_check.CheckResult("OPENAI_API_KEY", "FAIL", "missing")]
    assert config_check.has_failures(results) is True
