"""Utility script to refresh enforcement views in the target Supabase database."""

from __future__ import annotations

import pathlib
import sys

import psycopg

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.supabase_client import get_supabase_db_url


def main(env: str = "prod") -> None:
    url = get_supabase_db_url(env)
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'judgments'
                      AND column_name = 'plaintiff_id'
                )
                """
            )
            has_plaintiff_id = cur.fetchone()[0]

            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'plaintiffs'
                )
                """
            )
            has_plaintiffs_table = cur.fetchone()[0]

            if has_plaintiff_id and has_plaintiffs_table:
                enforcement_recent_sql = """
                    CREATE OR REPLACE VIEW public.v_enforcement_recent AS
                    SELECT
                        j.id AS judgment_id,
                        j.case_number,
                        j.plaintiff_id::text AS plaintiff_id,
                        j.judgment_amount,
                        j.enforcement_stage,
                        j.enforcement_stage_updated_at,
                        cs.collectability_tier,
                        COALESCE(p.name, j.plaintiff_name) AS plaintiff_name
                    FROM public.judgments j
                    LEFT JOIN public.plaintiffs p
                        ON p.id::text = j.plaintiff_id::text
                    LEFT JOIN public.v_collectability_snapshot cs
                        ON cs.case_number = j.case_number
                    ORDER BY
                        j.enforcement_stage_updated_at DESC,
                        j.id DESC;
                """

                judgment_pipeline_sql = """
                    CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
                    SELECT
                        j.id AS judgment_id,
                        j.case_number,
                        j.plaintiff_id::text AS plaintiff_id,
                        COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
                        j.defendant_name,
                        j.judgment_amount,
                        j.enforcement_stage,
                        j.enforcement_stage_updated_at,
                        cs.collectability_tier,
                        cs.age_days AS collectability_age_days,
                        cs.last_enriched_at,
                        cs.last_enrichment_status
                    FROM public.judgments j
                    LEFT JOIN public.plaintiffs p
                        ON p.id::text = j.plaintiff_id::text
                    LEFT JOIN public.v_collectability_snapshot cs
                        ON cs.case_number = j.case_number;
                """

            elif has_plaintiffs_table:
                enforcement_recent_sql = """
                    CREATE OR REPLACE VIEW public.v_enforcement_recent AS
                    SELECT
                        j.id AS judgment_id,
                        j.case_number,
                        p.id::text AS plaintiff_id,
                        j.judgment_amount,
                        j.enforcement_stage,
                        j.enforcement_stage_updated_at,
                        cs.collectability_tier,
                        COALESCE(p.name, j.plaintiff_name) AS plaintiff_name
                    FROM public.judgments j
                    LEFT JOIN public.plaintiffs p
                        ON lower(p.name) = lower(j.plaintiff_name)
                    LEFT JOIN public.v_collectability_snapshot cs
                        ON cs.case_number = j.case_number
                    ORDER BY
                        j.enforcement_stage_updated_at DESC,
                        j.id DESC;
                """

                judgment_pipeline_sql = """
                    CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
                    SELECT
                        j.id AS judgment_id,
                        j.case_number,
                        p.id::text AS plaintiff_id,
                        COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
                        j.defendant_name,
                        j.judgment_amount,
                        j.enforcement_stage,
                        j.enforcement_stage_updated_at,
                        cs.collectability_tier,
                        cs.age_days AS collectability_age_days,
                        cs.last_enriched_at,
                        cs.last_enrichment_status
                    FROM public.judgments j
                    LEFT JOIN public.plaintiffs p
                        ON lower(p.name) = lower(j.plaintiff_name)
                    LEFT JOIN public.v_collectability_snapshot cs
                        ON cs.case_number = j.case_number;
                """

            else:
                enforcement_recent_sql = """
                    CREATE OR REPLACE VIEW public.v_enforcement_recent AS
                    SELECT
                        j.id AS judgment_id,
                        j.case_number,
                        NULL::text AS plaintiff_id,
                        j.judgment_amount,
                        j.enforcement_stage,
                        j.enforcement_stage_updated_at,
                        cs.collectability_tier,
                        j.plaintiff_name
                    FROM public.judgments j
                    LEFT JOIN public.v_collectability_snapshot cs
                        ON cs.case_number = j.case_number
                    ORDER BY
                        j.enforcement_stage_updated_at DESC,
                        j.id DESC;
                """

                judgment_pipeline_sql = """
                    CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
                    SELECT
                        j.id AS judgment_id,
                        j.case_number,
                        NULL::text AS plaintiff_id,
                        j.plaintiff_name,
                        j.defendant_name,
                        j.judgment_amount,
                        j.enforcement_stage,
                        j.enforcement_stage_updated_at,
                        cs.collectability_tier,
                        cs.age_days AS collectability_age_days,
                        cs.last_enriched_at,
                        cs.last_enrichment_status
                    FROM public.judgments j
                    LEFT JOIN public.v_collectability_snapshot cs
                        ON cs.case_number = j.case_number;
                """

            cur.execute(enforcement_recent_sql)
            cur.execute(judgment_pipeline_sql)
            cur.execute(
                "GRANT SELECT ON public.v_enforcement_recent TO anon, authenticated, service_role"
            )
            cur.execute(
                "GRANT SELECT ON public.v_judgment_pipeline TO anon, authenticated, service_role"
            )

    print(
        "views refreshed",
        {
            "has_plaintiff_id": has_plaintiff_id,
            "has_plaintiffs_table": has_plaintiffs_table,
        },
    )


if __name__ == "__main__":
    main()
