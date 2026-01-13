# 🏗️ Infrastructure Notes

> **Purpose:** Document all infrastructure changes, env var updates, and deployment configurations.
> **Rule:** If you change an env var or infra setting, log it here with date and reason.

---

## Environment Variables

### Required for All Environments

| Variable                         | Description                                   | Where Set             |
| -------------------------------- | --------------------------------------------- | --------------------- |
| `SUPABASE_MODE`                  | `dev` or `prod` - controls which DB to target | Local shell / Railway |
| `SUPABASE_URL_DEV`               | Dev project REST API URL                      | `.env.local`          |
| `SUPABASE_URL_PROD`              | Prod project REST API URL                     | Railway / Vercel      |
| `SUPABASE_SERVICE_ROLE_KEY_DEV`  | Dev service role key                          | `.env.local`          |
| `SUPABASE_SERVICE_ROLE_KEY_PROD` | Prod service role key                         | Railway / Vercel      |
| `SUPABASE_DB_URL_DEV`            | Dev direct DB connection string               | `.env.local`          |
| `SUPABASE_DB_URL_PROD`           | Prod direct DB connection string              | Railway               |

### Backend-Specific

| Variable               | Description                  | Default |
| ---------------------- | ---------------------------- | ------- |
| `ENVIRONMENT`          | `dev`, `staging`, or `prod`  | `dev`   |
| `LOG_LEVEL`            | Logging verbosity            | `INFO`  |
| `WORKER_POLL_INTERVAL` | Seconds between worker polls | `10`    |

### Dashboard (Vercel)

| Variable                 | Description                  |
| ------------------------ | ---------------------------- |
| `VITE_SUPABASE_URL`      | Supabase REST API URL        |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon key for client |
| `VITE_API_BASE_URL`      | Backend API base URL         |

---

## Railway Services Configuration

### Overview

Railway runs three services from the same codebase:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Railway Project                          │
├─────────────────────┬─────────────────────┬─────────────────────┤
│   Backend API       │   Ingest Worker     │  Enforcement Worker │
│   (web)             │   (ingest)          │  (enforcement)      │
├─────────────────────┼─────────────────────┼─────────────────────┤
│   Port: 8888        │   No port           │   No port           │
│   Healthcheck: /    │   Logs only         │   Logs only         │
└─────────────────────┴─────────────────────┴─────────────────────┘
```

### Service 1: Backend API

- **Name:** `dragonfly-api`
- **Start Command:** `python -m tools.run_uvicorn`
- **Health Check:** `GET /health`
- **Region:** US-West (or closest to Supabase)
- **Env Vars:**
  ```
  SUPABASE_MODE=prod
  ENVIRONMENT=prod
  SUPABASE_URL_PROD=https://xxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY_PROD=xxx
  SUPABASE_DB_URL_PROD=postgresql://...
  ```

### Service 2: Ingest Processor Worker

- **Name:** `dragonfly-ingest-worker`
- **Start Command:** `python -m backend.workers.ingest_processor`
- **Health Check:** Logs show `🚀 Starting Ingest Processor Worker`
- **Region:** Same as API
- **Env Vars:** Same as Backend API
- **Expected Log Output:**
  ```
  🚀 Starting Ingest Processor Worker (env=prod)
  Poll interval: 2.0s
  Job types: ingest_csv
  ```

### Service 3: Enforcement Engine Worker

- **Name:** `dragonfly-enforcement-worker`
- **Start Command:** `python -m backend.workers.enforcement_engine`
- **Health Check:** Logs show `🚀 Starting Enforcement Engine Worker`
- **Region:** Same as API
- **Env Vars:** Same as Backend API
- **Expected Log Output:**
  ```
  🚀 Starting Enforcement Engine Worker (env=prod)
  Poll interval: 5.0s
  Job types: enforcement_strategy, enforcement_drafting
  ```

### Deployment Checklist

When deploying workers to Railway:

1. [ ] Create new Railway service from same GitHub repo
2. [ ] Set start command (from above)
3. [ ] Copy all env vars from Backend API service
4. [ ] Verify `SUPABASE_MODE=prod`
5. [ ] Deploy and watch logs for startup message
6. [ ] Confirm no crash loops after 5 minutes
7. [ ] Test by uploading CSV to Intake Station

---

## Vercel Configuration

### Dashboard Deployment

- **Build Command:** `npm run build`
- **Output Directory:** `dist`
- **Install Command:** `npm install`
- **Root Directory:** `dragonfly-dashboard`

### Environment Variables

```
VITE_SUPABASE_URL=https://xxx.supabase.co
VITE_SUPABASE_ANON_KEY=xxx
VITE_API_BASE_URL=https://dragonfly-api.railway.app
```

---

## Change Log

| Date       | Change                       | Reason                      | By     |
| ---------- | ---------------------------- | --------------------------- | ------ |
| 2024-12-09 | Initial documentation        | Codify infra patterns       | System |
| 2024-12-09 | Added worker service configs | Three-service Railway setup | System |

---

## Secrets Rotation Checklist

When rotating secrets:

1. [ ] Generate new key in Supabase dashboard
2. [ ] Update Railway env vars (all 3 services!)
3. [ ] Update Vercel env vars (if applicable)
4. [ ] Update local `.env.local`
5. [ ] Run `python -m tools.prod_smoke` to verify
6. [ ] Log rotation in Change Log above

---

## Troubleshooting

### Worker Not Processing Jobs

1. Check Railway logs for startup message
2. Verify `SUPABASE_MODE=prod` is set
3. Check `ops.job_queue` has pending jobs:
   ```sql
   SELECT * FROM ops.job_queue WHERE status = 'pending' LIMIT 10;
   ```
4. Check for locked jobs:
   ```sql
   SELECT * FROM ops.job_queue WHERE status = 'processing'
   AND updated_at < NOW() - INTERVAL '30 minutes';
   ```

### API Returning 500s

1. Check Railway API logs
2. Verify DB connection string is correct
3. Run `python -m tools.prod_smoke` locally with prod env vars

### Dashboard Build Failing

1. Check Vercel build logs
2. Run `npm run build` locally to reproduce
3. Verify no TypeScript errors with `npx tsc --noEmit`
