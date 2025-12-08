"""
Dragonfly Engine - Normalizer Agent

Standardizes and validates extracted judgment data.
Second stage in the enforcement pipeline.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .models import (
    AssetInfo,
    DebtorIntel,
    ExtractorOutput,
    NormalizedJudgment,
    NormalizerInput,
    NormalizerOutput,
)

logger = logging.getLogger(__name__)

# County name normalization map
NY_COUNTY_MAP: dict[str, str] = {
    # NYC boroughs
    "NEW YORK": "NEW YORK",
    "MANHATTAN": "NEW YORK",
    "NY": "NEW YORK",
    "KINGS": "KINGS",
    "BROOKLYN": "KINGS",
    "QUEENS": "QUEENS",
    "BRONX": "BRONX",
    "THE BRONX": "BRONX",
    "RICHMOND": "RICHMOND",
    "STATEN ISLAND": "RICHMOND",
    # Long Island
    "NASSAU": "NASSAU",
    "SUFFOLK": "SUFFOLK",
    # Hudson Valley
    "WESTCHESTER": "WESTCHESTER",
    "ROCKLAND": "ROCKLAND",
    "ORANGE": "ORANGE",
    "PUTNAM": "PUTNAM",
    "DUTCHESS": "DUTCHESS",
    "ULSTER": "ULSTER",
    # Upstate
    "ALBANY": "ALBANY",
    "ERIE": "ERIE",
    "MONROE": "MONROE",
    "ONONDAGA": "ONONDAGA",
}


class Normalizer:
    """
    Normalizer Agent - Stage 2

    Standardizes extracted data:
    - Normalizes county names
    - Validates required fields
    - Calculates derived fields (age_days, intel flags)
    - Flags data quality issues

    Input: NormalizerInput (ExtractorOutput)
    Output: NormalizerOutput (NormalizedJudgment + intel)
    """

    def __init__(self):
        """Initialize Normalizer agent."""
        self._initialized = True

    # =========================================================================
    # LOGGING HOOKS
    # =========================================================================

    def _log_start(self, input_data: NormalizerInput) -> None:
        """Hook: Called when normalization starts."""
        logger.info(
            f"[Normalizer] Starting normalization for "
            f"judgment_id={input_data.extractor_output.judgment_id}"
        )

    def _log_complete(self, output: NormalizerOutput, duration_ms: float) -> None:
        """Hook: Called when normalization completes."""
        judgment = output.judgment
        logger.info(
            f"[Normalizer] Completed normalization for "
            f"judgment_id={judgment.judgment_id} "
            f"valid={judgment.is_valid} "
            f"warnings={len(judgment.validation_warnings)} "
            f"in {duration_ms:.2f}ms"
        )

    def _log_error(self, input_data: NormalizerInput, error: Exception) -> None:
        """Hook: Called when normalization fails."""
        logger.error(
            f"[Normalizer] Failed normalization for "
            f"judgment_id={input_data.extractor_output.judgment_id}: "
            f"{type(error).__name__}: {error}"
        )

    # =========================================================================
    # NORMALIZATION HELPERS
    # =========================================================================

    def _normalize_county(self, county: str | None) -> str:
        """Normalize county name to canonical form."""
        if not county:
            return ""

        clean = county.strip().upper()
        clean = re.sub(r"\s+COUNTY$", "", clean)
        clean = re.sub(r"\s+CO\.?$", "", clean)

        return NY_COUNTY_MAP.get(clean, clean)

    def _calculate_age_days(self, judgment_date: date | None) -> int:
        """Calculate days since judgment."""
        if not judgment_date:
            return 0

        today = date.today()
        delta = today - judgment_date
        return max(0, delta.days)

    def _validate_judgment(
        self, extractor_output: ExtractorOutput
    ) -> tuple[bool, list[str], list[str]]:
        """
        Validate judgment data.

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Required fields
        if not extractor_output.case_number:
            errors.append("Missing case_number")

        if not extractor_output.debtor_name:
            warnings.append("Missing debtor_name")

        # Amount validation
        if extractor_output.judgment_amount is None:
            errors.append("Missing judgment_amount")
        elif extractor_output.judgment_amount <= 0:
            errors.append(f"Invalid judgment_amount: {extractor_output.judgment_amount}")

        # Date validation
        if extractor_output.judgment_date is None:
            warnings.append("Missing judgment_date")
        elif isinstance(extractor_output.judgment_date, date):
            if extractor_output.judgment_date > date.today():
                warnings.append("judgment_date is in the future")

        # County validation
        if not extractor_output.county:
            warnings.append("Missing county")

        is_valid = len(errors) == 0
        return is_valid, errors, warnings

    def _extract_intel_flags(
        self, debtor_intel: DebtorIntel | None, assets: list[AssetInfo]
    ) -> dict[str, Any]:
        """Extract boolean flags from intel data."""
        has_employer = False
        has_bank = False
        is_homeowner = False
        has_assets = False
        total_asset_value = Decimal("0")

        if debtor_intel:
            has_employer = bool(debtor_intel.employer_name)
            has_bank = bool(debtor_intel.bank_name)
            is_homeowner = debtor_intel.home_ownership == "owner"

        if assets:
            has_assets = True
            for asset in assets:
                if asset.estimated_value and not asset.is_exempt:
                    total_asset_value += asset.estimated_value

        return {
            "has_employer": has_employer,
            "has_bank": has_bank,
            "is_homeowner": is_homeowner,
            "has_assets": has_assets,
            "asset_count": len(assets),
            "total_asset_value": total_asset_value,
        }

    # =========================================================================
    # MAIN RUN METHOD
    # =========================================================================

    async def run(self, input_data: NormalizerInput) -> NormalizerOutput:
        """
        Execute the normalization pipeline.

        Args:
            input_data: NormalizerInput with ExtractorOutput

        Returns:
            NormalizerOutput with normalized judgment data

        Raises:
            Exception: On processing errors
        """
        start_time = datetime.utcnow()
        self._log_start(input_data)

        try:
            ext = input_data.extractor_output

            # Validate
            is_valid, errors, warnings = self._validate_judgment(ext)

            # Normalize county
            county_normalized = self._normalize_county(ext.county)

            # Calculate derived fields
            age_days = self._calculate_age_days(ext.judgment_date)

            # Extract intel flags
            intel_flags = self._extract_intel_flags(ext.debtor_intel, ext.assets)

            # Build normalized judgment
            judgment = NormalizedJudgment(
                judgment_id=ext.judgment_id,
                plaintiff_id=ext.plaintiff_id,
                plaintiff_name=ext.plaintiff_name or "",
                debtor_name=ext.debtor_name or "",
                case_number=ext.case_number or "",
                judgment_amount=ext.judgment_amount or Decimal("0"),
                judgment_date=ext.judgment_date,
                age_days=age_days,
                county=ext.county or "",
                county_normalized=county_normalized,
                status=ext.status or "",
                enforcement_stage=ext.enforcement_stage or "",
                has_employer=intel_flags["has_employer"],
                has_bank=intel_flags["has_bank"],
                is_homeowner=intel_flags["is_homeowner"],
                has_assets=intel_flags["has_assets"],
                asset_count=intel_flags["asset_count"],
                total_asset_value=intel_flags["total_asset_value"],
                is_valid=is_valid,
                validation_errors=errors,
                validation_warnings=warnings,
            )

            output = NormalizerOutput(
                judgment=judgment,
                debtor_intel=ext.debtor_intel,
                assets=ext.assets,
                normalized_at=datetime.utcnow(),
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

    async def _llm_normalize_address(self, address: str) -> dict[str, str]:
        """
        TODO: LLM integration for address normalization.

        Use case: Parse and standardize addresses that don't match
        standard patterns.

        Args:
            address: Raw address string

        Returns:
            Normalized address components

        Implementation notes:
            - Use OpenAI GPT-4 for parsing
            - Extract: street, city, state, zip, county
            - Handle abbreviations and typos
        """
        # TODO: Implement LLM call
        logger.debug("[Normalizer] LLM address normalization not implemented")
        return {}

    async def _llm_entity_resolution(self, debtor_name: str, aliases: list[str]) -> dict[str, Any]:
        """
        TODO: LLM integration for entity resolution.

        Use case: Determine if multiple names refer to the same person.

        Args:
            debtor_name: Primary debtor name
            aliases: List of potential aliases

        Returns:
            Entity resolution result

        Implementation notes:
            - Use LLM to compare name variations
            - Consider nicknames, maiden names, typos
            - Return confidence score
        """
        # TODO: Implement LLM call
        logger.debug("[Normalizer] LLM entity resolution not implemented")
        return {}
