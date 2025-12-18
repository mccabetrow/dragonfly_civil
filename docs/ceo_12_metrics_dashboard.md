# CEO 12 Metrics - Dashboard Card Mapping

## Overview

This document defines the 12 CEO metrics for the Dragonfly Civil executive dashboard, including their definitions, SQL sources, refresh rates, alert thresholds, and dashboard card mapping.

## API Endpoints

| Endpoint                          | Method | Description                                   |
| --------------------------------- | ------ | --------------------------------------------- |
| `/api/v1/ceo/metrics`             | GET    | Returns all 12 metrics with values and alerts |
| `/api/v1/ceo/metrics/definitions` | GET    | Returns metric definitions and thresholds     |
| `/api/v1/ceo/metrics/{category}`  | GET    | Returns metrics for a specific category       |

## The 12 CEO Metrics

### PIPELINE (3 Metrics) - Card Row 1

| #   | Metric Key                    | Display Name        | Description                                                              | Unit     | Card Position      |
| --- | ----------------------------- | ------------------- | ------------------------------------------------------------------------ | -------- | ------------------ |
| 1   | `pipeline_total_aum`          | **Total AUM**       | Total Assets Under Management - sum of all judgment amounts in portfolio | Currency | Top-left hero card |
| 2   | `pipeline_active_cases`       | **Active Cases**    | Count of cases not in closed/collected status                            | Count    | Row 1, Col 2       |
| 3   | `pipeline_intake_velocity_7d` | **Intake Velocity** | New judgments added in last 7 days                                       | Count    | Row 1, Col 3       |

### QUALITY (2 Metrics) - Card Row 2 Left

| #   | Metric Key                     | Display Name           | Description                                                      | Unit       | Card Position |
| --- | ------------------------------ | ---------------------- | ---------------------------------------------------------------- | ---------- | ------------- |
| 4   | `quality_batch_success_rate`   | **Batch Success Rate** | % of CSV import batches that completed successfully (30d window) | Percentage | Row 2, Col 1  |
| 5   | `quality_data_integrity_score` | **Data Integrity**     | % of judgment records with all required fields populated         | Percentage | Row 2, Col 2  |

### ENFORCEMENT (3 Metrics) - Card Row 2 Right + Row 3 Left

| #   | Metric Key                  | Display Name           | Description                                  | Unit  | Card Position |
| --- | --------------------------- | ---------------------- | -------------------------------------------- | ----- | ------------- |
| 6   | `enforcement_active_cases`  | **Active Enforcement** | Enforcement cases currently in progress      | Count | Row 2, Col 3  |
| 7   | `enforcement_stalled_cases` | **Stalled Cases**      | Cases with no activity in 14+ days           | Count | Row 3, Col 1  |
| 8   | `enforcement_actions_7d`    | **Actions (7d)**       | Enforcement actions completed in last 7 days | Count | Row 3, Col 2  |

### REVENUE (2 Metrics) - Card Row 3 Right

| #   | Metric Key              | Display Name          | Description                                     | Unit       | Card Position |
| --- | ----------------------- | --------------------- | ----------------------------------------------- | ---------- | ------------- |
| 9   | `revenue_collected_30d` | **Collections (30d)** | Amount collected from judgments in last 30 days | Currency   | Row 3, Col 3  |
| 10  | `revenue_recovery_rate` | **Recovery Rate**     | Historical % of judgment amounts collected      | Percentage | Row 4, Col 1  |

### RISK (2 Metrics) - Card Row 4

| #   | Metric Key            | Display Name       | Description                                 | Unit  | Card Position |
| --- | --------------------- | ------------------ | ------------------------------------------- | ----- | ------------- |
| 11  | `risk_queue_failures` | **Queue Failures** | Failed jobs in operations queue             | Count | Row 4, Col 2  |
| 12  | `risk_aging_90d`      | **Aging Cases**    | Cases older than 90 days without resolution | Count | Row 4, Col 3  |

---

## Alert Thresholds

### Color Coding

- 🟢 **Green**: Healthy - no action needed
- 🟡 **Yellow**: Warning - monitor closely
- 🔴 **Red**: Critical - immediate attention required

### Threshold Definitions

| Metric                         | Green      | Yellow     | Red       |
| ------------------------------ | ---------- | ---------- | --------- |
| `pipeline_total_aum`           | ≥ $100,000 | < $100,000 | < $50,000 |
| `pipeline_intake_velocity_7d`  | ≥ 10       | < 10       | < 5       |
| `quality_batch_success_rate`   | ≥ 95%      | < 95%      | < 90%     |
| `quality_data_integrity_score` | ≥ 98%      | < 98%      | < 95%     |
| `enforcement_stalled_cases`    | ≤ 10       | > 10       | > 25      |
| `enforcement_actions_7d`       | ≥ 5        | < 5        | < 2       |
| `revenue_recovery_rate`        | ≥ 5%       | < 5%       | < 2%      |
| `risk_queue_failures`          | ≤ 5        | > 5        | > 10      |
| `risk_aging_90d`               | ≤ 50       | > 50       | > 100     |

---

## SQL Sources

### View: `analytics.v_ceo_12_metrics`

Returns a single row with all 12 metrics plus alert status for each.

### RPC Function: `public.ceo_12_metrics()`

Wrapper function for Supabase client consumption:

```sql
SELECT * FROM public.ceo_12_metrics();
```

### Definition Table: `analytics.ceo_metric_definitions`

Contains metadata for each metric (for dashboard configuration):

- `metric_key` - Unique identifier
- `category` - Pipeline/Quality/Enforcement/Revenue/Risk
- `display_name` - Human-readable name
- `description` - Full description
- `unit` - currency/count/percentage
- `refresh_rate` - real-time
- `warning_threshold` - Yellow alert threshold
- `critical_threshold` - Red alert threshold
- `dashboard_card_position` - Card ordering (1-12)

---

## Refresh Rates

All 12 metrics are **real-time** (computed on-demand from underlying tables):

| Source Table                 | Metrics Derived |
| ---------------------------- | --------------- |
| `public.judgments`           | 1, 2, 3, 5, 12  |
| `ops.ingest_batches`         | 4               |
| `public.enforcement_cases`   | 6, 7, 9, 10     |
| `public.enforcement_actions` | 8               |
| `ops.job_queue`              | 11              |

---

## Dashboard Card Layout

```
┌────────────────────────────────────────────────────────────────┐
│                    CEO EXECUTIVE DASHBOARD                       │
├──────────────────┬─────────────────┬─────────────────┬──────────┤
│   TOTAL AUM      │  ACTIVE CASES   │ INTAKE VELOCITY │          │
│   $1,234,567     │     156         │    24/week      │ PIPELINE │
│   🟢 healthy    │                 │   🟢 healthy    │          │
├──────────────────┼─────────────────┼─────────────────┼──────────┤
│  BATCH SUCCESS   │ DATA INTEGRITY  │ ACTIVE ENFORCE  │          │
│     98.5%        │     99.2%       │      45         │ QUALITY  │
│   🟢 healthy    │   🟢 healthy    │                 │          │
├──────────────────┼─────────────────┼─────────────────┼──────────┤
│  STALLED CASES   │ ACTIONS (7d)    │ COLLECTIONS 30d │          │
│       8          │      12         │   $45,678       │ ENFORCE  │
│   🟢 healthy    │   🟢 healthy    │                 │ REVENUE  │
├──────────────────┼─────────────────┼─────────────────┼──────────┤
│  RECOVERY RATE   │ QUEUE FAILURES  │  AGING 90d+     │          │
│      8.5%        │       2         │      28         │  RISK    │
│   🟢 healthy    │   🟢 healthy    │   🟢 healthy    │          │
└──────────────────┴─────────────────┴─────────────────┴──────────┘
```

---

## React Component Structure

```typescript
// types/ceoMetrics.ts
interface CEO12Metrics {
  pipeline: {
    total_aum: number;
    active_cases: number;
    intake_velocity_7d: number;
    aum_alert: "green" | "yellow" | "red";
    velocity_alert: "green" | "yellow" | "red";
  };
  quality: {
    batch_success_rate: number;
    data_integrity_score: number;
    batch_alert: "green" | "yellow" | "red";
    integrity_alert: "green" | "yellow" | "red";
  };
  enforcement: {
    active_cases: number;
    stalled_cases: number;
    actions_7d: number;
    stalled_alert: "green" | "yellow" | "red";
    actions_alert: "green" | "yellow" | "red";
  };
  revenue: {
    collected_30d: number;
    recovery_rate: number;
    recovery_alert: "green" | "yellow" | "red";
  };
  risk: {
    queue_failures: number;
    aging_90d: number;
    queue_alert: "green" | "yellow" | "red";
    aging_alert: "green" | "yellow" | "red";
  };
  generated_at: string;
  metric_version: string;
}

// components/CEOMetricCard.tsx
interface CEOMetricCardProps {
  metricKey: string;
  displayName: string;
  value: number | string;
  unit: "currency" | "count" | "percentage";
  alert: "green" | "yellow" | "red";
  category: string;
}
```

---

## API Response Example

```json
{
  "pipeline": {
    "total_aum": 1234567.89,
    "active_cases": 156,
    "intake_velocity_7d": 24,
    "aum_alert": "green",
    "velocity_alert": "green"
  },
  "quality": {
    "batch_success_rate": 98.5,
    "data_integrity_score": 99.2,
    "batch_alert": "green",
    "integrity_alert": "green"
  },
  "enforcement": {
    "active_cases": 45,
    "stalled_cases": 8,
    "actions_7d": 12,
    "stalled_alert": "green",
    "actions_alert": "green"
  },
  "revenue": {
    "collected_30d": 45678.0,
    "recovery_rate": 8.5,
    "recovery_alert": "green"
  },
  "risk": {
    "queue_failures": 2,
    "aging_90d": 28,
    "queue_alert": "green",
    "aging_alert": "green"
  },
  "generated_at": "2025-12-16T17:15:00Z",
  "metric_version": "1.0"
}
```

---

## Implementation Files

| File                                                    | Purpose                            |
| ------------------------------------------------------- | ---------------------------------- |
| `supabase/migrations/20251216171329_ceo_12_metrics.sql` | SQL view + RPC + definitions table |
| `backend/routers/ceo_metrics.py`                        | FastAPI endpoints                  |
| `docs/ceo_12_metrics_dashboard.md`                      | This documentation                 |

---

## Usage

### Python (FastAPI)

```python
from backend.routers.ceo_metrics import CEO12Metrics

@router.get("/dashboard")
async def get_dashboard() -> CEO12Metrics:
    return await get_ceo_12_metrics(auth)
```

### JavaScript/TypeScript (Dashboard)

```typescript
const response = await fetch("/api/v1/ceo/metrics");
const metrics: CEO12Metrics = await response.json();

// Display with alert colors
const aumColor = metrics.pipeline.aum_alert; // 'green' | 'yellow' | 'red'
```

### Supabase RPC (Direct)

```typescript
const { data, error } = await supabase.rpc("ceo_12_metrics");
```
