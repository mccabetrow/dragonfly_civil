# Watchdog Service Deployment Guide

> **Service:** `backend.monitors.watchdog`  
> **Purpose:** Platform Health Monitor with Hard SLO Enforcement  
> **Runtime:** Python (smallest Railway instance)

---

## 🐕 What the Watchdog Does

The Watchdog runs every **60 seconds** and performs 4 health checks:

| Check               | SLO                                    | Action on Failure                             |
| ------------------- | -------------------------------------- | --------------------------------------------- |
| **Worker Liveness** | Heartbeat < 90s (stale), < 900s (dead) | Alert                                         |
| **Queue Freshness** | Oldest message < 300s                  | Alert "traffic jam"                           |
| **DLQ Discipline**  | Auto-triage failed jobs                | Create `security.incidents` or `public.tasks` |
| **API Health**      | Latency < 1000ms                       | Alert "degraded"                              |

---

## 🚀 Deployment Options

### Option A: Railway Service (Recommended)

Separate service = isolated resource, restarts independently, visible in metrics.

```bash
# Command for Railway service
python -m backend.monitors.watchdog
```

**Railway Configuration:**

1. **Create new service** in Railway:

   - Name: `watchdog`
   - Start Command: `python -m backend.monitors.watchdog`
   - Instance: **Smallest** (256MB RAM is sufficient)

2. **Environment Variables** (copy from API service):

   ```env
   SUPABASE_MODE=prod
   SUPABASE_URL=<your-url>
   SUPABASE_ANON_KEY=<your-key>
   SUPABASE_SERVICE_KEY=<your-service-key>
   SUPABASE_DB_URL=<your-db-url>
   API_BASE_URL=https://your-api.railway.app
   WATCHDOG_DISCORD_WEBHOOK=<optional-webhook-url>
   ```

3. **Health Check:**

   - The watchdog logs to stdout every 60s
   - Railway will show it as healthy if the process is running

4. **Restart Policy:** Always (default)

### Option B: Background Thread in API (Cost Saver)

If you want to save money, run the watchdog as a background thread in your FastAPI service.

**In `backend/main.py`:**

```python
import asyncio
from contextlib import asynccontextmanager
from backend.monitors.watchdog import run_watchdog_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start watchdog as background task
    watchdog_task = asyncio.create_task(run_watchdog_loop())
    yield
    # Shutdown
    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)
```

**Pros:** No extra Railway cost  
**Cons:** Watchdog dies if API dies (less isolation)

---

## 🧪 Local Testing

### Single Iteration

```powershell
$env:SUPABASE_MODE='dev'
python -m backend.monitors.watchdog --once
```

### Continuous Loop

```powershell
$env:SUPABASE_MODE='dev'
python -m backend.monitors.watchdog
```

### VS Code Tasks

Use the pre-configured tasks:

- `Watchdog (Dev)` — Single iteration
- `Watchdog Loop (Dev)` — Continuous monitoring

---

## 📊 Expected Output

```
🐕 Watchdog starting for environment: DEV
   Loop interval: 60s
   SLOs: queue=300s, worker=90s, api=1000ms
════════════════════════════════════════════════════════════
WATCHDOG ITERATION #1 (DEV)
════════════════════════════════════════════════════════════
[Check 1] Worker Liveness...
  → HEALTHY: 3 worker(s) alive (45ms)
[Check 2] Queue Freshness...
  → HEALTHY: All queues fresh (78ms)
[Check 3] DLQ Discipline...
  → HEALTHY: DLQ empty - all clear (32ms)
[Check 4] API Health...
  → HEALTHY: API responding (123ms)
────────────────────────────────────────────────────────────
OVERALL: ✅ HEALTHY (312ms)
════════════════════════════════════════════════════════════
```

---

## 🚨 Alert Actions

### DLQ Auto-Triage

The watchdog automatically triages DLQ messages:

| Pattern                                        | Category   | Action                      |
| ---------------------------------------------- | ---------- | --------------------------- |
| `unauthorized access`, `authentication failed` | Security   | Insert `security.incidents` |
| `authorization denied`, `invalid token`        | Security   | Insert `security.incidents` |
| `compliance block`, `fcra violation`           | Compliance | Insert `public.tasks`       |
| `consent missing`, `legal hold`                | Compliance | Insert `public.tasks`       |

### Discord Webhooks (Optional)

Set `WATCHDOG_DISCORD_WEBHOOK` to get alerts:

```python
# In watchdog.py, add after alerts are generated:
if DISCORD_WEBHOOK_URL and alerts:
    send_discord_alert(alerts)
```

---

## 🔧 Configuration

All SLOs are configurable in `backend/monitors/watchdog.py`:

```python
# Queue SLOs
MAX_QUEUE_AGE_SEC = 300      # 5 minutes = traffic jam

# Worker SLOs
MAX_WORKER_SILENCE_SEC = 90  # 1.5 minutes = stale
WORKER_DEAD_SEC = 900        # 15 minutes = dead

# API SLOs
API_LATENCY_THRESHOLD_MS = 1000  # 1 second
API_TIMEOUT_SEC = 5              # Hard timeout

# Loop Configuration
LOOP_INTERVAL_SEC = 60  # Check every minute
```

---

## 🩺 Troubleshooting

### "API unreachable"

- Set `API_BASE_URL` environment variable
- Ensure the API is running and accessible

### "DLQ has X failed job(s)"

- Check `security.incidents` for auto-triaged alerts
- Investigate the original queue that failed

### "Worker Dead"

- Check Railway logs for the worker service
- Worker heartbeats are in `workers.heartbeats` table

### "Queue Traffic Jam"

- Messages are piling up faster than processing
- Scale up workers or investigate processing bottleneck

---

## 📈 Metrics

The watchdog logs structured metrics for each check:

```json
{
  "iteration": 42,
  "environment": "prod",
  "overall_status": "healthy",
  "duration_ms": 312,
  "checks": {
    "worker_liveness": { "status": "healthy", "workers_alive": 3 },
    "queue_freshness": { "status": "healthy", "max_age_sec": 45 },
    "dlq_discipline": { "status": "healthy", "dlq_depth": 0 },
    "api_health": { "status": "healthy", "latency_ms": 123 }
  }
}
```

These can be parsed by Railway logging or sent to your observability stack.

---

## 🎯 SLO Summary

| Metric           | Target   | Alert Level            |
| ---------------- | -------- | ---------------------- |
| Worker Heartbeat | < 90s    | WARNING (stale)        |
| Worker Heartbeat | < 900s   | CRITICAL (dead)        |
| Queue Age        | < 300s   | WARNING (traffic jam)  |
| DLQ Depth        | 0        | WARNING (failed jobs)  |
| API Latency      | < 1000ms | WARNING (degraded)     |
| API Availability | 100%     | CRITICAL (unreachable) |

---

_The Watchdog gives you a pulse on your system. Deploy it and never guess about system health again._
