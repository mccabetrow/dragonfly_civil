"""
Golden Path Job Types - Canonical job type definitions.

This module defines the official job types for the Dragonfly Golden Path
orchestration pipeline. These types map to ops.job_type_enum in the database.

Pipeline Flow:
    IMPORT_PARSE → ENTITY_RESOLVE → JUDGMENT_CREATE → ENRICHMENT_REQUEST

Usage:
    from backend.config.job_types import JobType

    job_type = JobType.ENTITY_RESOLVE
    print(job_type.value)  # 'entity_resolve'
"""

from enum import Enum
from typing import Dict, List, Optional


class JobType(str, Enum):
    """
    Canonical job types for the Golden Path orchestration pipeline.

    Values must match ops.job_type_enum in PostgreSQL exactly.
    """

    # =========================================================================
    # INTAKE STAGE
    # =========================================================================

    IMPORT_PARSE = "import_parse"
    """
    Stage 1: Parse raw CSV file into staging rows.
    Input: Raw CSV file path
    Output: intake.simplicity_raw_rows with parsed data
    """

    # =========================================================================
    # ORCHESTRATION STAGES (Golden Path)
    # =========================================================================

    ENTITY_RESOLVE = "entity_resolve"
    """
    Stage 2: Resolve raw rows to normalized plaintiff/defendant entities.
    Input: Validated import row
    Output: Linked plaintiff_id, normalized defendant_name
    Triggers: After batch reaches 'validated' status in intake.simplicity_batches
    """

    JUDGMENT_CREATE = "judgment_create"
    """
    Stage 3: Create judgment records from resolved entities.
    Input: Entity-resolved import row
    Output: enforcement.judgments record
    Triggers: After all ENTITY_RESOLVE jobs complete for batch
    """

    ENRICHMENT_REQUEST = "enrichment_request"
    """
    Stage 4: Request external enrichment for defendant data.
    Input: Judgment ID
    Output: Enrichment data in enforcement.judgments
    Triggers: After JUDGMENT_CREATE completes
    """

    # =========================================================================
    # LEGACY ENRICHMENT (existing)
    # =========================================================================

    ENRICH_TLO = "enrich_tlo"
    """TLO enrichment for skip tracing."""

    ENRICH_IDICORE = "enrich_idicore"
    """idiCORE enrichment for asset discovery."""

    # =========================================================================
    # DOCUMENT GENERATION
    # =========================================================================

    GENERATE_PDF = "generate_pdf"
    """Generate PDF documents (demand letters, court filings)."""

    # =========================================================================
    # ENFORCEMENT STRATEGY
    # =========================================================================

    ENFORCEMENT_STRATEGY = "enforcement_strategy"
    """AI-driven enforcement strategy planning."""

    ENFORCEMENT_DRAFTING = "enforcement_drafting"
    """AI-driven document drafting for enforcement."""

    # =========================================================================
    # ORCHESTRATOR INTERNAL
    # =========================================================================

    ORCHESTRATOR_TICK = "orchestrator_tick"
    """
    Heartbeat job for orchestrator to check batch progress.
    Used for polling-based orchestration when events aren't available.
    """


# =============================================================================
# PIPELINE DEFINITIONS
# =============================================================================


class PipelineStage(str, Enum):
    """Stages in the Golden Path pipeline."""

    VALIDATED = "validated"
    ENTITY_RESOLVING = "entity_resolving"
    ENTITY_RESOLVED = "entity_resolved"
    JUDGMENT_CREATING = "judgment_creating"
    JUDGMENT_CREATED = "judgment_created"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    COMPLETE = "complete"
    FAILED = "failed"


# Mapping from pipeline stage to the job type that advances it
STAGE_JOB_MAP: Dict[PipelineStage, Optional[JobType]] = {
    PipelineStage.VALIDATED: JobType.ENTITY_RESOLVE,
    PipelineStage.ENTITY_RESOLVED: JobType.JUDGMENT_CREATE,
    PipelineStage.JUDGMENT_CREATED: JobType.ENRICHMENT_REQUEST,
    PipelineStage.ENRICHED: None,  # Terminal
    PipelineStage.COMPLETE: None,  # Terminal
    PipelineStage.FAILED: None,  # Terminal
}

# Stage transitions
STAGE_TRANSITIONS: Dict[PipelineStage, PipelineStage] = {
    PipelineStage.VALIDATED: PipelineStage.ENTITY_RESOLVING,
    PipelineStage.ENTITY_RESOLVING: PipelineStage.ENTITY_RESOLVED,
    PipelineStage.ENTITY_RESOLVED: PipelineStage.JUDGMENT_CREATING,
    PipelineStage.JUDGMENT_CREATING: PipelineStage.JUDGMENT_CREATED,
    PipelineStage.JUDGMENT_CREATED: PipelineStage.ENRICHING,
    PipelineStage.ENRICHING: PipelineStage.ENRICHED,
    PipelineStage.ENRICHED: PipelineStage.COMPLETE,
}


def get_next_stage(current: PipelineStage) -> Optional[PipelineStage]:
    """Get the next stage in the pipeline, or None if terminal."""
    return STAGE_TRANSITIONS.get(current)


def get_job_for_stage(stage: PipelineStage) -> Optional[JobType]:
    """Get the job type that processes a given stage."""
    return STAGE_JOB_MAP.get(stage)


def is_terminal_stage(stage: PipelineStage) -> bool:
    """Check if a stage is terminal (complete or failed)."""
    return stage in (PipelineStage.COMPLETE, PipelineStage.FAILED)


# =============================================================================
# VALIDATION
# =============================================================================


def validate_job_type(value: str) -> bool:
    """Check if a string is a valid job type."""
    try:
        JobType(value)
        return True
    except ValueError:
        return False


def get_all_job_types() -> List[str]:
    """Get all valid job type values."""
    return [jt.value for jt in JobType]


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "JobType",
    "PipelineStage",
    "STAGE_JOB_MAP",
    "STAGE_TRANSITIONS",
    "get_next_stage",
    "get_job_for_stage",
    "is_terminal_stage",
    "validate_job_type",
    "get_all_job_types",
]
