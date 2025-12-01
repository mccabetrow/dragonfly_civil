# Simplicity → Supabase Importer Runbook

## 1. Overview

- The Simplicity exporter hands us CSV or JSON files containing plaintiff, case, judgment, and contact info. Running the importer writes those rows into the canonical Supabase tables: `public.plaintiffs`, `public.plaintiff_contacts`, `judgments.cases`, and `judgments.judgments`.
- Every import creates a corresponding row in `public.import_runs`. That record stores the file name, source system, row counts, and a `status` (`running`, `completed`, or `failed`). It is the first place to look if you need to confirm what happened.
- The importer is idempotent: re-running the exact same file with the same `source_system` updates existing rows rather than duplicating them. This keeps the pipeline safe for corrections and QA reruns.

## 2. File Preparation

- Save Simplicity exports under `data/simplicity/` (or another clearly labeled folder checked into the repo’s `.gitignore`). Keeping a predictable location avoids mixups between dev and prod assets.
- Accepted formats:
  - CSV (UTF-8 with headers).
  - JSON (top-level list or `{ "rows": [...] }`).
- Required columns, regardless of format:
  - `LeadID`, `Court`, `IndexNumber`, `JudgmentDate`, `JudgmentAmount`.
  - `County`, `State`, `PlaintiffName`, `PlaintiffAddress` (street/city/state/zip if available).
  - `Phone`, `Email`, `BestContactMethod` (used for plaintiff contacts).
- Suggested naming pattern: `simplicity_<batch>_<yyyymmdd>.csv` (e.g., `simplicity_jbi900_20251122.csv`). This lines up nicely with `source_system` labels and Supabase audit trails.

## 3. Running an Import in Dev

1. Point all tooling at the dev Supabase project:
   ```powershell
   $env:SUPABASE_MODE = 'dev'
   ```
2. Run the importer module with an explicit source system:
   ```powershell
   python -m etl.simplicity_importer.import_simplicity "data/simplicity/simplicity_sample.csv" --source-system "simplicity_test"
   ```
3. Expected console output:
   - `[simplicity importer] planning import` (shows path + source system).
   - `[simplicity importer] loaded X rows`.
   - A final `[simplicity importer] import completed` plus inserted/updated/skipped counts.
4. Verify the results in Supabase:
   - `public.import_runs`: a new row with `source_system = 'simplicity_test'` and `status = 'completed'`. The `inserted_rows`, `skipped_rows`, and `metadata.updated_rows` fields should match the console totals.
   - `public.plaintiffs`: filter by `source_system = 'simplicity_test'` to see the new plaintiffs.
   - `judgments.cases` / `judgments.judgments`: filter by the same `source_system` to confirm case + judgment rows.
   - Views like `v_plaintiffs_overview` or `v_plaintiff_call_queue` should now include the imported plaintiffs (after row-level security refresh).

## 4. Running an Import in Prod (High-Level)

> ⚠️ Only authorized operators should touch production. Always complete the dev dry run and checklist before touching prod.

1. Target prod credentials:
   ```powershell
   $env:SUPABASE_MODE = 'prod'
   ```
2. Run the prod readiness script (config + security + doctor + pytest):
   ```powershell
   ./scripts/preflight_prod.ps1
   ```
3. Execute the importer with the prod source system (example uses the JBI 900 batch label):
   ```powershell
   python -m etl.simplicity_importer.import_simplicity "\\path\to\finalized\simplicity_batch.csv" --source-system "simplicity_jbi_900"
   ```
4. Post-run checklist:
   - Confirm the new `import_runs` row shows `status = 'completed'` and the expected row counts.
   - Spot-check plaintiffs/cases/judgments via Supabase SQL or Metabase dashboards.
   - Notify stakeholders (ops + engineering) that the batch finished and include the `import_run_id` for traceability.

## 5. Idempotency and Re-Runs

- The importer uses deterministic keys (lead IDs / case numbers / judgment numbers / contact info) so re-running a file with the same `source_system` updates the original rows. No duplicates are created for plaintiffs, cases, judgments, or contacts.
- Safe re-run scenarios:
  - You fixed a typo in the CSV header or cleaned a bad date locally.
  - Engineering patched the importer logic and asked you to replay the same dev batch for verification.
- Call engineering before re-running if:
  - The batch is large (hundreds+ rows) **and** destined for production.
  - You plan to change the `source_system` label (that would create new rows and should be intentional).

## 6. Troubleshooting

- **`import_runs.status = 'failed'`**
  - Check `metadata.error` (the importer writes the exception message there).
  - Inspect the CSV around the failing row for missing required columns, malformed dates, or blank amounts.
  - Try rerunning a trimmed version (e.g., the first 10 rows) in dev to isolate the issue.
- **Numbers look off in dashboards**
  - Confirm the `source_system` filter being used (dashboards often scope to active campaigns).
  - Verify that all rows show up in `public.plaintiffs` and `judgments.cases`. If counts differ, re-check the raw export for duplicates or missing case numbers.
  - If discrepancies persist, capture the `import_run_id`, sample row IDs, and escalate to engineering with screenshots/logs.

---

Need help? Ping the Dragonfly engineering channel with the file name, `source_system`, and the `import_run_id` so we can dig into logs quickly.
