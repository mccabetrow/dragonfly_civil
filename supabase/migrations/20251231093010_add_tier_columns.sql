-- 20251231093010_add_tier_columns.sql
-- ============================================================================
-- Add tier columns to public.judgments for collectability scoring
-- ============================================================================
-- The collectability worker needs these columns to store tier classification
-- in addition to the numeric score.
-- ============================================================================
-- Add tier column (A, B, C classification)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'tier'
) THEN
ALTER TABLE public.judgments
ADD COLUMN tier TEXT;
RAISE NOTICE 'Added tier column to public.judgments';
ELSE RAISE NOTICE 'tier column already exists on public.judgments';
END IF;
END $$;
-- Add tier_reason column (human-readable explanation)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'tier_reason'
) THEN
ALTER TABLE public.judgments
ADD COLUMN tier_reason TEXT;
RAISE NOTICE 'Added tier_reason column to public.judgments';
ELSE RAISE NOTICE 'tier_reason column already exists on public.judgments';
END IF;
END $$;
-- Add tier_as_of column (timestamp when tier was computed)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'tier_as_of'
) THEN
ALTER TABLE public.judgments
ADD COLUMN tier_as_of TIMESTAMPTZ;
RAISE NOTICE 'Added tier_as_of column to public.judgments';
ELSE RAISE NOTICE 'tier_as_of column already exists on public.judgments';
END IF;
END $$;
-- Add constraint to validate tier values
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_judgments_tier_valid'
) THEN
ALTER TABLE public.judgments
ADD CONSTRAINT chk_judgments_tier_valid CHECK (
        tier IS NULL
        OR tier IN ('A', 'B', 'C')
    );
RAISE NOTICE 'Added tier validation constraint';
ELSE RAISE NOTICE 'tier validation constraint already exists';
END IF;
END $$;
-- Add index on tier for dashboard filtering
CREATE INDEX IF NOT EXISTS idx_judgments_tier ON public.judgments (tier)
WHERE tier IS NOT NULL;
COMMENT ON COLUMN public.judgments.tier IS 'Collectability tier: A (high value + recent), B (mid-tier), C (low priority)';
COMMENT ON COLUMN public.judgments.tier_reason IS 'Human-readable explanation of how tier was computed';
COMMENT ON COLUMN public.judgments.tier_as_of IS 'Timestamp when tier/score was last computed';
DO $$ BEGIN RAISE NOTICE '✅ Tier columns added to public.judgments';
END $$;
