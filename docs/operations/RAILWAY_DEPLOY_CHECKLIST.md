# Railway Deploy Checklist

> **Printable checklist for every Railway deployment**  
> Last updated: 2025-01

---

## ✅ Pre-Deploy (Local Machine)

| Step | Action                                                                | ✓   |
| ---- | --------------------------------------------------------------------- | --- |
| 1    | Run tests: `python -m pytest -q`                                      | ☐   |
| 2    | Run doctor: `python -m tools.doctor --env prod`                       | ☐   |
| 3    | Verify no secrets in code (`git diff --cached`)                       | ☐   |
| 4    | Apply migrations if needed: `./scripts/db_push.ps1 -SupabaseEnv prod` | ☐   |
| 5    | Commit and push: `git push origin main`                               | ☐   |

---

## ✅ Railway Variables (Dashboard → Variables)

| Variable                    | Required | Value Set                   | ✓   |
| --------------------------- | -------- | --------------------------- | --- |
| `SUPABASE_URL`              | ✅       | `https://xxx.supabase.co`   | ☐   |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       | `eyJhbG...` (100+ chars)    | ☐   |
| `SUPABASE_DB_URL`           | ✅       | `postgresql://...` (pooler) | ☐   |
| `DRAGONFLY_API_KEY`         | ✅       | `df_prod_xxxx...`           | ☐   |
| `ENVIRONMENT`               | ✅       | `prod`                      | ☐   |
| `SUPABASE_MODE`             | ✅       | `prod`                      | ☐   |
| `LOG_LEVEL`                 | Optional | `INFO`                      | ☐   |
| `DISCORD_WEBHOOK_URL`       | Optional | Webhook URL                 | ☐   |
| `PORT`                      | Auto     | (Railway injects)           | ☐   |

---

## ✅ Post-Deploy Verification

| Step | Action                                               | Expected                             | ✓   |
| ---- | ---------------------------------------------------- | ------------------------------------ | --- |
| 1    | Watch logs: `railway logs`                           | No startup errors                    | ☐   |
| 2    | Check `/health`                                      | `{"status": "ok"}`                   | ☐   |
| 3    | Check `/api/health`                                  | `{"status": "ok", "version": "..."}` | ☐   |
| 4    | Check `/api/v1/intake/health` with `X-API-Key`       | `{"status": "ok"}`                   | ☐   |
| 5    | Verify scheduler started                             | Look for "Scheduler started" in logs | ☐   |
| 6    | Run smoke test: `python -m tools.prod_smoke_railway` | All checks pass                      | ☐   |

---

## 🔴 If Deploy Fails

1. **Check logs** for missing env vars (look for warnings like `DRAGONFLY_API_KEY not set`)
2. **Verify files exist:**
   - `runtime.txt` = `python-3.12.3`
   - `Procfile` = `web: uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8888}`
   - `requirements.txt` includes `psycopg-pool`
3. **Rollback** if needed:
   - Dashboard: Service → Deployments → Click on last working → **Rollback**
   - CLI: `railway rollback`

---

## 📋 Endpoint Reference

| Endpoint                            | Auth        | Purpose                    |
| ----------------------------------- | ----------- | -------------------------- |
| `GET /health`                       | None        | Load balancer health check |
| `GET /api/health`                   | None        | App health + version       |
| `GET /api/v1/intake/health`         | `X-API-Key` | Intake subsystem health    |
| `POST /api/v1/ops/guardian/trigger` | `X-API-Key` | Manual guardian trigger    |
| `GET /docs`                         | None        | OpenAPI docs               |

---

## 🔒 Security Reminders

- [ ] All secrets from env vars only (not file-based)
- [ ] `ENVIRONMENT=prod` enables rate limiting
- [ ] CORS allows only: `localhost:3000`, `localhost:5173`, `*.vercel.app`, `dragonfly-dashboard.vercel.app`
- [ ] 429 rate limits on semantic search (30/min), packets (30/min), offers (60/min)
- [ ] No secrets ever committed to git

---

## 📅 Deployment Log

| Date       | Version | Deployer     | Notes                                |
| ---------- | ------- | ------------ | ------------------------------------ |
| 2025-01-XX | 0.2.1   | **\_\_\_\_** | **************\_\_\_\_************** |
|            |         |              |                                      |
|            |         |              |                                      |
