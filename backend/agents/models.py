"""
Dragonfly Engine - Agent Models

Pydantic models for agent input/output interfaces.
All agents share these canonical types for pipeline interoperability.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# =============================================================================
# ENUMS
# =============================================================================


class EnforcementAction(str, Enum):
    """Supported enforcement actions."""

    WAGE_GARNISHMENT = "wage_garnishment"
    BANK_LEVY = "bank_levy"
    PROPERTY_LIEN = "property_lien"
    ASSET_SEIZURE = "asset_seizure"
    PAYMENT_PLAN = "payment_plan"
    INFORMATION_SUBPOENA = "information_subpoena"
    RESTRAINING_NOTICE = "restraining_notice"
    INCOME_EXECUTION = "income_execution"


class RiskLevel(str, Enum):
    """Case risk classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DocumentType(str, Enum):
    """Generated document types."""

    INCOME_EXECUTION = "income_execution"
    RESTRAINING_NOTICE = "restraining_notice"
    PROPERTY_EXECUTION = "property_execution"
    INFORMATION_SUBPOENA = "information_subpoena"
    SETTLEMENT_LETTER = "settlement_letter"
    DEMAND_LETTER = "demand_letter"


# =============================================================================
# EXTRACTOR MODELS
# =============================================================================


class ExtractorInput(BaseModel):
    """Input to Extractor agent."""

    judgment_id: str = Field(..., description="Supabase judgment UUID")
    include_debtor_intel: bool = Field(default=True, description="Fetch debtor_intelligence")
    include_assets: bool = Field(default=True, description="Fetch enrichment.assets")
    include_history: bool = Field(default=False, description="Fetch enforcement_history")


class DebtorIntel(BaseModel):
    """Debtor intelligence data."""

    employer_name: Optional[str] = None
    employer_address: Optional[str] = None
    income_band: Optional[str] = None
    bank_name: Optional[str] = None
    bank_address: Optional[str] = None
    home_ownership: Optional[str] = None
    is_verified: bool = False
    confidence_score: Optional[float] = None
    last_updated: Optional[datetime] = None


class AssetInfo(BaseModel):
    """Asset information from enrichment."""

    asset_type: str
    description: Optional[str] = None
    estimated_value: Optional[Decimal] = None
    location: Optional[str] = None
    is_exempt: bool = False
    source: Optional[str] = None


class ExtractorOutput(BaseModel):
    """Output from Extractor agent."""

    judgment_id: str
    plaintiff_id: Optional[str] = None
    plaintiff_name: Optional[str] = None
    debtor_name: Optional[str] = None
    case_number: Optional[str] = None
    judgment_amount: Optional[Decimal] = None
    judgment_date: Optional[date] = None
    county: Optional[str] = None
    status: Optional[str] = None
    enforcement_stage: Optional[str] = None
    collectability_score: Optional[float] = None

    debtor_intel: Optional[DebtorIntel] = None
    assets: list[AssetInfo] = Field(default_factory=list)

    raw_judgment: dict[str, Any] = Field(default_factory=dict, description="Full judgment row")
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# NORMALIZER MODELS
# =============================================================================


class NormalizerInput(BaseModel):
    """Input to Normalizer agent."""

    extractor_output: ExtractorOutput


class NormalizedJudgment(BaseModel):
    """Normalized judgment data with validation flags."""

    judgment_id: str
    plaintiff_id: Optional[str] = None
    plaintiff_name: str = ""
    debtor_name: str = ""
    case_number: str = ""
    judgment_amount: Decimal = Decimal("0")
    judgment_date: Optional[date] = None
    age_days: int = 0
    county: str = ""
    county_normalized: str = ""  # Standardized county name
    status: str = ""
    enforcement_stage: str = ""

    # Intel summary
    has_employer: bool = False
    has_bank: bool = False
    is_homeowner: bool = False
    has_assets: bool = False
    asset_count: int = 0
    total_asset_value: Decimal = Decimal("0")

    # Validation
    is_valid: bool = True
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)


class NormalizerOutput(BaseModel):
    """Output from Normalizer agent."""

    judgment: NormalizedJudgment
    debtor_intel: Optional[DebtorIntel] = None
    assets: list[AssetInfo] = Field(default_factory=list)
    normalized_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# REASONER MODELS
# =============================================================================


class ReasonerInput(BaseModel):
    """Input to Reasoner agent."""

    normalizer_output: NormalizerOutput


class EnforcementOpportunity(BaseModel):
    """Identified enforcement opportunity."""

    action: EnforcementAction
    target: str = Field(..., description="Target entity (employer, bank, etc.)")
    rationale: str = Field(..., description="Why this action is recommended")
    confidence: float = Field(..., ge=0, le=1, description="Confidence 0-1")
    estimated_recovery: Optional[Decimal] = None
    time_to_recovery_days: Optional[int] = None
    legal_requirements: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class CaseAnalysis(BaseModel):
    """Full case analysis from reasoner."""

    collectability_score: float = Field(..., ge=0, le=100)
    risk_level: RiskLevel
    key_facts: list[str] = Field(default_factory=list)
    opportunities: list[EnforcementOpportunity] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)


class ReasonerOutput(BaseModel):
    """Output from Reasoner agent."""

    judgment_id: str
    analysis: CaseAnalysis
    reasoned_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# STRATEGIST MODELS
# =============================================================================


class StrategistInput(BaseModel):
    """Input to Strategist agent."""

    reasoner_output: ReasonerOutput
    normalizer_output: NormalizerOutput


class ActionStep(BaseModel):
    """Single step in enforcement plan."""

    step_number: int
    action: EnforcementAction
    target: str
    description: str
    priority: int = Field(..., ge=1, le=5, description="1=highest priority")
    estimated_cost: Optional[Decimal] = None
    estimated_duration_days: Optional[int] = None
    dependencies: list[int] = Field(
        default_factory=list, description="Step numbers that must complete first"
    )
    documents_required: list[DocumentType] = Field(default_factory=list)


class EnforcementPlan(BaseModel):
    """Full enforcement strategy plan."""

    plan_id: str = Field(..., description="Unique plan identifier")
    judgment_id: str
    strategy_name: str
    strategy_rationale: str
    steps: list[ActionStep] = Field(default_factory=list)
    total_estimated_cost: Decimal = Decimal("0")
    total_estimated_duration_days: int = 0
    expected_recovery_rate: float = Field(..., ge=0, le=1)
    risk_assessment: str = ""
    fallback_strategies: list[str] = Field(default_factory=list)


class StrategistOutput(BaseModel):
    """Output from Strategist agent."""

    plan: EnforcementPlan
    strategized_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# DRAFTER MODELS
# =============================================================================


class DrafterInput(BaseModel):
    """Input to Drafter agent."""

    strategist_output: StrategistOutput
    normalizer_output: NormalizerOutput


class DraftDocument(BaseModel):
    """Generated document draft."""

    document_type: DocumentType
    title: str
    content: str = Field(..., description="Full document text")
    placeholders: list[str] = Field(
        default_factory=list, description="Fields requiring human review"
    )
    is_complete: bool = True
    requires_notarization: bool = False
    filing_instructions: Optional[str] = None


class DraftPacket(BaseModel):
    """Complete packet of enforcement documents."""

    packet_id: str
    judgment_id: str
    plan_id: str
    documents: list[DraftDocument] = Field(default_factory=list)
    cover_letter: Optional[str] = None
    filing_checklist: list[str] = Field(default_factory=list)
    total_filing_fees: Decimal = Decimal("0")


class DrafterOutput(BaseModel):
    """Output from Drafter agent."""

    packet: DraftPacket
    drafted_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# AUDITOR MODELS
# =============================================================================


class AuditorInput(BaseModel):
    """Input to Auditor agent."""

    drafter_output: DrafterOutput
    strategist_output: StrategistOutput
    normalizer_output: NormalizerOutput


class ComplianceIssue(BaseModel):
    """Identified compliance or quality issue."""

    severity: RiskLevel
    category: str = Field(..., description="Issue category (legal, data, format)")
    description: str
    location: Optional[str] = Field(None, description="Where in packet/document")
    recommendation: str
    auto_fixable: bool = False


class AuditResult(BaseModel):
    """Full audit result."""

    is_approved: bool
    score: float = Field(..., ge=0, le=100, description="Quality score 0-100")
    issues: list[ComplianceIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class AuditorOutput(BaseModel):
    """Output from Auditor agent."""

    judgment_id: str
    packet_id: str
    audit: AuditResult
    audited_at: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# ORCHESTRATOR MODELS
# =============================================================================


class OrchestratorInput(BaseModel):
    """Input to Orchestrator."""

    judgment_id: str
    skip_draft: bool = Field(default=False, description="Stop after strategist")
    skip_audit: bool = Field(default=False, description="Skip auditor stage")
    dry_run: bool = Field(default=False, description="Don't persist to Supabase")


class PipelineStage(str, Enum):
    """Pipeline execution stages."""

    EXTRACTOR = "extractor"
    NORMALIZER = "normalizer"
    REASONER = "reasoner"
    STRATEGIST = "strategist"
    DRAFTER = "drafter"
    AUDITOR = "auditor"
    COMPLETE = "complete"
    FAILED = "failed"


class OrchestratorOutput(BaseModel):
    """Output from Orchestrator."""

    judgment_id: str
    run_id: str = Field(..., description="Unique run identifier")
    final_stage: PipelineStage
    success: bool

    # Stage outputs (populated as pipeline progresses)
    extractor_output: Optional[ExtractorOutput] = None
    normalizer_output: Optional[NormalizerOutput] = None
    reasoner_output: Optional[ReasonerOutput] = None
    strategist_output: Optional[StrategistOutput] = None
    drafter_output: Optional[DrafterOutput] = None
    auditor_output: Optional[AuditorOutput] = None

    # Execution metadata
    stages_completed: list[PipelineStage] = Field(default_factory=list)
    error_stage: Optional[PipelineStage] = None
    error_message: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Persistence
    persisted_plan_id: Optional[str] = None
    persisted_packet_id: Optional[str] = None
