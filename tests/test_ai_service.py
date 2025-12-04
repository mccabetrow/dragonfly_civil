"""
Tests for backend.services.ai_service

Unit tests for embedding generation with mocked OpenAI API.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_embedding() -> list[float]:
    """Standard 1536-dimension mock embedding."""
    return [0.01] * 1536


@pytest.fixture
def mock_openai_response(mock_embedding: list[float]) -> dict[str, Any]:
    """Mock successful OpenAI embedding API response."""
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": mock_embedding}],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 8, "total_tokens": 8},
    }


class TestGenerateEmbedding:
    """Tests for generate_embedding function."""

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_text(self):
        """Empty or whitespace-only input returns None without API call."""
        from backend.services.ai_service import generate_embedding

        assert await generate_embedding("") is None
        assert await generate_embedding("   ") is None
        assert await generate_embedding("\n\t") is None

    @pytest.mark.asyncio
    async def test_returns_none_when_api_key_missing(self, monkeypatch):
        """Returns None when OPENAI_API_KEY is not configured."""
        from backend.services.ai_service import generate_embedding

        # Ensure env var is not set
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # Clear settings cache to force re-read
        with patch("backend.services.ai_service.settings") as mock_settings:
            mock_settings.openai_api_key = None
            result = await generate_embedding("test text")

        assert result is None

    @pytest.mark.asyncio
    async def test_successful_embedding_generation(
        self, mock_embedding: list[float], mock_openai_response: dict[str, Any]
    ):
        """Successfully generates embedding with valid API key and response."""
        from backend.services.ai_service import generate_embedding

        # Mock the httpx client
        mock_response = AsyncMock()
        mock_response.status_code = 200
        # Use regular MagicMock for json() since it returns a dict synchronously
        mock_response.json = lambda: mock_openai_response

        with patch("backend.services.ai_service._get_openai_api_key") as mock_key:
            mock_key.return_value = "sk-test-key"
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__.return_value = mock_instance
                mock_instance.__aexit__.return_value = None
                mock_client.return_value = mock_instance

                result = await generate_embedding("Test judgment text")

        assert result is not None
        assert len(result) == 1536
        assert result == mock_embedding

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        """Returns None (graceful degradation) on API error."""
        from backend.services.ai_service import generate_embedding

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("backend.services.ai_service._get_openai_api_key") as mock_key:
            mock_key.return_value = "sk-test-key"
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__.return_value = mock_instance
                mock_instance.__aexit__.return_value = None
                mock_client.return_value = mock_instance

                result = await generate_embedding("Test text")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self):
        """Returns None on request timeout."""
        import httpx

        from backend.services.ai_service import generate_embedding

        with patch("backend.services.ai_service._get_openai_api_key") as mock_key:
            mock_key.return_value = "sk-test-key"
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post.side_effect = httpx.TimeoutException("timeout")
                mock_instance.__aenter__.return_value = mock_instance
                mock_instance.__aexit__.return_value = None
                mock_client.return_value = mock_instance

                result = await generate_embedding("Test text")

        assert result is None


class TestBuildJudgmentContext:
    """Tests for build_judgment_context function."""

    def test_builds_context_with_all_fields(self):
        """Builds context string with all judgment fields."""
        from backend.services.ai_service import build_judgment_context

        context = build_judgment_context(
            plaintiff_name="John Doe",
            defendant_name="ABC Corp",
            court_name="Supreme Court",
            county_name="New York",
            judgment_amount=50000.0,
            case_number="2024-CV-1234",
            judgment_date="2024-01-15",
        )

        assert "John Doe" in context
        assert "ABC Corp" in context
        assert "Supreme Court" in context
        assert "New York" in context
        assert "50000" in context or "$50,000" in context
        assert "2024-CV-1234" in context
        assert "2024-01-15" in context

    def test_handles_partial_fields(self):
        """Builds context with only some fields provided."""
        from backend.services.ai_service import build_judgment_context

        context = build_judgment_context(
            plaintiff_name="Jane Smith",
            defendant_name=None,
            judgment_amount=10000.0,
        )

        assert "Jane Smith" in context
        assert "10000" in context or "$10,000" in context
        # Should not crash with None values

    def test_handles_empty_fields(self):
        """Returns valid string even with no fields."""
        from backend.services.ai_service import build_judgment_context

        context = build_judgment_context()

        assert isinstance(context, str)
