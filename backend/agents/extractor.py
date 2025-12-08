"""
Dragonfly Engine - Extractor Agent

Pulls raw judgment data from Supabase for downstream processing.
First stage in the enforcement pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from .models import AssetInfo, DebtorIntel, ExtractorInput, ExtractorOutput

logger = logging.getLogger(__name__)


class Extractor:
    """
    Extractor Agent - Stage 1

    Fetches judgment data from Supabase including:
    - Core judgment record
    - Debtor intelligence (employer, bank, assets)
    - Enrichment data
    - Enforcement history (optional)

    Input: ExtractorInput (judgment_id, options)
    Output: ExtractorOutput (raw data bundle)
    """

    def __init__(self, supabase_client: Any = None):
        """
        Initialize Extractor agent.

        Args:
            supabase_client: Supabase client instance. If None, will be
                            lazily loaded from backend.db
        """
        self._client = supabase_client
        self._initialized = False

    async def _ensure_client(self) -> Any:
        """Lazily initialize Supabase client."""
        if self._client is None:
            from ..db import get_supabase_client

            self._client = get_supabase_client()
        return self._client

    # =========================================================================
    # LOGGING HOOKS
    # =========================================================================

    def _log_start(self, input_data: ExtractorInput) -> None:
        """Hook: Called when extraction starts."""
        logger.info(f"[Extractor] Starting extraction for judgment_id={input_data.judgment_id}")

    def _log_complete(self, output: ExtractorOutput, duration_ms: float) -> None:
        """Hook: Called when extraction completes."""
        logger.info(
            f"[Extractor] Completed extraction for judgment_id={output.judgment_id} "
            f"in {duration_ms:.2f}ms"
        )

    def _log_error(self, input_data: ExtractorInput, error: Exception) -> None:
        """Hook: Called when extraction fails."""
        logger.error(
            f"[Extractor] Failed extraction for judgment_id={input_data.judgment_id}: "
            f"{type(error).__name__}: {error}"
        )

    # =========================================================================
    # DATA FETCHING
    # =========================================================================

    async def _fetch_judgment(self, judgment_id: str) -> Optional[dict[str, Any]]:
        """Fetch core judgment record."""
        _client = await self._ensure_client()  # noqa: F841 - Will be used when TODO is implemented

        # TODO: Replace with actual Supabase query
        # response = client.table("judgments").select("*").eq("id", judgment_id).single().execute()
        # return response.data

        # Stub implementation
        logger.debug(f"[Extractor] Fetching judgment {judgment_id}")

        # TODO: Implement actual Supabase fetch
        # This is a placeholder that returns None
        return None

    async def _fetch_debtor_intel(self, judgment_id: str) -> Optional[DebtorIntel]:
        """Fetch debtor intelligence data."""
        _client = await self._ensure_client()  # noqa: F841 - Will be used when TODO is implemented

        # TODO: Replace with actual Supabase query
        # response = (
        #     client.table("debtor_intelligence")
        #     .select("*")
        #     .eq("judgment_id", judgment_id)
        #     .single()
        #     .execute()
        # )
        # if response.data:
        #     return DebtorIntel(**response.data)

        logger.debug(f"[Extractor] Fetching debtor intel for {judgment_id}")
        return None

    async def _fetch_assets(self, judgment_id: str) -> list[AssetInfo]:
        """Fetch asset information from enrichment."""
        _client = await self._ensure_client()  # noqa: F841 - Will be used when TODO is implemented

        # TODO: Replace with actual Supabase query
        # response = (
        #     client.table("assets")
        #     .select("*")
        #     .eq("judgment_id", judgment_id)
        #     .execute()
        # )
        # return [AssetInfo(**row) for row in response.data or []]

        logger.debug(f"[Extractor] Fetching assets for {judgment_id}")
        return []

    # =========================================================================
    # MAIN RUN METHOD
    # =========================================================================

    async def run(self, input_data: ExtractorInput) -> ExtractorOutput:
        """
        Execute the extraction pipeline.

        Args:
            input_data: ExtractorInput with judgment_id and options

        Returns:
            ExtractorOutput with all fetched data

        Raises:
            ValueError: If judgment not found
            Exception: On Supabase errors
        """
        start_time = datetime.utcnow()
        self._log_start(input_data)

        try:
            # Fetch core judgment
            judgment = await self._fetch_judgment(input_data.judgment_id)

            if judgment is None:
                # TODO: In production, raise or return error state
                logger.warning(
                    f"[Extractor] Judgment {input_data.judgment_id} not found - "
                    "returning stub output"
                )
                judgment = {}

            # Fetch optional data
            debtor_intel = None
            assets: list[AssetInfo] = []

            if input_data.include_debtor_intel:
                debtor_intel = await self._fetch_debtor_intel(input_data.judgment_id)

            if input_data.include_assets:
                assets = await self._fetch_assets(input_data.judgment_id)

            # Build output
            output = ExtractorOutput(
                judgment_id=input_data.judgment_id,
                plaintiff_id=judgment.get("plaintiff_id"),
                plaintiff_name=judgment.get("plaintiff_name"),
                debtor_name=judgment.get("debtor_name"),
                case_number=judgment.get("case_number"),
                judgment_amount=(
                    Decimal(str(judgment["judgment_amount"]))
                    if judgment.get("judgment_amount")
                    else None
                ),
                judgment_date=judgment.get("judgment_date"),
                county=judgment.get("county"),
                status=judgment.get("status"),
                enforcement_stage=judgment.get("enforcement_stage"),
                collectability_score=judgment.get("collectability_score"),
                debtor_intel=debtor_intel,
                assets=assets,
                raw_judgment=judgment,
                extracted_at=datetime.utcnow(),
            )

            # Log completion
            duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            self._log_complete(output, duration_ms)

            return output

        except Exception as e:
            self._log_error(input_data, e)
            raise

    # =========================================================================
    # LLM INTEGRATION HOOKS
    # =========================================================================

    async def _llm_extract_from_documents(self, documents: list[str]) -> dict[str, Any]:
        """
        TODO: LLM integration for document extraction.

        Use case: Extract structured data from unstructured court documents,
        PDFs, or scanned images.

        Args:
            documents: List of document texts or URLs

        Returns:
            Extracted structured data

        Implementation notes:
            - Use OpenAI GPT-4 or Claude for extraction
            - Define extraction schema as JSON
            - Handle OCR if needed (via separate service)
        """
        # TODO: Implement LLM call
        # Example:
        # from ..services.ai_service import call_llm
        # response = await call_llm(
        #     system_prompt="Extract judgment data from documents...",
        #     user_prompt="\n\n".join(documents),
        #     response_format={"type": "json_schema", "schema": {...}}
        # )
        # return response

        logger.debug("[Extractor] LLM extraction not implemented")
        return {}
