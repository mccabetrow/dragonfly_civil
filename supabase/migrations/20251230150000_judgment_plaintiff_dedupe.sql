-- 20251230150000_judgment_plaintiff_dedupe.sql
-- Strengthen judgment + plaintiff dedupe semantics with deterministic keys
-- and ON CONFLICT-based RPCs that surface inserted vs reused rows.
-- ============================================================================
DROP FUNCTION IF EXISTS public.normalize_party_name(TEXT);
CREATE FUNCTION public.normalize_party_name(p_name TEXT) RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v_name TEXT;
BEGIN IF p_name IS NULL THEN RETURN NULL;
END IF;
v_name := upper(trim(p_name));
IF v_name = '' THEN RETURN NULL;
END IF;
v_name := regexp_replace(
    v_name,
    '\\s+(LLC|INC|CORP|CO|LTD)\\.?$',
    '',
    'gi'
);
v_name := regexp_replace(v_name, '\\s+', ' ', 'g');
RETURN v_name;
END;
$$;
COMMENT ON FUNCTION public.normalize_party_name(TEXT) IS 'Uppercase + whitespace normalized name with corporate suffixes trimmed.';
DROP FUNCTION IF EXISTS public.compute_judgment_dedupe_key(TEXT, TEXT);
CREATE FUNCTION public.compute_judgment_dedupe_key(
    p_case_number TEXT,
    p_defendant_name TEXT
) RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v_case TEXT;
v_def TEXT;
BEGIN IF p_case_number IS NULL THEN RETURN NULL;
END IF;
v_case := upper(trim(p_case_number));
IF v_case = '' THEN RETURN NULL;
END IF;
v_def := public.normalize_party_name(p_defendant_name);
IF v_def IS NULL THEN RETURN v_case;
END IF;
RETURN v_case || '|' || v_def;
END;
$$;
COMMENT ON FUNCTION public.compute_judgment_dedupe_key(TEXT, TEXT) IS 'Deterministic dedupe key: UPPER(case)#|NORMALIZED(defendant).';
-- ============================================================================
-- 2. Rebuild plaintiff dedupe column + unique constraint
-- ============================================================================
DROP INDEX IF EXISTS idx_plaintiffs_dedupe_key;
ALTER TABLE public.plaintiffs DROP COLUMN IF EXISTS dedupe_key;
ALTER TABLE public.plaintiffs
ADD COLUMN dedupe_key TEXT GENERATED ALWAYS AS (public.normalize_party_name(name)) STORED;
DO $$
DECLARE fk_rec RECORD;
dup_count BIGINT;
BEGIN CREATE TEMP TABLE tmp_plaintiff_dedupe AS
SELECT id,
    dedupe_key,
    FIRST_VALUE(id) OVER (
        PARTITION BY dedupe_key
        ORDER BY id
    ) AS canonical_id,
    ROW_NUMBER() OVER (
        PARTITION BY dedupe_key
        ORDER BY id
    ) AS rn
FROM public.plaintiffs
WHERE dedupe_key IS NOT NULL;
SELECT COUNT(*) INTO dup_count
FROM tmp_plaintiff_dedupe
WHERE rn > 1;
IF dup_count > 0 THEN FOR fk_rec IN
SELECT conrelid::regclass AS table_name,
    (
        SELECT attname
        FROM pg_attribute
        WHERE attrelid = c.conrelid
            AND attnum = c.conkey [1]
    ) AS column_name
FROM pg_constraint c
WHERE c.confrelid = 'public.plaintiffs'::regclass
    AND c.contype = 'f'
    AND array_length(c.conkey, 1) = 1 LOOP EXECUTE format(
        'UPDATE %s AS t
                 SET %I = map.canonical_id
                 FROM tmp_plaintiff_dedupe AS map
                 WHERE map.rn > 1 AND t.%I = map.id',
        fk_rec.table_name,
        fk_rec.column_name,
        fk_rec.column_name
    );
END LOOP;
DELETE FROM public.plaintiffs p USING tmp_plaintiff_dedupe map
WHERE map.rn > 1
    AND p.id = map.id;
END IF;
DROP TABLE IF EXISTS tmp_plaintiff_dedupe;
END;
$$;
CREATE UNIQUE INDEX idx_plaintiffs_dedupe_key ON public.plaintiffs (dedupe_key);
COMMENT ON COLUMN public.plaintiffs.dedupe_key IS 'Deterministic dedupe key derived from normalized plaintiff name.';
-- ============================================================================
-- 3. Add judgment dedupe column + unique index
-- ============================================================================
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS dedupe_key TEXT GENERATED ALWAYS AS (
        public.compute_judgment_dedupe_key(case_number, defendant_name)
    ) STORED;
CREATE UNIQUE INDEX IF NOT EXISTS idx_judgments_dedupe_key ON public.judgments (dedupe_key);
COMMENT ON COLUMN public.judgments.dedupe_key IS 'Deterministic dedupe key: UPPER(case_number)|NORMALIZED(defendant).';
-- ============================================================================
-- 4. RPCs: ON CONFLICT-powered insert_or_get_* helpers
-- ============================================================================
DROP FUNCTION IF EXISTS public.insert_or_get_plaintiff(TEXT, TEXT, UUID, INTEGER, TEXT);
CREATE OR REPLACE FUNCTION public.insert_or_get_plaintiff(
        p_name TEXT,
        p_source_system TEXT DEFAULT NULL,
        p_source_batch_id UUID DEFAULT NULL,
        p_source_row_index INTEGER DEFAULT NULL,
        p_source_file_hash TEXT DEFAULT NULL
    ) RETURNS TABLE (id BIGINT, was_inserted BOOLEAN) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_name TEXT;
v_key TEXT;
v_source_reference TEXT;
BEGIN v_name := NULLIF(trim(p_name), '');
IF v_name IS NULL THEN RAISE EXCEPTION 'Plaintiff name is required for insert_or_get_plaintiff';
END IF;
v_key := public.normalize_party_name(v_name);
v_source_reference := CASE
    WHEN p_source_batch_id IS NOT NULL THEN CONCAT_WS(':', p_source_system, p_source_batch_id::text)
    ELSE p_source_system
END;
RETURN QUERY WITH inserted AS (
    INSERT INTO public.plaintiffs (
            name,
            status,
            metadata,
            source_system,
            source_reference,
            source_batch_id,
            source_row_index,
            source_file_hash,
            first_ingested_at
        )
    VALUES (
            v_name,
            'intake_pending',
            '{}'::jsonb,
            p_source_system,
            v_source_reference,
            p_source_batch_id,
            p_source_row_index,
            p_source_file_hash,
            timezone('utc', now())
        ) ON CONFLICT (dedupe_key) DO NOTHING
    RETURNING id
)
SELECT id,
    true
FROM inserted
UNION ALL
SELECT pl.id,
    false
FROM public.plaintiffs pl
WHERE pl.dedupe_key = v_key
LIMIT 1;
END;
$$;
COMMENT ON FUNCTION public.insert_or_get_plaintiff(TEXT, TEXT, UUID, INTEGER, TEXT) IS 'Idempotently find or create a plaintiff based on normalized name dedupe key.';
GRANT EXECUTE ON FUNCTION public.insert_or_get_plaintiff(TEXT, TEXT, UUID, INTEGER, TEXT) TO service_role;
DROP FUNCTION IF EXISTS public.insert_or_get_judgment(
    TEXT,
    TEXT,
    TEXT,
    NUMERIC,
    DATE,
    TEXT,
    TEXT,
    TEXT,
    BIGINT
);
CREATE OR REPLACE FUNCTION public.insert_or_get_judgment(
        p_case_number TEXT,
        p_plaintiff_name TEXT DEFAULT NULL,
        p_defendant_name TEXT DEFAULT NULL,
        p_judgment_amount NUMERIC DEFAULT NULL,
        p_entry_date DATE DEFAULT NULL,
        p_court TEXT DEFAULT NULL,
        p_county TEXT DEFAULT NULL,
        p_source_file TEXT DEFAULT NULL,
        p_plaintiff_id BIGINT DEFAULT NULL
    ) RETURNS TABLE (id BIGINT, was_inserted BOOLEAN) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_case_number TEXT;
v_plaintiff TEXT;
v_defendant TEXT;
v_court TEXT;
v_county TEXT;
v_key TEXT;
BEGIN v_case_number := NULLIF(upper(trim(p_case_number)), '');
IF v_case_number IS NULL THEN RAISE EXCEPTION 'case_number is required for insert_or_get_judgment';
END IF;
v_plaintiff := NULLIF(trim(p_plaintiff_name), '');
v_defendant := NULLIF(trim(p_defendant_name), '');
v_court := NULLIF(trim(p_court), '');
v_county := NULLIF(trim(p_county), '');
v_key := public.compute_judgment_dedupe_key(v_case_number, v_defendant);
RETURN QUERY WITH inserted AS (
    INSERT INTO public.judgments (
            case_number,
            plaintiff_name,
            defendant_name,
            judgment_amount,
            entry_date,
            court,
            county,
            source_file,
            status,
            enforcement_stage,
            created_at,
            updated_at,
            plaintiff_id
        )
    VALUES (
            v_case_number,
            v_plaintiff,
            v_defendant,
            p_judgment_amount,
            p_entry_date,
            v_court,
            v_county,
            p_source_file,
            'active',
            'pre_enforcement',
            NOW(),
            NOW(),
            p_plaintiff_id
        ) ON CONFLICT (dedupe_key) DO NOTHING
    RETURNING id
)
SELECT id,
    true
FROM inserted
UNION ALL
SELECT j.id,
    false
FROM public.judgments j
WHERE j.dedupe_key = v_key
LIMIT 1;
END;
$$;
COMMENT ON FUNCTION public.insert_or_get_judgment(
    TEXT,
    TEXT,
    TEXT,
    NUMERIC,
    DATE,
    TEXT,
    TEXT,
    TEXT,
    BIGINT
) IS 'Idempotent judgment upsert keyed by case_number + normalized defendant (dedupe_key).';
GRANT EXECUTE ON FUNCTION public.insert_or_get_judgment(
        TEXT,
        TEXT,
        TEXT,
        NUMERIC,
        DATE,
        TEXT,
        TEXT,
        TEXT,
        BIGINT
    ) TO service_role;
-- ============================================================================
-- 5. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';