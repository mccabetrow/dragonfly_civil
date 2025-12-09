# Dragonfly Quickstart

<!-- CI/CD: production_deploy workflow triggers on push to main -->

1. Activate a virtual environment:
   - Windows: `python -m venv .venv && .\.venv\Scripts\Activate.ps1`
   - macOS/Linux: `python -m venv .venv && source .venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in values (no quotes).
4. Generate a session key if needed later:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
5. Run the Supabase smoke test: `make smoke`
6. Drop CSV files containing a `case_number` column into `data_in/`.
7. Start the ingestion watcher: `make watcher`
8. Watch the logs to confirm processing and Supabase uploads.
9. Confirm processed files move to `data_processed/` (errors land in `data_error/`).
10. Run `supabase db push` only when you add or change migrations.

## n8n Workflow Stub

1. Open the n8n editor and go to **Settings → Import**.
2. Choose `n8n/flows/ingestion_stub.json` and import the workflow.
3. Replace the placeholder Supabase URL and keys in the HTTP Request node with environment references or credentials (do not hard-code secrets).
4. Set up n8n credentials for Supabase with the service role key and update the node to use them.
5. Activate the workflow once your Supabase project values are configured.

## Runbook: Handling `data_error/` Files

- **Investigate**: Open the accompanying `.err.json` file in `data_error/` to review the failure reason and the chunk preview.
- **Fix**: Correct the CSV source data (or adjust schema/transforms) so the problematic rows conform to expected types.
- **Reprocess**: Delete the file’s SHA-256 entry from `state/manifest.jsonl`, place the corrected CSV back into `data_in/`, and rerun the watcher (or invoke `python judgment_ingestor/main.py --once --interval 0`).
- **Verify**: Confirm the file moves to `data_processed/` and the manifest records the new hash.

## CI / One-Off Runs

- To process the current queue once in CI or a local pipeline without polling, run: `python judgment_ingestor/main.py --once --interval 0`

## Schema Changes Checklist

- Update column mappings or defaults in `config/schema_map.yaml` whenever the external CSV schema evolves.
- Add corresponding Supabase migrations under `supabase/migrations/` (and `supabase/schema.sql` if needed) before pushing database changes.
