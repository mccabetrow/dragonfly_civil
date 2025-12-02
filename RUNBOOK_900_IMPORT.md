# RUNBOOK_900_IMPORT

Friendly step-by-step guide for loading the 900-plaintiff JBI batch into Supabase. Keep this next to the Dragonfly computer whenever you prep, rehearse, or run the import.

---

## When to use this runbook

- A new 900-case CSV landed from JBI and needs to hit Supabase.
- You must rehearse the intake in dev before a prod push or demo.
- You are verifying an earlier import and need to see the monitoring + cleanup knobs.

Every import touches production-grade workflows (queues, enforcement stages, dashboards). Follow each checklist, read commands out loud, and log the results in `#daily-ops`.

---

## Safety + readiness checklist (run before touching any data)

1. **Open the repo** – `c:\Users\mccab\dragonfly_civil` in VS Code.
2. **Load credentials** – run `./scripts/load_env.ps1`; confirm it prints the active `SUPABASE_MODE`.
3. **Confirm you are on Wi-Fi + VPN** – Supabase rejects connections from unknown networks.
4. **Pick the environment** – `dev` for rehearsal, `prod` only after dev is green and leadership has signed off.
5. **Health checks**
   - Dev: `Tasks → Preflight (Dev)`.
   - Prod: `Tasks → Preflight (Prod)` then `Tasks → Doctor All`.
6. **Run Preflight 900** – this is the **required safety gate** before the 900-plaintiff import:
   - Dev: `Tasks → Preflight: 900 Import (Dev)` or run directly:
     ```powershell
     .\scripts\preflight_900.ps1 -SupabaseEnv dev
     ```
   - Prod: `Tasks → Preflight: 900 Import (Prod)` or run directly:
     ```powershell
     .\scripts\preflight_900.ps1 -SupabaseEnv prod
     ```
   - **All 4 checks must pass** before proceeding:
     1. `check_schema_consistency` – verifies critical views/tables/RPCs
     2. `check_prod_schema` – confirms live schema matches frozen snapshot
     3. `enrichment_smoke` – proves `core_judgments` trigger + handler pipeline works
     4. `pytest` – runs idempotency + handler unit tests
   - The script prints `[OK] Preflight 900 complete - SAFE TO RUN 900 IMPORT` when all checks pass.
7. **Back up the CSV** – copy the vendor file into `data/jbi_export_<date>.csv` plus an off-machine backup.
8. **Name your batch** – `jbi900_<yyyymmdd>` works well; write it down because it ties every log, import run, and queued job together.

If any preflight step shows red text, stop, screenshot, and ping Engineering.

---

## Stage 1 – Validate the CSV offline (no database writes)

> Goal: catch header issues, blank rows, or bad dates before we touch Supabase.

1. Set the terminal environment:
   ```powershell
   cd C:\Users\mccab\dragonfly_civil
   $env:SUPABASE_MODE = 'dev'
   ```
2. Run the importer in dry-run mode (no `--commit`). This parses every row, reports counts, and never touches the database:
   ```powershell
   python -m tools.run_import --source jbi --csv data\jbi_export_valid_sample.csv --batch-name jbi900_20251105 --source-reference jbi900_wave_20251105 --skip-jobs --pretty
   ```
3. Read the JSON carefully:
   - `metadata.parse_errors` should be empty. If it lists rows, fix the CSV (look for missing `case_number`, amount, or plaintiff name) and rerun.
   - `summary.row_count` should match the CSV row count minus blank lines.
   - `planned_storage_path` appears because we skipped `--commit`; that is expected.
4. Save the JSON output in `logs/validation_<date>.txt` so everyone knows the file passed parsing.

Only move to Stage 2 when the dry-run is clean.

---

## Stage 2 – Dev rehearsal with real inserts (required before prod)

> Goal: land the file in dev, confirm contacts/tasks/queues/views, and rehearse the full workflow.

1. **Reset demo data if needed** – to start from a clean slate:
   ```powershell
   $env:SUPABASE_MODE = 'dev'
   python -m tools.dry_run_900 --env dev --reset-only
   ```
2. **Run the importer with `--commit`** (still in dev). Keep `--skip-jobs` on unless you want workers to pick up the queued jobs immediately.
   ```powershell
   python -m tools.run_import --source jbi --csv data\jbi_export_valid_sample.csv --batch-name dev-jbi900-20251105 --source-reference dev-jbi900-20251105 --commit --skip-jobs --pretty
   ```
   - Watch for `import_run_id` in the output—write it down.
   - `summary.insert_count` should equal `row_count` unless duplicates were skipped.
3. **Verify Supabase records**
   - `public.import_runs` – new row with your batch name, `status = completed`, and metadata counts.
   - `public.plaintiffs` / `judgments.cases` / `judgments.judgments` – filter by `source_system = 'jbi_900'`.
4. **Run doctor + smoke checks**
   ```powershell
   python -m tools.doctor --env dev
   python -m tools.smoke_plaintiffs --env dev
   ```
5. **Dashboard sanity** – open the dev dashboard and confirm:
   - `v_plaintiffs_overview`, `v_judgment_pipeline`, `v_enforcement_overview`, `v_enforcement_recent`, `v_plaintiff_call_queue` all show non-zero counts.
   - The call queue contains new tasks from the importer (Tier labels, due dates).
6. **Document the rehearsal** – log the batch name, `import_run_id`, and doctor/smoke timestamps in `#daily-ops`.

If anything fails, capture the terminal text + JSON, revert dev with `python -m tools.dry_run_900 --env dev --reset-only`, and loop with Engineering before continuing.

---

## Stage 3 – Production import (only after dev is green)

> Goal: load the approved CSV into prod, queue enrichment/enforcement jobs, and notify stakeholders.

1. **Switch context**
   ```powershell
   cd C:\Users\mccab\dragonfly_civil
   $env:SUPABASE_MODE = 'prod'
   ```
2. **Run the prod readiness scripts**
   - `Tasks → Preflight (Prod)`
   - `Tasks → Doctor All`
   - `python -m tools.smoke_plaintiffs --env prod`
     If any script fails, stop and escalate.
3. **Run the importer (no `--skip-jobs`)**
   ```powershell
   python -m tools.run_import --source jbi --csv "\\share\final\jbi900_20251105.csv" --batch-name jbi900_prod_20251105 --source-reference jbi900_prod_20251105 --commit --pretty
   ```
   - Keep the terminal visible until it prints the JSON summary.
   - Copy the summary block and post it to `#daily-ops` and `#engineering` with the file path.
4. **Immediate monitoring**
   - `public.import_runs` row should flip to `completed` with accurate counts.
   - `metadata.summary.queued_jobs` should list new `enrich` and `enforce` entries for every judgment.
   - `Queue depth` – run `make smoke` or `Tasks → smoke` to confirm workers can pick up the new jobs.
5. **Dashboard verification (prod)** – refresh the Exec + Pipeline dashboards; the plaintiff counts, enforcement tiles, and call queue should jump by ~900.
6. **Final health sweep** – rerun `python -m tools.doctor --env prod` after the import settles; screenshot the green ending for the ops log.

---

## Monitoring cheat sheet

- **Terminal logs** – look for `inserted`, `skip_existing_judgment`, or `error` actions in the JSON `row_operations` list.
- **Supabase `public.import_runs`** – status, row counts, insert/update/error totals, and `metadata.summary.contact_inserts` + `follow_up_tasks` confirm downstream effects.
- **`public.raw_simplicity_imports`** (or the JBI equivalent) – holds each raw row with `status = inserted / skipped / parse_error` for auditing.
- **Queues** – `metadata.queued_jobs` lists `enrich` + `enforce` message IDs. If workers should stay paused, stash the IDs so engineering can delete them later.
- **Views** – `SELECT COUNT(*) FROM public.v_enforcement_overview;` etc. should match the dashboard after RLS refresh.

---

## Troubleshooting guide

| Symptom                                | What it means                                                                         | What to do                                                                                                                              |
| -------------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `CSV file not found` error             | Path typo or missing network drive                                                    | Recheck the path. Use quotes for network shares (`"\\server\path\file.csv"`).                                                           |
| `missing required column`              | CSV header not normalized (`case_number`, `party_name`, `judgment_amount` must exist) | Fix the header in Excel/Sheets, re-export as UTF-8 CSV, rerun Stage 1.                                                                  |
| `parse_errors` non-empty               | Specific rows failed validation (bad amounts, blank names)                            | Open the row number in the CSV, correct it, rerun the dry-run until clean.                                                              |
| `import_runs.status = failed`          | Import crashed mid-run                                                                | Grab the `import_run_id`, copy `metadata.exception`, ping Engineering immediately. Do **not** rerun until told.                         |
| Row count mismatch vs. dashboards      | RLS cache or filters out of date                                                      | Run `python -m tools.doctor --env <env>` and refresh dashboards. If still wrong, capture screenshots + `import_run_id` for Engineering. |
| Workers grabbing jobs too early in dev | Forgot `--skip-jobs` during rehearsal                                                 | Note the `metadata.queued_jobs` IDs and ask Engineering to clear them via `pgmq_delete`, or let the worker finish processing if safe.   |

---

## Backout + recovery plan

1. **Dev rehearsal cleanup** – run `python -m tools.dry_run_900 --env dev --reset-only` to remove the seeded plaintiffs and reset dashboards.
2. **Prod misfire detected quickly (<15 min)**
   - Immediately stop any downstream scripts (workers, watchers) by pinging Engineering.
   - Gather: batch name, `import_run_id`, the wrong CSV path, and the terminal output.
   - Engineering will run the targeted rollback (delete plaintiffs/judgments/contact rows tied to that `import_run_id`) and confirm queues are flushed.
3. **Prod corrections (legit file but needs re-run)**
   - Re-run the importer with the fixed CSV **using the same `batch_name`** so rows update in place. Mention in Slack that it was an idempotent replay.
4. **Queue emergency** – if `enrich`/`enforce` jobs pile up, run `Tasks → REST: Reload` to reset PostgREST, then coordinate with workers via `scripts/run_workers.ps1`.
5. **Document everything** – each backout attempt needs a Slack thread with timestamps, commands, and screenshots for audit history.

---

## Who to contact

- `#daily-ops` – announce start/finish, share JSON summaries, log any hiccups.
- `#engineering` – escalate parse errors, failed imports, queue issues, or rollback requests. Include `batch_name`, `import_run_id`, and the CSV path.
- Phone tree (in the binder) – use if Slack is down or prod import failed and you need immediate help.

Keep this runbook updated. If you improve a step, PR the changes and tag Engineering so every future import stays as smooth as this one.

---

## 900 Import v1 – Command Reference (December 2025)

This section provides exact, copy-paste commands for the 900-plaintiff JBI import with the new enrichment pipeline.

### Preflight Commands

Run **both** checks before any import. All must pass.

#### Dev Preflight

```powershell
cd C:\Users\mccab\dragonfly_civil
$env:SUPABASE_MODE = 'dev'

# 1. Load env
. .\scripts\load_env.ps1

# 2. Full preflight gate
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight_900.ps1 -SupabaseEnv dev
```

Expected output: `[OK] Preflight 900 complete - SAFE TO RUN 900 IMPORT`

#### Prod Preflight

```powershell
cd C:\Users\mccab\dragonfly_civil
$env:SUPABASE_MODE = 'prod'

# 1. Load env
. .\scripts\load_env.ps1

# 2. Full preflight gate
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\preflight_900.ps1 -SupabaseEnv prod
```

Expected output: `[OK] Preflight 900 complete - SAFE TO RUN 900 IMPORT`

### Import Commands (with new enrichment pipeline)

#### Dev Import – Dry Run

```powershell
$env:SUPABASE_MODE = 'dev'
python -m tools.run_import `
  --source jbi `
  --csv data\jbi_export_valid_sample.csv `
  --batch-name "jbi900-dev-$(Get-Date -Format 'yyyyMMdd')" `
  --source-reference "jbi900-dev-$(Get-Date -Format 'yyyyMMdd')" `
  --enable-new-pipeline `
  --skip-jobs `
  --pretty
```

Verify: `metadata.parse_errors` is empty, `summary.row_count` matches CSV.

#### Dev Import – Commit

```powershell
$env:SUPABASE_MODE = 'dev'
python -m tools.run_import `
  --source jbi `
  --csv data\jbi_export_valid_sample.csv `
  --batch-name "jbi900-dev-$(Get-Date -Format 'yyyyMMdd')" `
  --source-reference "jbi900-dev-$(Get-Date -Format 'yyyyMMdd')" `
  --enable-new-pipeline `
  --commit `
  --pretty
```

Record: `import_run_id` from JSON output.

#### Prod Import – Commit

```powershell
$env:SUPABASE_MODE = 'prod'
python -m tools.run_import `
  --source jbi `
  --csv "\\share\final\jbi900_production.csv" `
  --batch-name "jbi900-prod-$(Get-Date -Format 'yyyyMMdd')" `
  --source-reference "jbi900-prod-$(Get-Date -Format 'yyyyMMdd')" `
  --enable-new-pipeline `
  --commit `
  --pretty
```

⚠️ **ONLY run after dev is fully green and prod preflight passes.**

### During-Import Verification

Run these queries in Supabase SQL Editor or via psql while the import is running:

```sql
-- Watch import_runs status (should be 'running' then 'completed')
SELECT id, batch_name, status, row_count, insert_count, error_count, created_at
FROM public.import_runs
ORDER BY created_at DESC
LIMIT 5;

-- Monitor core_judgments growth
SELECT COUNT(*) AS total_judgments,
       COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') AS last_hour
FROM public.core_judgments;

-- Check queue depth (enrichment jobs pending)
SELECT queue_name, msg_id, read_ct, enqueued_at
FROM pgmq.q_judgment_enrich
ORDER BY enqueued_at DESC
LIMIT 10;
```

### Post-Import Verification Checklist

Run these commands after the import completes:

```powershell
$env:SUPABASE_MODE = 'dev'  # or 'prod'

# 1. Doctor check
python -m tools.doctor --env dev

# 2. Plaintiff smoke test
python -m tools.smoke_plaintiffs --env dev

# 3. Enrichment smoke test
python -m tools.enrichment_smoke --env dev
```

#### SQL Verification Queries

```sql
-- 1. core_judgments count (should be ~900 new)
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '2 hours') AS recent
FROM public.core_judgments;

-- 2. debtor_intelligence coverage (grows as enrichment runs)
SELECT COUNT(DISTINCT judgment_id) AS enriched_judgments
FROM public.debtor_intelligence;

-- 3. enforcement_actions (starts at 0, grows after planner runs)
SELECT status, COUNT(*)
FROM public.enforcement_actions
GROUP BY status;

-- 4. Queue depths
SELECT
  (SELECT COUNT(*) FROM pgmq.q_judgment_enrich) AS enrich_queue,
  (SELECT COUNT(*) FROM pgmq.q_enforce) AS enforce_queue,
  (SELECT COUNT(*) FROM pgmq.q_plaintiff_sync) AS sync_queue;

-- 5. Pipeline stage distribution
SELECT pipeline_stage, COUNT(*)
FROM public.v_enforcement_pipeline_status
GROUP BY pipeline_stage
ORDER BY COUNT(*) DESC;
```

### Rollback / Abort Conditions

| Condition                         | Severity    | Response                                                                                             |
| --------------------------------- | ----------- | ---------------------------------------------------------------------------------------------------- |
| `import_runs.status = failed`     | 🔴 CRITICAL | Stop immediately. Do NOT retry. Grab `import_run_id`, screenshot terminal, escalate to #engineering. |
| `parse_errors` > 10 rows          | 🟠 ABORT    | Cancel import. Fix CSV issues. Re-run dry-run until clean.                                           |
| `error_count` > 5% of `row_count` | 🟠 ABORT    | Stop workers. Investigate `metadata.errors`. Coordinate rollback with Engineering.                   |
| Queue depth > 2000 after 30 min   | 🟡 WARNING  | Workers may be stuck. Check `scripts/run_workers.ps1` logs. Consider scaling workers.                |
| Dashboard shows 0 after import    | 🟡 WARNING  | Run `python -m tools.pgrst_reload --env <env>` then refresh. If still 0, escalate.                   |

#### Emergency Rollback (Engineering Only)

```sql
-- DANGER: Only run if instructed by Engineering
-- Identify the bad import run
SELECT id, batch_name, metadata FROM import_runs
WHERE batch_name LIKE 'jbi900%' ORDER BY created_at DESC LIMIT 3;

-- Delete downstream data (replace <import_run_id>)
DELETE FROM enforcement_actions
WHERE judgment_id IN (
  SELECT id FROM core_judgments WHERE metadata->>'import_run_id' = '<import_run_id>'
);

DELETE FROM debtor_intelligence
WHERE judgment_id IN (
  SELECT id FROM core_judgments WHERE metadata->>'import_run_id' = '<import_run_id>'
);

DELETE FROM core_judgments WHERE metadata->>'import_run_id' = '<import_run_id>';

-- Update import_runs status
UPDATE import_runs SET status = 'rolled_back' WHERE id = '<import_run_id>';
```

---

## Mom Enforcement Console v1 – First 2 Hours After Go-Live

This guide tells Mom exactly what to do when the 900 plaintiffs land in prod.

### Console Overview

Mom uses three main views after the import:

| View                                      | Purpose                                    | URL/Location               |
| ----------------------------------------- | ------------------------------------------ | -------------------------- |
| `v_enforcement_pipeline_status`           | See where each judgment is in the workflow | Dashboard → Pipeline tab   |
| `v_enforcement_actions_pending_signature` | Documents waiting for attorney sign-off    | Dashboard → Signatures tab |
| `v_plaintiff_call_queue`                  | Today's call list sorted by priority       | Dashboard → Call Queue tab |

### Hour 1: Verify the Import Landed

**Goal:** Confirm 900 new plaintiffs are visible and the pipeline is moving.

#### Step 1: Open Pipeline Dashboard (5 min)

1. Open Chrome → Dragonfly Dashboard bookmark
2. Click **Pipeline** in the left sidebar
3. Look at the **Pipeline Stage** breakdown chart

**Expected after 900 import:**

- `awaiting_enrichment`: ~900 (dropping as workers process)
- `awaiting_action_plan`: 0 initially (grows after enrichment completes)
- `awaiting_signature`: 0 initially (grows after planner runs)

#### Step 2: Watch Enrichment Progress (10 min)

1. Refresh the Pipeline page every 2 minutes
2. Watch `awaiting_enrichment` count decrease
3. Watch `awaiting_action_plan` count increase

**If stuck at 900 for > 10 minutes:**

- Check Slack #engineering for worker alerts
- Run: `python -m tools.doctor --env prod`
- Screenshot and escalate

#### Step 3: Verify Call Queue Populated (5 min)

1. Click **Call Queue** in the left sidebar
2. Should see new plaintiff names appearing
3. **Tier** column shows A (red), B (amber), C (blue)
4. **Due** column shows today's date for immediate calls

**If Call Queue is empty:**

- Check Pipeline → are there any judgments in `awaiting_action_plan` or later?
- If Pipeline shows data but Call Queue is empty, run: `python -m tools.pgrst_reload --env prod`
- Refresh browser with Ctrl+Shift+R

#### Step 4: Run Quick SQL Spot-Check (10 min)

Open Supabase SQL Editor and run:

```sql
-- Quick health check
SELECT
  (SELECT COUNT(*) FROM core_judgments) AS total_judgments,
  (SELECT COUNT(*) FROM debtor_intelligence) AS enriched,
  (SELECT COUNT(*) FROM enforcement_actions) AS actions,
  (SELECT COUNT(*) FROM v_plaintiff_call_queue) AS call_queue_size;
```

**Expected 1 hour after import:**

- `total_judgments`: ~900+
- `enriched`: 100-300 (growing)
- `actions`: 0-50 (starts after enrichment)
- `call_queue_size`: 50-200 (growing)

### Hour 2: Start Working the Call Queue

**Goal:** Make first outbound calls, log outcomes, build momentum.

#### Step 1: Open Call Queue Page

1. Click **Call Queue** in left sidebar
2. Sort by **Due** column (click header) → oldest first
3. Sort by **Tier** column → A (red) at top

#### Step 2: Work Top 10 Calls

For each row:

1. **Review plaintiff info:** Click the name to see case details
2. **Check phone number:** Visible in the **Phone** column
3. **Make the call:** Use the phone icon or dial manually
4. **Log outcome immediately:**
   - Click **Log Outcome** button
   - Select from dropdown:
     - `Reached + Next Steps` – spoke with them, action planned
     - `Left Voicemail` – no answer, left message
     - `Bad Number` – disconnected or wrong number
     - `No Answer` – rang, no voicemail
     - `Do Not Call` – requested removal
   - Add notes (who you spoke with, callback time)
   - Set follow-up date if needed
   - Click **Save Outcome**

#### Step 3: Monitor Signature Queue (check every 30 min)

1. Click **Signatures** tab
2. Look for rows in `v_enforcement_actions_pending_signature`
3. These are enforcement documents ready for attorney review

**For each document:**

- Review the **Action Type** (wage garnishment, bank levy, etc.)
- Check **Debtor Name** and **Principal Amount**
- Flag any that look unusual or need attorney attention first

#### Step 4: Log Progress to Slack

At the end of Hour 2, post to #daily-ops:

```
900 Import Status - [DATE] [TIME]
✅ Import complete: [import_run_id]
📊 Pipeline: [X] awaiting enrichment, [Y] action planned, [Z] awaiting signature
📞 Calls made: [N]
📝 Notes: [any issues or observations]
```

### Red Flags to Escalate Immediately

| Symptom                                     | Action                                                           |
| ------------------------------------------- | ---------------------------------------------------------------- |
| Dashboard shows 0 everywhere                | Screenshot → #engineering immediately                            |
| Call Queue stuck on same 10 rows for 30 min | Check if you're logging outcomes correctly. If yes, escalate.    |
| "Error loading data" message                | Screenshot → Ctrl+Shift+R → If persists, escalate                |
| Signature queue shows 100+ items suddenly   | Normal after planner catches up. Flag attorney for batch review. |
| Same plaintiff appears multiple times       | Screenshot the duplicates → #engineering                         |

### End of Day Checklist

Before logging off:

1. ✅ All overdue calls attempted or rescheduled
2. ✅ Outcomes logged for every call made
3. ✅ Signature queue reviewed (flagged any urgent)
4. ✅ Quick Slack update posted to #daily-ops
5. ✅ Note any plaintiffs that need special attention tomorrow

---

## Pre-Production Safety TODOs

Before running the 900 import on **prod**, complete these items:

### DB Guardian Tasks (Owner: DB Guardian)

- [ ] **Freeze schema on prod:** Run `python -c "from tools.check_schema_consistency import freeze_schema; freeze_schema('prod')"` and compare hash to dev (`7911a45007df...`)
- [ ] **Run prod preflight:** `.\scripts\preflight_900.ps1 -SupabaseEnv prod` — all 4 checks green
- [ ] **Verify RLS enforcement:** `python -m tools.security_audit --env prod` — no `CRITICAL` findings
- [ ] **Confirm queue tables exist:** Check `pgmq.q_judgment_enrich`, `pgmq.q_enforce`, `pgmq.q_plaintiff_sync` present in prod
- [ ] **Test rollback procedure:** Document the `DELETE` cascade for a test `import_run_id` on dev first

### ETL Builder Tasks (Owner: ETL Builder)

- [ ] **Validate production CSV:** Run dry-run with actual 900-row file, confirm `parse_errors = []`
- [ ] **Verify `--enable-new-pipeline` flag:** Confirm it inserts to both `plaintiffs` and `core_judgments`
- [ ] **Test idempotency:** Run same CSV twice with `--commit`, confirm no duplicates created
- [ ] **Confirm queue job emission:** Verify `metadata.queued_jobs` in import result shows `enrich` entries

### Planner Tasks (Owner: Planner / Project Lead)

- [ ] **Sign off dev rehearsal:** Review dev import JSON, dashboard screenshots, and doctor output
- [ ] **Schedule prod window:** Pick a time with low dashboard traffic, notify stakeholders
- [ ] **Alert attorney:** Documents will hit signature queue within 2-4 hours of import
- [ ] **Brief Mom:** Walk through the "First 2 Hours" section above before go-live
- [ ] **Prepare rollback comms:** Draft Slack message template if emergency rollback needed

### Go/No-Go Checklist (All Owners)

| Item                          | Owner       | Status |
| ----------------------------- | ----------- | ------ |
| Prod preflight passes         | DB Guardian | ⬜     |
| Schema freeze matches dev     | DB Guardian | ⬜     |
| CSV dry-run clean             | ETL Builder | ⬜     |
| Dev rehearsal approved        | Planner     | ⬜     |
| Attorney briefed              | Planner     | ⬜     |
| Mom briefed                   | Planner     | ⬜     |
| Slack channel ready           | All         | ⬜     |
| Rollback procedure documented | DB Guardian | ⬜     |

**All boxes must be checked before running `--commit` on prod.**
