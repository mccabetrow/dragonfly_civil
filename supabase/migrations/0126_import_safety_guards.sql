-- 0126_import_safety_guards.sql
-- Add check_import_guardrails RPC to keep high-volume imports safe in prod.
-- migrate:up
CREATE OR REPLACE FUNCTION public.check_import_guardrails(p_source_system text) RETURNS TABLE (ok boolean, message text) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    judgments AS $$
DECLARE normalized_source text := lower(NULLIF(btrim(p_source_system), ''));
duplicate_case text;
missing_case text;
empty_plaintiff text;
stuck_run text;
BEGIN IF normalized_source IS NULL
OR normalized_source = '' THEN normalized_source := 'unknown';
END IF;
SELECT dup.case_number INTO duplicate_case
FROM (
        SELECT upper(trim(c.case_number)) AS case_number
        FROM judgments.cases c
        WHERE COALESCE(NULLIF(lower(c.source_system), ''), 'unknown') = normalized_source
        GROUP BY upper(trim(c.case_number))
        HAVING COUNT(*) > 1
    ) AS dup
LIMIT 1;
IF duplicate_case IS NOT NULL THEN RETURN QUERY
SELECT false,
    format(
        'Duplicate case_number %s detected for source_system %s',
        duplicate_case,
        normalized_source
    );
RETURN;
END IF;
SELECT upper(trim(c.case_number)) INTO missing_case
FROM judgments.cases c
WHERE COALESCE(NULLIF(lower(c.source_system), ''), 'unknown') = normalized_source
    AND c.judgment_date IS NULL
ORDER BY c.created_at DESC
LIMIT 1;
IF missing_case IS NOT NULL THEN RETURN QUERY
SELECT false,
    format(
        'Judgment date missing for case_number %s (source_system %s)',
        missing_case,
        normalized_source
    );
RETURN;
END IF;
SELECT p.id::text INTO empty_plaintiff
FROM public.plaintiffs p
WHERE COALESCE(NULLIF(lower(p.source_system), ''), 'unknown') = normalized_source
    AND (
        p.name IS NULL
        OR btrim(p.name) = ''
    )
ORDER BY p.created_at DESC
LIMIT 1;
IF empty_plaintiff IS NOT NULL THEN RETURN QUERY
SELECT false,
    format(
        'Plaintiff %s is missing a name for source_system %s',
        empty_plaintiff,
        normalized_source
    );
RETURN;
END IF;
SELECT ir.id::text INTO stuck_run
FROM public.import_runs ir
WHERE COALESCE(NULLIF(lower(ir.source_system), ''), 'unknown') = normalized_source
    AND lower(COALESCE(ir.status, '')) = 'running'
ORDER BY ir.started_at ASC
LIMIT 1;
IF stuck_run IS NOT NULL THEN RETURN QUERY
SELECT false,
    format(
        'Import run %s is still running for source_system %s',
        stuck_run,
        normalized_source
    );
RETURN;
END IF;
RETURN QUERY
SELECT true,
    format(
        'All guardrails satisfied for %s',
        normalized_source
    );
END;
$$;
REVOKE ALL ON FUNCTION public.check_import_guardrails(text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.check_import_guardrails(text) TO service_role;
COMMENT ON FUNCTION public.check_import_guardrails(text) IS 'Validates duplicate cases, judgment dates, plaintiff names, and stuck import runs before running prod imports.';