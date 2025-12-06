# CORS Preflight Verification Plan

## Summary

The CORS tests in `tests/test_api_auth.py::TestCORSConfiguration` have been updated to use **production Vercel origins** instead of `localhost:5173`. This ensures tests reflect real-world behavior and will fail when production would fail.

## Key Changes

1. **New `cors_client` fixture** - Creates a fresh app with production CORS origins after clearing the settings cache
2. **Production origins tested**:
   - `https://dragonfly-console1.vercel.app` (primary)
   - `https://dragonfly-console1-git-main-mccabetrow.vercel.app` (git preview)
   - `http://localhost:5173` (local dev)
3. **6 comprehensive tests**:
   - `test_cors_preflight_prod_origin` - Main production origin works
   - `test_cors_preflight_git_branch_origin` - Git preview origin works
   - `test_cors_allows_credentials` - `Access-Control-Allow-Credentials: true`
   - `test_cors_allows_api_key_header` - `X-DRAGONFLY-API-KEY` allowed
   - `test_cors_allows_all_methods` - POST/GET/etc all allowed
   - `test_cors_rejects_unknown_origin` - Evil origins rejected

## Local Test Command

```powershell
# Run all CORS tests
.\.venv\Scripts\python.exe -m pytest tests/test_api_auth.py::TestCORSConfiguration -v
```

## Production Verification (curl)

After deploying, run these curl commands to verify CORS is working:

### 1. Preflight for Main Origin

```bash
curl -X OPTIONS \
  https://dragonflycivil-production-d57a.up.railway.app/api/health \
  -H "Origin: https://dragonfly-console1.vercel.app" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: X-DRAGONFLY-API-KEY" \
  -i
```

**Expected Response:**

- Status: `200 OK`
- `Access-Control-Allow-Origin: https://dragonfly-console1.vercel.app`
- `Access-Control-Allow-Credentials: true`
- `Access-Control-Allow-Methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT`
- `Access-Control-Allow-Headers: *` or includes `X-DRAGONFLY-API-KEY`

### 2. Preflight for Git Preview Origin

```bash
curl -X OPTIONS \
  https://dragonflycivil-production-d57a.up.railway.app/api/health \
  -H "Origin: https://dragonfly-console1-git-main-mccabetrow.vercel.app" \
  -H "Access-Control-Request-Method: GET" \
  -i
```

**Expected Response:**

- Status: `200 OK`
- `Access-Control-Allow-Origin: https://dragonfly-console1-git-main-mccabetrow.vercel.app`

### 3. Reject Unknown Origin

```bash
curl -X OPTIONS \
  https://dragonflycivil-production-d57a.up.railway.app/api/health \
  -H "Origin: https://evil.com" \
  -H "Access-Control-Request-Method: GET" \
  -i
```

**Expected Response:**

- Status: `400 Bad Request` or `200` without `Access-Control-Allow-Origin: https://evil.com`

## PowerShell Commands (Windows)

```powershell
# Main origin preflight
Invoke-WebRequest -Method OPTIONS -Uri "https://dragonflycivil-production-d57a.up.railway.app/api/health" `
  -Headers @{
    "Origin" = "https://dragonfly-console1.vercel.app"
    "Access-Control-Request-Method" = "GET"
    "Access-Control-Request-Headers" = "X-DRAGONFLY-API-KEY"
  } | Select-Object StatusCode, @{N='CORS';E={$_.Headers.'Access-Control-Allow-Origin'}}

# Should output: StatusCode CORS
#                200        https://dragonfly-console1.vercel.app
```

## Railway Environment Variable Checklist

If production still returns 400, check Railway environment variables:

1. **DRAGONFLY_CORS_ORIGINS** must include:

   ```
   https://dragonfly-console1.vercel.app,https://dragonfly-console1-git-main-mccabetrow.vercel.app,http://localhost:5173
   ```

2. **No trailing/leading spaces** in the comma-separated list

3. **No https:// typos** (e.g., `htpps://` or missing `s`)

4. **Restart Railway service** after changing env vars

## Debugging 400 on Production

If preflight returns 400:

1. **Check Railway logs** for the exact request headers
2. **Verify env var is set** in Railway dashboard
3. **Check for Railway proxy** stripping headers
4. **Try with curl from different network** (not behind VPN/proxy)

The 400 means Starlette's CORSMiddleware found the origin in the request but it's NOT in `allow_origins`. This is almost always an env var configuration issue.

## Related Files

- `backend/config.py` - `cors_allowed_origins` property parses `DRAGONFLY_CORS_ORIGINS`
- `backend/main.py` - CORSMiddleware setup at lines 127-142
- `tests/test_api_auth.py` - TestCORSConfiguration class
