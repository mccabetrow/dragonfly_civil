# Importer Runbook

This guide covers the Simplicity + JBI CSV importer suite that lands plaintiffs and judgments into Supabase while wiring contacts, follow-up tasks, enforcement stages, and downstream queue jobs.

## Pipeline overview

1. **CSV validation** – `parse_simplicity_csv` / `parse_jbi_900_csv` normalize vendor exports into the shared `SimplicityImportRow` model and record any parse issues in `LAST_PARSE_ERRORS`.
2. **Import run bookkeeping** – successful (non–dry-run) executions create an `import_runs` row that tracks batch metadata, storage path, counters, and the final summary payload returned by the importer.
3. **Storage upload** – the raw CSV is uploaded to the `imports` Supabase bucket for auditing.
4. **Raw ingestion log** – each processed row (including parse failures when the table exists) is copied into `public.raw_simplicity_imports` or its fallback table so we always retain the original payload and status.
5. **Plaintiff/judgment upsert** – the importer de-dupes by email/phone/name, inserts judgments, and logs plaintiff status history entries referencing the batch.
6. **Contact hydration** – `ContactSync` enforces one primary contact per plaintiff (phone/email) and an address record so outreach + dashboards have consistent data.
7. **Follow-up tasks** – `ensure_follow_up_task` adds an open `'call'` task when one does not already exist to keep Ops queues populated.
8. **Enforcement stage initialization** – `initialize_enforcement_stage` sets `pre_enforcement` via `public.set_enforcement_stage` (or updates the column directly if the RPC is missing).
9. **Queue jobs** – each inserted judgment enqueues `enrich` and `enforce` jobs through the `queue_job` RPC (unless `--skip-jobs` is passed or the RPC is unavailable). Message ids are stored in `metadata.queued_jobs` and per-row `queued_jobs` entries.

## Running the importer

Use the shared CLI: `python -m tools.run_import`.

```
usage: python -m tools.run_import --source {simplicity,jbi} --csv <file> [options]

optional arguments:
  --batch-name TEXT        Label stored in import_runs (defaults to CSV stem)
  --source-reference TEXT  External reference (defaults to batch name)
  --commit                 Apply changes (omit for dry-run mode)
  --skip-jobs              Skip queue_job RPC calls (handy for dev dry-runs)
  --pretty                 Pretty-print JSON output
```

Examples:

- Dry-run Simplicity sample: `python -m tools.run_import --source simplicity --csv data_in/simplicity_sample.csv --batch-name dev-simplicity --skip-jobs --pretty`
- Commit JBI import: `python -m tools.run_import --source jbi --csv data/jbi_export_valid_sample.csv --batch-name jbi-prod-2024-05-01 --commit`

Two VS Code tasks (`Importer: Simplicity (Dry Run)` and `Importer: JBI (Dry Run)`) wrap these commands with project defaults.

## Result metadata

The importer returns a JSON document with:

- `metadata.row_operations` – per-row action status, plaintiff/judgment ids, follow-up task info, contact insert counts, enforcement init flag, queued job metadata, and the raw import id (when the staging table is available).
- `metadata.raw_import_log` – summary of staging table writes (`enabled`, `table`, `rows_written`, and any failures if the table is missing).
- `metadata.contact_inserts`, `metadata.follow_up_tasks`, `metadata.enforcement_initializations` – aggregate counters mirrored into `import_runs.metadata.summary`.
- `metadata.queued_jobs` – flattened list of every queue_job attempt so watchers/tests can delete pgmq messages after verification.

Parse errors always bubble up in `metadata.parse_errors`. When the raw ingest table exists each failure will also include `raw_import_id` so data quality teams can inspect the JSON payload.

## Post-run verification

1. **Doctor + smoke** – after committing imports run `python -m tools.doctor --env dev` (or prod) and `python -m tools.smoke_plaintiffs` to confirm visibility of new rows.
2. **Queue cleanup for tests/dev** – integration tests call `_cleanup_queue_jobs` to delete pgmq messages using `public.pgmq_delete`. If you run the importer manually in dev and do not want workers picking up jobs yet, delete the queued message ids surfaced in the CLI output (`metadata.queued_jobs`).
3. **Manual spot checks** – query `public.plaintiff_contacts`, `public.plaintiff_tasks`, and `public.judgments` to confirm contact counts, open `'call'` tasks, and `enforcement_stage = 'pre_enforcement'` for the new judgments.
4. **Import history** – `select id, status, row_count, error_count from public.import_runs order by started_at desc limit 10;` provides a quick view of recent batches.

## Testing

`pytest tests/test_import_plaintiffs.py -q` exercises:

- Dry-run metadata (planned storage paths) for both importers
- Parse-error persistence & raw log wiring
- Full ingest path including contact creation, follow-up tasks, enforcement stage, queue job metadata, and cleanup hooks

Run this suite locally after modifying importer logic to catch regressions before shipping to Supabase.
