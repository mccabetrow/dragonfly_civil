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
