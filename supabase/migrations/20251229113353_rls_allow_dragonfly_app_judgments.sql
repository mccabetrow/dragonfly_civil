-- Migration: Allow dragonfly_app role to insert into judgments
-- Description: Add RLS policy for the application role to insert demo data
-- ============================================================================
-- Create policy allowing dragonfly_app to insert into judgments
CREATE POLICY IF NOT EXISTS "Allow dragonfly_app insert" ON public.judgments FOR
INSERT TO dragonfly_app WITH CHECK (true);
-- Also ensure dragonfly_app can update (for future use)
CREATE POLICY IF NOT EXISTS "Allow dragonfly_app update" ON public.judgments FOR
UPDATE TO dragonfly_app USING (true) WITH CHECK (true);