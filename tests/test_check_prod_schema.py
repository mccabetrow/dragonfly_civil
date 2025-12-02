from __future__ import annotations

from scripts import check_prod_schema
from tools.schema_guard import SchemaDiff


class DummyConn:
    def __init__(self, token: object) -> None:
        self._token = token

    def __enter__(self) -> object:
        return self._token

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _install_common_patches(monkeypatch):
    freeze_payload = {"hash": "abcd1234", "schemas": {}, "rpcs": {}}
    sentinel_conn = object()

    monkeypatch.setattr(
        check_prod_schema,
        "load_schema_freeze",
        lambda path: freeze_payload,
    )
    monkeypatch.setattr(
        check_prod_schema,
        "get_supabase_db_url",
        lambda env: f"postgresql://{env}/db",
    )
    monkeypatch.setattr(
        check_prod_schema,
        "describe_db_url",
        lambda url: ("localhost", "db", "user"),
    )
    monkeypatch.setattr(
        check_prod_schema.psycopg,
        "connect",
        lambda *args, **kwargs: DummyConn(sentinel_conn),
    )

    return freeze_payload, sentinel_conn


def test_check_prod_schema_passes_when_schema_matches(monkeypatch, capsys):
    freeze_payload, sentinel_conn = _install_common_patches(monkeypatch)

    def _diff(conn, freeze_data, freeze_path):
        assert conn is sentinel_conn
        assert freeze_data is freeze_payload
        return SchemaDiff([], [], [], [])

    monkeypatch.setattr(check_prod_schema, "diff_connection_against_freeze", _diff)

    exit_code = check_prod_schema.main(["--env", "prod"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "schema matches" in output


def test_check_prod_schema_reports_drift(monkeypatch, capsys):
    freeze_payload, sentinel_conn = _install_common_patches(monkeypatch)

    drift = SchemaDiff(["public.judgments (tables)"], [], [], [])

    def _diff(conn, freeze_data, freeze_path):
        assert conn is sentinel_conn
        assert freeze_data is freeze_payload
        return drift

    monkeypatch.setattr(check_prod_schema, "diff_connection_against_freeze", _diff)

    exit_code = check_prod_schema.main(["--env", "prod"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "missing relation" in output
    assert "deviates" in output
