"""Static SQL statements used by background workers."""

SELECT_NEW_CASES_FOR_ENRICH = (
    """
    with ranked_cases as (
        select
            c.case_id,
            c.index_no,
            c.court,
            c.county,
            c.status,
            c.created_at,
            row_number() over (order by c.created_at asc) as rn
        from judgments.cases c
        where c.status = 'new'
    )
    select
        case_id,
        index_no,
        court,
        county,
        status,
        created_at
    from ranked_cases
    where rn <= %(limit)s;
    """
).strip()

UPSERT_COLLECTABILITY = (
    """
    insert into enrichment.collectability (
        case_id,
        identity_score,
        contactability_score,
        asset_score,
        recency_amount_score,
        adverse_penalty,
        updated_at
    )
    values (
        %(case_id)s,
        %(identity_score)s,
        %(contactability_score)s,
        %(asset_score)s,
        %(recency_amount_score)s,
        %(adverse_penalty)s,
        now()
    )
    on conflict (case_id) do update
    set
        identity_score = excluded.identity_score,
        contactability_score = excluded.contactability_score,
        asset_score = excluded.asset_score,
        recency_amount_score = excluded.recency_amount_score,
        adverse_penalty = excluded.adverse_penalty,
        updated_at = now();
    """
).strip()
