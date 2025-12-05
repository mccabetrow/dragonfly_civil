"""
Dragonfly Engine - Reporting Service

Aggregates data from enforcement, ops, and intelligence views
to generate executive briefings and operational reports.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ..db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class CEOBriefingData:
    """Aggregated data for the CEO morning briefing."""

    # Portfolio Overview
    buy_candidates_count: int = 0
    total_portfolio_value: float = 0.0

    # Offer Performance
    offers_pending: int = 0
    offers_accepted_30d: int = 0
    acceptance_rate_30d: float = 0.0

    # System Health
    enrichment_healthy: bool = True
    jobs_pending: int = 0
    jobs_failed_24h: int = 0

    # Generated at
    generated_at: datetime | None = None


async def _query_buy_candidates() -> dict[str, Any]:
    """Query enforcement.v_radar for BUY_CANDIDATE count and value."""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT 
                    COUNT(*) AS count,
                    COALESCE(SUM(judgment_amount), 0) AS total_value
                FROM enforcement.v_radar
                WHERE recommendation = 'BUY_CANDIDATE'
                """
            )
            if row:
                return {"count": row["count"], "total_value": float(row["total_value"])}
    except Exception as e:
        logger.warning(f"Failed to query v_radar: {e}")

    return {"count": 0, "total_value": 0.0}


async def _query_offer_stats() -> dict[str, Any]:
    """Query enforcement.v_offer_stats for acceptance rates."""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT 
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (
                        WHERE status = 'accepted' 
                        AND updated_at >= CURRENT_DATE - INTERVAL '30 days'
                    ) AS accepted_30d,
                    COUNT(*) FILTER (
                        WHERE status IN ('accepted', 'rejected', 'expired')
                        AND updated_at >= CURRENT_DATE - INTERVAL '30 days'
                    ) AS resolved_30d
                FROM enforcement.v_offer_stats
                """
            )
            if row:
                pending = row["pending"] or 0
                accepted = row["accepted_30d"] or 0
                resolved = row["resolved_30d"] or 0
                rate = (accepted / resolved * 100) if resolved > 0 else 0.0
                return {
                    "pending": pending,
                    "accepted_30d": accepted,
                    "acceptance_rate_30d": rate,
                }
    except Exception as e:
        logger.warning(f"Failed to query v_offer_stats: {e}")

    return {"pending": 0, "accepted_30d": 0, "acceptance_rate_30d": 0.0}


async def _query_enrichment_health() -> dict[str, Any]:
    """Query ops.v_enrichment_health for system status."""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT 
                    COALESCE(SUM(pending_count), 0) AS pending,
                    COALESCE(SUM(failed_count), 0) AS failed_24h,
                    BOOL_AND(is_healthy) AS all_healthy
                FROM ops.v_enrichment_health
                """
            )
            if row:
                return {
                    "jobs_pending": int(row["pending"]),
                    "jobs_failed_24h": int(row["failed_24h"]),
                    "healthy": (
                        bool(row["all_healthy"])
                        if row["all_healthy"] is not None
                        else True
                    ),
                }
    except Exception as e:
        logger.warning(f"Failed to query v_enrichment_health: {e}")

    return {"jobs_pending": 0, "jobs_failed_24h": 0, "healthy": True}


async def gather_ceo_briefing_data() -> CEOBriefingData:
    """
    Gather all data needed for the CEO morning briefing.

    Queries multiple views and aggregates into a single data object.
    """
    logger.info("Gathering CEO briefing data...")

    # Query all sources
    buy_data = await _query_buy_candidates()
    offer_data = await _query_offer_stats()
    health_data = await _query_enrichment_health()

    return CEOBriefingData(
        buy_candidates_count=buy_data["count"],
        total_portfolio_value=buy_data["total_value"],
        offers_pending=offer_data["pending"],
        offers_accepted_30d=offer_data["accepted_30d"],
        acceptance_rate_30d=offer_data["acceptance_rate_30d"],
        enrichment_healthy=health_data["healthy"],
        jobs_pending=health_data["jobs_pending"],
        jobs_failed_24h=health_data["jobs_failed_24h"],
        generated_at=datetime.now(),
    )


def format_ceo_briefing_html(data: CEOBriefingData) -> str:
    """
    Format CEO briefing data as HTML email.

    Clean, mobile-friendly design with executive summary.
    """
    today = date.today().strftime("%A, %B %d, %Y")

    # Determine health status color
    if data.jobs_failed_24h > 0:
        health_color = "#e74c3c"  # Red
        health_status = "⚠️ Attention Needed"
    elif data.jobs_pending > 10:
        health_color = "#f39c12"  # Orange
        health_status = "⏳ Processing"
    else:
        health_color = "#27ae60"  # Green
        health_status = "✅ All Systems Normal"

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #1a365d 0%, #2c5282 100%);
            color: white;
            padding: 24px;
            border-radius: 8px 8px 0 0;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 600;
        }}
        .header .date {{
            opacity: 0.9;
            font-size: 14px;
            margin-top: 4px;
        }}
        .content {{
            background: white;
            padding: 24px;
            border-radius: 0 0 8px 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 24px;
        }}
        .metric {{
            background: #f8f9fa;
            padding: 16px;
            border-radius: 8px;
            text-align: center;
        }}
        .metric .value {{
            font-size: 28px;
            font-weight: 700;
            color: #1a365d;
        }}
        .metric .label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .health-bar {{
            background: {health_color};
            color: white;
            padding: 12px 16px;
            border-radius: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 16px;
        }}
        .section {{
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }}
        .section h2 {{
            font-size: 16px;
            color: #1a365d;
            margin: 0 0 12px 0;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #999;
            margin-top: 24px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🐉 Dragonfly Daily Briefing</h1>
        <div class="date">{today}</div>
    </div>
    
    <div class="content">
        <div class="metric-grid">
            <div class="metric">
                <div class="value">{data.buy_candidates_count}</div>
                <div class="label">Buy Candidates</div>
            </div>
            <div class="metric">
                <div class="value">${data.total_portfolio_value:,.0f}</div>
                <div class="label">Total Value</div>
            </div>
            <div class="metric">
                <div class="value">{data.offers_pending}</div>
                <div class="label">Offers Pending</div>
            </div>
            <div class="metric">
                <div class="value">{data.acceptance_rate_30d:.1f}%</div>
                <div class="label">30-Day Accept Rate</div>
            </div>
        </div>
        
        <div class="health-bar">
            <span>{health_status}</span>
            <span>{data.jobs_pending} pending / {data.jobs_failed_24h} failed</span>
        </div>
        
        <div class="section">
            <h2>📊 30-Day Performance</h2>
            <p>
                <strong>{data.offers_accepted_30d}</strong> offers accepted in the last 30 days
                with a <strong>{data.acceptance_rate_30d:.1f}%</strong> acceptance rate.
            </p>
        </div>
    </div>
    
    <div class="footer">
        Generated by Dragonfly Engine at {data.generated_at.strftime('%I:%M %p ET') if data.generated_at else 'N/A'}
    </div>
</body>
</html>
"""


def format_ceo_briefing_plain(data: CEOBriefingData) -> str:
    """
    Format CEO briefing data as plain text email (fallback).
    """
    today = date.today().strftime("%A, %B %d, %Y")

    return f"""
DRAGONFLY DAILY BRIEFING
{today}
{'=' * 40}

PORTFOLIO OVERVIEW
- Buy Candidates: {data.buy_candidates_count}
- Total Value: ${data.total_portfolio_value:,.2f}

OFFER PERFORMANCE (30 Days)
- Pending: {data.offers_pending}
- Accepted: {data.offers_accepted_30d}
- Acceptance Rate: {data.acceptance_rate_30d:.1f}%

SYSTEM STATUS
- Jobs Pending: {data.jobs_pending}
- Jobs Failed (24h): {data.jobs_failed_24h}
- Status: {'Healthy' if data.enrichment_healthy else 'Attention Needed'}

{'=' * 40}
Generated at {data.generated_at.strftime('%I:%M %p ET') if data.generated_at else 'N/A'}
"""


async def generate_ceo_briefing() -> dict[str, Any]:
    """
    Generate and format the complete CEO morning briefing.

    Returns:
        Dict with 'subject', 'html_body', 'plain_body', and 'data'
    """
    logger.info("Generating CEO briefing...")

    data = await gather_ceo_briefing_data()

    subject = f"Daily Briefing: {data.buy_candidates_count} Candidates, ${data.total_portfolio_value:,.0f} Value"

    return {
        "subject": subject,
        "html_body": format_ceo_briefing_html(data),
        "plain_body": format_ceo_briefing_plain(data),
        "data": data,
    }


async def generate_ops_summary() -> dict[str, Any]:
    """
    Generate an operational summary for the Ops team.

    Similar to CEO briefing but with more operational details.
    """
    logger.info("Generating Ops summary...")

    data = await gather_ceo_briefing_data()

    # Ops gets a more technical summary
    subject = f"Ops Daily: {data.jobs_pending} pending, {data.jobs_failed_24h} failed"

    plain_body = f"""
DRAGONFLY OPS DAILY SUMMARY
{date.today().strftime('%Y-%m-%d')}

JOBS
- Pending: {data.jobs_pending}
- Failed (24h): {data.jobs_failed_24h}

PORTFOLIO
- Buy Candidates: {data.buy_candidates_count}
- Offers Pending: {data.offers_pending}

ACTION NEEDED: {'Yes' if data.jobs_failed_24h > 0 else 'None'}
"""

    return {
        "subject": subject,
        "plain_body": plain_body,
        "html_body": None,  # Ops gets plain text
        "data": data,
    }
