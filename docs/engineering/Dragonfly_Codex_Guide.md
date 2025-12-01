# Dragonfly Codex Guide

This is a living field manual for human engineers and AI assistants collaborating on the Dragonfly Civil platform.

---

## Mission Statement

Dragonfly Civil helps New York judgment creditors lawfully locate assets, enforce CPLR Article 52 remedies, and return money to plaintiffs without wasting attorney time. Everything we build must keep judgment data accurate, defensible, and audit-ready.

---

## Current Stack Snapshot

- **Data platform**
  - Supabase/PostgreSQL managed schema (`supabase/migrations/**`, `supabase/schema.sql`, `supabase/db/migrations/**`).
  - Primary views for the dashboard in `dashboards/sql/**`.
- **Python estate**
  - Core runtime in `src/**`.
  - ETL pipelines in `etl/src/**` (notably `etl/src/collector_intel.py`, `etl/src/transforms.py`, `etl/src/plaintiff_vendor_adapter.py`).
  - Background workers and planners in `workers/**`, `planner/**`.
  - Operational tooling in `tools/**` (doctor, security audits, smoke tests).
- **Automation & orchestration**
  - n8n workflows stored in `n8n/flows/*.json` (import triggers, enforcement timeline updates, monitoring).
  - PowerShell automations in `scripts/*.ps1` (db push, preflight, deploy, watcher/worker runners).
- **Testing & quality gates**
  - pytest suite in `tests/**` and ETL tests in `etl/tests/**`.
  - Pre-commit hooks (configured at repo root) running black, ruff, isort, mypy, prettier, sqlfluff.
  - Doctor/security tooling invoked via `tools/doctor.py`, `tools/security_audit.py`, and aggregated in `scripts/preflight_*.ps1`.

---

## Core Data Domains

| Domain                             | Tables / Views                                                                                                                                                                         | Notes                                                                                                                                                          |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Judgments & Cases**              | `public.judgments`, `judgments.cases`, `judgments.parties`, `public.v_judgment_pipeline`, `public.v_enforcement_overview`                                                              | `judgments.cases` is canonical; `public.judgments` persists for legacy dashboards. Triggers in schema.sql enforce docket normalization and updated timestamps. |
| **Debtors & Plaintiffs**           | `public.plaintiffs`, `public.plaintiff_contacts`, `public.plaintiff_status_history`, `public.plaintiff_call_attempts`, `public.v_plaintiffs_overview`, `public.v_plaintiff_call_queue` | Simplicity importer writes here (`source_reference`, `lead_metadata`). Queue views drive call center workflows.                                                |
| **Enrichment & Intelligence**      | `public.enrichment_runs`, `public.collectability_snapshot`, `public.priority_pipeline`, `public.case_copilot_*`, metadata columns like `collectability_score`                          | Python ETL (`etl/src/collector_intel.py`, planners) and migrations 0053–0063/0129+/0142+ power scoring and dashboards.                                         |
| **Enforcement Actions & Payments** | `public.enforcement_cases`, `public.enforcement_timeline`, `public.plaintiff_tasks`, `public.enforcement_stage_*` RPCs, `public.ops_daily_summary`                                     | Created in migrations 0127–0140; timeline updater n8n flow and enforcement planner scripts maintain these records.                                             |

_When table names diverge from ideal nouns, treat the table listed above as the authoritative source for that domain._

---

## Legal & Compliance Constraints

- **CPLR Article 52 (NY)**
  - Governs post-judgment enforcement (levies, restraints, subpoenas). Automation must preserve audit trails for every action and keep debtor communications within statutory limits.
  - Asset restraints and subpoenas require attorney sign-off; code should surface `TODO: Attorney review required` wherever a human signature or court filing is triggered.
- **Judgment life cycle**
  - Money judgments are enforceable for **20 years** in NY (CPLR 211(b)).
  - Liens on real property last **10 years** and can be renewed once. Workflows should track renewal windows and never auto-expire data without counsel approval.
- **FDCPA / FCRA guardrails**
  - No deceptive or misleading communications; keep call/task automation respectful and opt-out aware.
  - Credit data, if touched, must follow permissible purpose and dispute handling procedures. Automations should log consumer interactions and never alter credit-reporting fields without manual review.
- **Data retention & PII**
  - Encrypt sensitive exports, redact where possible, and avoid dumping PII into logs/alerts. Use `src/auth/crypto.py` helpers instead of rolling custom encryption.

---

## Coding & Migration Conventions

- **Migrations**
  - Production migrations live in `supabase/migrations/NNNN_description.sql`; naming uses zero-padded integers plus descriptive slug.
  - Hotfix diffs created via Supabase CLI land in `supabase/db/migrations/` using similar numbering.
  - Favor additive changes (`ADD COLUMN IF NOT EXISTS`, `CREATE OR REPLACE VIEW`). Never drop/truncate tables without explicit partner instruction.
  - Update `supabase/schema.sql` after meaningful migration batches using `scripts/reload_schema.ps1`.
- **Deployment workflow**
  - Run `scripts/load_env.ps1` to hydrate secrets, then `scripts/preflight_dev.ps1` or `scripts/preflight_prod.ps1` (config checks + doctor + pytest).
  - Apply schema with `scripts/db_push.ps1` (respects `SUPABASE_MODE`).
  - Post-migration, reload PostgREST (`scripts/bootstrap.ps1 -Mode reload`) and run verifiers (`python -m tools.doctor`, `python -m tools.smoke_plaintiffs`).
- **Testing**
  - Python unit tests: `.\\.venv\\Scripts\\python.exe -m pytest -q` or targeted paths.
  - ETL integration tests live in `etl/tests/**`; mark db-dependent tests with `@pytest.mark.integration`.
  - Pre-commit remains the gatekeeper—never bypass it; fix the root cause instead of committing with `--no-verify`.
- **Scripting norms**
  - Use existing helpers (`tools.doctor`, `tools.pgrst_reload`, `tools.security_audit`) rather than bespoke scripts.
  - Scripts that mutate Supabase must accept `--env` or read `SUPABASE_MODE` to avoid prod accidents.

---

## How AI Should Behave

1. **Never drop or truncate** tables, views, or critical data structures in migrations unless an attorney or staff engineer explicitly authorizes it.
2. **Prefer additive migrations**: add columns, views, or grants incrementally; use `DROP ... IF EXISTS` only as part of safe replace patterns.
3. **Keep functions small and composable**—factor helpers into `etl/src/**` or `src/**` modules rather than monolith scripts.
4. **Mark human checkpoints** with `TODO: Attorney review required` (or similar) whenever legal sign-off, manual outreach, or notarized filings are needed.
5. **Respect existing tooling**: read files before editing, run the relevant tests or lint commands mentally, and keep diffs tight.
6. **Safeguard PII**: avoid logging debtor addresses, SSNs, or bank info; use encryption utilities when storing secrets.
7. **Document intent**: when touching migrations, ETL, or workflows, leave concise comments explaining why the change is safe and how it links back to legal/compliance requirements.

---

_Keep this guide updated whenever the schema, tooling, or legal assumptions change. Add sections for new data domains or compliance duties as the platform evolves._
