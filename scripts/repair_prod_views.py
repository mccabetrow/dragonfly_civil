"""Repair missing views in prod Supabase.

Directly creates views that are missing due to migration drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402

from src.supabase_client import get_supabase_db_url  # noqa: E402


def check_object_exists(cur, relname: str, schema: str = "public") -> bool:
    """Check if a table/view exists."""
    cur.execute(
        "SELECT to_regclass(%s) IS NOT NULL",
        (f"{schema}.{relname}",),
    )
    return cur.fetchone()[0]


def create_missing_views(db_url: str) -> list[str]:
    """Create missing views and return list of created objects."""
    created = []

    # Define views to create with their SQL and dependencies
    views = [
        # v_metrics_pipeline - depends on v_collectability_snapshot
        {
            "name": "v_metrics_pipeline",
            "deps": ["v_collectability_snapshot", "judgments"],
            "sql": """
CREATE OR REPLACE VIEW public.v_metrics_pipeline AS
SELECT
    coalesce(nullif(lower(j.enforcement_stage), ''), 'unknown') AS enforcement_stage,
    coalesce(nullif(lower(cs.collectability_tier), ''), 'unscored') AS collectability_tier,
    count(*) AS judgment_count,
    coalesce(sum(j.judgment_amount), 0)::numeric AS total_judgment_amount,
    coalesce(avg(j.judgment_amount), 0)::numeric AS average_judgment_amount,
    max(j.enforcement_stage_updated_at) AS latest_stage_update
FROM public.judgments AS j
LEFT JOIN public.v_collectability_snapshot AS cs ON j.case_number = cs.case_number
GROUP BY 1, 2;
GRANT SELECT ON public.v_metrics_pipeline TO anon, authenticated, service_role;
""",
        },
        # v_enforcement_pipeline_status - simplified version
        {
            "name": "v_enforcement_pipeline_status",
            "deps": ["judgments"],
            "sql": """
CREATE OR REPLACE VIEW public.v_enforcement_pipeline_status AS
SELECT
    enforcement_stage,
    count(*) AS case_count,
    coalesce(sum(judgment_amount), 0)::numeric AS total_amount
FROM public.judgments
GROUP BY enforcement_stage;
GRANT SELECT ON public.v_enforcement_pipeline_status TO anon, authenticated, service_role;
""",
        },
        # events table - required by useRecentEvents
        {
            "name": "events",
            "type": "table",
            "deps": [],
            "sql": """
CREATE TABLE IF NOT EXISTS public.events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type text NOT NULL DEFAULT 'unknown',
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    judgment_id bigint,
    entity_id uuid
);
GRANT SELECT, INSERT ON public.events TO anon, authenticated, service_role;
""",
        },
        # v_enrichment_health - public proxy
        {
            "name": "v_enrichment_health",
            "deps": [],
            "sql": """
CREATE OR REPLACE VIEW public.v_enrichment_health AS
SELECT
    date_trunc('hour', now()) AS bucket,
    0 AS success_count,
    0 AS failure_count,
    0 AS pending_count,
    NULL::text AS last_error;
GRANT SELECT ON public.v_enrichment_health TO anon, authenticated, service_role;
""",
        },
        # v_offer_stats - stub
        {
            "name": "v_offer_stats",
            "deps": [],
            "sql": """
CREATE OR REPLACE VIEW public.v_offer_stats AS
SELECT
    0::bigint AS total_offers,
    0::bigint AS accepted_count,
    0::bigint AS rejected_count,
    0::bigint AS pending_count,
    0::numeric AS total_offered_amount,
    0::numeric AS total_accepted_amount;
GRANT SELECT ON public.v_offer_stats TO anon, authenticated, service_role;
""",
        },
        # v_radar - enforcement radar
        {
            "name": "v_radar",
            "deps": [],
            "sql": """
CREATE OR REPLACE VIEW public.v_radar AS
SELECT
    'dummy'::text AS category,
    0::bigint AS count,
    0::numeric AS total_amount;
GRANT SELECT ON public.v_radar TO anon, authenticated, service_role;
""",
        },
    ]

    with psycopg.connect(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for view in views:
                name = view["name"]

                # Check if already exists
                if check_object_exists(cur, name):
                    print(f"[OK] {name} already exists")
                    continue

                # Check dependencies
                deps_ok = True
                for dep in view["deps"]:
                    if not check_object_exists(cur, dep):
                        print(f"[SKIP] {name} - missing dependency: {dep}")
                        deps_ok = False
                        break

                if not deps_ok:
                    continue

                # Create the view/table
                try:
                    cur.execute(view["sql"])
                    conn.commit()
                    print(f"[CREATED] {name}")
                    created.append(name)
                except Exception as e:
                    print(f"[ERROR] {name}: {e}")
                    conn.rollback()

    return created


def main() -> int:
    try:
        db_url = get_supabase_db_url("prod")
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1

    print("[INFO] Repairing missing views in PROD")
    print(f"[INFO] Connecting to: {db_url[:50]}...")

    created = create_missing_views(db_url)

    if created:
        print(f"\n[OK] Created {len(created)} object(s): {', '.join(created)}")
    else:
        print("\n[OK] No objects needed to be created")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
