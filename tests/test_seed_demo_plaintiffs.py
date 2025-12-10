from __future__ import annotations

from datetime import datetime, timezone

from click.testing import CliRunner

from tools import seed_demo_plaintiffs


class _DummyConnection:
    def __init__(self) -> None:
        self.token = object()

    def __enter__(self):  # noqa: D401 - standard ctx
        return self.token

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001 - context protocol
        return False


def test_guard_blocks_prod_env(monkeypatch):
    runner = CliRunner()

    monkeypatch.setattr(seed_demo_plaintiffs, "get_supabase_env", lambda: "prod")

    result = runner.invoke(seed_demo_plaintiffs.main)

    assert result.exit_code != 0
    assert "dev credentials" in result.output


def test_reset_only_short_circuits_seed(monkeypatch):
    runner = CliRunner()
    fake_specs = [object()]
    captured = {}

    monkeypatch.setattr(seed_demo_plaintiffs, "get_supabase_env", lambda: "dev")
    monkeypatch.setattr(
        seed_demo_plaintiffs, "get_supabase_db_url", lambda env: "postgresql://demo"
    )
    monkeypatch.setattr(
        seed_demo_plaintiffs,
        "describe_db_url",
        lambda url: ("demo-host", "demo-db", "postgres"),
    )
    monkeypatch.setattr(seed_demo_plaintiffs, "_demo_specs", lambda now: fake_specs)
    monkeypatch.setattr(
        seed_demo_plaintiffs,
        "_now",
        lambda: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    def fake_reset(conn, specs):
        captured["reset_conn"] = conn
        captured["reset_specs"] = specs
        return {
            "plaintiffs": 3,
            "contacts": 5,
            "statuses": 7,
            "tasks": 2,
            "judgments": 4,
        }

    def fake_seed(*_args, **_kwargs):  # pragma: no cover - guard path
        raise AssertionError("seed should not run in reset-only mode")

    monkeypatch.setattr(seed_demo_plaintiffs, "_reset_demo_rows", fake_reset)
    monkeypatch.setattr(seed_demo_plaintiffs, "_seed_dataset", fake_seed)
    monkeypatch.setattr(
        seed_demo_plaintiffs.psycopg,
        "connect",
        lambda *args, **kwargs: _DummyConnection(),
    )

    result = runner.invoke(seed_demo_plaintiffs.main, ["--reset-only"])

    assert result.exit_code == 0
    assert "reset-only complete" in result.output
    assert captured["reset_specs"] is fake_specs
    assert captured["reset_conn"] is not None


def test_happy_path_runs_seed(monkeypatch):
    runner = CliRunner()
    fake_specs = [object()]
    summary = seed_demo_plaintiffs.SeedSummary(
        plaintiffs=3,
        contacts=4,
        statuses=5,
        judgments=6,
        tasks=7,
    )

    monkeypatch.setattr(seed_demo_plaintiffs, "get_supabase_env", lambda: "dev")
    monkeypatch.setattr(
        seed_demo_plaintiffs, "get_supabase_db_url", lambda env: "postgresql://demo"
    )
    monkeypatch.setattr(
        seed_demo_plaintiffs,
        "describe_db_url",
        lambda url: ("demo-host", "demo-db", "postgres"),
    )
    monkeypatch.setattr(seed_demo_plaintiffs, "_demo_specs", lambda now: fake_specs)
    monkeypatch.setattr(seed_demo_plaintiffs, "_reset_demo_rows", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        seed_demo_plaintiffs,
        "_now",
        lambda: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(seed_demo_plaintiffs, "_seed_dataset", lambda conn, specs, now: summary)
    monkeypatch.setattr(
        seed_demo_plaintiffs.psycopg,
        "connect",
        lambda *args, **kwargs: _DummyConnection(),
    )

    result = runner.invoke(seed_demo_plaintiffs.main)

    assert result.exit_code == 0
    assert "seeded plaintiffs=3 contacts=4 statuses=5 judgments=6 tasks=7" in result.output
