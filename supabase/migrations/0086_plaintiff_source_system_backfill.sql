ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS source_system text;
UPDATE public.plaintiffs
SET source_system = COALESCE(NULLIF(source_system, ''), 'unknown')
WHERE
    source_system IS NULL
    OR BTRIM(source_system) = '';
ALTER TABLE public.plaintiffs
ALTER COLUMN source_system
SET DEFAULT 'unknown';
