# Dragonfly Demo Walkthrough (900+ Plaintiff Scale)

## 1. Prep Checklist

- Confirm `.env` includes `SUPABASE_*_DEV/PROD`, `SUPABASE_DB_URL_*`, and `N8N_API_KEY`.
- Run the environment loader once per shell:
  ```powershell
  cd C:\Users\mccab\dragonfly_civil
  .\scripts\load_env.ps1
  ```
- Activate the virtual environment (`.\.venv\Scripts\Activate.ps1`) or ensure `python` resolves inside the repo.

## 2. Health Checks Before Every Demo

1. **Dev preflight** – validates migrations, doctor checks, pytest, and Supabase smoke probes without touching prod:
   ```powershell
   $env:SUPABASE_MODE = 'dev'
   .\scripts\preflight_dev.ps1
   ```
2. **Prod preflight** – same checklist against prod credentials (read-only db push checks, config, security, doctor_all, pytest):
   ```powershell
   $env:SUPABASE_MODE = 'prod'
   .\scripts\preflight_prod.ps1
   ```
3. Success criteria: both scripts exit 0 and print `Preflight complete. All checks are green.`. If a step fails, re-run after fixing the referenced tool.

## 3. Reset + Smoke the Demo Dataset

Run the combined reset + smoke workflow so the dashboard story always matches the migrations you just tested:

```powershell
$env:SUPABASE_MODE = 'dev'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo_reset_and_smoke.ps1
```

- Script actions: wipes demo tables, reseeds plaintiffs/judgments, runs collectors/workers once, and asserts plaintiff/enforcement smoke counts.
- Exit 0 with `[OK] demo_reset_and_smoke complete` means you can proceed.

## 4. Run the Pipeline Demo & Interpret Scores

1. Execute the prod-safe pipeline helper:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo_pipeline_prod.ps1
   ```
2. Internals: `tools.demo_pipeline` upserts `DEMO-0001`, enqueues enrichment (pgmq `enrich` queue), waits for a worker result, then logs the collectability bundle.
3. Sample payload:
   ```json
   {
     "case_number": "DEMO-0001",
     "collectability_score": 0.62,
     "contactability_score": 0.8,
     "phones": ["+1-303-555-1234"],
     "emails": ["demo-0001.301@demo.dragonfly"],
     "employers": ["Stub Employer DEMO-0001"]
   }
   ```
4. Talking points:
   - `collectability_score ≥ 0.6` = legal should prep enforcement.
   - `contactability_score ≥ 0.7` = outreach sequences will hit live contacts.
   - Empty arrays → enrichment workers offline; restart via `scripts/run_workers.ps1` or `make watcher`.

## 5. Plaintiff / “Dad” Demo Script (Route Order)

1. **Overview** – headline metrics + “Do These First” queue answer “What moved today?”
2. **Exec Dashboard** – investor view; tiles + chart show dollars collected vs. pipeline.
3. **Collectability** – tier cards + filters prove we know who to call next.
4. **Pipeline** – stage cards quantify investigation → enforcement flow.
5. **Call Queue** – log an outcome so the row drops; show refresh + spinner.
6. **Cases** – search `DEMO-CASE-001`, open drawer, highlight judgment snapshot, research, FOIL responses.
7. **Enforcement** – link collectability tiers with enforcement stage updates.
8. **Ops Console** – TaskPlanner metrics + ingestion stats reassure ops.
9. **Help** – runbooks (Dad, Mom, Ops) match the sections they follow daily.
10. **Closing line** – “Because preflight + demo_reset ran minutes ago, what you see here is exactly what prod would show once we swap credentials.”

## 6. Common Failure Modes & Quick Fixes

- **Preflight failure**
  - Symptom: `db_push checks`, `config_check`, `security_audit`, or `doctor_all` fails.
  - Fix: rerun `scripts/load_env.ps1`, confirm Supabase credentials, and re-run the failing Python module directly for detail.
- **Demo reset errors**
  - Symptom: `demo_reset_and_smoke` stops at collector/worker step.
  - Fix: inspect `logs\` output, then retry after running `scripts/run_workers.ps1`.
- **Pipeline timeout**
  - Symptom: `demo_pipeline_prod` prints `[WARN] No enrichment run detected`.
  - Fix: start workers (`make watcher`) or run `python -m tools.ensure_queues_exist` then rerun.
- **Dashboard build warnings**
  - Symptom: `npm run build` logs new warnings.
  - Fix: install deps, rerun `npm run build`, ensure only the known chunk-size warning remains.
- **n8n / API auth issues**
  - Symptom: outreach logs empty.
  - Fix: refresh `N8N_API_KEY` in `.env` and the n8n vault, then re-run preflight.

## 7. Next Steps After the Demo

- Reset demo artifacts again (Section 3) so the next operator starts clean.
- Capture feedback and update `docs/dragonfly_operating_model.md` plus runbooks with new talking points.
- Schedule integration follow-ups: copy prod Supabase creds into secrets, re-run `scripts/preflight_prod.ps1`, and plan the first plaintiff import using `python -m etl.src.plaintiff_importer --commit` once approvals land.
