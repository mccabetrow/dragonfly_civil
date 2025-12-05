# Dragonfly Backend – Railway Deployment Guide

> **Service:** `dragonfly-engine` (FastAPI backend)  
> **Host:** Railway (HTTP on PORT)  
> **Start Command:** `uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8888}`

---

## 1. Required Environment Variables

Set these in the Railway dashboard under **Variables**:

| Variable                    | Description                                           | Example                              |
| --------------------------- | ----------------------------------------------------- | ------------------------------------ |
| `SUPABASE_URL`              | REST API URL for the **production** Supabase project  | `https://xyz.supabase.co`            |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (server-side only)                   | `eyJhbG…`                            |
| `SUPABASE_DB_URL`           | Postgres connection string (pooler, transaction mode) | `postgresql://…`                     |
| `DRAGONFLY_API_KEY`         | Secret key for `X-API-Key` header authentication      | `df_prod_xxxxxxxx-xxxx-xxxx-xxxx`    |
| `SUPABASE_MODE`             | Should be `prod` on Railway                           | `prod`                               |
| `ENVIRONMENT`               | Used by logging/metrics (must be `prod` for warnings) | `prod`                               |
| `LOG_LEVEL`                 | Logging verbosity                                     | `INFO`                               |
| `DISCORD_WEBHOOK_URL`       | (Optional) Webhook for escalation/intake alerts       | `https://discord.com/api/webhooks/…` |
| `SUPABASE_JWT_SECRET`       | (Optional) If using JWT tokens                        | `your-jwt-secret`                    |
| `PORT`                      | Injected by Railway automatically                     | `8888` (default)                     |

> ⚠️ **Important:** All secrets are read from environment variables only—NOT from file-based secrets.  
> Railway injects env vars at runtime; no `/secrets/` path is used.

> ⚠️ Never commit secrets. Railway encrypts env vars at rest.

---

## 2. Build & Start

Railway auto-detects Python via:

- **`runtime.txt`** – specifies `python-3.12.3`
- **`requirements.txt`** – pip dependencies (includes `psycopg-pool`)
- **`Procfile`** – start command (`web: uvicorn backend.main:app …`)

On every push to `main`:

1. Railway runs `pip install -r requirements.txt`
2. Railway starts the `web` process from `Procfile`
3. Scheduler jobs begin (APScheduler, 8 jobs)

---

## 3. Health Check Endpoints

Railway uses these to verify the service is alive:

| Endpoint                    | Auth        | Response                                          |
| --------------------------- | ----------- | ------------------------------------------------- |
| `GET /health`               | None        | `{"service": "Dragonfly Engine", "status": "ok"}` |
| `GET /api/health`           | None        | `{"status": "ok", "version": "…"}`                |
| `GET /api/v1/intake/health` | `X-API-Key` | `{"status": "ok", "service": "intake-gateway"}`   |

Configure Railway health checks to hit `/health` (no auth required).

---

## 4. How to Redeploy

### Option A – Push to `main`

```bash
git push origin main
```

Railway auto-deploys on every commit to the linked branch.

### Option B – Railway CLI

```bash
# Install CLI if needed
npm install -g @railway/cli

# Login
railway login

# Trigger deploy from current directory
railway up
```

### Option C – Railway Dashboard

1. Open https://railway.app → your project
2. Click the service → **Deploy** tab
3. Click **Redeploy** button

---

## 5. Running the Smoke Test

After deployment, verify endpoints are reachable:

```powershell
# Set base URL (replace with your Railway domain)
$env:API_BASE_URL = "https://dragonfly-engine-production.up.railway.app"

# Set API key for protected endpoints
$env:DRAGONFLY_API_KEY = "your-production-api-key"

# Run smoke test
python -m tools.prod_smoke_railway
```

Expected output:

```
=== Dragonfly Railway Production Smoke Test ===
Base URL: https://dragonfly-engine-production.up.railway.app

[1/3] GET /health ... ✓ OK (123ms)
[2/3] GET /api/health ... ✓ OK {"status": "ok", "version": "0.2.1"} (98ms)
[3/3] GET /api/v1/intake/health ... ✓ OK {"status": "ok", "service": "intake-gateway"} (105ms)

=== PASS: 3/3 checks succeeded ===
```

If any check fails, the script exits non-zero and prints the error.

---

## 6. Logs & Debugging

### View Logs

```bash
railway logs
```

Or in the dashboard: **Service → Logs** tab.

### Common Issues

| Symptom              | Cause                   | Fix                                                             |
| -------------------- | ----------------------- | --------------------------------------------------------------- |
| `502 Bad Gateway`    | App crashed on startup  | Check logs for import errors or missing env vars                |
| `connection refused` | Wrong `SUPABASE_DB_URL` | Verify pooler host and port (usually 6543 for transaction mode) |
| `401 Unauthorized`   | Missing `API_KEY`       | Ensure `API_KEY` env var is set and matches header              |
| Health check timeout | Slow startup            | Increase Railway health check timeout or optimize startup       |

---

## 7. Scheduler Jobs

The backend starts these APScheduler jobs automatically:

| Job                      | Interval | Description                              |
| ------------------------ | -------- | ---------------------------------------- |
| `intake_guardian`        | 60s      | Self-heals stuck CSV intake batches      |
| `collectability_refresh` | 5m       | Recalculates collectability scores       |
| `escalation_sweep`       | 15m      | Checks for overdue escalations           |
| …                        | …        | See `backend/scheduler.py` for full list |

Jobs run in-process; no separate worker dyno needed.

---

## 8. Rollback

If a deploy breaks production:

1. Go to Railway dashboard → **Deployments**
2. Find the last working deployment
3. Click **Rollback**

Or use CLI:

```bash
railway rollback
```

---

## 9. Checklist Before Deploy

- [ ] All tests pass locally: `python -m pytest -q`
- [ ] Doctor checks pass: `python -m tools.doctor --env prod`
- [ ] No secrets in code (use env vars only)
- [ ] `requirements.txt` includes all deps
- [ ] `runtime.txt` specifies correct Python version
- [ ] Migration applied: `./scripts/db_push.ps1 -SupabaseEnv prod`

---

## 10. Railway Deploy Checklist

Use this quick checklist after every Railway deploy:

### Pre-Deploy

- [ ] Push to `main` or run `railway up`
- [ ] Confirm Railway variables are set:
  - `SUPABASE_URL` ✓
  - `SUPABASE_SERVICE_ROLE_KEY` ✓
  - `SUPABASE_DB_URL` ✓
  - `DRAGONFLY_API_KEY` ✓
  - `ENVIRONMENT=prod` ✓
  - `SUPABASE_MODE=prod` ✓
  - `LOG_LEVEL=INFO` ✓
  - `DISCORD_WEBHOOK_URL` (optional)

### Post-Deploy

- [ ] Watch Railway logs for startup errors (`railway logs`)
- [ ] Run smoke test: `python -m tools.prod_smoke_railway`
- [ ] Verify `/health` returns `{"status": "ok"}`
- [ ] Verify `/api/v1/intake/health` with `X-API-Key` header
- [ ] Check scheduler jobs started (look for "Scheduler started" in logs)

### If Deploy Fails

1. Check logs for missing env vars (look for `DRAGONFLY_API_KEY not set` warning)
2. Verify `runtime.txt` = `python-3.12.3`
3. Verify `Procfile` = `web: uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8888}`
4. Rollback via Railway dashboard if needed

---

## 11. Related Docs

- [DB Migration Protocol](./DB_MIGRATION_PROTOCOL.md)
- [Ops Playbook](./ops_playbook_v1.md)
- [Intake 900 SOP](./SOP_INTAKE_900.md)
