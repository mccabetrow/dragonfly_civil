"""
Dragonfly Engine - Smart Strategy Agent

Deterministic enforcement strategy selector based on debtor intelligence.

This module implements the "Smart Strategy" logic that automatically
determines the best recovery method when a judgment is ingested:

Decision Tree:
    1. IF employer found → Wage Garnishment
    2. ELIF bank_name found → Bank Levy
    3. ELIF property/home_ownership = 'owner' → Property Lien
    4. ELSE → Surveillance (queue for enrichment)

Usage:
    from backend.workers.smart_strategy import SmartStrategy, StrategyDecision

    strategy = SmartStrategy(conn)
    decision = await strategy.evaluate(judgment_id="uuid-here")

    print(decision.strategy_type)   # "wage_garnishment"
    print(decision.strategy_reason) # "Employer found: ACME Corp at 123 Main St"
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


class StrategyType(str, Enum):
    """Available enforcement strategies."""

    WAGE_GARNISHMENT = "wage_garnishment"
    BANK_LEVY = "bank_levy"
    PROPERTY_LIEN = "property_lien"
    SURVEILLANCE = "surveillance"


@dataclass
class DebtorIntelligence:
    """Container for debtor intelligence data."""

    judgment_id: str
    employer_name: Optional[str] = None
    employer_address: Optional[str] = None
    income_band: Optional[str] = None
    bank_name: Optional[str] = None
    bank_address: Optional[str] = None
    home_ownership: Optional[str] = None
    has_benefits_only_account: Optional[bool] = None
    confidence_score: Optional[float] = None
    is_verified: bool = False
    data_source: Optional[str] = None

    @property
    def has_employer(self) -> bool:
        """Check if valid employer data exists."""
        return bool(self.employer_name and self.employer_name.strip())

    @property
    def has_bank(self) -> bool:
        """Check if valid bank data exists (excluding benefits-only accounts)."""
        if not self.bank_name or not self.bank_name.strip():
            return False
        # Benefits-only accounts are exempt under CPLR 5222(d)
        if self.has_benefits_only_account:
            return False
        return True

    @property
    def is_homeowner(self) -> bool:
        """Check if debtor is a homeowner."""
        return self.home_ownership and self.home_ownership.lower() == "owner"


@dataclass
class StrategyDecision:
    """Result of strategy evaluation."""

    judgment_id: str
    strategy_type: StrategyType
    strategy_reason: str
    intelligence: Optional[DebtorIntelligence] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


class SmartStrategy:
    """
    Smart Strategy Agent - Deterministic Enforcement Selection

    Evaluates debtor intelligence and selects optimal enforcement action
    using a priority-based decision tree.
    """

    def __init__(self, conn: psycopg.Connection):
        """
        Initialize SmartStrategy with database connection.

        Args:
            conn: Active psycopg connection to Supabase
        """
        self.conn = conn

    def _log_start(self, judgment_id: str) -> None:
        """Hook: Called when evaluation starts."""
        logger.info(f"[SmartStrategy] Starting evaluation for judgment_id={judgment_id}")

    def _log_decision(self, decision: StrategyDecision) -> None:
        """Hook: Called when decision is made."""
        logger.info(
            f"[SmartStrategy] Decision for judgment_id={decision.judgment_id}: "
            f"{decision.strategy_type.value} - {decision.strategy_reason}"
        )

    def _log_no_intel(self, judgment_id: str) -> None:
        """Hook: Called when no intelligence found."""
        logger.warning(
            f"[SmartStrategy] No debtor_intelligence found for judgment_id={judgment_id}"
        )

    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================

    def fetch_debtor_intelligence(self, judgment_id: str) -> Optional[DebtorIntelligence]:
        """
        Fetch debtor intelligence from database.

        Note: debtor_intelligence links to core_judgments.id (UUID).
        If judgment_id is a bigint reference to public.judgments,
        the caller must first resolve to core_judgments.id.

        Args:
            judgment_id: UUID of the core_judgment

        Returns:
            DebtorIntelligence object or None if not found
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    judgment_id::text,
                    employer_name,
                    employer_address,
                    income_band,
                    bank_name,
                    bank_address,
                    home_ownership,
                    has_benefits_only_account,
                    confidence_score,
                    is_verified,
                    data_source
                FROM public.debtor_intelligence
                WHERE judgment_id = %s::uuid
                ORDER BY confidence_score DESC NULLS LAST, created_at DESC
                LIMIT 1
                """,
                (judgment_id,),
            )
            row = cur.fetchone()

        if not row:
            return None

        return DebtorIntelligence(
            judgment_id=row["judgment_id"],
            employer_name=row.get("employer_name"),
            employer_address=row.get("employer_address"),
            income_band=row.get("income_band"),
            bank_name=row.get("bank_name"),
            bank_address=row.get("bank_address"),
            home_ownership=row.get("home_ownership"),
            has_benefits_only_account=row.get("has_benefits_only_account"),
            confidence_score=(
                float(row["confidence_score"]) if row.get("confidence_score") else None
            ),
            is_verified=row.get("is_verified", False),
            data_source=row.get("data_source"),
        )

    def persist_plan(self, decision: StrategyDecision) -> str:
        """
        Persist enforcement plan to database.

        Creates a new record in enforcement.enforcement_plans with
        the strategy decision.

        Args:
            decision: Strategy decision to persist

        Returns:
            UUID of the created plan
        """
        plan_id = str(uuid.uuid4())

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO enforcement.enforcement_plans (
                    id,
                    judgment_id,
                    plan_status,
                    priority,
                    strategy_type,
                    strategy_reason,
                    created_at,
                    updated_at
                ) VALUES (
                    %s::uuid,
                    %s::uuid,
                    'pending',
                    1,
                    %s,
                    %s,
                    now(),
                    now()
                )
                RETURNING id::text
                """,
                (
                    plan_id,
                    decision.judgment_id,
                    decision.strategy_type.value,
                    decision.strategy_reason,
                ),
            )
            result = cur.fetchone()
            self.conn.commit()

        created_id = result[0] if result else plan_id
        logger.info(
            f"[SmartStrategy] Persisted plan {created_id} for judgment {decision.judgment_id}"
        )
        return created_id

    # =========================================================================
    # DECISION LOGIC
    # =========================================================================

    def decide(self, intel: Optional[DebtorIntelligence], judgment_id: str) -> StrategyDecision:
        """
        Apply decision tree to determine best enforcement strategy.

        Priority Order:
            1. Wage Garnishment (if employer found)
            2. Bank Levy (if bank found, not benefits-only)
            3. Property Lien (if homeowner)
            4. Surveillance (default - queue for enrichment)

        Args:
            intel: DebtorIntelligence object (may be None)
            judgment_id: UUID for fallback if intel is None

        Returns:
            StrategyDecision with chosen strategy and reason
        """
        # No intelligence available - default to surveillance
        if intel is None:
            return StrategyDecision(
                judgment_id=judgment_id,
                strategy_type=StrategyType.SURVEILLANCE,
                strategy_reason="No debtor intelligence available - queued for enrichment research",
            )

        # Priority 1: Wage Garnishment (employer found)
        if intel.has_employer:
            addr_suffix = f" at {intel.employer_address}" if intel.employer_address else ""
            return StrategyDecision(
                judgment_id=intel.judgment_id,
                strategy_type=StrategyType.WAGE_GARNISHMENT,
                strategy_reason=f"Employer found: {intel.employer_name}{addr_suffix}",
                intelligence=intel,
            )

        # Priority 2: Bank Levy (bank found, not benefits-only)
        if intel.has_bank:
            addr_suffix = f" at {intel.bank_address}" if intel.bank_address else ""
            return StrategyDecision(
                judgment_id=intel.judgment_id,
                strategy_type=StrategyType.BANK_LEVY,
                strategy_reason=f"Bank account found: {intel.bank_name}{addr_suffix}",
                intelligence=intel,
            )

        # Priority 3: Property Lien (homeowner)
        if intel.is_homeowner:
            return StrategyDecision(
                judgment_id=intel.judgment_id,
                strategy_type=StrategyType.PROPERTY_LIEN,
                strategy_reason="Debtor is a homeowner - property lien recommended",
                intelligence=intel,
            )

        # Priority 4: Surveillance (fallback)
        return StrategyDecision(
            judgment_id=intel.judgment_id,
            strategy_type=StrategyType.SURVEILLANCE,
            strategy_reason="Insufficient intelligence for enforcement - queued for surveillance/research",
            intelligence=intel,
        )

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    def evaluate(self, judgment_id: str, persist: bool = True) -> StrategyDecision:
        """
        Evaluate and select enforcement strategy for a judgment.

        This is the main entry point for the Smart Strategy Agent.

        Args:
            judgment_id: UUID of the judgment to evaluate
            persist: If True, persist plan to enforcement.enforcement_plans

        Returns:
            StrategyDecision with strategy_type and strategy_reason
        """
        self._log_start(judgment_id)

        # Fetch debtor intelligence
        intel = self.fetch_debtor_intelligence(judgment_id)

        if intel is None:
            self._log_no_intel(judgment_id)

        # Apply decision logic
        decision = self.decide(intel, judgment_id)
        self._log_decision(decision)

        # Persist if requested
        if persist:
            plan_id = self.persist_plan(decision)
            logger.debug(f"[SmartStrategy] Created plan_id={plan_id}")

        return decision


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================


def run_smart_strategy(
    conn: psycopg.Connection, judgment_id: str, persist: bool = True
) -> StrategyDecision:
    """
    Convenience function to run Smart Strategy evaluation.

    Args:
        conn: Database connection
        judgment_id: UUID of judgment to evaluate
        persist: Whether to save the plan

    Returns:
        StrategyDecision
    """
    agent = SmartStrategy(conn)
    return agent.evaluate(judgment_id, persist=persist)
