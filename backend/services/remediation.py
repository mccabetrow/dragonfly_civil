"""
Dragonfly Engine - Remediation Service

Handles compliance failures by creating actionable tasks for the Operations team.
When an enforcement action is blocked due to missing consent or other compliance
issues, this service creates tracking tasks for remediation.

Usage:
    from backend.services.remediation import RemediationService

    service = RemediationService(supabase_client)
    task = service.create_missing_consent_task(
        case_id="uuid-...",
        plaintiff_id="uuid-...",
        org_id="uuid-...",
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Task types for compliance failures
TASK_TYPE_COMPLIANCE_BLOCK = "compliance_block"
TASK_TYPE_MISSING_LOA = "missing_loa"
TASK_TYPE_MISSING_FEE_AGREEMENT = "missing_fee_agreement"

# Default priority for compliance tasks
DEFAULT_PRIORITY = "high"

# Default role assignment for compliance tasks
DEFAULT_ASSIGNED_ROLE = "operations"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RemediationTask:
    """Result of creating a remediation task."""

    id: UUID
    case_id: UUID
    plaintiff_id: UUID
    org_id: UUID
    title: str
    task_type: str
    priority: str
    status: str
    created_at: datetime


# =============================================================================
# Exceptions
# =============================================================================


class RemediationError(Exception):
    """Raised when remediation task creation fails."""

    def __init__(
        self,
        message: str,
        case_id: Optional[str] = None,
        plaintiff_id: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.case_id = case_id
        self.plaintiff_id = plaintiff_id
        self.details = details or {}


# =============================================================================
# Remediation Service
# =============================================================================


class RemediationService:
    """
    Service for creating and managing remediation tasks.

    When enforcement actions are blocked due to compliance failures,
    this service creates trackable tasks for the Operations team
    to resolve the underlying issues.
    """

    def __init__(self, supabase: "Client"):
        """
        Initialize the RemediationService.

        Args:
            supabase: Supabase client with service role credentials
        """
        self._supabase = supabase

    def create_missing_consent_task(
        self,
        case_id: str | UUID,
        plaintiff_id: str | UUID,
        org_id: str | UUID,
        *,
        blocking_action: Optional[str] = None,
        additional_context: Optional[dict[str, Any]] = None,
    ) -> RemediationTask:
        """
        Create a task for missing LOA/Fee Agreement consent.

        This is called when an enforcement action is blocked because
        the plaintiff lacks proper legal authorization (LOA + Fee Agreement).

        Args:
            case_id: The case ID associated with the blocked action
            plaintiff_id: The plaintiff lacking consent
            org_id: The organization ID (tenant)
            blocking_action: Optional description of the blocked action
            additional_context: Optional extra metadata for the task

        Returns:
            RemediationTask with the created task details

        Raises:
            RemediationError: If task creation fails
        """
        # Normalize UUIDs
        case_uuid = str(case_id)
        plaintiff_uuid = str(plaintiff_id)
        org_uuid = str(org_id)

        # Build task title
        title = "Missing LOA/Fee Agreement for Plaintiff"
        if blocking_action:
            title = f"Missing LOA/Fee Agreement - Blocked: {blocking_action}"

        # Build description
        description = (
            f"Enforcement action blocked due to missing legal consent.\n\n"
            f"**Plaintiff ID:** {plaintiff_uuid}\n"
            f"**Required Documents:**\n"
            f"- Letter of Authorization (LOA)\n"
            f"- Fee Agreement\n\n"
            f"Please obtain signed consent documents and upload to the plaintiff record."
        )

        # Build metadata
        metadata = {
            "task_type": TASK_TYPE_COMPLIANCE_BLOCK,
            "compliance_reason": "missing_consent",
            "plaintiff_id": plaintiff_uuid,
            "blocking_action": blocking_action,
            "created_by": "enforcement_guard",
            **(additional_context or {}),
        }

        # Create task in public.tasks
        try:
            task_id = str(uuid4())

            response = (
                self._supabase.table("tasks")
                .insert(
                    {
                        "id": task_id,
                        "org_id": org_uuid,
                        "case_id": case_uuid,
                        "title": title,
                        "description": description,
                        "status": "pending",
                        "priority": DEFAULT_PRIORITY,
                        "assigned_role": DEFAULT_ASSIGNED_ROLE,
                        "metadata": metadata,
                    }
                )
                .execute()
            )

            if not response.data:
                raise RemediationError(
                    "Failed to create remediation task - no data returned",
                    case_id=case_uuid,
                    plaintiff_id=plaintiff_uuid,
                )

            task_data = response.data[0]

            logger.info(
                "📋 Created remediation task: type=%s case_id=%s plaintiff_id=%s task_id=%s",
                TASK_TYPE_COMPLIANCE_BLOCK,
                case_uuid,
                plaintiff_uuid,
                task_id,
            )

            return RemediationTask(
                id=UUID(task_data["id"]),
                case_id=UUID(task_data["case_id"]),
                plaintiff_id=UUID(plaintiff_uuid),
                org_id=UUID(task_data["org_id"]),
                title=task_data["title"],
                task_type=TASK_TYPE_COMPLIANCE_BLOCK,
                priority=task_data["priority"],
                status=task_data["status"],
                created_at=datetime.fromisoformat(task_data["created_at"].replace("Z", "+00:00")),
            )

        except RemediationError:
            raise
        except Exception as e:
            logger.error(
                "❌ Failed to create remediation task: case_id=%s plaintiff_id=%s error=%s",
                case_uuid,
                plaintiff_uuid,
                str(e),
            )
            raise RemediationError(
                f"Failed to create remediation task: {e}",
                case_id=case_uuid,
                plaintiff_id=plaintiff_uuid,
                details={"error": str(e)},
            ) from e

    def create_document_request_task(
        self,
        case_id: str | UUID,
        plaintiff_id: str | UUID,
        org_id: str | UUID,
        document_type: str,
        *,
        additional_context: Optional[dict[str, Any]] = None,
    ) -> RemediationTask:
        """
        Create a task for requesting a specific document.

        Args:
            case_id: The case ID
            plaintiff_id: The plaintiff requiring the document
            org_id: The organization ID (tenant)
            document_type: Type of document needed (e.g., 'loa', 'fee_agreement')
            additional_context: Optional extra metadata

        Returns:
            RemediationTask with the created task details
        """
        case_uuid = str(case_id)
        plaintiff_uuid = str(plaintiff_id)
        org_uuid = str(org_id)

        # Map document type to task type
        task_type = TASK_TYPE_MISSING_LOA
        if document_type.lower() in ("fee_agreement", "fee agreement", "retainer"):
            task_type = TASK_TYPE_MISSING_FEE_AGREEMENT

        title = f"Request {document_type.replace('_', ' ').title()} - Plaintiff"

        metadata = {
            "task_type": task_type,
            "document_type": document_type,
            "plaintiff_id": plaintiff_uuid,
            "created_by": "enforcement_guard",
            **(additional_context or {}),
        }

        try:
            task_id = str(uuid4())

            response = (
                self._supabase.table("tasks")
                .insert(
                    {
                        "id": task_id,
                        "org_id": org_uuid,
                        "case_id": case_uuid,
                        "title": title,
                        "description": f"Document required: {document_type}",
                        "status": "pending",
                        "priority": DEFAULT_PRIORITY,
                        "assigned_role": DEFAULT_ASSIGNED_ROLE,
                        "metadata": metadata,
                    }
                )
                .execute()
            )

            if not response.data:
                raise RemediationError(
                    "Failed to create document request task",
                    case_id=case_uuid,
                    plaintiff_id=plaintiff_uuid,
                )

            task_data = response.data[0]

            logger.info(
                "📋 Created document request task: type=%s document=%s plaintiff_id=%s",
                task_type,
                document_type,
                plaintiff_uuid,
            )

            return RemediationTask(
                id=UUID(task_data["id"]),
                case_id=UUID(task_data["case_id"]),
                plaintiff_id=UUID(plaintiff_uuid),
                org_id=UUID(task_data["org_id"]),
                title=task_data["title"],
                task_type=task_type,
                priority=task_data["priority"],
                status=task_data["status"],
                created_at=datetime.fromisoformat(task_data["created_at"].replace("Z", "+00:00")),
            )

        except RemediationError:
            raise
        except Exception as e:
            logger.error(
                "❌ Failed to create document request task: %s",
                str(e),
            )
            raise RemediationError(
                f"Failed to create document request task: {e}",
                case_id=case_uuid,
                plaintiff_id=plaintiff_uuid,
            ) from e
