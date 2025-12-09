# Dragonfly Civil – Observability & Monitoring Plan

> **Purpose:** Define dashboards, metrics, thresholds, and alerting for production monitoring  
> **Audience:** Engineering, DevOps, and Operations  
> **Last Updated:** December 9, 2025

---

## Table of Contents

1. [Overview](#1-overview)
2. [Supabase Monitoring](#2-supabase-monitoring)
3. [Railway API Monitoring](#3-railway-api-monitoring)
4. [Vercel Frontend Monitoring](#4-vercel-frontend-monitoring)
5. [Alerting Integration](#5-alerting-integration)
6. [Dashboard Checklist](#6-dashboard-checklist)
7. [Runbook Quick Reference](#7-runbook-quick-reference)

---

## 1. Overview

### Monitoring Philosophy

| Principle                         | Description                                                       |
| --------------------------------- | ----------------------------------------------------------------- |
| **Alert on symptoms, not causes** | Alert when users are affected, investigate causes after           |
| **Reduce noise**                  | Only alert on actionable issues; use thresholds to avoid flapping |
| **Layered visibility**            | Dashboards for context, alerts for urgency                        |
| **Single pane of glass**          | Discord as the unified notification channel                       |

### Stack Components

```
┌─────────────────────────────────────────────────────────────┐
│                        PRODUCTION                           │
├─────────────────┬─────────────────┬─────────────────────────┤
│    Vercel       │    Railway      │       Supabase          │
│   (Frontend)    │    (API)        │   (Database + Auth)     │
├─────────────────┼─────────────────┼─────────────────────────┤
│ - Dashboard     │ - FastAPI       │ - PostgreSQL            │
│ - Static assets │ - Background    │ - PostgREST             │
│                 │   workers       │ - Row Level Security    │
│                 │                 │ - pgmq (job queue)      │
└─────────────────┴─────────────────┴─────────────────────────┘
```

---

## 2. Supabase Monitoring

### 2.1 Metrics to Track

| Metric                         | Source                                            | Description                       |
| ------------------------------ | ------------------------------------------------- | --------------------------------- |
| **Query latency (p95, p99)**   | Supabase Dashboard → Database → Query Performance | Time to execute queries           |
| **Slow queries (>1s)**         | `pg_stat_statements`                              | Queries exceeding 1 second        |
| **Connection count**           | Supabase Dashboard → Database                     | Active database connections       |
| **Connection pool saturation** | Supabase Dashboard                                | % of pooler connections used      |
| **RLS policy violations**      | Postgres logs                                     | Unauthorized access attempts      |
| **Failed auth attempts**       | Supabase Auth logs                                | Brute force / credential stuffing |
| **Storage usage**              | Supabase Dashboard → Database                     | Database size growth              |
| **Replication lag**            | Supabase Dashboard                                | Read replica delay (if enabled)   |

### 2.2 Alert Thresholds

| Condition                   | Threshold        | Severity    | Action                              |
| --------------------------- | ---------------- | ----------- | ----------------------------------- |
| Query latency p95 > 500ms   | 5 min sustained  | ⚠️ Warning  | Investigate slow queries            |
| Query latency p99 > 2s      | 5 min sustained  | 🔴 Critical | Check for missing indexes           |
| Slow queries > 10/min       | 10 min sustained | ⚠️ Warning  | Review `pg_stat_statements`         |
| Connection count > 80% pool | Immediate        | ⚠️ Warning  | Check for connection leaks          |
| Connection count > 95% pool | Immediate        | 🔴 Critical | Scale pool or kill idle connections |
| RLS violation detected      | Any occurrence   | 🔴 Critical | Security review required            |
| Database size > 80% quota   | Daily check      | ⚠️ Warning  | Plan cleanup or upgrade             |
| Failed auth > 50/hour       | 1 hour window    | ⚠️ Warning  | Possible attack; review IPs         |

### 2.3 Slow Query Detection

Create a monitoring query to run periodically:

```sql
-- Save as: tools/sql/slow_query_check.sql
SELECT
    calls,
    round(total_exec_time::numeric, 2) as total_ms,
    round(mean_exec_time::numeric, 2) as avg_ms,
    round(max_exec_time::numeric, 2) as max_ms,
    query
FROM pg_stat_statements
WHERE mean_exec_time > 100  -- queries averaging > 100ms
ORDER BY mean_exec_time DESC
LIMIT 20;
```

### 2.4 RLS Violation Detection

Enable logging in Supabase:

1. Go to **Settings → Database → Postgres Logs**
2. Enable `log_statement = 'all'` (or `mod` for writes only)
3. Search logs for: `permission denied for table`

Create a Discord webhook trigger for RLS violations:

```sql
-- Future: Create a trigger that calls a webhook on security violations
-- For now, monitor via Supabase log search
```

---

## 3. Railway API Monitoring

### 3.1 Metrics to Track

| Metric                              | Source          | Description                       |
| ----------------------------------- | --------------- | --------------------------------- |
| **5xx error rate**                  | Railway Metrics | Server errors per minute          |
| **4xx error rate**                  | Railway Metrics | Client errors (may indicate bugs) |
| **Request latency (p50, p95, p99)** | Railway Metrics | API response time                 |
| **CPU usage**                       | Railway Metrics | Container CPU utilization         |
| **Memory usage**                    | Railway Metrics | Container memory utilization      |
| **Restart count**                   | Railway Metrics | Container crashes/restarts        |
| **Active connections**              | Custom metric   | Concurrent API connections        |

### 3.2 Alert Thresholds

| Condition                   | Threshold        | Severity    | Action                        |
| --------------------------- | ---------------- | ----------- | ----------------------------- |
| 5xx rate > 1% of requests   | 5 min sustained  | 🔴 Critical | Check logs immediately        |
| 5xx rate > 0.1% of requests | 15 min sustained | ⚠️ Warning  | Investigate error patterns    |
| Latency p95 > 2s            | 5 min sustained  | ⚠️ Warning  | Check database/external calls |
| Latency p99 > 5s            | 5 min sustained  | 🔴 Critical | System degradation            |
| CPU > 80%                   | 10 min sustained | ⚠️ Warning  | Consider scaling              |
| Memory > 90%                | 5 min sustained  | 🔴 Critical | Memory leak or scale up       |
| Container restarts > 3/hour | 1 hour window    | 🔴 Critical | Application crash loop        |

### 3.3 Health Check Endpoint

Ensure the API exposes a health check:

```python
# backend/routers/health.py
@router.get("/health")
async def health_check():
    """Health check for monitoring and load balancers."""
    try:
        # Check database connectivity
        await db.execute("SELECT 1")
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": settings.APP_VERSION
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )
```

### 3.4 Structured Logging

Ensure logs are JSON-formatted for searchability:

```python
# backend/core/logging.py
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

log = structlog.get_logger()

# Usage
log.info("request_completed",
         path="/api/judgments",
         status=200,
         duration_ms=45,
         user_id="abc123")
```

---

## 4. Vercel Frontend Monitoring

### 4.1 Metrics to Track

| Metric                              | Source                    | Description                  |
| ----------------------------------- | ------------------------- | ---------------------------- |
| **Build success rate**              | Vercel Dashboard          | Deployment success/failure   |
| **Build duration**                  | Vercel Dashboard          | Time to build and deploy     |
| **5xx error rate**                  | Vercel Analytics          | Server-side rendering errors |
| **Core Web Vitals (LCP, FID, CLS)** | Vercel Analytics          | User experience metrics      |
| **Page load time**                  | Vercel Analytics          | Time to interactive          |
| **Error rate (client-side)**        | Vercel Analytics / Sentry | JavaScript errors            |
| **Bandwidth usage**                 | Vercel Dashboard          | CDN and edge usage           |

### 4.2 Alert Thresholds

| Condition                   | Threshold       | Severity    | Action                   |
| --------------------------- | --------------- | ----------- | ------------------------ |
| Build failed                | Any occurrence  | 🔴 Critical | Check build logs         |
| Build duration > 5 min      | Any occurrence  | ⚠️ Warning  | Optimize build           |
| 5xx rate > 1%               | 5 min sustained | 🔴 Critical | Check SSR/API routes     |
| LCP > 2.5s                  | Daily average   | ⚠️ Warning  | Optimize largest content |
| CLS > 0.1                   | Daily average   | ⚠️ Warning  | Fix layout shifts        |
| Client JS errors > 100/hour | 1 hour window   | ⚠️ Warning  | Check error tracking     |

### 4.3 Web Vitals Targets

| Metric                             | Good    | Needs Improvement | Poor    |
| ---------------------------------- | ------- | ----------------- | ------- |
| **LCP** (Largest Contentful Paint) | ≤ 2.5s  | 2.5s – 4s         | > 4s    |
| **FID** (First Input Delay)        | ≤ 100ms | 100ms – 300ms     | > 300ms |
| **CLS** (Cumulative Layout Shift)  | ≤ 0.1   | 0.1 – 0.25        | > 0.25  |

### 4.4 Error Tracking Integration

Add Sentry for client-side error tracking:

```javascript
// dragonfly-dashboard/src/lib/sentry.ts
import * as Sentry from "@sentry/react";

Sentry.init({
  dsn: import.meta.env.VITE_SENTRY_DSN,
  environment: import.meta.env.MODE,
  tracesSampleRate: 0.1, // 10% of transactions
  beforeSend(event) {
    // Filter out non-actionable errors
    if (event.exception?.values?.[0]?.type === "ChunkLoadError") {
      return null; // User needs to refresh
    }
    return event;
  },
});
```

---

## 5. Alerting Integration

### 5.1 Discord Webhook Setup

Create dedicated channels:

| Channel            | Purpose                  | Who Monitors                 |
| ------------------ | ------------------------ | ---------------------------- |
| `#alerts-critical` | 🔴 Critical alerts only  | Engineering (immediate)      |
| `#alerts-warning`  | ⚠️ Warnings and notices  | Engineering (business hours) |
| `#deploys`         | Deployment notifications | Everyone                     |
| `#ops-daily`       | Daily health summaries   | Operations                   |

### 5.2 Webhook Configuration

```bash
# Store in GitHub Secrets or .env
DISCORD_WEBHOOK_CRITICAL=https://discord.com/api/webhooks/xxx/critical
DISCORD_WEBHOOK_WARNING=https://discord.com/api/webhooks/xxx/warning
DISCORD_WEBHOOK_DEPLOYS=https://discord.com/api/webhooks/xxx/deploys
```

### 5.3 Alert Message Format

**Critical Alert Template:**

```json
{
  "embeds": [
    {
      "title": "🔴 CRITICAL: Database Connection Pool Exhausted",
      "color": 15548997,
      "fields": [
        { "name": "Service", "value": "Supabase", "inline": true },
        { "name": "Metric", "value": "98% pool usage", "inline": true },
        { "name": "Duration", "value": "5 minutes", "inline": true }
      ],
      "footer": { "text": "Dragonfly Monitoring" },
      "timestamp": "2025-12-09T12:00:00Z"
    }
  ]
}
```

**Warning Alert Template:**

```json
{
  "embeds": [
    {
      "title": "⚠️ WARNING: Elevated API Latency",
      "color": 16776960,
      "fields": [
        { "name": "Service", "value": "Railway API", "inline": true },
        { "name": "Metric", "value": "p95 = 1.2s", "inline": true },
        { "name": "Threshold", "value": "> 500ms for 5min", "inline": true }
      ],
      "footer": { "text": "Dragonfly Monitoring" },
      "timestamp": "2025-12-09T12:00:00Z"
    }
  ]
}
```

### 5.4 Email Alerts (Backup)

For critical alerts, configure email backup:

| Provider     | Setup                                               |
| ------------ | --------------------------------------------------- |
| **Supabase** | Settings → Notifications → Add email                |
| **Railway**  | Settings → Notifications → Email alerts             |
| **Vercel**   | Settings → Notifications → Deployment notifications |

Recommended recipients:

- `eng-alerts@dragonflycivil.com` (critical)
- `ops@dragonflycivil.com` (daily summaries)

### 5.5 Uptime Monitoring

Use an external service to monitor from outside:

| Service           | Free Tier   | Recommendation    |
| ----------------- | ----------- | ----------------- |
| **UptimeRobot**   | 50 monitors | ✅ Recommended    |
| **Better Uptime** | 10 monitors | Good alternative  |
| **Pingdom**       | 1 monitor   | Enterprise option |

**Endpoints to monitor:**

| Endpoint                                | Check Interval | Alert After |
| --------------------------------------- | -------------- | ----------- |
| `https://api.dragonflycivil.com/health` | 1 min          | 2 failures  |
| `https://app.dragonflycivil.com`        | 1 min          | 2 failures  |
| Supabase REST endpoint                  | 5 min          | 1 failure   |

---

## 6. Dashboard Checklist

### 6.1 Supabase Dashboards

- [ ] **Query Performance Dashboard**
  - Slow queries by execution time
  - Query calls by frequency
  - Index usage statistics
- [ ] **Connection Pool Dashboard**
  - Active connections over time
  - Connection pool utilization %
  - Peak connection times
- [ ] **Security Dashboard**

  - Auth attempts (success/failure)
  - RLS violations (from logs)
  - API key usage by project

- [ ] **Storage Dashboard**
  - Database size trend
  - Table sizes
  - Index sizes

### 6.2 Railway Dashboards

- [ ] **API Health Dashboard**
  - Request rate (rpm)
  - Error rate (5xx, 4xx)
  - Latency percentiles (p50, p95, p99)
- [ ] **Resource Usage Dashboard**
  - CPU usage over time
  - Memory usage over time
  - Container restarts
- [ ] **Endpoint Performance Dashboard**
  - Latency by endpoint
  - Error rate by endpoint
  - Request volume by endpoint

### 6.3 Vercel Dashboards

- [ ] **Deployment Dashboard**
  - Build success rate
  - Build duration trend
  - Deployment frequency
- [ ] **Performance Dashboard**
  - Core Web Vitals (LCP, FID, CLS)
  - Page load time by route
  - Geographic performance
- [ ] **Error Dashboard** (via Sentry)
  - Error rate over time
  - Top errors by frequency
  - Errors by page/component

### 6.4 Unified Dashboard (Recommended)

Consider a single dashboard tool for all metrics:

| Tool              | Pros                          | Cons               |
| ----------------- | ----------------------------- | ------------------ |
| **Grafana Cloud** | Free tier, powerful, flexible | Setup complexity   |
| **Datadog**       | All-in-one, easy              | Expensive at scale |
| **New Relic**     | Good APM, free tier           | Can be complex     |
| **Axiom**         | Modern, simple pricing        | Less mature        |

**Recommendation:** Start with native dashboards (Supabase, Railway, Vercel), then consolidate to Grafana Cloud as complexity grows.

---

## 7. Runbook Quick Reference

### Critical Alert Response

```
🔴 CRITICAL ALERT RECEIVED
│
├─ Is the dashboard accessible?
│   ├─ NO → Check Vercel status, then DNS
│   └─ YES → Continue
│
├─ Is the API responding?
│   ├─ NO → Check Railway logs, then Supabase
│   └─ YES → Continue
│
├─ Is the database accessible?
│   ├─ NO → Check Supabase status page
│   └─ YES → Review specific error
│
└─ Escalation path:
    1. Check service status pages
    2. Review logs in relevant service
    3. Notify #alerts-critical with findings
    4. If unresolved in 15min, escalate to on-call
```

### Service Status Pages

| Service  | Status Page                   |
| -------- | ----------------------------- |
| Supabase | https://status.supabase.com   |
| Railway  | https://status.railway.app    |
| Vercel   | https://www.vercel-status.com |
| GitHub   | https://www.githubstatus.com  |

### Key Commands

```bash
# Check Railway logs
railway logs --tail 100

# Check Supabase connection
psql "$SUPABASE_DB_URL_PROD" -c "SELECT 1"

# Run health checks
python -m tools.doctor --env prod

# View recent migrations
python -m tools.migration_status --env prod
```

---

## 8. Implementation Roadmap

### Phase 1: Foundation (Week 1)

- [ ] Set up Discord webhook channels
- [ ] Configure native alerts in Supabase, Railway, Vercel
- [ ] Set up UptimeRobot for external monitoring
- [ ] Add `/health` endpoint to Railway API

### Phase 2: Visibility (Week 2)

- [ ] Create Supabase query performance view
- [ ] Enable structured logging in Railway
- [ ] Add Sentry to frontend
- [ ] Document runbooks for common alerts

### Phase 3: Automation (Week 3-4)

- [ ] Create daily summary Discord bot
- [ ] Build slow query alerting script
- [ ] Implement connection pool monitoring
- [ ] Set up automated incident response

### Phase 4: Optimization (Ongoing)

- [ ] Review and tune alert thresholds monthly
- [ ] Add custom business metrics (judgments processed, etc.)
- [ ] Consider unified dashboard (Grafana Cloud)
- [ ] Implement on-call rotation if needed

---

## 9. Appendix: Alert Configuration Snippets

### UptimeRobot Webhook to Discord

```json
{
  "content": null,
  "embeds": [
    {
      "title": "*monitorFriendlyName* is *alertTypeFriendlyName*",
      "description": "*alertDetails*",
      "color": 15548997,
      "fields": [
        { "name": "URL", "value": "*monitorURL*", "inline": false },
        { "name": "Duration", "value": "*alertDuration*", "inline": true }
      ],
      "timestamp": "*alertDateTime*"
    }
  ]
}
```

### Supabase Log Alert Query

```sql
-- Run periodically to check for issues
SELECT
    error_severity,
    message,
    timestamp
FROM postgres_logs
WHERE timestamp > now() - interval '1 hour'
  AND error_severity IN ('ERROR', 'FATAL', 'PANIC')
ORDER BY timestamp DESC
LIMIT 50;
```

---

_This plan should be reviewed quarterly and updated as the stack evolves._
