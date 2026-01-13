"""Tests for the production certification script."""

from __future__ import annotations

import pytest


class TestDryRunMode:
    """Ensure dry-run mode is side-effect free."""

    def test_dry_run_skips_certifier_instantiation(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from tools import certify_prod

        class Boom:
            def __init__(self, *_, **__) -> None:  # pragma: no cover - should not run
                raise AssertionError("ProdCertifier should not be constructed in dry-run")

        monkeypatch.setattr(certify_prod, "ProdCertifier", Boom)

        exit_code = certify_prod.main(["--url", "https://example", "--env", "prod", "--dry-run"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "DRY RUN" in captured.out
        assert "No network or database calls" in captured.out
