"""
Dragonfly Engine - Core Data Models

Pydantic models for strict validation at every entry point:
- API request/response payloads
- Queue job payloads
- Database write operations
- ETL record schemas

All models enforce:
- Required field validation
- Type coercion with strict mode
- Business rule constraints
- Immutability where appropriate

Usage:
    from backend.core.models import JudgmentCreate, QueueJobPayload

    # Validate incoming API request
    judgment = JudgmentCreate.model_validate(request_data)

    # Validate queue payload
    job = QueueJobPayload.model_validate(message.body)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

# =============================================================================
# Enums
# =============================================================================


class TierLevel(str, Enum):
    """Collectability tier classification."""

    A = "A"
    B = "B"
    C = "C"


class JudgmentStatus(str, Enum):
    """Valid judgment lifecycle statuses."""

    INTAKE = "intake"
    PENDING_ENRICHMENT = "pending_enrichment"
    ENRICHMENT_IN_PROGRESS = "enrichment_in_progress"
    ENRICHMENT_COMPLETE = "enrichment_complete"
    ENRICHMENT_FAILED = "enrich_failed"
    SCORED = "scored"
    ALLOCATED = "allocated"
    SERVICE_PENDING = "service_pending"
    SERVICE_IN_PROGRESS = "service_in_progress"
    SERVED = "served"
    SERVICE_FAILED = "service_failed"
    COLLECTION_ACTIVE = "collection_active"
    COLLECTED = "collected"
    CLOSED = "closed"
    ARCHIVED = "archived"


class QueueJobKind(str, Enum):
    """Valid queue job types."""

    ENRICH = "enrich"
    SCORE = "score"
    ALLOCATE = "allocate"
    OUTREACH = "outreach"
    ENFORCE = "enforce"
    SERVICE_DISPATCH = "service_dispatch"
    NOTIFICATION = "notification"


class QueueJobStatus(str, Enum):
    """Queue job lifecycle status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


# =============================================================================
# Base Configuration
# =============================================================================


class StrictModel(BaseModel):
    """Base model with strict validation settings."""

    model_config = ConfigDict(
        strict=True,
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True,
        use_enum_values=True,
    )


class FlexibleModel(BaseModel):
    """Base model that allows extra fields (for external data)."""

    model_config = ConfigDict(
        validate_assignment=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


# =============================================================================
# Judgment Models
# =============================================================================


class JudgmentBase(StrictModel):
    """Base judgment fields shared across create/update/read."""

    case_number: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="Court case number (unique identifier)",
    )
    plaintiff_name: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Plaintiff/creditor name",
    )
    defendant_name: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Defendant/debtor name",
    )
    judgment_amount: Decimal = Field(
        ...,
        ge=0,
        le=100_000_000,
        description="Judgment principal amount in dollars",
    )
    entry_date: Optional[date] = Field(
        None,
        description="Date judgment was entered by court",
    )

    @field_validator("case_number")
    @classmethod
    def normalize_case_number(cls, v: str) -> str:
        """Normalize case number: uppercase, remove extra spaces."""
        return re.sub(r"\s+", " ", v.strip().upper())

    @field_validator("judgment_amount", mode="before")
    @classmethod
    def parse_amount(cls, v: Any) -> Decimal:
        """Parse string amounts with currency symbols."""
        if isinstance(v, (int, float, Decimal)):
            return Decimal(str(v))
        if isinstance(v, str):
            cleaned = v.replace("$", "").replace(",", "").strip()
            return Decimal(cleaned)
        raise ValueError(f"Cannot parse amount: {v}")


class JudgmentCreate(JudgmentBase):
    """Model for creating a new judgment."""

    source_file: Optional[str] = Field(
        None,
        max_length=500,
        description="Source file or import batch reference",
    )
    plaintiff_id: Optional[UUID] = Field(
        None,
        description="Link to plaintiffs table",
    )
    interest_rate: Optional[Decimal] = Field(
        None,
        ge=0,
        le=1,
        description="Annual interest rate as decimal (e.g., 0.09 for 9%)",
    )
    court_costs: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Court costs and fees",
    )
    attorney_fees: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Attorney fees awarded",
    )


class JudgmentUpdate(StrictModel):
    """Model for updating judgment fields (all optional)."""

    plaintiff_name: Optional[str] = Field(None, min_length=1, max_length=500)
    defendant_name: Optional[str] = Field(None, min_length=1, max_length=500)
    judgment_amount: Optional[Decimal] = Field(None, ge=0, le=100_000_000)
    status: Optional[JudgmentStatus] = None
    collectability_score: Optional[int] = Field(None, ge=0, le=100)
    collectability_tier: Optional[TierLevel] = None
    pool_id: Optional[UUID] = None

    @field_validator("judgment_amount", mode="before")
    @classmethod
    def parse_amount(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        if isinstance(v, (int, float, Decimal)):
            return Decimal(str(v))
        if isinstance(v, str):
            cleaned = v.replace("$", "").replace(",", "").strip()
            return Decimal(cleaned)
        raise ValueError(f"Cannot parse amount: {v}")


class JudgmentRead(JudgmentBase):
    """Model for reading judgment data from database."""

    id: int = Field(..., description="Database primary key")
    status: JudgmentStatus = Field(default=JudgmentStatus.INTAKE)
    collectability_score: Optional[int] = Field(None, ge=0, le=100)
    collectability_tier: Optional[TierLevel] = None
    pool_id: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# =============================================================================
# Queue Job Models
# =============================================================================


class QueueJobPayloadBase(StrictModel):
    """Base payload for queue jobs."""

    kind: QueueJobKind = Field(..., description="Job type for routing")
    idempotency_key: Optional[str] = Field(
        None,
        max_length=255,
        description="Unique key for deduplication",
    )


class EnrichJobPayload(QueueJobPayloadBase):
    """Payload for enrichment queue jobs."""

    kind: Literal[QueueJobKind.ENRICH] = QueueJobKind.ENRICH
    case_number: str = Field(..., min_length=3, max_length=100)
    judgment_id: Optional[int] = Field(None, ge=1)
    priority: int = Field(default=5, ge=1, le=10)
    force_refresh: bool = Field(default=False)


class ScoreJobPayload(QueueJobPayloadBase):
    """Payload for scoring queue jobs."""

    kind: Literal[QueueJobKind.SCORE] = QueueJobKind.SCORE
    judgment_id: int = Field(..., ge=1)
    enrichment_data: Dict[str, Any] = Field(default_factory=dict)


class AllocateJobPayload(QueueJobPayloadBase):
    """Payload for allocation queue jobs."""

    kind: Literal[QueueJobKind.ALLOCATE] = QueueJobKind.ALLOCATE
    judgment_id: int = Field(..., ge=1)
    score: int = Field(..., ge=0, le=100)
    force_reassign: bool = Field(default=False)


class OutreachJobPayload(QueueJobPayloadBase):
    """Payload for outreach/communication jobs."""

    kind: Literal[QueueJobKind.OUTREACH] = QueueJobKind.OUTREACH
    case_number: str = Field(..., min_length=3, max_length=100)
    template_code: str = Field(..., min_length=1, max_length=50)
    channel: Literal["email", "sms", "mail"] = "email"
    recipient_data: Dict[str, Any] = Field(default_factory=dict)


class ServiceDispatchJobPayload(QueueJobPayloadBase):
    """Payload for physical service dispatch jobs."""

    kind: Literal[QueueJobKind.SERVICE_DISPATCH] = QueueJobKind.SERVICE_DISPATCH
    judgment_id: int = Field(..., ge=1)
    case_number: str = Field(..., min_length=3, max_length=100)
    defendant_address: str = Field(..., min_length=10, max_length=500)
    service_type: Literal["personal", "substitute", "posting"] = "personal"
    max_attempts: int = Field(default=3, ge=1, le=10)


class EnforceJobPayload(QueueJobPayloadBase):
    """Payload for enforcement action jobs."""

    kind: Literal[QueueJobKind.ENFORCE] = QueueJobKind.ENFORCE
    judgment_id: int = Field(..., ge=1)
    action_type: str = Field(..., min_length=1, max_length=50)
    target_entity: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Union type for all job payloads
QueueJobPayload = (
    EnrichJobPayload
    | ScoreJobPayload
    | AllocateJobPayload
    | OutreachJobPayload
    | ServiceDispatchJobPayload
    | EnforceJobPayload
)


class QueueJob(StrictModel):
    """Complete queue job record from database."""

    msg_id: int = Field(..., ge=1)
    kind: QueueJobKind
    status: QueueJobStatus = QueueJobStatus.PENDING
    payload: Dict[str, Any]
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=5, ge=1, le=20)
    created_at: datetime
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    @computed_field
    @property
    def can_retry(self) -> bool:
        """Check if job is eligible for retry."""
        return self.attempts < self.max_attempts and self.status == QueueJobStatus.FAILED


# =============================================================================
# Enrichment Models
# =============================================================================


class EnrichmentData(FlexibleModel):
    """Validated enrichment data from TLOxp/idiCORE."""

    defendant_name: Optional[str] = None
    ssn_last4: Optional[str] = Field(None, pattern=r"^\d{4}$")
    dob: Optional[date] = None

    # Employment
    employed: bool = False
    self_employed: bool = False
    employer_name: Optional[str] = None
    employer_address: Optional[str] = None

    # Assets
    has_real_estate: bool = False
    has_vehicle: bool = False
    real_estate_value: Optional[Decimal] = Field(None, ge=0)
    vehicle_count: int = Field(default=0, ge=0)

    # Banking
    has_bank_account_recent: bool = False
    bank_name: Optional[str] = None

    # Gig economy
    gig_platform_detected: bool = False
    gig_platforms: List[str] = Field(default_factory=list)

    # Addresses
    current_address: Optional[str] = None
    address_verified: bool = False
    address_confidence: Optional[float] = Field(None, ge=0, le=1)

    # Metadata
    enrichment_source: Optional[str] = None
    enrichment_timestamp: Optional[datetime] = None
    raw_response_hash: Optional[str] = None


class ScoreBreakdownModel(StrictModel):
    """Validated score breakdown components."""

    employment: int = Field(..., ge=0, le=40)
    assets: int = Field(..., ge=0, le=30)
    recency: int = Field(..., ge=0, le=20)
    banking: int = Field(..., ge=0, le=10)

    @computed_field
    @property
    def total(self) -> int:
        """Compute total score, clamped to 0-100."""
        raw = self.employment + self.assets + self.recency + self.banking
        return max(0, min(100, raw))


# =============================================================================
# API Request/Response Models
# =============================================================================


class BatchIngestRequest(StrictModel):
    """Request payload for batch judgment ingestion."""

    batch_name: str = Field(..., min_length=1, max_length=100)
    source_reference: str = Field(..., min_length=1, max_length=255)
    judgments: List[JudgmentCreate] = Field(..., min_length=1, max_length=1000)
    skip_duplicates: bool = Field(default=True)
    enqueue_enrichment: bool = Field(default=True)

    @model_validator(mode="after")
    def validate_batch(self) -> "BatchIngestRequest":
        """Validate batch-level constraints."""
        case_numbers = [j.case_number for j in self.judgments]
        if len(case_numbers) != len(set(case_numbers)):
            raise ValueError("Duplicate case numbers in batch")
        return self


class BatchIngestResponse(StrictModel):
    """Response from batch ingestion."""

    batch_id: UUID
    batch_name: str
    total_records: int
    inserted: int
    skipped_duplicates: int
    failed: int
    failed_case_numbers: List[str] = Field(default_factory=list)
    enrichment_jobs_queued: int


class ComplianceCheckRequest(StrictModel):
    """Request for compliance validation."""

    judgment_id: int = Field(..., ge=1)
    action_type: Literal["service_dispatch", "garnishment", "lien"] = "service_dispatch"
    override_guards: bool = Field(default=False)


class ComplianceCheckResponse(StrictModel):
    """Response from compliance check."""

    judgment_id: int
    passed: bool
    rule_triggered: Optional[str] = None
    message: Optional[str] = None
    judgment_amount: Optional[Decimal] = None
    score: Optional[int] = None
    gig_detected: bool = False
    gig_bypass_applied: bool = False


# =============================================================================
# Worker Context Models
# =============================================================================


class WorkerContext(StrictModel):
    """Context passed through worker processing pipeline."""

    run_id: UUID = Field(..., description="Unique ID for this processing run")
    job_id: int = Field(..., ge=1, description="Queue job message ID")
    kind: QueueJobKind
    judgment_id: Optional[int] = None
    case_number: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now())
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def log_context(self) -> Dict[str, Any]:
        """Return context dict for structured logging."""
        return {
            "run_id": str(self.run_id),
            "job_id": self.job_id,
            "kind": self.kind,
            "judgment_id": self.judgment_id,
            "case_number": self.case_number,
        }
