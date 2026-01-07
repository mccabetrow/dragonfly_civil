"""
Dragonfly Engine - Job Envelope Schema

Defines the strict contract for all job payloads consumed by workers.
Every message on pgmq queues MUST conform to this envelope structure.

The envelope provides:
- Traceability: job_id + trace_id for distributed tracing
- Multi-tenancy: org_id for tenant isolation
- Idempotency: idempotency_key for exactly-once processing
- Entity context: entity_type + entity_id for domain linkage
- Retry tracking: attempt counter
- Payload: the actual job-specific data

Usage:
    from backend.workers.envelope import JobEnvelope, InvalidEnvelopeError

    # Parse incoming message
    try:
        envelope = JobEnvelope.model_validate(raw_message)
    except InvalidEnvelopeError as e:
        # Move to DLQ - do not retry
        ...

    # Access fields
    print(f"Processing {envelope.entity_type}:{envelope.entity_id}")
    print(f"Payload: {envelope.payload}")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator


class InvalidEnvelopeError(Exception):
    """Raised when a message does not conform to the JobEnvelope schema."""

    def __init__(self, message: str, raw_payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.raw_payload = raw_payload
        self.validation_errors: list[dict[str, Any]] = []

    @classmethod
    def from_validation_error(
        cls,
        error: ValidationError,
        raw_payload: dict[str, Any] | None = None,
    ) -> "InvalidEnvelopeError":
        """Create from a Pydantic ValidationError."""
        instance = cls(str(error), raw_payload)
        instance.validation_errors = error.errors()
        return instance


class JobEnvelope(BaseModel):
    """
    Strict envelope schema for all worker job messages.

    Every message on a pgmq queue MUST contain these fields.
    The `payload` field contains the job-specific data.
    """

    # -------------------------------------------------------------------------
    # Identity & Tracing
    # -------------------------------------------------------------------------

    job_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this job instance",
    )

    trace_id: UUID = Field(
        default_factory=uuid4,
        description="Distributed tracing ID (propagate across service boundaries)",
    )

    # -------------------------------------------------------------------------
    # Multi-tenancy
    # -------------------------------------------------------------------------

    org_id: UUID = Field(
        ...,  # Required
        description="Organization ID for tenant isolation",
    )

    # -------------------------------------------------------------------------
    # Idempotency
    # -------------------------------------------------------------------------

    idempotency_key: str = Field(
        ...,  # Required
        min_length=1,
        max_length=512,
        description="Unique key for exactly-once processing",
    )

    # -------------------------------------------------------------------------
    # Entity Context
    # -------------------------------------------------------------------------

    entity_type: str = Field(
        ...,  # Required
        min_length=1,
        max_length=64,
        description="Type of entity this job operates on (e.g., 'plaintiff', 'judgment')",
    )

    entity_id: str = Field(
        ...,  # Required
        min_length=1,
        max_length=256,
        description="ID of the entity (string to support various ID formats)",
    )

    # -------------------------------------------------------------------------
    # Retry & Timing
    # -------------------------------------------------------------------------

    attempt: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Current attempt number (starts at 1)",
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this job was created",
    )

    # -------------------------------------------------------------------------
    # Payload
    # -------------------------------------------------------------------------

    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Job-specific data (the actual work to perform)",
    )

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        """Normalize entity type to lowercase."""
        return v.lower().strip()

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, v: str) -> str:
        """Strip whitespace from idempotency key."""
        return v.strip()

    # -------------------------------------------------------------------------
    # Model Configuration
    # -------------------------------------------------------------------------

    model_config = {
        "strict": False,  # Allow coercion from JSON strings
        "extra": "forbid",  # No extra fields allowed
        "frozen": False,  # Allow mutation for attempt increment
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    "trace_id": "660e8400-e29b-41d4-a716-446655440001",
                    "org_id": "770e8400-e29b-41d4-a716-446655440002",
                    "idempotency_key": "plaintiff:intake:12345",
                    "entity_type": "plaintiff",
                    "entity_id": "12345",
                    "attempt": 1,
                    "created_at": "2026-01-06T12:00:00Z",
                    "payload": {
                        "action": "score_collectability",
                        "priority": "high",
                    },
                }
            ]
        },
    }

    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        org_id: UUID,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        trace_id: UUID | None = None,
    ) -> "JobEnvelope":
        """
        Create a new job envelope with sensible defaults.

        Args:
            org_id: Tenant organization ID.
            entity_type: Type of entity (e.g., 'plaintiff').
            entity_id: Entity identifier.
            payload: Job-specific data.
            idempotency_key: Custom idempotency key. Auto-generated if None.
            trace_id: Distributed tracing ID. Auto-generated if None.

        Returns:
            A new JobEnvelope instance.
        """
        if idempotency_key is None:
            idempotency_key = f"{entity_type}:{entity_id}:{uuid4().hex[:8]}"

        return cls(
            org_id=org_id,
            entity_type=entity_type,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
            trace_id=trace_id or uuid4(),
            payload=payload or {},
        )

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "JobEnvelope":
        """
        Parse and validate a raw dictionary into a JobEnvelope.

        Args:
            raw: Raw message dictionary from pgmq.

        Returns:
            Validated JobEnvelope instance.

        Raises:
            InvalidEnvelopeError: If validation fails.
        """
        try:
            return cls.model_validate(raw)
        except ValidationError as e:
            raise InvalidEnvelopeError.from_validation_error(e, raw) from e

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def increment_attempt(self) -> "JobEnvelope":
        """Create a new envelope with incremented attempt counter."""
        return self.model_copy(update={"attempt": self.attempt + 1})

    def with_trace(self, trace_id: UUID) -> "JobEnvelope":
        """Create a new envelope with a specific trace ID."""
        return self.model_copy(update={"trace_id": trace_id})

    def to_dlq_payload(self, reason: str) -> dict[str, Any]:
        """
        Create a payload suitable for the dead letter queue.

        Args:
            reason: Why this job is being sent to DLQ.

        Returns:
            Dict containing the original envelope plus DLQ metadata.
        """
        return {
            "original_envelope": self.model_dump(mode="json"),
            "dlq_reason": reason,
            "dlq_at": datetime.now(timezone.utc).isoformat(),
        }

    @property
    def log_context(self) -> dict[str, str]:
        """Get a dict suitable for structured logging."""
        return {
            "job_id": str(self.job_id),
            "trace_id": str(self.trace_id),
            "org_id": str(self.org_id),
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "attempt": str(self.attempt),
        }
