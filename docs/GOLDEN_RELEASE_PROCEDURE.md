# Golden Release Procedure

> **The Definitive Guide to Production Deployment and Rollback**
>
> This document defines the exact steps for the "Golden Release" and "Perfect Rollback."
> Deviation from this procedure requires explicit approval from the Platform Lead.

---

## Table of Contents

1. [Pre-Release Requirements](#pre-release-requirements)
2. [Golden Release Sequence](#golden-release-sequence)
3. [Perfect Rollback Procedure](#perfect-rollback-procedure)
4. [Emergency Procedures](#emergency-procedures)
5. [Post-Release Monitoring](#post-release-monitoring)

---

## Pre-Release Requirements

Before initiating any release, ensure:

- [ ] All code is merged to `main` branch
- [ ] All tests pass in CI (GitHub Actions)
- [ ] `.env.prod` is configured with production credentials
- [ ] Railway dashboard access is available
- [ ] Database backup was taken in the last 24 hours
- [ ] Release notes are documented

### Required Access

| Resource           | Purpose                         |
| ------------------ | ------------------------------- |
| Railway Dashboard  | Scale workers, deploy services  |
| Supabase Dashboard | Database monitoring (read-only) |
| GitHub             | Verify commit SHA               |
| `.env.prod`        | Production credentials          |

---

## Golden Release Sequence

### Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    GOLDEN RELEASE SEQUENCE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐  │
│  │  FREEZE   │───▶│ PREFLIGHT │───▶│  MIGRATE  │───▶│  VERIFY   │  │
│  │ Workers=0 │    │   Gate    │    │    DB     │    │ Contract  │  │
│  └───────────┘    └───────────┘    └───────────┘    └───────────┘  │
│                                                            │        │
│                                                            ▼        │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐  │
│  │  SCALE    │◀───│   SMOKE   │◀───│  DEPLOY   │◀───│  VERIFY   │  │
│  │ Workers=N │    │   Tests   │    │   Code    │    │  Contract │  │
│  └───────────┘    └───────────┘    └───────────┘    └───────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Step-by-Step Procedure

#### STEP 1: FREEZE (Scale Workers to 0)

```powershell
# In Railway Dashboard:
# Workers → Settings → Scale to 0
```

**Why:** Prevents in-flight jobs during migration. Workers using old RPC signatures may fail against new schema.

**Verification:** Railway Dashboard shows "0 instances" for worker service.

---

#### STEP 2: PREFLIGHT (Run Deployment Gate)

```powershell
# Run the interactive release commander
.\scripts\release_commander.ps1

# Or run preflight manually
.\scripts\gate_preflight.ps1
```

**What it checks:**

- `RPC-CONTRACT`: Database RPC signatures match code expectations
- `WORKER-CONTRACT`: Worker code uses correct RPC signatures
- `CONFIG-CONTRACT`: Configuration logic is sound
- `UNIT-TESTS`: All non-integration tests pass

**STOP if any Hard Gate fails.** Fix the issue before proceeding.

---

#### STEP 3: MIGRATE (Apply Database Migrations)

```powershell
# In a separate terminal:
$env:SUPABASE_MODE = "prod"
.\scripts\deploy_db_prod.ps1
```

**What it does:**

- Applies all pending migrations from `supabase/migrations/`
- Runs in a transaction (all-or-nothing)

**Expected output:** `All migrations applied successfully`

---

#### STEP 4: VERIFY (Contract Truth Check)

```powershell
python scripts/verify_db_contract.py --env prod
```

**What it checks:**

- All canonical RPCs exist (`claim_pending_job`, `queue_job`, etc.)
- Each RPC has exactly 1 signature (no overloads)
- SECURITY DEFINER is set correctly

**ROLLBACK if verification fails.** See [Perfect Rollback Procedure](#perfect-rollback-procedure).

---

#### STEP 5: DEPLOY (Push Code to Railway)

```
In Railway Dashboard:
1. API Service → Trigger redeploy (or push to main)
2. Worker Service → Scale to 1
3. Wait for both services to show "Running"
```

**Verification:** Check Railway logs for successful startup.

---

#### STEP 6: SMOKE (Run Production Smoke Tests)

```powershell
.\scripts\smoke_production.ps1 -ApiBaseUrl "https://your-api.railway.app"
```

**What it tests:**

- API health endpoint responds
- Batch ingest flow works end-to-end
- Workers process jobs successfully

**If smoke fails:** Review logs carefully. You may proceed with caution or rollback.

---

#### STEP 7: SCALE (Scale Workers to Production Level)

```
In Railway Dashboard:
Workers → Settings → Scale to 2-4 (depending on load)
```

**Post-scale verification:**

- Check worker logs for successful heartbeats
- Verify job processing is working

---

## Perfect Rollback Procedure

### When to Rollback

- Smoke tests fail critically
- Workers crash repeatedly
- Database contract verification fails
- Production errors spike after deploy

### Rollback Steps

#### STEP 1: FREEZE (Immediate)

```
Railway Dashboard:
- Workers → Scale to 0
- API → Scale to 0 (if necessary)
```

**Why:** Stop the bleeding. Prevent further damage.

---

#### STEP 2: REDEPLOY PREVIOUS CODE

```
Railway Dashboard:
1. API Service → Deployments → Click on previous successful deploy
2. Click "Redeploy"
3. Repeat for Worker service
```

**Alternative (Git):**

```bash
git revert HEAD
git push origin main
```

---

#### STEP 3: DATABASE ROLLBACK (If Needed)

**For Dev Environment:**

```powershell
# CAUTION: This resets ALL data - always use explicit --db-url (Windows pooler issue)
.\scripts\db_push.ps1 -SupabaseEnv dev
# Or for full reset (destructive):
# supabase db reset --db-url $env:SUPABASE_DB_URL_DEV
```

**For Production (Specific Rollback):**

1. Locate the rollback migration:

   ```
   supabase/migrations/rollback_<timestamp>_to_<target>.sql
   ```

2. Apply it:

   ```powershell
   $env:SUPABASE_MODE = "prod"
   .\scripts\db_push.ps1 -SupabaseEnv prod
   ```

3. Or execute directly:
   ```powershell
   psql "$env:SUPABASE_DB_URL" -f supabase/migrations/rollback_XXX.sql
   ```

---

#### STEP 4: VERIFY ROLLBACK

```powershell
python scripts/verify_db_contract.py --env prod
```

**Expected:** All canonical RPCs exist with correct signatures matching the OLD code.

---

#### STEP 5: RESTORE SERVICES

```
Railway Dashboard:
1. Scale API to 1
2. Verify API is healthy
3. Scale Workers to 1
4. Monitor logs for 15 minutes
```

---

## Emergency Procedures

### Critical Production Outage

1. **Assess:** What's broken? DB? API? Workers?
2. **Freeze:** Scale all workers to 0
3. **Communicate:** Notify team immediately
4. **Rollback:** Follow [Perfect Rollback Procedure](#perfect-rollback-procedure)
5. **Post-mortem:** Document what happened

### Database Corruption

1. **Freeze:** Scale everything to 0
2. **Backup:** Take immediate snapshot if possible
3. **Contact:** Supabase support if necessary
4. **Restore:** Use point-in-time recovery or backup

### API Unresponsive

1. **Check:** Railway service status
2. **Logs:** Review for errors
3. **Restart:** Trigger redeploy
4. **Rollback:** If restart doesn't help

---

## Post-Release Monitoring

### First 15 Minutes

- [ ] Watch Railway logs for errors
- [ ] Check worker heartbeats in database
- [ ] Verify dashboard loads correctly
- [ ] Test one end-to-end flow manually

### First Hour

- [ ] Monitor error rates
- [ ] Check job processing latency
- [ ] Verify no queue buildup
- [ ] Confirm email/notification systems work

### First 24 Hours

- [ ] Review overnight job processing
- [ ] Check scheduled task execution
- [ ] Verify backup completed
- [ ] Update release notes with any issues

---

## Quick Reference

### Essential Commands

| Action              | Command                                            |
| ------------------- | -------------------------------------------------- |
| Interactive release | `.\scripts\release_commander.ps1`                  |
| Preflight gate      | `.\scripts\gate_preflight.ps1`                     |
| Deploy DB (prod)    | `.\scripts\deploy_db_prod.ps1`                     |
| Verify contract     | `python scripts/verify_db_contract.py --env prod`  |
| Smoke test          | `.\scripts\smoke_production.ps1 -ApiBaseUrl <url>` |
| Doctor check        | `python -m tools.doctor --env prod`                |

### Emergency Contacts

| Role             | Responsibility                        |
| ---------------- | ------------------------------------- |
| On-Call Engineer | First responder for production issues |
| Database Admin   | Schema rollback authority             |
| Platform Lead    | Final approval for emergency changes  |

---

_Last Updated: 2025-12-21_
_Document Version: 1.0_
