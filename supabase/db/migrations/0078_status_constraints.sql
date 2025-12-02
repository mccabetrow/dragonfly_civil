-- 0078_status_constraints.sql
-- Enforce canonical status and enforcement stage values while repairing legacy data.

-- migrate:up

WITH allowable_plaintiff_status AS (
    SELECT ARRAY[
        'new',
        'contacted',
        'qualified',
        'sent_agreement',
        'signed',
        'lost'
    ] AS values
)

UPDATE public.plaintiffs p
SET status = 'new'
FROM allowable_plaintiff_status AS als
WHERE
    p.status IS NULL
    OR btrim(lower(p.status)) = ''
    OR btrim(lower(p.status)) NOT IN (SELECT unnest(als.values));

WITH allowable_enforcement_stage AS (
    SELECT ARRAY[
        'pre_enforcement',
        'paperwork_filed',
        'levy_issued',
        'waiting_payment',
        'collected_partially',
        'collected_paid'
    ] AS values
)

UPDATE public.judgments j
SET enforcement_stage = 'pre_enforcement'
FROM allowable_enforcement_stage AS aes
WHERE
    j.enforcement_stage IS NULL
    OR btrim(lower(j.enforcement_stage)) = ''
    OR btrim(lower(j.enforcement_stage)) NOT IN (SELECT unnest(aes.values));

DO $$
DECLARE
    existing_constraint text;
BEGIN
    SELECT conname
    INTO existing_constraint
    FROM pg_constraint
    WHERE conrelid = 'public.plaintiffs'::regclass
      AND contype = 'c'
      AND conname IN ('plaintiffs_status_check', 'plaintiffs_status_allowed');

    IF existing_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.plaintiffs DROP CONSTRAINT %I', existing_constraint);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.plaintiffs'::regclass
          AND contype = 'c'
          AND conname = 'plaintiffs_status_allowed'
    ) THEN
        ALTER TABLE public.plaintiffs
            ADD CONSTRAINT plaintiffs_status_allowed
            CHECK (status IN (
                'new',
                'contacted',
                'qualified',
                'sent_agreement',
                'signed',
                'lost'
            ));
    END IF;
END
$$;

DO $$
DECLARE
    existing_constraint text;
BEGIN
    SELECT conname
    INTO existing_constraint
    FROM pg_constraint
    WHERE conrelid = 'public.judgments'::regclass
      AND contype = 'c'
      AND conname IN ('judgments_enforcement_stage_check', 'judgments_enforcement_stage_allowed');

    IF existing_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE public.judgments DROP CONSTRAINT %I', existing_constraint);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.judgments'::regclass
          AND contype = 'c'
          AND conname = 'judgments_enforcement_stage_allowed'
    ) THEN
        ALTER TABLE public.judgments
            ADD CONSTRAINT judgments_enforcement_stage_allowed
            CHECK (
                enforcement_stage IS NULL
                OR enforcement_stage IN (
                    'pre_enforcement',
                    'paperwork_filed',
                    'levy_issued',
                    'waiting_payment',
                    'collected_partially',
                    'collected_paid'
                )
            );
    END IF;
END
$$;

-- migrate:down

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.plaintiffs'::regclass
          AND contype = 'c'
          AND conname = 'plaintiffs_status_allowed'
    ) THEN
        ALTER TABLE public.plaintiffs
            DROP CONSTRAINT plaintiffs_status_allowed;
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.judgments'::regclass
          AND contype = 'c'
          AND conname = 'judgments_enforcement_stage_allowed'
    ) THEN
        ALTER TABLE public.judgments
            DROP CONSTRAINT judgments_enforcement_stage_allowed;
    END IF;
END
$$;

-- Allowed plaintiffs.status: new, contacted, qualified, sent_agreement, signed, lost.
-- Allowed judgments.enforcement_stage: pre_enforcement, paperwork_filed, levy_issued, waiting_payment, collected_partially, collected_paid.
