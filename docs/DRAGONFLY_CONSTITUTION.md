# The Dragonfly Constitution

> **Non-Negotiable Invariants**  
> _The Laws of the System_

This document codifies the engineering principles that govern the Dragonfly Civil platform. These are not guidelines—they are **invariants**. Violations break production and erode trust.

---

## Section 1: Availability

> "/health is process state, /readyz is dependency state. Never spam logs."

### 1.1 Liveness Probe (`GET /health`)

- **Purpose**: Confirms the process is alive and capable of handling requests.
- **Contract**: Returns `{"status": "ok"}` with HTTP 200.
- **Implementation**: No I/O, no database calls, no external dependencies.
- **Failure Mode**: If this fails, the orchestrator should restart the container.

### 1.2 Readiness Probe (`GET /readyz`)

- **Purpose**: Confirms all upstream dependencies are reachable.
- **Contract**: Returns `{"status": "ready", "services": {...}}` with HTTP 200 when ready.
- **Implementation**: Performs lightweight connectivity checks (database ping, cache ping).
- **Failure Mode**: If this fails, traffic should be drained until recovery.

### 1.3 Logging Discipline

- **Liveness checks MUST NOT emit logs**—they fire every 10 seconds; log spam kills observability.
- **Readiness failures SHOULD log once** with `WARNING` level, then suppress duplicates.
- **Error details are internal**—never expose stack traces or connection strings to callers.

---

## Section 2: Security

> "Frontend holds NO secrets. Ops schema is private. Rate limits are mandatory."

### 2.1 Secret Hygiene

| Layer              | Secrets Allowed                  |
| ------------------ | -------------------------------- |
| Frontend (browser) | ❌ None. Ever.                   |
| Edge Functions     | ✅ Service-role keys only        |
| Backend Workers    | ✅ Full credentials via env vars |

- **Supabase anon key** is the only key permitted in frontend code.
- **Service-role keys** and database passwords live exclusively in server-side environments.
- **Git commits** must never contain credentials—pre-commit hooks enforce this.

### 2.2 Schema Isolation

- `public` schema: User-facing tables with Row-Level Security (RLS) enabled.
- `ops` schema: Internal operations, queue management, audit logs—**never exposed via PostgREST**.
- `auth` schema: Managed by Supabase—do not modify directly.

### 2.3 Rate Limiting

- **All public endpoints** must have rate limits configured.
- Default: 100 requests/minute per IP for authenticated routes.
- Default: 20 requests/minute per IP for unauthenticated routes.
- Rate limit middleware is **mandatory**—it cannot be disabled in production.

### 2.4 CORS Policy

- Default behavior: **Deny All** (empty origins list).
- Allowed origins must be explicitly configured via `DRAGONFLY_CORS_ORIGINS`.
- Wildcards (`*`) are forbidden in production.

---

## Section 3: Deployment

> "Every artifact is traceable to a Git SHA. No deploy without a passing Gate."

### 3.1 Traceability

- Every HTTP response includes `X-Dragonfly-SHA` header.
- Every log entry includes `git_sha` field.
- Every deployed container is tagged with the commit hash.
- **If you can't trace it to a commit, it doesn't exist.**

### 3.2 The Production Gate

Before any production deployment, the following checks **must pass**:

| Check              | Tool                             | Failure Action |
| ------------------ | -------------------------------- | -------------- |
| Schema Consistency | `tools.check_schema_consistency` | Block deploy   |
| Security Audit     | `tools.security_audit`           | Block deploy   |
| Database Health    | `tools.doctor_all`               | Block deploy   |
| Unit Tests         | `pytest`                         | Block deploy   |
| Build Verification | `npm run build`                  | Block deploy   |

```bash
# The canonical gate command
python -m tools.prod_gate --env prod --strict
```

### 3.3 Deployment Verification

Post-deployment validation is **mandatory**:

```bash
python -m tools.smoke_deploy --url https://api.dragonfly.example.com
```

All 5 invariants must pass:

- ✅ Liveness probe returns 200
- ✅ Readiness probe returns 200
- ✅ `X-Dragonfly-SHA` header present
- ✅ CORS headers correct for allowed origins
- ✅ Response latency ≤ 500ms

### 3.4 Rollback Protocol

- If smoke tests fail, **rollback immediately**—do not debug in production.
- Rollback target: Previous known-good SHA from deployment log.
- Post-rollback: Re-run smoke tests to confirm recovery.

---

## Section 4: Observability

> "If it isn't in the JSON logs with a trace_id, it didn't happen."

### 4.1 Structured Logging

All log entries must be JSON with these required fields:

```json
{
  "timestamp": "2025-01-07T12:00:00.000Z",
  "level": "INFO",
  "message": "Request processed",
  "trace_id": "abc123-def456",
  "git_sha": "a1b2c3d",
  "service": "dragonfly-api"
}
```

### 4.2 Trace Propagation

- Inbound requests receive a `trace_id` (from header or generated).
- All downstream calls (database, external APIs, queues) propagate the same `trace_id`.
- Background workers inherit `trace_id` from the triggering event.

### 4.3 What Gets Logged

| Event               | Level   | Required |
| ------------------- | ------- | -------- |
| Request received    | DEBUG   | Optional |
| Request completed   | INFO    | ✅ Yes   |
| Validation failure  | WARNING | ✅ Yes   |
| Unhandled exception | ERROR   | ✅ Yes   |
| Security violation  | ERROR   | ✅ Yes   |
| Health check        | —       | ❌ Never |

### 4.4 What Never Gets Logged

- Passwords, tokens, API keys
- Full request/response bodies (use truncated previews)
- PII beyond what's necessary for debugging
- Health probe activity

---

## Enforcement

These invariants are enforced through:

1. **Automated Gates**: `tools.prod_gate` blocks non-compliant deploys.
2. **Smoke Tests**: `tools.smoke_deploy` validates production state.
3. **Code Review**: PRs modifying security-critical paths require CTO approval.
4. **Monitoring**: Alerts fire when invariants are violated in production.

---

## Amendment Process

This constitution may only be amended through:

1. Written proposal with rationale
2. Review by engineering leadership
3. Update to this document with change log
4. Communication to all team members

---

## Change Log

| Date       | Change               | Author |
| ---------- | -------------------- | ------ |
| 2025-01-07 | Initial constitution | CTO    |

---

_"We don't ship hope. We ship proof."_
