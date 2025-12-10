"""
Dragonfly Engine - Legal Packet Service

Generates court-ready enforcement documents (DOCX) from judgment records.
Supports Income Executions and Information Subpoenas for NY.

Templates assumed at: backend/assets/templates/{packet_type}.docx
Uses Jinja2-style tags via docxtpl.
"""

import logging
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional

from docxtpl import DocxTemplate

from ..config import get_settings
from ..db import get_pool, get_supabase_client

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

PACKET_TYPES: dict[str, str] = {
    "income_execution_ny": "income_execution_ny.docx",
    "info_subpoena_ny": "info_subpoena_ny.docx",
}

TEMPLATES_DIR = Path(__file__).parent.parent / "assets" / "templates"


# =============================================================================
# Exceptions
# =============================================================================


class PacketError(Exception):
    """Raised when packet generation fails."""

    pass


# =============================================================================
# Helpers
# =============================================================================


def format_currency(value: Optional[Decimal | float]) -> str:
    """Format a numeric value as US currency string."""
    if value is None:
        return "$0.00"
    return f"${value:,.2f}"


def format_date(d: Optional[date]) -> str:
    """Format a date as MM/DD/YYYY string."""
    if d is None:
        return ""
    return d.strftime("%m/%d/%Y")


async def load_judgment_context(judgment_id: int) -> dict[str, Any]:
    """
    Load judgment data and build a context dict for template rendering.

    Fetches from public.judgments and joins enrichment data if available.

    Args:
        judgment_id: The judgment ID to load

    Returns:
        Context dict with all template fields

    Raises:
        PacketError: If judgment not found or query fails
    """
    pool = await get_pool()
    if pool is None:
        raise PacketError("Database connection not available")

    query = """
        SELECT
            j.id,
            j.case_number,
            j.plaintiff_name,
            j.defendant_name,
            j.judgment_amount,
            j.entry_date,
            j.defendant_address,
            j.defendant_phone,
            j.defendant_email,
            j.status,
            j.notes,
            -- Check for enrichment columns (may not exist on all deployments)
            COALESCE(j.employer_name, NULL) as employer_name,
            COALESCE(j.employer_address, NULL) as employer_address,
            COALESCE(j.bank_name, NULL) as bank_name,
            COALESCE(j.bank_address, NULL) as bank_address
        FROM public.judgments j
        WHERE j.id = %s
    """

    try:
        async with pool.cursor() as cur:
            await cur.execute(query, (judgment_id,))
            row = await cur.fetchone()
    except Exception as e:
        # Handle case where enrichment columns don't exist
        logger.warning(f"Query failed, trying basic query: {e}")
        basic_query = """
            SELECT
                id,
                case_number,
                plaintiff_name,
                defendant_name,
                judgment_amount,
                entry_date,
                defendant_address,
                defendant_phone,
                defendant_email,
                status,
                notes
            FROM public.judgments
            WHERE id = %s
        """
        async with pool.cursor() as cur:
            await cur.execute(basic_query, (judgment_id,))
            row = await cur.fetchone()

    if row is None:
        raise PacketError(f"Judgment {judgment_id} not found")

    # Build context dict
    # Note: Column order matches query above
    if len(row) >= 15:
        # Full query with enrichment
        (
            id_,
            case_number,
            plaintiff_name,
            defendant_name,
            judgment_amount,
            entry_date,
            defendant_address,
            defendant_phone,
            defendant_email,
            status,
            notes,
            employer_name,
            employer_address,
            bank_name,
            bank_address,
        ) = row
    else:
        # Basic query without enrichment
        (
            id_,
            case_number,
            plaintiff_name,
            defendant_name,
            judgment_amount,
            entry_date,
            defendant_address,
            defendant_phone,
            defendant_email,
            status,
            notes,
        ) = row
        employer_name = None
        employer_address = None
        bank_name = None
        bank_address = None

    judgment_amount_decimal = Decimal(str(judgment_amount)) if judgment_amount else Decimal("0")

    # Get interest rate from settings
    settings = get_settings()

    return {
        "judgment_id": id_,
        "case_number": case_number or "",
        "plaintiff_name": plaintiff_name or "",
        "defendant_name": defendant_name or "",
        "judgment_amount": judgment_amount_decimal,
        "judgment_amount_formatted": format_currency(judgment_amount_decimal),
        "judgment_date": entry_date,
        "judgment_date_formatted": format_date(entry_date),
        "judgment_date_iso": entry_date.isoformat() if entry_date else "",
        "defendant_address": defendant_address or "",
        "defendant_phone": defendant_phone or "",
        "defendant_email": defendant_email or "",
        "status": status or "",
        "notes": notes or "",
        # Enrichment data (may be None)
        "employer_name": employer_name or "",
        "employer_address": employer_address or "",
        "bank_name": bank_name or "",
        "bank_address": bank_address or "",
        # Interest rate from config
        # NOTE: Confirm NY post-judgment rate with counsel (CPLR 5004)
        "interest_rate_percent": settings.ny_interest_rate_percent,
    }


def calculate_interest(
    judgment_amount: Decimal,
    judgment_date: Optional[date],
    annual_rate: Decimal,
) -> dict[str, Any]:
    """
    Calculate simple interest on a judgment.

    Uses simple interest formula: I = P * r * t
    where t = years since judgment (days / 365)

    Args:
        judgment_amount: Principal amount
        judgment_date: Date of judgment entry
        annual_rate: Annual interest rate as decimal (e.g., 9.0 for 9%)

    Returns:
        Dict with interest_amount, total_with_interest, and formatted versions
    """
    if judgment_date is None or judgment_amount <= 0:
        return {
            "interest_amount": Decimal("0"),
            "interest_amount_formatted": "$0.00",
            "total_with_interest": judgment_amount,
            "total_with_interest_formatted": format_currency(judgment_amount),
            "days_since_judgment": 0,
            "years_since_judgment": 0.0,
        }

    today = date.today()
    days_elapsed = (today - judgment_date).days

    # Clamp negative days (judgment in future) to 0
    if days_elapsed < 0:
        days_elapsed = 0

    years_elapsed = Decimal(days_elapsed) / Decimal(365)
    rate_decimal = annual_rate / Decimal(100)

    interest_amount = judgment_amount * rate_decimal * years_elapsed
    interest_amount = interest_amount.quantize(Decimal("0.01"))  # Round to cents

    total_with_interest = judgment_amount + interest_amount

    return {
        "interest_amount": interest_amount,
        "interest_amount_formatted": format_currency(interest_amount),
        "total_with_interest": total_with_interest,
        "total_with_interest_formatted": format_currency(total_with_interest),
        "days_since_judgment": days_elapsed,
        "years_since_judgment": float(years_elapsed),
    }


def _emit_event_best_effort(
    judgment_id: int,
    packet_type: str,
    packet_url: str,
) -> None:
    """
    Emit an event for the generated packet (best-effort, non-fatal).

    This hooks into our event stream for tracking and automation.
    Uses asyncio.create_task to run async emission in the background.
    """
    import asyncio

    async def _emit():
        try:
            from .event_service import emit_event_for_judgment

            await emit_event_for_judgment(
                judgment_id=judgment_id,
                event_type="packet_sent",
                payload={
                    "judgment_id": judgment_id,
                    "packet_type": packet_type,
                    "packet_url": packet_url,
                },
            )
            logger.info(
                "Packet event emitted",
                extra={
                    "judgment_id": judgment_id,
                    "packet_type": packet_type,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to emit packet event (non-fatal): {e}")

    try:
        # Try to get the running event loop and schedule the task
        loop = asyncio.get_running_loop()
        loop.create_task(_emit())
    except RuntimeError:
        # No running event loop - log and skip
        logger.debug(
            "No event loop available for packet event emission",
            extra={"judgment_id": judgment_id, "packet_type": packet_type},
        )


# =============================================================================
# Core Function
# =============================================================================


async def generate_packet(
    judgment_id: int,
    packet_type: Literal["income_execution_ny", "info_subpoena_ny"],
) -> str:
    """
    Generate a legal packet document for a judgment.

    1. Validates packet_type
    2. Loads judgment context from database
    3. Calculates interest
    4. Renders DOCX template
    5. Uploads to Supabase Storage
    6. Returns signed/public URL

    Args:
        judgment_id: The judgment ID to generate packet for
        packet_type: Type of packet (income_execution_ny, info_subpoena_ny)

    Returns:
        URL to download the generated document

    Raises:
        PacketError: If generation fails for any reason
    """
    # Validate packet type
    if packet_type not in PACKET_TYPES:
        raise PacketError(
            f"Invalid packet type: {packet_type}. " f"Valid types: {list(PACKET_TYPES.keys())}"
        )

    template_filename = PACKET_TYPES[packet_type]
    template_path = TEMPLATES_DIR / template_filename

    if not template_path.exists():
        raise PacketError(
            f"Template not found: {template_path}. " "Please ensure the template file exists."
        )

    logger.info(
        f"Generating {packet_type} packet for judgment {judgment_id}",
        extra={"judgment_id": judgment_id, "packet_type": packet_type},
    )

    try:
        # Load judgment data
        context = await load_judgment_context(judgment_id)

        # Calculate interest
        interest_data = calculate_interest(
            judgment_amount=context["judgment_amount"],
            judgment_date=context["judgment_date"],
            annual_rate=Decimal(str(context["interest_rate_percent"])),
        )
        context.update(interest_data)

        # Add generation timestamp
        context["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        context["generated_date"] = date.today().strftime("%m/%d/%Y")

        # Render template
        doc = DocxTemplate(template_path)
        doc.render(context)

        # Write to temp file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"judgment_{judgment_id}_{timestamp}.docx"

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_file:
            doc.save(tmp_file.name)
            tmp_path = tmp_file.name

        # Upload to Supabase Storage
        settings = get_settings()
        bucket_name = settings.legal_packet_bucket
        storage_path = f"{packet_type}/{output_filename}"

        try:
            supabase = get_supabase_client()

            # Read the file bytes
            with open(tmp_path, "rb") as f:
                file_bytes = f.read()

            # Upload to storage
            supabase.storage.from_(bucket_name).upload(
                path=storage_path,
                file=file_bytes,
                file_options={
                    "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                },
            )

            # Generate signed URL (1 hour expiry)
            signed_url_response = supabase.storage.from_(bucket_name).create_signed_url(
                path=storage_path,
                expires_in=3600,  # 1 hour
            )

            if signed_url_response and "signedURL" in signed_url_response:
                packet_url = signed_url_response["signedURL"]
            else:
                # Fallback to public URL if signed URL fails
                packet_url = supabase.storage.from_(bucket_name).get_public_url(storage_path)

            logger.info(
                f"Packet uploaded successfully: {storage_path}",
                extra={
                    "judgment_id": judgment_id,
                    "packet_type": packet_type,
                    "storage_path": storage_path,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to upload packet to storage",
                extra={
                    "judgment_id": judgment_id,
                    "packet_type": packet_type,
                    "error": str(e),
                },
            )
            raise PacketError(f"Failed to upload document: {str(e)}")

        finally:
            # Clean up temp file
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

        # Emit event (best-effort)
        _emit_event_best_effort(judgment_id, packet_type, packet_url)

        return packet_url

    except PacketError:
        raise
    except Exception as e:
        logger.error(
            "Packet generation failed",
            extra={
                "judgment_id": judgment_id,
                "packet_type": packet_type,
                "error": str(e),
            },
        )
        raise PacketError(f"Packet generation failed: {str(e)}")
