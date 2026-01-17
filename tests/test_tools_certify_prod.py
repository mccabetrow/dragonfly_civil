"""Tests for the production certification script."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

    def test_dry_run_shows_railway_domain_contract(self, capsys) -> None:
        """Dry run output should mention Railway domain contract."""
        from tools import certify_prod

        exit_code = certify_prod.main(["--url", "https://example", "--env", "prod", "--dry-run"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert (
            "service_name='dragonfly-api'" in captured.out
            or "Railway domain contract" in captured.out
        )


class TestRailwayFallbackDetection:
    """Tests for detecting Railway edge fallback responses."""

    def test_detects_railway_fallback_header(self) -> None:
        """Certifier must detect X-Railway-Fallback: true header."""
        from tools.certify_prod import ProdCertifier

        certifier = ProdCertifier(
            base_url="https://test.example.com",
            env="prod",
            supabase_url="https://supabase.example.com",
            anon_key="test-anon-key",
            service_key="test-service-key",
            db_url="postgresql://test@localhost/test",
        )

        # Mock the HTTP response with Railway fallback header
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"X-Railway-Fallback": "true"}
        mock_response.json.return_value = {"message": "Application not found"}

        with patch.object(certifier, "_api_get_raw", return_value=mock_response):
            result = certifier.check_service_identity()

        assert not result.passed, "Should fail when X-Railway-Fallback is true"
        assert "RAILWAY FALLBACK" in result.detail

    def test_detects_application_not_found_message(self) -> None:
        """Certifier must detect 'Application not found' in JSON response."""
        from tools.certify_prod import ProdCertifier

        certifier = ProdCertifier(
            base_url="https://test.example.com",
            env="prod",
            supabase_url="https://supabase.example.com",
            anon_key="test-anon-key",
            service_key="test-service-key",
            db_url="postgresql://test@localhost/test",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {"message": "Application not found"}

        with patch.object(certifier, "_api_get_raw", return_value=mock_response):
            result = certifier.check_service_identity()

        assert not result.passed, "Should fail when 'Application not found' in response"
        assert "Application not found" in result.detail

    def test_detects_wrong_service_name(self) -> None:
        """Certifier must fail if service_name is not 'dragonfly-api'."""
        from tools.certify_prod import ProdCertifier

        certifier = ProdCertifier(
            base_url="https://test.example.com",
            env="prod",
            supabase_url="https://supabase.example.com",
            anon_key="test-anon-key",
            service_key="test-service-key",
            db_url="postgresql://test@localhost/test",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "service_name": "some-other-api",
            "version": "1.0.0",
            "sha_short": "abc123",
            "env": "prod",
        }

        with patch.object(certifier, "_api_get_raw", return_value=mock_response):
            result = certifier.check_service_identity()

        assert not result.passed, "Should fail when service_name is wrong"
        assert "some-other-api" in result.detail

    def test_passes_with_correct_service_identity(self) -> None:
        """Certifier must pass when service_name is 'dragonfly-api'."""
        from tools.certify_prod import ProdCertifier

        certifier = ProdCertifier(
            base_url="https://test.example.com",
            env="prod",
            supabase_url="https://supabase.example.com",
            anon_key="test-anon-key",
            service_key="test-service-key",
            db_url="postgresql://test@localhost/test",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "service_name": "dragonfly-api",
            "version": "1.3.1",
            "sha_short": "abc12345",
            "env": "prod",
        }

        with patch.object(certifier, "_api_get_raw", return_value=mock_response):
            result = certifier.check_service_identity()

        assert result.passed, f"Should pass with correct service identity: {result.detail}"
        assert "dragonfly-api" in result.detail
        assert "v1.3.1" in result.detail

    def test_detects_http_404_error(self) -> None:
        """Certifier must fail on 404 response."""
        from tools.certify_prod import ProdCertifier

        certifier = ProdCertifier(
            base_url="https://test.example.com",
            env="prod",
            supabase_url="https://supabase.example.com",
            anon_key="test-anon-key",
            service_key="test-service-key",
            db_url="postgresql://test@localhost/test",
        )

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {}

        with patch.object(certifier, "_api_get_raw", return_value=mock_response):
            result = certifier.check_service_identity()

        assert not result.passed, "Should fail on 404"
        assert "404" in result.detail

    def test_detects_http_502_error(self) -> None:
        """Certifier must fail on 502 Bad Gateway."""
        from tools.certify_prod import ProdCertifier

        certifier = ProdCertifier(
            base_url="https://test.example.com",
            env="prod",
            supabase_url="https://supabase.example.com",
            anon_key="test-anon-key",
            service_key="test-service-key",
            db_url="postgresql://test@localhost/test",
        )

        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.headers = {}

        with patch.object(certifier, "_api_get_raw", return_value=mock_response):
            result = certifier.check_service_identity()

        assert not result.passed, "Should fail on 502"
        assert "502" in result.detail

    def test_detects_non_json_response(self) -> None:
        """Certifier must fail if response is not JSON."""
        from tools.certify_prod import ProdCertifier

        certifier = ProdCertifier(
            base_url="https://test.example.com",
            env="prod",
            supabase_url="https://supabase.example.com",
            anon_key="test-anon-key",
            service_key="test-service-key",
            db_url="postgresql://test@localhost/test",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.side_effect = ValueError("Not JSON")

        with patch.object(certifier, "_api_get_raw", return_value=mock_response):
            result = certifier.check_service_identity()

        assert not result.passed, "Should fail on non-JSON response"
        assert "json" in result.detail.lower()
