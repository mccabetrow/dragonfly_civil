"""
Dragonfly Engine - Notification Service

Unified outbound communications: Email (SendGrid) and SMS (Twilio).
All credentials are loaded from environment variables.
"""

import logging
from typing import Any

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content, HtmlContent
from twilio.rest import Client as TwilioClient

from ..config import get_settings

logger = logging.getLogger(__name__)

# Cache clients
_sendgrid_client: SendGridAPIClient | None = None
_twilio_client: TwilioClient | None = None


def _get_sendgrid_client() -> SendGridAPIClient | None:
    """Get or create SendGrid client."""
    global _sendgrid_client
    settings = get_settings()

    if not settings.sendgrid_api_key:
        logger.warning("SENDGRID_API_KEY not configured - email disabled")
        return None

    if _sendgrid_client is None:
        _sendgrid_client = SendGridAPIClient(api_key=settings.sendgrid_api_key)

    return _sendgrid_client


def _get_twilio_client() -> TwilioClient | None:
    """Get or create Twilio client."""
    global _twilio_client
    settings = get_settings()

    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.warning("Twilio credentials not configured - SMS disabled")
        return None

    if _twilio_client is None:
        _twilio_client = TwilioClient(
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )

    return _twilio_client


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    from_email: str | None = None,
) -> dict[str, Any]:
    """
    Send an email via SendGrid.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        body: Plain text body (fallback)
        html_body: HTML body (optional, preferred)
        from_email: Sender address (defaults to SENDGRID_FROM_EMAIL)

    Returns:
        Result dict with 'success', 'status_code', and optionally 'error'
    """
    settings = get_settings()
    client = _get_sendgrid_client()

    if client is None:
        logger.warning(f"Email not sent (SendGrid disabled): {subject}")
        return {"success": False, "error": "SendGrid not configured"}

    sender = from_email or settings.sendgrid_from_email
    if not sender:
        logger.error("SENDGRID_FROM_EMAIL not configured")
        return {"success": False, "error": "From email not configured"}

    try:
        message = Mail(
            from_email=Email(sender),
            to_emails=To(to_email),
            subject=subject,
        )

        # Add content
        if html_body:
            message.add_content(Content("text/plain", body))
            message.add_content(HtmlContent(html_body))
        else:
            message.add_content(Content("text/plain", body))

        response = client.send(message)

        logger.info(
            f"Email sent: to={to_email}, subject='{subject}', "
            f"status={response.status_code}"
        )

        return {
            "success": response.status_code in (200, 201, 202),
            "status_code": response.status_code,
        }

    except Exception as e:
        logger.exception(f"Failed to send email to {to_email}: {e}")
        return {"success": False, "error": str(e)}


async def send_sms(
    to_number: str,
    message: str,
    from_number: str | None = None,
) -> dict[str, Any]:
    """
    Send an SMS via Twilio.

    Args:
        to_number: Recipient phone number (E.164 format, e.g., +15551234567)
        message: SMS message body (max 1600 chars, will be split if longer)
        from_number: Sender number (defaults to TWILIO_FROM_NUMBER)

    Returns:
        Result dict with 'success', 'sid', and optionally 'error'
    """
    settings = get_settings()
    client = _get_twilio_client()

    if client is None:
        logger.warning(f"SMS not sent (Twilio disabled): {message[:50]}...")
        return {"success": False, "error": "Twilio not configured"}

    sender = from_number or settings.twilio_from_number
    if not sender:
        logger.error("TWILIO_FROM_NUMBER not configured")
        return {"success": False, "error": "From number not configured"}

    try:
        # Twilio handles message splitting automatically
        sms = client.messages.create(
            body=message,
            from_=sender,
            to=to_number,
        )

        logger.info(f"SMS sent: to={to_number}, sid={sms.sid}, " f"status={sms.status}")

        return {
            "success": True,
            "sid": sms.sid,
            "status": sms.status,
        }

    except Exception as e:
        logger.exception(f"Failed to send SMS to {to_number}: {e}")
        return {"success": False, "error": str(e)}


async def send_ops_alert(
    subject: str,
    body: str,
    html_body: str | None = None,
    include_sms: bool = False,
) -> dict[str, Any]:
    """
    Send an alert to the Ops team.

    Uses OPS_EMAIL and optionally OPS_PHONE from settings.

    Args:
        subject: Alert subject
        body: Alert body (plain text)
        html_body: HTML body (optional)
        include_sms: Also send SMS alert

    Returns:
        Result dict with email and sms outcomes
    """
    settings = get_settings()
    results: dict[str, Any] = {}

    # Email
    if settings.ops_email:
        results["email"] = await send_email(
            to_email=settings.ops_email,
            subject=f"[Dragonfly Ops] {subject}",
            body=body,
            html_body=html_body,
        )
    else:
        results["email"] = {"success": False, "error": "OPS_EMAIL not configured"}

    # SMS (optional)
    if include_sms and settings.ops_phone:
        # Truncate for SMS
        sms_body = f"{subject}: {body[:140]}"
        results["sms"] = await send_sms(
            to_number=settings.ops_phone,
            message=sms_body,
        )

    return results


async def send_ceo_briefing(
    subject: str,
    html_body: str,
    plain_body: str,
) -> dict[str, Any]:
    """
    Send the daily CEO briefing email.

    Uses CEO_EMAIL from settings.

    Args:
        subject: Email subject
        html_body: HTML email body
        plain_body: Plain text fallback

    Returns:
        Result dict with 'success' and details
    """
    settings = get_settings()

    if not settings.ceo_email:
        logger.warning("CEO_EMAIL not configured - briefing not sent")
        return {"success": False, "error": "CEO_EMAIL not configured"}

    return await send_email(
        to_email=settings.ceo_email,
        subject=f"[Dragonfly] {subject}",
        body=plain_body,
        html_body=html_body,
    )
