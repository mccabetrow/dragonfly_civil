-- Migration: Add 'ingest_csv' to ops.job_type_enum
-- Author: Dragonfly Engine
-- Date: 2025-12-09
--
-- This migration extends the job_type_enum to support CSV ingestion jobs
-- processed by the ingest_processor worker.
-- Add the new enum value
ALTER TYPE ops.job_type_enum
ADD VALUE IF NOT EXISTS 'ingest_csv';
-- Note: ALTER TYPE ... ADD VALUE cannot run inside a transaction block
-- in Postgres < 12, but Supabase typically runs 14+, so this is safe.
COMMENT ON TYPE ops.job_type_enum IS 'Job types for async processing: enrich_tlo, enrich_idicore, generate_pdf, ingest_csv';
