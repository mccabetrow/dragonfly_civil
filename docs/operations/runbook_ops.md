# Dragonfly Civil Operations Runbook

## Overview

Dragonfly Civil automates municipal judgment enforcement by syncing case data from ingestion pipelines into Supabase, enriching records for collectability insights, and powering the internal dashboards used during demos and live monitoring. The platform orchestrates collectors, queues, and workers that update judgments, parties, enrichment runs, and outreach activity.

## Daily Operations

- Review the dashboard Overview page for overall demo health: charts should show current counts for open cases, FOIL responses, and enrichment status without large gaps.
- Inspect the Collectability view; tiers A–C should have recent timestamps and no obvious empty metrics. If tier scores disappear, trigger enrichment.
- Spot check the Cases page: ensure seeded demo cases (DEMO-CASE-001/2/3) display judgments, parties, and FOIL cards without missing sections.
- Confirm Supabase logs (Judgments schema) show recent activity timestamps matching the latest run; if anything stalls, note it in the daily standup.
- If the dashboard drifts from expected data, run `scripts/demo_reset_and_smoke.ps1` (dev) followed by `scripts/demo_pipeline_prod.ps1` to rehydrate the storyline.

## Weekly Tasks

- Run the collector scripts (`python -m etl.src.collector_v1` or the Make targets) to ensure ingest pathways remain healthy.
- Review queue backlogs using `tools.list_queue_functions` and enforce/collect queues in Supabase; anything older than 24 hours should be flushed or re-run.
- Execute both `scripts/preflight_dev.ps1` and `scripts/preflight_prod.ps1`; archive the `[OK]` terminal output so founders know both environments are healthy.
- Validate migrations by running `scripts/db_push.ps1 -SupabaseEnv dev` (or prod when approved) after pulling the latest migrations.

## Demo Data Management

- Quick refresh: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo_reset_and_smoke.ps1` (requires `SUPABASE_MODE='dev'`). The script wipes demo rows, reseeds plaintiffs/judgments, runs planners/workers, and finishes with smoke checks.
- Pipeline storytelling: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo_pipeline_prod.ps1` to insert DEMO-0001, enqueue enrichment, and print the collectability/contactability payload you can narrate live.
- Inspect seeded cases with `python -m scripts.inspect_cases demo` to verify row counts; if counts mismatch, rerun the reset script or check Supabase constraints.

## Troubleshooting

- Logs: review PowerShell task transcripts under `logs/` and Supabase function logs for failed RPCs (especially `spawn_enforcement_flow`).
- Diagnostics: run `python -m tools.doctor` for environment & dependency checks; `python -m tools.db_check` for Supabase connectivity (both already covered inside the preflight scripts).
- Queue insight: `python -m tools.list_queue_functions` confirms RPC availability.
- Alerts: monitor Discord #ops channel for automated messages; respond by triaging with the steps above and logging the outcome in Ops notes.
- Escalation: if migrations fail or Supabase returns permission denied, contact the engineering lead and prepare to run `scripts/db_repair.ps1` in a supervised session.
