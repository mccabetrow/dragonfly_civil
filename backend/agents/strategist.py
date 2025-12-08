"""
Dragonfly Engine - Strategist Agent

Generates prioritized enforcement strategy from case analysis.
Fourth stage in the enforcement pipeline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from .models import (
    ActionStep,
    DocumentType,
    EnforcementAction,
    EnforcementPlan,
    NormalizerOutput,
    ReasonerOutput,
    StrategistInput,
    StrategistOutput,
)

logger = logging.getLogger(__name__)

# Cost estimates by action type
ACTION_COSTS: dict[EnforcementAction, Decimal] = {
    EnforcementAction.WAGE_GARNISHMENT: Decimal("150"),
    EnforcementAction.BANK_LEVY: Decimal("200"),
    EnforcementAction.PROPERTY_LIEN: Decimal("75"),
    EnforcementAction.ASSET_SEIZURE: Decimal("500"),
    EnforcementAction.PAYMENT_PLAN: Decimal("50"),
    EnforcementAction.INFORMATION_SUBPOENA: Decimal("100"),
    EnforcementAction.RESTRAINING_NOTICE: Decimal("50"),
    EnforcementAction.INCOME_EXECUTION: Decimal("125"),
}

# Duration estimates by action type (days)
ACTION_DURATIONS: dict[EnforcementAction, int] = {
    EnforcementAction.WAGE_GARNISHMENT: 45,
    EnforcementAction.BANK_LEVY: 30,
    EnforcementAction.PROPERTY_LIEN: 14,
    EnforcementAction.ASSET_SEIZURE: 60,
    EnforcementAction.PAYMENT_PLAN: 7,
    EnforcementAction.INFORMATION_SUBPOENA: 45,
    EnforcementAction.RESTRAINING_NOTICE: 7,
    EnforcementAction.INCOME_EXECUTION: 45,
}

# Document requirements by action type
ACTION_DOCUMENTS: dict[EnforcementAction, list[DocumentType]] = {
    EnforcementAction.WAGE_GARNISHMENT: [
        DocumentType.INCOME_EXECUTION,
        DocumentType.RESTRAINING_NOTICE,
    ],
    EnforcementAction.BANK_LEVY: [
        DocumentType.PROPERTY_EXECUTION,
        DocumentType.RESTRAINING_NOTICE,
    ],
    EnforcementAction.PROPERTY_LIEN: [],
    EnforcementAction.INFORMATION_SUBPOENA: [
        DocumentType.INFORMATION_SUBPOENA,
    ],
    EnforcementAction.PAYMENT_PLAN: [
        DocumentType.SETTLEMENT_LETTER,
    ],
}


class Strategist:
    """
    Strategist Agent - Stage 4

    Generates enforcement strategy:
    - Prioritizes opportunities by ROI
    - Builds step-by-step action plan
    - Estimates costs and timelines
    - Identifies fallback strategies

    Input: StrategistInput (ReasonerOutput + NormalizerOutput)
    Output: StrategistOutput (EnforcementPlan)
    """

    def __init__(self):
        """Initialize Strategist agent."""
        self._initialized = True

    # =========================================================================
    # LOGGING HOOKS
    # =========================================================================

    def _log_start(self, input_data: StrategistInput) -> None:
        """Hook: Called when strategy generation starts."""
        logger.info(
            f"[Strategist] Starting strategy generation for "
            f"judgment_id={input_data.reasoner_output.judgment_id}"
        )

    def _log_complete(self, output: StrategistOutput, duration_ms: float) -> None:
        """Hook: Called when strategy generation completes."""
        plan = output.plan
        logger.info(
            f"[Strategist] Completed strategy for judgment_id={plan.judgment_id} "
            f"steps={len(plan.steps)} "
            f"cost=${plan.total_estimated_cost:.2f} "
            f"in {duration_ms:.2f}ms"
        )

    def _log_error(self, input_data: StrategistInput, error: Exception) -> None:
        """Hook: Called when strategy generation fails."""
        logger.error(
            f"[Strategist] Failed strategy for "
            f"judgment_id={input_data.reasoner_output.judgment_id}: "
            f"{type(error).__name__}: {error}"
        )

    # =========================================================================
    # STRATEGY HELPERS
    # =========================================================================

    def _prioritize_opportunities(
        self, reasoner_output: ReasonerOutput
    ) -> list[tuple[int, EnforcementAction, str, float]]:
        """
        Prioritize opportunities by expected ROI.

        Returns:
            List of (priority, action, target, confidence) tuples
        """
        opportunities = reasoner_output.analysis.opportunities

        # Score by confidence * estimated_recovery_rate
        scored = []
        for opp in opportunities:
            # Calculate ROI score
            cost = ACTION_COSTS.get(opp.action, Decimal("100"))
            recovery = opp.estimated_recovery or Decimal("0")
            roi = float(recovery) / max(1, float(cost)) * opp.confidence

            scored.append((roi, opp))

        # Sort by ROI descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Assign priorities
        prioritized = []
        for i, (roi, opp) in enumerate(scored):
            priority = min(5, i + 1)  # 1-5 scale
            prioritized.append((priority, opp.action, opp.target, opp.confidence))

        return prioritized

    def _build_action_steps(
        self,
        prioritized: list[tuple[int, EnforcementAction, str, float]],
        judgment_id: str,
    ) -> list[ActionStep]:
        """Build sequential action steps from prioritized opportunities."""
        steps: list[ActionStep] = []

        for i, (priority, action, target, confidence) in enumerate(prioritized):
            step_num = i + 1

            # Get cost and duration estimates
            cost = ACTION_COSTS.get(action, Decimal("100"))
            duration = ACTION_DURATIONS.get(action, 30)
            documents = ACTION_DOCUMENTS.get(action, [])

            # Build description
            description = self._build_step_description(action, target)

            # Determine dependencies
            # Generally, later steps depend on earlier ones in same category
            dependencies: list[int] = []
            if step_num > 1 and action in {
                EnforcementAction.BANK_LEVY,
                EnforcementAction.ASSET_SEIZURE,
            }:
                # These often follow restraining notice
                for prev_step in steps:
                    if prev_step.action == EnforcementAction.RESTRAINING_NOTICE:
                        dependencies.append(prev_step.step_number)

            step = ActionStep(
                step_number=step_num,
                action=action,
                target=target,
                description=description,
                priority=priority,
                estimated_cost=cost,
                estimated_duration_days=duration,
                dependencies=dependencies,
                documents_required=documents,
            )
            steps.append(step)

        return steps

    def _build_step_description(self, action: EnforcementAction, target: str) -> str:
        """Generate human-readable step description."""
        descriptions = {
            EnforcementAction.WAGE_GARNISHMENT: (
                f"File income execution against employer: {target}"
            ),
            EnforcementAction.BANK_LEVY: (
                f"Execute property levy against bank account at: {target}"
            ),
            EnforcementAction.PROPERTY_LIEN: f"File judgment lien against: {target}",
            EnforcementAction.ASSET_SEIZURE: f"Execute seizure of: {target}",
            EnforcementAction.PAYMENT_PLAN: "Negotiate payment plan with debtor",
            EnforcementAction.INFORMATION_SUBPOENA: f"Serve information subpoena on: {target}",
            EnforcementAction.RESTRAINING_NOTICE: (f"Serve restraining notice on: {target}"),
            EnforcementAction.INCOME_EXECUTION: (f"Execute income execution against: {target}"),
        }
        return descriptions.get(action, f"Execute {action.value} against {target}")

    def _determine_strategy_name(self, steps: list[ActionStep], score: float) -> tuple[str, str]:
        """Determine strategy name and rationale."""
        if not steps:
            return "Discovery", "No clear enforcement path - begin with discovery"

        primary_action = steps[0].action

        if primary_action == EnforcementAction.WAGE_GARNISHMENT:
            return (
                "Wage Garnishment Priority",
                "Known employer enables steady income execution for sustained recovery",
            )
        elif primary_action == EnforcementAction.BANK_LEVY:
            return (
                "Bank Levy Priority",
                "Known bank account enables immediate asset recovery",
            )
        elif primary_action == EnforcementAction.PROPERTY_LIEN:
            return (
                "Asset Protection",
                "Property lien secures judgment position for long-term recovery",
            )
        elif primary_action == EnforcementAction.INFORMATION_SUBPOENA:
            return (
                "Discovery First",
                "Limited intel requires discovery before enforcement",
            )
        else:
            return (
                "Multi-Vector Enforcement",
                "Combined approach targeting multiple recovery paths",
            )

    def _calculate_expected_recovery(
        self, steps: list[ActionStep], judgment_amount: Decimal
    ) -> float:
        """Estimate expected recovery rate based on strategy."""
        if not steps:
            return 0.1  # 10% baseline

        # Base recovery by action type
        base_rates = {
            EnforcementAction.WAGE_GARNISHMENT: 0.70,
            EnforcementAction.BANK_LEVY: 0.50,
            EnforcementAction.PROPERTY_LIEN: 0.40,
            EnforcementAction.PAYMENT_PLAN: 0.30,
            EnforcementAction.INFORMATION_SUBPOENA: 0.20,
        }

        # Weight by priority
        total_weight = 0.0
        weighted_rate = 0.0
        for step in steps:
            weight = 1.0 / step.priority  # Higher priority = higher weight
            rate = base_rates.get(step.action, 0.25)
            weighted_rate += rate * weight
            total_weight += weight

        if total_weight > 0:
            return min(0.95, weighted_rate / total_weight)
        return 0.20

    # =========================================================================
    # MAIN RUN METHOD
    # =========================================================================

    async def run(self, input_data: StrategistInput) -> StrategistOutput:
        """
        Execute the strategy generation pipeline.

        Args:
            input_data: StrategistInput with ReasonerOutput and NormalizerOutput

        Returns:
            StrategistOutput with EnforcementPlan

        Raises:
            Exception: On processing errors
        """
        start_time = datetime.utcnow()
        self._log_start(input_data)

        try:
            reasoner_output = input_data.reasoner_output
            normalizer_output = input_data.normalizer_output
            judgment = normalizer_output.judgment

            # Generate plan ID
            plan_id = f"plan_{uuid.uuid4().hex[:12]}"

            # Prioritize opportunities
            prioritized = self._prioritize_opportunities(reasoner_output)

            # Build action steps
            steps = self._build_action_steps(prioritized, judgment.judgment_id)

            # Calculate totals
            total_cost = sum((s.estimated_cost or Decimal("0")) for s in steps)
            total_duration = sum((s.estimated_duration_days or 0) for s in steps)

            # Determine strategy
            strategy_name, rationale = self._determine_strategy_name(
                steps, reasoner_output.analysis.collectability_score
            )

            # Calculate expected recovery
            expected_recovery = self._calculate_expected_recovery(steps, judgment.judgment_amount)

            # Build risk assessment
            risk_assessment = (
                f"Risk level: {reasoner_output.analysis.risk_level.value}. "
                f"Score: {reasoner_output.analysis.collectability_score:.0f}/100. "
                f"Expected recovery: {expected_recovery:.0%}."
            )

            # Fallback strategies
            fallback_strategies: list[str] = []
            if steps and steps[0].action != EnforcementAction.INFORMATION_SUBPOENA:
                fallback_strategies.append("If primary strategy fails, conduct debtor examination")
            if judgment.judgment_amount > Decimal("25000"):
                fallback_strategies.append("Consider third-party collection agency referral")

            # Build plan
            plan = EnforcementPlan(
                plan_id=plan_id,
                judgment_id=judgment.judgment_id,
                strategy_name=strategy_name,
                strategy_rationale=rationale,
                steps=steps,
                total_estimated_cost=total_cost,
                total_estimated_duration_days=total_duration,
                expected_recovery_rate=expected_recovery,
                risk_assessment=risk_assessment,
                fallback_strategies=fallback_strategies,
            )

            output = StrategistOutput(
                plan=plan,
                strategized_at=datetime.utcnow(),
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

    async def _llm_optimize_strategy(
        self, plan: EnforcementPlan, constraints: list[str]
    ) -> EnforcementPlan:
        """
        TODO: LLM integration for strategy optimization.

        Use case: Refine strategy based on complex constraints
        or precedent from similar cases.

        Args:
            plan: Initial enforcement plan
            constraints: Business/legal constraints to consider

        Returns:
            Optimized enforcement plan

        Implementation notes:
            - Use Claude or GPT-4 for reasoning
            - Include NY enforcement law context
            - Consider plaintiff preferences
        """
        # TODO: Implement LLM call
        logger.debug("[Strategist] LLM strategy optimization not implemented")
        return plan

    async def _llm_generate_rationale(self, plan: EnforcementPlan) -> str:
        """
        TODO: LLM integration for strategy explanation.

        Use case: Generate human-readable explanation of
        why this strategy was chosen.

        Args:
            plan: Enforcement plan

        Returns:
            Strategy rationale text

        Implementation notes:
            - Generate clear, professional explanation
            - Suitable for plaintiff/attorney review
            - Include key decision factors
        """
        # TODO: Implement LLM call
        logger.debug("[Strategist] LLM rationale generation not implemented")
        return plan.strategy_rationale
