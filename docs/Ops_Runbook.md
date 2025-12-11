# Dragonfly Civil – Ops Runbook

**Daily Operations & Demo Guide for Non-Technical Operators**

_Version 1.0 | December 2025_

---

## Table of Contents

1. [Morning Check (Dev)](#1-morning-check-dev)
2. [Pre-Deploy Check (Prod)](#2-pre-deploy-check-prod)
3. [Railway Watch](#3-railway-watch)
4. [CI Green Policy](#4-ci-green-policy)
5. [Dad Demo Script](#5-dad-demo-script)
6. [Demo CSV Template](#6-demo-csv-template)
7. [Production Configuration Checklist](#7-production-configuration-checklist)

---

## 1. Morning Check (Dev)

Run this **every morning** before starting development work. It ensures your local environment and dev database are healthy.

### Command

Open PowerShell in the project folder and run:

```powershell
Set-Location C:\Users\mccab\dragonfly_civil
.\scripts\daily_dev_check.ps1
```

### What It Does

| Step | Action                                                   | Duration |
| ---- | -------------------------------------------------------- | -------- |
| 1/3  | Apply pending migrations to dev database                 | ~10 sec  |
| 2/3  | Run critical test suite (intake, enforcement, analytics) | ~30 sec  |
| 3/3  | Run system doctor health checks                          | ~10 sec  |

### What "Good" Looks Like ✅

```
=== [DRAGONFLY] Dev Health Check ===
Environment: dev

[1/3] Applying migrations...
  [OK] Migrations applied

[2/3] Running tests...
..........................................................  [100%]
  [OK] Tests passed

[3/3] System Doctor...
  [OK] Doctor checks passed

>>> Ready to Build. <<<
```

**Result:** All three checks show `[OK]`. You're good to code.

### What "Bad" Looks Like ❌

```
=== [DRAGONFLY] Dev Health Check ===
Environment: dev

[1/3] Applying migrations...
  [FAIL] Migration failed: relation "plaintiffs" already exists

OR

[2/3] Running tests...
  [FAIL] Tests failed: FAILED tests/test_workers_ingest.py::test_batch_processing
```

**What to do:**

1. **Migration failed:** Check `supabase/migrations/` for conflicts. A table or column may already exist. Contact engineering.
2. **Tests failed:** Read the error message. It tells you which test and why. Common causes:
   - Database connection issues → Check VPN or network
   - Schema mismatch → Run migrations first
   - Missing env vars → Run `.\scripts\load_env.ps1`
3. **Doctor failed:** Usually means a required view or table is missing. Check if migrations ran successfully.

---

## 2. Pre-Deploy Check (Prod)

Run this **before any demo, production change, or important meeting**. It verifies production is healthy.

### Command

```powershell
Set-Location C:\Users\mccab\dragonfly_civil
.\scripts\daily_prod_check.ps1
```

### What It Does

| Step | Action                                         | Duration |
| ---- | ---------------------------------------------- | -------- |
| 1/2  | Sync schema (apply pending migrations to prod) | ~15 sec  |
| 2/2  | Run health check / smoke test against prod     | ~10 sec  |

### What "Good" Looks Like ✅

```
=== [DRAGONFLY] PROD Status ===
[!] Running against PRODUCTION

[1/2] Syncing Schema...
  [OK] Schema synced

[2/2] Checking Pulse...
============================================================
Dragonfly Civil – Production Smoke Test
============================================================

1. Railway API health check
   URL: https://dragonflycivil-production-d57a.up.railway.app/api/health
   [OK] HTTP 200 – environment=prod

2. Postgres connection check
   [OK] Connection established

3. Query view: enforcement.v_enforcement_pipeline_status
   [OK] row_count=1

4. Query view: finance.v_portfolio_stats
   [OK] row_count=1

============================================================
ALL 4/4 CHECKS PASSED
============================================================
  [OK] Prod health check passed

>>> PROD IS HEALTHY. <<<
```

**Result:** Production is ready for demos or operations.

### What "Bad" Looks Like ❌

```
=== [DRAGONFLY] PROD Status ===
[!] Running against PRODUCTION

[1/2] Syncing Schema...
  [FAIL] Schema sync failed: connection refused
```

**What to do:**

1. **Connection refused:** Check if Supabase is accessible. May be a network issue or Supabase maintenance.
2. **Schema sync failed (other error):** Contact engineering immediately. Do NOT proceed with demos.
3. **Health check failed:** Production has an issue. Check Railway logs (see Section 3).

---

## 3. Railway Watch

Railway hosts our backend API and background workers. Here's how to monitor them.

### Services to Monitor

| Service Name         | What It Does                       | Start Command                                          |
| -------------------- | ---------------------------------- | ------------------------------------------------------ |
| `web` (Backend API)  | Powers the dashboard and API calls | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| `ingest-worker`      | Processes incoming CSV batches     | `python -m backend.workers.ingest_processor`           |
| `enforcement-worker` | Runs enforcement actions           | `python -m backend.workers.enforcement_engine`         |

### How to View Logs

1. Go to **[railway.app](https://railway.app)** and log in
2. Click on the **dragonfly_civil** project
3. Click on the service you want to check (e.g., `web`, `ingest-worker`)
4. Click the **Logs** tab

### What to Look For in Logs

| Log Message                         | Meaning                             | Status            |
| ----------------------------------- | ----------------------------------- | ----------------- |
| `"polling for jobs"`                | Worker is running, waiting for work | ✅ Healthy        |
| `"processing batch"`                | Worker is actively processing       | ✅ Healthy        |
| `"success"` or `"completed"`        | Task finished successfully          | ✅ Healthy        |
| `"error"` or `"failed"`             | Something went wrong                | ⚠️ Investigate    |
| `"crash"` or `"exited with code 1"` | Service crashed                     | 🔴 Restart needed |
| No logs for 5+ minutes              | Service may be frozen               | ⚠️ Investigate    |

### How to Restart a Worker

**Option A: Railway Dashboard (Recommended)**

1. Go to the service in Railway dashboard
2. Click the **three dots menu** (⋮) in the top-right
3. Click **Restart**
4. Wait 30 seconds for the service to come back online
5. Check logs to confirm it's running

**Option B: Redeploy**

1. Go to the service in Railway dashboard
2. Click **Deployments** tab
3. Find the most recent successful deployment
4. Click the **three dots menu** (⋮) → **Redeploy**

### When to Restart

- If logs show repeated errors
- If "processing" message appears but never shows "success"
- If no new logs appear for 10+ minutes during business hours
- After a known database migration

---

## 4. CI Green Policy

**Rule:** CI (Continuous Integration) must be GREEN before running any production deployment.

### What Is CI?

CI is our automated testing system that runs on every code push. It checks:

- All tests pass
- Code formatting is correct
- Database migrations work

### How to Check CI Status

**Quick Method: GitHub CLI**

```powershell
gh run list --limit 5
```

This shows the 5 most recent CI runs:

```
STATUS  TITLE                    WORKFLOW           BRANCH  EVENT  ID          ELAPSED  AGE
✓       Merge feature/new-view   Supabase Migrate   main    push   12345678    2m30s    5m
✓       Fix intake bug           Supabase Migrate   main    push   12345677    2m15s    1h
✗       WIP changes              Supabase Migrate   main    push   12345676    1m45s    2h
```

| Symbol | Meaning            |
| ------ | ------------------ |
| ✓      | Passed (GREEN)     |
| ✗      | Failed (RED)       |
| ○      | Running or pending |

### How to View Failed Run Logs

```powershell
gh run view 12345676 --log-failed
```

Or go to GitHub:

1. Visit **github.com/mccabetrow/dragonfly_civil**
2. Click **Actions** tab
3. Click on the failed run
4. Expand the failed step to see error details

### CI Must Be Green Before:

- ✅ Running `.\scripts\deploy_prod.ps1`
- ✅ Running `.\scripts\daily_prod_check.ps1`
- ✅ Demonstrating to clients or stakeholders
- ✅ Merging new features to main branch

### If CI Is Red:

1. **Do NOT deploy to production**
2. Check the error message (usually a test failure)
3. Contact engineering if you didn't make the change
4. Wait for the fix to be pushed and CI to turn green

---

## 5. Dad Demo Script

**Purpose:** Walk a non-technical CEO through the complete intake-to-enforcement flow.

### Prerequisites

- [ ] Production dashboard is accessible
- [ ] Run `.\scripts\daily_prod_check.ps1` — shows "PROD IS HEALTHY"
- [ ] Demo CSV file ready (see Section 6)
- [ ] Big monitor or screen share ready

### Step-by-Step Demo

#### Step 1: Open CEO Dashboard

1. Open your browser to: **https://dashboard.dragonflycivil.com/ceo/overview**
2. You should see the CEO Command Center with KPIs:
   - Actionable Liquidity
   - Active Cases
   - Recovery Velocity
   - Avg Collectability Score

**Say:** _"This is your daily command center. All the key numbers at a glance."_

#### Step 2: Open Intake Station

1. Open a new browser tab
2. Navigate to: **https://dashboard.dragonflycivil.com/intake**
3. You should see the Intake Station with:
   - Upload dropzone
   - Recent batch history table

**Say:** _"This is where new judgment data enters the system. You can drag-and-drop CSV files."_

#### Step 3: Upload Demo CSV

1. Have the demo CSV file ready on your desktop (see Section 6)
2. Drag the file into the dropzone, OR click "Browse" and select it
3. The file will upload and you'll see a new row appear in the batch table

**Say:** _"Watch — I just dropped 8 new judgments into the system."_

#### Step 4: Watch Processing

1. The batch status will show: **"queued"** → **"processing"** → **"completed"**
2. This typically takes 5-15 seconds per batch
3. Refresh the page if needed to see status updates

**Say:** _"The system is now validating the data, enriching it, and calculating collectability scores."_

#### Step 5: Return to CEO Dashboard

1. Switch back to the `/ceo/overview` tab
2. Refresh the page (F5 or click refresh)
3. Watch the metrics update:
   - Active Cases should increase by 8
   - Actionable Liquidity may increase (if high-value cases)

**Say:** _"Look — the CEO dashboard automatically reflects the new cases. No manual data entry needed."_

#### Step 6: Show Portfolio Explorer

1. Navigate to: **https://dashboard.dragonflycivil.com/portfolio/explorer**
2. Sort by "Created" date (newest first)
3. You should see the 8 new demo cases at the top

**Say:** _"Here's the detailed portfolio view. You can filter, sort, and drill into any case."_

#### Step 7: Show Enforcement Radar

1. Navigate to: **https://dashboard.dragonflycivil.com/radar**
2. The new cases should appear with their collectability scores
3. Filter to "BUY_CANDIDATE" to show high-value targets

**Say:** _"The Radar prioritizes which cases to pursue first based on collectability. Green scores = call first."_

### Demo Talking Points

- **Speed:** "Data goes from CSV to actionable in under 30 seconds."
- **Automation:** "Enrichment and scoring happen automatically — no manual research."
- **Prioritization:** "The system tells you who to call first, not the other way around."
- **Real-time:** "Dashboards update live. What you see is what you have."

---

## 6. Demo CSV Template

This CSV matches the exact schema expected by the Intake Station. Copy this content into a file named `demo_intake_batch.csv`.

### CSV Content

```csv
LeadID,PlaintiffName,Email,Phone,IndexNumber,Court,County,State,JudgmentDate,JudgmentAmount,DefendantName,Status
DEMO-001,Acme Collections LLC,contact@acmecollections.com,212-555-0101,2024-CV-1001,Kings County Civil Court,Kings,NY,2024-06-15,45000.00,John Smith,Active
DEMO-002,Metro Recovery Services,intake@metrorecovery.com,718-555-0202,2024-CV-1002,Queens County Civil Court,Queens,NY,2024-05-22,28500.00,Jane Doe,Active
DEMO-003,Empire State Debt Solutions,legal@empiredebt.com,516-555-0303,2024-CV-1003,Nassau County Civil Court,Nassau,NY,2024-07-08,67250.00,Robert Johnson,Active
DEMO-004,Liberty Judgment Buyers,info@libertyjb.com,917-555-0404,2024-CV-1004,New York County Civil Court,New York,NY,2024-04-11,12800.00,Maria Garcia,Active
DEMO-005,Hudson Valley Collections,hvcc@hvcolections.com,845-555-0505,2024-CV-1005,Westchester County Civil Court,Westchester,NY,2024-08-19,95000.00,William Brown,Active
DEMO-006,Brooklyn Asset Recovery,bar@brooklynasset.com,347-555-0606,2024-CV-1006,Kings County Civil Court,Kings,NY,2024-03-28,18750.00,Patricia Davis,Active
DEMO-007,Manhattan Judgment Group,mjg@mjglaw.com,646-555-0707,2024-CV-1007,New York County Civil Court,New York,NY,2024-09-05,52400.00,Michael Wilson,Active
DEMO-008,Queens Boulevard Partners,qbp@queensblvd.com,718-555-0808,2024-CV-1008,Queens County Civil Court,Queens,NY,2024-02-14,34200.00,Jennifer Martinez,Active
```

### Column Reference

| Column         | Format                 | Example                     | Required |
| -------------- | ---------------------- | --------------------------- | -------- |
| LeadID         | Unique identifier      | DEMO-001                    | ✅       |
| PlaintiffName  | Company or person      | Acme Collections LLC        | ✅       |
| Email          | Valid email            | contact@acmecollections.com | ✅       |
| Phone          | 10 digits or formatted | 212-555-0101                | ✅       |
| IndexNumber    | Case/docket number     | 2024-CV-1001                | ✅       |
| Court          | Full court name        | Kings County Civil Court    | ✅       |
| County         | County name            | Kings                       | ✅       |
| State          | 2-letter state code    | NY                          | ✅       |
| JudgmentDate   | YYYY-MM-DD             | 2024-06-15                  | ✅       |
| JudgmentAmount | Decimal, no $          | 45000.00                    | ✅       |
| DefendantName  | Debtor name            | John Smith                  | Optional |
| Status         | Active/Closed          | Active                      | Optional |

### Date Formats Accepted

The system accepts multiple date formats:

- `YYYY-MM-DD` (preferred): `2024-06-15`
- `MM/DD/YYYY`: `06/15/2024`
- `DD/MM/YYYY`: `15/06/2024`

### Tips

- Save as UTF-8 CSV
- No special characters in names (avoid ™, ®, etc.)
- Phone numbers: digits only or standard US format
- Amounts: numbers only, no $ or commas in the raw value

---

## 7. Production Configuration Checklist

Before running the demo in production, verify these settings are configured:

### Vercel (Frontend Dashboard)

| Environment Variable     | Description                     | Where to Set                 |
| ------------------------ | ------------------------------- | ---------------------------- |
| `VITE_API_BASE_URL`      | Railway backend URL with `/api` | Vercel → Settings → Env Vars |
| `VITE_DRAGONFLY_API_KEY` | API key (must match Railway)    | Vercel → Settings → Env Vars |

**Check:** Go to Vercel dashboard → Project → Settings → Environment Variables

### Railway (Backend API)

| Environment Variable   | Description                     | Where to Set                  |
| ---------------------- | ------------------------------- | ----------------------------- |
| `DRAGONFLY_API_KEY`    | API key (must match Vercel)     | Railway → Service → Variables |
| `SUPABASE_URL`         | Production Supabase project URL | Railway → Service → Variables |
| `SUPABASE_SERVICE_KEY` | Supabase service role key       | Railway → Service → Variables |
| `ALLOWED_ORIGINS`      | Must include Vercel domain      | Railway → Service → Variables |

**CORS Check:** Ensure `ALLOWED_ORIGINS` includes:

- `https://dashboard.dragonflycivil.com`
- `https://*.vercel.app` (for preview deploys)

### Supabase (Database)

| Setting            | Verification                       |
| ------------------ | ---------------------------------- |
| RLS Policies       | All tables should have RLS enabled |
| API Key            | Service key has read/write access  |
| Connection Pooling | Transaction mode for workers       |

### Quick Verification Commands

```powershell
# Check CI is green
gh run list --limit 3

# Check prod health
.\scripts\daily_prod_check.ps1

# Check backend is responding
curl https://dragonflycivil-production-d57a.up.railway.app/api/health
```

### If Demo Fails

| Symptom                            | Likely Cause              | Fix                                          |
| ---------------------------------- | ------------------------- | -------------------------------------------- |
| Dashboard shows "401 Unauthorized" | API key mismatch          | Verify VITE_DRAGONFLY_API_KEY = Railway key  |
| CORS error in console              | Missing allowed origin    | Add Vercel domain to ALLOWED_ORIGINS         |
| "Failed to fetch" error            | Backend down or wrong URL | Check Railway service is running             |
| CSV upload hangs                   | Ingest worker stopped     | Restart ingest-worker in Railway             |
| Metrics don't update               | View refresh issue        | Hard refresh (Ctrl+F5) or check backend logs |

---

## Quick Reference Card

### Daily Commands

```powershell
# Morning (before coding)
Set-Location C:\Users\mccab\dragonfly_civil
.\scripts\daily_dev_check.ps1

# Before demo or prod changes
.\scripts\daily_prod_check.ps1

# Check CI status
gh run list --limit 5
```

### Key URLs

| Resource           | URL                                                     |
| ------------------ | ------------------------------------------------------- |
| Dashboard (Prod)   | https://dashboard.dragonflycivil.com                    |
| CEO Overview       | https://dashboard.dragonflycivil.com/ceo/overview       |
| Intake Station     | https://dashboard.dragonflycivil.com/intake             |
| Portfolio Explorer | https://dashboard.dragonflycivil.com/portfolio/explorer |
| Enforcement Radar  | https://dashboard.dragonflycivil.com/radar              |
| Railway Dashboard  | https://railway.app                                     |
| GitHub Actions     | https://github.com/mccabetrow/dragonfly_civil/actions   |

### Emergency Contacts

| Issue             | Action                                        |
| ----------------- | --------------------------------------------- |
| Dashboard down    | Check Vercel status, then contact engineering |
| API errors (500s) | Check Railway logs, restart if needed         |
| Database issues   | Check Supabase dashboard, contact engineering |
| CI stuck red      | Do NOT deploy. Wait for fix from engineering. |

---

_Last updated: December 11, 2025_
