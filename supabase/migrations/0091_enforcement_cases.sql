-- 0091_enforcement_cases.sql
-- Introduce enforcement case tracking tables, supporting views, and access controls.
BEGIN;
CREATE TABLE IF NOT EXISTS public.enforcement_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    judgment_id bigint NOT NULL REFERENCES public.judgments (
        id
    ) ON DELETE CASCADE,
    case_number text,
    opened_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    current_stage text,
    status text NOT NULL DEFAULT 'open',
    assigned_to text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX IF NOT EXISTS enforcement_cases_judgment_idx ON public.enforcement_cases (
    judgment_id
);
CREATE INDEX IF NOT EXISTS enforcement_cases_status_idx ON public.enforcement_cases (
    status
);
DROP TRIGGER IF EXISTS trg_enforcement_cases_touch ON public.enforcement_cases;
CREATE TRIGGER trg_enforcement_cases_touch BEFORE
UPDATE ON public.enforcement_cases FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
ALTER TABLE public.enforcement_cases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.enforcement_cases
FROM public;
GRANT SELECT ON TABLE public.enforcement_cases TO anon,
authenticated,
service_role;
GRANT INSERT,
UPDATE,
DELETE ON TABLE public.enforcement_cases TO authenticated,
service_role;
DROP POLICY IF EXISTS enforcement_cases_rw ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_read ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_write ON public.enforcement_cases;
CREATE POLICY enforcement_cases_read ON public.enforcement_cases FOR
SELECT USING (
    auth.role() IN ('anon', 'authenticated', 'service_role')
);
CREATE POLICY enforcement_cases_write ON public.enforcement_cases FOR ALL USING (
    auth.role() IN ('authenticated', 'service_role')
) WITH CHECK (auth.role() IN ('authenticated', 'service_role'));
CREATE TABLE IF NOT EXISTS public.enforcement_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES public.enforcement_cases (
        id
    ) ON DELETE CASCADE,
    event_type text NOT NULL,
    event_date timestamptz NOT NULL DEFAULT timezone('utc', now()),
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX IF NOT EXISTS enforcement_events_case_idx ON public.enforcement_events (
    case_id
);
CREATE INDEX IF NOT EXISTS enforcement_events_date_idx ON public.enforcement_events (
    event_date DESC
);
DROP TRIGGER IF EXISTS trg_enforcement_events_touch ON public.enforcement_events;
CREATE TRIGGER trg_enforcement_events_touch BEFORE
UPDATE ON public.enforcement_events FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
ALTER TABLE public.enforcement_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.enforcement_events
FROM public;
GRANT SELECT ON TABLE public.enforcement_events TO anon,
authenticated,
service_role;
GRANT INSERT,
UPDATE,
DELETE ON TABLE public.enforcement_events TO authenticated,
service_role;
DROP POLICY IF EXISTS enforcement_events_read ON public.enforcement_events;
DROP POLICY IF EXISTS enforcement_events_write ON public.enforcement_events;
CREATE POLICY enforcement_events_read ON public.enforcement_events FOR
SELECT USING (
    auth.role() IN ('anon', 'authenticated', 'service_role')
);
CREATE POLICY enforcement_events_write ON public.enforcement_events FOR ALL USING (
    auth.role() IN ('authenticated', 'service_role')
) WITH CHECK (auth.role() IN ('authenticated', 'service_role'));
CREATE TABLE IF NOT EXISTS public.evidence_files (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES public.enforcement_cases (
        id
    ) ON DELETE CASCADE,
    storage_path text NOT NULL,
    file_type text,
    uploaded_by text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX IF NOT EXISTS evidence_files_case_idx ON public.evidence_files (
    case_id
);
DROP TRIGGER IF EXISTS trg_evidence_files_touch ON public.evidence_files;
CREATE TRIGGER trg_evidence_files_touch BEFORE
UPDATE ON public.evidence_files FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
ALTER TABLE public.evidence_files ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.evidence_files
FROM public;
GRANT SELECT ON TABLE public.evidence_files TO anon,
authenticated,
service_role;
GRANT INSERT,
UPDATE,
DELETE ON TABLE public.evidence_files TO authenticated,
service_role;
DROP POLICY IF EXISTS evidence_files_read ON public.evidence_files;
DROP POLICY IF EXISTS evidence_files_write ON public.evidence_files;
CREATE POLICY evidence_files_read ON public.evidence_files FOR
SELECT USING (
    auth.role() IN ('anon', 'authenticated', 'service_role')
);
CREATE POLICY evidence_files_write ON public.evidence_files FOR ALL USING (
    auth.role() IN ('authenticated', 'service_role')
) WITH CHECK (auth.role() IN ('authenticated', 'service_role'));
CREATE OR REPLACE VIEW public.v_enforcement_case_summary AS WITH latest_event AS (
    SELECT DISTINCT ON (e.case_id)
        e.case_id,
        e.event_type,
        e.event_date,
        e.notes,
        e.metadata
    FROM public.enforcement_events AS e
    ORDER BY
        e.case_id ASC,
        e.event_date DESC,
        e.created_at DESC
),

case_rows AS (
    SELECT
        ec.id AS case_id,
        ec.judgment_id,
        ec.case_number,
        ec.opened_at,
        ec.current_stage,
        ec.status,
        ec.assigned_to,
        ec.metadata,
        ec.created_at,
        ec.updated_at,
        j.judgment_amount,
        j.case_number AS judgment_case_number,
        j.plaintiff_id,
        p.name AS plaintiff_name
    FROM public.enforcement_cases AS ec
    INNER JOIN public.judgments AS j ON ec.judgment_id = j.id
    LEFT JOIN public.plaintiffs AS p ON j.plaintiff_id = p.id
)

SELECT
    cr.case_id,
    cr.judgment_id,
    cr.opened_at,
    cr.current_stage,
    cr.status,
    cr.assigned_to,
    cr.metadata,
    cr.created_at,
    cr.updated_at,
    cr.judgment_amount,
    cr.plaintiff_id,
    cr.plaintiff_name,
    le.event_type AS latest_event_type,
    le.event_date AS latest_event_date,
    le.notes AS latest_event_note,
    le.metadata AS latest_event_metadata,
    coalesce(cr.case_number, cr.judgment_case_number) AS case_number
FROM case_rows AS cr
LEFT JOIN latest_event AS le ON cr.case_id = le.case_id;
CREATE OR REPLACE VIEW public.v_enforcement_timeline AS
SELECT
    e.case_id,
    e.id AS source_id,
    'event'::text AS item_kind,
    e.event_date AS occurred_at,
    e.event_type AS title,
    e.notes AS details,
    NULL::text AS storage_path,
    NULL::text AS file_type,
    NULL::text AS uploaded_by,
    e.metadata,
    e.created_at
FROM public.enforcement_events AS e
UNION ALL
SELECT
    f.case_id,
    f.id AS source_id,
    'evidence'::text AS item_kind,
    coalesce(f.created_at, timezone('utc', now())) AS occurred_at,
    coalesce(f.file_type, 'evidence') AS title,
    NULL::text AS details,
    f.storage_path,
    f.file_type,
    f.uploaded_by,
    f.metadata,
    f.created_at
FROM public.evidence_files AS f;
GRANT SELECT ON public.v_enforcement_case_summary TO anon,
authenticated,
service_role;
GRANT SELECT ON public.v_enforcement_timeline TO anon,
authenticated,
service_role;
COMMIT;
