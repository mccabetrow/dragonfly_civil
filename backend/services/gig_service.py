"""
Gig Economy Garnishment Service

Detects gig platform activity in judgment/plaintiff data and generates
targeted subpoenas to registered agents for earnings garnishment.

Workflow:
1. detect_gig_activity() - Scans employer_name, enrichment data for keywords
2. generate_gig_subpoena() - Creates subpoena document via packet_service
3. dispatch_gig_subpoena() - Sends via physical_service (Proof.com)

Depends on:
- intelligence.gig_platforms table (keywords, registered agent addresses)
- intelligence.gig_detections table (detection log)
- packet_service for document generation
- physical_service for process server dispatch
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from backend.db import get_pool

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class GigPlatform:
    """Gig platform metadata from intelligence.gig_platforms."""

    id: int
    platform_name: str
    registered_agent_name: Optional[str]
    registered_agent_address: str
    registered_agent_city: Optional[str]
    registered_agent_state: Optional[str]
    registered_agent_zip: Optional[str]
    detection_keywords: list[str]
    subpoena_notes: Optional[str]

    @property
    def full_address(self) -> str:
        """Build full mailing address."""
        parts = [
            self.registered_agent_address,
            self.registered_agent_city,
            f"{self.registered_agent_state} {self.registered_agent_zip}".strip(),
        ]
        return ", ".join(p for p in parts if p)


@dataclass
class GigDetection:
    """Detection result when gig activity is found."""

    platform: GigPlatform
    matched_keyword: str
    detection_source: str  # 'employer_name', 'enrichment', 'bank_name', etc.
    confidence_score: float = 1.0


# =============================================================================
# Exceptions
# =============================================================================


class GigServiceError(Exception):
    """Raised when gig detection or subpoena generation fails."""

    pass


# =============================================================================
# Platform Loading
# =============================================================================


async def load_gig_platforms() -> list[GigPlatform]:
    """
    Load all active gig platforms from the database.

    Returns:
        List of GigPlatform objects with keywords and addresses

    Raises:
        GigServiceError: If database query fails
    """
    pool = await get_pool()
    if pool is None:
        raise GigServiceError("Database connection not available")

    query = """
        SELECT
            id,
            platform_name,
            registered_agent_name,
            registered_agent_address,
            registered_agent_city,
            registered_agent_state,
            registered_agent_zip,
            detection_keywords,
            subpoena_notes
        FROM intelligence.gig_platforms
        WHERE is_active = TRUE
        ORDER BY platform_name
    """

    try:
        async with pool.cursor() as cur:
            await cur.execute(query)
            rows = await cur.fetchall()
    except Exception as e:
        logger.error(f"Failed to load gig platforms: {e}")
        raise GigServiceError(f"Failed to load gig platforms: {e}") from e

    platforms = []
    for row in rows:
        platforms.append(
            GigPlatform(
                id=row[0],
                platform_name=row[1],
                registered_agent_name=row[2],
                registered_agent_address=row[3],
                registered_agent_city=row[4],
                registered_agent_state=row[5],
                registered_agent_zip=row[6],
                detection_keywords=row[7] or [],
                subpoena_notes=row[8],
            )
        )

    logger.debug(f"Loaded {len(platforms)} active gig platforms")
    return platforms


# =============================================================================
# Detection Logic
# =============================================================================


def match_text_against_platforms(
    text: str, platforms: list[GigPlatform], source: str
) -> list[GigDetection]:
    """
    Check text against all platform keywords.

    Args:
        text: Text to scan (employer name, bank name, notes, etc.)
        platforms: List of platforms to match against
        source: Detection source label (e.g., 'employer_name')

    Returns:
        List of GigDetection results
    """
    if not text:
        return []

    text_lower = text.lower()
    detections = []

    for platform in platforms:
        for keyword in platform.detection_keywords:
            # Case-insensitive word boundary match
            pattern = rf"\b{re.escape(keyword.lower())}\b"
            if re.search(pattern, text_lower):
                detections.append(
                    GigDetection(
                        platform=platform,
                        matched_keyword=keyword,
                        detection_source=source,
                        confidence_score=1.0,
                    )
                )
                break  # One match per platform is enough

    return detections


async def detect_gig_activity(judgment_id: int) -> list[GigDetection]:
    """
    Scan judgment record for gig platform activity.

    Checks:
    - employer_name column
    - employer_address column
    - notes column
    - bank_name column (some drivers use platform-linked banks)

    Args:
        judgment_id: The judgment to scan

    Returns:
        List of GigDetection results

    Raises:
        GigServiceError: If database query fails
    """
    pool = await get_pool()
    if pool is None:
        raise GigServiceError("Database connection not available")

    # Load platforms first
    platforms = await load_gig_platforms()
    if not platforms:
        logger.info("No active gig platforms configured")
        return []

    # Fetch judgment data
    query = """
        SELECT
            employer_name,
            employer_address,
            notes,
            bank_name
        FROM public.judgments
        WHERE id = %s
    """

    try:
        async with pool.cursor() as cur:
            await cur.execute(query, (judgment_id,))
            row = await cur.fetchone()
    except Exception as e:
        logger.error(f"Failed to load judgment {judgment_id}: {e}")
        raise GigServiceError(f"Failed to load judgment data: {e}") from e

    if row is None:
        raise GigServiceError(f"Judgment {judgment_id} not found")

    employer_name, employer_address, notes, bank_name = row

    # Scan each field
    all_detections: list[GigDetection] = []

    all_detections.extend(
        match_text_against_platforms(employer_name, platforms, "employer_name")
    )
    all_detections.extend(
        match_text_against_platforms(employer_address, platforms, "employer_address")
    )
    all_detections.extend(match_text_against_platforms(notes, platforms, "notes"))
    all_detections.extend(
        match_text_against_platforms(bank_name, platforms, "bank_name")
    )

    # Deduplicate by platform
    seen_platforms: set[int] = set()
    unique_detections: list[GigDetection] = []
    for detection in all_detections:
        if detection.platform.id not in seen_platforms:
            seen_platforms.add(detection.platform.id)
            unique_detections.append(detection)

    logger.info(
        f"Judgment {judgment_id}: detected {len(unique_detections)} gig platforms"
    )
    return unique_detections


async def detect_gig_activity_for_plaintiff(
    plaintiff_id: str,
) -> list[GigDetection]:
    """
    Scan plaintiff records for gig platform activity.

    Checks:
    - employer_name from plaintiffs table
    - notes from plaintiffs table

    Args:
        plaintiff_id: UUID of the plaintiff

    Returns:
        List of GigDetection results

    Raises:
        GigServiceError: If database query fails
    """
    pool = await get_pool()
    if pool is None:
        raise GigServiceError("Database connection not available")

    # Load platforms first
    platforms = await load_gig_platforms()
    if not platforms:
        logger.info("No active gig platforms configured")
        return []

    # Fetch plaintiff data
    query = """
        SELECT
            employer_name,
            notes
        FROM public.plaintiffs
        WHERE id = %s::uuid
    """

    try:
        async with pool.cursor() as cur:
            await cur.execute(query, (plaintiff_id,))
            row = await cur.fetchone()
    except Exception as e:
        logger.error(f"Failed to load plaintiff {plaintiff_id}: {e}")
        raise GigServiceError(f"Failed to load plaintiff data: {e}") from e

    if row is None:
        raise GigServiceError(f"Plaintiff {plaintiff_id} not found")

    employer_name, notes = row

    # Scan each field
    all_detections: list[GigDetection] = []

    all_detections.extend(
        match_text_against_platforms(employer_name, platforms, "employer_name")
    )
    all_detections.extend(match_text_against_platforms(notes, platforms, "notes"))

    # Deduplicate by platform
    seen_platforms: set[int] = set()
    unique_detections: list[GigDetection] = []
    for detection in all_detections:
        if detection.platform.id not in seen_platforms:
            seen_platforms.add(detection.platform.id)
            unique_detections.append(detection)

    logger.info(
        f"Plaintiff {plaintiff_id}: detected {len(unique_detections)} gig platforms"
    )
    return unique_detections


# =============================================================================
# Detection Logging
# =============================================================================


async def log_gig_detection(
    detection: GigDetection,
    judgment_id: Optional[int] = None,
    plaintiff_id: Optional[str] = None,
) -> int:
    """
    Log a gig detection to the database.

    Args:
        detection: The detection result
        judgment_id: Associated judgment (optional)
        plaintiff_id: Associated plaintiff UUID (optional)

    Returns:
        The created detection record ID

    Raises:
        GigServiceError: If insert fails
    """
    pool = await get_pool()
    if pool is None:
        raise GigServiceError("Database connection not available")

    query = """
        INSERT INTO intelligence.gig_detections (
            judgment_id,
            plaintiff_id,
            platform_id,
            detection_source,
            matched_keyword,
            confidence_score
        ) VALUES (%s, %s::uuid, %s, %s, %s, %s)
        RETURNING id
    """

    try:
        async with pool.cursor() as cur:
            await cur.execute(
                query,
                (
                    judgment_id,
                    plaintiff_id,
                    detection.platform.id,
                    detection.detection_source,
                    detection.matched_keyword,
                    detection.confidence_score,
                ),
            )
            result = await cur.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Failed to log gig detection: {e}")
        raise GigServiceError(f"Failed to log detection: {e}") from e


# =============================================================================
# Subpoena Generation
# =============================================================================


async def generate_gig_subpoena(
    judgment_id: int,
    platform_name: str,
) -> dict:
    """
    Generate a subpoena document for a gig platform.

    Uses packet_service to create a templated subpoena addressed to
    the platform's registered agent.

    Args:
        judgment_id: The judgment to generate subpoena for
        platform_name: Name of the gig platform (e.g., 'Uber')

    Returns:
        Dict with document_url and metadata

    Raises:
        GigServiceError: If generation fails
    """
    # Import here to avoid circular imports
    from backend.services.packet_service import (
        PacketError,
        generate_packet,
        load_judgment_context,
    )

    # Find the platform
    platforms = await load_gig_platforms()
    platform = next((p for p in platforms if p.platform_name == platform_name), None)

    if platform is None:
        raise GigServiceError(f"Platform '{platform_name}' not found")

    # Load judgment context
    try:
        context = await load_judgment_context(judgment_id)
    except PacketError as e:
        raise GigServiceError(f"Failed to load judgment: {e}") from e

    # Note: context loaded but not currently used - generate_packet uses its own context
    # Future: Extend packet_service to accept custom_context for gig-specific templates
    _ = context  # Suppress unused variable warning

    # Generate the subpoena document
    # Use info_subpoena_ny as the base template (gig-specific template can be added later)
    try:
        document_url = await generate_packet(
            judgment_id=judgment_id,
            packet_type="info_subpoena_ny",
        )
        result = {"document_url": document_url}
    except PacketError as e:
        raise GigServiceError(f"Failed to generate subpoena: {e}") from e

    logger.info(f"Generated gig subpoena for judgment {judgment_id} -> {platform_name}")

    return {
        "judgment_id": judgment_id,
        "platform_name": platform_name,
        "registered_agent_address": platform.full_address,
        "document_url": result.get("document_url"),
    }


async def dispatch_gig_subpoena(
    judgment_id: int,
    platform_name: str,
    document_url: str,
) -> dict:
    """
    Dispatch a gig subpoena via process server (Proof.com).

    Args:
        judgment_id: The judgment ID
        platform_name: Name of the gig platform
        document_url: URL of the subpoena document

    Returns:
        Dict with serve job details

    Raises:
        GigServiceError: If dispatch fails
    """
    from backend.services.physical_service import ProofClient, ProofServiceError

    # Find the platform
    platforms = await load_gig_platforms()
    platform = next((p for p in platforms if p.platform_name == platform_name), None)

    if platform is None:
        raise GigServiceError(f"Platform '{platform_name}' not found")

    # Build case details for Proof.com
    case_details = {
        "judgment_id": judgment_id,
        "recipient_name": platform.registered_agent_name or platform.platform_name,
        "recipient_address": {
            "street": platform.registered_agent_address,
            "city": platform.registered_agent_city or "",
            "state": platform.registered_agent_state or "",
            "zip": platform.registered_agent_zip or "",
        },
        "document_type": "Information Subpoena",
        "special_instructions": platform.subpoena_notes or "",
    }

    # Dispatch via Proof.com
    client = ProofClient()

    if not client.is_configured:
        raise GigServiceError("Proof.com integration not configured")

    try:
        result = await client.create_serve_job(
            case_details=case_details, document_url=document_url
        )
    except ProofServiceError as e:
        raise GigServiceError(f"Failed to dispatch subpoena: {e}") from e

    logger.info(
        f"Dispatched gig subpoena for judgment {judgment_id} "
        f"-> {platform_name} (job: {result.get('job_id')})"
    )

    return result


# =============================================================================
# Full Workflow
# =============================================================================


async def process_judgment_for_gig_garnishment(judgment_id: int) -> list[dict]:
    """
    Full workflow: Detect gig activity, generate subpoenas, dispatch.

    Args:
        judgment_id: The judgment to process

    Returns:
        List of results for each detected platform

    Raises:
        GigServiceError: If any step fails
    """
    # Step 1: Detect gig activity
    detections = await detect_gig_activity(judgment_id)

    if not detections:
        logger.info(f"Judgment {judgment_id}: No gig activity detected")
        return []

    results = []

    for detection in detections:
        try:
            # Log the detection
            detection_id = await log_gig_detection(
                detection=detection, judgment_id=judgment_id
            )

            # Generate subpoena
            subpoena_result = await generate_gig_subpoena(
                judgment_id=judgment_id, platform_name=detection.platform.platform_name
            )

            # Dispatch if we have a document URL
            dispatch_result = None
            if subpoena_result.get("document_url"):
                try:
                    dispatch_result = await dispatch_gig_subpoena(
                        judgment_id=judgment_id,
                        platform_name=detection.platform.platform_name,
                        document_url=subpoena_result["document_url"],
                    )
                except GigServiceError as e:
                    logger.warning(f"Dispatch failed (will retry later): {e}")

            results.append(
                {
                    "detection_id": detection_id,
                    "platform": detection.platform.platform_name,
                    "matched_keyword": detection.matched_keyword,
                    "detection_source": detection.detection_source,
                    "subpoena_generated": True,
                    "document_url": subpoena_result.get("document_url"),
                    "dispatch_result": dispatch_result,
                }
            )

        except GigServiceError as e:
            logger.error(f"Failed to process {detection.platform.platform_name}: {e}")
            results.append(
                {
                    "platform": detection.platform.platform_name,
                    "error": str(e),
                }
            )

    logger.info(f"Judgment {judgment_id}: processed {len(results)} gig platforms")
    return results
