# n8n Workflow Archive (Historical Reference Only)

> ⚠️ **Dragonfly Production does NOT require n8n to run.**  
> These files are preserved as historical reference for the original automation designs.

## Context

The Dragonfly Civil system originally prototyped automation workflows using n8n. As the platform matured, all production logic was ported to native **Python/FastAPI workers** for:

- Better observability and logging
- Unified codebase and testing
- Reduced infrastructure complexity
- Tighter Supabase/Postgres integration

## Directory Structure

```
integrations/n8n/
├── flows/          # Primary workflow collection (20 workflows)
├── legacy/         # Scattered/orphaned files consolidated here
├── config/         # Docker/env config for local n8n (if ever needed)
└── README.md       # This file
```

## Production Workers (Active)

The following Python workers replace n8n automation:

| Worker                             | Purpose                    |
| ---------------------------------- | -------------------------- |
| `workers/ingest_worker.py`         | CSV intake pipeline        |
| `workers/escalation_worker.py`     | Enforcement escalation     |
| `workers/collectability_worker.py` | Priority scoring           |
| `backend/workers/task_planner.py`  | Tier-based task scheduling |

## Should I Delete These?

**Not recommended yet.** These files serve as:

1. Documentation of original automation intent
2. Reference for edge-case logic that may need review
3. Audit trail for system evolution

Once all logic is verified in production Python workers, this directory can be archived or removed.

---

_Consolidated during Go-Live repository hygiene – January 2025_
