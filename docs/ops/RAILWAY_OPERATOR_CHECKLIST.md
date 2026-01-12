# Railway Operator Checklist: Database Variables

> **Purpose**: Prevent production outages from misconfigured database connection strings  
> **Audience**: Platform engineers with Railway console access  
> **Last Updated**: 2025-01-XX

---

## Variable Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  SHARED VARIABLES (Project-Level)                               │
│  ─────────────────────────────────────────                      │
│  Inherited by ALL services unless overridden                    │
│  ⚠️ Changes here affect dragonfly-api, worker-ingest,           │
│     worker-enforcement, and any future services                 │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  ┌──────────┐          ┌──────────┐          ┌──────────┐
  │ API      │          │ Ingest   │          │ Enforce  │
  │ Service  │          │ Worker   │          │ Worker   │
  └──────────┘          └──────────┘          └──────────┘
```

---

## ✅ Required Shared Variables

These MUST be set at **Project Level** (Shared Variables):

| Variable          | Required Value                                                                                        | Notes                  |
| ----------------- | ----------------------------------------------------------------------------------------------------- | ---------------------- |
| `SUPABASE_DB_URL` | `postgresql://postgres.[REF]:[PASS]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require` | **ONLY** pooler URL    |
| `SUPABASE_URL`    | `https://[REF].supabase.co`                                                                           | REST API base URL      |
| `SUPABASE_KEY`    | `eyJ...` (service_role key)                                                                           | Service role, not anon |
| `SUPABASE_MODE`   | `prod`                                                                                                | Must be exactly `prod` |
| `PORT`            | `8000`                                                                                                | Standard port          |

---

## ⛔ NEVER Override Per-Service

These variables must **NEVER** be set at service level:

| Variable                  | Why It's Dangerous                         |
| ------------------------- | ------------------------------------------ |
| `SUPABASE_DB_URL`         | Connection pooling chaos, auth lockouts    |
| `SUPABASE_KEY`            | Services with different keys = split-brain |
| `SUPABASE_MODE`           | Mixing prod/dev = data corruption          |
| `SUPABASE_MIGRATE_DB_URL` | **Must not exist in any runtime service**  |

### How to Verify No Overrides Exist

```powershell
# Check each service for overrides
$services = @("dragonfly-api", "dragonfly-worker-ingest", "dragonfly-worker-enforcement")

foreach ($svc in $services) {
    Write-Host "=== $svc ===" -ForegroundColor Cyan
    railway variables -s $svc | Select-String "SUPABASE|DATABASE"
}
```

**Expected output**: Only shared variables, no service-specific duplicates.

---

## 🔒 Variable Lock Checklist

Before any deployment:

- [ ] `SUPABASE_DB_URL` is at **Project Level** (not per-service)
- [ ] URL contains `.pooler.supabase.com` (not direct connection)
- [ ] Port is `6543` (not `5432`)
- [ ] URL ends with `?sslmode=require`
- [ ] Username is `postgres.[PROJECT_REF]` (not just `postgres`)
- [ ] No service has `SUPABASE_MIGRATE_DB_URL` set
- [ ] All services show `SUPABASE_MODE=prod`

---

## ⚠️ Dangerous Operations

### DO NOT:

1. **Copy a service and inherit its overrides**

   - Use "Create New Service" not "Duplicate"
   - Overrides may silently carry over

2. **Edit variables while services are running**

   - Scale to 0 first
   - Update variable
   - Scale back to 1

3. **Use Railway UI "Quick Add" for database variables**

   - It may create service-level not project-level

4. **Mix direct and pooler connections**
   - All runtime services use pooler (6543)
   - Direct connections (5432) only for migrations

---

## Pre-Deploy Verification Script

Run this before any production deployment:

```powershell
# Save as: scripts/verify_railway_vars.ps1

Write-Host "🔍 Railway Variable Audit" -ForegroundColor Cyan

# Check shared variable exists
$sharedUrl = railway variables | Select-String "^SUPABASE_DB_URL="
if (-not $sharedUrl) {
    Write-Host "⛔ SUPABASE_DB_URL not in shared variables!" -ForegroundColor Red
    exit 1
}

# Validate URL format
$url = $sharedUrl -replace "SUPABASE_DB_URL=", ""
if ($url -notmatch "pooler\.supabase\.com:6543") {
    Write-Host "⛔ URL doesn't use pooler:6543!" -ForegroundColor Red
    exit 1
}

# Check for service overrides
$services = @("dragonfly-api", "dragonfly-worker-ingest", "dragonfly-worker-enforcement")
$hasOverrides = $false

foreach ($svc in $services) {
    $svcVars = railway variables -s $svc 2>&1
    if ($svcVars -match "SUPABASE_DB_URL=") {
        Write-Host "⛔ $svc has SUPABASE_DB_URL override!" -ForegroundColor Red
        $hasOverrides = $true
    }
    if ($svcVars -match "SUPABASE_MIGRATE_DB_URL=") {
        Write-Host "⛔ $svc has SUPABASE_MIGRATE_DB_URL (forbidden)!" -ForegroundColor Red
        $hasOverrides = $true
    }
}

if ($hasOverrides) {
    Write-Host "`n⛔ DEPLOY BLOCKED: Fix service-level overrides first" -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ Railway variables validated for production" -ForegroundColor Green
```

---

## Recovery: Removing Bad Overrides

If a service has incorrect overrides:

```bash
# 1. Scale service to 0
railway service update SERVICE_NAME --replicas 0

# 2. Remove the override
railway variables unset SUPABASE_DB_URL -s SERVICE_NAME
railway variables unset SUPABASE_MIGRATE_DB_URL -s SERVICE_NAME

# 3. Verify it now inherits shared
railway variables -s SERVICE_NAME | Select-String "SUPABASE"

# 4. Scale back up
railway service update SERVICE_NAME --replicas 1
```

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────┐
│  RAILWAY DB VARIABLES - QUICK REFERENCE                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  SHARED (Project-Level):                                    │
│    ✅ SUPABASE_DB_URL     → pooler:6543 only                │
│    ✅ SUPABASE_URL        → https://ref.supabase.co         │
│    ✅ SUPABASE_KEY        → service_role key                │
│    ✅ SUPABASE_MODE       → prod                            │
│                                                             │
│  PER-SERVICE:                                               │
│    ✅ PORT               → 8000 (if needed)                 │
│    ✅ WORKER_TYPE        → ingest | enforcement             │
│    ⛔ SUPABASE_*         → NEVER override!                  │
│                                                             │
│  FORBIDDEN EVERYWHERE:                                      │
│    ⛔ SUPABASE_MIGRATE_DB_URL → migrations only, not runtime│
│    ⛔ DATABASE_URL            → use SUPABASE_DB_URL         │
│    ⛔ Direct connections      → always use pooler           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Audit Log

When making variable changes, document:

| Date       | Operator | Change              | Reason             | Ticket |
| ---------- | -------- | ------------------- | ------------------ | ------ |
| YYYY-MM-DD | @handle  | Set SUPABASE_DB_URL | Initial prod setup | DF-123 |
|            |          |                     |                    |        |
