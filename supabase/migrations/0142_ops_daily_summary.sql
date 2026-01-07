-- Rollup view that exposes a single daily ops summary row.
CREATE OR REPLACE VIEW public.v_ops_daily_summary AS WITH summary_anchor AS (
        SELECT timezone('utc', now())::date AS summary_date
    ),
    new_plaintiff_counts AS (
        SELECT anchor.summary_date,
            COUNT(p.id) AS new_plaintiffs
        FROM summary_anchor AS anchor
            LEFT JOIN public.plaintiffs AS p ON p.created_at::date = anchor.summary_date
        GROUP BY anchor.summary_date
    ),
    call_attempt_counts AS (
        SELECT anchor.summary_date,
            COUNT(ca.id) AS calls_made
        FROM summary_anchor AS anchor
            LEFT JOIN public.plaintiff_call_attempts AS ca ON ca.attempted_at::date = anchor.summary_date
        GROUP BY anchor.summary_date
    ),
    plaintiff_contact_counts AS (
        SELECT anchor.summary_date,
            COUNT(DISTINCT activity.plaintiff_id) AS plaintiffs_contacted
        FROM summary_anchor AS anchor
            LEFT JOIN (
                SELECT plaintiff_id,
                    attempted_at::date AS activity_date
                FROM public.plaintiff_call_attempts
                WHERE attempted_at IS NOT NULL
                UNION ALL
                SELECT plaintiff_id,
                    changed_at::date AS activity_date
                FROM public.plaintiff_status_history
                WHERE changed_at IS NOT NULL
                    AND status IN (
                        'contacted',
                        'qualified',
                        'sent_agreement',
                        'signed'
                    )
            ) AS activity ON activity.activity_date = anchor.summary_date
        GROUP BY anchor.summary_date
    ),
    agreement_counts AS (
        SELECT anchor.summary_date,
            COUNT(*) FILTER (
                WHERE sh.status = 'sent_agreement'
            ) AS agreements_sent,
            COUNT(*) FILTER (
                WHERE sh.status = 'signed'
            ) AS agreements_signed
        FROM summary_anchor AS anchor
            LEFT JOIN public.plaintiff_status_history AS sh ON sh.changed_at::date = anchor.summary_date
            AND sh.status IN ('sent_agreement', 'signed')
        GROUP BY anchor.summary_date
    )
SELECT anchor.summary_date,
    COALESCE(np.new_plaintiffs, 0) AS new_plaintiffs,
    COALESCE(pc.plaintiffs_contacted, 0) AS plaintiffs_contacted,
    COALESCE(ca.calls_made, 0) AS calls_made,
    COALESCE(ac.agreements_sent, 0) AS agreements_sent,
    COALESCE(ac.agreements_signed, 0) AS agreements_signed
FROM summary_anchor AS anchor
    LEFT JOIN new_plaintiff_counts AS np USING (summary_date)
    LEFT JOIN plaintiff_contact_counts AS pc USING (summary_date)
    LEFT JOIN call_attempt_counts AS ca USING (summary_date)
    LEFT JOIN agreement_counts AS ac USING (summary_date);
GRANT SELECT ON public.v_ops_daily_summary TO authenticated;
GRANT SELECT ON public.v_ops_daily_summary TO service_role;
