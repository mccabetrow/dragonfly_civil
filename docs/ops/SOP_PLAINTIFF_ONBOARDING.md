# Dragonfly Plaintiff Onboarding – Operator SOP

**Date:** 2026-01-10  
**Audience:** CEO / Non-Engineer Operator  
**Goal:** Safely bring production online and begin plaintiff intake

---

## Pre-Flight: Run the GO/NO-GO Script

Before touching Railway, run this from your laptop (PowerShell):

```powershell
cd C:\Users\mccab\dragonfly_civil
.\scripts\dad_go.ps1
```

| Result                   | Meaning                            | Action                            |
| ------------------------ | ---------------------------------- | --------------------------------- |
| ✅ **ALL CHECKS PASSED** | System is healthy, safe to proceed | Continue to Railway steps         |
| ❌ **ANY CHECK FAILED**  | Something is misconfigured         | Stop. Call Ryan before proceeding |

---

## Railway Click-Path (Production)

### Step 1: Verify API Health

1. Open **Railway Dashboard** → Project: `dragonfly-civil`
2. Click service: **dragonfly-api**
3. Click the public URL (ends in `.up.railway.app`)
4. Append `/readyz` to the URL → should show `{"status":"ok"}`

### Step 2: Start Workers (if stopped)

1. In Railway, click service: **dragonfly-worker-ingest**
2. If status shows "Crashed" or "Stopped" → click **Redeploy**
3. Repeat for **dragonfly-worker-enforcement**

### Step 3: Confirm All Green

- All 3 services show **"Running"** with green dots
- `/readyz` returns `{"status":"ok"}`

---

## Troubleshooting

### Problem: `/readyz` returns 503 or "unhealthy"

| Check            | Fix                                                             |
| ---------------- | --------------------------------------------------------------- |
| Service crashed? | Click **Redeploy** in Railway                                   |
| Database down?   | Check Supabase dashboard → Project → Database → is it "Active"? |
| Wrong port?      | See "Forbidden Env Vars" below                                  |

**If still broken:** Copy the last 20 lines from Railway logs → send to Ryan.

---

### Problem: Logs show `server_login_retry`

This means **bad database password** or **wrong credentials**.

| Step | Action                                                     |
| ---- | ---------------------------------------------------------- |
| 1    | Go to Railway → **dragonfly-api** → **Variables**          |
| 2    | Find `SUPABASE_DB_URL`                                     |
| 3    | Verify it matches the Supabase dashboard connection string |
| 4    | Ensure port is **6543** (not 5432)                         |
| 5    | Click **Redeploy**                                         |

---

## Environment Variables: What Must Exist vs What Must NOT

### ✅ REQUIRED (must be set in Railway)

| Variable                    | What It Is                                   |
| --------------------------- | -------------------------------------------- |
| `SUPABASE_URL`              | Your Supabase project URL                    |
| `SUPABASE_SERVICE_ROLE_KEY` | The long secret key from Supabase            |
| `SUPABASE_DB_URL`           | Database connection (must use port **6543**) |
| `DRAGONFLY_API_KEY`         | API authentication key                       |
| `ENVIRONMENT`               | Must be `prod` for production                |

### 🚫 FORBIDDEN (must NOT exist in Railway runtime)

| Variable                  | Why It's Dangerous                     |
| ------------------------- | -------------------------------------- |
| `SUPABASE_MIGRATE_DB_URL` | Leaks direct DB access; causes crashes |

**If you see `SUPABASE_MIGRATE_DB_URL` in any Railway service → DELETE IT immediately.**

---

## Quick Reference Card

| Task                      | How                                                                      |
| ------------------------- | ------------------------------------------------------------------------ |
| Check system health       | Run `.\scripts\dad_go.ps1` locally                                       |
| View live logs            | Railway → Service → **Logs** tab                                         |
| Restart a crashed service | Railway → Service → **Redeploy**                                         |
| Verify API is up          | Visit `https://[your-url].up.railway.app/readyz`                         |
| Emergency stop            | Railway → Service → **Settings** → **Remove Service** (use with caution) |

---

## Go-Live Checklist

- [ ] `dad_go.ps1` shows ALL CHECKS PASSED
- [ ] Railway: dragonfly-api is Running
- [ ] Railway: dragonfly-worker-ingest is Running
- [ ] Railway: dragonfly-worker-enforcement is Running
- [ ] `/readyz` returns `{"status":"ok"}`
- [ ] No `SUPABASE_MIGRATE_DB_URL` in any service variables

**All boxes checked? You are cleared for plaintiff onboarding.**

---

_Questions? Call Ryan. Don't guess._
