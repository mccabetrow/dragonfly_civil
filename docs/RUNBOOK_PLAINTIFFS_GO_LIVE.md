# PLAINTIFFS GO-LIVE: DRAGONFLY

**Operator**: Dad  
**Last Updated**: 2026-01-11  
**Time Required**: ~10 minutes

---

## PRE-FLIGHT CHECKLIST

Before touching Railway, confirm these on your machine:

- [ ] Connected to internet
- [ ] Have Railway dashboard access (railway.app)
- [ ] Have Supabase dashboard access (supabase.com)

---

## STEP 1: SCALE UP SERVICES (Railway)

Open: **https://railway.app** → Select **dragonfly-civil** project

### 1.1 Start API First

1. Click **dragonfly-api** service
2. Click **Settings** tab
3. Find **Replicas** → Set to **1**
4. Click **Deploy** (top right, purple button)
5. Wait for green checkmark (~2 min)

### 1.2 Start Ingest Worker

1. Click **dragonfly-worker-ingest** service
2. Settings → Replicas → **1**
3. Deploy → Wait for green checkmark

### 1.3 Start Enforcement Worker

1. Click **dragonfly-worker-enforcement** service
2. Settings → Replicas → **1**
3. Deploy → Wait for green checkmark

---

## STEP 2: HEALTH CHECK

Open each URL in browser. Look for the result.

| URL                                            | ✅ PASS                    | ❌ FAIL                 |
| ---------------------------------------------- | -------------------------- | ----------------------- |
| `https://dragonfly-api.up.railway.app/healthz` | Shows `{"status":"ok"}`    | Any error or blank page |
| `https://dragonfly-api.up.railway.app/readyz`  | Shows `{"status":"ready"}` | Shows 503 or error      |

**If both PASS** → Go to Step 3  
**If either FAIL** → Go to Troubleshooting below

---

## STEP 3: RUN GO/NO-GO GATE

On your computer, open **PowerShell** in the project folder and run:

```powershell
$env:SUPABASE_MODE='prod'; .\.venv\Scripts\python.exe -m tools.prod_gate --env prod --strict
```

### Reading the Output

| You See                     | Meaning                           |
| --------------------------- | --------------------------------- |
| `ALL CHECKS PASSED (5/5)`   | ✅ **GO** - Safe to proceed       |
| `CHECKS FAILED` or red text | ❌ **NO-GO** - Stop, call Patrick |

---

## TROUBLESHOOTING QUICK FIXES

### `/readyz` returns 503

**Meaning**: Database not connected yet  
**Fix**: Wait 60 seconds, refresh. If still 503 after 2 minutes → call Patrick

### "server_login_retry" in logs

**Meaning**: Database is waking up (normal for first request)  
**Fix**: Wait 30 seconds, try again. Usually self-heals.

### "password authentication failed"

**Meaning**: Wrong database password  
**Fix**: **STOP** - Do not retry. Call Patrick immediately.

### "port 5432" error or "wrong port"

**Meaning**: Using migration URL instead of pooler  
**Fix**: **STOP** - Configuration error. Call Patrick.

### "sslmode" missing or disabled

**Meaning**: Insecure connection attempted  
**Fix**: **STOP** - Call Patrick.

### "ops schema" access denied

**Meaning**: Dashboard trying to read internal tables  
**Fix**: This is expected for anon users. If API is healthy, ignore.

---

## FINAL GO-LIVE CONFIRMATION

When all checks pass:

```
╔══════════════════════════════════════════════════════════════╗
║  ✅ SYSTEM READY FOR PLAINTIFF OPERATIONS                   ║
║                                                              ║
║  API:         HEALTHY                                        ║
║  Ingest:      HEALTHY                                        ║
║  Enforcement: HEALTHY                                        ║
║  Database:    CONNECTED                                      ║
║                                                              ║
║  → Plaintiffs can now be imported and processed              ║
╚══════════════════════════════════════════════════════════════╝
```

---

## EMERGENCY SHUTDOWN

If something goes wrong after go-live:

1. Railway → Each service → Settings → Replicas → **0**
2. Deploy each
3. Call Patrick

---

## CONTACTS

| Issue                          | Contact                   |
| ------------------------------ | ------------------------- |
| Any error you don't understand | Patrick (text first)      |
| Railway won't load             | Check status.railway.app  |
| Supabase won't load            | Check status.supabase.com |
