# Dragonfly Repo Overview

## Supabase Assets

- **supabase/config.toml** – Supabase CLI project definition; points local tooling at `supabase/db` for migration diffs and auth/session configuration.
- **supabase/schema.sql** – Canonical declarative schema for the dedicated `judgments` schema (cases, judgments, parties) and supporting public tables; documents triggers such as `judgments.apply_case_defaults`, `judgments.apply_judgment_defaults`, touch-up triggers (`trg_*_touch_updated`), and collector-centric indexes.
- **supabase/migrations/** – Production migration history (`0001`–`0153`) covering:
  - Core case/contact intake (0001–0034) including `public.judgments`, `public.cases_entities`, and the public RPC wrappers used by the dashboard.
  - Queue job lifecycle (0035–0052) and enrichment run pipelines (0053–0062).
  - Collectability/tier analytics (0057–0075) powering `v_plaintiffs_overview`, `v_judgment_pipeline`, and call queue views.
  - Simplicity + import hardening (0124_simplicity_import_support.sql, 0126_import_safety_guards.sql) that add `source_reference`, `lead_metadata`, contact uniqueness, and ingestion guards for external CSVs.
  - Enforcement planner/timeline stack (0127–0133, 0140) defining `public.enforcement_cases`, `public.plaintiff_tasks`, timeline materialized views, and RLS on enforcement artifacts.
  - RLS/security tightening (0145_ops_monitoring_refresh.sql through 0151_table_security_lockdown.sql) locking down grants on plaintiffs, judgments, and pipeline analytics.
  - Latest documentation sync (20251129165247_rpc_docstrings.sql) annotating RPC contract metadata.
- **supabase/db/migrations/** – Supabase CLI-driven diffs used for rapid hotfixes (`0076_import_runs.sql`, `0084_jbi_900_intake.sql`, etc.); mirrors production history but scoped to CLI `db` commands.
- **supabase/migrations_archive/** – Deprecated/retired SQL preserved for reference; useful when auditing past schema decisions.
- **supabase/schema.sql** + **supabase/migrations/** interplay – schema.sql is kept in sync via `scripts/reload_schema.ps1` and `scripts/db_get_migrations.ps1` to regenerate declarative DDL after each migration batch.
- **scripts/bootstrap.ps1** – Unified entrypoint for Supabase automation (`-Mode push|reload|smoke`); loads env via `scripts/load_env.ps1`, resolves Supabase project refs, and dispatches to CLI commands.
- **scripts/db_push.ps1** – Thin wrapper around `bootstrap.ps1 -Mode push`; applies migrations to the selected env (`SUPABASE_MODE` guard) and logs to the console.
- **scripts/db_repair.ps1** / **scripts/db_check.sql** – Performs structural repairs and sanity SQL checks when the migration chain diverges.
- **scripts/db_get_migrations.ps1** / **scripts/fix_migration_versions.ps1** – Utilities for enumerating migration status and reconciling file numbering across Supabase CLI + repo history.
- **scripts/preflight\*.ps1** – Composite entrypoints (`preflight.ps1`, `preflight_dev.ps1`, `preflight_prod.ps1`) that run config validation, doctor checks, pytest, and Supabase smoke tests before pushing schema changes.
- **scripts/load_env.ps1** – Normalizes local/CI env vars (Supabase keys, DSNs) so CLI and Python tools share the same project credentials.

## Judgment, Plaintiff, and Enforcement Data Stores

- **judgments.cases** (defined in `supabase/schema.sql`) – Primary case registry with docket metadata, filing details, and ingestion provenance; enforced defaults ensure docket/case number normalization.
- **judgments.judgments** – Stores individual judgment records linked to `judgments.cases`; maintains amount/interest defaults and touch-up triggers for lifecycle timestamps.
- **judgments.parties** – Party roster for each case, including normalized addresses and role validation (`role IN ('plaintiff','defendant')`).
- **public.judgments** – Legacy intake table still referenced by orchestration/migrations (e.g., 0030_judgments_table.sql, 0124_simplicity_import_support.sql) for dashboard compatibility.
- **public.plaintiffs** – Canonical plaintiff dimension (status, tier, source_system, `source_reference`, `lead_metadata`), hardened for Simplicity imports (unique email/phone merges).
- **public.plaintiff_contacts** – Deduplicated contact table (kind/value uniqueness added in 0124) storing phone/email combinations tied to plaintiffs.
- **public.plaintiff_status_history** – Historical status timeline; leveraged by call queue views and enforcement planners.
- **public.plaintiff_call_attempts** – Tracks outreach attempts with indexes for queue prioritization (0141_log_call_outcome.sql, 0146_restore_log_call_outcome.sql).
- **public.plaintiff_tasks** – Enforcement/task planner backlog; migrations 0129, 0140, 0147 harden uniqueness and auto-refresh logic.
- **public.enforcement_cases** / **public.enforcement_timeline** – Created across 0127_enforcement_timeline.sql and 0140_enforcement_unify.sql; ties judgments back to enforcement workflows with plaintiff foreign keys and timeline snapshots.
- **Analytic Views** – `public.v_plaintiffs_overview`, `public.v_judgment_pipeline`, `public.v_enforcement_overview`, `public.v_plaintiff_call_queue`, `public.v_plaintiff_open_tasks`, `public.v_enforcement_recent`, `public.v_metrics_*`; defined across migrations 0057+, 0129+, 0142+, and guarded by grant hardening in 0149–0152.

## Judgment & Simplicity ETL / Automation

- **etl/src/simplicity_orchestrator.py** – Production CLI that hydrates Supabase via `--batch-file` CSV imports; handles dry-run vs `--commit`, per-row savepoints, dead-letter CSV output, and summary JSON.
- **etl/src/importers/simplicity_plaintiffs.py** – Core parsing + reconciliation engine (Pydantic models, idempotent merge strategies) used by orchestrator and historical JBI/Simplicity importers.
- **etl/src/plaintiff_importer.py** / **etl/src/plaintiff_batch_importer.py** – Shared ingestion helpers that map normalized rows into `public.plaintiffs`, judgments, contacts, and tasks.
- **etl/src/importers/jbi_900.py** – Adapter for the JBI “900 plaintiffs” cohort; reuses Simplicity models to hydrate import batches and audit failures.
- **etl/src/sync_simplicity.py** & **scripts/sync_simplicity.py** – Bi-directional sync utilities that reconcile Simplicity exports, apply per-row savepoints, and emit ingestion metadata.
- **etl/src/collector_intel.py**, **etl/src/loaders.py**, **etl/src/transforms.py** – Support csv to Supabase pipelines for judgments/cases; rely on Supabase RPCs defined in the migrations above.
- **integration/simplicity/** – Test fixtures + CSV readers validating Simplicity importer behavior against known datasets.
- **n8n/flows/dragonfly_import_trigger_v1.json** – Scheduler that polls `v_plaintiffs_overview`, seeds `import_runs`, and enqueues Supabase `queue_job` dispatchers.
- **n8n/flows/csv_ingest_monitor.json** – Watches Supabase `import_runs` / storage buckets for pending CSVs and escalates ingestion failures to ops.
- **n8n/flows/dragonfly_new_plaintiff_intake_v1.json** – Automates plaintiff onboarding by calling Supabase RPCs for `public.plaintiffs` and judgment staging.
- **n8n/flows/dragonfly_enforcement_timeline_updater_v1.json** – Keeps enforcement snapshots aligned with `public.enforcement_cases` updates.
- **n8n/flows/dragonfly_intake_monitor_v1.json** & **dragonfly_call_queue_sync_v1.json** – Monitor ingestion health and sync call-queue metrics derived from plaintiff/judgment tables.
- **scripts/import*900*\*.ps1** / **tools/import_900.py** – Batch import drivers for the 900-plaintiff cohort; wrap CSV parsing and Supabase writes, logging to `import_runs` tables surfaced in migrations `0076_import_runs.sql` and `0084_jbi_900_intake.sql`.

## Security, Doctor, and Preflight Tooling

- **tools/doctor.py** – Comprehensive Supabase health check (connectivity, required views, queue RPC signatures, metrics views); used by preflight scripts and CI to guard schema integrity.
- **tools/doctor_all.py** – Aggregates intake and enforcement doctor suites across environments; invoked by `scripts/preflight_*` and CI smoke jobs.
- **tools/security_audit.py** – Validates RLS policies, grants, and table ownership against expected locked-down state (aligns with migrations 0149–0152).
- **tools/check_schema_consistency.py** / **tools/schema_guard.py** – Compares live Supabase catalogs to repo expectations, ensuring migrations and schema.sql stay aligned.
- **tools/smoke_plaintiffs.py**, **tools/smoke_enforcement.py**, **tools/ops_healthcheck.py** – Run domain-specific queries asserting that plaintiffs/judgments/enforcement rows remain visible under RLS and contain required columns.
- **scripts/preflight\*.ps1** – Bundle config checks, `tools.doctor`, pytest, and linting before deployments to dev/prod.
- **scripts/sanity_probe.ps1**, **scripts/probe_rest.ps1** – REST-level smoke probes hitting PostgREST endpoints for plaintiffs/judgments resources.
- **scripts/run_watcher.ps1** / **scripts/run_workers.ps1** – Launch background ingestion workers that rely on Supabase queue jobs created by the migrations above; typically executed after `db_push` and `doctor` succeed.
- **tools/pgrst_reload.py** / **scripts/bootstrap.ps1 -Mode reload** – Force PostgREST to reload schema after migrations, preventing stale role caches from exposing unsecured columns.

Use this document to orient new agents: Supabase migrations and scripts govern the canonical data model, the ETL stack (Python + n8n) loads and reconciles judgments/plaintiffs, and the doctor/security tooling enforces database integrity before anything reaches production.
