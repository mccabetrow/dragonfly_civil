"""
Physical Service Module - Proof.com Integration

Dispatches process servers for physical service of legal documents.
Uses Proof.com's API to create serve jobs and track their status.

Configuration:
  PROOF_API_KEY       - API key for Proof.com authentication
  PROOF_API_URL       - API base URL (sandbox: https://api.sandbox.proof.com,
                        prod: https://api.proof.com)
  PROOF_WEBHOOK_SECRET- Secret for verifying webhook signatures
"""

import hashlib
import hmac
import logging
from typing import Any

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)


class ProofServiceError(Exception):
    """Raised when Proof.com API operations fail."""

    def __init__(
        self, message: str, status_code: int | None = None, response: dict | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ProofClient:
    """
    Client for Proof.com Process Service API.

    Handles authentication, job creation, and status tracking for
    physical service of legal documents.
    """

    # Default API endpoints
    SANDBOX_URL = "https://api.sandbox.proof.com"
    PROD_URL = "https://api.proof.com"

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        webhook_secret: str | None = None,
    ):
        """
        Initialize Proof.com client.

        Args:
            api_key: Proof.com API key (falls back to settings)
            api_url: Proof.com API URL (falls back to settings or sandbox)
            webhook_secret: Secret for webhook signature verification
        """
        settings = get_settings()

        self.api_key = api_key or getattr(settings, "proof_api_key", None)
        self.api_url = (
            api_url or getattr(settings, "proof_api_url", None) or self.SANDBOX_URL
        ).rstrip("/")
        self.webhook_secret = webhook_secret or getattr(
            settings, "proof_webhook_secret", None
        )

        if not self.api_key:
            logger.warning(
                "PROOF_API_KEY not configured - Proof.com integration disabled"
            )

    @property
    def is_configured(self) -> bool:
        """Check if the client is properly configured."""
        return bool(self.api_key)

    def _get_headers(self) -> dict[str, str]:
        """Build authentication headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_serve_job(
        self,
        case_details: dict[str, Any],
        document_url: str,
        *,
        priority: str = "standard",
        attempts: int = 3,
    ) -> dict[str, Any]:
        """
        Create a new serve job with Proof.com.

        Args:
            case_details: Dictionary containing case information:
                - case_number: str - Case/judgment number
                - defendant_name: str - Name of person to be served
                - defendant_address: str - Service address
                - defendant_city: str - City
                - defendant_state: str - State (2-letter code)
                - defendant_zip: str - ZIP code
                - court: str - Court name
                - judgment_amount: float - Amount of judgment
                - plaintiff_name: str - Plaintiff name
            document_url: URL to the document to be served (must be publicly accessible)
            priority: Service priority ("rush", "standard", "economy")
            attempts: Number of service attempts

        Returns:
            Dictionary containing:
                - job_id: str - Proof.com job identifier
                - status: str - Initial job status
                - estimated_cost: float - Estimated service cost
                - estimated_completion: str - ISO date estimate

        Raises:
            ProofServiceError: If API call fails or client not configured
        """
        if not self.is_configured:
            raise ProofServiceError("Proof.com client not configured - missing API key")

        # Map our case details to Proof.com's API payload format
        payload = {
            "service_type": "personal",  # personal, substituted, posting
            "priority": priority,
            "max_attempts": attempts,
            "case_reference": case_details.get("case_number", ""),
            "documents": [
                {
                    "url": document_url,
                    "name": f"Judgment - {case_details.get('case_number', 'Unknown')}",
                    "type": "judgment",
                }
            ],
            "recipient": {
                "name": case_details.get("defendant_name", ""),
                "address": {
                    "street": case_details.get("defendant_address", ""),
                    "city": case_details.get("defendant_city", ""),
                    "state": case_details.get("defendant_state", ""),
                    "zip": case_details.get("defendant_zip", ""),
                    "country": "US",
                },
            },
            "case_info": {
                "court_name": case_details.get("court", ""),
                "case_number": case_details.get("case_number", ""),
                "plaintiff_name": case_details.get("plaintiff_name", ""),
                "defendant_name": case_details.get("defendant_name", ""),
                "judgment_amount": case_details.get("judgment_amount", 0),
            },
            "webhook_url": case_details.get("webhook_url"),
            "metadata": {
                "dragonfly_judgment_id": str(case_details.get("judgment_id", "")),
                "source": "dragonfly_civil",
            },
        }

        logger.info(
            "Creating Proof.com serve job",
            extra={
                "case_number": case_details.get("case_number"),
                "defendant": case_details.get("defendant_name"),
                "priority": priority,
            },
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_url}/v1/jobs",
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code == 401:
                    raise ProofServiceError(
                        "Authentication failed - check PROOF_API_KEY",
                        status_code=401,
                    )

                if response.status_code == 422:
                    error_data = response.json()
                    raise ProofServiceError(
                        f"Validation error: {error_data.get('detail', 'Unknown')}",
                        status_code=422,
                        response=error_data,
                    )

                if response.status_code >= 400:
                    raise ProofServiceError(
                        f"API error: {response.status_code}",
                        status_code=response.status_code,
                        response=response.json() if response.content else None,
                    )

                data = response.json()

                logger.info(
                    "Proof.com serve job created",
                    extra={
                        "job_id": data.get("id"),
                        "status": data.get("status"),
                        "estimated_cost": data.get("estimated_cost"),
                    },
                )

                return {
                    "job_id": data.get("id"),
                    "status": data.get("status", "created"),
                    "estimated_cost": data.get("estimated_cost", 0.0),
                    "estimated_completion": data.get("estimated_completion"),
                    "raw_response": data,
                }

        except httpx.TimeoutException:
            raise ProofServiceError("Request timed out connecting to Proof.com")
        except httpx.RequestError as e:
            raise ProofServiceError(f"Network error: {e}")

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        """
        Get the current status of a serve job.

        Args:
            job_id: Proof.com job identifier

        Returns:
            Dictionary with job status details
        """
        if not self.is_configured:
            raise ProofServiceError("Proof.com client not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.api_url}/v1/jobs/{job_id}",
                headers=self._get_headers(),
            )

            if response.status_code == 404:
                raise ProofServiceError(f"Job not found: {job_id}", status_code=404)

            if response.status_code >= 400:
                raise ProofServiceError(
                    f"API error: {response.status_code}",
                    status_code=response.status_code,
                )

            return response.json()

    async def cancel_job(self, job_id: str, reason: str = "") -> dict[str, Any]:
        """
        Cancel a pending serve job.

        Args:
            job_id: Proof.com job identifier
            reason: Optional cancellation reason

        Returns:
            Updated job details
        """
        if not self.is_configured:
            raise ProofServiceError("Proof.com client not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.api_url}/v1/jobs/{job_id}/cancel",
                headers=self._get_headers(),
                json={"reason": reason},
            )

            if response.status_code >= 400:
                raise ProofServiceError(
                    f"Failed to cancel job: {response.status_code}",
                    status_code=response.status_code,
                )

            return response.json()

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        timestamp: str | None = None,
    ) -> bool:
        """
        Verify a webhook signature from Proof.com.

        Args:
            payload: Raw request body bytes
            signature: Signature from X-Proof-Signature header
            timestamp: Timestamp from X-Proof-Timestamp header (if used)

        Returns:
            True if signature is valid
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured - skipping verification")
            return True  # Allow in dev, but log warning

        # Build the signed payload (typically timestamp.payload)
        if timestamp:
            signed_payload = f"{timestamp}.".encode() + payload
        else:
            signed_payload = payload

        expected_signature = hmac.new(
            self.webhook_secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature, expected_signature)


# Singleton instance
_proof_client: ProofClient | None = None


def get_proof_client() -> ProofClient:
    """Get or create the singleton ProofClient instance."""
    global _proof_client
    if _proof_client is None:
        _proof_client = ProofClient()
    return _proof_client


# =============================================================================
# High-Level Dispatch Function with Compliance Guard
# =============================================================================


async def dispatch_service_of_process(
    judgment_id: int,
    document_url: str,
    case_details: dict[str, Any] | None = None,
    *,
    priority: str = "standard",
    skip_compliance: bool = False,
) -> dict[str, Any]:
    """
    Dispatch physical service for a judgment with compliance validation.

    This is the main entry point for initiating process service. It:
    1. Validates the judgment against spend guards (ROI, confidence)
    2. Creates a serve job via Proof.com if compliant
    3. Records the serve job in enforcement.serve_jobs
    4. Falls back to manual review task if compliance fails

    Args:
        judgment_id: The judgment ID to serve
        document_url: URL to the document to be served
        case_details: Optional dict with case info (will be fetched if not provided)
        priority: Service priority ("rush", "standard", "economy")
        skip_compliance: If True, bypass compliance checks (use with caution)

    Returns:
        Dictionary with:
            - success: bool
            - serve_job_id: UUID of the enforcement.serve_jobs record
            - proof_job_id: Proof.com job ID (if dispatched)
            - manual_review_task_id: Task ID (if compliance failed)
            - compliance_bypass: str reason if bypassed

    Raises:
        ProofServiceError: If Proof.com API call fails
    """
    from backend.db import get_pool

    result: dict[str, Any] = {
        "success": False,
        "judgment_id": judgment_id,
        "serve_job_id": None,
        "proof_job_id": None,
        "manual_review_task_id": None,
        "compliance_bypass": None,
    }

    # Step 1: Compliance validation
    if not skip_compliance:
        try:
            from .compliance_service import (
                ComplianceError,
                create_manual_review_task,
                validate_service_dispatch,
            )

            compliance_result = await validate_service_dispatch(judgment_id)
            logger.info(
                f"Compliance passed for judgment {judgment_id}: "
                f"gig_bypass={compliance_result.gig_bypass_applied}"
            )

            if compliance_result.gig_bypass_applied:
                result["compliance_bypass"] = "gig_detected"

        except ComplianceError as ce:
            logger.warning(
                f"Compliance failed for judgment {judgment_id}: {ce} (rule={ce.rule})"
            )

            # Create manual review task instead of dispatching
            try:
                task_id = await create_manual_review_task(judgment_id, ce)
                result["manual_review_task_id"] = task_id
                result["compliance_error"] = str(ce)
                result["compliance_rule"] = ce.rule
                logger.info(
                    f"Created manual review task {task_id} for judgment {judgment_id}"
                )
            except Exception as task_err:
                logger.error(
                    f"Failed to create manual review task for judgment {judgment_id}: {task_err}"
                )
                result["compliance_error"] = str(ce)

            return result

    else:
        result["compliance_bypass"] = "skip_compliance_flag"
        logger.warning(
            f"Compliance skipped for judgment {judgment_id} (skip_compliance=True)"
        )

    # Step 2: Fetch case details if not provided
    if case_details is None:
        conn = await get_pool()
        if conn is None:
            raise ProofServiceError("Database connection not available")

        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    j.case_number,
                    j.defendant_name,
                    j.defendant_address,
                    j.defendant_city,
                    j.defendant_state,
                    j.defendant_zip,
                    j.judgment_amount,
                    j.plaintiff_name,
                    j.court
                FROM public.judgments j
                WHERE j.id = %s
                """,
                (judgment_id,),
            )
            row = await cur.fetchone()

            if row is None:
                raise ProofServiceError(f"Judgment {judgment_id} not found")

            case_details = {
                "judgment_id": judgment_id,
                "case_number": row[0],
                "defendant_name": row[1],
                "defendant_address": row[2],
                "defendant_city": row[3],
                "defendant_state": row[4],
                "defendant_zip": row[5],
                "judgment_amount": float(row[6]) if row[6] else 0.0,
                "plaintiff_name": row[7],
                "court": row[8],
            }
    else:
        case_details["judgment_id"] = judgment_id

    # Step 3: Dispatch to Proof.com
    client = get_proof_client()

    if not client.is_configured:
        logger.warning("Proof.com not configured - creating placeholder serve job")
        # Create a placeholder record without actually calling Proof.com
        proof_result = {
            "job_id": None,
            "status": "pending_configuration",
            "estimated_cost": 0.0,
        }
    else:
        proof_result = await client.create_serve_job(
            case_details=case_details,
            document_url=document_url,
            priority=priority,
        )

    # Step 4: Record in enforcement.serve_jobs
    conn = await get_pool()
    if conn is not None:
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO enforcement.serve_jobs (
                        judgment_id,
                        provider_job_id,
                        provider,
                        status,
                        priority,
                        estimated_cost,
                        metadata,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        'proof.com',
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        NOW(),
                        NOW()
                    )
                    RETURNING id
                    """,
                    (
                        judgment_id,
                        proof_result.get("job_id") or "pending",
                        proof_result.get("status", "created"),
                        priority,
                        proof_result.get("estimated_cost", 0.0),
                        {
                            "document_url": document_url,
                            "compliance_bypass": result.get("compliance_bypass"),
                        },
                    ),
                )
                row = await cur.fetchone()
                if row:
                    result["serve_job_id"] = str(row[0])

        except Exception as db_err:
            logger.error(
                f"Failed to record serve job for judgment {judgment_id}: {db_err}"
            )

    result["success"] = True
    result["proof_job_id"] = proof_result.get("job_id")
    result["status"] = proof_result.get("status")
    result["estimated_cost"] = proof_result.get("estimated_cost")

    logger.info(
        f"Dispatched service for judgment {judgment_id}: "
        f"proof_job={result['proof_job_id']}, serve_job={result['serve_job_id']}"
    )

    return result
