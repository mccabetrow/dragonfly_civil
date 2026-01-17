# Route Contract & Production Certification Hardening

## Summary

This update makes production certification impossible to fail due to routing/path ambiguity.

## Changes Made

### 1. Route Contract (backend/main.py)

**Problem**: `/health` and `/readyz` were defined twice - once in `health_root_router` and once inline in `create_app()`. This caused route shadowing.

**Fix**: Removed inline duplicates. Routes now come exclusively from `health_root_router` which returns richer responses including version, SHA, and environment.

**Verification**:

```bash
# These MUST return 200 (or 503 for readyz if DB unavailable)
curl http://localhost:8080/health
curl http://localhost:8080/readyz
```

### 2. Header Contract (backend/main.py)

**Problem**: Exception handlers only included CORS headers. Missing X-Dragonfly-\* headers on error responses.

**Fix**: Created `_get_required_headers()` that combines:

- CORS headers (for cross-origin access)
- `X-Dragonfly-Env` (environment)
- `X-Dragonfly-SHA` / `X-Dragonfly-SHA-Short` (commit)
- `X-Dragonfly-Version` (package version)

All exception handlers now use `_get_required_headers()`.

**Verification**:

```bash
# Check headers on any response
curl -I http://localhost:8080/health | grep X-Dragonfly
# Should see: X-Dragonfly-Env, X-Dragonfly-SHA-Short, etc.

# Even 404s should have headers
curl -I http://localhost:8080/nonexistent | grep X-Dragonfly
```

### 3. Certifier Autodiscovery (tools/certify_prod.py)

**New Features**:

- `--base-path` CLI flag: Use when routes are mounted under `/api`
- OpenAPI autodiscovery: Fetches `/openapi.json` to verify routes
- Critical remediation messages when `/health` is under `/api` but not root

**Usage**:

```bash
# Standard certification
python -m tools.certify_prod --url https://api.dragonfly.com --env prod

# If routes are under /api
python -m tools.certify_prod --url https://api.dragonfly.com --env prod --base-path /api

# Dry run to see what will be checked
python -m tools.certify_prod --url https://example.com --env prod --dry-run
```

### 4. Port Discipline (tools/run_uvicorn.py)

**Enhanced startup logging**:

- Prints module, host, port, workers, log level, environment at startup
- Uses `PORT` env var (Railway/Heroku/Render standard)
- Falls back to 8080 for local development

**Sample output**:

```
========================================================================
  DRAGONFLY ENGINE STARTUP
========================================================================
  Module:      backend.main:app
  Host:        0.0.0.0
  Port:        8080
  Workers:     1
  Log Level:   info
  Environment: prod
========================================================================
🚀 Starting Uvicorn: backend.main:app on 0.0.0.0:8080
```

### 5. Route Contract Tests (tests/test_route_contract.py)

New comprehensive test file with 16 tests covering:

- `/health` exists at root (not redirect)
- `/readyz` exists at root (not redirect)
- Response content includes status=ok
- X-Dragonfly-\* headers on all responses (including 404)
- OpenAPI spec includes `/health` and `/readyz`
- Liveness vs Readiness contract (health never 503)

---

## Operator Checklist: Safe Deployment

### Pre-Deployment

- [ ] Run route contract tests locally:

  ```bash
  python -m pytest tests/test_route_contract.py -v
  ```

- [ ] Verify certify_prod dry run:

  ```bash
  python -m tools.certify_prod --url http://localhost:8080 --env dev --dry-run
  ```

- [ ] Check no duplicate routes in OpenAPI:
  ```bash
  curl http://localhost:8080/openapi.json | jq '.paths | keys | map(select(contains("health")))'
  # Should show: ["/health", "/api/health", "/api/health/..."]
  ```

### Deployment

- [ ] Ensure Railway sets `PORT` environment variable (automatic)
- [ ] Deploy the new code

### Post-Deployment Verification

- [ ] Run production certification:

  ```bash
  python -m tools.certify_prod --url https://YOUR_RAILWAY_URL --env prod
  ```

- [ ] Verify headers:

  ```bash
  curl -I https://YOUR_RAILWAY_URL/health
  # Check: X-Dragonfly-Env: prod
  # Check: X-Dragonfly-SHA-Short: (not "unknown")
  ```

- [ ] Check readiness probe:

  ```bash
  curl https://YOUR_RAILWAY_URL/readyz
  # Should return {"status": "ready", "services": {"database": "connected"}}
  ```

- [ ] Review Railway logs for startup banner showing PORT and module

---

## Files Changed

| File                           | Change                                                                              |
| ------------------------------ | ----------------------------------------------------------------------------------- |
| `backend/main.py`              | Removed duplicate routes, added `_get_required_headers()`, fixed exception handlers |
| `tools/certify_prod.py`        | Added `--base-path`, OpenAPI autodiscovery, remediation messages                    |
| `tools/run_uvicorn.py`         | Enhanced startup logging with PORT discipline                                       |
| `tests/test_route_contract.py` | NEW - 16 tests for route contract enforcement                                       |

---

## Rollback

If issues occur, revert these files and redeploy:

```bash
git checkout HEAD~1 -- backend/main.py tools/certify_prod.py tools/run_uvicorn.py
git checkout HEAD~1 -- tests/test_route_contract.py  # or just delete it
```
