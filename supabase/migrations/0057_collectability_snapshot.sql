create or replace view judgments.v_collectability_snapshot as with latest_enrichment as (
        select er.case_id,
            er.created_at,
            er.status,
            row_number() over (
                partition by er.case_id
                order by er.created_at desc,
                    er.id desc
            ) as row_num
        from judgments.enrichment_runs er
    )
select c.case_id,
    c.case_number,
    c.amount_awarded as judgment_amount,
    c.judgment_date,
    case
        when c.judgment_date is not null then (current_date - c.judgment_date)
    end as age_days,
    le.created_at as last_enriched_at,
    le.status as last_enrichment_status,
    case
        when coalesce(c.amount_awarded, 0) >= 3000
        and c.judgment_date is not null
        and (current_date - c.judgment_date) <= 365 then 'A'
        when (
            coalesce(c.amount_awarded, 0) between 1000 and 2999
        )
        or (
            c.judgment_date is not null
            and (current_date - c.judgment_date) between 366 and 1095
        ) then 'B'
        else 'C'
    end as collectability_tier
from judgments.cases c
    left join latest_enrichment le on c.case_id = le.case_id
    and le.row_num = 1;
grant select on judgments.v_collectability_snapshot to service_role;
-- migrate:down
drop view if exists judgments.v_collectability_snapshot;