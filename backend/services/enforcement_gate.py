"""
Dragonfly Engine - Enforcement Gate

Hard gate for enforcement actions. No worker or API can take action against
a debtor unless the plaintiff is explicitly authorized (LOA + Fee Agreement).

This is the minimal "Safety Valve" that must be called before any enforcement
logic. If authorization fails, it automatically creates a remediation task.

Usage:
    from backend.services.enforcement_gate import EnforcementGate

    gate = EnforcementGate()

    # In EnforcementWorker.process():
    if not gate.verify_authorization(plaintiff_id, org_id=org_id, case_id=case_id):
        # Authorization failed - remediation task created automatically
        return {"status": "blocked", "reason": "missing_consent"}

    # Proceed with enforcement logic...

Integration Note:
    EnforcementWorker MUST call verify_authorization() before executing any
    enforcement logic. This is a hard gate - unauthorized actions must not proceed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Task configuration for compliance remediation
TASK_TYPE_COMPLIANCE_REMEDIATION = "compliance_remediation"
TASK_TITLE_MISSING_CONSENT = "Missing LOA/Fee Agreement"
TASK_PRIORITY = "high"
TASK_ASSIGNED_ROLE = "operations"


# =============================================================================
# Enforcement Gate
# =============================================================================


class EnforcementGate:
    """
    Hard authorization gate for enforcement actions.

    This gate checks the `legal.is_authorized(plaintiff_id)` function
    and creates a remediation task if authorization fails.

    The gate is stateless and can be instantiated per-request or
    as a singleton in the worker.
    """

    def __init__(self, db_url: Optional[str] = None):
        """
        Initialize the enforcement gate.

        Args:
            db_url: Optional database URL. If not provided, uses
                    get_supabase_db_url() to resolve from environment.
        """
        self._db_url = db_url

    def _get_db_url(self) -> str:
        """Get database connection URL."""
        return self._db_url or get_supabase_db_url()

    # -------------------------------------------------------------------------
    # Main Gate Method
    # -------------------------------------------------------------------------

    def verify_authorization(
        self,
        plaintiff_id: str | UUID,
        *,
        org_id: Optional[str | UUID] = None,
        case_id: Optional[str | UUID] = None,
        context: Optional[dict] = None,
    ) -> bool:
        """
        Verify plaintiff is authorized for enforcement actions.

        Calls `legal.is_authorized(plaintiff_id)` SQL function.
        If False:
          - Logs warning
          - Inserts remediation task into public.tasks
          - Returns False

        If True:
          - Returns True

        Args:
            plaintiff_id: The plaintiff UUID to check
            org_id: Organization ID (required if creating remediation task)
            case_id: Case ID (optional, for task context)
            context: Additional context to include in task notes

        Returns:
            True if authorized, False otherwise

        Note:
            EnforcementWorker MUST call this before executing enforcement logic.
        """
        plaintiff_uuid = str(plaintiff_id)

        # Check authorization via legal.is_authorized
        is_authorized = self._check_authorization(plaintiff_uuid)

        if is_authorized:
            logger.debug(
                "✅ Enforcement gate: AUTHORIZED plaintiff_id=%s",
                plaintiff_uuid,
            )
            return True

        # Authorization failed - log warning
        logger.warning(
            "⛔ Enforcement gate: BLOCKED - Missing consent for plaintiff_id=%s",
            plaintiff_uuid,
        )

        # Create remediation task if org_id provided
        if org_id:
            self._create_remediation_task(
                plaintiff_id=plaintiff_uuid,
                org_id=str(org_id),
                case_id=str(case_id) if case_id else None,
                context=context,
            )

        return False

    # -------------------------------------------------------------------------
    # Authorization Check
    # -------------------------------------------------------------------------

    def _check_authorization(self, plaintiff_id: str) -> bool:
        """
        Call legal.is_authorized(plaintiff_id) SQL function.

        The function checks:
        - Valid Letter of Authorization (LOA) on file
        - Valid Fee Agreement on file

        Returns:
            True if both LOA and Fee Agreement are valid, False otherwise
        """
        try:
            with psycopg.connect(
                self._get_db_url(),
                row_factory=dict_row,
                connect_timeout=10,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT legal.is_authorized(%s::uuid) AS authorized",
                        (plaintiff_id,),
                    )
                    row = cur.fetchone()
                    return bool(row and row["authorized"])

        except Exception as e:
            logger.error(
                "❌ Authorization check failed: plaintiff_id=%s error=%s",
                plaintiff_id,
                str(e),
            )
            # Fail closed - if we can't verify, assume unauthorized
            return False

    # -------------------------------------------------------------------------
    # Remediation Task Creation
    # -------------------------------------------------------------------------

    def _create_remediation_task(
        self,
        plaintiff_id: str,
        org_id: str,
        case_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> Optional[UUID]:
        """
        Create a remediation task in public.tasks.

        Args:
            plaintiff_id: Plaintiff who needs consent documents
            org_id: Organization ID for tenant isolation
            case_id: Optional case ID for linkage
            context: Optional additional context

        Returns:
            Task UUID if created, None if failed
        """
        try:
            task_id = uuid4()
            notes = (
                f"Enforcement blocked for plaintiff {plaintiff_id}. "
                "Missing Letter of Authorization (LOA) and/or Fee Agreement. "
                "Obtain signed consent documents before proceeding."
            )
            if context:
                notes += f"\n\nContext: {context}"

            with psycopg.connect(
                self._get_db_url(),
                row_factory=dict_row,
                connect_timeout=10,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.tasks (
                            id,
                            org_id,
                            case_id,
                            plaintiff_id,
                            type,
                            title,
                            notes,
                            status,
                            priority,
                            assigned_role,
                            created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING id
                        """,
                        (
                            str(task_id),
                            org_id,
                            case_id,
                            plaintiff_id,
                            TASK_TYPE_COMPLIANCE_REMEDIATION,
                            TASK_TITLE_MISSING_CONSENT,
                            notes,
                            "pending",
                            TASK_PRIORITY,
                            TASK_ASSIGNED_ROLE,
                            datetime.now(timezone.utc),
                        ),
                    )
                conn.commit()

            logger.info(
                "📋 Created remediation task: task_id=%s plaintiff_id=%s type=%s",
                task_id,
                plaintiff_id,
                TASK_TYPE_COMPLIANCE_REMEDIATION,
            )
            return task_id

        except Exception as e:
            logger.error(
                "❌ Failed to create remediation task: plaintiff_id=%s error=%s",
                plaintiff_id,
                str(e),
            )
            return None


# =============================================================================
# Convenience Function
# =============================================================================


def verify_enforcement_authorized(
    plaintiff_id: str | UUID,
    *,
    org_id: Optional[str | UUID] = None,
    case_id: Optional[str | UUID] = None,
) -> bool:
    """
    Convenience function for one-shot authorization check.

    Usage:
        from backend.services.enforcement_gate import verify_enforcement_authorized

        if not verify_enforcement_authorized(plaintiff_id, org_id=org_id):
            return  # Blocked

    Args:
        plaintiff_id: Plaintiff to check
        org_id: Org ID for remediation task creation
        case_id: Optional case ID for task linkage

    Returns:
        True if authorized, False if blocked
    """
    gate = EnforcementGate()
    return gate.verify_authorization(
        plaintiff_id,
        org_id=org_id,
        case_id=case_id,
    )
