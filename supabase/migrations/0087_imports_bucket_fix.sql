-- Clean up the legacy imports bucket metadata rows; bucket provisioning now
-- happens via tools.ensure_storage_buckets which calls the Supabase Storage API.
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'storage'
        AND table_name = 'buckets'
) THEN
DELETE FROM storage.buckets
WHERE name = 'imports';
END IF;
END;
$$;

