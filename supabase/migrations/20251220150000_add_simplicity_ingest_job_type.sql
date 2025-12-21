-- Migration: Add 'simplicity_ingest' to ops.job_type_enum
-- Author: Dragonfly Engine
-- Date: 2025-12-20
--
-- This migration extends the job_type_enum to support Simplicity CSV ingestion jobs
-- processed by the simplicity_ingest_worker.
-- Add the new enum value
ALTER TYPE ops.job_type_enum
ADD VALUE IF NOT EXISTS 'simplicity_ingest';
COMMENT ON TYPE ops.job_type_enum IS 'Job types: enrich_tlo, enrich_idicore, generate_pdf, ingest_csv, enforcement_strategy, enforcement_drafting, enforcement_generate_packet, simplicity_ingest';