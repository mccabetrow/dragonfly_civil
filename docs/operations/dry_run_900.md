# 900 Plaintiff Dry Run Simulator

This guide covers the dev-only CLI (`python -m tools.dry_run_900`) that seeds a
900 plaintiff cohort, simulates the downstream workflow, and confirms the
dashboard-critical views without waiting for live vendors.

## What the simulator does

- **Bulk intake** – runs the JBI 900 importer against `run/plaintiffs_canonical.csv`
  (or a trimmed subset) and records the resulting `import_runs` metadata.
- **Queue kicks** – leverages the importer-enqueued `enrich`/`enforce` jobs and
  appends a `foil_request` entry per case so workers can observe PGMQ traffic.
- **Enrichment + FOIL stubs** – inserts deterministic rows into
  `judgments.enrichment_runs`, drives the `set_case_enrichment` /
  `set_case_scores` RPCs, and fabricates FOIL responses so the enforcement and
  pipeline dashboards light up.
- **Call outcomes** – logs realistic `log_call_outcome` scenarios against the
  importer-created call tasks to exercise the call queue and plaintiff history
  cards.
- **View validation** – counts `v_plaintiffs_overview`, `v_judgment_pipeline`,
  `v_enforcement_overview`, `v_enforcement_recent`, `v_plaintiff_call_queue`,
  and `v_collectability_snapshot` so we can immediately confirm the data
  surfaced to the Ops Console.
- **Reset safety** – writes the inserted plaintiff/judgment ids to
  `state/dry_run_900_last.json`, enabling one-command cleanup via `--reset`.

## Running the dry run

> **Prereqs:**
>
> - `SUPABASE_MODE` must be `dev` and credentials loaded (`./scripts/load_env.ps1`).
> - The dev database should be empty or disposable; this CLI is intentionally
>   destructive during cleanup.

```powershell
# Seed all 900 plaintiffs, simulate enrichment, FOIL, and call outcomes
$env:SUPABASE_MODE = 'dev'
python -m tools.dry_run_900 --env dev --count 900 --reset
```

The command prints a JSON summary similar to:

```json
{
  "batch_name": "dry_run_900_20240101120000",
  "call_outcomes": {
    "do_not_call": 8,
    "reached": 62,
    "total": 120,
    "voicemail": 50
  },
  "enrichment": { "case_count": 900, "enrichment_runs": 900 },
  "env": "dev",
  "foil": { "foil_responses": 900 },
  "judgments": 900,
  "plaintiffs": 900,
  "queue": { "available": true, "queued": 900 },
  "views": {
    "public.v_enforcement_overview": 5,
    "public.v_enforcement_recent": 25,
    "public.v_collectability_snapshot": 900,
    "public.v_judgment_pipeline": 900,
    "public.v_plaintiff_call_queue": 60,
    "public.v_plaintiffs_overview": 900
  }
}
```

Key options:

| Option         | Description                                                                                                    |
| -------------- | -------------------------------------------------------------------------------------------------------------- |
| `--env`        | Supabase credential set (must be `dev`; defaults to `SUPABASE_MODE`).                                          |
| `--csv`        | Source CSV. Defaults to `run/plaintiffs_canonical.csv`.                                                        |
| `--count`      | Number of rows to import. The CLI trims the CSV automatically when `count` < total (handy for a 50-row smoke). |
| `--batch-name` | Override the auto-generated `dry_run_900_<timestamp>` label.                                                   |
| `--reset`      | Deletes the previous dry run cohort (tracked in `state/dry_run_900_last.json`) before seeding.                 |
| `--reset-only` | Performs the cleanup step and exits without importing or simulating anything.                                  |

## Cleanup + reruns

Every execution records the affected ids in `state/dry_run_900_last.json`. To
remove the synthetic cohort later:

```powershell
$env:SUPABASE_MODE = 'dev'
python -m tools.dry_run_900 --env dev --reset-only
```

The CLI removes FOIL rows, enrichment runs, call attempts, tasks, contacts,
statuses, judgments, and plaintiffs for the recorded ids, then deletes the state
file. Running the full simulator with `--reset` achieves the same cleanup before
re-importing the CSV.

## Post-run validation

After the dry run completes you can:

1. Load `dragonfly-dashboard` and confirm the Overview, Enforcement, and Call
   Queue pages show populated cards.
2. Run `python -m tools.doctor --env dev` or
   `python -m tools.smoke_plaintiffs --env dev` for extra assurance before a
   demo.
3. Capture the CLI JSON summary in the ops log so the team knows which batch
   seeded the environment.

Operate this CLI like any other production-adjacent tool: keep it dev-only,
commit migrations or schema tweaks first, and always clean up the synthetic
cohort before pointing vendor data at the same environment.
