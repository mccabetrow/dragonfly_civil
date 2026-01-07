-- 0078_status_constraints.sql
-- Enforce canonical status and enforcement stage values while repairing legacy data.

-- migrate:up

with allowable_plaintiff_status as (
    select array[
        'new',
        'contacted',
        'qualified',
        'sent_agreement',
        'signed',
        'lost'
    ] as values
)

update public.plaintiffs p
set status = 'new'
from allowable_plaintiff_status as als
where
    p.status is NULL
    or btrim(lower(p.status)) = ''
    or btrim(lower(p.status)) not in (select unnest(als.values));

with allowable_enforcement_stage as (
    select array[
        'pre_enforcement',
        'paperwork_filed',
        'levy_issued',
        'waiting_payment',
        'collected_partially',
        'collected_paid'
    ] as values
)

update public.judgments j
set enforcement_stage = 'pre_enforcement'
from allowable_enforcement_stage as aes
where
    j.enforcement_stage is NULL
    or btrim(lower(j.enforcement_stage)) = ''
    or btrim(lower(j.enforcement_stage)) not in (select unnest(aes.values));

do $$
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

do $$
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

do $$
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

do $$
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

do $$
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

do $$
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
