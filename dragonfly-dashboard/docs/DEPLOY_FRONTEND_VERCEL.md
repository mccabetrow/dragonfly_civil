# Dragonfly Dashboard – Vercel Deployment Guide

> **App:** `dragonfly-dashboard` (Vite + React + TypeScript)  
> **Host:** Vercel  
> **Backend:** Railway (`https://dragonflycivil-production-d57a.up.railway.app`)

---

## 1. Required Environment Variables

Set these in **Vercel Dashboard → Project → Settings → Environment Variables**:

| Variable                 | Required | Description                                  | Example Value                                               |
| ------------------------ | -------- | -------------------------------------------- | ----------------------------------------------------------- |
| `VITE_API_BASE_URL`      | ✅       | Railway backend API URL (with `/api` suffix) | `https://dragonflycivil-production-d57a.up.railway.app/api` |
| `VITE_DRAGONFLY_API_KEY` | ✅       | API key for `X-API-KEY` header               | `df_prod_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`              |
| `VITE_SUPABASE_URL`      | ✅       | Supabase project URL                         | `https://xxxxxx.supabase.co`                                |
| `VITE_SUPABASE_ANON_KEY` | ✅       | Supabase anonymous/public key                | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`                   |

### Environment Scope

For each variable, select which environments it applies to:

- **Production**: Live site at your custom domain
- **Preview**: PR preview deployments
- **Development**: Rarely used (local dev uses `.env`)

> ⚠️ **Security Note**: `VITE_` prefixed variables are bundled into the client-side JavaScript. Never put server-side secrets here.

---

## 2. How Vercel Gets the Variables

1. Go to [vercel.com](https://vercel.com) → Your Project → **Settings** → **Environment Variables**
2. Click **Add New**
3. Enter each variable name and value
4. Select environments (Production, Preview, or both)
5. Click **Save**

After adding/changing variables, you must **redeploy** for changes to take effect:

- Push a new commit, OR
- Go to **Deployments** → click the `...` menu → **Redeploy**

---

## 3. Verifying the Connection (Browser Network Tab)

After deployment, verify the dashboard is calling the Railway backend correctly:

### Step-by-Step

1. Open your production dashboard: `https://dragonfly-dashboard.vercel.app/ops/console`
2. Open **DevTools** (F12 or Cmd+Option+I)
3. Go to the **Network** tab
4. Filter by **Fetch/XHR**
5. Refresh the page or trigger an action (e.g., upload a file)

### What to Look For

✅ **Correct**: Requests go to Railway backend

```
Request URL: https://dragonflycivil-production-d57a.up.railway.app/api/v1/intake/batches
Request Headers:
  X-API-KEY: df_prod_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Status: 200 OK
```

❌ **Wrong**: Requests go to wrong URL or missing headers

```
Request URL: http://127.0.0.1:8000/api/v1/intake/batches  ← Local dev URL!
Status: Failed to fetch (CORS error or connection refused)
```

❌ **Wrong**: Missing API key

```
Request URL: https://dragonflycivil-production-d57a.up.railway.app/api/v1/intake/batches
Request Headers:
  (no X-API-KEY header)  ← Missing!
Status: 401 Unauthorized
```

---

## 4. Common Issues & Fixes

| Symptom                                                     | Cause                               | Fix                                                                   |
| ----------------------------------------------------------- | ----------------------------------- | --------------------------------------------------------------------- |
| Console shows `VITE_API_BASE_URL is not set in production!` | Missing env var                     | Add `VITE_API_BASE_URL` in Vercel settings                            |
| `401 Unauthorized` on API calls                             | Missing or wrong API key            | Verify `VITE_DRAGONFLY_API_KEY` matches Railway's `DRAGONFLY_API_KEY` |
| CORS errors                                                 | Backend doesn't allow Vercel origin | Check Railway backend has `*.vercel.app` in CORS origins              |
| Network requests to `localhost`                             | Env var not set at build time       | Redeploy after adding env var                                         |
| Supabase auth fails                                         | Wrong Supabase keys                 | Verify `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`               |

---

## 5. Local Development vs Production

| Scenario                | `VITE_API_BASE_URL` | Behavior                                        |
| ----------------------- | ------------------- | ----------------------------------------------- |
| Local dev (npm run dev) | Not set             | Defaults to `http://127.0.0.1:8000/api`         |
| Local dev               | Set to Railway URL  | Calls Railway backend (useful for prod testing) |
| Vercel Production       | **Must be set**     | Uses Railway production backend                 |
| Vercel Preview          | Should be set       | Uses Railway backend for PR previews            |

---

## 6. Quick Checklist

### Before Deploy

- [ ] All tests pass: `npm test`
- [ ] Build succeeds: `npm run build`
- [ ] No secrets in code (use env vars only)

### In Vercel Settings

- [ ] `VITE_API_BASE_URL` set to Railway URL
- [ ] `VITE_DRAGONFLY_API_KEY` set (matches Railway)
- [ ] `VITE_SUPABASE_URL` set
- [ ] `VITE_SUPABASE_ANON_KEY` set

### After Deploy

- [ ] Open production site
- [ ] Check Network tab for Railway requests
- [ ] Verify `X-API-KEY` header is present
- [ ] Test an API action (e.g., load intake batches)

---

## 7. Related Docs

- [Backend Railway Deployment](../../docs/operations/DEPLOY_BACKEND_RAILWAY.md)
- [Railway Deploy Checklist](../../docs/operations/RAILWAY_DEPLOY_CHECKLIST.md)
