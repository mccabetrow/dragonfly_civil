# Deployment Checklist — Mom Console + Backend

> **Purpose:** Step-by-step guide to deploy the Dragonfly frontend (Vercel) and backend (Railway)  
> **Audience:** McCabe, future engineers, or anyone setting up from scratch  
> **Last Updated:** December 2025

---

## Prerequisites (Before You Start)

```
[ ] GitHub repo access (mccabetrow/dragonfly_civil)
[ ] Vercel account (vercel.com)
[ ] Railway account (railway.app)
[ ] Supabase project credentials (dev and prod)
[ ] Local repo cloned and up to date
```

---

# Section A – Frontend (Vercel)

## A.1 Prerequisites Checklist

```
[ ] Console app exists at: dragonfly-dashboard/
[ ] package.json has build script: "build": "tsc && vite build"
[ ] vercel.json exists in dragonfly-dashboard/
[ ] .env.example documents required variables
[ ] npm run build succeeds locally
```

## A.2 Connect Repository to Vercel

1. **Log in to Vercel:** https://vercel.com/dashboard

2. **Click "Add New Project"**

3. **Import Git Repository:**

   ```
   [ ] Select GitHub
   [ ] Authorize Vercel if prompted
   [ ] Find and select: mccabetrow/dragonfly_civil
   ```

4. **Configure Project:**
   | Setting | Value |
   |---------|-------|
   | Project Name | `dragonfly-mom-console` |
   | Framework Preset | `Vite` (auto-detected) |
   | Root Directory | `dragonfly-dashboard` ← **IMPORTANT** |
   | Build Command | `npm run build` (default) |
   | Output Directory | `dist` (default) |
   | Install Command | `npm install` (default) |

   ```
   [ ] Root Directory set to: dragonfly-dashboard
   [ ] Framework detected as Vite
   ```

## A.3 Configure Environment Variables

In Vercel Project Settings → Environment Variables, add:

| Variable                 | Value                                     | Environment |
| ------------------------ | ----------------------------------------- | ----------- |
| `VITE_API_BASE_URL`      | `https://your-railway-app.up.railway.app` | Production  |
| `VITE_DRAGONFLY_API_KEY` | `df_prod_xxxxxxxx-xxxx...`                | Production  |
| `VITE_SUPABASE_URL`      | `https://xxx.supabase.co`                 | Production  |
| `VITE_SUPABASE_ANON_KEY` | `eyJ...` (anon key)                       | Production  |
| `VITE_DEMO_MODE`         | `false` (or omit)                         | Production  |

```
[ ] VITE_API_BASE_URL added (Railway backend URL)
[ ] VITE_DRAGONFLY_API_KEY added (matches Railway DRAGONFLY_API_KEY)
[ ] VITE_SUPABASE_URL added
[ ] VITE_SUPABASE_ANON_KEY added
[ ] VITE_DEMO_MODE omitted or set to "false"
```

> ⚠️ **Never add service role keys or secrets to frontend env vars!**
>
> ⚠️ **Deprecated vars removed:** `VITE_SUPABASE_URL_PROD`, `VITE_SUPABASE_ANON_KEY_PROD`, `VITE_SUPABASE_ENV`, `VITE_IS_DEMO` are no longer used.

## A.4 Deploy

1. **Click "Deploy"** in Vercel

2. **Wait for build to complete** (usually 1-2 minutes)

3. **Check build logs for errors:**

   ```
   [ ] TypeScript compilation: no errors
   [ ] Vite build: success
   [ ] Output: dist/ directory created
   ```

4. **Note your deployment URL:**
   ```
   Production URL: https://dragonfly-mom-console.vercel.app
   ```

## A.5 Test Frontend Deployment

```
[ ] Open production URL in browser
[ ] Page loads without errors
[ ] No console errors (F12 → Console tab)
[ ] Pipeline tab loads (may show empty if no data)
[ ] Signatures tab loads
[ ] Call Queue tab loads
[ ] Activity tab loads
```

## A.6 Frontend Deployment Complete

```
[ ] Deployment URL recorded: ________________________
[ ] All tabs functional
[ ] No console errors
```

---

# Section B – Backend (Railway)

## B.1 Prerequisites Checklist

```
[ ] FastAPI app exists at: src/api/app.py
[ ] app = FastAPI() is defined
[ ] Procfile exists in repo root with uvicorn command
[ ] requirements.txt includes: fastapi, uvicorn[standard], gunicorn
[ ] /healthz endpoint exists in app.py
```

**Procfile contents:**

```
web: uvicorn src.api.app:app --host 0.0.0.0 --port $PORT --workers 3
```

## B.2 Connect Repository to Railway

1. **Log in to Railway:** https://railway.app/dashboard

2. **Click "New Project"**

3. **Select "Deploy from GitHub repo"**

4. **Configure Repository:**

   ```
   [ ] Select: mccabetrow/dragonfly_civil
   [ ] Branch: main (or release/golden-prod)
   ```

5. **Railway auto-detects Python** and finds:
   - `requirements.txt` → installs dependencies
   - `Procfile` → uses as start command

## B.3 Configure Environment Variables

In Railway Project → Variables tab, add:

| Variable        | Value                        | Notes                  |
| --------------- | ---------------------------- | ---------------------- |
| `SUPABASE_URL`  | `https://xxx.supabase.co`    | Prod Supabase URL      |
| `SUPABASE_KEY`  | `eyJ...` (service role key)  | For backend operations |
| `SUPABASE_MODE` | `prod`                       | Environment selector   |
| `N8N_API_KEY`   | `your-api-key`               | For n8n webhook auth   |
| `PORT`          | (Railway sets automatically) | Don't set manually     |

```
[ ] SUPABASE_URL added
[ ] SUPABASE_KEY added (service role key for backend)
[ ] SUPABASE_MODE set to "prod"
[ ] N8N_API_KEY added
[ ] Any other settings from src/settings.py
```

> ⚠️ **Backend CAN use service role key — it's server-side only.**

## B.4 Configure Build Settings

In Railway Project → Settings:

| Setting        | Value                                    |
| -------------- | ---------------------------------------- |
| Root Directory | `/` (repo root)                          |
| Build Command  | `pip install -r requirements.txt` (auto) |
| Start Command  | From Procfile (auto)                     |
| Watch Paths    | `src/**`, `requirements.txt`, `Procfile` |

```
[ ] Root Directory is repo root (/)
[ ] Procfile detected
[ ] Build command auto-detected
```

## B.5 Deploy

1. **Railway deploys automatically** when you push to the branch

2. **Or click "Deploy"** to trigger manually

3. **Watch the build logs:**

   ```
   [ ] pip install completes
   [ ] uvicorn starts
   [ ] "Application startup complete" in logs
   ```

4. **Note your deployment URL:**
   ```
   Railway URL: https://dragonfly-civil-production.up.railway.app
   ```

## B.6 Test Backend Deployment

```
[ ] Open: https://your-railway-url.up.railway.app/healthz
[ ] Response: {"status": "ok"}
[ ] Open: https://your-railway-url.up.railway.app/docs
[ ] Swagger UI loads (FastAPI auto-docs)
```

**Test with curl:**

```bash
curl https://your-railway-url.up.railway.app/healthz
# Expected: {"status":"ok"}
```

## B.7 Backend Deployment Complete

```
[ ] Deployment URL recorded: ________________________
[ ] /healthz returns {"status": "ok"}
[ ] /docs (Swagger) loads
[ ] No errors in Railway logs
```

---

# Section C – Wiring Frontend to Backend

## C.1 Update Frontend Environment

Now that Railway is live, update the frontend to point to it:

1. **Go to Vercel Project → Settings → Environment Variables**

2. **Update `VITE_API_BASE_URL`:**

   ```
   VITE_API_BASE_URL = https://your-railway-url.up.railway.app
   ```

3. **Save changes**

```
[ ] VITE_API_BASE_URL updated with Railway URL
```

## C.2 Redeploy Frontend

1. **Go to Vercel Project → Deployments**

2. **Click the "..." menu on the latest deployment**

3. **Select "Redeploy"**

4. **Wait for build to complete**

```
[ ] Redeploy triggered
[ ] Build successful
[ ] New deployment live
```

## C.3 Final Smoke Tests

### Test 1: Frontend Loads

```
[ ] Open: https://dragonfly-mom-console.vercel.app
[ ] Page loads without errors
[ ] No "Failed to fetch" errors in console
```

### Test 2: Data Loads from Supabase

```
[ ] Pipeline tab shows data (or empty state, not error)
[ ] Signatures tab loads
[ ] Call Queue tab loads
[ ] Activity tab loads
```

### Test 3: Backend Health

```
[ ] curl https://your-railway-url.up.railway.app/healthz
[ ] Response: {"status": "ok"}
```

### Test 4: Backend API Docs

```
[ ] Open: https://your-railway-url.up.railway.app/docs
[ ] Swagger UI displays all endpoints
```

### Test 5: End-to-End (if API is wired)

```
[ ] Frontend calls backend endpoint (check Network tab)
[ ] Response received successfully
[ ] No CORS errors
```

---

# Section D – Post-Deployment

## D.1 Record Deployment Info

Fill in and save:

| Service           | URL                                | Status       |
| ----------------- | ---------------------------------- | ------------ |
| Frontend (Vercel) | `https://________________________` | ✅ Live      |
| Backend (Railway) | `https://________________________` | ✅ Live      |
| Supabase (Prod)   | `https://________________________` | ✅ Connected |

## D.2 Set Up Monitoring (Optional)

```
[ ] Vercel: Enable Analytics (Project Settings → Analytics)
[ ] Railway: Check Metrics tab for CPU/Memory
[ ] Set up uptime monitoring (e.g., UptimeRobot, Checkly)
```

## D.3 Configure Custom Domain (Optional)

**Vercel:**

1. Project Settings → Domains
2. Add: `console.dragonflycivil.com` (or similar)
3. Update DNS records as instructed

**Railway:**

1. Project Settings → Domains
2. Add: `api.dragonflycivil.com` (or similar)
3. Update DNS records as instructed

```
[ ] Custom domain configured (if applicable)
[ ] SSL certificate active
```

## D.4 Notify Team

```
[ ] Share production URLs with team
[ ] Update docs/operations/mom_enforcement_console_guide.md with final URL
[ ] Update week_1_go_live_plan.md if needed
```

---

# Troubleshooting

## Frontend won't build

1. Check Vercel build logs
2. Common issues:
   - TypeScript errors → fix in code
   - Missing dependencies → check package.json
   - Wrong root directory → must be `dragonfly-dashboard`

## Backend won't start

1. Check Railway logs
2. Common issues:
   - Missing env vars → add in Railway Variables
   - Import errors → check requirements.txt
   - Port binding → Railway sets $PORT automatically

## CORS errors in browser

1. Backend needs CORS middleware for frontend domain
2. Check `src/api/app.py` for CORS configuration
3. Add frontend URL to allowed origins

## "Failed to fetch" in frontend

1. Check browser Network tab for the failing request
2. Verify `VITE_API_BASE_URL` is correct
3. Verify backend is running (hit /healthz)
4. Check for CORS issues

## Data not loading

1. Check browser console for errors
2. Verify Supabase credentials are correct
3. Check Supabase dashboard for connection logs
4. Verify views exist: `v_enforcement_pipeline_status`, etc.

---

# Quick Reference

| Item                | Value                                                 |
| ------------------- | ----------------------------------------------------- |
| **Frontend Root**   | `dragonfly-dashboard/`                                |
| **Frontend Build**  | `npm run build`                                       |
| **Frontend Output** | `dist/`                                               |
| **Backend Root**    | `/` (repo root)                                       |
| **Backend Start**   | `uvicorn src.api.app:app --host 0.0.0.0 --port $PORT` |
| **Health Check**    | `GET /healthz` → `{"status": "ok"}`                   |
| **API Docs**        | `GET /docs` → Swagger UI                              |

---

_Checklist complete. Both services should now be live and connected._
