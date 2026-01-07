"""
Dragonfly Engine - Enforcement Service

Service-plane guard for enforcement actions. Ensures all enforcement
operations are only executed for authorized plaintiffs (valid LOA + Fee Agreement).

The Guard Pattern:
1. Before any enforcement action, check `legal.is_authorized(plaintiff_id)`
2. If unauthorized → block action, create remediation task, return blocked status
3. If authorized → proceed with enforcement, return success

Usage:
    from backend.services.enforcement import EnforcementService
    from backend.services.remediation import RemediationService
    from src.supabase_client import create_supabase_client

    supabase = create_supabase_client()
    remediation = RemediationService(supabase)
    enforcement = EnforcementService(supabase, remediation)

    result = enforcement.execute_enforcement_step(
        case_id="uuid-...",
        plaintiff_id="uuid-...",
        org_id="uuid-...",
        action_type="file_suit",
    )

    if result["status"] == "blocked":
        print(f"Action blocked: {result['reason']}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url

from .remediation import RemediationService, RemediationTask

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)


# =============================================================================
# Constants & Types
# =============================================================================


class EnforcementStatus(str, Enum):
    """Status codes for enforcement action results."""

    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"
    PENDING = "pending"


class BlockReason(str, Enum):
    """Reasons an enforcement action may be blocked."""

    MISSING_CONSENT = "missing_consent"
    MISSING_LOA = "missing_loa"
    MISSING_FEE_AGREEMENT = "missing_fee_agreement"
    UNAUTHORIZED = "unauthorized"
    COMPLIANCE_HOLD = "compliance_hold"


# Enforcement action types
ACTION_TYPES = {
    "file_suit",
    "generate_document",
    "send_demand_letter",
    "schedule_hearing",
    "file_motion",
    "serve_papers",
    "garnishment",
    "levy",
    "lien",
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class EnforcementResult:
    """Result of an enforcement action attempt."""

    status: EnforcementStatus
    action_type: str
    case_id: str
    plaintiff_id: str
    reason: Optional[BlockReason] = None
    remediation_task: Optional[RemediationTask] = None
    data: Optional[dict[str, Any]] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "status": self.status.value,
            "action_type": self.action_type,
            "case_id": self.case_id,
            "plaintiff_id": self.plaintiff_id,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.reason:
            result["reason"] = self.reason.value
        if self.remediation_task:
            result["remediation_task_id"] = str(self.remediation_task.id)
        if self.data:
            result["data"] = self.data
        return result


# =============================================================================
# Exceptions
# =============================================================================


class EnforcementError(Exception):
    """Base exception for enforcement failures."""

    def __init__(
        self,
        message: str,
        status: EnforcementStatus = EnforcementStatus.FAILED,
        reason: Optional[BlockReason] = None,
    ):
        super().__init__(message)
        self.status = status
        self.reason = reason


class UnauthorizedPlaintiffError(EnforcementError):
    """Raised when plaintiff lacks authorization for enforcement."""

    def __init__(self, plaintiff_id: str, missing: Optional[list[str]] = None):
        self.plaintiff_id = plaintiff_id
        self.missing = missing or ["loa", "fee_agreement"]
        super().__init__(
            f"Plaintiff {plaintiff_id} not authorized (missing: {', '.join(self.missing)})",
            status=EnforcementStatus.BLOCKED,
            reason=BlockReason.MISSING_CONSENT,
        )


# =============================================================================
# Enforcement Service
# =============================================================================


class EnforcementService:
    """
    Service-plane guard for enforcement actions.

    Ensures all enforcement operations are gated by authorization checks.
    If a plaintiff is not authorized (missing LOA or Fee Agreement),
    the action is blocked and a remediation task is created.
    """

    def __init__(
        self,
        supabase: "Client",
        remediation_service: RemediationService,
    ):
        """
        Initialize the EnforcementService.

        Args:
            supabase: Supabase client with service role credentials
            remediation_service: Service for creating remediation tasks
        """
        self._supabase = supabase
        self._remediation = remediation_service

    # -------------------------------------------------------------------------
    # Authorization Check
    # -------------------------------------------------------------------------

    def check_authorization(self, plaintiff_id: str | UUID) -> bool:
        """
        Check if a plaintiff is authorized for enforcement actions.

        Calls the `legal.is_authorized` SQL function which verifies:
        - Valid Letter of Authorization (LOA) on file
        - Valid Fee Agreement on file

        Args:
            plaintiff_id: The plaintiff UUID to check

        Returns:
            True if authorized, False otherwise
        """
        plaintiff_uuid = str(plaintiff_id)

        try:
            # Use direct SQL for reliable cross-schema function call
            db_url = get_supabase_db_url()
            with psycopg.connect(db_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT legal.is_authorized(%s::uuid) AS authorized",
                        (plaintiff_uuid,),
                    )
                    row = cur.fetchone()
                    is_authorized = row["authorized"] if row else False

            if is_authorized:
                logger.debug(
                    "✅ Authorization check passed: plaintiff_id=%s",
                    plaintiff_uuid,
                )
            else:
                logger.warning(
                    "⛔ Authorization check failed: plaintiff_id=%s",
                    plaintiff_uuid,
                )

            return bool(is_authorized)

        except Exception as e:
            logger.error(
                "❌ Authorization check error: plaintiff_id=%s error=%s",
                plaintiff_uuid,
                str(e),
            )
            # Fail closed - if we can't verify, assume unauthorized
            return False

    # -------------------------------------------------------------------------
    # Main Guard Method
    # -------------------------------------------------------------------------

    def execute_enforcement_step(
        self,
        case_id: str | UUID,
        plaintiff_id: str | UUID,
        org_id: str | UUID,
        action_type: str,
        *,
        action_params: Optional[dict[str, Any]] = None,
    ) -> EnforcementResult:
        """
        Execute an enforcement step with authorization guard.

        This is the main entry point for all enforcement actions.
        It performs authorization checks before allowing any action.

        Steps:
        1. Check authorization via legal.is_authorized RPC
        2. If unauthorized: block, create remediation task, return blocked status
        3. If authorized: execute the action, return success

        Args:
            case_id: The case ID for this action
            plaintiff_id: The plaintiff ID to check authorization for
            org_id: The organization ID (tenant)
            action_type: Type of enforcement action (e.g., "file_suit")
            action_params: Optional parameters for the action

        Returns:
            EnforcementResult with status, reason, and optional data
        """
        case_uuid = str(case_id)
        plaintiff_uuid = str(plaintiff_id)
        org_uuid = str(org_id)

        logger.info(
            "🔒 Enforcement guard: action=%s case_id=%s plaintiff_id=%s",
            action_type,
            case_uuid,
            plaintiff_uuid,
        )

        # =================================================================
        # Step 1: Check Authorization
        # =================================================================
        is_authorized = self.check_authorization(plaintiff_uuid)

        # =================================================================
        # Step 2: Handle Unauthorized
        # =================================================================
        if not is_authorized:
            logger.warning(
                "⛔ Enforcement Blocked: Unauthorized Plaintiff - "
                "action=%s case_id=%s plaintiff_id=%s",
                action_type,
                case_uuid,
                plaintiff_uuid,
            )

            # Create remediation task for Operations team
            remediation_task = self._remediation.create_missing_consent_task(
                case_id=case_uuid,
                plaintiff_id=plaintiff_uuid,
                org_id=org_uuid,
                blocking_action=action_type,
                additional_context={
                    "action_params": action_params,
                },
            )

            return EnforcementResult(
                status=EnforcementStatus.BLOCKED,
                action_type=action_type,
                case_id=case_uuid,
                plaintiff_id=plaintiff_uuid,
                reason=BlockReason.MISSING_CONSENT,
                remediation_task=remediation_task,
                data={
                    "message": "Enforcement blocked due to missing consent",
                    "required": ["loa", "fee_agreement"],
                },
            )

        # =================================================================
        # Step 3: Execute Action (Authorized)
        # =================================================================
        logger.info(
            "✅ Enforcement authorized: action=%s case_id=%s plaintiff_id=%s",
            action_type,
            case_uuid,
            plaintiff_uuid,
        )

        # Dispatch to appropriate action handler
        try:
            result_data = self._execute_action(
                action_type=action_type,
                case_id=case_uuid,
                plaintiff_id=plaintiff_uuid,
                org_id=org_uuid,
                params=action_params or {},
            )

            return EnforcementResult(
                status=EnforcementStatus.SUCCESS,
                action_type=action_type,
                case_id=case_uuid,
                plaintiff_id=plaintiff_uuid,
                data=result_data,
            )

        except Exception as e:
            logger.error(
                "❌ Enforcement action failed: action=%s error=%s",
                action_type,
                str(e),
            )
            return EnforcementResult(
                status=EnforcementStatus.FAILED,
                action_type=action_type,
                case_id=case_uuid,
                plaintiff_id=plaintiff_uuid,
                data={"error": str(e)},
            )

    # -------------------------------------------------------------------------
    # Action Dispatcher
    # -------------------------------------------------------------------------

    def _execute_action(
        self,
        action_type: str,
        case_id: str,
        plaintiff_id: str,
        org_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute the actual enforcement action.

        This is called only after authorization is verified.

        Args:
            action_type: The type of action to execute
            case_id: Case identifier
            plaintiff_id: Plaintiff identifier
            org_id: Organization identifier
            params: Action-specific parameters

        Returns:
            Dict with action results
        """
        # Map action types to handlers
        handlers = {
            "file_suit": self._action_file_suit,
            "generate_document": self._action_generate_document,
            "send_demand_letter": self._action_send_demand_letter,
            "serve_papers": self._action_serve_papers,
        }

        handler = handlers.get(action_type)
        if handler:
            return handler(case_id, plaintiff_id, org_id, params)

        # Default: log and return success for unknown actions
        logger.info(
            "Enforcement action executed: action=%s case_id=%s",
            action_type,
            case_id,
        )
        return {
            "action": action_type,
            "executed": True,
        }

    # -------------------------------------------------------------------------
    # Action Handlers (Stubs for now)
    # -------------------------------------------------------------------------

    def _action_file_suit(
        self,
        case_id: str,
        plaintiff_id: str,
        org_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle file_suit enforcement action."""
        logger.info("📄 Filing suit: case_id=%s", case_id)
        # TODO: Integrate with court filing system
        return {
            "action": "file_suit",
            "executed": True,
            "case_id": case_id,
        }

    def _action_generate_document(
        self,
        case_id: str,
        plaintiff_id: str,
        org_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle document generation action."""
        document_type = params.get("document_type", "generic")
        logger.info(
            "📝 Generating document: type=%s case_id=%s",
            document_type,
            case_id,
        )
        # TODO: Integrate with document generation service
        return {
            "action": "generate_document",
            "executed": True,
            "document_type": document_type,
        }

    def _action_send_demand_letter(
        self,
        case_id: str,
        plaintiff_id: str,
        org_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle demand letter action."""
        logger.info("📬 Sending demand letter: case_id=%s", case_id)
        # TODO: Integrate with mailing service
        return {
            "action": "send_demand_letter",
            "executed": True,
            "case_id": case_id,
        }

    def _action_serve_papers(
        self,
        case_id: str,
        plaintiff_id: str,
        org_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle paper service action."""
        logger.info("📋 Serving papers: case_id=%s", case_id)
        # TODO: Integrate with process server (e.g., Proof.com)
        return {
            "action": "serve_papers",
            "executed": True,
            "case_id": case_id,
        }


# =============================================================================
# Decorator for Guard Pattern
# =============================================================================

F = TypeVar("F", bound=Callable[..., Any])


def require_authorization(
    enforcement_service: EnforcementService,
    case_id_arg: str = "case_id",
    plaintiff_id_arg: str = "plaintiff_id",
) -> Callable[[F], F]:
    """
    Decorator to enforce authorization on any function.

    Usage:
        @require_authorization(enforcement_service)
        def my_enforcement_action(case_id, plaintiff_id, ...):
            # This only runs if plaintiff is authorized
            ...

    Args:
        enforcement_service: EnforcementService instance
        case_id_arg: Name of the case_id argument in the decorated function
        plaintiff_id_arg: Name of the plaintiff_id argument

    Returns:
        Decorated function that checks authorization first
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract IDs from kwargs or positional args
            plaintiff_id = kwargs.get(plaintiff_id_arg)

            if not plaintiff_id:
                raise ValueError(f"Missing required argument: {plaintiff_id_arg}")

            # Check authorization
            if not enforcement_service.check_authorization(plaintiff_id):
                raise UnauthorizedPlaintiffError(str(plaintiff_id))

            # Proceed with the function
            return func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator
