# SUPABASE_MIGRATE_DB_URL Policy

> **Classification**: Security-Critical  
> **Last Updated**: 2026-01-11  
> **Owner**: Platform Team  
> **Implementation**: [backend/core/config_guard.py](../backend/core/config_guard.py)

---

## Policy Statement

`SUPABASE_MIGRATE_DB_URL` provides **direct Postgres access** (port 5432) bypassing Supabase connection pooling. It is:

| Context                  | Allowed          | Reason                                  |
| ------------------------ | ---------------- | --------------------------------------- |
| Local dev scripts        | ✅ Yes           | Migrations require direct DDL access    |
| CI/CD pipelines          | ✅ Yes           | Automated migration deployment          |
| Railway runtime services | ❌ **FORBIDDEN** | Credential leak vector, bypasses pooler |

---

## Forbidden Services (Railway)

These services must **NEVER** contain `SUPABASE_MIGRATE_DB_URL`:

```
dragonfly-api
dragonfly-worker-ingest
dragonfly-worker-enforcement
dragonfly-worker-enrichment
dragonfly-dashboard (if deployed)
```

**Allowed exception**: A dedicated `dragonfly-migrator` ephemeral job that runs migrations and immediately terminates.

---

## Runtime Detection (Already Implemented)

### Existing Guard

The guard is already implemented in `backend/core/config_guard.py` and called at the top of `backend/main.py`:

```python
# backend/main.py (lines 22-27)
from backend.core.config_guard import (
    validate_db_config,
    validate_production_config,
    validate_runtime_config,
)

validate_runtime_config()  # Blocks if SUPABASE_MIGRATE_DB_URL present
```

### Key Functions

| Function                       | Purpose                                              |
| ------------------------------ | ---------------------------------------------------- |
| `validate_runtime_config()`    | Blocks if SUPABASE_MIGRATE_DB_URL present in runtime |
| `is_scripts_mode()`            | Detects CLI tools, pytest, one-off scripts           |
| `validate_production_config()` | Additional prod safety (SSL, port 6543)              |

### Detection Heuristics

Scripts mode is detected when any of these are true:

- `DRAGONFLY_SCRIPT_MODE=1` environment variable
- Running under pytest (`PYTEST_CURRENT_TEST` set)
- Module invocation via `python -m tools.*` or `python -m etl.*`
- PowerShell script execution (`.ps1` extension)

---

## Remediation Procedure

If `SUPABASE_MIGRATE_DB_URL` is found in a Railway runtime service:

### Immediate Actions (< 5 minutes)

```bash
# 1. Scale down the affected service immediately
railway service scale dragonfly-api --replicas 0

# 2. Remove the variable via Railway CLI
railway variables unset SUPABASE_MIGRATE_DB_URL --service dragonfly-api

# 3. Verify removal
railway variables --service dragonfly-api | grep -i migrate
# Should return empty

# 4. Scale back up
railway service scale dragonfly-api --replicas 1
```

### Post-Incident

1. **Rotate the credential** - Generate new Postgres password in Supabase Dashboard
2. **Update local .env files** with new password
3. **Audit Railway variables** for all services:
   ```bash
   for svc in dragonfly-api dragonfly-worker-ingest dragonfly-worker-enforcement; do
     echo "=== $svc ==="
     railway variables --service $svc | grep -iE "(migrate|db_url|postgres)"
   done
   ```
4. **Add incident to security log**

---

## Allowed Credentials by Service Type

| Variable                                | Local Scripts | Railway Services |
| --------------------------------------- | ------------- | ---------------- |
| `SUPABASE_URL`                          | ✅            | ✅               |
| `SUPABASE_SERVICE_ROLE_KEY`             | ✅            | ✅               |
| `SUPABASE_DB_URL` (pooler 6543)         | ✅            | ✅               |
| `SUPABASE_MIGRATE_DB_URL` (direct 5432) | ✅            | ❌               |
| `SUPABASE_ANON_KEY`                     | ✅            | ✅ (if needed)   |

---

## Verification Script

Add to CI/CD or run manually before deploys:

```powershell
# scripts/check_railway_credentials.ps1
$forbidden = @("SUPABASE_MIGRATE_DB_URL", "POSTGRES_PASSWORD", "DATABASE_URL")
$services = @("dragonfly-api", "dragonfly-worker-ingest", "dragonfly-worker-enforcement")

$violations = @()
foreach ($svc in $services) {
    $vars = railway variables --service $svc 2>$null
    foreach ($f in $forbidden) {
        if ($vars -match $f) {
            $violations += "$svc contains $f"
        }
    }
}

if ($violations.Count -gt 0) {
    Write-Host "🚨 CREDENTIAL VIOLATIONS DETECTED:" -ForegroundColor Red
    $violations | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
} else {
    Write-Host "✅ All services clean" -ForegroundColor Green
}
```

---

## Summary Checklist

| Checkpoint             | Owner            | Frequency          |
| ---------------------- | ---------------- | ------------------ |
| Runtime startup guard  | Code (automatic) | Every boot         |
| Railway variable audit | Ops              | Before each deploy |
| Credential rotation    | Security         | After any exposure |
| CI/CD variable check   | Pipeline         | Every PR merge     |

---

## Related Documentation

- [backend/core/config_guard.py](../backend/core/config_guard.py) - Implementation
- [RUNBOOK_DAD.md](../RUNBOOK_DAD.md) - Operational procedures
- [supabase_client.py](../src/supabase_client.py) - DSN resolution logic
