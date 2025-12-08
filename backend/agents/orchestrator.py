"""
Dragonfly Engine - Orchestrator

Top-level pipeline coordinator that runs all agents in sequence
and persists results to Supabase.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from .auditor import Auditor
from .drafter import Drafter
from .extractor import Extractor
from .models import (
    AuditorInput,
    DrafterInput,
    ExtractorInput,
    NormalizerInput,
    OrchestratorInput,
    OrchestratorOutput,
    PipelineStage,
    ReasonerInput,
    StrategistInput,
)
from .normalizer import Normalizer
from .reasoner import Reasoner
from .strategist import Strategist

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Pipeline Orchestrator

    Coordinates the full enforcement automation pipeline:
    1. Extractor   → Pull judgment data
    2. Normalizer  → Standardize and validate
    3. Reasoner    → Analyze and identify opportunities
    4. Strategist  → Generate enforcement plan
    5. Drafter     → Create document packet
    6. Auditor     → Validate outputs

    Results are persisted to Supabase tables:
    - enforcement_plans
    - draft_packets
    - audit_results
    """

    def __init__(self, supabase_client: Any = None):
        """
        Initialize Orchestrator with optional Supabase client.

        Args:
            supabase_client: Supabase client instance. If None,
                            will be lazily loaded from backend.db
        """
        self._client = supabase_client

        # Initialize agents
        self.extractor = Extractor(supabase_client)
        self.normalizer = Normalizer()
        self.reasoner = Reasoner()
        self.strategist = Strategist()
        self.drafter = Drafter()
        self.auditor = Auditor()

    async def _ensure_client(self) -> Any:
        """Lazily initialize Supabase client."""
        if self._client is None:
            from ..db import get_supabase_client

            self._client = get_supabase_client()
        return self._client

    # =========================================================================
    # LOGGING HOOKS
    # =========================================================================

    def _log_pipeline_start(self, input_data: OrchestratorInput, run_id: str) -> None:
        """Hook: Called when pipeline starts."""
        logger.info(
            f"[Orchestrator] Starting pipeline run_id={run_id} "
            f"judgment_id={input_data.judgment_id} "
            f"dry_run={input_data.dry_run}"
        )

    def _log_stage_start(self, stage: PipelineStage, run_id: str) -> None:
        """Hook: Called when a stage starts."""
        logger.debug(f"[Orchestrator] run_id={run_id} → Stage: {stage.value}")

    def _log_stage_complete(self, stage: PipelineStage, run_id: str, duration_ms: float) -> None:
        """Hook: Called when a stage completes."""
        logger.debug(
            f"[Orchestrator] run_id={run_id} ← Stage: {stage.value} "
            f"completed in {duration_ms:.2f}ms"
        )

    def _log_pipeline_complete(self, output: OrchestratorOutput, duration_s: float) -> None:
        """Hook: Called when pipeline completes."""
        logger.info(
            f"[Orchestrator] Pipeline complete run_id={output.run_id} "
            f"success={output.success} "
            f"stages={len(output.stages_completed)} "
            f"duration={duration_s:.2f}s"
        )

    def _log_pipeline_error(self, run_id: str, stage: PipelineStage, error: Exception) -> None:
        """Hook: Called when pipeline fails."""
        logger.error(
            f"[Orchestrator] Pipeline failed run_id={run_id} "
            f"stage={stage.value} "
            f"error={type(error).__name__}: {error}"
        )

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_enforcement_plan(self, output: OrchestratorOutput) -> Optional[str]:
        """
        Persist enforcement plan to Supabase.

        Returns:
            Plan ID if persisted, None otherwise
        """
        if not output.strategist_output:
            return None

        _client = await self._ensure_client()  # noqa: F841 - Will be used when TODO is implemented
        plan = output.strategist_output.plan

        # TODO: Replace with actual Supabase upsert
        # data = {
        #     "id": plan.plan_id,
        #     "judgment_id": plan.judgment_id,
        #     "strategy_name": plan.strategy_name,
        #     "strategy_rationale": plan.strategy_rationale,
        #     "steps": [s.model_dump() for s in plan.steps],
        #     "total_estimated_cost": float(plan.total_estimated_cost),
        #     "total_estimated_duration_days": plan.total_estimated_duration_days,
        #     "expected_recovery_rate": plan.expected_recovery_rate,
        #     "risk_assessment": plan.risk_assessment,
        #     "fallback_strategies": plan.fallback_strategies,
        #     "created_at": datetime.utcnow().isoformat(),
        # }
        # response = client.table("enforcement_plans").upsert(data).execute()

        logger.debug(f"[Orchestrator] Would persist enforcement_plan: {plan.plan_id}")
        return plan.plan_id

    async def _persist_draft_packet(self, output: OrchestratorOutput) -> Optional[str]:
        """
        Persist draft packet to Supabase.

        Returns:
            Packet ID if persisted, None otherwise
        """
        if not output.drafter_output:
            return None

        _client = await self._ensure_client()  # noqa: F841 - Will be used when TODO is implemented
        packet = output.drafter_output.packet

        # TODO: Replace with actual Supabase upsert
        # data = {
        #     "id": packet.packet_id,
        #     "judgment_id": packet.judgment_id,
        #     "plan_id": packet.plan_id,
        #     "documents": [
        #         {
        #             "type": d.document_type.value,
        #             "title": d.title,
        #             "content": d.content,
        #             "placeholders": d.placeholders,
        #             "is_complete": d.is_complete,
        #         }
        #         for d in packet.documents
        #     ],
        #     "cover_letter": packet.cover_letter,
        #     "filing_checklist": packet.filing_checklist,
        #     "total_filing_fees": float(packet.total_filing_fees),
        #     "created_at": datetime.utcnow().isoformat(),
        # }
        # response = client.table("draft_packets").upsert(data).execute()

        logger.debug(f"[Orchestrator] Would persist draft_packet: {packet.packet_id}")
        return packet.packet_id

    async def _persist_audit_result(self, output: OrchestratorOutput) -> None:
        """Persist audit result to Supabase."""
        if not output.auditor_output:
            return

        _client = await self._ensure_client()  # noqa: F841 - Will be used when TODO is implemented
        audit = output.auditor_output

        # TODO: Replace with actual Supabase upsert
        # data = {
        #     "judgment_id": audit.judgment_id,
        #     "packet_id": audit.packet_id,
        #     "is_approved": audit.audit.is_approved,
        #     "score": audit.audit.score,
        #     "issues": [i.model_dump() for i in audit.audit.issues],
        #     "warnings": audit.audit.warnings,
        #     "passed_checks": audit.audit.passed_checks,
        #     "recommendations": audit.audit.recommendations,
        #     "audited_at": audit.audited_at.isoformat(),
        # }
        # response = client.table("audit_results").upsert(data).execute()

        logger.debug(f"[Orchestrator] Would persist audit_result for packet: {audit.packet_id}")

    async def _update_judgment_status(self, judgment_id: str, output: OrchestratorOutput) -> None:
        """Update judgment with pipeline results."""
        _client = await self._ensure_client()  # noqa: F841 - Will be used when TODO is implemented

        # TODO: Replace with actual Supabase update
        # new_stage = "plan_generated" if output.success else "pipeline_error"
        # data = {
        #     "enforcement_stage": new_stage,
        #     "last_pipeline_run": datetime.utcnow().isoformat(),
        #     "current_plan_id": output.persisted_plan_id,
        # }
        # response = (
        #     client.table("judgments")
        #     .update(data)
        #     .eq("id", judgment_id)
        #     .execute()
        # )

        logger.debug(f"[Orchestrator] Would update judgment status: {judgment_id}")

    # =========================================================================
    # MAIN RUN METHOD
    # =========================================================================

    async def run(self, input_data: OrchestratorInput) -> OrchestratorOutput:
        """
        Execute the full enforcement pipeline.

        Args:
            input_data: OrchestratorInput with judgment_id and options

        Returns:
            OrchestratorOutput with all stage outputs and metadata

        Pipeline stages:
            1. Extractor - Fetch judgment data
            2. Normalizer - Validate and standardize
            3. Reasoner - Analyze opportunities
            4. Strategist - Generate plan
            5. Drafter - Create documents (optional)
            6. Auditor - Validate outputs (optional)

        Results are persisted to Supabase unless dry_run=True.
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        started_at = datetime.utcnow()
        current_stage = PipelineStage.EXTRACTOR

        self._log_pipeline_start(input_data, run_id)

        # Initialize output
        output = OrchestratorOutput(
            judgment_id=input_data.judgment_id,
            run_id=run_id,
            final_stage=PipelineStage.EXTRACTOR,
            success=False,
            started_at=started_at,
        )

        try:
            # -----------------------------------------------------------------
            # STAGE 1: EXTRACTOR
            # -----------------------------------------------------------------
            current_stage = PipelineStage.EXTRACTOR
            self._log_stage_start(current_stage, run_id)
            stage_start = datetime.utcnow()

            extractor_input = ExtractorInput(
                judgment_id=input_data.judgment_id,
                include_debtor_intel=True,
                include_assets=True,
            )
            output.extractor_output = await self.extractor.run(extractor_input)
            output.stages_completed.append(current_stage)

            stage_ms = (datetime.utcnow() - stage_start).total_seconds() * 1000
            self._log_stage_complete(current_stage, run_id, stage_ms)

            # -----------------------------------------------------------------
            # STAGE 2: NORMALIZER
            # -----------------------------------------------------------------
            current_stage = PipelineStage.NORMALIZER
            self._log_stage_start(current_stage, run_id)
            stage_start = datetime.utcnow()

            normalizer_input = NormalizerInput(extractor_output=output.extractor_output)
            output.normalizer_output = await self.normalizer.run(normalizer_input)
            output.stages_completed.append(current_stage)

            stage_ms = (datetime.utcnow() - stage_start).total_seconds() * 1000
            self._log_stage_complete(current_stage, run_id, stage_ms)

            # -----------------------------------------------------------------
            # STAGE 3: REASONER
            # -----------------------------------------------------------------
            current_stage = PipelineStage.REASONER
            self._log_stage_start(current_stage, run_id)
            stage_start = datetime.utcnow()

            reasoner_input = ReasonerInput(normalizer_output=output.normalizer_output)
            output.reasoner_output = await self.reasoner.run(reasoner_input)
            output.stages_completed.append(current_stage)

            stage_ms = (datetime.utcnow() - stage_start).total_seconds() * 1000
            self._log_stage_complete(current_stage, run_id, stage_ms)

            # -----------------------------------------------------------------
            # STAGE 4: STRATEGIST
            # -----------------------------------------------------------------
            current_stage = PipelineStage.STRATEGIST
            self._log_stage_start(current_stage, run_id)
            stage_start = datetime.utcnow()

            strategist_input = StrategistInput(
                reasoner_output=output.reasoner_output,
                normalizer_output=output.normalizer_output,
            )
            output.strategist_output = await self.strategist.run(strategist_input)
            output.stages_completed.append(current_stage)

            stage_ms = (datetime.utcnow() - stage_start).total_seconds() * 1000
            self._log_stage_complete(current_stage, run_id, stage_ms)

            # -----------------------------------------------------------------
            # STAGE 5: DRAFTER (optional)
            # -----------------------------------------------------------------
            if not input_data.skip_draft:
                current_stage = PipelineStage.DRAFTER
                self._log_stage_start(current_stage, run_id)
                stage_start = datetime.utcnow()

                drafter_input = DrafterInput(
                    strategist_output=output.strategist_output,
                    normalizer_output=output.normalizer_output,
                )
                output.drafter_output = await self.drafter.run(drafter_input)
                output.stages_completed.append(current_stage)

                stage_ms = (datetime.utcnow() - stage_start).total_seconds() * 1000
                self._log_stage_complete(current_stage, run_id, stage_ms)

                # ---------------------------------------------------------
                # STAGE 6: AUDITOR (optional)
                # ---------------------------------------------------------
                if not input_data.skip_audit:
                    current_stage = PipelineStage.AUDITOR
                    self._log_stage_start(current_stage, run_id)
                    stage_start = datetime.utcnow()

                    auditor_input = AuditorInput(
                        drafter_output=output.drafter_output,
                        strategist_output=output.strategist_output,
                        normalizer_output=output.normalizer_output,
                    )
                    output.auditor_output = await self.auditor.run(auditor_input)
                    output.stages_completed.append(current_stage)

                    stage_ms = (datetime.utcnow() - stage_start).total_seconds() * 1000
                    self._log_stage_complete(current_stage, run_id, stage_ms)

            # -----------------------------------------------------------------
            # PERSISTENCE
            # -----------------------------------------------------------------
            if not input_data.dry_run:
                output.persisted_plan_id = await self._persist_enforcement_plan(output)
                output.persisted_packet_id = await self._persist_draft_packet(output)
                await self._persist_audit_result(output)
                await self._update_judgment_status(input_data.judgment_id, output)

            # Mark success
            output.success = True
            output.final_stage = PipelineStage.COMPLETE

        except Exception as e:
            self._log_pipeline_error(run_id, current_stage, e)
            output.error_stage = current_stage
            output.error_message = str(e)
            output.final_stage = PipelineStage.FAILED

        # Finalize timing
        completed_at = datetime.utcnow()
        output.completed_at = completed_at
        output.duration_seconds = (completed_at - started_at).total_seconds()

        self._log_pipeline_complete(output, output.duration_seconds)

        return output

    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================

    async def run_dry(self, judgment_id: str) -> OrchestratorOutput:
        """
        Run pipeline in dry-run mode (no persistence).

        Args:
            judgment_id: Judgment to process

        Returns:
            OrchestratorOutput
        """
        return await self.run(OrchestratorInput(judgment_id=judgment_id, dry_run=True))

    async def run_strategy_only(self, judgment_id: str) -> OrchestratorOutput:
        """
        Run pipeline through strategist only (no drafting/auditing).

        Args:
            judgment_id: Judgment to process

        Returns:
            OrchestratorOutput
        """
        return await self.run(
            OrchestratorInput(
                judgment_id=judgment_id,
                skip_draft=True,
                dry_run=True,
            )
        )

    async def run_full(self, judgment_id: str) -> OrchestratorOutput:
        """
        Run full pipeline with persistence.

        Args:
            judgment_id: Judgment to process

        Returns:
            OrchestratorOutput
        """
        return await self.run(OrchestratorInput(judgment_id=judgment_id))
