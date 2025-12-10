-- Test SQL: Insert a sample ingest_csv job
-- Run this AFTER the migration has been applied
--
-- Prerequisites:
--   1. Apply migration: 20251209125818_add_ingest_csv_job_type.sql
--   2. Upload a test CSV to Supabase Storage bucket 'intake'
--   3. Create a corresponding ingest_batches record
-- Step 1: Create an ingest batch record
INSERT INTO ops.ingest_batches (
        id,
        source,
        filename,
        row_count_raw,
        status,
        created_at
    )
VALUES (
        'test-batch-001',
        'manual_test',
        'test_batch.csv',
        10,
        'pending',
        NOW()
    ) ON CONFLICT (id) DO NOTHING;
-- Step 2: Queue an ingest job
INSERT INTO ops.job_queue (
        id,
        job_type,
        payload,
        status,
        attempts,
        created_at
    )
VALUES (
        gen_random_uuid(),
        'ingest_csv',
        jsonb_build_object(
            'batch_id',
            'test-batch-001',
            'file_path',
            'intake/test_batch.csv',
            'source',
            'manual_test'
        ),
        'pending',
        0,
        NOW()
    );
-- Verify the job was created
SELECT id,
    job_type,
    payload,
    status,
    created_at
FROM ops.job_queue
WHERE job_type = 'ingest_csv'
ORDER BY created_at DESC
LIMIT 5;