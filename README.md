# Dragonfly Civil

> **Judgment-Enforcement Operating System**

<!-- CI/CD: production_deploy workflow triggers on push to main -->

---

## 📂 System Architecture & Repository Structure

Dragonfly is organized into **4 Planes** with strict separation of concerns:

| Plane          | Responsibility  | Directory                                  | Technology                         |
| -------------- | --------------- | ------------------------------------------ | ---------------------------------- |
| **Data**       | Source of Truth | `supabase/`                                | Postgres, RLS, Migrations          |
| **Service**    | Business Logic  | `backend/`, `etl/`, `workers/`, `brain/`   | Python, FastAPI, Railway           |
| **Experience** | User Interface  | `dragonfly-dashboard/`                     | React, TypeScript, Vercel          |
| **Ops**        | Reliability     | `scripts/`, `tools/`, `.github/workflows/` | PowerShell, Python, GitHub Actions |

```
dragonfly_civil/
├── supabase/           # DATA PLANE - Migrations, schema
├── backend/            # SERVICE PLANE - FastAPI, workers
├── etl/                # SERVICE PLANE - Ingestion pipelines
├── workers/            # SERVICE PLANE - Background jobs
├── brain/              # SERVICE PLANE - Scoring & escalation
├── dragonfly-dashboard/# EXPERIENCE PLANE - React frontend
├── scripts/            # OPS PLANE - PowerShell automation
├── tools/              # OPS PLANE - Python tooling & gates
├── .github/workflows/  # OPS PLANE - CI/CD pipelines
└── docs/               # OPS PLANE - Documentation
```

📖 **Full Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
📋 **Decision Records:** [docs/decisions/](docs/decisions/)

---

## Quickstart

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
