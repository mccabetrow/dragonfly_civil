"""
Dragonfly Engine - AI Service

OpenAI integration for embedding generation and AI-powered features.
Handles vectorization of judgment data for semantic search.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# OpenAI embedding model
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMENSIONS = 1536
OPENAI_API_URL = "https://api.openai.com/v1/embeddings"

# Timeout for embedding requests (seconds)
EMBED_TIMEOUT = 30.0


def _get_openai_api_key() -> Optional[str]:
    """
    Get OpenAI API key from settings (falls back to env var).

    Returns:
        API key string or None if not configured
    """
    # Prefer settings, fall back to environment
    if settings.openai_api_key:
        return settings.openai_api_key

    import os

    return os.environ.get("OPENAI_API_KEY")


async def generate_embedding(text: str) -> Optional[list[float]]:
    """
    Generate an embedding vector for the given text using OpenAI.

    Args:
        text: Input text to embed

    Returns:
        List of floats (1536 dimensions) or None on failure/empty input

    Notes:
        - Returns None if text is empty or whitespace only
        - Returns None if OpenAI API call fails (logs error)
        - Does not raise exceptions; designed for graceful degradation
    """
    # Validate input
    if not text or not text.strip():
        logger.debug("Empty text provided for embedding, returning None")
        return None

    text = text.strip()

    # Get API key
    api_key = _get_openai_api_key()
    if not api_key:
        logger.warning("OPENAI_API_KEY not configured, skipping embedding generation")
        return None

    try:
        async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
            response = await client.post(
                OPENAI_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EMBED_MODEL,
                    "input": text,
                    "dimensions": EMBED_DIMENSIONS,
                },
            )

            if response.status_code != 200:
                logger.error(
                    f"OpenAI embedding API error: {response.status_code} - {response.text}"
                )
                return None

            data = response.json()
            embedding = data.get("data", [{}])[0].get("embedding")

            if not embedding:
                logger.error("No embedding returned from OpenAI API")
                return None

            logger.debug(f"Generated embedding with {len(embedding)} dimensions")
            return embedding

    except httpx.TimeoutException:
        logger.error(f"OpenAI embedding request timed out after {EMBED_TIMEOUT}s")
        return None
    except httpx.RequestError as e:
        logger.error(f"OpenAI embedding request failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error generating embedding: {e}")
        return None


def build_judgment_context(
    plaintiff_name: Optional[str] = None,
    defendant_name: Optional[str] = None,
    court_name: Optional[str] = None,
    county_name: Optional[str] = None,
    judgment_amount: Optional[float] = None,
    case_number: Optional[str] = None,
    judgment_date: Optional[str] = None,
) -> str:
    """
    Build a rich context string for a judgment to be embedded.

    This string is what gets vectorized for semantic search.

    Args:
        plaintiff_name: Name of the plaintiff/creditor
        defendant_name: Name of the defendant/debtor
        court_name: Court where judgment was entered
        county_name: County of the court
        judgment_amount: Dollar amount of the judgment
        case_number: Court case/docket number
        judgment_date: Date judgment was entered

    Returns:
        Formatted context string suitable for embedding
    """
    parts = []

    if plaintiff_name:
        parts.append(f"Plaintiff: {plaintiff_name}")
    if defendant_name:
        parts.append(f"Defendant: {defendant_name}")
    if court_name:
        parts.append(f"Court: {court_name}")
    if county_name:
        parts.append(f"County: {county_name}")
    if judgment_amount is not None:
        parts.append(f"Amount: ${judgment_amount:,.2f}")
    if case_number:
        parts.append(f"Case Number: {case_number}")
    if judgment_date:
        parts.append(f"Judgment Date: {judgment_date}")

    return "; ".join(parts) if parts else ""


async def generate_judgment_embedding(
    plaintiff_name: Optional[str] = None,
    defendant_name: Optional[str] = None,
    court_name: Optional[str] = None,
    county_name: Optional[str] = None,
    judgment_amount: Optional[float] = None,
    case_number: Optional[str] = None,
    judgment_date: Optional[str] = None,
) -> Optional[list[float]]:
    """
    Generate an embedding for a judgment record.

    Convenience wrapper that builds context and generates embedding.

    Args:
        All judgment fields (see build_judgment_context)

    Returns:
        Embedding vector or None on failure
    """
    context = build_judgment_context(
        plaintiff_name=plaintiff_name,
        defendant_name=defendant_name,
        court_name=court_name,
        county_name=county_name,
        judgment_amount=judgment_amount,
        case_number=case_number,
        judgment_date=judgment_date,
    )

    if not context:
        logger.debug("Empty judgment context, skipping embedding")
        return None

    return await generate_embedding(context)
