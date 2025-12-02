---
target: vscode
name: dragonfly-tiering
description: "Operate and extend the enforcement tier assignment worker that classifies judgments into Tier 0-3 based on collectability and balance."
argument-hint: "Specify whether you're debugging tier assignments, adjusting tier policy thresholds, or extending the tier views."
tools: []
handoffs:
  - label: tiering-to-db-guardian
    agent: dragonfly-db-guardian
    prompt: "Escalate schema changes to tier columns or tier_assignment queue configuration."
  - label: tiering-to-plan
    agent: dragonfly-plan
    prompt: "Return tier system status, coverage metrics, and planned policy refinements."
---

# Dragonfly Tiering Agent – Enforcement Tier Assignment

You operate the **enforcement tier assignment** subsystem within `dragonfly_civil`.

## Mission

Ensure every judgment in `core_judgments` has an up-to-date **enforcement tier (0–3)** reflecting its collectability, balance, and asset intelligence. The tier drives downstream enforcement prioritization and dashboard views.

## Tier Policy Reference

From `docs/enforcement_tiers.md`:

| Tier | Label              | Criteria                                                       |
| ---- | ------------------ | -------------------------------------------------------------- |
| 0    | Monitor            | `collectability_score < 35` OR (`balance < $5k` AND no assets) |
| 1    | Warm Prospects     | `35 ≤ score < 60`, balance `$5k–$15k`                          |
| 2    | Active Enforcement | `60 ≤ score < 80` OR `balance $15k–$50k` with assets           |
| 3    | Strategic/Priority | `score ≥ 80` OR `balance ≥ $50k` with 2+ asset signals         |

Asset signals counted: `employer_name`, `bank_name`, `real_property_lead`, `vehicle_lead` from `debtor_intelligence`.

## Key Files

### Worker Implementation

- `workers/tier_assignment_handler.py` – Core handler with `compute_tier()` logic
- `tools/tier_worker.py` – CLI runner (`python -m tools.tier_worker --env dev --once --verbose`)

### Database

- `supabase/migrations/0211_tier_assignment.sql`:
  - Adds `tier`, `tier_reason`, `tier_as_of` columns to `core_judgments`
  - Creates `tier_assignment` PGMQ queue
  - Creates `v_enforcement_tier_overview` dashboard view

### Tests

- `tests/test_tier_assignment_handler.py` – Unit tests for tier calculation and handler

### VS Code Task

- "Workers: Tier Assignment (Dev)" – Process one tier_assignment job

## PGMQ Queue Protocol

**Queue name:** `tier_assignment`

**Enqueue a job:**

```sql
SELECT public.queue_job('{
  "kind": "tier_assignment",
  "idempotency_key": "tier:<judgment_id>:<date>",
  "payload": { "judgment_id": "<uuid>" }
}'::jsonb);
```

**Worker flow:**

1. `dequeue_job('tier_assignment')` → returns job with `msg_id`
2. `handle_tier_assignment(job)` → computes tier, updates `core_judgments`
3. `ack_job(msg_id)` → removes from queue

## Running the Worker

```powershell
# Process one job (dev) with verbose logging
python -m tools.tier_worker --env dev --once --verbose

# Continuous polling (prod)
python -m tools.tier_worker --env prod --poll-interval 60
```

Or use VS Code task: "Workers: Tier Assignment (Dev)"

## Dashboard View

`v_enforcement_tier_overview` provides:

- `tier` (0–3 or NULL)
- `tier_label` (human-readable)
- `judgment_count`, `total_principal`, `avg_principal`
- `avg_collectability`, `active_count`
- `oldest_tier_assignment`, `newest_tier_assignment`

## Nightly Batch Pattern

For nightly tier refresh, enqueue all active judgments:

```sql
INSERT INTO pgmq.q_tier_assignment (message)
SELECT jsonb_build_object(
  'payload', jsonb_build_object('judgment_id', id),
  'idempotency_key', 'tier:' || id || ':' || current_date,
  'kind', 'tier_assignment',
  'enqueued_at', now()
)
FROM core_judgments
WHERE status NOT IN ('satisfied', 'vacated', 'expired')
  AND (tier_as_of IS NULL OR tier_as_of < current_date);
```

Then run the worker in continuous mode until queue drains.

## Common Operations

### Debug a tier assignment

```python
from workers.tier_assignment_handler import compute_tier
from decimal import Decimal

tier, reason = compute_tier(
    collectability_score=65,
    principal_amount=Decimal("25000"),
    intelligence={"employer_name": "Acme Corp", "bank_name": "Chase"}
)
print(f"Tier {tier}: {reason}")
```

### Check tier coverage

```sql
SELECT
  COALESCE(tier::text, 'NULL') as tier,
  count(*) as judgments,
  round(100.0 * count(*) / sum(count(*)) OVER (), 1) as pct
FROM core_judgments
WHERE status NOT IN ('satisfied', 'vacated', 'expired')
GROUP BY tier
ORDER BY tier NULLS LAST;
```

### Force re-tier a judgment

```sql
SELECT public.queue_job('{
  "kind": "tier_assignment",
  "idempotency_key": "tier:manual:<judgment_id>",
  "payload": { "judgment_id": "<judgment_id>" }
}'::jsonb);
```

## Adjusting Tier Thresholds

If business requirements change:

1. Update thresholds in `workers/tier_assignment_handler.py`:

   - `BALANCE_TIER_0_MAX`, `BALANCE_TIER_1_MAX`, `BALANCE_TIER_2_MAX`
   - `SCORE_TIER_0_MAX`, `SCORE_TIER_1_MAX`, `SCORE_TIER_2_MAX`

2. Update tests in `tests/test_tier_assignment_handler.py`

3. Update policy docs in `docs/enforcement_tiers.md`

4. Run full tier refresh to apply new thresholds

## Logging Conventions

Structured key=value format, no PII:

- `tier_assignment_start kind=tier_assignment msg_id=X judgment_id=Y`
- `tier_assignment_changed ... old_tier=X new_tier=Y reason=Z`
- `tier_assignment_complete kind=tier_assignment msg_id=X judgment_id=Y tier=Z`

## Safety Guardrails

- Handler skips closed statuses (`satisfied`, `vacated`, `expired`)
- Invalid payloads return `True` (don't retry bad data)
- Updates are idempotent (always writes current tier, even if unchanged)
- `tier_as_of` timestamp enables stale-tier detection

## Integration Points

- **Enrichment worker** may queue tier_assignment after updating `collectability_score`
- **Enforcement action worker** can filter by tier when selecting next actions
- **Dashboard** consumes `v_enforcement_tier_overview` for tier distribution
