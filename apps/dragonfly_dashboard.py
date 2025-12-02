#!/usr/bin/env python3
"""
Dragonfly Civil Dashboard - Streamlit Application

A simple, readable dashboard for non-technical users to monitor
judgment enforcement pipeline, browse actionable judgments, and
trigger income execution workflows.

Usage:
    streamlit run apps/dragonfly_dashboard.py

Environment Variables:
    SUPABASE_URL            - Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY - Service role API key
    SUPABASE_MODE           - 'dev' or 'prod' (default: dev)
    N8N_INCOME_EXECUTION_WEBHOOK - n8n webhook URL for income execution
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import httpx
import streamlit as st

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.supabase_client import create_supabase_client, get_supabase_env

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Page configuration - must be first Streamlit command
st.set_page_config(
    page_title="Dragonfly Civil Dashboard",
    page_icon="🐉",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS for bigger fonts and readable layout
st.markdown(
    """
    <style>
    /* Main content styling */
    .main .block-container {
        padding-top: 2rem;
        max-width: 1200px;
    }
    
    /* Bigger fonts for readability */
    h1 {
        font-size: 2.5rem !important;
        color: #1e3a5f;
    }
    h2 {
        font-size: 1.8rem !important;
        color: #2c5282;
    }
    h3 {
        font-size: 1.4rem !important;
    }
    
    /* Metric styling */
    [data-testid="stMetricValue"] {
        font-size: 2rem !important;
        font-weight: bold;
    }
    [data-testid="stMetricLabel"] {
        font-size: 1.1rem !important;
    }
    
    /* Table styling */
    .dataframe {
        font-size: 1rem !important;
    }
    
    /* Button styling */
    .stButton > button {
        font-size: 1rem;
        padding: 0.5rem 1rem;
    }
    
    /* Error/warning boxes */
    .stAlert {
        font-size: 1.1rem;
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab"] {
        font-size: 1.2rem;
        padding: 1rem 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Supabase Client
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner="Connecting to database...")
def get_supabase_client():
    """Create and cache Supabase client."""
    try:
        env = get_supabase_env()
        client = create_supabase_client(env)
        return client
    except Exception as e:
        logger.error("Failed to connect to Supabase: %s", e)
        raise


def safe_query(query_func):
    """Execute a Supabase query with error handling."""
    try:
        return query_func()
    except Exception as e:
        logger.error("Database query failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Data Loading Functions
# ---------------------------------------------------------------------------


def load_judgment_status_counts(client) -> dict[str, int]:
    """Load count of judgments per status for the Pipeline tab."""
    try:
        response = client.table("core_judgments").select("status").execute()
        if not response.data:
            return {}

        counts: dict[str, int] = {}
        for row in response.data:
            status = row.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts
    except Exception as e:
        logger.error("Failed to load status counts: %s", e)
        st.error(f"⚠️ Could not load pipeline data: {e}")
        return {}


def load_actionable_judgments(
    client,
    county_filter: str | None = None,
    min_principal: float | None = None,
) -> list[dict[str, Any]]:
    """
    Load judgments with status ACTIONABLE or LITIGATION,
    joined to debtor_intelligence rows.
    """
    try:
        # Build query for actionable judgments
        # Note: We map collectability_score >= 60 as "ACTIONABLE" per docs
        query = client.table("core_judgments").select(
            "id, case_index_number, debtor_name, original_creditor, "
            "judgment_date, principal_amount, county, status, collectability_score, "
            "debtor_intelligence(employer_name, employer_address, income_band, bank_name)"
        )

        # Filter for actionable judgments (collectability_score >= 60)
        # or status in litigation-related states
        # Since we don't have ACTIONABLE/LITIGATION as literal status values,
        # we filter by collectability_score for "actionable" judgments
        query = query.gte("collectability_score", 60)

        if county_filter and county_filter != "All Counties":
            query = query.eq("county", county_filter)

        if min_principal and min_principal > 0:
            query = query.gte("principal_amount", min_principal)

        response = query.order("collectability_score", desc=True).execute()
        return response.data or []
    except Exception as e:
        logger.error("Failed to load actionable judgments: %s", e)
        st.error(f"⚠️ Could not load judgments: {e}")
        return []


def load_distinct_counties(client) -> list[str]:
    """Load distinct county values for filtering."""
    try:
        response = client.table("core_judgments").select("county").execute()
        if not response.data:
            return []
        counties = sorted(
            set(row.get("county") for row in response.data if row.get("county"))
        )
        return counties
    except Exception as e:
        logger.error("Failed to load counties: %s", e)
        return []


def load_stats(client) -> dict[str, Any]:
    """Load aggregate statistics for the Stats tab."""
    stats = {
        "total_principal": 0.0,
        "actionable_principal": 0.0,
        "enforcement_counts": {},
    }

    try:
        # Total principal across all judgments
        response = client.table("core_judgments").select("principal_amount").execute()
        if response.data:
            stats["total_principal"] = sum(
                float(row.get("principal_amount") or 0) for row in response.data
            )

        # Total principal for actionable judgments (collectability_score >= 60)
        response = (
            client.table("core_judgments")
            .select("principal_amount")
            .gte("collectability_score", 60)
            .execute()
        )
        if response.data:
            stats["actionable_principal"] = sum(
                float(row.get("principal_amount") or 0) for row in response.data
            )

        # Count enforcement actions by type
        response = client.table("enforcement_actions").select("action_type").execute()
        if response.data:
            for row in response.data:
                action_type = row.get("action_type") or "unknown"
                stats["enforcement_counts"][action_type] = (
                    stats["enforcement_counts"].get(action_type, 0) + 1
                )
    except Exception as e:
        logger.error("Failed to load stats: %s", e)
        st.error(f"⚠️ Could not load statistics: {e}")

    return stats


# ---------------------------------------------------------------------------
# Webhook Integration
# ---------------------------------------------------------------------------


def trigger_income_execution(
    judgment_id: str, requested_by: str = "dashboard"
) -> dict[str, Any]:
    """
    Call the n8n webhook to generate an income execution document.

    Args:
        judgment_id: UUID of the judgment
        requested_by: Email or identifier of requestor

    Returns:
        Response from the webhook, or error dict
    """
    webhook_url = os.getenv("N8N_INCOME_EXECUTION_WEBHOOK")

    if not webhook_url:
        return {
            "success": False,
            "error": "N8N_INCOME_EXECUTION_WEBHOOK environment variable not set",
        }

    payload = {
        "judgment_id": judgment_id,
        "requested_by": requested_by,
        "require_attorney_signature": True,
    }

    try:
        with httpx.Client(timeout=30.0) as http_client:
            response = http_client.post(webhook_url, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error("Webhook HTTP error: %s", e)
        return {
            "success": False,
            "error": f"HTTP {e.response.status_code}: {e.response.text}",
        }
    except httpx.RequestError as e:
        logger.error("Webhook request error: %s", e)
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Webhook unexpected error: %s", e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tab: Pipeline
# ---------------------------------------------------------------------------


def render_pipeline_tab(client):
    """Render the Pipeline tab with status counts bar chart."""
    st.header("📊 Judgment Pipeline")
    st.markdown("Overview of all judgments by enforcement status.")

    with st.spinner("Loading pipeline data..."):
        counts = load_judgment_status_counts(client)

    if not counts:
        st.info("ℹ️ No judgments found in the database.")
        return

    # Display metrics in columns
    cols = st.columns(min(len(counts), 4))
    sorted_statuses = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    for idx, (status, count) in enumerate(sorted_statuses[:4]):
        with cols[idx]:
            label = status.replace("_", " ").title()
            st.metric(label=label, value=f"{count:,}")

    # Bar chart
    st.subheader("Status Distribution")

    import pandas as pd

    df = pd.DataFrame(
        [
            {"Status": status.replace("_", " ").title(), "Count": count}
            for status, count in sorted_statuses
        ]
    )

    st.bar_chart(df.set_index("Status")["Count"], use_container_width=True)

    # Summary
    total = sum(counts.values())
    st.markdown(f"**Total Judgments:** {total:,}")


# ---------------------------------------------------------------------------
# Tab: Judgments
# ---------------------------------------------------------------------------


def render_judgments_tab(client):
    """Render the Judgments tab with filters and action buttons."""
    st.header("⚖️ Actionable Judgments")
    st.markdown(
        "Judgments ready for enforcement action (collectability score ≥ 60). "
        "Click **Generate Income Execution** to create wage garnishment documents."
    )

    # Filters
    st.subheader("Filters")
    col1, col2 = st.columns(2)

    with col1:
        counties = load_distinct_counties(client)
        county_options = ["All Counties"] + counties
        selected_county = st.selectbox(
            "📍 County",
            options=county_options,
            index=0,
            help="Filter judgments by county",
        )

    with col2:
        min_principal = st.number_input(
            "💰 Minimum Principal Amount ($)",
            min_value=0.0,
            value=0.0,
            step=500.0,
            format="%.2f",
            help="Show only judgments above this principal amount",
        )

    # Load data
    with st.spinner("Loading judgments..."):
        county_filter = selected_county if selected_county != "All Counties" else None
        judgments = load_actionable_judgments(client, county_filter, min_principal)

    if not judgments:
        st.info("ℹ️ No actionable judgments match your filters.")
        return

    st.markdown(f"**Showing {len(judgments)} judgment(s)**")
    st.divider()

    # Display each judgment as a card
    for judgment in judgments:
        judgment_id = judgment.get("id", "")
        case_number = judgment.get("case_index_number", "Unknown")
        debtor = judgment.get("debtor_name", "Unknown Debtor")
        creditor = judgment.get("original_creditor", "Unknown Creditor")
        principal = judgment.get("principal_amount") or 0
        county = judgment.get("county", "N/A")
        score = judgment.get("collectability_score", 0)
        judgment_date = judgment.get("judgment_date", "N/A")

        # Extract debtor intelligence (nested relation)
        intel_list = judgment.get("debtor_intelligence") or []
        intel = intel_list[0] if intel_list else {}
        employer = intel.get("employer_name", "—")
        income_band = intel.get("income_band", "—")

        # Card layout
        with st.container():
            cols = st.columns([3, 2, 1])

            with cols[0]:
                st.markdown(f"### {case_number}")
                st.markdown(f"**Debtor:** {debtor}")
                st.markdown(f"**Creditor:** {creditor}")
                st.markdown(f"**County:** {county} | **Date:** {judgment_date}")

            with cols[1]:
                st.metric("Principal", f"${principal:,.2f}")
                st.markdown(f"**Score:** {score}/100")
                st.markdown(f"**Employer:** {employer}")
                st.markdown(f"**Income:** {income_band}")

            with cols[2]:
                # Check if income execution is possible
                can_execute = (
                    employer
                    and employer != "—"
                    and income_band not in ("LOW", "$0-25k", None, "")
                )

                if can_execute:
                    button_key = f"exec_{judgment_id}"
                    if st.button(
                        "📄 Generate Income Execution", key=button_key, type="primary"
                    ):
                        with st.spinner("Generating document..."):
                            result = trigger_income_execution(judgment_id)

                        if result.get("success"):
                            st.success("✅ Document generated! Check your email.")
                            if result.get("data", {}).get("document_url"):
                                st.markdown(
                                    f"[📥 Download PDF]({result['data']['document_url']})"
                                )
                        else:
                            error = result.get("error", "Unknown error")
                            st.error(f"❌ Failed: {error}")
                else:
                    st.button(
                        "📄 Generate Income Execution",
                        key=f"exec_disabled_{judgment_id}",
                        disabled=True,
                        help="Missing employer info or income too low",
                    )

            st.divider()


# ---------------------------------------------------------------------------
# Tab: Stats
# ---------------------------------------------------------------------------


def render_stats_tab(client):
    """Render the Stats tab with aggregate metrics."""
    st.header("📈 Enforcement Statistics")
    st.markdown("Aggregate metrics across all judgments and enforcement actions.")

    with st.spinner("Loading statistics..."):
        stats = load_stats(client)

    # Principal amounts
    st.subheader("💰 Principal Amounts")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            label="Total Principal (All Judgments)",
            value=f"${stats['total_principal']:,.2f}",
        )

    with col2:
        st.metric(
            label="Actionable Principal (Score ≥ 60)",
            value=f"${stats['actionable_principal']:,.2f}",
        )

    with col3:
        if stats["total_principal"] > 0:
            pct = (stats["actionable_principal"] / stats["total_principal"]) * 100
            st.metric(
                label="Actionable %",
                value=f"{pct:.1f}%",
            )
        else:
            st.metric(label="Actionable %", value="N/A")

    st.divider()

    # Enforcement actions breakdown
    st.subheader("🎯 Enforcement Actions by Type")

    enforcement_counts = stats.get("enforcement_counts", {})

    if not enforcement_counts:
        st.info("ℹ️ No enforcement actions recorded yet.")
    else:
        import pandas as pd

        df = pd.DataFrame(
            [
                {"Action Type": action_type.replace("_", " ").title(), "Count": count}
                for action_type, count in sorted(
                    enforcement_counts.items(), key=lambda x: x[1], reverse=True
                )
            ]
        )

        # Show as table and bar chart
        col1, col2 = st.columns([1, 2])

        with col1:
            st.dataframe(
                df,
                hide_index=True,
                use_container_width=True,
            )

        with col2:
            st.bar_chart(df.set_index("Action Type")["Count"], use_container_width=True)

        total_actions = sum(enforcement_counts.values())
        st.markdown(f"**Total Enforcement Actions:** {total_actions:,}")


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------


def main():
    """Main application entry point."""
    # Header
    st.title("🐉 Dragonfly Civil Dashboard")

    # Environment indicator
    try:
        env = get_supabase_env()
        env_color = "🔴" if env == "prod" else "🟢"
        st.caption(f"{env_color} Environment: **{env.upper()}**")
    except Exception:
        st.caption("⚠️ Environment: Unknown")

    # Initialize Supabase client
    try:
        client = get_supabase_client()
    except Exception as e:
        st.error(
            f"""
            ## ⚠️ Database Connection Error
            
            Could not connect to Supabase. Please check your environment variables:
            
            - `SUPABASE_URL`
            - `SUPABASE_SERVICE_ROLE_KEY`
            - `SUPABASE_MODE` (optional, defaults to 'dev')
            
            **Error:** {e}
            """
        )
        st.stop()

    # Tabs
    tab_pipeline, tab_judgments, tab_stats = st.tabs(
        [
            "📊 Pipeline",
            "⚖️ Judgments",
            "📈 Stats",
        ]
    )

    with tab_pipeline:
        render_pipeline_tab(client)

    with tab_judgments:
        render_judgments_tab(client)

    with tab_stats:
        render_stats_tab(client)

    # Footer
    st.divider()
    st.caption(
        "Dragonfly Civil © 2024 | "
        "[Documentation](docs/README.md) | "
        "Questions? Contact the ops team."
    )


if __name__ == "__main__":
    main()
