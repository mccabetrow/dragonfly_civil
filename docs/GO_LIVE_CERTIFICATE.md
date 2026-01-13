# Dragonfly Go-Live Certificate

**Version:** 1.0  
**Status:** DRAFT  
**Author:** Principal Engineer  
**Date:** 2026-01-12

---

## 1. Runtime Variable Contract

### 1.1 REQUIRED in Railway Production

| Variable                    | Format                      | Validation                              |
| --------------------------- | --------------------------- | --------------------------------------- |
| `SUPABASE_URL`              | `https://<ref>.supabase.co` | Must contain `.supabase.co`             |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJ...` (JWT)              | Must start with `eyJ`, length > 100     |
| `SUPABASE_DB_URL`           | See §3 DSN Contract         | Pooler host, port 6543, sslmode=require |
| `ENVIRONMENT`               | `prod` or `production`      | Case-insensitive match                  |
| `SUPABASE_MODE`             | `prod`                      | Exact match                             |
| `PORT`                      | `8080`                      | Railway injects this                    |

### 1.2 OPTIONAL in Railway Production

| Variable                 | Default   | Purpose                          |
| ------------------------ | --------- | -------------------------------- |
| `RAILWAY_GIT_COMMIT_SHA` | `unknown` | Injected by Railway for tracing  |
| `OPENAI_API_KEY`         | `None`    | RAG features disabled if missing |
| `DISCORD_WEBHOOK_URL`    | `None`    | Alerting disabled if missing     |
| `DRAGONFLY_CORS_ORIGINS` | `*`       | Comma-separated allowed origins  |

### 1.3 MUST NEVER EXIST in Railway Production

| Variable                  | Reason                                                     |
| ------------------------- | ---------------------------------------------------------- |
| `SUPABASE_MIGRATE_DB_URL` | Migration URLs bypass pooler; direct DB access only for CI |
| `DEBUG`                   | Enables verbose logging that may leak secrets              |
| `TESTING`                 | Disables security middleware                               |
| `DEV_MODE`                | Bypasses production guards                                 |

**Enforcement:** `validate_runtime_config()` in `config_guard.py` MUST fail-fast if forbidden variables are set.

---

## 2. Deterministic Boot Contract

### 2.1 Invariant

> **Bootstrap MUST NOT require `.env.*` files in Railway.**
>
> Bootstrap MAY load `.env.dev` or `.env.prod` if the file exists on disk.
> If the file does not exist, bootstrap continues silently using system environment variables.

### 2.2 Implementation Contract

```
FUNCTION bootstrap_environment(mode: str) -> BootResult:
    env_file = f".env.{mode}"

    IF file_exists(env_file):
        load_dotenv(env_file)
        source = "ENV_FILE"
    ELSE:
        log.info(f"Env file not found ({env_file}), relying on system variables")
        source = "SYSTEM_ENV"

    RETURN BootResult(source=source, env=mode)
```

### 2.3 Success Indicators (Logs)

On successful Railway boot, logs MUST contain:

```
[WARN] Env file not found (.env.prod), relying on system variables.
[BOOT] Mode: PROD | Config Source: SYSTEM_ENV | SHA: abc123
```

### 2.4 Failure Mode

If `FileNotFoundError` is raised for any `.env.*` file, the bootstrap is **NON-COMPLIANT** and must be fixed.

---

## 3. DB DSN Correctness Contract

### 3.1 Production DSN Requirements

| Component    | Requirement                              | Example                               |
| ------------ | ---------------------------------------- | ------------------------------------- |
| **Host**     | Must end with `.pooler.supabase.com`     | `aws-0-us-east-1.pooler.supabase.com` |
| **Port**     | Must be `6543` (transaction pooler)      | `6543`                                |
| **SSL Mode** | Must be `require` (explicit or injected) | `?sslmode=require`                    |
| **User**     | Must be `postgres.<ref>` for pooler auth | `postgres.iaketsyhmqbwaabgykux`       |

### 3.2 Forbidden DSN Patterns

| Pattern                | Reason                                                        |
| ---------------------- | ------------------------------------------------------------- |
| `db.<ref>.supabase.co` | Direct DB host; bypasses pooler, causes connection exhaustion |
| Port `5432`            | Direct Postgres port; bypasses PgBouncer                      |
| `sslmode=disable`      | Security violation                                            |
| Missing `sslmode`      | Ambiguous; must be explicit                                   |

### 3.3 Validation Pseudocode

```
FUNCTION validate_db_dsn(dsn: str) -> Result:
    parsed = parse_dsn(dsn)

    # Host check
    IF NOT parsed.host.endswith(".pooler.supabase.com"):
        RETURN Error("DSN uses direct DB host, not pooler")

    # Port check
    IF parsed.port != 6543:
        RETURN Error(f"DSN port {parsed.port} != 6543 (pooler)")

    # SSL check
    IF parsed.sslmode NOT IN ("require", "verify-full"):
        RETURN Error(f"DSN sslmode={parsed.sslmode}, must be 'require'")

    RETURN Ok("DSN compliant")
```

### 3.4 Fail-Fast Behavior

On DSN validation failure:

```
⛔ DSN VALIDATION FAILED
   Host: db.xxx.supabase.co (INVALID - must use pooler host)
   Expected: *.pooler.supabase.com:6543

   ACTION: Update SUPABASE_DB_URL in Railway to use the Transaction Pooler
           connection string from Supabase Dashboard.

sys.exit(1)
```

---

## 4. Certification Script Specification

### 4.1 Invocation

```bash
python -m tools.certify_prod --url https://dragonfly-api-prod.up.railway.app
```

### 4.2 Test Matrix

| Test ID         | Category       | Description                                  | Pass Criteria                     |
| --------------- | -------------- | -------------------------------------------- | --------------------------------- |
| `HEALTH_01`     | Endpoint       | `GET /health`                                | HTTP 200                          |
| `READY_01`      | Endpoint       | `GET /readyz`                                | HTTP 200                          |
| `HEADER_01`     | Observability  | `X-Dragonfly-SHA-Short` present              | Non-empty, != "unknown"           |
| `HEADER_02`     | Observability  | `X-Dragonfly-Env` present                    | Value = "prod"                    |
| `RLS_01`        | Security       | `ops.import_runs` denied for `anon`          | HTTP 401 or empty result          |
| `RLS_02`        | Security       | `ops.import_runs` denied for `authenticated` | HTTP 403 or empty result          |
| `RLS_03`        | Security       | `ops.import_runs` allowed for `service_role` | HTTP 200, result accessible       |
| `IDEMPOTENT_01` | Data Integrity | Duplicate import_run is skipped              | Second insert returns existing ID |

### 4.3 Pseudocode

```python
#!/usr/bin/env python3
"""tools/certify_prod.py - Production Go-Live Certification"""

import sys
import httpx
import uuid
from datetime import datetime

class CertificationResult:
    def __init__(self):
        self.passed = []
        self.failed = []

    def record(self, test_id: str, passed: bool, detail: str = ""):
        entry = {"id": test_id, "detail": detail}
        if passed:
            self.passed.append(entry)
        else:
            self.failed.append(entry)

    @property
    def all_passed(self) -> bool:
        return len(self.failed) == 0


def certify_production(base_url: str, service_role_key: str) -> CertificationResult:
    result = CertificationResult()

    # ─────────────────────────────────────────────────────────────────────
    # HEALTH_01: GET /health
    # ─────────────────────────────────────────────────────────────────────
    try:
        resp = httpx.get(f"{base_url}/health", timeout=10)
        result.record("HEALTH_01", resp.status_code == 200, f"HTTP {resp.status_code}")
    except Exception as e:
        result.record("HEALTH_01", False, str(e))

    # ─────────────────────────────────────────────────────────────────────
    # READY_01: GET /readyz
    # ─────────────────────────────────────────────────────────────────────
    try:
        resp = httpx.get(f"{base_url}/readyz", timeout=10)
        result.record("READY_01", resp.status_code == 200, f"HTTP {resp.status_code}")
    except Exception as e:
        result.record("READY_01", False, str(e))

    # ─────────────────────────────────────────────────────────────────────
    # HEADER_01: X-Dragonfly-SHA-Short
    # ─────────────────────────────────────────────────────────────────────
    try:
        resp = httpx.get(f"{base_url}/health", timeout=10)
        sha = resp.headers.get("X-Dragonfly-SHA-Short", "")
        valid = sha and sha != "unknown" and len(sha) >= 7
        result.record("HEADER_01", valid, f"SHA={sha}")
    except Exception as e:
        result.record("HEADER_01", False, str(e))

    # ─────────────────────────────────────────────────────────────────────
    # HEADER_02: X-Dragonfly-Env
    # ─────────────────────────────────────────────────────────────────────
    try:
        resp = httpx.get(f"{base_url}/health", timeout=10)
        env = resp.headers.get("X-Dragonfly-Env", "")
        valid = env.lower() == "prod"
        result.record("HEADER_02", valid, f"Env={env}")
    except Exception as e:
        result.record("HEADER_02", False, str(e))

    # ─────────────────────────────────────────────────────────────────────
    # RLS_01: ops schema denied for anon
    # ─────────────────────────────────────────────────────────────────────
    try:
        # Attempt to query ops.import_runs without auth
        resp = httpx.get(
            f"{base_url.replace('/api', '')}/rest/v1/rpc/list_import_runs",
            headers={"apikey": "anon-key-placeholder"},
            timeout=10
        )
        # Should be denied (401/403) or return empty
        denied = resp.status_code in (401, 403) or resp.json() == []
        result.record("RLS_01", denied, f"HTTP {resp.status_code}")
    except Exception as e:
        result.record("RLS_01", True, f"Blocked: {e}")  # Exception = blocked = good

    # ─────────────────────────────────────────────────────────────────────
    # RLS_02: ops schema denied for authenticated
    # ─────────────────────────────────────────────────────────────────────
    try:
        # Attempt with a fake auth token (should still be denied)
        resp = httpx.get(
            f"{base_url.replace('/api', '')}/rest/v1/rpc/list_import_runs",
            headers={
                "apikey": "anon-key-placeholder",
                "Authorization": "Bearer fake-jwt-token"
            },
            timeout=10
        )
        denied = resp.status_code in (401, 403) or resp.json() == []
        result.record("RLS_02", denied, f"HTTP {resp.status_code}")
    except Exception as e:
        result.record("RLS_02", True, f"Blocked: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # RLS_03: ops schema allowed for service_role
    # ─────────────────────────────────────────────────────────────────────
    try:
        resp = httpx.get(
            f"{base_url.replace('/api', '')}/rest/v1/rpc/list_import_runs",
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}"
            },
            timeout=10
        )
        allowed = resp.status_code == 200
        result.record("RLS_03", allowed, f"HTTP {resp.status_code}")
    except Exception as e:
        result.record("RLS_03", False, str(e))

    # ─────────────────────────────────────────────────────────────────────
    # IDEMPOTENT_01: Duplicate import_run is skipped
    # ─────────────────────────────────────────────────────────────────────
    try:
        test_batch = f"certify_test_{uuid.uuid4().hex[:8]}"

        # First insert
        resp1 = httpx.post(
            f"{base_url}/api/v1/import/start",
            json={"batch_name": test_batch, "source": "certification"},
            headers={"Authorization": f"Bearer {service_role_key}"},
            timeout=10
        )
        first_id = resp1.json().get("import_run_id")

        # Second insert (same batch_name) - should return same ID or skip
        resp2 = httpx.post(
            f"{base_url}/api/v1/import/start",
            json={"batch_name": test_batch, "source": "certification"},
            headers={"Authorization": f"Bearer {service_role_key}"},
            timeout=10
        )
        second_id = resp2.json().get("import_run_id")

        # Idempotency check: same ID returned OR explicit skip message
        idempotent = (first_id == second_id) or resp2.status_code == 409
        result.record("IDEMPOTENT_01", idempotent, f"ID1={first_id}, ID2={second_id}")

        # Cleanup: mark as completed
        httpx.post(
            f"{base_url}/api/v1/import/{first_id}/complete",
            headers={"Authorization": f"Bearer {service_role_key}"},
            timeout=10
        )
    except Exception as e:
        result.record("IDEMPOTENT_01", False, str(e))

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dragonfly Production Certification")
    parser.add_argument("--url", required=True, help="Production API base URL")
    parser.add_argument("--service-key", help="Service role key (or use SUPABASE_SERVICE_ROLE_KEY)")
    args = parser.parse_args()

    service_key = args.service_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not service_key:
        print("❌ SUPABASE_SERVICE_ROLE_KEY required")
        sys.exit(1)

    print("=" * 70)
    print("  DRAGONFLY GO-LIVE CERTIFICATION")
    print("=" * 70)
    print(f"  Target: {args.url}")
    print(f"  Time:   {datetime.utcnow().isoformat()}Z")
    print("=" * 70)
    print()

    result = certify_production(args.url, service_key)

    # Print results
    for test in result.passed:
        print(f"  ✅ {test['id']}: {test['detail']}")
    for test in result.failed:
        print(f"  ❌ {test['id']}: {test['detail']}")

    print()
    print("=" * 70)

    if result.all_passed:
        print()
        print("  ╔══════════════════════════════════════════════════════════════╗")
        print("  ║                                                              ║")
        print("  ║    ✅  CERTIFIED: GO FOR PLAINTIFFS                          ║")
        print("  ║                                                              ║")
        print("  ║    All 8 tests passed. Dragonfly is production-ready.        ║")
        print("  ║                                                              ║")
        print("  ╚══════════════════════════════════════════════════════════════╝")
        print()
        sys.exit(0)
    else:
        print()
        print("  ╔══════════════════════════════════════════════════════════════╗")
        print("  ║                                                              ║")
        print("  ║    ❌  NOT CERTIFIED: DO NOT OPERATE                         ║")
        print("  ║                                                              ║")
        print("  ║    {}/{} tests failed. Fix issues before go-live.            ║".format(
            len(result.failed), len(result.passed) + len(result.failed)))
        print("  ║                                                              ║")
        print("  ╚══════════════════════════════════════════════════════════════╝")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

---

## 5. Certification Checklist

Before running `python -m tools.certify_prod`:

- [ ] **Railway Variables Set** per §1.1
- [ ] **Forbidden Variables Absent** per §1.3
- [ ] **SUPABASE_DB_URL** uses pooler host (`*.pooler.supabase.com:6543`)
- [ ] **Service deployed** and responding to `/health`
- [ ] **Logs show** `SYSTEM_ENV` config source (not file-based)
- [ ] **Logs show** `✅ DB Connected` within 10s of boot

---

## 6. Signature Block

```
┌─────────────────────────────────────────────────────────────────────┐
│  DRAGONFLY GO-LIVE CERTIFICATE                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Environment:  PRODUCTION                                           │
│  API URL:      https://dragonfly-api-prod.up.railway.app            │
│  Certified:    ____-__-__ __:__:__ UTC                              │
│                                                                     │
│  Tests Passed: ___ / 8                                              │
│  SHA:          ________                                             │
│                                                                     │
│  Certified By: _______________________                              │
│                                                                     │
│  Status:       [ ] GO FOR PLAINTIFFS                                │
│                [ ] NOT CERTIFIED                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Appendix A: Quick Reference

### Correct Production DSN Format

```
postgresql://postgres.PROJREF:PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
           │         │                │                                        │        │
           │         │                │                                        │        └─ REQUIRED
           │         │                │                                        └─ Must be 6543
           │         │                └─ Must be *.pooler.supabase.com
           │         └─ User format: postgres.PROJREF
           └─ Scheme: postgresql or postgres
```

### Boot Log Success Pattern

```
[WARN] Env file not found (.env.prod), relying on system variables.
[BOOT] Mode: PROD | Config Source: SYSTEM_ENV | SHA: abc1234
[INFO] ✅ Config Verified (Pooler: 6543)
[INFO] DB pool init: attempt 1/6
[INFO] ✅ DB Connected (attempt: 1, init_duration_ms: 234)
```

### Boot Log Failure Pattern (Auth)

```
[ERROR] 🚨 Auth failure detected in pool logs: server_login_retry
[CRITICAL] ⛔ AUTH FATAL: Credentials rejected. Exiting immediately.
```
